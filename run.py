"""Start the pixel mapper web app.

    python run.py                      # http://<this machine>:8000
    python run.py --projects "G:/My Drive/House Stuff/Christmas Snowflake LEDs/data/mapper"
"""

import argparse
import socket

import uvicorn

from app import project


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Pixel mapper web app")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default all interfaces)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--projects", help="folder holding project folders (default ./projects)")
    args = parser.parse_args()

    if args.projects:
        project.set_root(args.projects)
    print(f"Projects folder: {project.root()}")
    print(f"Open http://localhost:{args.port}")
    ip = lan_address()
    if ip and args.host in ("0.0.0.0", ip):
        print(f"From a phone or another computer: http://{ip}:{args.port}")

    from app.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
