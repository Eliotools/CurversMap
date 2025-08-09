from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from typing import Any, Dict, List

import folium
import requests


MAX_WORKERS = int(os.getenv("MAX_WORKERS", "32"))
IDS_FILE = os.getenv("IDS_FILE", "culvers_ids.txt")
OUTPUT_JSON = os.getenv("OUTPUT_JSON", os.path.join("html", "culvers_details.json"))
OUTPUT_HTML = os.getenv("OUTPUT_HTML", os.path.join("html", "main.html"))
LAST_REFRESH_PATH = os.path.join("html", "last_refresh.json")


def _today_string() -> str:
    return datetime.date.today().isoformat()


def _get_session() -> requests.Session:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_culvers_details(session: requests.Session, olo_id: str, timeout_seconds: int = 15) -> Dict[str, Any]:
    url = f"https://www.culvers.com/api/restaurants/getDetails?oloID={olo_id}"
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def load_ids(path: str) -> List[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"IDs file not found: {path}")
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]


def build_details_json(ids: List[str]) -> List[Dict[str, Any]]:
    session = _get_session()

    simplified_results: List[Dict[str, Any]] = []

    def _worker(olo_id: str):
        try:
            raw = fetch_culvers_details(session, olo_id)
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
            # Skip failed IDs; this mirrors server behavior that collects timeouts separately
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_worker, str(olo_id)) for olo_id in ids]
        concurrent.futures.wait(futures)

    return simplified_results


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def build_map_html(details_json_path: str, output_html_path: str) -> None:
    with open(details_json_path, "r") as f:
        locations = json.load(f)

    center_lat = 39.8283
    center_lng = -98.5795
    m = folium.Map(location=[center_lat, center_lng], zoom_start=5)

    for loc in locations:
        lat = loc.get("lat")
        lng = loc.get("lng")
        address = loc.get("address", "No address")
        flavors = loc.get("flavors", "No flavor")
        popup_text = f"{address}<br>Flavor: {flavors}"
        folium.Marker(
            location=[lat, lng],
            popup=popup_text,
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(m)

    m.save(output_html_path)


def write_index_redirect(html_dir: str) -> None:
    # Ensure the site root loads the map without manual URL suffix
    os.makedirs(html_dir, exist_ok=True)
    index_path = os.path.join(html_dir, "index.html")
    content = """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta http-equiv=\"refresh\" content=\"0; url=main.html\" />
    <title>Redirecting…</title>
  </head>
  <body>
    <p>Loading map… If you are not redirected automatically, <a href=\"main.html\">open the map</a>.</p>
  </body>
  </html>
""".strip()
    with open(index_path, "w") as f:
        f.write(content)


def write_last_refresh(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"date": _today_string()}, f)


def main() -> None:
    ids = load_ids(IDS_FILE)
    results = build_details_json(ids)
    save_json(OUTPUT_JSON, results)
    build_map_html(OUTPUT_JSON, OUTPUT_HTML)
    write_index_redirect(os.path.dirname(OUTPUT_HTML))
    write_last_refresh(LAST_REFRESH_PATH)


if __name__ == "__main__":
    main()

import requests
import json
import os
import threading
import concurrent.futures


def save_culvers_details_to_file(oloID, details):
    with open(f"culvers_details_{oloID}.json", "w") as file:
        json.dump(details, file, indent=4)


_thread_local = threading.local()
timeout = []
results = []

def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return _thread_local.session


def get_culvers_details(oloID):
    print(oloID)
    url = f"https://www.culvers.com/api/restaurants/getDetails?oloID={oloID}"
    try:
        session = _get_session()
        response = session.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("data", {}).get("restaurant", {}).get("getRestaurantDetails") is None:
            return None
        details = data["data"]["restaurant"]["getRestaurantDetails"]
        res = {
            "flavors": details["flavors"][0]["name"],
            "oloID": oloID,
            "address": f"{details['streetAddress']} {details['city']} {details['state']}",
            "lat" : details.get("latitude"),
            "lng" : details.get("longitude"),
        }
        return res
    except requests.RequestException as e:
        print(f"Error fetching details for oloID {oloID}: {e}")
        timeout.append(oloID)
        return None

def _run_concurrently(ids : list[int], max_workers: int) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(get_culvers_details, olo_id) for olo_id in ids]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res is not None:
                results.append(res)
            # Ensure exceptions are surfaced
            _ = future.result()

with open("culvers_ids.txt", "r") as f:
    ids = [line.strip() for line in f if line.strip()]
if __name__ == "__main__":
    workers = MAX_WORKERS
    _run_concurrently(ids, workers)
    print(timeout)
    

# Save all results to a single file
with open("culvers_details.json", "w") as out_f:
    json.dump(results, out_f, indent=2)


