import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from components.cookies import sanitize_cookies
from components.page_fetcher import fetch_page
from components.proxy_service import find_best_proxy
from components.session_state import init_session_state
from components.solver_runner import run_solver
from components.url_utils import ensure_scheme

# --- App ---
st.set_page_config(page_title="Playwright URL Reader", layout="centered")
init_session_state()

st.title("Ambil Data dari URL dengan Playwright")
st.caption("Tekan tombol 'Go' untuk mengambil data dari URL.")

# --- Sidebar ---
st.sidebar.header("Opsi")
take_screenshot = st.sidebar.checkbox("Ambil screenshot", value=False)
get_html = st.sidebar.checkbox("Get HTML", value=False)
use_solver = st.sidebar.checkbox("Gunakan solver Cloudflare jika perlu", value=True)

st.sidebar.header("Proxy")
proxy_input = st.sidebar.text_input("Proxy Address", value=st.session_state.proxy_address)

if st.sidebar.button("Cari proxy otomatis"):
    with st.spinner("Mencari & menguji proxy..."):
        best_proxy = find_best_proxy()
        if best_proxy:
            st.session_state.proxy_address = best_proxy["proxy"]
            st.session_state.proxy_country = best_proxy["country"]
            st.rerun()
        else:
            st.sidebar.error("Tidak ada proxy yang berfungsi ditemukan.")
            st.session_state.proxy_address = ""
            st.session_state.proxy_country = ""

if st.session_state.proxy_country:
    st.sidebar.info(f"Negara Proxy: {st.session_state.proxy_country}")

st.sidebar.header("Overrides")
user_agent_input = st.sidebar.text_input("User Agent")
cookie_json_text_input = st.sidebar.text_area(
    "Cookies (JSON Array)", value=st.session_state.cookie_text
)
cookie_file = st.sidebar.file_uploader("Upload cookies.json", type=["json"])

# --- Main Page ---
url_input = st.text_input("Masukkan URL yang ingin diambil datanya", value="")

if st.button("Go"):
    normalized_url = ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
    else:
        # --- Data Extraction from UI ---
        loaded_cookies = None
        raw_json_data = None

        if cookie_file:
            try:
                raw_json_data = json.load(cookie_file)
            except Exception as err:
                st.error(f"Gagal membaca file cookie: {err}")
                st.stop()
        elif cookie_json_text_input:
            try:
                raw_json_data = json.loads(cookie_json_text_input)
            except json.JSONDecodeError:
                st.error("JSON cookie di text area tidak valid.")
                st.stop()

        if raw_json_data:
            if isinstance(raw_json_data, list):
                loaded_cookies = raw_json_data
            else:
                st.error(
                    "Format cookie JSON tidak valid. Harus berupa array (daftar) objek cookie."
                )
                st.stop()

            st.session_state.cookie_text = json.dumps(raw_json_data, indent=2)

        # --- Determine Final Settings ---
        final_proxy = proxy_input if proxy_input else None
        final_user_agent = user_agent_input if user_agent_input else None

        # --- Main Orchestration Logic ---
        with st.spinner("Mengambil halaman..."):
            result = fetch_page(
                normalized_url,
                take_screenshot=take_screenshot,
                get_html=get_html,
                proxy=final_proxy,
                cookies=loaded_cookies,
                user_agent=final_user_agent,
            )

        if use_solver and result.get("status") == "cloudflare_challenge":
            solver_cookies = run_solver(normalized_url, final_proxy)
            if not solver_cookies:
                st.error("Cloudflare solver gagal mendapatkan cookies.")
                st.stop()

            sanitized_cookies = sanitize_cookies(solver_cookies)
            st.session_state.cookie_text = json.dumps(sanitized_cookies, indent=2)
            st.success("Solver berhasil mendapatkan cookies. Mengambil ulang halaman...")

            st.rerun()

        # --- Display Results ---
        if result.get("status") == "ok":
            st.success("Operasi Selesai!")
            st.subheader("Title")
            st.code(result.get("title", "-"))

            if "screenshot" in result:
                st.subheader("Screenshot")
                st.image(result["screenshot"])
                st.download_button(
                    "Download screenshot",
                    data=result["screenshot"],
                    file_name="screenshot.png",
                    mime="image/png",
                )

            if "html" in result:
                st.subheader("HTML Content")
                st.code(result["html"], language="html")
                st.download_button(
                    "Download HTML",
                    data=result["html"],
                    file_name="page.html",
                    mime="text/html",
                )

        elif result.get("status") == "cloudflare_challenge":
            st.error("Gagal melewati Cloudflare. Coba aktifkan solver jika belum aktif.")

        else:
            st.error(f"Gagal mengambil halaman: {result.get('message', 'Unknown error')}")

