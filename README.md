## Lightpanda + Playwright (CDP) + Streamlit

This app:
- Runs a Lightpanda CDP server on `localhost:9222` (auto-start on Linux, including Streamlit Community Cloud).
- Connects to a CDP endpoint via Playwright: `playwright.chromium.connect_over_cdp("ws://127.0.0.1:9222")`
- Lets you input a URL and click **Go** to fetch the page **title**.

Note: if the CDP server does not accept a `ws://...` endpoint, switch to `http://127.0.0.1:9222` in the sidebar.

Screenshot note: taking a screenshot requires the CDP command `Page.captureScreenshot`. Some CDP servers (including Lightpanda at the moment) do not implement it, so **Show screenshot** may fail. If you need screenshots, use Chrome/Chromium started with `--remote-debugging-port=9222` and point the app to that endpoint.

Project structure:
- Source code lives in `src/lightpanda_local/`
- `streamlit_app.py` and `init_lightpanda.py` in the repo root are small shims/launchers to make local runs and Streamlit Cloud deployments easier

### Run locally

1) Install dependencies:

`pip install -r requirements.txt`

2) (Optional) Start Lightpanda manually:

`python init_lightpanda.py --host 127.0.0.1 --port 9222 --wait`

3) Run Streamlit:

`streamlit run streamlit_app.py`

### Deploy to Streamlit Community Cloud

Important files:
- `streamlit_app.py` (default entrypoint on Streamlit Cloud)
- `requirements.txt`
- `runtime.txt`

Lightpanda is auto-downloaded when you click **Go** (Linux only) and started as:

`lightpanda serve --host 127.0.0.1 --port 9222`

If you already run Lightpanda yourself, disable **Autostart Lightpanda (Linux)** in the sidebar or set `LIGHTPANDA_CDP_WS`.
