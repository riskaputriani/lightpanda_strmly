import os
import platform
import subprocess
import sys

def install_google_chrome():
    """
    Downloads and installs Google Chrome. This is intended to be run on Streamlit Cloud.
    """
    if platform.system() == "Linux":
        # Check if running in Streamlit Cloud
        if "STREAMLIT_SERVER_RUNNING" in os.environ:
            # Check if google-chrome is already installed
            try:
                subprocess.run(["google-chrome", "--version"], capture_output=True, check=True)
                print("Google Chrome is already installed.")
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("Google Chrome not found. Installing...")

            # Install Google Chrome
            try:
                subprocess.run(["apt-get", "update"], check=True)
                subprocess.run(["apt-get", "install", "-y", "wget"], check=True)
                subprocess.run(["wget", "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"], check=True)
                subprocess.run(["dpkg", "-i", "google-chrome-stable_current_amd64.deb"], check=True)
                subprocess.run(["rm", "google-chrome-stable_current_amd64.deb"], check=True)
                print("Google Chrome installed successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Failed to install Google Chrome: {e}", file=sys.stderr)
                sys.exit(1)
