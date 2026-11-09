; ============================================================
;  EGM Downloader — NSIS Installer (Unified Repo Build)
;  www.egerena.com
;
;  Required command-line defines (passed by BUILD.sh):
;    -DVERSION=0.93
;    -DBUILD=94
;    -DREPO_ROOT=/path/to/EGM-Downloader     (absolute, no trailing slash)
;    -DAPP_FOLDER=/path/to/dist/win-unpacked (the installer folder: Electron,
;                                             Python and the app, signed exe)
;    -DAPP_FOLDER_LIST=/path/to/dist/win-unpacked-files.nsh
;                                            (windows/installer/uninstall_list.py
;                                             writes it from APP_FOLDER)
;    -DOUTFILE=/path/to/dist/egm-setup.exe   (absolute output path)
;
;  Compile (from repo root), after windows/BUILD.sh built and the exe was signed:
;    makensis -DVERSION=0.93 -DBUILD=94 \
;             -DREPO_ROOT="$(pwd)" \
;             -DAPP_FOLDER="$(pwd)/dist/win-unpacked" \
;             -DAPP_FOLDER_LIST="$(pwd)/dist/win-unpacked-files.nsh" \
;             -DOUTFILE="$(pwd)/dist/egm-setup.exe" \
;             windows/setup.nsi
; ============================================================

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "StrFunc.nsh"
${Using:StrFunc} StrStr
${Using:StrFunc} UnStrStr

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
!ifndef APP_FOLDER
  !error "APP_FOLDER must be passed via -DAPP_FOLDER="
!endif
!ifndef APP_FOLDER_LIST
  !error "APP_FOLDER_LIST must be passed via -DAPP_FOLDER_LIST="
!endif

; EGM_REMOVE_APP_FOLDER: one Delete per top level file of APP_FOLDER, one RMDir /r per top level
; folder (resources, locales). Generated at build time, so it follows the Electron version.
!include "${APP_FOLDER_LIST}"

; ── The installed layout of v1.5.0 to v1.5.2.3 (launcher + launch.py + downloaded Electron) ──
; Its program files, by name only: never a wildcard on the install root, never anything not
; listed. User data, logs, ffmpeg_bin, runtime (Deno) and anything unknown are not touched.
; The old launcher "EGM Downloader.exe" is not here: the new exe is written over it.
; electron goes first and launch.py last: launch.py is what marks this layout, so a run cut short
; between two steps leaves a folder that is still seen as this layout, and the next run finishes it.
!macro EGM_REMOVE_OLD_LAYOUT
  RMDir /r "$INSTDIR\electron"
  RMDir /r "$INSTDIR\node_bin"
  RMDir /r "$INSTDIR\__pycache__"
  RMDir /r "$INSTDIR\templates"
  RMDir /r "$INSTDIR\static"
  RMDir /r "$INSTDIR\languages"
  Delete "$INSTDIR\launch.vbs"
  Delete "$INSTDIR\launch.bat"
  Delete "$INSTDIR\rcedit-x64.exe"
  Delete "$INSTDIR\rcedit_tmp.exe"
  Delete "$INSTDIR\.electron-update"
  Delete "$INSTDIR\embedded-python-setup.log"
  Delete "$INSTDIR\patchnotes.txt"
  Delete "$INSTDIR\app.py"
  Delete "$INSTDIR\launch.py"
!macroend

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
Var SelectedLangCode ; 2-letter code handed off to the app

; ── MUI Settings ─────────────────────────────────────────────
!define MUI_ICON   "${REPO_ROOT}/static/icon.ico"
!define MUI_UNICON "${REPO_ROOT}/static/icon.ico"

; ── Dark skin — colors mirror the app's CSS tokens (see templates) ───────────
; bg #0b1120, surf #111c2e, border #243454, acc #3b82f6, text #e2e8f6
; Checkbox/radio text ignores SetCtlColors while UXTHEME draws it (NSIS bug
; #443); MUI2 only strips theming in high-contrast mode UNLESS this is defined.
!define MUI_FORCECLASSICCONTROLS
!define MUI_BGCOLOR   "0b1120"
!define MUI_TEXTCOLOR "e2e8f6"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP   "${REPO_ROOT}/windows/assets/installer-header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${REPO_ROOT}/windows/assets/installer-header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP   "${REPO_ROOT}/windows/assets/installer-sidebar.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${REPO_ROOT}/windows/assets/installer-sidebar.bmp"

; Language dropdown lives ON the welcome page (screen 1); choosing there
; retranslates every later page — their strings resolve at page-show.
!define MUI_PAGE_CUSTOMFUNCTION_PRE   WelcomePage_Pre
!define MUI_PAGE_CUSTOMFUNCTION_SHOW  WelcomePage_Show
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE WelcomePage_Leave

!define MUI_WELCOMEPAGE_TITLE   "$(EGM_WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT    "$(EGM_WELCOME_TEXT)"

!define MUI_DIRECTORYPAGE_TEXT_TOP "$(EGM_DIRECTORY_TEXT)"
; Directory path box + InstFiles progress/details log — the two remaining
; controls MUI_BGCOLOR/MUI_TEXTCOLOR don't reach (those only cover the
; header, Welcome, and Finish pages; confirmed via NSIS's own Directory.nsh
; and InstallFiles.nsh, not assumed).
!define MUI_DIRECTORYPAGE_BGCOLOR   "182338"
!define MUI_DIRECTORYPAGE_TEXTCOLOR "e2e8f6"
!define MUI_INSTFILESPAGE_COLORS    "e2e8f6 0b1120"

!define MUI_FINISHPAGE_RUN      "$INSTDIR\EGM Downloader.exe"
!define MUI_FINISHPAGE_RUN_TEXT "$(EGM_FINISH_RUN)"
!define MUI_FINISHPAGE_RUN_FUNCTION FinishPage_LaunchApp
!define MUI_FINISHPAGE_TITLE    "$(EGM_FINISH_TITLE)"
!define MUI_FINISHPAGE_TEXT     "$(EGM_FINISH_TEXT)"
!define MUI_FINISHPAGE_SHOWREADME        ""
!define MUI_FINISHPAGE_SHOWREADME_TEXT   "$(EGM_FINISH_SHORTCUT)"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION FinishPage_CreateDesktopShortcut

; ── Pages ────────────────────────────────────────────────────
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_PRE DirectoryPage_Pre
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

; SetCompressor is /SOLID lzma (see top of file) — under solid compression,
; files must be reserved to be accessible before the rest of the data block
; is decompressed. Without this, MUI_LANGDLL_DISPLAY (called from .onInit,
; necessarily before most of the installer's data is needed) can fail to
; show or behave unpredictably. Documented NSIS requirement, not optional
; under solid compression.
!insertmacro MUI_RESERVEFILE_LANGDLL

; ── Installer strings — 10 languages (source: v1.3 translation table) ───────────
LangString EGM_WELCOME_TITLE ${LANG_ENGLISH} "Welcome to EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_ARABIC} "مرحباً بك في EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_GERMAN} "Willkommen bei EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_SPANISH} "Bienvenido a EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_FRENCH} "Bienvenue dans EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_ITALIAN} "Benvenuto in EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_JAPANESE} "EGM Downloader v${VERSION} へようこそ"
LangString EGM_WELCOME_TITLE ${LANG_DUTCH} "Welkom bij EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_PORTUGUESEBR} "Bem-vindo ao EGM Downloader v${VERSION}"
LangString EGM_WELCOME_TITLE ${LANG_RUSSIAN} "Добро пожаловать в EGM Downloader v${VERSION}"

LangString EGM_WELCOME_TEXT ${LANG_ENGLISH} "This will install EGM Downloader v${VERSION} on your computer.$\r$\nEverything it needs is included. On first launch, ffmpeg and Deno are downloaded automatically.$\r$\nClick Next to continue."
LangString EGM_WELCOME_TEXT ${LANG_ARABIC} "سيؤدي هذا إلى تثبيت EGM Downloader v${VERSION} على جهازك.$\r$\nكل ما يحتاجه التطبيق مضمّن. عند التشغيل الأول، سيتم تنزيل ffmpeg وDeno تلقائياً.$\r$\nانقر على $\"التالي$\" للمتابعة."
LangString EGM_WELCOME_TEXT ${LANG_GERMAN} "Hiermit wird EGM Downloader v${VERSION} auf deinem Computer installiert.$\r$\nAlles, was die App braucht, ist enthalten. Beim ersten Start werden ffmpeg und Deno automatisch heruntergeladen.$\r$\nKlicke auf Weiter, um fortzufahren."
LangString EGM_WELCOME_TEXT ${LANG_SPANISH} "Esto instalará EGM Downloader v${VERSION} en tu equipo.$\r$\nTodo lo que necesita ya está incluido. En el primer inicio, ffmpeg y Deno se descargarán automáticamente.$\r$\nHaz clic en Siguiente para continuar."
LangString EGM_WELCOME_TEXT ${LANG_FRENCH} "Ceci va installer EGM Downloader v${VERSION} sur votre ordinateur.$\r$\nTout ce dont l'application a besoin est inclus. Au premier lancement, ffmpeg et Deno seront téléchargés automatiquement.$\r$\nCliquez sur Suivant pour continuer."
LangString EGM_WELCOME_TEXT ${LANG_ITALIAN} "Questo installerà EGM Downloader v${VERSION} sul tuo computer.$\r$\nTutto il necessario è incluso. Al primo avvio, ffmpeg e Deno verranno scaricati automaticamente.$\r$\nFai clic su Avanti per continuare."
LangString EGM_WELCOME_TEXT ${LANG_JAPANESE} "これにより、EGM Downloader v${VERSION}がこのコンピューターにインストールされます。$\r$\n必要なものはすべて含まれています。初回起動時に、ffmpegとDenoが自動的にダウンロードされます。$\r$\n「次へ」をクリックして続行してください。"
LangString EGM_WELCOME_TEXT ${LANG_DUTCH} "Hiermee wordt EGM Downloader v${VERSION} op je computer geïnstalleerd.$\r$\nAlles wat de app nodig heeft, is inbegrepen. Bij de eerste start worden ffmpeg en Deno automatisch gedownload.$\r$\nKlik op Volgende om door te gaan."
LangString EGM_WELCOME_TEXT ${LANG_PORTUGUESEBR} "Isso instalará o EGM Downloader v${VERSION} no seu computador.$\r$\nTudo o que é necessário está incluído. Na primeira execução, o ffmpeg e o Deno serão baixados automaticamente.$\r$\nClique em Próximo para continuar."
LangString EGM_WELCOME_TEXT ${LANG_RUSSIAN} "Будет выполнена установка EGM Downloader v${VERSION} на ваш компьютер.$\r$\nВсё необходимое уже входит в комплект. При первом запуске ffmpeg и Deno будут загружены автоматически.$\r$\nНажмите «Далее», чтобы продолжить."

