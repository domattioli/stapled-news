"""Literature lookup helpers (free APIs only: OpenAlex, Crossref, doi.org).

Usage:
  python3 scripts/lit/lookup.py search "QUERY" [--n 8]
  python3 scripts/lit/lookup.py resolve DOI
  python3 scripts/lit/lookup.py bib DOI
"""
import json
import sys
import time
import urllib.parse
import urllib.request

UA = "stapled-news-lit/0.1 (mailto:none)"


def get(url, accept="application/json", tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise last


def abstract(inv):
    if not inv:
        return ""
    pos = {}
    for w, idx in inv.items():
        for i in idx:
            pos[i] = w
    return " ".join(pos[i] for i in sorted(pos))


def oa_row(w):
    loc = (w.get("primary_location") or {}).get("source") or {}
    return {
        "openalex_id": w.get("id", "").rsplit("/", 1)[-1],
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title": w.get("title"),
        "year": w.get("publication_year"),
        "venue": loc.get("display_name"),
        "cited_by": w.get("cited_by_count"),
        "abstract": abstract(w.get("abstract_inverted_index")),
    }


def search(q, n=8):
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": q, "per_page": n})
    for w in json.loads(get(url))["results"]:
        print(json.dumps(oa_row(w)))


def resolve(doi):
    try:
        m = json.loads(get("https://api.crossref.org/works/" + urllib.parse.quote(doi)))["message"]
        out = {
            "doi": m.get("DOI"),
            "title": (m.get("title") or [""])[0],
            "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "venue": (m.get("container-title") or [""])[0],
            "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in m.get("author", [])],
            "source": "crossref",
        }
    except Exception:  # noqa: BLE001
        out = oa_row(json.loads(get("https://api.openalex.org/works/doi:" + doi)))
        out["source"] = "openalex"
    print(json.dumps(out))


def bib(doi):
    print(get("https://doi.org/" + doi, accept="application/x-bibtex"))


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "search":
        search(arg, int(sys.argv[4]) if "--n" in sys.argv else 8)
    elif cmd == "resolve":
        resolve(arg)
    elif cmd == "bib":
        bib(arg)
