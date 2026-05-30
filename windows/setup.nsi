; ============================================================
;  EGM Downloader — NSIS Installer (Unified Repo Build)
;  www.egerena.com
;
;  Required command-line defines (passed by BUILD.sh):
;    -DVERSION=0.93
;    -DBUILD=94
;    -DREPO_ROOT=/path/to/EGM-Downloader     (absolute, no trailing slash)
;    -DOUTFILE=/path/to/dist/egm-setup.exe   (absolute output path)
;
;  Compile (from repo root):
;    makensis -DVERSION=0.93 -DBUILD=94 \
;             -DREPO_ROOT="$(pwd)" \
;             -DOUTFILE="$(pwd)/dist/egm-setup.exe" \
;             windows/setup.nsi
; ============================================================

!include "MUI2.nsh"
!include "LogicLib.nsh"

; ── Required defines (sanity check) ──────────────────────────
!ifndef VERSION
  !error "VERSION must be passed via -DVERSION="
!endif
!ifndef BUILD
  !error "BUILD must be passed via -DBUILD="
!endif
!ifndef REPO_ROOT
  !error "REPO_ROOT must be passed via -DREPO_ROOT="
!endif
!ifndef OUTFILE
  !error "OUTFILE must be passed via -DOUTFILE="
!endif

; ── Metadata ─────────────────────────────────────────────────
!define APPNAME    "EGM Downloader"
!define PUBLISHER  "egerena.com"
!define APPURL     "https://egerena.com/apps"
!define REGKEY     "Software\EGM Downloader"
!define UNINSTREG  "Software\Microsoft\Windows\CurrentVersion\Uninstall\EGMDownloader"

Name             "${APPNAME}"
OutFile          "${OUTFILE}"
InstallDir       "$LOCALAPPDATA\EGM Downloader"
RequestExecutionLevel user
SetCompressor    /SOLID lzma
Unicode          true

; ── Variables ────────────────────────────────────────────────
Var PreviousVersion
Var PreviousInstDir

; ── MUI Settings ─────────────────────────────────────────────
!define MUI_ICON   "${REPO_ROOT}/static/icon.ico"
!define MUI_UNICON "${REPO_ROOT}/static/icon.ico"

!define MUI_WELCOMEPAGE_TITLE   "Welcome to EGM Downloader v${VERSION}"
!define MUI_WELCOMEPAGE_TEXT    "This will install EGM Downloader v${VERSION} (Build ${BUILD}) on your computer.$\r$\n$\r$\nPython 3.10 or newer is required. On first launch, ~250 MB of additional components will be downloaded automatically.$\r$\n$\r$\nClick Next to continue."

!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose the folder where EGM Downloader will be installed."

!define MUI_FINISHPAGE_RUN      "$INSTDIR\EGM Downloader.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APPNAME}"
!define MUI_FINISHPAGE_RUN_FUNCTION FinishPage_LaunchApp
!define MUI_FINISHPAGE_TITLE    "Installation Complete"
!define MUI_FINISHPAGE_TEXT     "EGM Downloader v${VERSION} (Build ${BUILD}) has been installed.$\r$\n$\r$\nOn first launch, required components will be downloaded in the background. This is a one-time process."
!define MUI_FINISHPAGE_SHOWREADME        ""
!define MUI_FINISHPAGE_SHOWREADME_TEXT   "Add shortcut to desktop"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION FinishPage_CreateDesktopShortcut

; ── Pages ────────────────────────────────────────────────────
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ── Desktop shortcut — created only if user checks the box on finish page ────
Function FinishPage_CreateDesktopShortcut
  CreateShortCut "$DESKTOP\EGM Downloader.lnk" \
    "$INSTDIR\EGM Downloader.exe" "" \
    "$INSTDIR\static\icon.ico" 0
FunctionEnd

; ── Launch app from finish page — uses ShellExecute to avoid CMD flash ────────
Function FinishPage_LaunchApp
  ExecShell "open" "$INSTDIR\EGM Downloader.exe"
FunctionEnd

; ── Startup: detect existing install ─────────────────────────
Function .onInit
  ReadRegStr $PreviousVersion HKCU "${REGKEY}" "Version"
  ReadRegStr $PreviousInstDir HKCU "${REGKEY}" "InstallPath"

  ; No previous install — fresh install
  ${If} $PreviousVersion == ""
    Return
  ${EndIf}

  ; Same version installed — Maintenance mode
  ${If} $PreviousVersion == "${VERSION}"
    ${If} $PreviousInstDir != ""
      StrCpy $INSTDIR $PreviousInstDir
    ${EndIf}
    MessageBox MB_YESNOCANCEL|MB_ICONQUESTION \
      "EGM Downloader v${VERSION} is already installed.$\r$\n$\r$\n\
Yes  →  Repair (reinstall files, keep settings)$\r$\n\
No   →  Uninstall$\r$\n\
Cancel  →  Exit" \
      /SD IDCANCEL IDYES repair IDNO do_uninstall
    Abort
    repair:
      Return
    do_uninstall:
      ${If} $PreviousInstDir != ""
        ExecWait '"$PreviousInstDir\uninstall.exe" /S'
      ${EndIf}
      Abort
  ${EndIf}

  ; Different version — Upgrade. Reuse previous install dir.
  ${If} $PreviousInstDir != ""
    StrCpy $INSTDIR $PreviousInstDir
  ${EndIf}
FunctionEnd

