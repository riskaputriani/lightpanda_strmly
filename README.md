## Playwright + Chrome/Chromium + Streamlit

A minimal Streamlit UI that uses **Playwright** with **Google Chrome** (if available) or the bundled **Chromium** to:
- Scrape the page **title** of any URL you enter.
- (Optional) take a full-page **screenshot**.
- (Optional) download the page **HTML**.

### Run locally

1) Install Python deps:

```bash
pip install -r requirements.txt
```

2) Install the Playwright-managed Chromium browser (first run only, no sudo):

```bash
PLAYWRIGHT_BROWSERS_PATH=.pw-browsers python -m playwright install chromium
```

3) Run Streamlit:

```bash
streamlit run streamlit_app.py
```

### Notes

- On Streamlit Cloud/Linux, `install_google_chrome()` tries to use system Chrome; if not available, the app relies on Playwright's bundled Chromium.
- The app always opens pages headlessly via Playwright and returns the title. Checkboxes let you also fetch a screenshot and/or HTML.
- On non-root Linux environments where `apt` is unavailable, the system Chrome install step is skipped; the app falls back to Playwright's bundled Chromium (ensure `PLAYWRIGHT_BROWSERS_PATH=.pw-browsers python -m playwright install chromium` has been run).
- If you cannot install system Chrome, download the Playwright-managed Chromium into a local folder (no sudo) with: `PLAYWRIGHT_BROWSERS_PATH=.pw-browsers python -m playwright install chromium`.
