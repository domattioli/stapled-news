"""Fetch a recent US political-news headline corpus on a GitHub Actions runner.

Sources, in order:
  1. GDELT DOC 2.1 API — day-windowed queries over the last N days (primary).
  2. Live RSS snapshot of national political feeds (fallback/supplement).
  3. HuggingFace probe — report-only listing of palewire datasets for future use.

Writes corpus/us/headlines.csv.gz (domain,title,url,seendate,source) and
corpus/us/FETCH_REPORT.md. Designed to run where egress is open; the sandbox
ingests the committed output via git.
"""

import csv
import gzip
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

OUT_DIR = os.environ.get("OUT_DIR", "corpus/us")
DAYS = int(os.environ.get("FETCH_DAYS", "30"))
GDELT_QUERIES = [
    '(sourcecountry:US AND (theme:USPEC_POLITICS_GENERAL1 OR theme:ELECTION))',
    'sourcecountry:US (congress OR senate OR "white house" OR president OR election)',
]
RSS_FEEDS = {
    "politico.com": "https://rss.politico.com/politics-news.xml",
    "thehill.com": "https://thehill.com/feed/",
    "npr.org": "https://feeds.npr.org/1014/rss.xml",
    "foxnews.com": "https://moxie.foxnews.com/google-publisher/politics.xml",
    "cnn.com": "http://rss.cnn.com/rss/cnn_allpolitics.rss",
    "nytimes.com": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "washingtonpost.com": "https://feeds.washingtonpost.com/rss/politics",
    "abcnews.go.com": "https://abcnews.go.com/abcnews/politicsheadlines",
    "cbsnews.com": "https://www.cbsnews.com/latest/rss/politics",
    "nbcnews.com": "https://feeds.nbcnews.com/nbcnews/public/politics",
    "axios.com": "https://api.axios.com/feed/politics",
    "newsmax.com": "https://www.newsmax.com/rss/Politics/1/",
    "breitbart.com": "https://www.breitbart.com/politics/feed/",
    "huffpost.com": "https://www.huffpost.com/section/politics/feed",
    "theguardian.com": "https://www.theguardian.com/us-news/us-politics/rss",
    "apnews.com": "https://apnews.com/hub/politics?output=rss",
    "reuters.com": "https://www.reutersagency.com/feed/?best-topics=political-general",
    "usatoday.com": "http://rssfeeds.usatoday.com/UsatodaycomWashington-TopStories",
    "wsj.com": "https://feeds.content.dowjones.io/public/rss/socialpoliticsfeed",
    "msnbc.com": "https://www.msnbc.com/feeds/latest",
    "dailycaller.com": "https://dailycaller.com/section/politics/feed/",
    "motherjones.com": "https://www.motherjones.com/politics/feed/",
    "nationalreview.com": "https://www.nationalreview.com/politics-policy/feed/",
    "salon.com": "https://www.salon.com/category/politics/feed",
    "washingtontimes.com": "https://www.washingtontimes.com/rss/headlines/news/politics/",
}


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "stapled-news-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_gdelt(days, report):
    rows = {}
    end = datetime.now(timezone.utc)
    for q in GDELT_QUERIES:
        got_q = 0
        for d in range(days):
            day_end = end - timedelta(days=d)
            day_start = day_end - timedelta(days=1)
            params = urllib.parse.urlencode({
                "query": q,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": "250",
                "startdatetime": day_start.strftime("%Y%m%d%H%M%S"),
                "enddatetime": day_end.strftime("%Y%m%d%H%M%S"),
            })
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
            data = None
            for attempt in range(4):
                try:
                    data = json.loads(_get(url).decode("utf-8", "replace"))
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 3:
                        report.append(f"- GDELT day {d} error: {type(e).__name__}: {e}")
                    time.sleep(10 * (attempt + 1))  # GDELT 429s demand patience
            if data is None:
                continue
            for a in data.get("articles", []):
                u = (a.get("url") or "").split("?")[0]
                t = (a.get("title") or "").strip()
                dom = (a.get("domain") or "").lower().lstrip("www.")
                if u and t and dom and u not in rows:
                    rows[u] = (dom, t, u, a.get("seendate", ""), "gdelt")
                    got_q += 1
            time.sleep(6)  # GDELT enforces ~5s between queries
        report.append(f"- GDELT query `{q[:50]}…`: {got_q} new rows")
    return rows


def fetch_rss(report):
    rows = {}
    title_re = re.compile(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
    link_re = re.compile(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", re.S)
    item_re = re.compile(r"<item>(.*?)</item>", re.S)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for dom, feed in RSS_FEEDS.items():
        try:
            xml = _get(feed).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            report.append(f"- RSS {dom}: FAILED {type(e).__name__}")
            continue
        n = 0
        for item in item_re.findall(xml):
            t = title_re.search(item)
            li = link_re.search(item)
            if not t or not li:
                continue
            title = re.sub(r"\s+", " ", t.group(1)).strip()
            url = li.group(1).strip().split("?")[0]
            if title and url and url not in rows:
                rows[url] = (dom, title, url, now, "rss")
                n += 1
        report.append(f"- RSS {dom}: {n} items")
    return rows


def probe_hf(report):
    try:
        data = json.loads(_get(
            "https://huggingface.co/api/datasets?author=palewire&limit=20"
        ).decode())
        names = [d.get("id") for d in data]
        report.append(f"- HF probe: palewire datasets visible: {names}")
    except Exception as e:  # noqa: BLE001
        report.append(f"- HF probe failed: {type(e).__name__}: {e}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = [f"# US headline fetch — {datetime.now(timezone.utc).isoformat()}", ""]
    mode = os.environ.get("FETCH_MODE", "all")
    rows = {} if mode == "rss" else fetch_gdelt(DAYS, report)
    rss_rows = fetch_rss(report)
    for u, r in rss_rows.items():
        rows.setdefault(u, r)
    probe_hf(report)

    out = os.path.join(OUT_DIR, "headlines.csv.gz")
    # Accumulate across runs: prior corpus rows are kept (URL-keyed).
    if os.path.exists(out):
        try:
            with gzip.open(out, "rt", encoding="utf-8") as f:
                for prior in csv.DictReader(f):
                    rows.setdefault(prior["url"], (
                        prior["domain"], prior["title"], prior["url"],
                        prior["seendate"], prior["source"],
                    ))
        except Exception as e:  # noqa: BLE001
            report.append(f"- prior-corpus merge failed: {type(e).__name__}")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["domain", "title", "url", "seendate", "source"])
    for r in sorted(rows.values()):
        w.writerow(r)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        f.write(buf.getvalue())

    report.insert(2, f"**Total unique headlines: {len(rows)}**")
    with open(os.path.join(OUT_DIR, "FETCH_REPORT.md"), "w") as f:
        f.write("\n".join(report) + "\n")
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
