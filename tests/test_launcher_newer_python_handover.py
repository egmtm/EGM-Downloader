"""
Windows installer edition: an old Python first on PATH must not block a newer one behind it.

windows/launcher.c starts the first of `python`, `python3`, `py` that starts at all. A PC with
Python 3.10 first on PATH and 3.12 installed behind the py launcher therefore ran launch.py on
3.10 and got the "needs Python 3.11" dialog, although a good Python was installed. The gate in
windows/launch.py now looks for one through `py -3.13`, `-3.12`, `-3.11` (newest first) before
it gives up, and hands over to it. The new Python's folder goes first on PATH for everything
started from there, because the app finds its Python by the name `python` (main.js findPython):
without that the window would open and the backend would still run on the old one.

Both pieces run here for real, with stand ins for `subprocess`, `sys` and `os`, so nothing is
started and no dialog can open on any operating system.
"""
import io
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "windows" / "launch.py"
SRC = LAUNCH.read_text(encoding="utf-8")

CREATE_NO_WINDOW = 0x08000000


def _helper():
    return SRC[SRC.index("def _find_newer_python"):SRC.index("# ── Python version gate")]


def _gate():
    start = SRC.index("_PY_MIN = ")
    end_marker = "    sys.exit(1)\n"
    return SRC[start:SRC.index(end_marker, start) + len(end_marker)]


# ── _find_newer_python ─────────────────────────────────────────────────────────

class _Py:
    """A fake py launcher: `installed` maps a tag ("3.12") to the python.exe it would report."""

    def __init__(self, installed, missing_launcher=False, raises=(), versions=None):
        self.installed, self.missing_launcher, self.raises = installed, missing_launcher, set(raises)
        self.versions = versions or {}
        self.calls = []

    def run(self, cmd, **kw):
        assert cmd[0] == "py" and cmd[1].startswith("-3."), cmd
        assert kw.get("creationflags") == CREATE_NO_WINDOW and kw.get("timeout"), kw
        tag = cmd[1][1:]
        self.calls.append(tag)
        if self.missing_launcher:
            raise FileNotFoundError("py")
        if tag in self.raises:
            raise OSError("py hung")
        if tag not in self.installed:
            return types.SimpleNamespace(returncode=1, stdout="")
        out = self.installed[tag]
        if isinstance(out, str) and out.startswith("RAW:"):
            return types.SimpleNamespace(returncode=0, stdout=out[4:])
        major, minor = self.versions.get(tag, tuple(int(n) for n in tag.split(".")))
        return types.SimpleNamespace(returncode=0, stdout="%d %d\n%s\n" % (major, minor, out))


def _find(py, minimum=(3, 11)):
    ns = {"subprocess": types.SimpleNamespace(run=py.run, PIPE=-1, DEVNULL=-3), "Path": Path}
    exec(compile(_helper(), "launch_helper", "exec"), ns)
    return ns["_find_newer_python"](minimum)


@pytest.fixture
def exes(tmp_path):
    """python.exe files that exist, one per version."""
    made = {}
    for tag in ("3.13", "3.12", "3.11"):
        d = tmp_path / ("Python" + tag.replace(".", ""))
        d.mkdir()
        (d / "python.exe").write_text("x")
        made[tag] = str(d / "python.exe")
    return made


def test_newest_installed_python_wins_and_the_rest_are_not_asked(exes):
    py = _Py(exes)
    assert _find(py) == exes["3.13"]
    assert py.calls == ["3.13"]


def test_a_version_that_is_not_installed_is_skipped(exes):
    py = _Py({"3.12": exes["3.12"], "3.11": exes["3.11"]})
    assert _find(py) == exes["3.12"]
    assert py.calls == ["3.13", "3.12"]


def test_only_3_11_installed(exes):
    py = _Py({"3.11": exes["3.11"]})
    assert _find(py) == exes["3.11"]
    assert py.calls == ["3.13", "3.12", "3.11"]


def test_nothing_installed_returns_none(exes):
    py = _Py({})
    assert _find(py) is None
    assert py.calls == ["3.13", "3.12", "3.11"]


def test_no_py_launcher_returns_none_at_once():
    py = _Py({}, missing_launcher=True)
    assert _find(py) is None
    assert py.calls == ["3.13"], "without the py launcher nothing else is worth asking"


def test_a_hung_or_failing_probe_does_not_stop_the_search(exes):
    py = _Py(exes, raises=["3.13"])
    assert _find(py) == exes["3.12"]
    assert py.calls == ["3.13", "3.12"]


def test_a_python_below_the_minimum_is_skipped(exes):
    # The portable edition needs 3.10, the installer 3.11: a minimum above 3.11 skips it.
    py = _Py({"3.11": exes["3.11"]})
    assert _find(py, minimum=(3, 12)) is None


def test_an_answer_that_is_older_than_it_claims_is_skipped(exes):
    py = _Py({"3.13": exes["3.13"], "3.12": exes["3.12"]}, versions={"3.13": (3, 9)})
    assert _find(py) == exes["3.12"]


def test_a_reported_python_that_is_not_on_disk_is_skipped(exes, tmp_path):
    ghost = str(tmp_path / "gone" / "python.exe")
    py = _Py({"3.13": ghost, "3.12": exes["3.12"]})
    assert _find(py) == exes["3.12"]


