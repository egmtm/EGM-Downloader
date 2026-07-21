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

; ── Installer strings — 10 languages (source: Linguist v1.3 table) ───────────
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

LangString EGM_WELCOME_TEXT ${LANG_ENGLISH} "This will install EGM Downloader v${VERSION} (Build ${BUILD}) on your computer.$\r$\nPython 3.10 or newer is required. On first launch, ~250 MB of additional components will be downloaded automatically.$\r$\nClick Next to continue."
LangString EGM_WELCOME_TEXT ${LANG_ARABIC} "سيؤدي هذا إلى تثبيت EGM Downloader v${VERSION} (الإصدار ${BUILD}) على جهازك.$\r$\nيتطلب الأمر Python 3.10 أو أحدث. عند التشغيل الأول، سيتم تنزيل حوالي 250 ميجابايت من المكونات الإضافية تلقائياً.$\r$\nانقر على $\"التالي$\" للمتابعة."
LangString EGM_WELCOME_TEXT ${LANG_GERMAN} "Hiermit wird EGM Downloader v${VERSION} (Build ${BUILD}) auf deinem Computer installiert.$\r$\nPython 3.10 oder neuer ist erforderlich. Beim ersten Start werden automatisch ca. 250 MB zusätzliche Komponenten heruntergeladen.$\r$\nKlicke auf Weiter, um fortzufahren."
LangString EGM_WELCOME_TEXT ${LANG_SPANISH} "Esto instalará EGM Downloader v${VERSION} (Build ${BUILD}) en tu equipo.$\r$\nSe requiere Python 3.10 o superior. En el primer inicio, se descargarán automáticamente ~250 MB de componentes adicionales.$\r$\nHaz clic en Siguiente para continuar."
LangString EGM_WELCOME_TEXT ${LANG_FRENCH} "Ceci va installer EGM Downloader v${VERSION} (Build ${BUILD}) sur votre ordinateur.$\r$\nPython 3.10 ou plus récent est requis. Au premier lancement, environ 250 Mo de composants supplémentaires seront téléchargés automatiquement.$\r$\nCliquez sur Suivant pour continuer."
LangString EGM_WELCOME_TEXT ${LANG_ITALIAN} "Questo installerà EGM Downloader v${VERSION} (Build ${BUILD}) sul tuo computer.$\r$\nÈ richiesto Python 3.10 o versione successiva. Al primo avvio, verranno scaricati automaticamente circa 250 MB di componenti aggiuntivi.$\r$\nFai clic su Avanti per continuare."
LangString EGM_WELCOME_TEXT ${LANG_JAPANESE} "これにより、EGM Downloader v${VERSION}（ビルド ${BUILD}）がこのコンピューターにインストールされます。$\r$\nPython 3.10 以降が必要です。初回起動時に、追加コンポーネント（約250MB）が自動的にダウンロードされます。$\r$\n「次へ」をクリックして続行してください。"
LangString EGM_WELCOME_TEXT ${LANG_DUTCH} "Hiermee wordt EGM Downloader v${VERSION} (Build ${BUILD}) op je computer geïnstalleerd.$\r$\nPython 3.10 of nieuwer is vereist. Bij de eerste start wordt automatisch ongeveer 250 MB aan extra onderdelen gedownload.$\r$\nKlik op Volgende om door te gaan."
LangString EGM_WELCOME_TEXT ${LANG_PORTUGUESEBR} "Isso instalará o EGM Downloader v${VERSION} (Build ${BUILD}) no seu computador.$\r$\nÉ necessário Python 3.10 ou mais recente. Na primeira execução, cerca de 250 MB de componentes adicionais serão baixados automaticamente.$\r$\nClique em Avançar para continuar."
LangString EGM_WELCOME_TEXT ${LANG_RUSSIAN} "Будет выполнена установка EGM Downloader v${VERSION} (сборка ${BUILD}) на ваш компьютер.$\r$\nТребуется Python 3.10 или новее. При первом запуске автоматически будет загружено около 250 МБ дополнительных компонентов.$\r$\nНажмите «Далее», чтобы продолжить."

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

