"""Upsert a headlines CSV/CSV.gz into the Supabase `headlines` table (stdlib only).

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY. The key is never printed.
Usage: supabase_upsert.py PATH [--batch 1000]   |   supabase_upsert.py --count
"""
import argparse
import csv
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

FIELDS = ("domain", "title", "url", "seendate", "source")


def _env():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)) if not v]
    if missing:
        sys.exit(f"error: missing env var(s): {', '.join(missing)}")
    return url, key


def _headers(key, **extra):
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    h.update(extra)
    return h


def open_rows(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def post_batch(url, key, batch, retries=4):
    body = json.dumps(batch).encode("utf-8")
    endpoint = f"{url}/rest/v1/headlines?on_conflict=url"
    hdrs = _headers(key, **{
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates,return=minimal",
    })
    last = ""
    for attempt in range(retries):
        req = urllib.request.Request(endpoint, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
                return
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        time.sleep(2 ** attempt)
    sys.exit(f"error: batch failed after {retries} attempts ({last})")


def count(url, key):
    req = urllib.request.Request(
        f"{url}/rest/v1/headlines?select=url",
        headers=_headers(key, Prefer="count=exact", Range="0-0"),
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            cr = resp.headers.get("Content-Range", "")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"error: count failed ({type(e).__name__})")
    total = cr.rsplit("/", 1)[-1]
    if not total.isdigit():
        sys.exit(f"error: unparseable Content-Range: {cr!r}")
    return int(total)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--count", action="store_true", help="print exact table row count")
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args(argv)
    url, key = _env()
    if args.count:
        print(count(url, key))
        return 0
    if not args.path:
        sys.exit("error: PATH required unless --count")
    if not os.path.exists(args.path):
        sys.exit(f"error: file not found: {args.path}")
    seen, batch, sent = set(), [], 0
    for row in open_rows(args.path):
        u = (row.get("url") or "").strip()
        if not u or u in seen or not (row.get("domain") or "").strip():
            continue
        seen.add(u)
        batch.append({k: (row.get(k) or "") for k in FIELDS} | {"url": u})
        if len(batch) >= args.batch:
            post_batch(url, key, batch)
            sent += len(batch)
            batch = []
    if batch:
        post_batch(url, key, batch)
        sent += len(batch)
    print(f"upserted {sent} unique rows from {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
