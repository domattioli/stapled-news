"""Tests for corpus snapshot resolution and supabase_upsert env handling."""
import gzip
import hashlib
import importlib.util
import json
import pathlib

import pytest

from stapled.ingest import snapshot


def _pin(tmp_path, payload: bytes, sha=None):
    meta = {
        "file": "headlines-test.csv.gz",
        "sha256": sha or hashlib.sha256(payload).hexdigest(),
        "url": "http://example.invalid/x.csv.gz",
    }
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(meta))
    return meta


def test_existing_path_returned(tmp_path):
    p = tmp_path / "headlines.csv.gz"
    p.write_bytes(gzip.compress(b"domain,title,url\n"))
    assert snapshot.resolve_corpus(str(p)) == str(p)


def test_cached_hit(tmp_path, monkeypatch):
    data = b"abc"
    meta = _pin(tmp_path, data)
    (tmp_path / meta["file"]).write_bytes(data)
    monkeypatch.setattr(snapshot, "_download", lambda *a: pytest.fail("no download"))
    assert snapshot.resolve_corpus(str(tmp_path / "headlines.csv.gz")) == str(tmp_path / meta["file"])


def test_download_ok(tmp_path, monkeypatch):
    data = b"payload"
    meta = _pin(tmp_path, data)
    monkeypatch.setattr(snapshot, "_download", lambda u, d: pathlib.Path(d).write_bytes(data))
    out = snapshot.resolve_corpus(str(tmp_path / "headlines.csv.gz"))
    assert out == str(tmp_path / meta["file"])


def test_sha_mismatch(tmp_path, monkeypatch):
    meta = _pin(tmp_path, b"expected")
    monkeypatch.setattr(snapshot, "_download", lambda u, d: pathlib.Path(d).write_bytes(b"other"))
    with pytest.raises(snapshot.SnapshotError, match="sha256"):
        snapshot.resolve_corpus(str(tmp_path / "headlines.csv.gz"))
    assert not (tmp_path / meta["file"]).exists()


def test_missing_everything(tmp_path):
    with pytest.raises(snapshot.SnapshotError):
        snapshot.resolve_corpus(str(tmp_path / "headlines.csv.gz"))


def test_upsert_missing_env_exits(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "supabase_upsert", pathlib.Path(__file__).parents[2] / "scripts" / "supabase_upsert.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        mod.main(["--count"])
    assert "SUPABASE_URL" in str(e.value)
