import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _chrome_exists() -> bool:
    """
    Check if a Chrome binary is already available.
    """
    return bool(
        shutil.which("google-chrome")
        or shutil.which("chrome")
        or shutil.which("chromium")
    )


def install_google_chrome() -> None:
    """
    Ensure Google Chrome is installed (Linux only).
    Intended for Streamlit Cloud or similar environments where Chrome might be missing.
    """
    if platform.system() != "Linux":
        return

    if _chrome_exists():
        print("Google Chrome is already installed.")
        return

    print("Google Chrome not found. Installing via apt...")

    deb_path = Path("google-chrome-stable_current_amd64.deb")

    try:
        subprocess.run(["apt-get", "update", "-y"], check=True)
        subprocess.run(["apt-get", "install", "-y", "wget"], check=True)
        subprocess.run(
            ["wget", "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"],
            check=True,
        )
        subprocess.run(
            ["apt-get", "install", "-y", str(deb_path)],
            check=True,
        )
        print("Google Chrome installed successfully.")
        subprocess.run(["google-chrome", "--version"], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to install Google Chrome: {exc}", file=sys.stderr)
    finally:
        if deb_path.exists():
            deb_path.unlink()