LangString EGM_DIRECTORY_TEXT ${LANG_ENGLISH} "Choose the folder where EGM Downloader will be installed."
LangString EGM_DIRECTORY_TEXT ${LANG_ARABIC} "اختر المجلد الذي سيتم تثبيت EGM Downloader فيه."
LangString EGM_DIRECTORY_TEXT ${LANG_GERMAN} "Wähle den Ordner, in dem EGM Downloader installiert werden soll."
LangString EGM_DIRECTORY_TEXT ${LANG_SPANISH} "Elige la carpeta donde se instalará EGM Downloader."
LangString EGM_DIRECTORY_TEXT ${LANG_FRENCH} "Choisissez le dossier où EGM Downloader sera installé."
LangString EGM_DIRECTORY_TEXT ${LANG_ITALIAN} "Scegli la cartella in cui verrà installato EGM Downloader."
LangString EGM_DIRECTORY_TEXT ${LANG_JAPANESE} "EGM Downloader をインストールするフォルダを選択してください。"
LangString EGM_DIRECTORY_TEXT ${LANG_DUTCH} "Kies de map waarin EGM Downloader wordt geïnstalleerd."
LangString EGM_DIRECTORY_TEXT ${LANG_PORTUGUESEBR} "Escolha a pasta onde o EGM Downloader será instalado."
LangString EGM_DIRECTORY_TEXT ${LANG_RUSSIAN} "Выберите папку, в которую будет установлен EGM Downloader."

LangString EGM_FINISH_TITLE ${LANG_ENGLISH} "Installation Complete"
LangString EGM_FINISH_TITLE ${LANG_ARABIC} "اكتمل التثبيت"
LangString EGM_FINISH_TITLE ${LANG_GERMAN} "Installation abgeschlossen"
LangString EGM_FINISH_TITLE ${LANG_SPANISH} "Instalación completa"
LangString EGM_FINISH_TITLE ${LANG_FRENCH} "Installation terminée"
LangString EGM_FINISH_TITLE ${LANG_ITALIAN} "Installazione completata"
LangString EGM_FINISH_TITLE ${LANG_JAPANESE} "インストール完了"
LangString EGM_FINISH_TITLE ${LANG_DUTCH} "Installatie voltooid"
LangString EGM_FINISH_TITLE ${LANG_PORTUGUESEBR} "Instalação concluída"
LangString EGM_FINISH_TITLE ${LANG_RUSSIAN} "Установка завершена"

LangString EGM_FINISH_TEXT ${LANG_ENGLISH} "EGM Downloader v${VERSION} has been installed.$\r$\nOn first launch, ffmpeg and Deno are downloaded in the background."
LangString EGM_FINISH_TEXT ${LANG_ARABIC} "تم تثبيت EGM Downloader v${VERSION}.$\r$\nعند التشغيل الأول، سيتم تنزيل ffmpeg وDeno في الخلفية."
LangString EGM_FINISH_TEXT ${LANG_GERMAN} "EGM Downloader v${VERSION} wurde installiert.$\r$\nBeim ersten Start werden ffmpeg und Deno im Hintergrund heruntergeladen."
LangString EGM_FINISH_TEXT ${LANG_SPANISH} "EGM Downloader v${VERSION} se ha instalado.$\r$\nEn el primer inicio, ffmpeg y Deno se descargan en segundo plano."
LangString EGM_FINISH_TEXT ${LANG_FRENCH} "EGM Downloader v${VERSION} a été installé.$\r$\nAu premier lancement, ffmpeg et Deno sont téléchargés en arrière-plan."
LangString EGM_FINISH_TEXT ${LANG_ITALIAN} "EGM Downloader v${VERSION} è stato installato.$\r$\nAl primo avvio, ffmpeg e Deno vengono scaricati in background."
LangString EGM_FINISH_TEXT ${LANG_JAPANESE} "EGM Downloader v${VERSION}がインストールされました。$\r$\n初回起動時に、ffmpegとDenoがバックグラウンドでダウンロードされます。"
LangString EGM_FINISH_TEXT ${LANG_DUTCH} "EGM Downloader v${VERSION} is geïnstalleerd.$\r$\nBij de eerste start worden ffmpeg en Deno op de achtergrond gedownload."
LangString EGM_FINISH_TEXT ${LANG_PORTUGUESEBR} "O EGM Downloader v${VERSION} foi instalado.$\r$\nNa primeira execução, o ffmpeg e o Deno são baixados em segundo plano."
LangString EGM_FINISH_TEXT ${LANG_RUSSIAN} "EGM Downloader v${VERSION} установлен.$\r$\nПри первом запуске ffmpeg и Deno загружаются в фоновом режиме."

LangString EGM_FINISH_RUN ${LANG_ENGLISH} "Launch EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_ARABIC} "تشغيل EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_GERMAN} "EGM Downloader starten"
LangString EGM_FINISH_RUN ${LANG_SPANISH} "Iniciar EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_FRENCH} "Lancer EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_ITALIAN} "Avvia EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_JAPANESE} "EGM Downloader を起動"
LangString EGM_FINISH_RUN ${LANG_DUTCH} "EGM Downloader starten"
LangString EGM_FINISH_RUN ${LANG_PORTUGUESEBR} "Iniciar EGM Downloader"
LangString EGM_FINISH_RUN ${LANG_RUSSIAN} "Запустить EGM Downloader"

LangString EGM_FINISH_SHORTCUT ${LANG_ENGLISH} "Add shortcut to desktop"
LangString EGM_FINISH_SHORTCUT ${LANG_ARABIC} "إضافة اختصار إلى سطح المكتب"
LangString EGM_FINISH_SHORTCUT ${LANG_GERMAN} "Verknüpfung auf dem Desktop hinzufügen"
LangString EGM_FINISH_SHORTCUT ${LANG_SPANISH} "Agregar acceso directo al escritorio"
LangString EGM_FINISH_SHORTCUT ${LANG_FRENCH} "Ajouter un raccourci sur le bureau"
LangString EGM_FINISH_SHORTCUT ${LANG_ITALIAN} "Aggiungi collegamento al desktop"
LangString EGM_FINISH_SHORTCUT ${LANG_JAPANESE} "デスクトップにショートカットを追加"
LangString EGM_FINISH_SHORTCUT ${LANG_DUTCH} "Snelkoppeling toevoegen aan bureaublad"
LangString EGM_FINISH_SHORTCUT ${LANG_PORTUGUESEBR} "Adicionar atalho à área de trabalho"
LangString EGM_FINISH_SHORTCUT ${LANG_RUSSIAN} "Добавить ярлык на рабочий стол"