LangString EGM_FINISH_TEXT ${LANG_ENGLISH} "EGM Downloader v${VERSION} (Build ${BUILD}) has been installed.$\r$\nOn first launch, required components will be downloaded in the background. This is a one-time process."
LangString EGM_FINISH_TEXT ${LANG_ARABIC} "تم تثبيت EGM Downloader v${VERSION} (الإصدار ${BUILD}).$\r$\nعند التشغيل الأول، سيتم تنزيل المكونات المطلوبة في الخلفية. هذه عملية تتم مرة واحدة فقط."
LangString EGM_FINISH_TEXT ${LANG_GERMAN} "EGM Downloader v${VERSION} (Build ${BUILD}) wurde installiert.$\r$\nBeim ersten Start werden erforderliche Komponenten im Hintergrund heruntergeladen. Dies ist ein einmaliger Vorgang."
LangString EGM_FINISH_TEXT ${LANG_SPANISH} "EGM Downloader v${VERSION} (Build ${BUILD}) se ha instalado.$\r$\nEn el primer inicio, los componentes necesarios se descargarán en segundo plano. Este es un proceso único."
LangString EGM_FINISH_TEXT ${LANG_FRENCH} "EGM Downloader v${VERSION} (Build ${BUILD}) a été installé.$\r$\nAu premier lancement, les composants requis seront téléchargés en arrière-plan. Ceci est un processus unique."
LangString EGM_FINISH_TEXT ${LANG_ITALIAN} "EGM Downloader v${VERSION} (Build ${BUILD}) è stato installato.$\r$\nAl primo avvio, i componenti necessari verranno scaricati in background. Questo è un processo unico."
LangString EGM_FINISH_TEXT ${LANG_JAPANESE} "EGM Downloader v${VERSION}（ビルド ${BUILD}）がインストールされました。$\r$\n初回起動時に、必要なコンポーネントがバックグラウンドでダウンロードされます。これは一度だけの処理です。"
LangString EGM_FINISH_TEXT ${LANG_DUTCH} "EGM Downloader v${VERSION} (Build ${BUILD}) is geïnstalleerd.$\r$\nBij de eerste start worden de vereiste onderdelen op de achtergrond gedownload. Dit gebeurt eenmalig."
LangString EGM_FINISH_TEXT ${LANG_PORTUGUESEBR} "O EGM Downloader v${VERSION} (Build ${BUILD}) foi instalado.$\r$\nNa primeira execução, os componentes necessários serão baixados em segundo plano. Este é um processo único."
LangString EGM_FINISH_TEXT ${LANG_RUSSIAN} "EGM Downloader v${VERSION} (сборка ${BUILD}) установлен.$\r$\nПри первом запуске необходимые компоненты будут загружены в фоновом режиме. Это одноразовый процесс."

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
LangString EGM_APP_RUNNING ${LANG_ARABIC} "EGM Downloader قيد التشغيل حالياً.$\r$\nأغلقه قبل المتابعة، أو دع المثبت يغلقه نيابة عنك.$\r$\nموافق ← إغلاقه نيابة عني$\r$\nإلغاء ← إلغاء التثبيت"
LangString EGM_APP_RUNNING ${LANG_GERMAN} "EGM Downloader wird gerade ausgeführt.$\r$\nSchließe es, bevor du fortfährst, oder lasse es vom Installationsprogramm für dich schließen.$\r$\nOK → Für mich schließen$\r$\nAbbrechen → Installation abbrechen"
LangString EGM_APP_RUNNING ${LANG_SPANISH} "EGM Downloader se está ejecutando actualmente.$\r$\nCiérralo antes de continuar, o deja que el instalador lo cierre por ti.$\r$\nAceptar → Cerrarlo por mí$\r$\nCancelar → Cancelar instalación"
LangString EGM_APP_RUNNING ${LANG_FRENCH} "EGM Downloader est actuellement en cours d'exécution.$\r$\nFermez-le avant de continuer, ou laissez l'installateur le fermer pour vous.$\r$\nOK → Le fermer pour moi$\r$\nAnnuler → Annuler l'installation"
LangString EGM_APP_RUNNING ${LANG_ITALIAN} "EGM Downloader è attualmente in esecuzione.$\r$\nChiudilo prima di continuare, oppure lascia che il programma di installazione lo chiuda per te.$\r$\nOK → Chiudilo per me$\r$\nAnnulla → Annulla installazione"
LangString EGM_APP_RUNNING ${LANG_JAPANESE} "EGM Downloader は現在実行中です。$\r$\n続行する前に終了するか、インストーラーに終了させてください。$\r$\nOK → 代わりに終了する$\r$\nキャンセル → インストールを中止"
LangString EGM_APP_RUNNING ${LANG_DUTCH} "EGM Downloader wordt momenteel uitgevoerd.$\r$\nSluit het voordat je doorgaat, of laat het installatieprogramma het voor je sluiten.$\r$\nOK → Sluit het voor mij$\r$\nAnnuleren → Installatie annuleren"
LangString EGM_APP_RUNNING ${LANG_PORTUGUESEBR} "O EGM Downloader está em execução no momento.$\r$\nFeche-o antes de continuar, ou deixe o instalador fechá-lo para você.$\r$\nOK → Fechar para mim$\r$\nCancelar → Cancelar instalação"
LangString EGM_APP_RUNNING ${LANG_RUSSIAN} "EGM Downloader сейчас запущен.$\r$\nЗакройте его перед продолжением или позвольте установщику закрыть его за вас.$\r$\nОК → Закрыть за меня$\r$\nОтмена → Отменить установку"

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
    "$INSTDIR\static\icon.ico" 0
