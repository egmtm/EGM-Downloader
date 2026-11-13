"""What's New reaches no network by any road, and a version's block is found by its exact number.

test_whats_new_running_version.py counts calls of urlopen and _safe_urlopen. A request made another way
(an opener, http.client, a socket) was not counted, and in a test machine without network it failed
quietly and the route still answered with no bullets, so the test passed. Here every socket the process
would open is refused and recorded instead.

The reader picks the block whose header carries the running version. Real versions share prefixes
(1.5.0 and 1.5.0.0.8 are both in patchnotes.txt), so a match on the start of the number would show
another version's notes; the fake file here has such a pair.
"""
import importlib.util
import socket
from pathlib import Path

import pytest

from conftest import ROOT

APPS = (("app.py", "WINDOWS"), ("mac/app.py", "MAC"), ("linux/app.py", "LINUX"))


@pytest.fixture(scope="module", params=APPS, ids=[a[1] for a in APPS])
def backend(request, tmp_path_factory):
    path, tag = request.param
    if path == "app.py":
        return request.getfixturevalue("app_module")
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_whats_new_offline_" + tag.lower(), Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def no_network(monkeypatch):
    tried = []

    def refuse(*a, **k):
        tried.append(a[:2])
        raise OSError("the test refuses every network contact")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return tried


PATCHNOTES = """\
v2.0.0.1 - Later (1/2/2026)
-----------------------------------------

  • [ALL] later note

v2.0.0 - Base (1/1/2026)
-----------------------------------------

  • [ALL] base note

v2.0 - Older (12/1/2025)
-----------------------------------------

  • [ALL] older note
"""


def _notes(mod, monkeypatch, tmp_path, version, patchnotes=PATCHNOTES):
    pn = tmp_path / "patchnotes.txt"
    if patchnotes is not None:
        pn.write_text(patchnotes, encoding="utf-8")
    monkeypatch.setattr(mod, "APP_VERSION", version)
    monkeypatch.setattr(mod, "_PATCHNOTES_FILE", pn)
    r = mod.app.test_client().get("/api/whats-new", headers={"X-EGM-Token": mod._API_TOKEN})
    assert r.status_code == 200
    return r.get_json()["notes_list"]


@pytest.mark.parametrize("version,patchnotes", [
    ("2.0.0", PATCHNOTES), ("9.9.9", PATCHNOTES), ("2.0.0", None), ("2.0.0", ""),
])
def test_whats_new_opens_no_socket(backend, no_network, monkeypatch, tmp_path, version, patchnotes):
    _notes(backend, monkeypatch, tmp_path, version, patchnotes)
    assert no_network == [], f"What's New tried the network: {no_network}"


@pytest.mark.parametrize("version,expected", [
    ("2.0.0", ["base note"]), ("2.0", ["older note"]), ("2.0.0.1", ["later note"]), ("2", []), ("2.0.0.", []),
])
def test_the_block_is_found_by_its_exact_version(backend, no_network, monkeypatch, tmp_path, version, expected):
    assert _notes(backend, monkeypatch, tmp_path, version) == expected