LangString EGM_ALREADY_INSTALLED ${LANG_ENGLISH} "EGM Downloader v${VERSION} is already installed.$\r$\nYes → Repair (reinstall files, keep settings)$\r$\nNo → Uninstall$\r$\nCancel → Exit"
LangString EGM_ALREADY_INSTALLED ${LANG_ARABIC} "EGM Downloader v${VERSION} مثبت بالفعل.$\r$\nنعم ← إصلاح (إعادة تثبيت الملفات مع الإبقاء على الإعدادات)$\r$\nلا ← إلغاء التثبيت$\r$\nإلغاء ← خروج"
LangString EGM_ALREADY_INSTALLED ${LANG_GERMAN} "EGM Downloader v${VERSION} ist bereits installiert.$\r$\nJa → Reparieren (Dateien neu installieren, Einstellungen behalten)$\r$\nNein → Deinstallieren$\r$\nAbbrechen → Beenden"
LangString EGM_ALREADY_INSTALLED ${LANG_SPANISH} "EGM Downloader v${VERSION} ya está instalado.$\r$\nSí → Reparar (reinstalar archivos, conservar configuración)$\r$\nNo → Desinstalar$\r$\nCancelar → Salir"
LangString EGM_ALREADY_INSTALLED ${LANG_FRENCH} "EGM Downloader v${VERSION} est déjà installé.$\r$\nOui → Réparer (réinstaller les fichiers, conserver les paramètres)$\r$\nNon → Désinstaller$\r$\nAnnuler → Quitter"
LangString EGM_ALREADY_INSTALLED ${LANG_ITALIAN} "EGM Downloader v${VERSION} è già installato.$\r$\nSì → Ripara (reinstalla i file, mantieni le impostazioni)$\r$\nNo → Disinstalla$\r$\nAnnulla → Esci"
LangString EGM_ALREADY_INSTALLED ${LANG_JAPANESE} "EGM Downloader v${VERSION} は既にインストールされています。$\r$\nはい → 修復（ファイルを再インストールし、設定は保持）$\r$\nいいえ → アンインストール$\r$\nキャンセル → 終了"
LangString EGM_ALREADY_INSTALLED ${LANG_DUTCH} "EGM Downloader v${VERSION} is al geïnstalleerd.$\r$\nJa → Herstellen (bestanden opnieuw installeren, instellingen behouden)$\r$\nNee → Verwijderen$\r$\nAnnuleren → Afsluiten"
LangString EGM_ALREADY_INSTALLED ${LANG_PORTUGUESEBR} "O EGM Downloader v${VERSION} já está instalado.$\r$\nSim → Reparar (reinstalar arquivos, manter configurações)$\r$\nNão → Desinstalar$\r$\nCancelar → Sair"
LangString EGM_ALREADY_INSTALLED ${LANG_RUSSIAN} "EGM Downloader v${VERSION} уже установлен.$\r$\nДа → Восстановить (переустановить файлы, сохранить настройки)$\r$\nНет → Удалить$\r$\nОтмена → Выход"

LangString EGM_APP_RUNNING ${LANG_ENGLISH} "EGM Downloader is currently running.$\r$\nClose it before continuing, or let the installer close it for you.$\r$\nOK → Close it for me$\r$\nCancel → Cancel installation"
LangString EGM_APP_RUNNING ${LANG_ARABIC} "EGM Downloader قيد التشغيل حالياً.$\r$\nأغلقه قبل المتابعة، أو دع المثبت يغلقه نيابة عنك.$\r$\nموافق ← إغلاقه نيابة عني$\r$\nإلغاء ← إيقاف التثبيت"
LangString EGM_APP_RUNNING ${LANG_GERMAN} "EGM Downloader wird gerade ausgeführt.$\r$\nSchließe es, bevor du fortfährst, oder lasse es vom Installationsprogramm für dich schließen.$\r$\nOK → Für mich schließen$\r$\nAbbrechen → Installation abbrechen"
LangString EGM_APP_RUNNING ${LANG_SPANISH} "EGM Downloader se está ejecutando actualmente.$\r$\nCiérralo antes de continuar, o deja que el instalador lo cierre por ti.$\r$\nAceptar → Cerrarlo por mí$\r$\nCancelar → Cancelar instalación"
LangString EGM_APP_RUNNING ${LANG_FRENCH} "EGM Downloader est actuellement en cours d'exécution.$\r$\nFermez-le avant de continuer, ou laissez l'installateur le fermer pour vous.$\r$\nOK → Le fermer pour moi$\r$\nAnnuler → Annuler l'installation"
LangString EGM_APP_RUNNING ${LANG_ITALIAN} "EGM Downloader è attualmente in esecuzione.$\r$\nChiudilo prima di continuare, oppure lascia che il programma di installazione lo chiuda per te.$\r$\nOK → Chiudilo per me$\r$\nAnnulla → Annulla installazione"
LangString EGM_APP_RUNNING ${LANG_JAPANESE} "EGM Downloader は現在実行中です。$\r$\n続行する前に終了するか、インストーラーに終了させてください。$\r$\nOK → 代わりに終了する$\r$\nキャンセル → インストールを中止"
LangString EGM_APP_RUNNING ${LANG_DUTCH} "EGM Downloader wordt momenteel uitgevoerd.$\r$\nSluit het voordat je doorgaat, of laat het installatieprogramma het voor je sluiten.$\r$\nOK → Sluit het voor mij$\r$\nAnnuleren → Installatie annuleren"
LangString EGM_APP_RUNNING ${LANG_PORTUGUESEBR} "O EGM Downloader está em execução no momento.$\r$\nFeche-o antes de continuar, ou deixe o instalador fechá-lo para você.$\r$\nOK → Fechar para mim$\r$\nCancelar → Cancelar instalação"
LangString EGM_APP_RUNNING ${LANG_RUSSIAN} "EGM Downloader сейчас запущен.$\r$\nЗакройте его перед продолжением или позвольте установщику закрыть его за вас.$\r$\nОК → Закрыть за меня$\r$\nОтмена → Отменить установку"

LangString EGM_APP_STILL_RUNNING ${LANG_ENGLISH} "${APPNAME} is still running and could not be closed.$\r$\nNothing was changed. Quit it from the tray icon (or end it in Task Manager), then run the installer again."
LangString EGM_APP_STILL_RUNNING ${LANG_ARABIC} "ما زال ${APPNAME} قيد التشغيل وتعذّر إغلاقه.$\r$\nلم يتم تغيير أي شيء. أغلقه من أيقونة منطقة الإشعارات (أو أنهِه من إدارة المهام)، ثم شغّل المثبت مرة أخرى."
LangString EGM_APP_STILL_RUNNING ${LANG_GERMAN} "${APPNAME} läuft noch und konnte nicht geschlossen werden.$\r$\nEs wurde nichts geändert. Beende es über das Symbol im Infobereich (oder im Task-Manager) und starte das Installationsprogramm dann erneut."
LangString EGM_APP_STILL_RUNNING ${LANG_SPANISH} "${APPNAME} sigue en ejecución y no se pudo cerrar.$\r$\nNo se ha cambiado nada. Ciérralo desde el icono de la bandeja del sistema (o finalízalo en el Administrador de tareas) y vuelve a ejecutar el instalador."
LangString EGM_APP_STILL_RUNNING ${LANG_FRENCH} "${APPNAME} est toujours en cours d'exécution et n'a pas pu être fermé.$\r$\nRien n'a été modifié. Quittez-le depuis l'icône de la zone de notification (ou terminez-le dans le Gestionnaire des tâches), puis relancez l'installateur."
LangString EGM_APP_STILL_RUNNING ${LANG_ITALIAN} "${APPNAME} è ancora in esecuzione e non è stato possibile chiuderlo.$\r$\nNon è stato modificato nulla. Chiudilo dall'icona nell'area di notifica (o terminalo da Gestione attività), poi esegui di nuovo il programma di installazione."
LangString EGM_APP_STILL_RUNNING ${LANG_JAPANESE} "${APPNAME} はまだ実行中で、終了できませんでした。$\r$\n何も変更されていません。タスクトレイのアイコンから終了するか、タスクマネージャーで終了してから、インストーラーをもう一度実行してください。"
LangString EGM_APP_STILL_RUNNING ${LANG_DUTCH} "${APPNAME} draait nog en kon niet worden gesloten.$\r$\nEr is niets gewijzigd. Sluit het af via het pictogram in het systeemvak (of beëindig het in Taakbeheer) en voer het installatieprogramma daarna opnieuw uit."
LangString EGM_APP_STILL_RUNNING ${LANG_PORTUGUESEBR} "O ${APPNAME} ainda está em execução e não foi possível fechá-lo.$\r$\nNada foi alterado. Saia dele pelo ícone da bandeja do sistema (ou encerre-o no Gerenciador de Tarefas) e execute o instalador novamente."
LangString EGM_APP_STILL_RUNNING ${LANG_RUSSIAN} "${APPNAME} всё ещё запущен, и его не удалось закрыть.$\r$\nНичего не изменено. Выйдите из программы через значок в области уведомлений (или завершите её в диспетчере задач), затем снова запустите установщик."

LangString EGM_INSTALL_CANCELLED ${LANG_ENGLISH} "Installation cancelled — please close ${APPNAME} and run the installer again."
LangString EGM_INSTALL_CANCELLED ${LANG_ARABIC} "تم إيقاف التثبيت. أغلق ${APPNAME} ثم شغّل المثبت مرة أخرى."
LangString EGM_INSTALL_CANCELLED ${LANG_GERMAN} "Installation abgebrochen. Bitte schließe ${APPNAME} und starte das Installationsprogramm erneut."
LangString EGM_INSTALL_CANCELLED ${LANG_SPANISH} "Instalación cancelada. Cierra ${APPNAME} y vuelve a ejecutar el instalador."
LangString EGM_INSTALL_CANCELLED ${LANG_FRENCH} "Installation annulée. Veuillez fermer ${APPNAME} et relancer l'installateur."
LangString EGM_INSTALL_CANCELLED ${LANG_ITALIAN} "Installazione annullata. Chiudi ${APPNAME} ed esegui di nuovo il programma di installazione."
LangString EGM_INSTALL_CANCELLED ${LANG_JAPANESE} "インストールを中止しました。${APPNAME} を終了してから、インストーラーをもう一度実行してください。"
LangString EGM_INSTALL_CANCELLED ${LANG_DUTCH} "Installatie geannuleerd. Sluit ${APPNAME} en voer het installatieprogramma opnieuw uit."
LangString EGM_INSTALL_CANCELLED ${LANG_PORTUGUESEBR} "Instalação cancelada. Feche o ${APPNAME} e execute o instalador novamente."
LangString EGM_INSTALL_CANCELLED ${LANG_RUSSIAN} "Установка отменена. Закройте ${APPNAME} и снова запустите установщик."

