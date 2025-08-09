from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import threading
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS


app = Flask(__name__, static_folder="html", static_url_path="")
CORS(app)  # Enables Access-Control-Allow-Origin: *


_thread_local = threading.local()
_refresh_lock = threading.Lock()

# Stores the last day we refreshed data (YYYY-MM-DD)
LAST_REFRESH_PATH = os.path.join("html", "last_refresh.json")


def _today_string() -> str:
    return datetime.date.today().isoformat()


def _read_last_refresh_date() -> Optional[str]:
    if not os.path.exists(LAST_REFRESH_PATH):
        return None
    try:
        with open(LAST_REFRESH_PATH, "r") as f:
            payload = json.load(f)
        return payload.get("date")
    except Exception:
        return None


def _write_last_refresh_date(date_str: str) -> None:
    os.makedirs(os.path.dirname(LAST_REFRESH_PATH), exist_ok=True)
    with open(LAST_REFRESH_PATH, "w") as f:
        json.dump({"date": date_str}, f)


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return _thread_local.session


def fetch_culvers_details(olo_id: str, timeout_seconds: int = 15) -> Dict[str, Any]:
    url = f"https://www.culvers.com/api/restaurants/getDetails?oloID={olo_id}"
    session = _get_session()
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


@app.get("/api/details")
def proxy_single_details():
    olo_id = request.args.get("oloID")
    if not olo_id:
        return jsonify({"error": "Missing required query param 'oloID'"}), 400
    try:
        data = fetch_culvers_details(olo_id)
        return jsonify(data), 200
    except requests.HTTPError as http_err:
        return jsonify({"error": str(http_err), "oloID": olo_id}), 502
    except requests.RequestException as req_err:
        return jsonify({"error": str(req_err), "oloID": olo_id}), 504


@app.post("/api/batch")
def proxy_batch_details():
    payload = request.get_json(silent=True) or {}
    ids: List[str] = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Provide JSON body { 'ids': [""125984"", ...] }"}), 400

    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    def _worker(olo_id: str):
        try:
            data = fetch_culvers_details(olo_id)
            results[olo_id] = data
        except Exception as exc:  # noqa: BLE001 - return error to client
            errors[olo_id] = str(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.getenv("MAX_WORKERS", "32"))) as executor:
        futures = [executor.submit(_worker, str(olo_id)) for olo_id in ids]
        concurrent.futures.wait(futures)

    return jsonify({"results": results, "errors": errors}), 200


@app.post("/api/save_all")
def save_all_to_file():
    ids_file = request.args.get("idsFile", "culvers_ids.txt")
    output_file = request.args.get("outputFile", os.path.join("html", "culvers_details.json"))
    if not os.path.exists(ids_file):
        return jsonify({"error": f"IDs file not found: {ids_file}"}), 400

    with open(ids_file, "r") as f:
        ids = [line.strip() for line in f if line.strip()]

    simplified_results: List[Dict[str, Any]] = []
    timeouts: List[str] = []

    def _worker(olo_id: str):
        try:
            raw = fetch_culvers_details(olo_id)
            details = raw.get("data", {}).get("restaurant", {}).get("getRestaurantDetails")
            if not details:
                return
            simplified_results.append({
                "flavors": details.get("flavors", [{}])[0].get("name"),
                "oloID": olo_id,
                "address": f"{details.get('streetAddress', '')} {details.get('city', '')} {details.get('state', '')}".strip(),
                "lat": details.get("latitude"),
                "lng": details.get("longitude"),
            })
        except Exception:
            timeouts.append(olo_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.getenv("MAX_WORKERS", "32"))) as executor:
        futures = [executor.submit(_worker, str(olo_id)) for olo_id in ids]
        concurrent.futures.wait(futures)

    with open(output_file, "w") as out_f:
        json.dump(simplified_results, out_f, indent=2)

    return jsonify({
        "saved": True,
        "count": len(simplified_results),
        "outputFile": output_file,
        "timeouts": timeouts,
    }), 200

def get_map(force: bool = False):
    # Check if the map file already exists; if so, do nothing unless forced
    import os
    map_path = os.path.join('html', 'main.html')
    if (not force) and os.path.exists(map_path):
        return
    import json
    import folium

    # Load the Culver's details from the JSON file
    if not os.path.exists(os.path.join('html', 'culvers_details.json')):
        save_all_to_file()

    with open('html/culvers_details.json', 'r') as f:
        locations = json.load(f)
    # Calculate the center of the US for the initial map view
    center_lat = 39.8283
    center_lng = -98.5795

    # Create a folium map centered on the US
    m = folium.Map(location=[center_lat, center_lng], zoom_start=5)

    # Add a pin for every location
    for loc in locations:
        lat = loc.get('lat')
        lng = loc.get('lng')
        address = loc.get('address', 'No address')
        flavors = loc.get('flavors', 'No flavor')
        popup_text = f"{address}<br>Flavor: {flavors}"
        folium.Marker(
            location=[lat, lng],
            popup=popup_text,
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)

    # Save the map to an HTML file and display a message
    m.save('html/main.html')

@app.get("/")
def serve_index():
    # Daily refresh: if it's a new day, rebuild data and map
    today = _today_string()
    last_refresh = _read_last_refresh_date()

    force_rebuild = last_refresh != today
    if force_rebuild:
        with _refresh_lock:
            # Re-check after acquiring the lock to avoid duplicate work
            last_refresh_locked = _read_last_refresh_date()
            if last_refresh_locked != today:
                # Recreate data and map
                save_all_to_file()
                _write_last_refresh_date(today)
                get_map(force=True)
            else:
                get_map()
    else:
        get_map()

    return app.send_static_file("main.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=True)

