"""
Record the installer folder at the end of phase 1, and check it before --continue packages it.

Between the two phases the folder sits on disk while its exe is signed. If anything changes in it then
(the exe is started to try it, and the app writes its settings, history, cookies, logs or Python's
__pycache__ into the folder it runs from; a signing tool leaves a backup), File /r would put that into
every user's install and the uninstall list would delete it from their folder. So phase 1 writes the
SHA-256 of every file, and --continue packages the folder only when it is exactly that, except the
signed exe (verified separately).

usage: folder_manifest.py write <installer folder> <manifest>
       folder_manifest.py check <installer folder> <manifest>
"""
import hashlib
import sys
from pathlib import Path

SIGNED = "EGM Downloader.exe"   # the one file signing changes, at the top of the folder


def listing(folder):
    """{relative path: sha256} of every file in the folder except the signed exe."""
    folder = Path(folder)
    out = {}
    for p in sorted(folder.rglob("*")):
        if p.is_symlink():
            raise SystemExit(f"unexpected link in the installer folder: {p.relative_to(folder).as_posix()}")
        if not p.is_file():
            continue
        rel = p.relative_to(folder).as_posix()
        if rel == SIGNED:
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
    return out


def render(entries):
    return "".join(f"{h}  {rel}\n" for rel, h in sorted(entries.items()))


def parse(text):
    entries = {}
    for line in text.splitlines():
        h, sep, rel = line.partition("  ")
        if not sep or len(h) != 64:
            raise SystemExit(f"not a manifest line: {line!r}")
        entries[rel] = h
    return entries


def differences(recorded, now):
    """Human readable lines, empty when the folder is what phase 1 built."""
    lines = [f"added:   {r}" for r in sorted(set(now) - set(recorded))]
    lines += [f"missing: {r}" for r in sorted(set(recorded) - set(now))]
    lines += [f"changed: {r}" for r in sorted(set(now) & set(recorded)) if now[r] != recorded[r]]
    return lines


def main(argv):
    if len(argv) != 4 or argv[1] not in ("write", "check"):
        raise SystemExit(__doc__)
    folder, manifest = Path(argv[2]), Path(argv[3])
    if not (folder / SIGNED).is_file():
        raise SystemExit(f"{folder} has no {SIGNED}")
    if argv[1] == "write":
        entries = listing(folder)
        manifest.write_text(render(entries), encoding="utf-8")
        print(f"   ✓ Folder manifest: {len(entries)} files")
        return 0
    if not manifest.is_file():
        print(f"   ❌ {manifest} not found — build phase 1 again (bash windows/BUILD.sh)")
        return 1
    diff = differences(parse(manifest.read_text(encoding="utf-8")), listing(folder))
    if diff:
        print("   ❌ The installer folder changed after phase 1 built it (only its exe may change, by signing):")
        for line in diff[:40]:
            print(f"     {line}")
        if len(diff) > 40:
            print(f"     … and {len(diff) - 40} more")
        print("   Was the exe started from dist/win-unpacked? Build phase 1 again, sign, then --continue.")
        return 1
    print("   ✓ Installer folder is the one phase 1 built")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
