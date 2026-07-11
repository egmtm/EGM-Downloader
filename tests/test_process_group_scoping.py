"""Process-group scoping guard for conversion subprocesses (Mac/Linux).

_kill_proc uses os.killpg(os.getpgid(proc.pid), SIGTERM) with no scoping --
a child spawned without its own session shares the app's own process group,
so killing it kills the app itself (Flask, and Electron above it). This is
exactly what happened before the round-6/round-8 fix: cancelling a video
conversion (_ensure_h264 or the newer _upscale_to_preset) could close the
whole app on Mac/Linux, because their ffmpeg subprocess was spawned via
plain _popen() with no start_new_session=True, unlike the download proc,
which has always had it.

That fix was verified by manual reproduction at the time (a real _kill_proc
call against a plain-_popen-spawned child, in an isolated simulator process)
but never had a permanent automated guard -- this test is that guard, added
after OVERSEER asked whether one existed.

Scope: any function whose result is registered in _active_procs (i.e. is a
process _kill_proc can be called against) must spawn its subprocess with
start_new_session=True on Mac/Linux. Currently that's _ensure_h264 and
_upscale_to_preset. If a third such function is ever added, it needs the
same audit -- this test only knows about the two names below; a genuinely
general guard would need to trace _active_procs assignments themselves,
which is more machinery than this bug class has earned so far.

Windows is untouched by this bug class -- taskkill /F /T /PID is scoped to
that PID's own tree, not a process-group concept -- so it's not checked here.
"""
import re
from conftest import read_source

# Functions whose tracked subprocess must be session-isolated on Mac/Linux.
# Add here (and audit start_new_session at every _popen call inside it)
# whenever a new function's proc gets assigned into _active_procs.
GUARDED_FUNCTIONS = ("_run_h264_encode",)


def _function_body(source: str, func_name: str) -> str:
    """Extract a function body from `def {func_name}(` to the next top-level
    `def ` at column 0 (or end of file)."""
    m = re.search(rf"^def {re.escape(func_name)}\(", source, re.MULTILINE)
    assert m, f"{func_name} not found"
    start = m.start()
    next_def = re.search(r"^def ", source[m.end():], re.MULTILINE)
    end = m.end() + next_def.start() if next_def else len(source)
    return source[start:end]


def _popen_calls_and_flags(body: str):
    """Return (count of _popen( calls, count of start_new_session=True occurrences)."""
    popen_calls = len(re.findall(r"_popen\(", body))
    session_flags = len(re.findall(r"start_new_session\s*=\s*True", body))
    return popen_calls, session_flags


def test_conversion_procs_are_session_isolated_on_mac_and_linux():
    for platform_file in ("mac/app.py", "linux/app.py"):
        source = read_source(platform_file)
        for func_name in GUARDED_FUNCTIONS:
            body = _function_body(source, func_name)
            popen_calls, session_flags = _popen_calls_and_flags(body)
            assert popen_calls > 0, (
                f"{platform_file}: {func_name} has no _popen( call -- "
                "guard assumption changed, update this test"
            )
            assert session_flags >= popen_calls, (
                f"{platform_file}: {func_name} spawns via _popen() without "
                "start_new_session=True on every call -- this is the exact "
                "class of bug that let cancel-during-conversion kill the "
                "whole app (killpg has no scoping without it)"
            )


def test_guard_has_teeth():
    """Prove-by-mutation: removing the flag from a real function body must
    make the guard fail, not silently pass."""
    fake_vulnerable = 'def _ensure_h264(job_id, path, job):\n    proc = _popen(str(ffmpeg), "-y")\n'
    calls, flags = _popen_calls_and_flags(fake_vulnerable)
    assert calls == 1 and flags == 0

    fake_fixed = (
        'def _ensure_h264(job_id, path, job):\n'
        '    proc = _popen(str(ffmpeg), "-y",\n'
        '                  start_new_session=True)\n'
    )
    calls2, flags2 = _popen_calls_and_flags(fake_fixed)
    assert calls2 == 1 and flags2 == 1
