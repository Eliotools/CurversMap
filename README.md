## CurversMap

Builds and deploys an interactive Folium map of Culver's locations and flavors. The map is generated from a list of Olo IDs, rendered as `html/main.html`, and published to GitHub Pages daily.

### Features

- **Daily auto-build and deploy**: GitHub Actions runs every day at 10:00 UTC and on manual trigger.
- **Filter by flavor**: Markers are grouped by flavor as layers; use the Layers control to toggle flavors on/off.

### Requirements

- Python 3.11+ (matches CI)
- pip

### Project structure

- `main.py`: Builds `html/culvers_details.json` and `html/main.html`
- `culvers_ids.txt`: Input Olo IDs (one per line)
- `html/`: Output folder for JSON and HTML
- `.github/workflows/deploy.yml`: GitHub Pages deployment workflow

### Setup (local)

1. Create and activate a virtual environment (optional):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Build the data and map:

   ```bash
   python main.py
   ```

   Outputs:

   - `html/culvers_details.json`
   - `html/main.html`
   - `html/index.html` (redirects to `main.html`)
   - `html/last_refresh.json`

4. Open the map locally by opening `html/index.html` in your browser.
