"""windows/BUILD.sh accepts a signature only with a verified timestamp.

osslsigncode 2.8 exits 0 for a signature that carries no timestamp (its report says "Timestamp is
not available") and also when the timestamp's own certificate chain does not verify ("Timestamp
Server Signature verification: failed"), so the exit code alone cannot refuse either. Without a
timestamp the signature stops verifying the day the certificate expires. The build's check therefore
reads the two result lines of the report as well as the exit code, and never passes
-ignore-timestamp. The report goes to a file from mktemp that is removed on every exit path.

The check (verify_signed) is cut out of the script and run against a stand in for osslsigncode
that prints a canned report; the reports are those of osslsigncode 2.8, shortened."""
import os
import re
import subprocess

import pytest

from conftest import read_source

SH = read_source("windows/BUILD.sh")

REPORT_TIMESTAMPED = """PE checksum   : 00013A19

Signature Index: 0  (Primary Signature)
Countersignatures:
\tTimestamp time: Nov  8 16:40:51 2026 GMT
Timestamp verified using:
\t------------------
Timestamp serial number: 02
Timestamp Server Signature verification: ok
Signature verification: ok

Number of verified signatures: 1
Succeeded
"""

REPORT_NO_TIMESTAMP = """PE checksum   : 0000D33E

Signature Index: 0  (Primary Signature)
CAfile: /etc/ssl/certs/ca-certificates.crt
TSA's certificates file: /etc/ssl/certs/ca-certificates.crt

Timestamp is not available

Signing certificate chain verified using:
\t------------------
Signature verification: ok

Number of verified signatures: 1
Succeeded
"""

REPORT_TIMESTAMP_CHAIN_FAILED = """PE checksum   : 00013A19

Signature Index: 0  (Primary Signature)
Countersignatures:
\tTimestamp time: Nov  8 16:40:51 2026 GMT
Timestamp verified using:
\t------------------
\tError: self-signed certificate in certificate chain
CMS_verify error
Timestamp Server Signature verification: failed
Signing certificate chain verified using:
\t------------------
Signature verification: ok

Number of verified signatures: 1
Succeeded
"""

REPORT_UNSIGNED = """PE checksum   : 0001771D

No signature found

Unable to extract existing signature
Failed
"""


def _check_block():
    """From the line that makes the report file to the end of verify_signed()."""
    start = SH.index("VERIFY_OUT=$(mktemp)")
    fn = SH.index("verify_signed() {", start)
    end = SH.index("\n}\n", fn) + 3
    return SH[start:end]


def _run(tmp_path, report, rc):
    """Run verify_signed on one file with a stand in osslsigncode that prints `report` and exits `rc`."""
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    (tmp_path / "report.txt").write_text(report, encoding="utf-8")
    stub = tools / "osslsigncode"
    stub.write_text("#!/bin/bash\n"
                    f'printf \'%s\\n\' "$@" > "{tmp_path}/argv.txt"\n'
                    f'cat "{tmp_path}/report.txt"\n'
                    f"exit {rc}\n", encoding="utf-8")
    stub.chmod(0o755)
    exe = tmp_path / "dist" / "egm-setup.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(b"MZ")
    script = (f'set -e\nHAVE_OSSLSIGNCODE=1\nREPO_ROOT="{tmp_path}"\n{_check_block()}\n'
              'echo "REPORT_FILE=$VERIFY_OUT"\n'
              f'verify_signed "{exe}"\necho "VERIFIED"\n')
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)
    report_file = re.search(r"^REPORT_FILE=(.+)$", r.stdout, re.M).group(1)
    argv = (tmp_path / "argv.txt").read_text(encoding="utf-8").split("\n")
    return r, argv, report_file


def test_a_signature_with_a_verified_timestamp_passes(tmp_path):
    r, argv, report_file = _run(tmp_path, REPORT_TIMESTAMPED, 0)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VERIFIED" in r.stdout and "✓ Signature and timestamp verified" in r.stdout
    assert argv[:2] == ["verify", "-in"] and "-ignore-timestamp" not in argv, argv
    assert not os.path.exists(report_file), "the report file from mktemp is removed when the check passes"


def test_a_signature_without_a_timestamp_is_refused_although_the_tool_exits_zero(tmp_path):
    r, _, report_file = _run(tmp_path, REPORT_NO_TIMESTAMP, 0)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VERIFIED" not in r.stdout
    assert "no timestamp" in r.stdout.lower() and "timestamp server" in r.stdout.lower(), r.stdout
    assert not os.path.exists(report_file), "the report file from mktemp is removed on the failure path too"


def test_a_timestamp_whose_chain_failed_is_refused_although_the_tool_exits_zero(tmp_path):
    r, _, _ = _run(tmp_path, REPORT_TIMESTAMP_CHAIN_FAILED, 0)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VERIFIED" not in r.stdout
    assert "Timestamp Server Signature verification: failed" in r.stdout, "the report is shown"


def test_an_unsigned_file_is_refused(tmp_path):
    r, _, _ = _run(tmp_path, REPORT_UNSIGNED, 1)
    assert r.returncode == 1 and "VERIFIED" not in r.stdout
    assert "No signature found" in r.stdout


def test_the_script_never_ignores_the_timestamp_and_uses_no_fixed_temp_file():
    assert "-ignore-timestamp" not in SH
    assert "/tmp/osslsigncode_out.txt" not in SH
    assert "VERIFY_OUT=$(mktemp)" in SH and "trap 'rm -f \"$VERIFY_OUT\"' EXIT" in SH
