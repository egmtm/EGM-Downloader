#!/usr/bin/env python3
"""Sign an EGM update manifest with the ed25519 private key.

Usage:
    python3 scripts/sign-manifest.py dist/egm-version.json /path/to/egm_manifest_private.pem
    python3 scripts/sign-manifest.py dist/egm-version.json  # reads EGM_MANIFEST_KEY env var

Signs all 4 feeds at once (typical release workflow):
    KEY=/path/to/egm_manifest_private.pem
    for f in dist/egm-version.json dist/egm-portable-version.json dist/egmac-update.json dist/egmlinux-update.json; do
        python3 scripts/sign-manifest.py "$f" "$KEY"
    done

The script:
  1. Reads the JSON feed
  2. Removes any existing 'signature' field
  3. Produces a canonical payload (keys sorted, compact JSON, UTF-8)
  4. Signs with the ed25519 private key
  5. Writes the base64 signature back into the JSON under 'signature'

Private key passphrase is always prompted interactively — never read from
environment or args to avoid shell history / process list exposure.
"""
import sys
import json
import base64
import getpass
from pathlib import Path


def sign_manifest(json_path: str, key_path: str) -> None:
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        print("Error: 'cryptography' package not installed.")
        print("       pip install cryptography")
        sys.exit(1)

    key_path_obj = Path(key_path)
    if not key_path_obj.exists():
        print(f"Error: private key not found: {key_path}")
        sys.exit(1)

    json_path_obj = Path(json_path)
    if not json_path_obj.exists():
        print(f"Error: manifest not found: {json_path}")
        sys.exit(1)

    passphrase = getpass.getpass(f"Passphrase for {key_path_obj.name}: ").encode()

    try:
        private_key = load_pem_private_key(key_path_obj.read_bytes(), password=passphrase)
    except Exception as e:
        print(f"Error: could not load private key — {e}")
        sys.exit(1)

    data = json.loads(json_path_obj.read_text(encoding='utf-8'))

    # Remove any existing signature before signing
    data.pop('signature', None)

    # Canonical payload: all fields, keys sorted, compact JSON, UTF-8
    payload = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')

    try:
        sig = private_key.sign(payload)
    except Exception as e:
        print(f"Error: signing failed — {e}")
        sys.exit(1)

    data['signature'] = base64.b64encode(sig).decode('ascii')

    json_path_obj.write_text(
        json.dumps(data, indent=2) + '\n',
        encoding='utf-8'
    )

    print(f"  ✓ Signed: {json_path}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 sign-manifest.py <manifest.json> [private_key.pem]")
        print("       Set EGM_MANIFEST_KEY env var to skip key path argument.")
        sys.exit(1)

    manifest = sys.argv[1]

    key = None
    if len(sys.argv) >= 3:
        key = sys.argv[2]
    else:
        import os
        key = os.environ.get('EGM_MANIFEST_KEY')

    if not key:
        print("Error: provide private key path as argument or set EGM_MANIFEST_KEY env variable.")
        sys.exit(1)

    sign_manifest(manifest, key)
