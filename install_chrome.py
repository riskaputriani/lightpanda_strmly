import os
import pathlib
import subprocess
import zipfile
import requests
import stat

CHROME_DIR = pathlib.Path.home() / ".local" / "chrome"
CHROME_BIN = CHROME_DIR / "chrome"

def install_chrome():
    if CHROME_BIN.exists():
        print("Chrome already installed")
        return

    CHROME_DIR.mkdir(parents=True, exist_ok=True)

    # Download Chrome
    print("Downloading Google Chrome Stable...")
    latest_release_url = "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE"
    latest_release = requests.get(latest_release_url).text.strip()
    download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{latest_release}/linux64/chrome-linux64.zip"
    zip_path = CHROME_DIR / "chrome-linux.zip"
    response = requests.get(download_url, stream=True)
    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    # Extract Chrome
    print("Extracting Chrome...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(CHROME_DIR)
    
    # Move files
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
