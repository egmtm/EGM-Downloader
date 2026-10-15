"""
Windows portable: pip is set up from a PINNED wheel, never from an unverified
downloaded script. The embedded Python zip and Node.js were already checksum
verified; the pip step was the one download that was fetched and run unchecked.

windows/launch.py is import safe (constants and functions only; the real work is
behind __main__), so these tests exercise the real functions with the network and
the subprocess faked. Nothing here downloads or runs anything.
"""
import hashlib
import importlib.util
import inspect
import re
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


@pytest.fixture
def launch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_under_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PY_SETUP_LOG", tmp_path / "setup.log")
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    py_dir = tmp_path / "python"
    py_dir.mkdir()
    (py_dir / "python312._pth").write_text("python312.zip\n.\n#import site\n", encoding="utf-8")
    monkeypatch.setattr(mod, "PY_DIR", py_dir)
    monkeypatch.setattr(mod, "PY_EXE", py_dir / "python.exe")
    return mod


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Done:
    returncode, stdout, stderr = 0, "pip 99", ""


def test_pip_pin_is_well_formed(launch):
    assert re.fullmatch(r"[0-9a-f]{64}", launch.PIP_SHA256)
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", launch.PIP_VERSION)
    assert launch.PIP_WHEEL_NAME == f"pip-{launch.PIP_VERSION}-py3-none-any.whl"
    assert launch.PIP_WHEEL_URL.startswith("https://files.pythonhosted.org/packages/")
    assert launch.PIP_WHEEL_URL.endswith("/" + launch.PIP_WHEEL_NAME)


def test_verify_sha256_accepts_only_the_exact_digest(launch, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert launch._verify_sha256(f, _sha(b"abc"), "t") is True
    assert launch._verify_sha256(f, _sha(b"abc").upper(), "t") is True
    assert launch._verify_sha256(f, _sha(b"abd"), "t") is False


@pytest.mark.parametrize("pin", [None, "", "abc", "z" * 64, "0" * 63, "0" * 65])
def test_verify_sha256_fails_closed_on_a_bad_pin(launch, tmp_path, pin):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert launch._verify_sha256(f, pin, "t") is False


def test_verify_sha256_fails_closed_on_a_missing_file(launch, tmp_path):
    assert launch._verify_sha256(tmp_path / "nope.bin", _sha(b"abc"), "t") is False


def test_python_zip_check_still_uses_its_own_pin(launch, tmp_path, monkeypatch):
    f = tmp_path / "py.zip"
    f.write_bytes(b"zip")
    monkeypatch.setattr(launch, "PY_SHA256", _sha(b"zip"))
    assert launch._verify_py_zip(f) is True
    monkeypatch.setattr(launch, "PY_SHA256", _sha(b"other"))
    assert launch._verify_py_zip(f) is False
    monkeypatch.setattr(launch, "PY_SHA256", "")
    assert launch._verify_py_zip(f) is False


def test_a_wheel_that_fails_the_check_is_never_run_and_is_removed(launch, monkeypatch):
    def fake_download(url, dest, *a, **k):
        Path(dest).write_bytes(b"tampered")

    def must_not_run(*a, **k):
        raise AssertionError("an unverified download was executed")

    monkeypatch.setattr(launch.urllib.request, "urlretrieve", fake_download)
    monkeypatch.setattr(launch.subprocess, "run", must_not_run)
    # PIP_SHA256 stays the real pin, so b"tampered" can never match it.
    assert launch._setup_embedded_pip() is False
    assert not (launch.PY_DIR / launch.PIP_WHEEL_NAME).exists()
    assert "pip wheel: checksum mismatch" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")


def test_a_failed_download_runs_nothing(launch, monkeypatch):
    def broken_download(*a, **k):
        raise OSError("offline")

    def must_not_run(*a, **k):
        raise AssertionError("something ran after a failed download")

    monkeypatch.setattr(launch.urllib.request, "urlretrieve", broken_download)
    monkeypatch.setattr(launch.subprocess, "run", must_not_run)
    assert launch._setup_embedded_pip() is False
    assert "pip wheel download failed" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")


def test_a_verified_wheel_installs_itself_offline_and_is_cleaned_up(launch, monkeypatch):
    data = b"pretend wheel"
    monkeypatch.setattr(launch, "PIP_SHA256", _sha(data))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(data))
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append([str(c) for c in cmd])
        return _Done()

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    assert launch._setup_embedded_pip() is True
    install, check = calls
    wheel = str(launch.PY_DIR / launch.PIP_WHEEL_NAME)
    assert install[0] == str(launch.PY_EXE)
    # pip is run FROM the wheel (argument 1 of the -c code), never as "<wheel>\pip"
    assert install[1:4] == ["-c", launch.PIP_BOOTSTRAP_CODE, wheel]
    assert install[4:5] == ["install"] and "--no-index" in install and install[-1] == wheel
    assert check[1:] == ["-m", "pip", "--version"]
    assert not (launch.PY_DIR / launch.PIP_WHEEL_NAME).exists()


