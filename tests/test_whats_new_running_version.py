"""
What's New must list the notes of the RUNNING version, not of whatever the feed carries.

The heading shows the running version, but the list used to come from the signed feed, which
only ever carries the latest release. A test build, an older install, a machine that was offline
and, on Linux and Mac, every user of an older version, saw another version's notes under the
wrong heading. The notes now come from the patchnotes.txt shipped next to app.py (the same
bullets and platform filter the feed is built from), and only then from the signed feed: its
history entry for this version, or its latest notes when the feed is this very version. Never
another version's notes.

All three backends are driven through their real route with a fake patchnotes file and a fake
feed. Nothing is fetched.
"""
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

from conftest import ROOT, read_source

APPS = (("app.py", "WINDOWS", "windows"), ("mac/app.py", "MAC", "mac"), ("linux/app.py", "LINUX", "linux"))

PATCHNOTES = """\
vTBD - TBD (TBD)
-----------------------------------------

  • [ALL] draft shared
  • [WINDOWS] draft windows

v2.0.0.1 - Name (1/2/2026)
-----------------------------------------

  • [ALL] shared note
  • [WINDOWS] windows note
  • [MAC] mac note
  • [LINUX] linux note
  • [MAC] [LINUX] mac and linux note
  • [WINDOWS][MAC] windows and mac note

v2.0.0.0 - Old (1/1/2026)
-----------------------------------------

  • [ALL] old shared
  • [LINUX] old linux
"""

EXPECTED_NEW = {
    "WINDOWS": ["shared note", "windows note", "windows and mac note"],
    "MAC": ["shared note", "mac note", "mac and linux note", "windows and mac note"],
    "LINUX": ["shared note", "linux note", "mac and linux note"],
}
EXPECTED_OLD = {"WINDOWS": ["old shared"], "MAC": ["old shared"], "LINUX": ["old shared", "old linux"]}


