# Implementation Handoff — Rename Electron processes in Task Manager
## (runtime-download variant — no binary committed to the repo)

**Goal:** every Electron sub-process (main, GPU, renderer, utility, crashpad) shows
as **"EGM Downloader"** in both Task Manager tabs. The separate Python/Flask process
is intentionally left as-is.

**Why this works:** all Electron processes are the *same* binary re-launched with
`--type=` flags. The Processes tab shows the EXE's `FileDescription` resource (not
the filename), so we use `rcedit` to rewrite that resource on the one binary. The
file rename alone only changes the Details tab.

**How rcedit is obtained:** downloaded once at runtime, pinned to v2.0.0 and
**SHA-256 verified, fail-closed** — same model as your Node/ffmpeg/Deno downloads.
Nothing is vendored in the repo. The whole feature is cosmetic: any failure just
skips the rename and the app launches normally.

**Files touched:** `windows/launch.py`, `windows/setup.nsi`. **Risk:** very low.

---

## Step 1 — Set the pinned SHA-256 (the ONLY required action)
In `windows/launch.py` find:

```python
RCEDIT_SHA256  = "PASTE_VERIFIED_SHA256_HERE"
```

Put the verified SHA-256 (64 hex chars) of **rcedit-x64.exe v2.0.0** there. Get it
once from a trusted source and confirm it:

```powershell
# Windows
Invoke-WebRequest https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe -OutFile rcedit-x64.exe
(Get-FileHash rcedit-x64.exe -Algorithm SHA256).Hash
```
```bash
# Linux/macOS
curl -L -o rcedit-x64.exe https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe
sha256sum rcedit-x64.exe
```

Paste that hash (lowercase is fine — the code lowercases). **Until a real 64-char
hash is set, the rename is safely skipped** (no download attempted).

> Bumping rcedit later = change both `RCEDIT_VERSION` and `RCEDIT_SHA256` together.

## Step 2 — Apply the code
Copy these two files from the zip into your `rc2` tree:
- `windows/launch.py`  (adds the rcedit download/verify/stamp logic + hide-list entry)
- `windows/setup.nsi`  (uninstall now also removes the downloaded `rcedit-x64.exe`)

There is **no** `File` line to add to the installer — the binary is fetched at
runtime, not shipped.

## Step 3 — Build & ship as usual
No build-time asset needed. `BUILD.sh` / `makensis` unchanged in behavior.

## Step 4 — Verify (clean machine or VM)
1. Install and launch. On first run the launcher briefly shows "Setting up app
   identity…" while it fetches+verifies rcedit (~2 MB).
2. Task Manager:
   - **Processes** tab: app + children all read **"EGM Downloader"** (was "Electron").
   - **Details** tab: image name **"EGM Downloader.exe"** for every Electron process.
3. `python.exe` (Flask) keeps its own name — expected.
4. Artifacts written:
   - `<INSTDIR>\rcedit-x64.exe` (verified download)
   - `<INSTDIR>\electron\node_modules\electron\dist\EGM Downloader.stamped`
     containing the stamped version (e.g. `0.99.13.121`)

Optional spot-check:
```
rcedit-x64.exe "EGM Downloader.exe" --get-version-string FileDescription   → EGM Downloader
```

## Step 5 — Lifecycle (all automatic)
- **Relaunch:** marker matches version → fast path, no re-stamp, no re-download.
- **App version bump:** `app.py` `APP_VERSION`/`APP_BUILD` change → marker mismatch
  → re-stamp next launch (exe idle then).
- **Electron major upgrade:** `ensure_npm()` wipes `node_modules`, so the renamed exe
  + marker vanish → next launch re-renames + re-stamps.
- **rcedit download fails / hash unset / mismatch:** stamping skipped; the file-rename
  (Details tab) still applies; app launches normally.

---

## Key invariants (don't break these)
- **Stamp before launch, never during** — a running exe is file-locked; the call is
  placed before `subprocess.Popen` for exactly this reason.
- **Keep `app.setName('EGM Downloader')` in main.js** — helps taskbar grouping but
  does NOT rename processes; the rcedit resource does.
- **Never guess the hash** — leaving the placeholder simply disables the feature
  (fail-closed), which is the safe default.

## Rollback
Revert the two files. Optionally delete `<INSTDIR>\rcedit-x64.exe` and the
`.stamped` marker. No data/migration impact.

## Security notes
- Download is HTTPS from `github.com/electron/rcedit/releases` and verified against
  the pinned SHA-256 before use — a tampered/corrupt download is rejected.
- `rcedit-x64.exe` is added to the portable-mode hide-list so it doesn't clutter the
  portable folder.
- `github.com`/`objects.githubusercontent.com` are already in app.py's outbound
  allowlist, but note this particular fetch is in `launch.py` (which has no allowlist
  layer); it relies on the pinned-hash check for integrity, consistent with how
  `launch.py` already downloads Node.
