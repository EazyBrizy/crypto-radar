from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from typing import Sequence


def request_backend_api(
    *,
    method: str,
    path: str,
    body: str = "",
    base_url: str = "http://127.0.0.1:8000",
    user_id: str = "usr_demo",
    timeout_seconds: float = 30.0,
    quiet_errors: bool = False,
) -> str:
    headers = {"x-dev-user": user_id}
    data: bytes | None = None
    if body.strip():
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if not quiet_errors:
            sys.stderr.write(exc.read().decode("utf-8"))
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        if not quiet_errors:
            sys.stderr.write(f"Backend API request failed: {exc}\n")
        raise SystemExit(1) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Container-local backend API request helper")
    parser.add_argument("method")
    parser.add_argument("path")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="usr_demo")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--quiet-errors", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    sys.stdout.write(
        request_backend_api(
            method=args.method,
            path=args.path,
            body=sys.stdin.read(),
            base_url=args.base_url,
            user_id=args.user_id,
            timeout_seconds=args.timeout,
            quiet_errors=args.quiet_errors,
        )
    )


if __name__ == "__main__":
    main()
