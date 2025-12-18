import os
import pathlib
import subprocess
import sys
from playwright.sync_api import Error as PlaywrightError

CHROME_DIR = pathlib.Path.home() / ".local" / "chrome"
CHROME_BIN = CHROME_DIR / "chrome"

def ensure_chrome_installed() -> str:
    """
    Ensure Chrome binary is available under ~/.local/chrome using the provided install script.
    Returns the path to the Chrome binary.
    """
    if CHROME_BIN.exists():
        return str(CHROME_BIN)

    subprocess.run(
        [sys.executable, "install_chrome.py"],
        check=True,
        env=os.environ.copy(),
    )

    if not CHROME_BIN.exists():
        raise PlaywrightError("Chrome installation failed; chrome binary not found.")

    return str(CHROME_BIN)
