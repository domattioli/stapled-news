"""Resolve the US headline corpus: tracked file, cached snapshot, or download."""
import hashlib
import json
import os
import urllib.request

DEFAULT_PATH = "corpus/us/headlines.csv.gz"


class SnapshotError(RuntimeError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: str) -> None:
    urllib.request.urlretrieve(url, dest)


def resolve_corpus(path: str = DEFAULT_PATH) -> str:
    """Return a readable corpus path; fall back to the pinned snapshot if absent."""
    if os.path.exists(path):
        return path
    base = os.path.dirname(path) or "."
    pin = os.path.join(base, "SNAPSHOT.json")
    if not os.path.exists(pin):
        raise SnapshotError(f"corpus file {path} missing and no {pin} to fall back to")
    with open(pin, encoding="utf-8") as f:
        meta = json.load(f)
    cached = os.path.join(base, meta["file"])
    if os.path.exists(cached):
        if _sha256(cached) == meta["sha256"]:
            return cached
        raise SnapshotError(f"cached snapshot {cached} sha256 mismatch; delete it and retry")
    if not meta.get("url"):
        raise SnapshotError(f"snapshot {meta['file']} has no url")
    try:
        _download(meta["url"], cached)
    except Exception as e:
        if os.path.exists(cached):
            os.remove(cached)
        raise SnapshotError(
            f"could not download snapshot from {meta['url']} ({type(e).__name__}); "
            f"published={meta.get('published')}"
        ) from e
    if _sha256(cached) != meta["sha256"]:
        os.remove(cached)
        raise SnapshotError(f"downloaded snapshot sha256 mismatch for {meta['file']}")
    return cached
