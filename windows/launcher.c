/*
 * EGM Downloader portable launcher
 * Native Windows EXE that launches the Python backend.
 * Replaces the .vbs launcher with a signable native binary.
 *
 * Behavior:
 *   1. Resolve the directory this .exe lives in
 *   2. Prefer the bundled embedded Python at "<dir>\python\python.exe" (set up on
 *      the portable's first run); otherwise fall back to system "python",
 *      "python3", then "py" to run launch.py
 *   3. Process is started with SW_HIDE so no console window flashes
 *   4. If no Python is found at all, show a friendly MessageBox pointing to python.org
 *
 * Build (cross-compile from Linux):
 *   x86_64-w64-mingw32-windres launcher.rc -O coff -o launcher.res
 *   x86_64-w64-mingw32-gcc -O2 -mwindows -municode -s launcher.c launcher.res -o "EGM Downloader.exe"
 */

#include <windows.h>
#include <stdio.h>

/* Interpreter flags for the private Python only: -s keeps the user's packages folder (and any
 * .pth file in it, which runs code at start) out of this process, -E makes it ignore PYTHON*
 * variables. launch.py passes the same on when it hands over to pythonw.exe and sets the
 * environment for everything else it starts. The system Python attempts below get none: the
 * installer edition runs on that Python and its packages may live in that user folder. */
static const wchar_t *PRIVATE_PY_FLAGS = L"-s -E ";

static int try_launch(const wchar_t *py_cmd, const wchar_t *py_flags, const wchar_t *script_path) {
    /* Build: "python" <flags>"<script_path>" (flags are empty or end in a space) */
    wchar_t cmdline[1024];
    _snwprintf_s(cmdline, 1024, _TRUNCATE, L"\"%s\" %s\"%s\"", py_cmd, py_flags, script_path);

    STARTUPINFOW si = { 0 };
    PROCESS_INFORMATION pi = { 0 };
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    BOOL ok = CreateProcessW(
        NULL, cmdline, NULL, NULL, FALSE,
        CREATE_NO_WINDOW, NULL, NULL, &si, &pi
    );

    if (ok) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        return 1;
    }
    return 0;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, LPWSTR lpCmdLine, int nShow) {
    /* Get our own EXE path */
    wchar_t exe_path[MAX_PATH];
    GetModuleFileNameW(NULL, exe_path, MAX_PATH);

    /* Strip filename to get directory */
    wchar_t *last_slash = wcsrchr(exe_path, L'\\');
    if (last_slash) *last_slash = L'\0';

    /* Build path to launch.py */
    wchar_t script_path[MAX_PATH];
    _snwprintf_s(script_path, MAX_PATH, _TRUNCATE, L"%s\\launch.py", exe_path);

    /* Prefer the portable's bundled embedded Python, so a warm portable launch
     * never touches the system interpreter (the whole point of the isolation).
     * It only exists after the first run sets it up; the installer never creates
     * it, so there it simply isn't found and we fall through to system Python. */
    wchar_t embedded_py[MAX_PATH];
    _snwprintf_s(embedded_py, MAX_PATH, _TRUNCATE, L"%s\\python\\python.exe", exe_path);
    DWORD attrs = GetFileAttributesW(embedded_py);
    if (attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY)) {
        /* The private Python is a full one: a PYTHONHOME or PYTHONPATH set on this PC for
         * another Python would point it at the wrong standard library before launch.py
         * could clear them. Clear both for this child only, and put them back if it does
         * not start, so a system Python below still gets them. */
        static const wchar_t *names[2] = { L"PYTHONHOME", L"PYTHONPATH" };
        wchar_t *saved[2] = { NULL, NULL };
        for (int i = 0; i < 2; i++) {
            DWORD n = GetEnvironmentVariableW(names[i], NULL, 0);
            if (n > 0) {
                saved[i] = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, n * sizeof(wchar_t));
                if (saved[i] && GetEnvironmentVariableW(names[i], saved[i], n) == 0) {
                    HeapFree(GetProcessHeap(), 0, saved[i]);
                    saved[i] = NULL;
                }
            }
            SetEnvironmentVariableW(names[i], NULL);
        }
        if (try_launch(embedded_py, PRIVATE_PY_FLAGS, script_path)) {
            return 0;
        }
        for (int i = 0; i < 2; i++) {
            if (saved[i]) {
                SetEnvironmentVariableW(names[i], saved[i]);
                HeapFree(GetProcessHeap(), 0, saved[i]);
            }
        }
    }

    /* First-run / installer / fallback: system python, python3, then py. */
    const wchar_t *candidates[] = { L"python", L"python3", L"py" };
    for (int i = 0; i < 3; i++) {
        if (try_launch(candidates[i], L"", script_path)) {
            return 0;
        }
    }

    /* Nothing worked — show error */
    MessageBoxW(NULL,
        L"Python 3.11+ is required.\n\n"
        L"Download from: https://python.org\n"
        L"Check 'Add Python to PATH' during install.",
        L"EGM Downloader",
        MB_ICONWARNING | MB_OK);
    return 1;
}
