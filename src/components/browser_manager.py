import streamlit as st

from browser.chrome_installer import ensure_chrome_installed


def get_chrome_path() -> str:
    """Ensure Chrome is installed and cached in session state."""
    if st.session_state.get("browser_path"):
        return st.session_state.browser_path

    chrome_path = ensure_chrome_installed()
    st.session_state.browser_path = chrome_path
    return chrome_path

