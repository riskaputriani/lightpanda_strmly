import random
from typing import Dict, List, Optional

import requests
import streamlit as st
from bs4 import BeautifulSoup


@st.cache_data(ttl=600)
def get_free_proxies() -> List[Dict[str, str]]:
    """Scrape free-proxy-list.net for HTTPS proxies and their countries."""
    try:
        url = "https://free-proxy-list.net/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table")

        proxies: List[Dict[str, str]] = []
        for row in table.tbody.find_all("tr"):
            cols = row.find_all("td")
            if cols and len(cols) > 6:
                ip = cols[0].text.strip()
                port = cols[1].text.strip()
                country = cols[3].text.strip()
                is_https = cols[6].text.strip()
                if is_https == "yes":
                    proxies.append({"proxy": f"http://{ip}:{port}", "country": country})
        return proxies
    except requests.exceptions.RequestException:
        return []


def find_best_proxy() -> Optional[Dict[str, str]]:
    """Find a working proxy by testing them sequentially."""
    proxies_list = get_free_proxies()
    random.shuffle(proxies_list)

    for proxy_info in proxies_list:
        proxy = proxy_info["proxy"]
        try:
            requests.get(
                "https://httpbin.org/ip",
                proxies={"http": proxy, "https": proxy},
                timeout=3,
            )
            return proxy_info
        except requests.exceptions.RequestException:
            continue
    return None

