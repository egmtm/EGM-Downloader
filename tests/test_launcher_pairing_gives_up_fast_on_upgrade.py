"""On the upgrade path the launcher's pairing pip run gives up as quickly as the upgrade itself.

A package below its floor is upgraded at start with --retries 1 --timeout 15, so an offline start is
not held up for minutes; the solver pairing run that follows had pip's defaults (5 retries, 15 s each).
It now gets the same two options. On a first install (a missing package) nothing changes: that pip run
must succeed, and so may wait. The harness is the one of tests/test_launcher_pairs_ytdlp_ejs.py."""
from test_launcher_pairs_ytdlp_ejs import _first_install, _repair, launcher  # noqa: F401  (launcher is a fixture)


def _pair(launcher):
    pairs = [c for c in launcher.calls if any(a.startswith("yt-dlp-ejs==") for a in c)]
    assert len(pairs) == 1, launcher.calls
    return pairs[0]


def test_the_upgrade_paths_pairing_run_gives_up_fast(launcher, monkeypatch):
    _repair(launcher, monkeypatch)
    cmd = _pair(launcher)
    i = cmd.index("--retries")
    assert cmd[i:i + 4] == ["--retries", "1", "--timeout", "15"], cmd


def test_a_first_installs_pairing_run_keeps_pips_defaults(launcher, monkeypatch):
    _first_install(launcher, monkeypatch)
    cmd = _pair(launcher)
    assert "--retries" not in cmd and "--timeout" not in cmd, cmd
