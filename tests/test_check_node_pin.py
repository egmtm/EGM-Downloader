"""
scripts/check-node-pin.py: compares the Node.js zip pin in windows/launch.py with nodejs.org.

The script is run by hand at every Node bump (the tests cannot tell a mistyped pin from a right
one, only nodejs.org can). These tests keep the script itself honest and never touch the network:
the fetch is a fake. They also run it against the real launcher module, so a rename of
NODE_VERSION, NODE_ZIP_NAME, NODE_ZIP_URL, NODE_ZIP_SHA256 or _verify_node_zip fails here
instead of at the next bump.
"""
import hashlib
import importlib.util
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-node-pin.py"
LAUNCH = ROOT / "windows" / "launch.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk = _load("egm_check_node_pin", SCRIPT)

NAME = "node-v9.9.9-win-x64.zip"
BASE = "https://nodejs.org/dist/v9.9.9"
GOOD = "a" * 64


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _manifest(zip_hash):
    """A SHASUMS256.txt with look alike lines around the one that matters."""
    return "\n".join([
        f"{'1' * 64}  node-v9.9.9-win-x64.7z",
        f"{'2' * 64}  node-v9.9.9-win-arm64.zip",
        f"{'3' * 64}  win-x64/node.exe",
        f"{zip_hash}  {NAME}",
        f"{'4' * 64}  node-v9.9.9-linux-x64.tar.gz",
    ]) + "\n"


class Resp:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


