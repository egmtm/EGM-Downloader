"""A failed download stops the build and says so.

curl without -f writes an HTTP error page (a 404, a 504 from the release host) to the output
file and exits 0, so the Python archive download "succeeded" with a 92 byte HTML page and the
build then failed at the SHA-256 check with "does not match the pinned SHA-256", which reads like
tampering. Every download in the build scripts now runs with -f, and the archive download reports
the HTTP status it got when it fails; the SHA-256 check stays for the archive that did arrive.

The download step is cut out of each script and run against a local server that answers 504."""
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import read_source

SCRIPTS = ["windows/installer/build-folder.sh", "linux/BUILD.sh", "mac/BUILD.sh"]


@pytest.mark.parametrize("rel", SCRIPTS + ["windows/BUILD.sh"])
def test_every_curl_download_fails_on_an_http_error(rel):
    downloads = [l for l in read_source(rel).splitlines() if re.search(r"\bcurl\b.* -o ", l)]
    if rel == "windows/BUILD.sh":
        assert downloads == [], "windows/BUILD.sh downloads nothing itself"
        return
    assert downloads, f"{rel}: no curl download found"
    for line in downloads:
        assert re.search(r"\bcurl( -[a-zA-Z]*f[a-zA-Z]*)", line), f"{rel}: curl without -f: {line.strip()}"


class _Gateway(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(504)
        self.end_headers()
        self.wfile.write(b"<html><body><h1>504 Gateway Time-out</h1></body></html>")

    def log_message(self, *args):
        pass


@pytest.fixture
def failing_server():
    srv = HTTPServer(("127.0.0.1", 0), _Gateway)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/cpython.tar.gz"
    srv.shutdown()


def _download_step(rel):
    """The archive download and its failure handler (the curl line and its continuation)."""
    lines = read_source(rel).splitlines()
    i = next(k for k, l in enumerate(lines) if l.strip().startswith("HTTP=$(curl") and "python.tar.gz" in l)
    step = lines[i]
    while step.rstrip().endswith("\\"):
        i += 1
        step += "\n" + lines[i]
    return step


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_failed_archive_download_says_so_with_the_status_and_leaves_no_file(rel, failing_server, tmp_path):
    script = f'set -e\nPYTHON_URL="{failing_server}"\n{_download_step(rel)}\necho DOWNLOADED\n'
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "DOWNLOADED" not in out
    assert "download" in out.lower() and "504" in out, out
    assert "SHA-256" not in out, "an HTTP error is not a hash mismatch"
    assert not (tmp_path / "python.tar.gz").exists(), "the error page is not left behind as the archive"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_hash_check_stays_right_after_the_download(rel):
    lines = read_source(rel).splitlines()
    i = next(k for k, l in enumerate(lines) if l.strip().startswith("HTTP=$(curl") and "python.tar.gz" in l)
    following = "\n".join(lines[i:i + 4])
    assert "does not match the pinned SHA-256" in following