@pytest.mark.parametrize("raw", ["RAW:", "RAW:garbage", "RAW:3 12", "RAW:x y\nC:\\python.exe\n", "RAW:3 12\n\n"])
def test_nonsense_output_is_skipped_without_raising(raw, exes):
    py = _Py({"3.13": raw, "3.12": exes["3.12"]})
    assert _find(py) == exes["3.12"]


# ── the gate hands over ────────────────────────────────────────────────────────

def _run_gate(tmp_path, monkeypatch, version, newer, environ=None, with_pythonw=True, argv=("launch.py", "--x")):
    """Run the real gate block. Returns (exit code or None, dialogs, Popen calls, helper calls)."""
    (tmp_path / "launch.py").write_text("", encoding="utf-8")
    dialogs, popens, asked = [], [], []
    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(
        user32=types.SimpleNamespace(MessageBoxW=lambda _h, text, *_a: dialogs.append(text)))))

    def fake_exit(code=0):
        raise SystemExit(code)

    fake_sys = types.SimpleNamespace(version_info=version + ("final", 0), stderr=io.StringIO(),
                                     exit=fake_exit, argv=list(argv))
    fake_os = types.SimpleNamespace(environ=dict(environ or {"PATH": "C:\\Windows", "KEEP": "1"}), pathsep=";")
    ns = {"__file__": str(tmp_path / "launch.py"), "sys": fake_sys, "Path": Path, "os": fake_os,
          "subprocess": types.SimpleNamespace(Popen=lambda cmd, **kw: popens.append((cmd, kw))),
          "_find_newer_python": lambda minimum: (asked.append(minimum), newer)[1]}
    if newer and with_pythonw:
        (Path(newer).parent / "pythonw.exe").write_text("x")
    try:
        exec(compile(_gate(), "launch_gate", "exec"), ns)
    except SystemExit as stop:
        return stop.code, dialogs, popens, asked
    return None, dialogs, popens, asked


@pytest.fixture
def newer(tmp_path):
    d = tmp_path / "Python312"
    d.mkdir()
    (d / "python.exe").write_text("x")
    return str(d / "python.exe")


def test_old_python_hands_over_to_the_newer_one_without_a_dialog(tmp_path, monkeypatch, newer):
    code, dialogs, popens, asked = _run_gate(tmp_path, monkeypatch, (3, 10, 11), newer)
    assert code == 0 and dialogs == []
    assert asked == [(3, 11)]
    (cmd, kw), = popens
    assert cmd == [str(Path(newer).with_name("pythonw.exe")), str(tmp_path / "launch.py"), "--x"]
    assert kw["creationflags"] == CREATE_NO_WINDOW


def test_the_newer_pythons_folder_goes_first_on_path_and_the_rest_of_the_environment_is_kept(tmp_path, monkeypatch, newer):
    _, _, popens, _ = _run_gate(tmp_path, monkeypatch, (3, 10, 11), newer)
    env = popens[0][1]["env"]
    assert env["PATH"] == str(Path(newer).parent) + ";C:\\Windows"
    assert env["EGM_PY_HANDOVER"] == "1" and env["EGM_SILENT"] == "1" and env["KEEP"] == "1"


def test_without_pythonw_it_starts_python_exe_hidden(tmp_path, monkeypatch, newer):
    code, _, popens, _ = _run_gate(tmp_path, monkeypatch, (3, 10, 11), newer, with_pythonw=False)
    assert code == 0 and popens[0][0][0] == newer
    assert popens[0][1]["creationflags"] == CREATE_NO_WINDOW


def test_no_newer_python_ends_in_the_same_dialog_as_before(tmp_path, monkeypatch):
    code, dialogs, popens, asked = _run_gate(tmp_path, monkeypatch, (3, 10, 11), None)
    assert code == 1 and popens == [] and asked == [(3, 11)]
    assert "needs Python 3.11 or newer" in dialogs[0] and "Detected: Python 3.10.11" in dialogs[0]


def test_a_second_hand_over_is_never_tried(tmp_path, monkeypatch, newer):
    # The new interpreter was started by a hand over: if it is still too old, stop, do not loop.
    code, dialogs, popens, asked = _run_gate(tmp_path, monkeypatch, (3, 10, 11), newer,
                                             environ={"PATH": "x", "EGM_PY_HANDOVER": "1"})
    assert code == 1 and popens == [] and asked == [], "the search must not even start"
    assert dialogs


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 12, 10), (3, 13, 1)])
def test_a_python_that_passes_the_gate_never_looks_for_another(tmp_path, monkeypatch, newer, version):
    code, dialogs, popens, asked = _run_gate(tmp_path, monkeypatch, version, newer)
    assert (code, dialogs, popens, asked) == (None, [], [], [])


def test_portable_edition_asks_for_3_10_not_3_11(tmp_path, monkeypatch, newer):
    (tmp_path / ".portable").write_text("marker")
    _, _, _, asked = _run_gate(tmp_path, monkeypatch, (3, 9, 13), newer)
    assert asked == [(3, 10)]


def test_helper_sits_above_the_gate_and_adds_no_import():
    assert SRC.index("def _find_newer_python") < SRC.index("if sys.version_info < _PY_MIN:")
    import re
    assert not re.search(r"^\s*(import|from)\s", _helper(), re.M), \
        "the helper must use only what launch.py already imports above it"
