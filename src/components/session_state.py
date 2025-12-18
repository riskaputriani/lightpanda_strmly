import streamlit as st


DEFAULT_STATE = {
    "proxy_address": "",
    "proxy_country": "",
    "browser_path": None,
    "cookie_text": "",
}


def init_session_state() -> None:
    """Initialize shared session state keys for the app."""
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value

