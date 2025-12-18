#!/usr/bin/env bash
set -e

CHROME_DIR="$HOME/.local/chrome"
CHROME_BIN="$CHROME_DIR/chrome"
DEPS_DIR="$CHROME_DIR/deps"

if [ -x "$CHROME_BIN" ]; then
  echo "Chrome already installed"
  exit 0
fi

mkdir -p "$CHROME_DIR"
cd "$CHROME_DIR"

echo "Downloading Google Chrome Stable..."
curl -L -o chrome-linux.zip \
  https://storage.googleapis.com/chrome-for-testing-public/$$(curl -s https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE)/linux64/chrome-linux64.zip

# Extract using Python's zipfile (avoids needing system unzip)
python - <<'PY'
import zipfile, pathlib
zip_path = pathlib.Path("chrome-linux.zip")
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(".")
PY

mv chrome-linux64/* .
rm -rf chrome-linux64 chrome-linux.zip

chmod -R +x .

echo "Chrome installed at $CHROME_BIN"
"$CHROME_BIN" --version || true