; ── Install Section ──────────────────────────────────────────
Section "Install"
  SetOutPath "$INSTDIR"

  ; ── Root files ──
  File "${REPO_ROOT}/windows/EGM Downloader.exe"
  File "${REPO_ROOT}/windows/launch.bat"
  File "${REPO_ROOT}/windows/launch.py"
  File "${REPO_ROOT}/windows/instructions.txt"
  File "${REPO_ROOT}/app.py"
  File "${REPO_ROOT}/patchnotes.txt"

  ; ── templates\ ──
  SetOutPath "$INSTDIR\templates"
  File "${REPO_ROOT}/templates/index.html"
  File "${REPO_ROOT}/templates/index_styles.html"
  File "${REPO_ROOT}/templates/index_scripts.html"
  File "${REPO_ROOT}/templates/history.html"
  File "${REPO_ROOT}/templates/themes.html"
  File "${REPO_ROOT}/templates/theme_styles.html"

  ; ── static\ ──
  SetOutPath "$INSTDIR\static"
  File "${REPO_ROOT}/static/icon.ico"
  File "${REPO_ROOT}/static/icon-512.png"
  File "${REPO_ROOT}/static/icon-256.png"
  File "${REPO_ROOT}/static/icon-128.png"
  File "${REPO_ROOT}/static/icon-64.png"
  File "${REPO_ROOT}/static/icon-32.png"
  File "${REPO_ROOT}/static/icon-16.png"

  ; ── electron\ ──
  SetOutPath "$INSTDIR\electron"
  File "${REPO_ROOT}/windows/electron/main.js"
  File "${REPO_ROOT}/windows/electron/preload.js"
  File "${REPO_ROOT}/windows/electron/splash.html"
  File "${REPO_ROOT}/windows/electron/package.json"
  File "${REPO_ROOT}/windows/electron/package-lock.json"

  ; Reset path back to install dir for the rest
  SetOutPath "$INSTDIR"

  ; ── Registry: app info ──
  WriteRegStr HKCU "${REGKEY}" "Version"     "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Build"       "${BUILD}"
  WriteRegStr HKCU "${REGKEY}" "InstallPath" "$INSTDIR"

  ; ── Registry: Add/Remove Programs ──
  WriteRegStr HKCU "${UNINSTREG}" "DisplayName"     "${APPNAME}"
  WriteRegStr HKCU "${UNINSTREG}" "DisplayVersion"  "${VERSION}"
  WriteRegStr HKCU "${UNINSTREG}" "DisplayIcon"     "$INSTDIR\static\icon.ico"
  WriteRegStr HKCU "${UNINSTREG}" "Publisher"       "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTREG}" "URLInfoAbout"    "${APPURL}"
  WriteRegStr HKCU "${UNINSTREG}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTREG}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTREG}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTREG}" "NoRepair" 1

  ; ── Start Menu shortcuts ──
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" \
                  "$INSTDIR\EGM Downloader.exe" "" "$INSTDIR\static\icon.ico"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" \
                  "$INSTDIR\uninstall.exe"

  ; ── Write the uninstaller ──
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ── Uninstall Section ────────────────────────────────────────
Section "Uninstall"
  ; ── Close the app if it's still running, so files aren't locked ──
  ; Both the launcher and the renamed Electron runtime use this image name.
  nsExec::Exec 'taskkill /F /T /IM "EGM Downloader.exe"'
  Sleep 500

  ; ── Remove app files ──
  Delete "$INSTDIR\EGM Downloader.exe"
  Delete "$INSTDIR\launch.bat"
  Delete "$INSTDIR\launch.py"
  Delete "$INSTDIR\instructions.txt"
  Delete "$INSTDIR\app.py"
  Delete "$INSTDIR\rcedit-x64.exe"
  Delete "$INSTDIR\patchnotes.txt"

  RMDir /r "$INSTDIR\templates"
  RMDir /r "$INSTDIR\static"

  ; Electron app files (but preserve node_modules unless user opts in below)
  Delete "$INSTDIR\electron\main.js"
  Delete "$INSTDIR\electron\preload.js"
  Delete "$INSTDIR\electron\splash.html"
  Delete "$INSTDIR\electron\package.json"
  Delete "$INSTDIR\electron\package-lock.json"

  ; Python __pycache__ (created at runtime)
  RMDir /r "$INSTDIR\__pycache__"

  Delete "$INSTDIR\uninstall.exe"

  ; ── Prompt 1: downloaded RUNTIME COMPONENTS only (no user data here) ──
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Also remove downloaded components (Node.js, Electron, ffmpeg, Deno)?$\r$\n$\r$\n\
This will free ~350 MB but means re-downloading on next install.$\r$\n\
Choose No to keep them for faster reinstall." \
    /SD IDNO IDNO skip_components

  RMDir /r "$INSTDIR\node_bin"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\ffmpeg_bin"
  RMDir /r "$INSTDIR\electron\node_modules"

  skip_components:

  ; ── Prompt 2: USER DATA (settings, history, cookies, thumbnails, logs) ──
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Also remove your data (settings, download history, cookies, logs)?$\r$\n$\r$\n\
Choose No to keep them for a faster setup on next install." \
    /SD IDNO IDNO skip_userdata

  Delete "$INSTDIR\egm_settings.json"
  Delete "$INSTDIR\egm_history.json"
  Delete "$INSTDIR\cookies.txt"
  RMDir /r "$INSTDIR\thumbnails"
  RMDir /r "$INSTDIR\data"
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\electron-data"
  ; Installed-build Electron userData (package.json "name" = egm-downloader)
  RMDir /r "$APPDATA\egm-downloader"

  skip_userdata:

  ; ── Remove now-empty install dirs (no-op if components/data were kept) ──
  RMDir "$INSTDIR\electron"
  RMDir "$INSTDIR"

  ; ── Start Menu + Desktop shortcuts ──
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir  "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\EGM Downloader.lnk"

  ; ── Registry ──
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "${UNINSTREG}"
SectionEnd
