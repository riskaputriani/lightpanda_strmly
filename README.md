## Playwright + Google Chrome + Streamlit

A minimal Streamlit UI that uses **Playwright** with **Google Chrome** to:
- Scrape the page **title** of any URL you enter.
- (Optional) take a full-page **screenshot**.
- (Optional) download the page **HTML**.

### Run locally

1) Install Python deps:

```bash
pip install -r requirements.txt
```

2) Install the Chrome browser for Playwright (first run only):

```bash
python -m playwright install chrome
```

3) Run Streamlit:

```bash
streamlit run streamlit_app.py
```

### Notes

- On Streamlit Cloud/Linux, `install_google_chrome()` ensures Google Chrome is present. Locally, make sure Chrome is installed or Playwright's `chrome` channel is available.
- The app always opens pages headlessly via Playwright and returns the title. Checkboxes let you also fetch a screenshot and/or HTML.
- On non-root Linux environments where `apt` is unavailable, the Chrome install step is skipped; the app will fall back to Playwright's bundled Chrome channel (ensure `python -m playwright install chrome` has been run).
