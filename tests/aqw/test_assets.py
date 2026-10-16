# tests/aqw/test_assets.py
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from autoswf.aqw.assets import AqwCache, DownloadError, download_reference_files

SWF_BYTES = b"FWS\x0f" + bytes(20)
QUIET = {"progress": lambda message: None}

@pytest.fixture
def server():
    files, hits = {}, []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404); self.end_headers()
            if body is not None:
                self.wfile.write(body)
        def log_message(self, *args):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield files, hits, "http://127.0.0.1:%d/game" % srv.server_port
    srv.shutdown()

def publish(files, client="Game123.swf"):
    files["/game/api/data/gameversion"] = json.dumps({"sFile": client, "sVersion": "R1"}).encode()
    files["/game/gamefiles/" + client] = SWF_BYTES
    for g in "MF":
        files["/game/gamefiles/classes/%s/TestArmor.swf" % g] = SWF_BYTES

def test_downloads_client_and_both_armors(tmp_path, server):
    files, hits, url = server; publish(files)
    cache = AqwCache(tmp_path)
    got = download_reference_files(cache, armor="TestArmor", base_url=url, **QUIET)
    assert cache.client_path() == tmp_path / "aqw" / "gamefiles" / "Game123.swf"
    assert cache.armor_path("F", "TestArmor").read_bytes() == SWF_BYTES and len(got) == 3
    assert cache.missing("TestArmor") == []

def test_existing_files_are_not_downloaded_again(tmp_path, server):
    files, hits, url = server; publish(files)
    download_reference_files(AqwCache(tmp_path), armor="TestArmor", base_url=url, **QUIET); hits.clear()
    assert download_reference_files(AqwCache(tmp_path), armor="TestArmor", base_url=url, **QUIET) == []
    assert hits == ["/game/api/data/gameversion"]

def test_bad_responses_raise_and_leave_nothing_behind(tmp_path, server):
    files, hits, url = server
    publish(files, client="../evil.swf")
    with pytest.raises(DownloadError, match="client"):
        download_reference_files(AqwCache(tmp_path), armor="TestArmor", base_url=url, **QUIET)
    publish(files); files["/game/gamefiles/classes/F/TestArmor.swf"] = b"<html>error</html>"
    with pytest.raises(DownloadError, match="classes/F/TestArmor.swf"):
        download_reference_files(AqwCache(tmp_path), armor="TestArmor", base_url=url, **QUIET)
    assert not AqwCache(tmp_path).armor_path("F", "TestArmor").exists()
    assert [p.name for p in (tmp_path / "aqw").rglob("*") if p.is_file() and p.suffix not in (".swf", ".json")] == []
    with pytest.raises(DownloadError, match="Nope.swf"):
        download_reference_files(AqwCache(tmp_path), armor="Nope", base_url=url, **QUIET)

def test_missing_lists_what_the_preview_needs(tmp_path):
    assert AqwCache(tmp_path).missing("TestArmor") == ["AQW game client", "armor classes/M/TestArmor.swf", "armor classes/F/TestArmor.swf"]

def test_download_command(tmp_path, server, capsys, monkeypatch):
    from autoswf.cli import main
    files, hits, url = server; publish(files); monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path))
    assert main(["download-aqw", "--armor", "TestArmor", "--base-url", url]) == 0
    assert "never shared" in capsys.readouterr().out and AqwCache(tmp_path).missing("TestArmor") == []
