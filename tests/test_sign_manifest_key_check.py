"""scripts/sign-manifest.py must only produce feeds the installed app accepts.

It signed with whatever key it was given, so a release signed with the wrong key passed every
step and then failed the update check of every installed app. It now checks the new signature
against the public key the three app copies hold, and writes nothing when that fails. The keys
here are throwaway keys made in the test.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def signer(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (BestAvailableEncryption, Encoding,
                                                              PrivateFormat, PublicFormat)
    spec = importlib.util.spec_from_file_location("egm_sign_manifest", ROOT / "scripts" / "sign-manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "throwaway.pem"
    key_file.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(b"pw")))
    monkeypatch.setattr(mod.getpass, "getpass", lambda *a, **k: "pw")
    feed = tmp_path / "egm-version.json"
    feed.write_text(json.dumps({"version": "9.9.9.9", "build": 999}), encoding="utf-8")
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return mod, feed, key_file, pub


def test_the_script_reads_the_one_key_every_app_copy_trusts(signer, app_module):
    mod = signer[0]
    keys = mod._trusted_public_keys()
    assert set(keys) == {"app.py", "mac/app.py", "linux/app.py"}
    assert set(keys.values()) == {app_module._MANIFEST_PUBLIC_KEY_PEM}


def test_a_key_the_app_does_not_trust_writes_nothing_and_fails(signer):
    mod, feed, key_file, _ = signer
    before = feed.read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as stop:
        mod.sign_manifest(str(feed), str(key_file))
    assert stop.value.code == 1
    assert feed.read_text(encoding="utf-8") == before


def test_the_trusted_key_signs_a_feed_the_app_accepts(signer, app_module, monkeypatch):
    mod, feed, key_file, pub = signer
    monkeypatch.setattr(mod, "_trusted_public_keys", lambda: {k: pub for k in mod.APP_FILES})
    mod.sign_manifest(str(feed), str(key_file))
    signed = json.loads(feed.read_text(encoding="utf-8"))
    monkeypatch.setattr(app_module, "_MANIFEST_PUBLIC_KEY_PEM", pub)
    assert app_module._verify_manifest(signed) is True
    assert app_module._verify_manifest(dict(signed, build=1000)) is False


def test_app_copies_that_disagree_on_the_key_stop_the_signing(signer, monkeypatch):
    mod, feed, key_file, pub = signer
    monkeypatch.setattr(mod, "_trusted_public_keys", lambda: {"app.py": pub, "mac/app.py": pub, "linux/app.py": b"x"})
    with pytest.raises(SystemExit):
        mod.sign_manifest(str(feed), str(key_file))
    assert "signature" not in json.loads(feed.read_text(encoding="utf-8"))
