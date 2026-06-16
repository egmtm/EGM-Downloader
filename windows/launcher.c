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

static int try_launch(const wchar_t *py_cmd, const wchar_t *script_path) {
    /* Build: "python" "<script_path>" */
    wchar_t cmdline[1024];
    _snwprintf_s(cmdline, 1024, _TRUNCATE, L"\"%s\" \"%s\"", py_cmd, script_path);

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
        if (try_launch(embedded_py, script_path)) {
            return 0;
        }
    }

    /* First-run / installer / fallback: system python, python3, then py. */
    const wchar_t *candidates[] = { L"python", L"python3", L"py" };
    for (int i = 0; i < 3; i++) {
        if (try_launch(candidates[i], script_path)) {
            return 0;
        }
    }

    /* Nothing worked — show error */
    MessageBoxW(NULL,
        L"Python 3.10+ is required.\n\n"
        L"Download from: https://python.org\n"
        L"Check 'Add Python to PATH' during install.",
        L"EGM Downloader",
        MB_ICONWARNING | MB_OK);
    return 1;
}
