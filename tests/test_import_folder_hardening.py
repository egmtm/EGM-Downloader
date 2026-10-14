"""Regression tests for the download folder that arrives with an imported settings file.

  - /api/settings/save validates last_folder before it touches the disk (the route
    also receives the settings object of an imported export file, which can come
    from anyone), and stores only the resolved path of a valid folder.
  - The startup cleanup removes only the app's own partial files, never another
    program's in progress downloads that sit in the same folder.
  - Both rules are the same text on all three platforms.
"""
import pytest

from conftest import PLATFORM_APP_FILES, read_source


def _save(app_module, monkeypatch, payload):
    saved = {}
    monkeypatch.setattr(app_module, "_save_settings", lambda d: saved.update(d))
    with app_module.app.test_client() as c:
        r = c.post("/api/settings/save", json=payload, headers={"X-EGM-Token": app_module._API_TOKEN})
    assert r.status_code == 200
    return saved


def test_last_folder_is_validated_before_it_is_created_or_stored(app_module, monkeypatch, tmp_path):
    target = tmp_path / "nested" / "from-an-import"
    seen = []

    def reject(path):
        seen.append(path)
        return False, "", "resolves to a system path"
    monkeypatch.setattr(app_module, "_validate_download_dir", reject)
    saved = _save(app_module, monkeypatch, {"last_folder": str(target), "concurrency": 3})
    assert seen == [str(target)], "the folder goes through the download-folder check"
    assert not target.exists(), "a rejected folder must not be created"
    assert "last_folder" not in saved and saved.get("concurrency") == 3, "rejected key dropped, the rest kept"


def test_a_valid_last_folder_is_created_and_stored_resolved(app_module, monkeypatch, tmp_path):
    target = tmp_path / "new" / "downloads"
    saved = _save(app_module, monkeypatch, {"last_folder": str(target)})
    assert target.is_dir()
    assert saved["last_folder"] == str(target.resolve())


@pytest.mark.parametrize("bad", [{"x": 1}, ["/tmp"], 42])
def test_a_non_string_last_folder_is_not_stored(app_module, monkeypatch, bad):
    assert "last_folder" not in _save(app_module, monkeypatch, {"last_folder": bad})


def test_a_relative_last_folder_is_not_created_or_stored(app_module, monkeypatch, tmp_path):
    """A relative value would resolve under the app's own working directory."""
    monkeypatch.chdir(tmp_path)
    saved = _save(app_module, monkeypatch, {"last_folder": "made_up/inside/cwd"})
    assert "last_folder" not in saved
    assert not (tmp_path / "made_up").exists()


def test_startup_cleanup_removes_only_this_apps_own_partials(app_module, tmp_path):
    ours = ["0123456789.mp4.part", "abcdef0123.f137.mp4.part", "abcdef0123.mp4.ytdl"]
    theirs = ["Firefox Setup.exe.part", "holiday.mp4.part", "notes.ytdl", "ABCDEF0123.mp4.part",
              "012345678.mp4.part", "keep.txt"]
    for n in ours + theirs:
        (tmp_path / n).write_bytes(b"x")
    app_module._cleanup_orphan_partials(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(theirs)
    app_module._cleanup_orphan_partials({"not": "a path"})   # an imported value of the wrong type: no exception
    app_module._cleanup_orphan_partials("")                   # nothing saved yet
    app_module._cleanup_orphan_partials(str(tmp_path / "missing"))


# ── all three platforms carry the same rules ─────────────────────────────────
def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def test_startup_runs_the_own_files_cleanup_on_every_platform():
    for rel in PLATFORM_APP_FILES:
        src = read_source(rel)
        main_block = src.split('if __name__ == "__main__":', 1)[1]
        assert "_cleanup_orphan_partials(_load_settings()" in main_block, rel
        assert src.count("glob(pattern)") == 1, f"{rel}: the only partial file sweep is the helper"


def test_folder_rules_are_identical_on_all_platforms():
    pieces = (
        ("def _cleanup_orphan_partials", 'if __name__ == "__main__":'),
        ('    if "last_folder" in data:', "    # Sanitize favorites"),
    )
    for start, end in pieces:
        base = _between(read_source(PLATFORM_APP_FILES[0]), start, end)
        for rel in PLATFORM_APP_FILES[1:]:
            assert _between(read_source(rel), start, end) == base, f"{rel}: {start}"


def test_the_full_path_rule_is_in_every_platform_validator():
    """The behaviour test drives the Windows app.py only."""
    for rel in PLATFORM_APP_FILES:
        src = read_source(rel)
        body = _between(src, "def _validate_download_dir", "\ndef ")
        assert "if not Path(os.path.expanduser(dl_dir)).is_absolute():" in body, rel
        assert 'return False, "", "Download directory must be a full path."' in body, rel
