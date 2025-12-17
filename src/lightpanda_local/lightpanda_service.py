"""Download and run Lightpanda CDP server (optional) and connect helpers."""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_LIGHTPANDA_DOWNLOAD_URL = (
    "https://github.com/lightpanda-io/browser/releases/download/nightly/"
    "lightpanda-x86_64-linux"
)


@dataclass(frozen=True)
class CdpTarget:
    host: str
    port: int


def parse_cdp_target(endpoint: str) -> CdpTarget:
    parsed = urlparse(endpoint)

    if parsed.scheme in {"ws", "wss", "http", "https"} and parsed.hostname and parsed.port:
        return CdpTarget(host=parsed.hostname, port=parsed.port)

    raise ValueError(
        "CDP endpoint must look like ws://127.0.0.1:9222 or http://127.0.0.1:9222"
    )


def is_port_open(host: str, port: int, timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_port_open(host, port):
            return
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {host}:{port} to accept connections.")


def default_install_dir() -> Path:
    return Path(os.environ.get("LIGHTPANDA_DIR", "/tmp/lightpanda"))


def binary_path(install_dir: Path | None = None) -> Path:
    install_dir = install_dir or default_install_dir()
    return install_dir / "lightpanda"


def ensure_binary(download_url: str = DEFAULT_LIGHTPANDA_DOWNLOAD_URL) -> Path:
    path = binary_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        return path

    if platform.system().lower() != "linux":
        raise RuntimeError(
            "Auto-download is only implemented for Linux. "
            "Set LIGHTPANDA_CDP_WS to an already-running Lightpanda instance."
        )

    with urllib.request.urlopen(download_url) as response, open(path, "wb") as f:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    path.chmod(0o755)
    return path


def start_lightpanda_server(
    host: str = "127.0.0.1",
    port: int = 9222,
    download_url: str = DEFAULT_LIGHTPANDA_DOWNLOAD_URL,
    capture_logs: bool = False,
) -> subprocess.Popen[str]:
    exe = ensure_binary(download_url=download_url)
    stdout = subprocess.PIPE if capture_logs else subprocess.DEVNULL
    stderr = subprocess.STDOUT if capture_logs else subprocess.DEVNULL
    process = subprocess.Popen(
        [str(exe), "serve", "--host", host, "--port", str(port)],
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    return process


def ensure_lightpanda_server(
    endpoint: str,
    download_url: str = DEFAULT_LIGHTPANDA_DOWNLOAD_URL,
    startup_timeout_s: float = 10.0,
) -> subprocess.Popen[str] | None:
    target = parse_cdp_target(endpoint)
    if is_port_open(target.host, target.port):
        return None

    process = start_lightpanda_server(
        host=target.host,
        port=target.port,
        download_url=download_url,
    )
    try:
        wait_for_port(target.host, target.port, timeout_s=startup_timeout_s)
    except Exception:
        rc = process.poll()
        if rc is not None:
            raise RuntimeError(f"Lightpanda exited early (code={rc}).")
        raise
    return process
