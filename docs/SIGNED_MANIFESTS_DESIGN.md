# Signed Update Manifests — Key Management Design

**Version:** v0.99.12 VAULT
**Date:** May 25, 2026
**Author:** CODEMASTER
**Status:** Pre-implementation — requires EGM sign-off before any code is written

---

## Purpose

This document defines how the ed25519 keypair for signed update manifests is generated, stored, used, and rotated. Per OVERSEER's operational note: key management must be decided and written down before implementation — once deployed, changing this gets much harder.

---

## The keypair

**Algorithm:** Ed25519
- Industry standard (used by SSH, Git, npm, Signal)
- Small keys (32 bytes private, 32 bytes public)
- Small signatures (64 bytes)
- Fast verification — negligible overhead on every update check

**One keypair, forever** — no per-release key generation. The same private key signs every release until a rotation event occurs.

---

## Private key

**Location:** EGM's encrypted drive (already in use for code signing cert and sensitive credentials)

**Format:** PEM file — `egm_manifest_private.pem`

**Backup:** Encrypted Backblaze backup (already in place)

**Access rule:** Never leaves EGM's machine. Never committed to any repo. Never shared with any team member. Never uploaded anywhere.

**Passphrase:** Protect the PEM file with a passphrase at generation time:
```bash
openssl genpkey -algorithm ed25519 -aes256 -out egm_manifest_private.pem
```
Passphrase stored in EGM's password manager (same discipline as other credentials).

---

## Public key

**Location:** Compiled into the app binary at build time — hardcoded constant in `windows/electron/main.js`, `mac/electron/main.js`, `linux/electron/main.js`

**Format:** PEM string, embedded as a JS constant:
```js
const MANIFEST_PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA...
-----END PUBLIC KEY-----`;
```

**Not secret** — anyone can read it. Useless for forging signatures. Safe to commit to the public repo.

---

## Signing procedure (per release)

After generating the 4 JSON feeds normally, sign each one before uploading:

```bash
# Run from repo root after gen-update-json.py has produced the feeds
python3 scripts/sign-manifest.py dist/egm-version.json
python3 scripts/sign-manifest.py dist/egm-portable-version.json
python3 scripts/sign-manifest.py dist/egmac-update.json
python3 scripts/sign-manifest.py dist/egmlinux-update.json
```

The script reads `egm_manifest_private.pem` (path configured once, stored outside repo), signs the JSON content, and adds a `"signature"` field to each file. Upload the signed JSONs to egerena.com as usual.

**Time cost per release:** ~30 seconds.

---

## Verification procedure (automatic, every update check)

The app fetches the JSON, extracts the `signature` field, verifies the remaining content against `MANIFEST_PUBLIC_KEY`. If verification fails for any reason, the update is silently ignored — no error shown to the user, structured security log entry written.

---

## Rotation procedure

**When to rotate:**
- EGM's machine is compromised or stolen
- Private key file is lost (and backup is also unavailable)
- Strong suspicion the private key was exposed

**How to rotate:**
1. Generate a new keypair
2. Update the `_MANIFEST_PUBLIC_KEY_PEM` constant in all 3 `app.py` files (root for Windows, `mac/app.py`, `linux/app.py`) — this is the PEM-encoded ed25519 public key embedded at build time
3. Ship an app update with the new public key embedded — **this update must be signed with the OLD private key** so existing users' apps accept it
4. After the update reaches users (allow 2-4 weeks), switch signing to the new private key
5. Retire and securely delete the old private key

**Important:** there is a transition window where both keys are in play. Step 3 is the critical step — the update that carries the new public key must be signed with the old key, or existing users are locked out of future updates.

**Rotation is rare** — treat the private key with the same care as the code signing certificate.

---

## What rotation does NOT require

- Notifying users
- Any server-side changes
- Any changes to egerena.com infrastructure
- Any coordination beyond shipping an app update

---

## Summary checklist (one-time setup)

- [ ] Generate keypair with passphrase: `openssl genpkey -algorithm ed25519 -aes256 -out egm_manifest_private.pem`
- [ ] Extract public key: `openssl pkey -in egm_manifest_private.pem -pubout -out egm_manifest_public.pem`
- [ ] Store `egm_manifest_private.pem` on encrypted drive
- [ ] Verify Backblaze backup includes the new file
- [ ] Embed public key string in all 3 `main.js` files
- [ ] Write `scripts/sign-manifest.py` with private key path configured
- [ ] Test sign → verify round-trip before first release

---

*This document lives in `docs/SIGNED_MANIFESTS_DESIGN.md` in the repo.*
*Once signed off by EGM, implementation begins.*
