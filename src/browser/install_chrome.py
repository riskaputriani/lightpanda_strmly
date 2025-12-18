import stat
import subprocess
import zipfile
from pathlib import Path

import requests

from .paths import CHROME_BIN, CHROME_DIR


def _download_release_archive(destination: Path) -> Path:
    latest_release_url = "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE"
    latest_release = requests.get(latest_release_url).text.strip()
    download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{latest_release}/linux64/chrome-linux64.zip"
    response = requests.get(download_url, stream=True)

    with open(destination, "wb") as fh:
        for chunk in response.iter_content(chunk_size=8192):
            fh.write(chunk)

    return destination


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(target_dir)


def install_chrome() -> None:
    """
    Download and install the Chrome for Testing binary into CHROME_DIR.
    """
    if CHROME_BIN.exists():
        print("Chrome already installed")
        return

    CHROME_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading Google Chrome Stable...")
    zip_path = CHROME_DIR / "chrome-linux.zip"
    _download_release_archive(zip_path)

    print("Extracting Chrome...")
    _extract_archive(zip_path, CHROME_DIR)

    extracted_dir = CHROME_DIR / "chrome-linux64"
    for item in extracted_dir.iterdir():
        item.rename(CHROME_DIR / item.name)
    extracted_dir.rmdir()
    zip_path.unlink()

    # Make all files executable
    print("Setting permissions...")
    for item in CHROME_DIR.rglob("*"):
        if item.is_file():
            current_permissions = item.stat().st_mode
            item.chmod(current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Chrome installed at {CHROME_BIN}")
    subprocess.run([str(CHROME_BIN), "--version"])


if __name__ == "__main__":
    install_chrome()

