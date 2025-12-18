import json
import sys
import re
from pathlib import Path
from io import BytesIO
from typing import Dict, List, Optional

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from components.cookies import sanitize_cookies
from components.page_fetcher import fetch_page
from components.session_state import init_session_state
from components.solver_runner import run_solver
from components.url_utils import ensure_scheme

try:
    import pandas as pd
    from bs4 import BeautifulSoup
    from lxml import html as lxml_html
    from lxml import etree
except Exception as exc:  # pragma: no cover - import guard
    st.error(f"Dependency error: {exc}. Pastikan beautifulsoup4 dan pandas terinstall.")
    raise


st.set_page_config(page_title="Auto Table Scraper", layout="centered")
init_session_state()

st.title("Auto Table Scraper")
st.caption(
    "Masukkan URL, definisikan kolom + selector (XPath/CSS/JS), dan scrap baris berulang otomatis. Unduh JSON/CSV/Excel."
)


# --------------------------------------------------------------------------- #
# Parsing Helpers
# --------------------------------------------------------------------------- #
def _apply_index(selector: str, idx: int) -> str:
    """Ganti nth-child(...) angka pertama dengan idx, atau {i} placeholder."""
    if "{i}" in selector:
        return selector.replace("{i}", str(idx))
    return re.sub(r"nth-child\(\s*\d+\s*\)", f"nth-child({idx})", selector, count=1)


def _exists(selector_type: str, selector: str, soup: BeautifulSoup, tree) -> bool:
    try:
        if selector_type == "xpath":
            nodes = tree.xpath(selector)
            return bool(nodes)
        else:  # css or js treated the same
            return soup.select_one(selector) is not None
    except Exception:
        return False


def _extract_value_with_mode(
    selector_type: str,
    selector: str,
    mode: str,
    attr_name: str,
    soup: BeautifulSoup,
    tree,
) -> str:
    """Ambil nilai teks atau atribut."""
    try:
        if selector_type == "xpath":
            nodes = tree.xpath(selector)
            if not nodes:
                return ""
            node = nodes[0]
            if mode == "attr" and attr_name:
                if hasattr(node, "get"):
                    return str(node.get(attr_name, "")).strip()
                return ""
            if isinstance(node, str):
                return node.strip()
            if hasattr(node, "text_content"):
                return node.text_content().strip()
            return str(node).strip()
        else:  # css or js treated the same
            el = soup.select_one(selector)
            if not el:
                return ""
            if mode == "attr" and attr_name:
                return (el.get(attr_name) or "").strip()
            return el.get_text(" ", strip=True)
    except Exception:
        return ""


def extract_with_mappings(
    html: str,
    mappings: List[Dict[str, str]],
    repeat_selector: Optional[str] = None,
    repeat_type: str = "css",
) -> Optional[pd.DataFrame]:
    """Extract rows berdasarkan daftar mapping kolom + selector (dengan opsi repeat global)."""
    soup = BeautifulSoup(html, "html.parser")
    tree = lxml_html.fromstring(html)

    if not mappings:
        return None

    rows: List[Dict[str, str]] = []

    if not repeat_selector:
        row = {}
        for m in mappings:
            row[m["name"]] = _extract_value_with_mode(
                m.get("selector_type", "css"),
                m.get("selector", ""),
                m.get("value_mode", "text"),
                m.get("attr_name", ""),
                soup,
                tree,
            )
        rows.append(row)
    else:
        idx = 1
        while True:
            repeat_idx = _apply_index(repeat_selector, idx)
            if not _exists(repeat_type, repeat_idx, soup, tree):
                break

            row: Dict[str, str] = {}
            for m in mappings:
                selector_idx = _apply_index(m.get("selector", ""), idx)
                row[m["name"]] = _extract_value_with_mode(
                    m.get("selector_type", "css"),
                    selector_idx,
                    m.get("value_mode", "text"),
                    m.get("attr_name", ""),
                    soup,
                    tree,
                )
            rows.append(row)
            idx += 1

    if not rows:
        return None

    # Normalisasi kolom (ikut urutan input)
    headers = [m["name"] for m in mappings]
    df = pd.DataFrame(rows)
    for h in headers:
        if h not in df.columns:
            df[h] = ""
    return df[headers]


# --------------------------------------------------------------------------- #
# Sidebar options
# --------------------------------------------------------------------------- #
st.sidebar.header("Scraping Options")
use_solver = st.sidebar.checkbox("Gunakan solver Cloudflare jika perlu", value=True)
get_html = True  # mandatory for mapping extraction
take_screenshot = st.sidebar.checkbox("Ambil screenshot (opsional)", value=False)

st.sidebar.header("Proxy & Overrides")
proxy_input = st.sidebar.text_input("Proxy Address", value=st.session_state.proxy_address)
user_agent_input = st.sidebar.text_input("User Agent", value=st.session_state.user_agent)
cookie_text_input = st.sidebar.text_area(
    "Cookies (JSON Array)", value=st.session_state.cookie_text, height=120
)
cookie_file = st.sidebar.file_uploader("Upload cookies.json", type=["json"])

st.session_state.user_agent = user_agent_input
st.session_state.proxy_address = proxy_input


# --------------------------------------------------------------------------- #
# Main form
# --------------------------------------------------------------------------- #
url_input = st.text_input("Masukkan URL", value="", placeholder="https://contoh.com/produk")

st.subheader("Kolom & Selector")
if "column_mappings" not in st.session_state:
    st.session_state.column_mappings = [
        {
            "name": "Products",
            "selector_type": "css",
            "selector": "body > div.main > div > div.products-wrap > div.products > div:nth-child(1) > div.col-8.description > h3 > a",
            "value_mode": "text",
            "attr_name": "",
        }
    ]

