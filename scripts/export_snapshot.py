"""Export the Supabase `headlines` table to a dated gzip CSV and print its sha256.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY. Usage: export_snapshot.py [OUT_DIR]
"""
import csv
import gzip
import hashlib
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime

PAGE = 1000
FIELDS = ("domain", "title", "url", "seendate", "source")


def main():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        sys.exit("error: SUPABASE_URL and SUPABASE_SERVICE_KEY required")
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "corpus/us"
    os.makedirs(out_dir, exist_ok=True)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    out = os.path.join(out_dir, f"headlines-{date}.csv.gz")
    n, offset = 0, 0
    with gzip.open(out, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        while True:
            req = urllib.request.Request(
                f"{url}/rest/v1/headlines?select={','.join(FIELDS)}&order=url.asc"
                f"&limit={PAGE}&offset={offset}",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                rows = json.load(resp)
            for r in rows:
                w.writerow([r.get(k) or "" for k in FIELDS])
            n += len(rows)
            if len(rows) < PAGE:
                break
            offset += PAGE
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    print(f"file: {out}\nrows: {n}\nsha256: {h.hexdigest()}")


if __name__ == "__main__":
    main()
