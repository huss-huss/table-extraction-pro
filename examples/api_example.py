#!/usr/bin/env python3
"""
Call a running API (start it with `table-extract serve`).

    python examples/api_example.py report.pdf [http://localhost:8000]

Uses only the standard library.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def post_file(url: str, path: Path, fields: dict) -> dict:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n".encode()
        + path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url, data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    with urllib.request.urlopen(f"{base}/healthz") as resp:
        print("healthz:", json.load(resp))
    result = post_file(f"{base}/extract", Path(sys.argv[1]), {"include_metadata": "false"})
    print(json.dumps(result, indent=2)[:2000])
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