# ── pip refuses to modify itself on Windows when started as "pip" ────────────
# pip/_internal/utils/misc.py (pip 26.2.1, the pinned wheel):
#     modifying_pip and WINDOWS and os.path.basename(sys.argv[0]) in pip_names
# with pip_names = pip, pip3, pip3.X. "python <wheel>\pip install <wheel>" gives
# argv[0] = "<wheel>\pip", so the first Windows portable run failed with "To modify
# pip, please run the following command". A Linux run never sees it, so the rule is
# reproduced here by a stand in wheel that applies the same check unconditionally.

_FAKE_PIP_MAIN = '''
import os, sys
def main(args=None):
    if args is None:
        args = sys.argv[1:]
    names = ["pip", "pip%d" % sys.version_info.major,
             "pip%d.%d" % (sys.version_info.major, sys.version_info.minor)]
    if os.path.basename(sys.argv[0]) in names:      # pip's own rule, minus the WINDOWS test
        sys.stderr.write("To modify pip, please run the following command:\\n")
        return 1
    open(os.environ["FAKE_PIP_OUT"], "w").write(repr(list(args)))
    return 0
'''
_FAKE_PIP_DUNDER_MAIN = '''
import os, sys
if sys.path[0] in ("", os.getcwd()):
    sys.path.pop(0)
if not __spec__ or __spec__.parent == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
if __name__ == "__main__":
    from pip._internal.cli.main import main as _main
    sys.exit(_main())
'''


def _fake_pip_wheel(tmp_path):
    import zipfile
    whl = tmp_path / "pip-99.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("pip/__init__.py", "")
        z.writestr("pip/__main__.py", _FAKE_PIP_DUNDER_MAIN)
        z.writestr("pip/_internal/__init__.py", "")
        z.writestr("pip/_internal/cli/__init__.py", "")
        z.writestr("pip/_internal/cli/main.py", _FAKE_PIP_MAIN)
    return whl


def _run_python(args, tmp_path):
    import os, subprocess, sys
    env = {**os.environ, "FAKE_PIP_OUT": str(tmp_path / "out.txt")}
    return subprocess.run([sys.executable, *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)


def test_the_old_way_of_starting_pip_is_refused_by_its_own_guard(tmp_path):
    """Teeth: the stand in reproduces the failure seen on Windows with the old command."""
    whl = _fake_pip_wheel(tmp_path)
    r = _run_python([str(whl / "pip"), "install", "--no-index", str(whl)], tmp_path)
    assert r.returncode != 0 and "To modify pip" in r.stderr


def test_the_bootstrap_code_gets_past_the_guard_and_hands_pip_its_arguments(launch, tmp_path):
    whl = _fake_pip_wheel(tmp_path)
    r = _run_python(["-c", launch.PIP_BOOTSTRAP_CODE, str(whl),
                     "install", "--no-index", "--no-warn-script-location", str(whl)], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out.txt").read_text() == repr(
        ["install", "--no-index", "--no-warn-script-location", str(whl)])


def test_no_unverified_script_is_fetched_or_run(launch):
    src = LAUNCH.read_text(encoding="utf-8")
    assert "get-pip" not in src and "GETPIP" not in src and "bootstrap.pypa.io" not in src
    body = inspect.getsource(launch._setup_embedded_pip)
    download = body.index("urlretrieve(")
    verify = body.index("_verify_sha256(")
    first_run = body.index("subprocess.run(")
    assert download < verify < first_run, "the check must sit between the download and the first run"