def _fake_fetch(routes, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        value = routes[url]
        if isinstance(value, Exception):
            raise value
        return Resp(value if isinstance(value, bytes) else value.encode())
    return fetch


def _launch(pin, verify=None):
    return SimpleNamespace(
        NODE_VERSION="9.9.9",
        NODE_ZIP_NAME=NAME,
        NODE_ZIP_URL=f"{BASE}/{NAME}",
        NODE_ZIP_SHA256={} if pin is None else {"9.9.9": pin},
        _verify_node_zip=verify or (lambda p: False),
    )


def _run(launch, routes, download=False):
    lines, calls = [], []
    code = chk.check(launch, _fake_fetch(routes, calls), download=download, out=lines.append)
    return code, "\n".join(lines), calls


# ---- manifest_hash ----------------------------------------------------------------------

def test_manifest_hash_picks_the_exact_zip_among_look_alikes():
    assert chk.manifest_hash(_manifest(GOOD), NAME) == GOOD


def test_manifest_hash_accepts_a_binary_mode_star_prefix():
    assert chk.manifest_hash(f"{GOOD} *{NAME}\n", NAME) == GOOD


def test_manifest_hash_lowercases():
    assert chk.manifest_hash(f"{'A' * 64}  {NAME}\n", NAME) == "a" * 64


def test_manifest_hash_is_none_when_the_zip_is_not_listed():
    assert chk.manifest_hash(_manifest(GOOD), "node-v9.9.9-win-x86.zip") is None
    assert chk.manifest_hash("", NAME) is None


# ---- check: the manifest comparison -----------------------------------------------------

def test_a_matching_pin_passes_and_reads_the_manifest_next_to_the_zip():
    code, out, calls = _run(_launch(GOOD), {f"{BASE}/SHASUMS256.txt": _manifest(GOOD)})
    assert code == 0 and "OK" in out
    assert calls == [f"{BASE}/SHASUMS256.txt"]


def test_an_uppercase_pin_passes_because_the_launcher_accepts_it_too():
    code, _, _ = _run(_launch(GOOD.upper()), {f"{BASE}/SHASUMS256.txt": _manifest(GOOD)})
    assert code == 0


def test_a_pin_that_differs_by_one_character_fails():
    typo = GOOD[:-1] + "b"
    code, out, _ = _run(_launch(typo), {f"{BASE}/SHASUMS256.txt": _manifest(GOOD)})
    assert code == 1 and "FAIL" in out


def test_a_zip_missing_from_the_manifest_fails():
    manifest = _manifest(GOOD).replace(NAME, "node-v9.9.9-win-x86.zip")
    code, out, _ = _run(_launch(GOOD), {f"{BASE}/SHASUMS256.txt": manifest})
    assert code == 1 and "no entry" in out


def test_no_pin_for_the_version_fails_without_touching_the_network():
    code, out, calls = _run(_launch(None), {})
    assert code == 1 and "no NODE_ZIP_SHA256 entry" in out
    assert calls == []


def test_nodejs_org_unreachable_is_exit_2_not_a_verdict():
    err = urllib.error.URLError("offline")
    code, out, _ = _run(_launch(GOOD), {f"{BASE}/SHASUMS256.txt": err})
    assert code == 2 and "Could not fetch" in out


# ---- check --download: the launcher's own verification on the real zip -------------------

def test_download_runs_the_launchers_check_on_the_zip_bytes(tmp_path):
    zip_bytes = b"pretend node zip"
    seen = {}

    def verify(path):
        seen["bytes"] = Path(path).read_bytes()
        seen["name"] = Path(path).name
        return True

    routes = {f"{BASE}/SHASUMS256.txt": _manifest(_sha(zip_bytes)), f"{BASE}/{NAME}": zip_bytes}
    code, out, calls = _run(_launch(_sha(zip_bytes), verify), routes, download=True)
    assert code == 0 and "launcher accepts" in out
    assert seen == {"bytes": zip_bytes, "name": NAME}
    assert calls == [f"{BASE}/SHASUMS256.txt", f"{BASE}/{NAME}"]


def test_download_fails_when_the_launcher_refuses_the_zip():
    routes = {f"{BASE}/SHASUMS256.txt": _manifest(GOOD), f"{BASE}/{NAME}": b"x"}
    code, out, _ = _run(_launch(GOOD, lambda p: False), routes, download=True)
    assert code == 1 and "refuses" in out


def test_download_is_skipped_when_the_manifest_check_already_failed():
    routes = {f"{BASE}/SHASUMS256.txt": _manifest("f" * 64)}
    code, _, calls = _run(_launch(GOOD), routes, download=True)
    assert code == 1
    assert calls == [f"{BASE}/SHASUMS256.txt"]


def test_a_failed_download_is_exit_2():
    routes = {f"{BASE}/SHASUMS256.txt": _manifest(GOOD), f"{BASE}/{NAME}": urllib.error.URLError("cut")}
    code, out, _ = _run(_launch(GOOD), routes, download=True)
    assert code == 2 and "Could not download" in out


# ---- against the real launcher ----------------------------------------------------------

@pytest.fixture
def real():
    return _load("egm_launch_pin_script_test", LAUNCH)


def _real_routes(real, manifest_hash, zip_bytes=b""):
    base = real.NODE_ZIP_URL.rsplit("/", 1)[0]
    manifest = f"{manifest_hash}  {real.NODE_ZIP_NAME}\n"
    return {f"{base}/SHASUMS256.txt": manifest, real.NODE_ZIP_URL: zip_bytes}


def test_the_real_launchers_pin_passes_against_a_manifest_that_lists_it(real):
    pin = real.NODE_ZIP_SHA256[real.NODE_VERSION]
    code, _, _ = _run(real, _real_routes(real, pin))
    assert code == 0


def test_the_real_launchers_pin_fails_against_a_manifest_that_lists_another_hash(real):
    pin = real.NODE_ZIP_SHA256[real.NODE_VERSION]
    code, _, _ = _run(real, _real_routes(real, pin[:-1] + ("0" if pin[-1] != "0" else "1")))
    assert code == 1


def test_the_real_launcher_accepts_bytes_whose_hash_is_pinned_and_refuses_others(real, monkeypatch):
    zip_bytes = b"stand in for the real zip"
    monkeypatch.setitem(real.NODE_ZIP_SHA256, real.NODE_VERSION, _sha(zip_bytes))
    code, _, _ = _run(real, _real_routes(real, _sha(zip_bytes), zip_bytes), download=True)
    assert code == 0
    code, _, _ = _run(real, _real_routes(real, _sha(zip_bytes), zip_bytes + b"!"), download=True)
    assert code == 1
