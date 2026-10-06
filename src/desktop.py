"""
Desktop Launcher for Mistral-TTS-Booksmith.
Initializes the working environment, starts the FastAPI server via Uvicorn,
and launches the user's default web browser.
"""

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn

# Set working directory appropriately
if getattr(sys, "frozen", False):
    # PyInstaller executable mode: ensure working directory is next to executable
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Development mode: ensure working directory is repository root
    BASE_DIR = Path(__file__).resolve().parent.parent

os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("booksmith-desktop")


def find_available_port(start_port: int = 8000, max_attempts: int = 20) -> int:
    """Finds an available TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def open_browser(url: str, delay: float = 1.2) -> None:
    """Opens the given URL in the default browser in a background thread."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Could not open browser automatically: {e}")

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def run_app(host: str = "127.0.0.1", port: Optional[int] = None, open_browser_tab: bool = True) -> None:
    """
    Spawns Uvicorn with the FastAPI application, opens the browser,
    and handles graceful shutdown on interrupt.
    """
    from src.web import app

    if port is None:
        port = find_available_port(8000)

    url = f"http://{host}:{port}"
    logger.info(f"Starting Mistral-TTS-Booksmith at {url}")
    print("\n" + "=" * 56)
    print(" Mistral-TTS-Booksmith Desktop Server")
    print(f" URL: {url}")
    print(" Press Ctrl+C in this window to stop the server.")
    print("=" * 56 + "\n")

    if open_browser_tab:
        open_browser(url)

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Server stopped. Exiting...")


def main() -> None:
    """CLI entry point for desktop launcher."""
    parser = argparse.ArgumentParser(description="Mistral-TTS-Booksmith Desktop Launcher")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: auto-detected from 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
    args = parser.parse_args()

    run_app(host=args.host, port=args.port, open_browser_tab=not args.no_browser)


if __name__ == "__main__":
    main()
