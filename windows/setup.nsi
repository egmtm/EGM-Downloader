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
!include "nsDialogs.nsh"

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
Var LangCombo        ; combobox on the welcome page
Var SelectedLangCode ; 2-letter code handed off to the app

; ── MUI Settings ─────────────────────────────────────────────
!define MUI_ICON   "${REPO_ROOT}/static/icon.ico"
!define MUI_UNICON "${REPO_ROOT}/static/icon.ico"

; ── Dark skin — colors mirror the app's CSS tokens (see templates) ───────────
; bg #0b1120, surf #111c2e, border #243454, acc #3b82f6, text #e2e8f6
!define MUI_BGCOLOR   "0b1120"
!define MUI_TEXTCOLOR "e2e8f6"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP   "${REPO_ROOT}/windows/assets/installer-header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${REPO_ROOT}/windows/assets/installer-header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP   "${REPO_ROOT}/windows/assets/installer-sidebar.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${REPO_ROOT}/windows/assets/installer-sidebar.bmp"

; Language dropdown lives ON the welcome page (screen 1); choosing there
; retranslates every later page — their strings resolve at page-show.
!define MUI_PAGE_CUSTOMFUNCTION_SHOW  WelcomePage_Show
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE WelcomePage_Leave

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

;  Order matters: the first declared language is the fallback when the OS
;  locale matches none of these ("en" — same default as _detect_os_language).
;  "PortugueseBR": languages/pt.json uses Brazilian conventions ("Salvo",
;  "Configurações"), so the BR variant is the matching NSIS identifier.
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Italian"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Dutch"
!insertmacro MUI_LANGUAGE "PortugueseBR"
!insertmacro MUI_LANGUAGE "Russian"

; ── Welcome-page language selector ────────────────────────────────────────────
; Rows map 1:1, index-aligned, to the codes in LangCodeFromIndex below.
Function WelcomePage_Show
  ; Dark title/body text on the welcome page (MUI_BGCOLOR sets the canvas)
  SetCtlColors $mui.WelcomePage.Title "e2e8f6" "0b1120"
  SetCtlColors $mui.WelcomePage.Text  "8faecf" "0b1120"

  ${NSD_CreateComboBox} 120u 130u 100u 12u ""
  Pop $LangCombo
  SetCtlColors $LangCombo "e2e8f6" "182338"
  ${NSD_CB_AddString} $LangCombo "English"
  ${NSD_CB_AddString} $LangCombo "العربية"
  ${NSD_CB_AddString} $LangCombo "Deutsch"
  ${NSD_CB_AddString} $LangCombo "Español"
  ${NSD_CB_AddString} $LangCombo "Français"
  ${NSD_CB_AddString} $LangCombo "Italiano"
  ${NSD_CB_AddString} $LangCombo "日本語"
  ${NSD_CB_AddString} $LangCombo "Nederlands"
  ${NSD_CB_AddString} $LangCombo "Português"
  ${NSD_CB_AddString} $LangCombo "Русский"

  ; Preselect the row matching $LANGUAGE (NSIS set it from the OS locale)
  StrCpy $0 0
  ${If} $LANGUAGE == ${LANG_ARABIC}
    StrCpy $0 1
  ${ElseIf} $LANGUAGE == ${LANG_GERMAN}
    StrCpy $0 2
  ${ElseIf} $LANGUAGE == ${LANG_SPANISH}
    StrCpy $0 3
  ${ElseIf} $LANGUAGE == ${LANG_FRENCH}
    StrCpy $0 4
  ${ElseIf} $LANGUAGE == ${LANG_ITALIAN}
    StrCpy $0 5
  ${ElseIf} $LANGUAGE == ${LANG_JAPANESE}
    StrCpy $0 6
  ${ElseIf} $LANGUAGE == ${LANG_DUTCH}
    StrCpy $0 7
  ${ElseIf} $LANGUAGE == ${LANG_PORTUGUESEBR}
    StrCpy $0 8
  ${ElseIf} $LANGUAGE == ${LANG_RUSSIAN}
    StrCpy $0 9
  ${EndIf}
  SendMessage $LangCombo ${CB_SETCURSEL} $0 0
FunctionEnd

Function WelcomePage_Leave
  SendMessage $LangCombo ${CB_GETCURSEL} 0 0 $0
  ; index → NSIS language + 2-letter code for the app hand-off
  StrCpy $SelectedLangCode "en"
  StrCpy $LANGUAGE ${LANG_ENGLISH}
  ${If} $0 == 1
    StrCpy $SelectedLangCode "ar"
    StrCpy $LANGUAGE ${LANG_ARABIC}
  ${ElseIf} $0 == 2
    StrCpy $SelectedLangCode "de"
    StrCpy $LANGUAGE ${LANG_GERMAN}
  ${ElseIf} $0 == 3
    StrCpy $SelectedLangCode "es"
    StrCpy $LANGUAGE ${LANG_SPANISH}
  ${ElseIf} $0 == 4
    StrCpy $SelectedLangCode "fr"
    StrCpy $LANGUAGE ${LANG_FRENCH}
  ${ElseIf} $0 == 5
    StrCpy $SelectedLangCode "it"
    StrCpy $LANGUAGE ${LANG_ITALIAN}
  ${ElseIf} $0 == 6
    StrCpy $SelectedLangCode "ja"
    StrCpy $LANGUAGE ${LANG_JAPANESE}
  ${ElseIf} $0 == 7
    StrCpy $SelectedLangCode "nl"
    StrCpy $LANGUAGE ${LANG_DUTCH}
  ${ElseIf} $0 == 8
    StrCpy $SelectedLangCode "pt"
    StrCpy $LANGUAGE ${LANG_PORTUGUESEBR}
  ${ElseIf} $0 == 9
    StrCpy $SelectedLangCode "ru"
    StrCpy $LANGUAGE ${LANG_RUSSIAN}
  ${EndIf}
