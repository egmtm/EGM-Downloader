"""Clear History removes the three logs, and tries once more when Windows refuses the first delete.

* egm_error.log (the traceback log in the data folder) goes with egm_debug.log and egm_debug.log.old:
  a traceback can carry a URL or a file name of a download that was just cleared.
* On Windows a file that a thread is writing can refuse a delete (a sharing violation). Each log is
  deleted once more after about 200 ms; if that fails too, Clear History goes on as before.

All three backends are driven through the real route, with the data folder in tmp_path and Path.unlink
replaced by a stand in that refuses a chosen number of times."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
LOGS = ("egm_debug.log", "egm_debug.log.old", "egm_error.log")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_clear_logs_" + path.split("/")[0], ROOT / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


@pytest.fixture
def backend(backend_module, tmp_path, monkeypatch):
    mod = backend_module
    data = tmp_path / "data"
    (data / "thumbnails").mkdir(parents=True)
    monkeypatch.setattr(mod, "THUMBNAILS_DIR", data / "thumbnails")
    monkeypatch.setattr(mod, "HISTORY_FILE", data / "egm_history.json")
    if hasattr(mod, "DATA_DIR"):
        monkeypatch.setattr(mod, "DATA_DIR", data)
    else:
        monkeypatch.setattr(mod, "get_data_dir", lambda: data)
    for name in LOGS:
        (data / name).write_text("2026-11-08 [EGM] download started: site.example\n", encoding="utf-8")
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    mod.test_data, mod.test_sleeps = data, sleeps
    return mod


def _refuse(monkeypatch, times):
    """Path.unlink refuses each log `times` times, as Windows does while a thread writes it."""
    real = Path.unlink
    tries = {}

    def unlink(self, missing_ok=False):
        if self.name in LOGS:
            tries[self.name] = tries.get(self.name, 0) + 1
            if tries[self.name] <= times:
                raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    return tries


def _clear(mod):
    r = mod.app.test_client().post("/api/history/clear", headers={"X-EGM-Token": mod._API_TOKEN})
    assert r.get_json() == {"ok": True}


def test_the_error_log_goes_with_the_debug_logs(backend):
    _clear(backend)
    for name in LOGS:
        assert not (backend.test_data / name).exists(), f"{name} is still there"


def test_a_log_that_refuses_the_first_delete_is_deleted_on_the_second(backend, monkeypatch):
    tries = _refuse(monkeypatch, 1)
    _clear(backend)
    for name in LOGS:
        assert tries.get(name) == 2, (name, tries)
        assert not (backend.test_data / name).exists(), f"{name} was not deleted on the second try"
    assert backend.test_sleeps and all(0.1 <= s <= 0.5 for s in backend.test_sleeps), backend.test_sleeps


def test_a_log_that_refuses_twice_is_left_and_clear_history_goes_on(backend, monkeypatch):
    tries = _refuse(monkeypatch, 99)
    _clear(backend)
    for name in LOGS:
        assert tries.get(name) == 2, f"{name}: tried {tries.get(name)} times, not twice"
        assert (backend.test_data / name).exists()
    assert backend.test_data.joinpath("egm_history.json").exists(), "the history itself was still cleared"


def test_a_log_that_goes_at_once_is_not_waited_for(backend, monkeypatch):
    tries = _refuse(monkeypatch, 0)
    _clear(backend)
    assert all(tries.get(name) == 1 for name in LOGS), tries
    assert backend.test_sleeps == []
