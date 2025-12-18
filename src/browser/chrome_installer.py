from playwright.sync_api import Error as PlaywrightError

from .install_chrome import install_chrome
from .paths import CHROME_BIN


def ensure_chrome_installed() -> str:
    """
    Ensure Chrome is available locally and return its binary path.
    """
    if CHROME_BIN.exists():
        return str(CHROME_BIN)

    install_chrome()

    if not CHROME_BIN.exists():
        raise PlaywrightError("Chrome installation failed; chrome binary not found.")

    return str(CHROME_BIN)