FunctionEnd

; ── Launch app from finish page — uses ShellExecute to avoid CMD flash ────────
Function FinishPage_LaunchApp
  ExecShell "open" "$INSTDIR\EGM Downloader.exe"
FunctionEnd

; ── Startup: detect existing install ─────────────────────────
Function .onInit
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
        ExecWait '"$PreviousInstDir\uninstall.exe" /S'
      ${EndIf}
      Quit
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
        "$(EGM_APP_RUNNING)" \
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
  ; Pre-v0.99.11 installs launched via launch.vbs/launch.bat — the compiled
  ; EXE replaced them (Build 119) but upgrades never cleaned them up.
  Delete "$INSTDIR\launch.vbs"
  Delete "$INSTDIR\launch.bat"

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
  File "${REPO_ROOT}/templates/console.html"
  File "${REPO_ROOT}/templates/history.html"
  File "${REPO_ROOT}/templates/themes.html"
  File "${REPO_ROOT}/templates/theme_styles.html"
  File "${REPO_ROOT}/templates/theme_data.html"
  File "${REPO_ROOT}/templates/theme_validator.html"
  File "${REPO_ROOT}/templates/i18n.html"
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
  File "${REPO_ROOT}/static/badge-1.png"
  File "${REPO_ROOT}/static/badge-2.png"
  File "${REPO_ROOT}/static/badge-3.png"
  File "${REPO_ROOT}/static/badge-4.png"
  File "${REPO_ROOT}/static/badge-5.png"
  File "${REPO_ROOT}/static/badge-6.png"
  File "${REPO_ROOT}/static/badge-7.png"
  File "${REPO_ROOT}/static/badge-8.png"
  File "${REPO_ROOT}/static/badge-9.png"
  File "${REPO_ROOT}/static/badge-9plus.png"

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

  ; Taskbar/notification display name for the app's AppUserModelID (must match
  ; app.setAppUserModelId in electron/main.js). Without it, Windows falls back
  ; to the Electron runtime's internal FileDescription ("Electron") in the
  ; taskbar right-click menu — the runtime downloads at first run, so its
  ; version resources are not ours to patch.
  WriteRegStr HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader" "DisplayName" "EGM Downloader"
  WriteRegStr HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader" "IconUri" "$INSTDIR\static\icon.ico"

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
  Delete "$INSTDIR\launch.vbs"
  Delete "$INSTDIR\launch.bat"
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
  DeleteRegKey HKCU "Software\Classes\AppUserModelId\com.egerena.egm-downloader"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "${UNINSTREG}"
SectionEnd
