import json
import os
from datetime import datetime
from typing import List, Optional

import streamlit as st

from components.cookies import sanitize_cookies
from components.page_fetcher import fetch_page
from components.session_state import init_session_state
from components.solver_runner import run_solver
from components.url_utils import ensure_scheme

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


st.set_page_config(page_title="Scrape + AI Chat", layout="centered")
init_session_state()

st.title("Scrape + Tanya AI")
st.caption("Ambil halaman (bisa lewat solver) lalu tanya apa saja lewat chat.")


# --- Helpers -----------------------------------------------------------------
def _load_cookies_from_inputs(file, text_value: str) -> Optional[List[dict]]:
    """Load cookies either from upload or text area."""
    raw_json_data = None
    if file:
        raw_json_data = json.load(file)
    elif text_value:
        raw_json_data = json.loads(text_value)

    if raw_json_data:
        if not isinstance(raw_json_data, list):
            raise ValueError(
                "Format cookie JSON tidak valid. Harus berupa array (daftar) objek cookie."
            )
        return raw_json_data
    return None


def _seed_system_message(title: str, html: Optional[str]) -> None:
    """Create a system prompt containing scraped content."""
    snippet = (html or "")[:6000] if html else "HTML tidak diminta."
    context = (
        "Kamu adalah asisten yang menjawab permintaan berdasarkan hasil scrape.\n"
        f"Judul halaman: {title or '-'}\n"
        f"Cuplikan HTML:\n{snippet}"
    )
    st.session_state.ai_messages = [{"role": "system", "content": context}]


def _get_openai_client() -> OpenAI:
    if OpenAI is None:
        raise RuntimeError("Paket 'openai' belum terpasang. Install dulu untuk memakai chat.")

    api_key = st.session_state.get("ai_api_key") or os.getenv("OPENAI_API_KEY")
    base_url = st.session_state.get("ai_base_url") or os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("API key belum diisi. Set di form LLM settings.")

    return OpenAI(api_key=api_key, base_url=base_url or None)


# --- Sidebar: scraping options -----------------------------------------------
st.sidebar.header("Scraping Options")
use_solver = st.sidebar.checkbox("Gunakan solver Cloudflare jika perlu", value=True)
take_screenshot = st.sidebar.checkbox("Ambil screenshot", value=False)
get_html = st.sidebar.checkbox("Get HTML", value=True)

st.sidebar.header("Proxy & Override")
proxy_input = st.sidebar.text_input("Proxy Address", value=st.session_state.proxy_address)
user_agent_input = st.sidebar.text_input("User Agent", value=st.session_state.user_agent)
cookie_text_input = st.sidebar.text_area(
    "Cookies (JSON Array)", value=st.session_state.cookie_text, height=150
)
cookie_file = st.sidebar.file_uploader("Upload cookies.json", type=["json"])

st.session_state.user_agent = user_agent_input
st.session_state.proxy_address = proxy_input


# --- Main layout -------------------------------------------------------------
url_input = st.text_input("Masukkan URL", value="", placeholder="https://contoh.com/halaman")

col_btn, col_status = st.columns([1, 2])
if col_btn.button("Fetch & Seed Chat"):
    normalized_url = ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
        st.stop()

    # Parse cookies
    loaded_cookies: Optional[List[dict]] = None
    try:
        loaded_cookies = _load_cookies_from_inputs(cookie_file, cookie_text_input)
    except Exception as err:
        st.error(f"Gagal membaca cookie: {err}")
        st.stop()

    if loaded_cookies:
        st.session_state.cookie_text = json.dumps(loaded_cookies, indent=2)

    final_proxy = proxy_input or None
    final_user_agent = user_agent_input or None

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
        solver_result = run_solver(normalized_url, final_proxy)
        solver_cookies: List[dict] = []
        solver_user_agent: Optional[str] = None
        if isinstance(solver_result, dict):
            solver_cookies = solver_result.get("cookies") or []
            solver_user_agent = solver_result.get("user_agent") or final_user_agent
        elif solver_result:
            solver_cookies = solver_result

        if not solver_cookies:
            st.error("Cloudflare solver gagal mendapatkan cookies.")
            st.stop()

        sanitized = sanitize_cookies(solver_cookies)
        st.session_state.cookie_text = json.dumps(sanitized, indent=2)
        if solver_user_agent:
            st.session_state.user_agent = solver_user_agent

        st.success("Solver berhasil. Mengambil ulang halaman dengan cookies + UA solver...")
        with st.spinner("Mengambil ulang..."):
            result = fetch_page(
                normalized_url,
                take_screenshot=take_screenshot,
                get_html=get_html,
                proxy=final_proxy,
                cookies=sanitized,
                user_agent=solver_user_agent or final_user_agent,
            )

    if result.get("status") != "ok":
        st.error(f"Gagal mengambil halaman: {result.get('message', 'Unknown error')}")
        st.stop()

    # Save scrape result
    st.session_state.ai_scrape_result = result
    st.session_state.ai_scraped_url = normalized_url
    st.session_state.ai_scraped_at = datetime.utcnow().isoformat()

    _seed_system_message(result.get("title", "-"), result.get("html"))
    st.success("Scrape berhasil. Chat sudah disiapkan dengan konteks halaman ini.")


# --- Display last scrape summary --------------------------------------------
if st.session_state.get("ai_scrape_result"):
    last = st.session_state.ai_scrape_result
    st.info(
        f"Halaman terakhir: {st.session_state.get('ai_scraped_url', '-')}\n\n"
        f"Judul: {last.get('title', '-')}\n"
        f"Waktu scrape (UTC): {st.session_state.get('ai_scraped_at', '-')}"
    )
    if take_screenshot and "screenshot" in last:
        st.image(last["screenshot"], caption="Screenshot (terakhir)")


# --- LLM settings ------------------------------------------------------------
st.subheader("LLM Settings")
default_model = st.session_state.get("ai_model", "gpt-3.5-turbo")
st.session_state.ai_model = st.text_input("Model", value=default_model)
st.session_state.ai_api_key = st.text_input(
    "API Key", type="password", value=st.session_state.get("ai_api_key", "")
)
st.session_state.ai_base_url = st.text_input(
    "API Base URL (opsional, untuk Ollama/self-hosted)", value=st.session_state.get("ai_base_url", "")
)


# --- Chat UI ----------------------------------------------------------------
st.subheader("Chat dengan AI")
if "ai_messages" not in st.session_state:
    st.session_state.ai_messages = []

for msg in st.session_state.ai_messages:
    if msg["role"] == "system":
        continue
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


user_prompt = st.chat_input("Tulis pertanyaan atau instruksi terkait hasil scrape...")

if user_prompt:
    if not st.session_state.get("ai_scrape_result"):
        st.error("Belum ada hasil scrape. Jalankan 'Fetch & Seed Chat' dulu.")
        st.stop()

    st.session_state.ai_messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.write(user_prompt)

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=st.session_state.ai_model,
            messages=st.session_state.ai_messages,
            temperature=0,
        )
        answer = response.choices[0].message.content
    except Exception as err:
        answer = f"Gagal memanggil LLM: {err}"

    st.session_state.ai_messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.write(answer)
