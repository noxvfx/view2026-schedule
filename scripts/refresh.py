#!/usr/bin/env python3
"""Fetch the live VIEW Conference schedule, parse it, and rebuild index.html.

Run from the repo root: python scripts/refresh.py
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import parse_schedule  # noqa: E402

SOURCE_URL = "https://www.viewconference.it/assets/html/view_CET.html"
ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = Path(__file__).parent / "template.html"
OUTPUT_PATH = ROOT / "index.html"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Fetch failed: HTTP {resp.status}")
        return resp.read().decode("utf-8")


def main():
    html = fetch(SOURCE_URL)
    if len(html) < 20000:
        print(f"ABORT: source page unexpectedly small ({len(html)} bytes)", file=sys.stderr)
        sys.exit(1)

    data = parse_schedule.parse(html)
    if len(data["sessions"]) < 30:
        print(f"ABORT: only {len(data['sessions'])} sessions parsed; "
              f"source structure may have changed.", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if "__SCHEDULE_DATA__" not in template:
        print("ABORT: template is missing the __SCHEDULE_DATA__ placeholder", file=sys.stderr)
        sys.exit(1)

    output = template.replace("__SCHEDULE_DATA__", payload)
    if not (80000 < len(output) < 500000):
        print(f"ABORT: unexpected output size {len(output)}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"OK sessions={len(data['sessions'])} days={len(data['days'])} "
          f"speakers={len(data['speakers'])} generatedAt={data['generatedAt']} "
          f"bytes={len(output)}")


if __name__ == "__main__":
    main()