LangString EGM_APP_RUNNING_ANY_COPY ${LANG_ENGLISH} "EGM Downloader is running, and the installer could not tell which copy it is.$\r$\nClosing it closes every EGM Downloader running on this computer, a portable copy too.$\r$\nOK → Close them all$\r$\nCancel → Cancel installation"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_ARABIC} "EGM Downloader قيد التشغيل، ولم يتمكن المثبت من تحديد أي نسخة هي.$\r$\nإغلاقه يغلق كل نسخ EGM Downloader العاملة على هذا الكمبيوتر، بما في ذلك النسخة المحمولة.$\r$\nموافق ← إغلاقها كلها$\r$\nإلغاء ← إيقاف التثبيت"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_GERMAN} "EGM Downloader wird ausgeführt, und das Installationsprogramm konnte nicht erkennen, um welche Kopie es sich handelt.$\r$\nBeim Schließen werden alle EGM Downloader auf diesem Computer beendet, auch eine portable Kopie.$\r$\nOK → Alle schließen$\r$\nAbbrechen → Installation abbrechen"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_SPANISH} "EGM Downloader se está ejecutando y el instalador no pudo saber de qué copia se trata.$\r$\nAl cerrarlo se cierran todas las copias de EGM Downloader que se ejecutan en este equipo, también una copia portátil.$\r$\nAceptar → Cerrarlas todas$\r$\nCancelar → Cancelar instalación"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_FRENCH} "EGM Downloader est en cours d'exécution et l'installateur n'a pas pu déterminer de quelle copie il s'agit.$\r$\nLe fermer ferme toutes les copies d'EGM Downloader en cours d'exécution sur cet ordinateur, y compris une copie portable.$\r$\nOK → Toutes les fermer$\r$\nAnnuler → Annuler l'installation"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_ITALIAN} "EGM Downloader è in esecuzione e il programma di installazione non è riuscito a capire di quale copia si tratti.$\r$\nChiuderlo chiude tutte le copie di EGM Downloader in esecuzione su questo computer, anche una copia portatile.$\r$\nOK → Chiudi tutte$\r$\nAnnulla → Annulla installazione"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_JAPANESE} "EGM Downloader は実行中ですが、インストーラーはどのコピーか判別できませんでした。$\r$\n終了すると、このコンピューターで実行中のすべての EGM Downloader が終了します（ポータブル版も含む）。$\r$\nOK → すべて終了する$\r$\nキャンセル → インストールを中止"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_DUTCH} "EGM Downloader draait en het installatieprogramma kon niet bepalen om welke kopie het gaat.$\r$\nAls je het sluit, worden alle exemplaren van EGM Downloader op deze computer gesloten, ook een draagbare kopie.$\r$\nOK → Alles sluiten$\r$\nAnnuleren → Installatie annuleren"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_PORTUGUESEBR} "O EGM Downloader está em execução e o instalador não conseguiu identificar de qual cópia se trata.$\r$\nFechá-lo fecha todas as cópias do EGM Downloader em execução neste computador, inclusive uma cópia portátil.$\r$\nOK → Fechar todas$\r$\nCancelar → Cancelar instalação"
LangString EGM_APP_RUNNING_ANY_COPY ${LANG_RUSSIAN} "EGM Downloader запущен, и установщик не смог определить, какая это копия.$\r$\nЕсли закрыть его, будут закрыты все копии EGM Downloader, запущенные на этом компьютере, в том числе портативная.$\r$\nОК → Закрыть все$\r$\nОтмена → Отменить установку"

LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_ENGLISH} "EGM Downloader is running, and the uninstaller could not tell which copy it is.$\r$\nClosing it closes every EGM Downloader running on this computer, a portable copy too.$\r$\nOK → Close them all$\r$\nCancel → Cancel uninstall"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_ARABIC} "EGM Downloader قيد التشغيل، ولم تتمكن أداة إزالة التثبيت من تحديد أي نسخة هي.$\r$\nإغلاقه يغلق كل نسخ EGM Downloader العاملة على هذا الكمبيوتر، بما في ذلك النسخة المحمولة.$\r$\nموافق ← إغلاقها كلها$\r$\nإلغاء ← إيقاف الإزالة"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_GERMAN} "EGM Downloader wird ausgeführt, und das Deinstallationsprogramm konnte nicht erkennen, um welche Kopie es sich handelt.$\r$\nBeim Schließen werden alle EGM Downloader auf diesem Computer beendet, auch eine portable Kopie.$\r$\nOK → Alle schließen$\r$\nAbbrechen → Deinstallation abbrechen"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_SPANISH} "EGM Downloader se está ejecutando y el desinstalador no pudo saber de qué copia se trata.$\r$\nAl cerrarlo se cierran todas las copias de EGM Downloader que se ejecutan en este equipo, también una copia portátil.$\r$\nAceptar → Cerrarlas todas$\r$\nCancelar → Cancelar desinstalación"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_FRENCH} "EGM Downloader est en cours d'exécution et le désinstallateur n'a pas pu déterminer de quelle copie il s'agit.$\r$\nLe fermer ferme toutes les copies d'EGM Downloader en cours d'exécution sur cet ordinateur, y compris une copie portable.$\r$\nOK → Toutes les fermer$\r$\nAnnuler → Annuler la désinstallation"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_ITALIAN} "EGM Downloader è in esecuzione e il programma di disinstallazione non è riuscito a capire di quale copia si tratti.$\r$\nChiuderlo chiude tutte le copie di EGM Downloader in esecuzione su questo computer, anche una copia portatile.$\r$\nOK → Chiudi tutte$\r$\nAnnulla → Annulla disinstallazione"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_JAPANESE} "EGM Downloader は実行中ですが、アンインストーラーはどのコピーか判別できませんでした。$\r$\n終了すると、このコンピューターで実行中のすべての EGM Downloader が終了します（ポータブル版も含む）。$\r$\nOK → すべて終了する$\r$\nキャンセル → アンインストールを中止"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_DUTCH} "EGM Downloader draait en het verwijderprogramma kon niet bepalen om welke kopie het gaat.$\r$\nAls je het sluit, worden alle exemplaren van EGM Downloader op deze computer gesloten, ook een draagbare kopie.$\r$\nOK → Alles sluiten$\r$\nAnnuleren → Verwijderen annuleren"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_PORTUGUESEBR} "O EGM Downloader está em execução e o desinstalador não conseguiu identificar de qual cópia se trata.$\r$\nFechá-lo fecha todas as cópias do EGM Downloader em execução neste computador, inclusive uma cópia portátil.$\r$\nOK → Fechar todas$\r$\nCancelar → Cancelar desinstalação"
LangString EGM_UN_APP_RUNNING_ANY_COPY ${LANG_RUSSIAN} "EGM Downloader запущен, и программа удаления не смогла определить, какая это копия.$\r$\nЕсли закрыть его, будут закрыты все копии EGM Downloader, запущенные на этом компьютере, в том числе портативная.$\r$\nОК → Закрыть все$\r$\nОтмена → Отменить удаление"

LangString EGM_UN_APP_RUNNING ${LANG_ENGLISH} "EGM Downloader is currently running.$\r$\nClose it before continuing, or let the uninstaller close it for you.$\r$\nOK → Close it for me$\r$\nCancel → Cancel uninstall"
LangString EGM_UN_APP_RUNNING ${LANG_ARABIC} "EGM Downloader قيد التشغيل حالياً.$\r$\nأغلقه قبل المتابعة، أو دع أداة إزالة التثبيت تغلقه نيابة عنك.$\r$\nموافق ← إغلاقه نيابة عني$\r$\nإلغاء ← إيقاف الإزالة"
LangString EGM_UN_APP_RUNNING ${LANG_GERMAN} "EGM Downloader wird gerade ausgeführt.$\r$\nSchließe es, bevor du fortfährst, oder lasse es vom Deinstallationsprogramm für dich schließen.$\r$\nOK → Für mich schließen$\r$\nAbbrechen → Deinstallation abbrechen"
LangString EGM_UN_APP_RUNNING ${LANG_SPANISH} "EGM Downloader se está ejecutando actualmente.$\r$\nCiérralo antes de continuar, o deja que el desinstalador lo cierre por ti.$\r$\nAceptar → Cerrarlo por mí$\r$\nCancelar → Cancelar desinstalación"
LangString EGM_UN_APP_RUNNING ${LANG_FRENCH} "EGM Downloader est actuellement en cours d'exécution.$\r$\nFermez-le avant de continuer, ou laissez le désinstallateur le fermer pour vous.$\r$\nOK → Le fermer pour moi$\r$\nAnnuler → Annuler la désinstallation"
LangString EGM_UN_APP_RUNNING ${LANG_ITALIAN} "EGM Downloader è attualmente in esecuzione.$\r$\nChiudilo prima di continuare, oppure lascia che il programma di disinstallazione lo chiuda per te.$\r$\nOK → Chiudilo per me$\r$\nAnnulla → Annulla disinstallazione"
LangString EGM_UN_APP_RUNNING ${LANG_JAPANESE} "EGM Downloader は現在実行中です。$\r$\n続行する前に終了するか、アンインストーラーに終了させてください。$\r$\nOK → 代わりに終了する$\r$\nキャンセル → アンインストールを中止"
LangString EGM_UN_APP_RUNNING ${LANG_DUTCH} "EGM Downloader wordt momenteel uitgevoerd.$\r$\nSluit het voordat je doorgaat, of laat het verwijderprogramma het voor je sluiten.$\r$\nOK → Sluit het voor mij$\r$\nAnnuleren → Verwijderen annuleren"
LangString EGM_UN_APP_RUNNING ${LANG_PORTUGUESEBR} "O EGM Downloader está em execução no momento.$\r$\nFeche-o antes de continuar, ou deixe o desinstalador fechá-lo para você.$\r$\nOK → Fechar para mim$\r$\nCancelar → Cancelar desinstalação"
LangString EGM_UN_APP_RUNNING ${LANG_RUSSIAN} "EGM Downloader сейчас запущен.$\r$\nЗакройте его перед продолжением или позвольте программе удаления закрыть его за вас.$\r$\nОК → Закрыть за меня$\r$\nОтмена → Отменить удаление"