FunctionEnd

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
  ; ── Guard: never install over a RUNNING app (locked files → corrupt/partial
  ;    copy or silent failure). nsProcess isn't in our build environment, so we
  ;    detect with tasklist piped to find: find's exit code is 0 only when the
  ;    image name appears in tasklist's output. We match the IMAGE NAME (not
  ;    tasklist's "no tasks" line, which is localized), so this is locale-robust.
  ;    Both the launcher and the renamed Electron runtime run as
  ;    "EGM Downloader.exe", so this one image name covers the whole app. ──
  check_running:
    nsExec::ExecToStack 'cmd /c tasklist /FI "IMAGENAME eq ${APPNAME}.exe" /NH | find /I "${APPNAME}.exe"'
    Pop $0   ; process exit code (= find's: 0 = running, 1 = not running)
    Pop $1   ; captured stdout (unused)
    ${If} $0 == 0
      MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
        "${APPNAME} is currently running.$\r$\n$\r$\n\
Close it before continuing, or let the installer close it for you.$\r$\n$\r$\n\
OK      →  Close it for me$\r$\n\
Cancel  →  Cancel installation" \
        /SD IDOK IDOK kill_running
      Abort "Installation cancelled — please close ${APPNAME} and run the installer again."
      kill_running:
        ; Same image name as the uninstaller's kill; /T also takes child processes.
        nsExec::Exec 'taskkill /F /T /IM "${APPNAME}.exe"'
        Sleep 1000
        Goto check_running   ; re-verify it actually closed before we write files
    ${EndIf}

  SetOutPath "$INSTDIR"

  ; ── Root files ──
  File "${REPO_ROOT}/windows/EGM Downloader.exe"
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
  File "${REPO_ROOT}/templates/theme_data.html"
  File "${REPO_ROOT}/templates/theme_validator.html"
  File "${REPO_ROOT}/templates/subscriptions.html"

  ; ── templates\js\ ──
  SetOutPath "$INSTDIR\templates\js"
  File "${REPO_ROOT}/templates/js/_core.html"
  File "${REPO_ROOT}/templates/js/_settings.html"
  File "${REPO_ROOT}/templates/js/_download.html"
  File "${REPO_ROOT}/templates/js/_bulk.html"
  File "${REPO_ROOT}/templates/js/_nav_history.html"
  File "${REPO_ROOT}/templates/js/_theme.html"
  File "${REPO_ROOT}/templates/js/_quality.html"
  File "${REPO_ROOT}/templates/js/_creator.html"

  ; ── languages\ ──
  SetOutPath "$INSTDIR\languages"
  File "${REPO_ROOT}/languages/ar.json"
  File "${REPO_ROOT}/languages/de.json"
  File "${REPO_ROOT}/languages/en.json"
  File "${REPO_ROOT}/languages/es.json"
  File "${REPO_ROOT}/languages/fr.json"
  File "${REPO_ROOT}/languages/it.json"
  File "${REPO_ROOT}/languages/ja.json"
  File "${REPO_ROOT}/languages/nl.json"
  File "${REPO_ROOT}/languages/pt.json"
  File "${REPO_ROOT}/languages/ru.json"

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
  ; One-time language hand-off: the app reads, validates against its own
  ; allowlist, persists to egm_settings.json, and deletes this file.
  ${If} $SelectedLangCode != ""
    FileOpen $0 "$INSTDIR\first-run-language.txt" w
    FileWrite $0 "$SelectedLangCode"
    FileClose $0
  ${EndIf}

  WriteRegStr HKCU "${REGKEY}" "Version"     "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Language"    "$LANGUAGE"
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
Function un.onInit
  ; Come up in the language chosen at install time (falls back to OS locale)
  ReadRegStr $0 HKCU "${REGKEY}" "Language"
  ${If} $0 != ""
    StrCpy $LANGUAGE $0
  ${EndIf}
FunctionEnd

Section "Uninstall"
  ; ── Close the app if it's still running, so files aren't locked ──
  ; Both the launcher and the renamed Electron runtime use this image name.
  nsExec::Exec 'taskkill /F /T /IM "EGM Downloader.exe"'
  Sleep 500

  ; ── Remove app files ──
  Delete "$INSTDIR\EGM Downloader.exe"
  Delete "$INSTDIR\launch.py"
  Delete "$INSTDIR\instructions.txt"
  Delete "$INSTDIR\app.py"
  Delete "$INSTDIR\rcedit-x64.exe"
  Delete "$INSTDIR\patchnotes.txt"
  Delete "$INSTDIR\first-run-language.txt"

  RMDir /r "$INSTDIR\templates"
  RMDir /r "$INSTDIR\static"
  RMDir /r "$INSTDIR\languages"

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
  RMDir /r "$INSTDIR\python"
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
  Delete "$INSTDIR\egm_subscriptions.json"
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