@pytest.fixture(scope="module", params=APPS, ids=[a[1] for a in APPS])
def plat(request, tmp_path_factory):
    path, tag, name = request.param
    if path == "app.py":
        mod = request.getfixturevalue("app_module")
    else:
        # Linux and Mac create their data folders at import: point them at a temporary home.
        home = str(tmp_path_factory.mktemp("home"))
        mp = pytest.MonkeyPatch()
        for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
            mp.setenv(var, home)
        try:
            spec = importlib.util.spec_from_file_location("egm_whats_new_" + name, Path(ROOT) / path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            mp.undo()
    return mod, tag, name


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _get(plat, monkeypatch, tmp_path, version, patchnotes=PATCHNOTES, feed=None, verified=True):
    """Call the real route. Returns (notes_list, number of feed fetches)."""
    app, _tag, _name = plat
    pn = tmp_path / "patchnotes.txt"
    if patchnotes is not None:
        pn.write_text(patchnotes, encoding="utf-8")
    fetches = []

    def fake_urlopen(req, timeout):
        fetches.append(req)
        return _Resp(json.dumps(feed if feed is not None else {}).encode())

    monkeypatch.setattr(app, "APP_VERSION", version)
    monkeypatch.setattr(app, "_PATCHNOTES_FILE", pn)
    monkeypatch.setattr(app, "_verify_manifest", lambda d: verified)
    monkeypatch.setattr(app, "_safe_urlopen", fake_urlopen)
    r = app.app.test_client().get("/api/whats-new", headers={"X-EGM-Token": app._API_TOKEN}).get_json()
    assert r["version"] == version
    return r["notes_list"], len(fetches)


def test_running_version_notes_come_from_the_bundled_file_for_this_platform(plat, monkeypatch, tmp_path):
    notes, fetches = _get(plat, monkeypatch, tmp_path, "2.0.0.1")
    assert notes == EXPECTED_NEW[plat[1]]
    assert fetches == 0, "the bundled notes must not need the network"


def test_an_older_running_version_gets_its_own_block_not_the_latest(plat, monkeypatch, tmp_path):
    notes, fetches = _get(plat, monkeypatch, tmp_path, "2.0.0.0")
    assert notes == EXPECTED_OLD[plat[1]]
    assert fetches == 0


def test_draft_block_bullets_never_show_under_a_real_version(plat, monkeypatch, tmp_path):
    for version in ("2.0.0.1", "2.0.0.0"):
        notes, _ = _get(plat, monkeypatch, tmp_path, version)
        assert not any("draft" in n for n in notes), (version, notes)


def test_version_without_a_block_uses_its_entry_in_the_feed_history(plat, monkeypatch, tmp_path):
    feed = {"version": "3.0.0", "_version_notes": ["newer note"],
            "_history": [{"version": "3.0.0", "notes": ["newer note"]},
                         {"version": "1.9.9", "notes": ["history note"]}]}
    notes, fetches = _get(plat, monkeypatch, tmp_path, "1.9.9", feed=feed)
    assert notes == ["history note"] and fetches == 1


def test_missing_file_falls_back_to_the_feed(plat, monkeypatch, tmp_path):
    feed = {"version": "2.0.0.1", "_version_notes": ["feed note"], "_history": []}
    notes, fetches = _get(plat, monkeypatch, tmp_path, "2.0.0.1", patchnotes=None, feed=feed)
    assert notes == ["feed note"] and fetches == 1


def test_latest_feed_notes_only_when_the_feed_is_this_version(plat, monkeypatch, tmp_path):
    same = {"version": "9.9.9", "_version_notes": ["same version note"]}
    assert _get(plat, monkeypatch, tmp_path, "9.9.9", feed=same)[0] == ["same version note"]


def test_never_another_versions_notes_under_the_running_heading(plat, monkeypatch, tmp_path):
    # The old bug: the running version is not in the file or in the feed's history, and the
    # feed's latest notes (another version) used to be shown under its heading.
    feed = {"version": "3.0.0", "_version_notes": ["newer note"],
            "_history": [{"version": "3.0.0", "notes": ["newer note"]}]}
    notes, fetches = _get(plat, monkeypatch, tmp_path, "1.0.0", feed=feed)
    assert notes == [] and fetches == 1


def test_unverified_feed_is_never_trusted(plat, monkeypatch, tmp_path):
    feed = {"version": "9.9.9", "_version_notes": ["forged"], "_history": [{"version": "9.9.9", "notes": ["forged"]}]}
    assert _get(plat, monkeypatch, tmp_path, "9.9.9", patchnotes=None, feed=feed, verified=False)[0] == []


@pytest.mark.parametrize("history", ["oops", {"version": "9.9.9"}, [None, 5, "x"], None])
def test_a_malformed_history_does_not_break_the_route(plat, monkeypatch, tmp_path, history):
    feed = {"version": "3.0.0", "_version_notes": ["newer note"], "_history": history}
    assert _get(plat, monkeypatch, tmp_path, "9.9.9", patchnotes=None, feed=feed)[0] == []


@pytest.mark.parametrize("path,tag,name", APPS, ids=[a[1] for a in APPS])
def test_bundled_notes_equal_what_the_feed_generator_builds_from_the_real_file(path, tag, name, monkeypatch):
    """The app and the feeds read the same file: for every version the feed carries in its history
    (the newest five, all in the current header form), the app returns exactly the same notes, so
    the two readers cannot drift apart. (The generator merges a few ancient headers without a
    date into the block above them; the app splits on every header, which is the right reading,
    and no feed carries those.)"""
    gen_path = Path(ROOT) / "scripts" / "gen-update-json.py"
    monkeypatch.setattr(sys, "argv", [str(gen_path)])
    spec = importlib.util.spec_from_file_location("_t_gen_update_json_" + name, gen_path)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    history = gen.parse_history(name)
    assert history, "the generator found no tagged versions in patchnotes.txt"

    src = read_source(path)
    ns = {"_re": re, "Path": Path, "_PATCHNOTES_FILE": Path(ROOT) / "patchnotes.txt",
          "_PATCHNOTES_TAG": tag}
    start = src.index("def _bundled_version_notes")
    exec(src[start:src.index('@app.route("/api/whats-new")')], ns)
    for entry in history:
        assert ns["_bundled_version_notes"](entry["version"]) == entry["notes"], entry["version"]


def test_the_three_copies_of_the_reader_are_identical_apart_from_the_platform_tag():
    bodies = []
    for path, tag, _name in APPS:
        src = read_source(path)
        assert re.search(r'^_PATCHNOTES_TAG\s*=\s*"%s"$' % tag, src, re.M), path
        assert re.search(r'^_PATCHNOTES_FILE\s*=\s*Path\(__file__\)\.parent / "patchnotes\.txt"$', src, re.M), path
        start = src.index("def _bundled_version_notes")
        body = src[start:src.index('@app.route("/api/whats-new")')]
        # The file holds "•" and Arabic: read as UTF-8 whatever the user's locale is (on Windows the default
        # is not UTF-8, and a mis-decoded bullet would silently send every user to the feed).
        assert 'read_text(encoding="utf-8")' in body, path
        bodies.append(body)
        route = src[src.index('@app.route("/api/whats-new")'):src.index('@app.route("/api/check-app-update")')]
        assert "_bundled_version_notes(APP_VERSION)" in route, path
    assert bodies[0] == bodies[1] == bodies[2]


# ── The file has to be next to app.py in every package ─────────────────────────

def test_windows_installer_portable_and_update_zip_ship_patchnotes():
    assert 'File "${REPO_ROOT}/patchnotes.txt"' in read_source("windows/setup.nsi")
    sh = read_source("windows/BUILD.sh")
    zip_lines = [l for l in sh.splitlines() if "app.py" in l and "requirements.txt" in l and "patchnotes.txt" in l]
    assert zip_lines, "the update zip no longer lists patchnotes.txt"
    assert re.search(r'cp "\$REPO_ROOT/patchnotes\.txt"\s+"\$PORTABLE_STAGE/"', sh), "the portable no longer gets patchnotes.txt"


@pytest.mark.parametrize("platform", ["linux", "mac"])
def test_linux_and_mac_packages_put_patchnotes_next_to_app_py(platform):
    pkg = json.loads(read_source(f"{platform}/electron/package.json"))
    res = pkg["build"]["extraResources"]
    assert any(r.get("from") == "../../" and r.get("to") == "app" and "patchnotes.txt" in r.get("filter", [])
               for r in res), f"{platform}: patchnotes.txt is not copied to app/ (next to app.py)"
    # app.py itself lands in app/ too, so Path(__file__).parent / "patchnotes.txt" finds it.
    assert any(r.get("to") == "app" and "app.py" in r.get("filter", []) for r in res)


def test_the_real_file_carries_each_version_once():
    """The reader joins the bullets of every block whose header carries the running version, so two
    blocks with the same version would show their notes together. No release gate refuses that; this does."""
    versions = re.findall(r"^v(\S+)\s+-", read_source("patchnotes.txt"), re.M)
    twice = sorted({v for v in versions if versions.count(v) > 1})
    assert not twice, f"patchnotes.txt has more than one block for: {twice}"
