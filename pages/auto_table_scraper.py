import json
from collections import defaultdict
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import streamlit as st

from components.cookies import sanitize_cookies
from components.page_fetcher import fetch_page
from components.session_state import init_session_state
from components.solver_runner import run_solver
from components.url_utils import ensure_scheme

try:
    import pandas as pd
    from bs4 import BeautifulSoup, Tag
except Exception as exc:  # pragma: no cover - import guard
    st.error(f"Dependency error: {exc}. Pastikan beautifulsoup4 dan pandas terinstall.")
    raise


st.set_page_config(page_title="Auto Table Scraper", layout="centered")
init_session_state()

st.title("Auto Table Scraper")
st.caption(
    "Masukkan URL, deteksi blok elemen berulang (produk, harga, dsb) jadi tabel otomatis, dan unduh sebagai JSON/CSV/Excel."
)


# --------------------------------------------------------------------------- #
# Parsing Helpers
# --------------------------------------------------------------------------- #
def _parse_html_table(soup: BeautifulSoup) -> Optional[Tuple[List[str], List[List[str]]]]:
    """Cari tabel HTML terbaik (paling banyak baris)."""
    best_headers: List[str] = []
    best_rows: List[List[str]] = []
    best_count = 0

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # header
        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(" ", strip=True) or f"col_{i+1}" for i, cell in enumerate(header_cells)]

        body_rows = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            body_rows.append([cell.get_text(" ", strip=True) for cell in cells])

        if len(body_rows) > best_count:
            best_headers = headers
            best_rows = body_rows
            best_count = len(body_rows)

    if best_rows:
        return best_headers, best_rows
    return None


def _signature(element) -> Tuple[str, Tuple[str, ...]]:
    classes = tuple(sorted(element.get("class", [])))
    return element.name, classes


def _extract_lists(
    soup: BeautifulSoup,
) -> Optional[Tuple[List[str], List[List[str]]]]:
    """
    Cari <ul>/<ol> dengan banyak <li>. Ambil teks tiap li (tanpa HTML).
    """
    best_rows: List[List[str]] = []
    best_fields = 0
    for lst in soup.find_all(["ul", "ol"]):
        items = lst.find_all("li", recursive=False) or lst.find_all("li")
        if len(items) < 3:
            continue

        rows: List[List[str]] = []
        max_fields = 0
        for li in items:
            parts = [p for p in li.stripped_strings if p]
            if not parts:
                continue
            rows.append(parts)
            max_fields = max(max_fields, len(parts))

        if len(rows) < 3:
            continue

        score = len(rows) * max_fields
        best_score = len(best_rows) * best_fields
        if score > best_score:
            best_rows = rows
            best_fields = max_fields

    if not best_rows:
        return None

    headers = [f"col_{i+1}" for i in range(best_fields)]
    normalized: List[List[str]] = []
    for row in best_rows:
        normalized.append((row + [""] * (best_fields - len(row)))[:best_fields])
    return headers, normalized


def _extract_repeating_blocks(
    soup: BeautifulSoup,
) -> Optional[Tuple[List[str], List[List[str]]]]:
    """
    Deteksi elemen berulang berbasis struktur kartu/list:
    - Pilih parent yang memiliki banyak anak dengan tag+class sama.
    - Jatuhkan ke elemen anak itu sebagai baris.
    """
    best_children: List[Tag] = []
    best_sig: Optional[Tuple[str, Tuple[str, ...]]] = None
    best_score = 0

    for parent in soup.find_all(True):
        children = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) < 3:
            continue
        sig = _signature(children[0])
        if not all(_signature(c) == sig for c in children):
            continue

        # score: banyaknya anak * panjang teks rata-rata
        texts = [" ".join(c.stripped_strings) for c in children]
        avg_len = sum(len(t) for t in texts) / len(texts) if texts else 0
        score = len(children) * (avg_len + 1)
        if score > best_score:
            best_children = children
            best_sig = sig
            best_score = score

    if not best_children:
        return None

    def _row_fields(el: Tag) -> Dict[str, str]:
        """Ambil field terstruktur dari kartu/list."""
        fields: Dict[str, str] = {}

        # Gambar
        img = el.find("img")
        if img and img.get("src"):
            fields["image"] = img["src"]
        if img and img.get("alt"):
            fields["image_alt"] = img["alt"]

        # Judul dan url produk
        h = el.find(["h1", "h2", "h3", "h4"])
        if h:
            fields["title"] = h.get_text(" ", strip=True)
            link = h.find("a")
            if link and link.get("href"):
                fields["url_product"] = link["href"]
        else:
            link = el.find("a")
            if link and link.get_text(strip=True):
                fields["title"] = link.get_text(" ", strip=True)
            if link and link.get("href"):
                fields["url_product"] = link["href"]

        # Harga
        price_node = el.find(class_="price")
        if price_node and price_node.get_text(strip=True):
            fields["price"] = price_node.get_text(strip=True)

        # Short description
        short_desc = el.find(class_="short-description")
        if short_desc:
            fields["short_description"] = short_desc.get_text(" ", strip=True)

        # Fallback teks gabungan
        if "title" not in fields:
            fields["title"] = el.get_text(" ", strip=True)[:200]

        return fields

    rows_dicts = [_row_fields(c) for c in best_children]
    # Buat header union
    headers_set = set()
    for rd in rows_dicts:
        headers_set.update(rd.keys())
    headers = sorted(headers_set)

    rows: List[List[str]] = []
    for rd in rows_dicts:
        rows.append([rd.get(h, "") for h in headers])

    return headers, rows


def extract_tabular_data(html: str) -> Optional[pd.DataFrame]:
    """Kembalikan DataFrame dari tabel HTML atau blok elemen berulang."""
    soup = BeautifulSoup(html, "html.parser")

    # 1) Coba tabel eksplisit
    table_result = _parse_html_table(soup)
    if table_result:
        headers, rows = table_result
        return pd.DataFrame(rows, columns=headers)

    # 2) Coba <ul>/<ol> dengan <li> berulang
    list_result = _extract_lists(soup)
    if list_result:
        headers, rows = list_result
        return pd.DataFrame(rows, columns=headers)

    # 3) Coba blok elemen berulang (kartu/list/div sejenis)
    repeating = _extract_repeating_blocks(soup)
    if repeating:
        headers, rows = repeating
        return pd.DataFrame(rows, columns=headers)

    return None


# --------------------------------------------------------------------------- #
# Sidebar options
# --------------------------------------------------------------------------- #
st.sidebar.header("Scraping Options")
use_solver = st.sidebar.checkbox("Gunakan solver Cloudflare jika perlu", value=True)
get_html = True  # mandatory for table detection
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

    df = extract_tabular_data(html_content)
    if df is None or df.empty:
        st.error("Tidak menemukan struktur tabel atau blok elemen berulang yang dapat diubah menjadi tabel.")
        st.stop()

    st.success(f"Berhasil mengekstrak {len(df)} baris.")
    st.dataframe(df, use_container_width=True)

    # Downloads
    json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False)
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

    # Optional info
    st.info(
        "Deteksi otomatis memakai tabel HTML jika ada. Jika tidak ada tabel, pencarian berdasarkan blok elemen "
        "berulang (tag + class). Kolom dinamai generik col_1, col_2, dst."
    )
