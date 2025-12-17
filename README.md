## Lightpanda + Playwright (CDP) + Streamlit

App ini:
- Menjalankan Lightpanda CDP server di `localhost:9222` (autostart di Linux, termasuk Streamlit Cloud).
- Menggunakan Playwright untuk connect via CDP: `playwright.chromium.connect_over_cdp("ws://127.0.0.1:9222")`
- Input URL + tombol **Go** untuk ambil **title** halaman.

Catatan: kalau endpoint `ws://...` tidak diterima oleh server CDP, coba ganti jadi `http://127.0.0.1:9222` lewat sidebar.

Struktur project:
- Source code ada di `src/lightpanda_local/`
- `streamlit_app.py` dan `init_lightpanda.py` di root adalah shim/launcher supaya gampang dijalankan di lokal dan Streamlit Cloud

### Jalankan lokal

1) Install dependencies:

`pip install -r requirements.txt`

2) (Opsional) Start Lightpanda manual:

`python init_lightpanda.py --host 127.0.0.1 --port 9222 --wait`

3) Jalankan Streamlit:

`streamlit run streamlit_app.py`

### Deploy ke Streamlit Community Cloud

File penting:
- `streamlit_app.py` (entrypoint default di Streamlit Cloud)
- `requirements.txt`
- `runtime.txt`

Lightpanda akan di-download otomatis saat tombol **Go** ditekan (Linux only) dan dijalankan dengan:

`lightpanda serve --host 127.0.0.1 --port 9222`

Kalau kamu sudah menjalankan Lightpanda sendiri, matikan toggle **Autostart Lightpanda (Linux)** di sidebar atau set env `LIGHTPANDA_CDP_WS`.
