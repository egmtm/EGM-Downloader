"""The checks inside the release scripts, run for real.

Each of these checks could be removed or loosened without any test noticing: the feed
generator's argument checks, the signer's canonical payload, the checksum importer's line format,
its unknown-file and post-write checks, and the version validator's APP_VERSION, APP_BUILD and
merge-conflict checks. Keys are throwaway keys made here; nothing is written to dist/.
"""
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location("egm_script_" + name.replace("-", "_"), SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── gen-update-json.py ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args, message", [
    (["--checksum", "abc"], "64-character"),
    (["--checksum", "g" * 64], "64-character"),
    (["--size-bytes", "-5"], "positive"),
    (["--size-bytes", "10"], "sane range"),
    (["--size-bytes", str(3 * 1024 ** 3)], "sane range"),
])
def test_the_feed_generator_refuses_a_bad_checksum_or_size(args, message):
    feeds = sorted((ROOT / "dist").glob("*.json")) if (ROOT / "dist").exists() else []
    r = subprocess.run([sys.executable, str(SCRIPTS / "gen-update-json.py"), "--platform", "windows", "--dry-run", *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and message in r.stderr, (r.returncode, r.stderr[-300:])
    assert (sorted((ROOT / "dist").glob("*.json")) if (ROOT / "dist").exists() else []) == feeds


# ── sign-manifest.py ────────────────────────────────────────────────────────────────────────

def test_the_signer_signs_the_canonical_payload_without_any_old_signature(tmp_path, monkeypatch, app_module):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (BestAvailableEncryption, Encoding,
                                                              PrivateFormat, PublicFormat)
    signer = _load("sign-manifest")
    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "k.pem"
    key_file.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(b"pw")))
    monkeypatch.setattr(signer.getpass, "getpass", lambda *a, **k: "pw")
    if hasattr(signer, "_trusted_public_keys"):      # newer signer: let it trust the throwaway key
        pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        monkeypatch.setattr(signer, "_trusted_public_keys", lambda: {"app.py": pub})
    feed = tmp_path / "feed.json"
    # keys deliberately out of order, and a stale signature from an earlier run
    feed.write_text(json.dumps({"version": "9.9.9.9", "build": 999, "_checksums": {"sha256": "ab" * 32},
                                "signature": base64.b64encode(b"old").decode()}), encoding="utf-8")
    signer.sign_manifest(str(feed), str(key_file))
    monkeypatch.setattr(app_module, "_MANIFEST_PUBLIC_KEY_PEM",
                        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    assert app_module._verify_manifest(json.loads(feed.read_text(encoding="utf-8"))) is True


# ── apply-signed-checksums.py ───────────────────────────────────────────────────────────────

def test_the_checksum_importer_reads_only_full_length_hashes():
    mod = _load("apply-signed-checksums")
    good = "EGMd.zip 589003 " + "a" * 64
    assert mod.parse_input(good) == [("EGMd.zip", 589003, "a" * 64)]
    assert mod.parse_input("EGMd.zip 589003 " + "a" * 63) == []
    assert mod.parse_input("EGMd.zip 589003 " + "a" * 65) == []


def test_the_checksum_importer_fails_on_an_unknown_file(tmp_path, monkeypatch):
    mod = _load("apply-signed-checksums")
    src = tmp_path / "in.txt"
    src.write_text("Other.zip 589003 " + "b" * 64 + "\n")
    monkeypatch.setattr(sys, "argv", ["apply-signed-checksums.py", str(src)])
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: pytest.fail("nothing must run for an unknown file"))
    with pytest.raises(SystemExit) as stop:
        mod.main()
    assert stop.value.code == 1


def test_the_checksum_importer_fails_when_the_written_feed_does_not_match(tmp_path, monkeypatch):
    mod = _load("apply-signed-checksums")
    monkeypatch.setattr(mod, "DIST", tmp_path)
    src = tmp_path / "in.txt"
    src.write_text("EGMd.zip 589003 " + "c" * 64 + "\n")
    monkeypatch.setattr(sys, "argv", ["apply-signed-checksums.py", str(src)])

    def generator_writes_something_else(cmd, *a, **k):
        if "gen-update-json.py" in " ".join(map(str, cmd)):
            (tmp_path / "egm-version.json").write_text(json.dumps({"_checksums": {"sha256": "d" * 64}, "size_bytes": 589003}))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        pytest.fail("the validator must not run after a mismatch")
    monkeypatch.setattr(mod.subprocess, "run", generator_writes_something_else)
    with pytest.raises(SystemExit) as stop:
        mod.main()
    assert stop.value.code == 1


# ── validate-version-sync.py ────────────────────────────────────────────────────────────────

def test_the_validator_reports_a_stale_app_version_and_build(tmp_path, monkeypatch):
    mod = _load("validate-version-sync")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "app.py").write_text('APP_VERSION = "1.0.0"\nAPP_BUILD = 7\n')
    assert mod._check_app_py("app.py", "1.0.0", 7) == []
    errors = mod._check_app_py("app.py", "2.0.0", 8)
    assert any("APP_VERSION is '1.0.0'" in e for e in errors) and any("APP_BUILD is 7" in e for e in errors)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_validator_finds_a_merge_conflict_marker_in_a_tracked_file(tmp_path, monkeypatch):
    mod = _load("validate-version-sync")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    # Inside a commit hook git exports GIT_DIR and GIT_INDEX_FILE; left in place, these git calls
    # (and the validator's own) would write to the real repository's index instead of tmp_path.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("ok\n" + "<" * 7 + " HEAD\nmine\n" + "=" * 7 + "\ntheirs\n" + ">" * 7 + " branch\n")
    (tmp_path / "clean.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "README.md", "clean.py"], cwd=tmp_path, check=True)
    errors = mod.check_merge_conflict_markers()
    assert errors and all("README.md" in e for e in errors)