LangString EGM_UN_APP_STILL_RUNNING ${LANG_ENGLISH} "EGM Downloader is still running and could not be closed.$\r$\nNothing was removed. Quit it from the tray icon (or end it in Task Manager), then run the uninstaller again."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_ARABIC} "EGM Downloader ما زال قيد التشغيل وتعذّر إغلاقه.$\r$\nلم تتم إزالة أي شيء. أغلقه من أيقونة منطقة الإشعارات (أو أنهِه من إدارة المهام)، ثم شغّل أداة إزالة التثبيت مرة أخرى."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_GERMAN} "EGM Downloader läuft noch und konnte nicht geschlossen werden.$\r$\nEs wurde nichts entfernt. Beende es über das Symbol im Infobereich (oder im Task-Manager) und starte das Deinstallationsprogramm dann erneut."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_SPANISH} "EGM Downloader sigue en ejecución y no se pudo cerrar.$\r$\nNo se ha eliminado nada. Ciérralo desde el icono de la bandeja del sistema (o finalízalo en el Administrador de tareas) y vuelve a ejecutar el desinstalador."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_FRENCH} "EGM Downloader est toujours en cours d'exécution et n'a pas pu être fermé.$\r$\nRien n'a été supprimé. Quittez-le depuis l'icône de la zone de notification (ou terminez-le dans le Gestionnaire des tâches), puis relancez le désinstallateur."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_ITALIAN} "EGM Downloader è ancora in esecuzione e non è stato possibile chiuderlo.$\r$\nNon è stato rimosso nulla. Chiudilo dall'icona nell'area di notifica (o terminalo da Gestione attività), poi esegui di nuovo il programma di disinstallazione."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_JAPANESE} "EGM Downloader はまだ実行中で、終了できませんでした。$\r$\n何も削除されていません。タスクトレイのアイコンから終了するか、タスクマネージャーで終了してから、アンインストーラーをもう一度実行してください。"
LangString EGM_UN_APP_STILL_RUNNING ${LANG_DUTCH} "EGM Downloader draait nog en kon niet worden gesloten.$\r$\nEr is niets verwijderd. Sluit het af via het pictogram in het systeemvak (of beëindig het in Taakbeheer) en start het verwijderprogramma daarna opnieuw."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_PORTUGUESEBR} "O EGM Downloader ainda está em execução e não foi possível fechá-lo.$\r$\nNada foi removido. Saia dele pelo ícone da bandeja do sistema (ou encerre-o no Gerenciador de Tarefas) e execute o desinstalador novamente."
LangString EGM_UN_APP_STILL_RUNNING ${LANG_RUSSIAN} "EGM Downloader всё ещё запущен, и его не удалось закрыть.$\r$\nНичего не удалено. Выйдите из программы через значок в области уведомлений (или завершите её в диспетчере задач), затем снова запустите программу удаления."

LangString EGM_FOLDER_NOT_OURS ${LANG_ENGLISH} "This folder is not empty and does not hold an installed copy of EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nA portable copy is not an installed copy. Nothing was changed.$\r$\nRun the installer again and choose an empty folder, or the folder EGM Downloader is installed in."
LangString EGM_FOLDER_NOT_OURS ${LANG_ARABIC} "هذا المجلد ليس فارغاً ولا يحتوي على نسخة مثبتة من EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nالنسخة المحمولة ليست نسخة مثبتة. لم يتم تغيير أي شيء.$\r$\nشغّل المثبت مرة أخرى واختر مجلداً فارغاً، أو المجلد الذي تم تثبيت EGM Downloader فيه."
LangString EGM_FOLDER_NOT_OURS ${LANG_GERMAN} "Dieser Ordner ist nicht leer und enthält keine installierte Kopie von EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nEine portable Kopie ist keine installierte Kopie. Es wurde nichts geändert.$\r$\nStarte das Installationsprogramm erneut und wähle einen leeren Ordner oder den Ordner, in dem EGM Downloader installiert ist."
LangString EGM_FOLDER_NOT_OURS ${LANG_SPANISH} "Esta carpeta no está vacía y no contiene una copia instalada de EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nUna copia portátil no es una copia instalada. No se ha cambiado nada.$\r$\nVuelve a ejecutar el instalador y elige una carpeta vacía o la carpeta en la que está instalado EGM Downloader."
LangString EGM_FOLDER_NOT_OURS ${LANG_FRENCH} "Ce dossier n'est pas vide et ne contient pas de copie installée d'EGM Downloader :$\r$\n$INSTDIR$\r$\n$\r$\nUne copie portable n'est pas une copie installée. Rien n'a été modifié.$\r$\nRelancez l'installateur et choisissez un dossier vide, ou le dossier dans lequel EGM Downloader est installé."
LangString EGM_FOLDER_NOT_OURS ${LANG_ITALIAN} "Questa cartella non è vuota e non contiene una copia installata di EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nUna copia portatile non è una copia installata. Non è stato modificato nulla.$\r$\nEsegui di nuovo il programma di installazione e scegli una cartella vuota, oppure la cartella in cui è installato EGM Downloader."
LangString EGM_FOLDER_NOT_OURS ${LANG_JAPANESE} "このフォルダーは空ではなく、インストール済みの EGM Downloader が含まれていません：$\r$\n$INSTDIR$\r$\n$\r$\nポータブル版はインストール済みのコピーではありません。何も変更されていません。$\r$\nインストーラーをもう一度実行し、空のフォルダー、または EGM Downloader がインストールされているフォルダーを選んでください。"
LangString EGM_FOLDER_NOT_OURS ${LANG_DUTCH} "Deze map is niet leeg en bevat geen geïnstalleerde kopie van EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nEen draagbare kopie is geen geïnstalleerde kopie. Er is niets gewijzigd.$\r$\nVoer het installatieprogramma opnieuw uit en kies een lege map, of de map waarin EGM Downloader is geïnstalleerd."
LangString EGM_FOLDER_NOT_OURS ${LANG_PORTUGUESEBR} "Esta pasta não está vazia e não contém uma cópia instalada do EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nUma cópia portátil não é uma cópia instalada. Nada foi alterado.$\r$\nExecute o instalador novamente e escolha uma pasta vazia ou a pasta em que o EGM Downloader está instalado."
LangString EGM_FOLDER_NOT_OURS ${LANG_RUSSIAN} "Эта папка не пуста и не содержит установленной копии EGM Downloader:$\r$\n$INSTDIR$\r$\n$\r$\nПортативная копия не является установленной. Ничего не изменено.$\r$\nСнова запустите установщик и выберите пустую папку или папку, в которую установлен EGM Downloader."

