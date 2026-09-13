from __future__ import annotations

import argparse

import uvicorn

from .migrations import current, downgrade, upgrade


def main() -> None:
    parser = argparse.ArgumentParser(prog="backend-api")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    db = subparsers.add_parser("db")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_upgrade = db_sub.add_parser("upgrade")
    db_upgrade.add_argument("revision", nargs="?", default="head")
    db_downgrade = db_sub.add_parser("downgrade")
    db_downgrade.add_argument("revision", nargs="?", default="-1")
    db_sub.add_parser("current")

    args = parser.parse_args()
    if args.command in {None, "serve"}:
        uvicorn.run("backend.app:app", host=getattr(args, "host", "127.0.0.1"), port=getattr(args, "port", 8000))
    elif args.command == "db" and args.db_command == "upgrade":
        upgrade(args.revision)
    elif args.command == "db" and args.db_command == "downgrade":
        downgrade(args.revision)
    elif args.command == "db" and args.db_command == "current":
        current()


if __name__ == "__main__":
    main()