if "repeat_selector_shared" not in st.session_state:
    st.session_state.repeat_selector_shared = "body > div.main > div > div.products-wrap > div.products > div:nth-child(1)"
if "repeat_type_shared" not in st.session_state:
    st.session_state.repeat_type_shared = "css"

repeat_cols = st.columns(2)
repeat_selector_shared = repeat_cols[0].text_input(
    "Selector repeat (opsional, satu untuk semua kolom)",
    value=st.session_state.repeat_selector_shared,
    help="Jika diisi, akan diulang dengan nth-child / {i} naik 1,2,3... sampai tidak ada hasil.",
)
repeat_type_shared = repeat_cols[1].selectbox(
    "Tipe selector repeat",
    options=["css", "xpath", "js"],
    index=["css", "xpath", "js"].index(st.session_state.repeat_type_shared),
)
st.session_state.repeat_selector_shared = repeat_selector_shared.strip()
st.session_state.repeat_type_shared = repeat_type_shared

new_mappings: List[Dict[str, str]] = []
for idx, mapping in enumerate(st.session_state.column_mappings):
    st.markdown(f"**Kolom {idx+1}**")
    col1, col2, col3 = st.columns(3)
    name = col1.text_input("Nama kolom", value=mapping.get("name", f"col_{idx+1}"), key=f"name_{idx}")
    selector_type = col2.selectbox(
        "Tipe selector",
        options=["css", "xpath", "js"],
        index=["css", "xpath", "js"].index(mapping.get("selector_type", "css")),
        key=f"type_{idx}",
    )
    selector = col3.text_input(
        "Selector untuk nilai",
        value=mapping.get("selector", ""),
        key=f"selector_{idx}",
        help="Gunakan nth-child(1) atau {i} untuk indeks berulang.",
    )
    val_col, attr_col = st.columns(2)
    value_mode = val_col.selectbox(
        "Ambil apa?",
        options=["text", "attr"],
        index=["text", "attr"].index(mapping.get("value_mode", "text")),
        key=f"value_mode_{idx}",
    )
    attr_name = attr_col.text_input(
        "Nama atribut (jika pilih attr)",
        value=mapping.get("attr_name", ""),
        key=f"attr_name_{idx}",
        help="Contoh: src, href, alt, data-id",
    )
    new_mappings.append(
        {
            "name": name.strip() or f"col_{idx+1}",
            "selector_type": selector_type,
            "selector": selector.strip(),
            "value_mode": value_mode,
            "attr_name": attr_name.strip(),
        }
    )
    st.divider()

if st.button("Tambah kolom"):
    st.session_state.column_mappings.append(
        {
            "name": f"col_{len(st.session_state.column_mappings)+1}",
            "selector_type": "css",
            "selector": "",
            "value_mode": "text",
            "attr_name": "",
        }
    )
    st.rerun()

# Persist updated mappings
st.session_state.column_mappings = new_mappings

if st.button("Extract Table"):
    normalized_url = ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
        st.stop()

    # Parse cookies
    loaded_cookies: Optional[List[dict]] = None
    if cookie_file:
        try:
            loaded_cookies = json.load(cookie_file)
        except Exception as err:
            st.error(f"Gagal membaca file cookie: {err}")
            st.stop()
    elif cookie_text_input:
        try:
            loaded_cookies = json.loads(cookie_text_input)
        except json.JSONDecodeError:
            st.error("JSON cookie di text area tidak valid.")
            st.stop()

    if loaded_cookies:
        if not isinstance(loaded_cookies, list):
            st.error("Format cookie JSON tidak valid. Harus berupa array objek cookie.")
            st.stop()
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

    html_content = result.get("html")
    if not html_content:
        st.error("HTML tidak tersedia dari hasil fetch. Aktifkan Get HTML.")
        st.stop()

    df = extract_with_mappings(
        html_content,
        st.session_state.column_mappings,
        st.session_state.repeat_selector_shared or None,
        st.session_state.repeat_type_shared,
    )
    if df is None or df.empty:
        st.error("Tidak menemukan data dengan mapping/selector yang diberikan. Periksa selector atau repeat.")
        st.stop()

    # Persist extracted data so reruns (e.g., after download) still show the table
    st.session_state.extracted_records = df.to_dict(orient="records")
    st.session_state.extracted_columns = list(df.columns)
    st.session_state.extracted_row_count = len(df)

    # Optional info
    st.info(
        "Gunakan placeholder nth-child(1) atau {i} untuk selector yang berulang. "
        "Selector repeat (satu untuk semua kolom) menentukan elemen list yang akan diiterasi hingga habis. "
        "Setiap kolom bisa memilih ambil teks atau atribut tertentu."
    )


# --------------------------------------------------------------------------- #
# Display & Downloads (persisted)                                            #
# --------------------------------------------------------------------------- #
if st.session_state.get("extracted_records"):
    df_display = pd.DataFrame(st.session_state.extracted_records, columns=st.session_state.extracted_columns)
    st.success(f"Data tersedia: {st.session_state.get('extracted_row_count', len(df_display))} baris.")
    st.dataframe(df_display, width="stretch")

    json_bytes = df_display.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
    csv_bytes = df_display.to_csv(index=False).encode("utf-8")
    excel_buffer = BytesIO()
    df_display.to_excel(excel_buffer, index=False)
    excel_buffer.seek(0)

    col_json, col_csv, col_xlsx = st.columns(3)
    col_json.download_button("Download JSON", data=json_bytes, file_name="data.json", mime="application/json")
    col_csv.download_button("Download CSV", data=csv_bytes, file_name="data.csv", mime="text/csv")
    col_xlsx.download_button(
        "Download Excel",
        data=excel_buffer,
        file_name="data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
