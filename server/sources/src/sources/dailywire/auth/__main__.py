from __future__ import annotations

from sources.dailywire.auth import cli

def main() -> int:
    cli.run_cli()
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
