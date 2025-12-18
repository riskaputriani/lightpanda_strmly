import json
import sys
from pathlib import Path
from collections import defaultdict
from io import BytesIO
from typing import Dict, List, Optional, Tuple

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
    from bs4 import BeautifulSoup, Tag
    from lxml import html as lxml_html
    from lxml import etree
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


def _row_fields_from_tag(el: Tag) -> Dict[str, str]:
    """Ambil field terstruktur dari satu kartu/list item."""
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

    rows_dicts = [_row_fields_from_tag(c) for c in best_children]
    # Buat header union
    headers_set = set()
    for rd in rows_dicts:
        headers_set.update(rd.keys())
    headers = sorted(headers_set)

    rows: List[List[str]] = []
    for rd in rows_dicts:
        rows.append([rd.get(h, "") for h in headers])

    return headers, rows


def _extract_by_xpath(html: str, xpath_expr: str) -> Optional[pd.DataFrame]:
    """Gunakan XPath untuk memilih elemen berulang. Setiap node diproses seperti kartu."""
    if not xpath_expr.strip():
        return None
    try:
        tree = lxml_html.fromstring(html)
        nodes = tree.xpath(xpath_expr)
    except (etree.XPathError, ValueError):
        return None

    cards: List[Tag] = []
    for node in nodes:
        if not hasattr(node, "tag"):
            continue
        fragment = etree.tostring(node, encoding="unicode")
        soup = BeautifulSoup(fragment, "html.parser")
        tag = soup.find(True)
        if tag:
            cards.append(tag)

    if len(cards) < 1:
        return None

    rows_dicts = [_row_fields_from_tag(c) for c in cards]
    headers_set = set()
    for rd in rows_dicts:
        headers_set.update(rd.keys())
    headers = sorted(headers_set)
    rows = [[rd.get(h, "") for h in headers] for rd in rows_dicts]
    return pd.DataFrame(rows, columns=headers)


def extract_tabular_data(html: str, xpath_filter: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Kembalikan DataFrame dari tabel HTML atau blok elemen berulang."""
    soup = BeautifulSoup(html, "html.parser")

    # 0) Jika ada XPath, coba dulu
    if xpath_filter:
        df_xpath = _extract_by_xpath(html, xpath_filter)
        if df_xpath is not None and not df_xpath.empty:
            return df_xpath

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
xpath_input = st.text_input(
    "XPath (opsional) untuk memilih elemen berulang",
    value="",
    placeholder="//div[contains(@class,'product')]",
    help="Jika diisi, akan dipakai terlebih dulu untuk menemukan list item (mis. //div[@class='row product']).",
)

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

    df = extract_tabular_data(html_content, xpath_filter=xpath_input.strip() or None)
    if df is None or df.empty:
        msg = "Tidak menemukan struktur tabel atau blok elemen berulang yang dapat diubah menjadi tabel."
        if xpath_input.strip():
            msg += " XPath tidak menghasilkan data; coba kosongkan atau perbaiki ekspresi."
        st.error(msg)
        st.stop()

    st.success(f"Berhasil mengekstrak {len(df)} baris.")
    st.dataframe(df, width="stretch")

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
        "Urutan deteksi: (1) XPath jika diisi, (2) tabel HTML, (3) list <ul>/<ol>, "
        "(4) parent dengan banyak child sejenis (kartu/list). Kolom dibuat dari gabungan field yang ditemukan."
    )
