#!/usr/bin/env bash
set -e

CHROME_DIR="$HOME/.local/chrome"
CHROME_BIN="$CHROME_DIR/chrome"

if [ -x "$CHROME_BIN" ]; then
  echo "Chrome already installed"
  exit 0
fi

mkdir -p "$CHROME_DIR"
cd "$CHROME_DIR"

echo "Downloading Google Chrome Stable..."
curl -L -o chrome-linux.zip \
  https://storage.googleapis.com/chrome-for-testing-public/$(curl -s https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE)/linux64/chrome-linux64.zip

unzip chrome-linux.zip
mv chrome-linux64/* .
rm -rf chrome-linux64 chrome-linux.zip

chmod +x chrome

echo "Chrome installed at $CHROME_BIN"
"$CHROME_BIN" --version