LangString EGM_ARCH_UNSUPPORTED ${LANG_ENGLISH} "EGM Downloader needs 64 bit Windows on an Intel or AMD processor, or Windows 11 on an ARM processor.$\r$\nThis computer has neither, so nothing was installed."
LangString EGM_ARCH_UNSUPPORTED ${LANG_ARABIC} "يتطلب EGM Downloader نظام Windows بإصدار 64 بت على معالج Intel أو AMD، أو Windows 11 على معالج ARM.$\r$\nهذا الكمبيوتر لا يستوفي أيّاً من الشرطين، لذلك لم يتم تثبيت أي شيء."
LangString EGM_ARCH_UNSUPPORTED ${LANG_GERMAN} "EGM Downloader benötigt 64-Bit-Windows auf einem Intel- oder AMD-Prozessor oder Windows 11 auf einem ARM-Prozessor.$\r$\nDieser Computer erfüllt keine der beiden Voraussetzungen, daher wurde nichts installiert."
LangString EGM_ARCH_UNSUPPORTED ${LANG_SPANISH} "EGM Downloader necesita Windows de 64 bits en un procesador Intel o AMD, o Windows 11 en un procesador ARM.$\r$\nEste equipo no cumple ninguno de los dos requisitos, por lo que no se ha instalado nada."
LangString EGM_ARCH_UNSUPPORTED ${LANG_FRENCH} "EGM Downloader nécessite Windows 64 bits sur un processeur Intel ou AMD, ou Windows 11 sur un processeur ARM.$\r$\nCet ordinateur ne répond à aucune de ces conditions, donc rien n'a été installé."
LangString EGM_ARCH_UNSUPPORTED ${LANG_ITALIAN} "EGM Downloader richiede Windows a 64 bit su un processore Intel o AMD, oppure Windows 11 su un processore ARM.$\r$\nQuesto computer non soddisfa nessuna delle due condizioni, quindi non è stato installato nulla."
LangString EGM_ARCH_UNSUPPORTED ${LANG_JAPANESE} "EGM Downloader には、IntelまたはAMDプロセッサ上の64ビット版Windows、またはARMプロセッサ上のWindows 11が必要です。$\r$\nこのコンピューターはどちらにも該当しないため、何もインストールされていません。"
LangString EGM_ARCH_UNSUPPORTED ${LANG_DUTCH} "EGM Downloader vereist 64-bits Windows op een Intel- of AMD-processor, of Windows 11 op een ARM-processor.$\r$\nDeze computer voldoet aan geen van beide, dus er is niets geïnstalleerd."
LangString EGM_ARCH_UNSUPPORTED ${LANG_PORTUGUESEBR} "O EGM Downloader requer Windows de 64 bits em um processador Intel ou AMD, ou Windows 11 em um processador ARM.$\r$\nEste computador não atende a nenhum dos dois requisitos, por isso nada foi instalado."
LangString EGM_ARCH_UNSUPPORTED ${LANG_RUSSIAN} "Для EGM Downloader требуется 64-разрядная версия Windows на процессоре Intel или AMD либо Windows 11 на процессоре ARM.$\r$\nЭтот компьютер не соответствует ни одному из условий, поэтому ничего не установлено."

LangString EGM_UN_REMOVE_COMPONENTS ${LANG_ENGLISH} "Also remove the downloaded components (ffmpeg and Deno)?$\r$\n$\r$\nThe app downloads them again on its first launch after a new install.$\r$\nChoose No to keep them for a faster reinstall."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_ARABIC} "هل تريد إزالة المكونات التي تم تنزيلها (ffmpeg وDeno) أيضاً؟$\r$\n$\r$\nيعيد التطبيق تنزيلها عند التشغيل الأول بعد تثبيت جديد.$\r$\nاختر «لا» للإبقاء عليها وإعادة تثبيت أسرع."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_GERMAN} "Auch die heruntergeladenen Komponenten (ffmpeg und Deno) entfernen?$\r$\n$\r$\nDie App lädt sie beim ersten Start nach einer Neuinstallation erneut herunter.$\r$\nWähle Nein, um sie für eine schnellere Neuinstallation zu behalten."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_SPANISH} "¿Quieres eliminar también los componentes descargados (ffmpeg y Deno)?$\r$\n$\r$\nLa aplicación los vuelve a descargar en el primer inicio después de una nueva instalación.$\r$\nElige No para conservarlos y reinstalar más rápido."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_FRENCH} "Supprimer aussi les composants téléchargés (ffmpeg et Deno) ?$\r$\n$\r$\nL'application les télécharge de nouveau au premier lancement après une nouvelle installation.$\r$\nChoisissez Non pour les conserver et réinstaller plus rapidement."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_ITALIAN} "Rimuovere anche i componenti scaricati (ffmpeg e Deno)?$\r$\n$\r$\nL'app li scarica di nuovo al primo avvio dopo una nuova installazione.$\r$\nScegli No per conservarli e reinstallare più velocemente."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_JAPANESE} "ダウンロード済みのコンポーネント（ffmpegとDeno）も削除しますか？$\r$\n$\r$\n新たにインストールした後の初回起動時に、アプリが再びダウンロードします。$\r$\n「いいえ」を選ぶと保持され、再インストールが速くなります。"
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_DUTCH} "Ook de gedownloade onderdelen (ffmpeg en Deno) verwijderen?$\r$\n$\r$\nDe app downloadt ze opnieuw bij de eerste start na een nieuwe installatie.$\r$\nKies Nee om ze te bewaren voor een snellere herinstallatie."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_PORTUGUESEBR} "Remover também os componentes baixados (ffmpeg e Deno)?$\r$\n$\r$\nO aplicativo os baixa novamente na primeira execução após uma nova instalação.$\r$\nEscolha Não para mantê-los e reinstalar mais rápido."
LangString EGM_UN_REMOVE_COMPONENTS ${LANG_RUSSIAN} "Удалить также загруженные компоненты (ffmpeg и Deno)?$\r$\n$\r$\nПриложение загрузит их снова при первом запуске после новой установки.$\r$\nВыберите «Нет», чтобы сохранить их для более быстрой переустановки."

LangString EGM_UN_REMOVE_DATA ${LANG_ENGLISH} "Also remove your data (settings, download history, cookies, logs)?$\r$\n$\r$\nChoose No to keep them for a faster setup on next install."
LangString EGM_UN_REMOVE_DATA ${LANG_ARABIC} "هل تريد إزالة بياناتك أيضاً (الإعدادات، سجل التحميلات، ملفات تعريف الارتباط، السجلات)؟$\r$\n$\r$\nاختر «لا» للإبقاء عليها وإعداد أسرع عند التثبيت التالي."
LangString EGM_UN_REMOVE_DATA ${LANG_GERMAN} "Auch deine Daten (Einstellungen, Downloadverlauf, Cookies, Protokolle) entfernen?$\r$\n$\r$\nWähle Nein, um sie für eine schnellere Einrichtung bei der nächsten Installation zu behalten."
LangString EGM_UN_REMOVE_DATA ${LANG_SPANISH} "¿Quieres eliminar también tus datos (configuración, historial de descargas, cookies, registros)?$\r$\n$\r$\nElige No para conservarlos y configurar más rápido en la próxima instalación."
LangString EGM_UN_REMOVE_DATA ${LANG_FRENCH} "Supprimer aussi vos données (paramètres, historique des téléchargements, cookies, journaux) ?$\r$\n$\r$\nChoisissez Non pour les conserver et configurer plus rapidement lors de la prochaine installation."
LangString EGM_UN_REMOVE_DATA ${LANG_ITALIAN} "Rimuovere anche i tuoi dati (impostazioni, cronologia dei download, cookie, log)?$\r$\n$\r$\nScegli No per conservarli e configurare più velocemente alla prossima installazione."
LangString EGM_UN_REMOVE_DATA ${LANG_JAPANESE} "データ（設定、ダウンロード履歴、クッキー、ログ）も削除しますか？$\r$\n$\r$\n「いいえ」を選ぶと保持され、次回のインストール後のセットアップが速くなります。"
LangString EGM_UN_REMOVE_DATA ${LANG_DUTCH} "Ook je gegevens (instellingen, downloadgeschiedenis, cookies, logboeken) verwijderen?$\r$\n$\r$\nKies Nee om ze te bewaren voor een snellere installatie de volgende keer."
LangString EGM_UN_REMOVE_DATA ${LANG_PORTUGUESEBR} "Remover também seus dados (configurações, histórico de downloads, cookies, logs)?$\r$\n$\r$\nEscolha Não para mantê-los e configurar mais rápido na próxima instalação."
LangString EGM_UN_REMOVE_DATA ${LANG_RUSSIAN} "Удалить также ваши данные (настройки, историю загрузок, файлы cookie, журналы)?$\r$\n$\r$\nВыберите «Нет», чтобы сохранить их для более быстрой настройки при следующей установке."

; ── Welcome-page language selector ────────────────────────────────────────────
; Rows map 1:1, index-aligned, to the codes in LangCodeFromIndex below.
Function WelcomePage_Show
  ; Dark title/body text on the welcome page (MUI_BGCOLOR sets the canvas)
  SetCtlColors $mui.WelcomePage.Title "e2e8f6" "0b1120"
  SetCtlColors $mui.WelcomePage.Text  "8faecf" "0b1120"
FunctionEnd

Function WelcomePage_Leave
  ; Map the startup language choice to the app hand-off code
  StrCpy $SelectedLangCode "en"
  ${If} $LANGUAGE == ${LANG_ARABIC}
    StrCpy $SelectedLangCode "ar"
  ${ElseIf} $LANGUAGE == ${LANG_GERMAN}
    StrCpy $SelectedLangCode "de"
  ${ElseIf} $LANGUAGE == ${LANG_SPANISH}
    StrCpy $SelectedLangCode "es"
  ${ElseIf} $LANGUAGE == ${LANG_FRENCH}
    StrCpy $SelectedLangCode "fr"
  ${ElseIf} $LANGUAGE == ${LANG_ITALIAN}
    StrCpy $SelectedLangCode "it"
  ${ElseIf} $LANGUAGE == ${LANG_JAPANESE}
    StrCpy $SelectedLangCode "ja"
  ${ElseIf} $LANGUAGE == ${LANG_DUTCH}
    StrCpy $SelectedLangCode "nl"
  ${ElseIf} $LANGUAGE == ${LANG_PORTUGUESEBR}
    StrCpy $SelectedLangCode "pt"
  ${ElseIf} $LANGUAGE == ${LANG_RUSSIAN}
    StrCpy $SelectedLangCode "ru"
  ${EndIf}
FunctionEnd

; ── Desktop shortcut — created only if user checks the box on finish page ────
Function FinishPage_CreateDesktopShortcut
  CreateShortCut "$DESKTOP\EGM Downloader.lnk" \
    "$INSTDIR\EGM Downloader.exe" "" \
    "$INSTDIR\resources\app\static\icon.ico" 0
