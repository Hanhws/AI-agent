; 가닥 — Windows 설치 프로그램 (NSIS 3). 만들기: python -m backend.winapp --installer
; 이 파일은 UTF-8로 저장해요 (makensis에 /INPUTCHARSET UTF8로 알려 줘요).
; stage\ 는 backend/winapp.py가 모아 둔 폴더예요 (python\ · site-packages\ · app\ · gadak.ico · 가닥 켜기.cmd · 처음 여는 법.txt).
; 내 계정에만 깔아요: 관리자 암호가 필요 없고, 깔리는 곳은 %LOCALAPPDATA%\Programs\Gadak 이에요.

Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef LAUNCH
  !define LAUNCH "-X utf8 -m backend.launch --app"
!endif
!ifndef OUTFILE
  !define OUTFILE "gadak-setup.exe"
!endif
!define NAME "Gadak"
!define FOLDER "Gadak"
!define TAGLINE "Keep the thread of every long chat."
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Gadak"
; 켜져 있는 가닥이 쥐고 있는 표시 (backend/win.py의 RUNNING과 같은 이름)
!define RUNNING "GadakAppRunning"
; 가닥이 깔린 폴더라는 표시. 이 파일이 있을 때만 그 폴더를 치워요 (엉뚱한 폴더를 지우지 않게)
!define MARK "app\BUILD.json"

Name "${NAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${FOLDER}"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
BrandingText "${NAME} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${NAME}"
VIAddVersionKey "FileDescription" "${NAME} Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "${TAGLINE}"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON "stage\gadak.ico"
!define MUI_UNICON "stage\gadak.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "${TAGLINE}$\r$\n$\r$\nInstalls Gadak for your account on this PC. No administrator password is needed.$\r$\n$\r$\nChats are stored only on this PC."
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "${LAUNCH}"
!define MUI_FINISHPAGE_RUN_TEXT "Start Gadak"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\How to open Gadak.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show how to open Gadak"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; 가닥이 켜져 있으면 파일을 바꿀 수 없어요. 끄고 다시 하라고 알려요
!macro StopIfRunning
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${RUNNING}") p .r0'
  StrCmp $0 0 +4
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK|MB_ICONEXCLAMATION "Gadak is running. Close the Gadak window and try again." /SD IDOK
    Abort
!macroend

Function .onInit
  !insertmacro StopIfRunning
FunctionEnd

Function un.onInit
  !insertmacro StopIfRunning
FunctionEnd

Section "${NAME}" Main
  SectionIn RO
  ; 예전 판 위에 깔 때: 예전 코드 · 꾸러미를 치우고 새로 깔아요 (없어진 파일이 남지 않게)
  IfFileExists "$INSTDIR\${MARK}" 0 +4
    RMDir /r "$INSTDIR\app"
    RMDir /r "$INSTDIR\site-packages"
    RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File /r "stage\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 시작 메뉴와 바탕 화면의 ‘가닥’. 창 없는 파이썬(pythonw)으로 켜서 검은 창이 뜨지 않아요
  CreateShortcut "$SMPROGRAMS\${NAME}.lnk" "$INSTDIR\python\pythonw.exe" "${LAUNCH}" "$INSTDIR\gadak.ico" 0 SW_SHOWNORMAL "" "${TAGLINE}"
  CreateShortcut "$DESKTOP\${NAME}.lnk" "$INSTDIR\python\pythonw.exe" "${LAUNCH}" "$INSTDIR\gadak.ico" 0 SW_SHOWNORMAL "" "${TAGLINE}"

  ; 설정 → 앱 → 설치된 앱에 보이게
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\gadak.ico"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" "$0"
SectionEnd

; 지울 때: 깔았던 것만 지워요. 대화가 든 폴더(%USERPROFILE%\.gadak)는 그대로 둬요 (‘처음 여는 법.txt’에 적어 뒀어요)
Section "Uninstall"
  Delete "$SMPROGRAMS\${NAME}.lnk"
  Delete "$DESKTOP\${NAME}.lnk"
  IfFileExists "$INSTDIR\${MARK}" 0 +4
    RMDir /r "$INSTDIR\app"
    RMDir /r "$INSTDIR\site-packages"
    RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\gadak.ico"
  Delete "$INSTDIR\Start Gadak.cmd"
  Delete "$INSTDIR\How to open Gadak.txt"
  Delete "$INSTDIR\Gadak install guide.pdf"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