FunctionEnd

; ── Launch app from finish page — uses ShellExecute to avoid CMD flash ────────
Function FinishPage_LaunchApp
  ExecShell "open" "$INSTDIR\EGM Downloader.exe"
FunctionEnd

; ── The app of THIS folder, running: for the installer and the uninstaller ────
; Only processes whose image is in the install folder: the app (also the 1.5.x launcher, and that
; layout's Electron, renamed or not) and the bundled Python, which can outlive the app. A copy
; running from any other folder (a portable copy, say) is left alone. wmic is gone from new Windows,
; so PowerShell asks WMI (Win32_Process gives this 32 bit installer the image path of 64 bit
; processes too, which Get-Process does not). The folder goes in an environment variable, so no
; character of a folder name can break the command, and every tool is called by its full path:
; a find.exe or tasklist.exe earlier on PATH (Git for Windows, MSYS) plays no part.
; Out: $0 = how many, $1 = "/PID n /PID m" for taskkill; $0 = -1 when the query could not tell.
!macro EGM_FIND_RUNNING_FUNCTION un
Function ${un}EGM_FindRunning
  System::Call 'kernel32::SetEnvironmentVariable(t "EGM_STOP_DIR", t "$INSTDIR")i'
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$$ProgressPreference = 'SilentlyContinue'; $$d = $$env:EGM_STOP_DIR; $$w = @(($$d + '\EGM Downloader.exe'), ($$d + '\resources\python\python.exe'), ($$d + '\electron\node_modules\electron\dist\EGM Downloader.exe'), ($$d + '\electron\node_modules\electron\dist\electron.exe')); try { $$a = @(Get-CimInstance Win32_Process -ErrorAction Stop) } catch { exit 255 }; $$p = @($$a | Where-Object { $$w -contains $$_.ExecutablePath }); [Console]::Out.Write((($$p | ForEach-Object { '/PID ' + $$_.ProcessId }) -join ' ') + ' EGM_QUERY_RAN'); exit $$p.Count"`
  Pop $0
  Pop $1
  ; The query writes EGM_QUERY_RAN last, and only once WMI has answered. Without it (PowerShell
  ; blocked or missing, WMI failing, "error" or "timeout" from nsExec) nothing is known, whatever the
  ; exit code says: $0 = -1, and the caller asks by image name (EGM_FindRunningByName).
  StrCpy $2 $1 "" -14
  ${If} $2 == " EGM_QUERY_RAN"
    StrCpy $1 $1 -14
  ${Else}
    StrCpy $0 -1
    StrCpy $1 ""
  ${EndIf}
FunctionEnd

; When the query could not tell: is any EGM Downloader.exe running, from any folder? tasklist by its
; full path, as CSV without a header: the quoted name is in its output only when one runs (the "no
; tasks" line, in any language, does not hold it). Only that name: python.exe would match other
; people's Pythons. Out: $0 = 1 running, 0 not (also when tasklist itself fails).
Function ${un}EGM_FindRunningByName
  nsExec::ExecToStack '"$SYSDIR\tasklist.exe" /FI "IMAGENAME eq EGM Downloader.exe" /FO CSV /NH'
  Pop $0
  Pop $1
  !if "${un}" == ""
    ${StrStr} $2 $1 '"EGM Downloader.exe"'
  !else
    ${UnStrStr} $2 $1 '"EGM Downloader.exe"'
  !endif
  StrCpy $0 0
  ${If} $2 != ""
    StrCpy $0 1
  ${EndIf}
FunctionEnd
!macroend
!insertmacro EGM_FIND_RUNNING_FUNCTION ""
!insertmacro EGM_FIND_RUNNING_FUNCTION "un."

; ── Startup: detect existing install ─────────────────────────
Function .onInit
  ; ── Only where the app runs, checked first, before anything changes: 64 bit Windows on an Intel
  ;    or AMD processor, or Windows 11 on ARM, which runs x64 programs (Windows 10 on ARM does not).
  ;    Silent: no box, exit code 2 (Abort in .onInit). The language dialog has not run yet, so the
  ;    box comes in the Windows display language when it is one of the ten, else in English. ──
  ${IfNot} ${IsNativeAMD64}
    ${IfNot} ${IsNativeARM64}
    ${OrIfNot} ${AtLeastWin11}
      MessageBox MB_OK|MB_ICONSTOP "$(EGM_ARCH_UNSUPPORTED)" /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}

  ; Language must be chosen HERE: NSIS binds the UI language once at startup;
  ; $LANGUAGE changes after GUI init have no effect (empirically verified —
  ; the welcome-page dropdown approach could never work). This dialog lists
  ; the 10 declared languages by native name and preselects the OS match.
  !insertmacro MUI_LANGDLL_DISPLAY

  ReadRegStr $PreviousVersion HKCU "${REGKEY}" "Version"
  ReadRegStr $PreviousInstDir HKCU "${REGKEY}" "InstallPath"

  ; Reuse the previous install dir (upgrade & maintenance).
  ${If} $PreviousInstDir != ""
    StrCpy $INSTDIR $PreviousInstDir
  ${EndIf}
FunctionEnd

; Maintenance-mode prompt lives HERE, not in .onInit: LangStrings are not
; available in .onInit (language finalizes when it returns), so the prompt
; there always rendered in English regardless of the dialog pick.
Function WelcomePage_Pre
  ${If} $PreviousVersion == "${VERSION}"
    MessageBox MB_YESNOCANCEL|MB_ICONQUESTION \
      "$(EGM_ALREADY_INSTALLED)" \
      /SD IDCANCEL IDYES repair IDNO do_uninstall
    Quit
    repair:
      Return
    do_uninstall:
      ${If} $PreviousInstDir != ""
        ; The uninstaller asks its own questions (keep ffmpeg and Deno, keep the data). _?= runs it
        ; in place so ExecWait waits for it; from there it cannot delete itself, so uninstall.exe and
        ; the folder, if nothing else is left in it, are removed here, and only after an uninstall
        ; that ran to its end (0): a cancelled one leaves the install as it was, with its uninstaller.
        ExecWait '"$PreviousInstDir\uninstall.exe" _?=$PreviousInstDir' $0
        ${If} $0 == 0
          Delete "$PreviousInstDir\uninstall.exe"
          RMDir "$PreviousInstDir"
        ${EndIf}
      ${EndIf}
      Quit
  ${EndIf}
FunctionEnd

; ── Upgrade or repair: no folder page ─────────────────────────
; With the app already in the folder the installer would use (the one the last install recorded,
; or the default), the install goes there: another folder would orphan that install and start
; without its settings and history. A portable copy there is not an install (the install refuses
; its folder), so the page stays and another folder can be chosen.
Function DirectoryPage_Pre
  ${If} ${FileExists} "$INSTDIR\EGM Downloader.exe"
  ${AndIfNot} ${FileExists} "$INSTDIR\.portable"
    Abort
  ${EndIf}
FunctionEnd

; ── Install Section ──────────────────────────────────────────
Section "Install" SecInstall
  ; ── Only into an empty folder or one of ours, checked before anything is closed or changed ──
  ; A folder of something else would get the app's files mixed into it and loses files by name
  ; below. A portable copy (launch.py with .portable) keeps its data inside and is not an install.
  ; Ours too: what an uninstall leaves when the user keeps the data (egm_settings.json, which every
  ; run of the app writes) or the downloaded components (ffmpeg_bin).
  ${DirState} "$INSTDIR" $0
  ${If} ${FileExists} "$INSTDIR\launch.py"
  ${AndIf} ${FileExists} "$INSTDIR\.portable"
    StrCpy $0 "refuse"
  ${ElseIf} $0 == 1
  ${AndIfNot} ${FileExists} "$INSTDIR\EGM Downloader.exe"
  ${AndIfNot} ${FileExists} "$INSTDIR\resources\app.asar"
  ${AndIfNot} ${FileExists} "$INSTDIR\launch.py"
  ${AndIfNot} ${FileExists} "$INSTDIR\electron\main.js"
  ${AndIfNot} ${FileExists} "$INSTDIR\egm_settings.json"
  ${AndIfNot} ${FileExists} "$INSTDIR\ffmpeg_bin\*.*"
    StrCpy $0 "refuse"
  ${EndIf}
  ${If} $0 == "refuse"
    MessageBox MB_OK|MB_ICONSTOP "$(EGM_FOLDER_NOT_OURS)" /SD IDOK
    Abort
  ${EndIf}

  ; ── Guard: never install over a RUNNING app (locked files → corrupt/partial
  ;    copy or silent failure). Only the app of this folder counts (EGM_FindRunning). ──
  Call EGM_FindRunning
  ${If} $0 > 0
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
      "$(EGM_APP_RUNNING)" \
      /SD IDOK IDOK kill_running
    Abort "$(EGM_INSTALL_CANCELLED)"
    kill_running:
      ; By process id, so only this folder's processes; /T also takes the processes they started.
      nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T $1'
      Pop $0
      Sleep 1000
      ; Check again: if it still runs, stop here, before anything is deleted or copied.
      Call EGM_FindRunning
      ${If} $0 > 0
        MessageBox MB_OK|MB_ICONSTOP "$(EGM_APP_STILL_RUNNING)" /SD IDOK
        Abort "$(EGM_INSTALL_CANCELLED)"
      ${EndIf}
  ${ElseIf} $0 < 0
    ; The query could not tell (PowerShell blocked or missing, WMI failing): ask by image name. This
    ; cannot tell this folder's copy from another one, so the box says that closing ends every copy,
    ; and when silent nobody agreed to that: Cancel, exit code 2, nothing changed.
    Call EGM_FindRunningByName
    ${If} $0 > 0
      MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(EGM_APP_RUNNING_ANY_COPY)" /SD IDCANCEL IDOK kill_by_name
      Abort "$(EGM_INSTALL_CANCELLED)"
      kill_by_name:
        nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM "EGM Downloader.exe"'
        Pop $0
        Sleep 1000
        Call EGM_FindRunningByName
        ${If} $0 > 0
          MessageBox MB_OK|MB_ICONSTOP "$(EGM_APP_STILL_RUNNING)" /SD IDOK
          Abort "$(EGM_INSTALL_CANCELLED)"
        ${EndIf}
    ${EndIf}
  ${EndIf}

  ; ── What is installed here already: decided by files, never by version ──
  ; Two independent checks, the old layout first: a folder holding both is cleaned of the old
  ; files and then gets the new install.
  ${If} ${FileExists} "$INSTDIR\launch.py"
    ; The v1.5.0 to v1.5.2.3 layout: remove its program files by name (the old launcher is
    ; overwritten below). Settings, history, logs, ffmpeg and Deno stay; the user's system
    ; Python and its packages are never touched. launch.py alone marks it: the macro removes it
    ; last, so a folder whose cleanup was cut short is still found here.
    !insertmacro EGM_REMOVE_OLD_LAYOUT
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\resources\app.asar"
    ; This layout (upgrade or repair): resources (the app, app.asar, the bundled Python) and
    ; locales hold only this app's files and are replaced as a whole, so no file of an earlier
    ; version stays next to the new ones. User data lives in the install folder itself (the shell
    ; hands app.py that folder in EGM_INSTALL_DIR), never in these two. The rest is overwritten.
    RMDir /r "$INSTDIR\resources"
    RMDir /r "$INSTDIR\locales"
  ${EndIf}
  ; Files the v0.99 installers put here and no later one removed (this folder passed the check
  ; above, so it is one of ours).
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\EGM Downloader.vbs"
  ; Anything else: nothing is deleted.

  ; ── The app: Electron, the bundled Python with its packages, and the app files ──
  SetOutPath "$INSTDIR"
  File /r "${APP_FOLDER}/*"
  File "${REPO_ROOT}/windows/instructions.txt"
  File "${REPO_ROOT}/LICENSE"

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

  ; Taskbar/notification display name for the app's AppUserModelID (must match
  ; app.setAppUserModelId in electron/main.js). Without it, Windows can fall back
  ; to the exe's internal FileDescription in the taskbar right-click menu.
  WriteRegStr HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader" "DisplayName" "EGM Downloader"
  WriteRegStr HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader" "IconUri" "$INSTDIR\resources\app\static\icon.ico"

  ; ── Registry: Add/Remove Programs ──
  WriteRegStr HKCU "${UNINSTREG}" "DisplayName"     "${APPNAME}"
  WriteRegStr HKCU "${UNINSTREG}" "DisplayVersion"  "${VERSION}"
  WriteRegStr HKCU "${UNINSTREG}" "DisplayIcon"     "$INSTDIR\resources\app\static\icon.ico"
  WriteRegStr HKCU "${UNINSTREG}" "Publisher"       "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTREG}" "URLInfoAbout"    "${APPURL}"
  WriteRegStr HKCU "${UNINSTREG}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTREG}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTREG}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTREG}" "NoRepair" 1
  ; In KB: the files of this section, counted when the installer is built
  SectionGetSize ${SecInstall} $0
  WriteRegDWORD HKCU "${UNINSTREG}" "EstimatedSize" $0
  WriteRegStr HKCU "${UNINSTREG}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'

  ; ── Start Menu shortcuts ──
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut  "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" \
                  "$INSTDIR\EGM Downloader.exe" "" "$INSTDIR\resources\app\static\icon.ico"
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
  ; ── Close the app of this folder if it runs, so no file is locked: the installer's check ──
  Call un.EGM_FindRunning
  ${If} $0 > 0
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
      "$(EGM_UN_APP_RUNNING)" \
      /SD IDOK IDOK un_kill_running
    Abort
    un_kill_running:
      nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T $1'
      Pop $0
      Sleep 1000
      ; Check again: if it still runs, stop here, before anything is removed.
      Call un.EGM_FindRunning
      ${If} $0 > 0
        MessageBox MB_OK|MB_ICONSTOP "$(EGM_UN_APP_STILL_RUNNING)" /SD IDOK
        Abort
      ${EndIf}
  ${ElseIf} $0 < 0
    ; The query could not tell: by image name, asking first, as the installer does
    Call un.EGM_FindRunningByName
    ${If} $0 > 0
      MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(EGM_UN_APP_RUNNING_ANY_COPY)" /SD IDCANCEL IDOK un_kill_by_name
      Abort
      un_kill_by_name:
        nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM "EGM Downloader.exe"'
        Pop $0
        Sleep 1000
        Call un.EGM_FindRunningByName
        ${If} $0 > 0
          MessageBox MB_OK|MB_ICONSTOP "$(EGM_UN_APP_STILL_RUNNING)" /SD IDOK
          Abort
        ${EndIf}
    ${EndIf}
  ${EndIf}

  ; ── Remove app files: exactly what the installer wrote ──
  ; The folder's top level files and its resources\ and locales\ folders (generated list).
  ; resources\ goes as a whole, with the __pycache__ folders Python writes there at runtime.
  ; Only where this edition is installed: resources and locales are common folder names, and the
  ; install folder is the user's choice (it can be one that held other things first).
  ${If} ${FileExists} "$INSTDIR\resources\app.asar"
  ${OrIf} ${FileExists} "$INSTDIR\EGM Downloader.exe"
    !insertmacro EGM_REMOVE_APP_FOLDER
  ${EndIf}
  Delete "$INSTDIR\instructions.txt"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\first-run-language.txt"
  ; The Reinstall Electron marker the app may have written, and anything an earlier
  ; layout left behind (an older installer run over this one, say).
  Delete "$INSTDIR\.electron-update"
  ${If} ${FileExists} "$INSTDIR\launch.py"
  ${OrIf} ${FileExists} "$INSTDIR\electron\main.js"
    !insertmacro EGM_REMOVE_OLD_LAYOUT
  ${EndIf}

  Delete "$INSTDIR\uninstall.exe"

  ; ── Prompt 1: downloaded RUNTIME COMPONENTS only (no user data here) ──
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "$(EGM_UN_REMOVE_COMPONENTS)" \
    /SD IDNO IDNO skip_components

  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\ffmpeg_bin"

  skip_components:

  ; ── Prompt 2: USER DATA (settings, history, cookies, thumbnails, logs) ──
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "$(EGM_UN_REMOVE_DATA)" \
    /SD IDNO IDNO skip_userdata

  Delete "$INSTDIR\egm_settings.json"
  Delete "$INSTDIR\egm_history.json"
  Delete "$INSTDIR\egm_subscriptions.json"
  Delete "$INSTDIR\cookies.txt"
  ; Log files beside the app, and the temporary files of a write cut short
  Delete "$INSTDIR\egm_debug.log"
  Delete "$INSTDIR\egm_debug.log.old"
  Delete "$INSTDIR\egm_error.log"
  Delete "$INSTDIR\egm_settings.json.tmp"
  Delete "$INSTDIR\egm_history.json.tmp"
  Delete "$INSTDIR\egm_subscriptions.json.tmp"
  Delete "$INSTDIR\cookies.txt.tmp"
  Delete "$INSTDIR\egm_settings.json.*.tmp"
  ; The copies the app keeps of a settings, history or subscriptions file it could not read
  Delete "$INSTDIR\egm_settings.json.unreadable"
  Delete "$INSTDIR\egm_history.json.unreadable"
  Delete "$INSTDIR\egm_subscriptions.json.unreadable"
  RMDir /r "$INSTDIR\thumbnails"
  RMDir /r "$INSTDIR\data"
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\electron-data"
  ; Installed-build Electron userData (package.json "name" = egm-downloader)
  RMDir /r "$APPDATA\egm-downloader"
  ; The folder is recorded until its data goes (see Registry below)
  DeleteRegValue HKCU "${REGKEY}" "InstallPath"

  skip_userdata:

  ; ── Remove the install folder if it is empty now (kept components or data keep it) ──
  RMDir "$INSTDIR"

  ; ── Start Menu + Desktop shortcuts ──
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir  "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\EGM Downloader.lnk"

  ; ── Registry ──
  DeleteRegKey HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader"
  ; InstallPath stays when the data stays (it went with the data above): a later install then
  ; finds the folder, a custom one too, and the settings and history in it.
  DeleteRegValue HKCU "${REGKEY}" "Version"
  DeleteRegValue HKCU "${REGKEY}" "Language"
  DeleteRegValue HKCU "${REGKEY}" "Build"
  DeleteRegKey /ifempty HKCU "${REGKEY}"
  DeleteRegKey HKCU "${UNINSTREG}"
SectionEnd
