; Terre System — Windows суулгагч (NSIS)
Unicode true
Target amd64-unicode
!define APPNAME "Terre System"
!define VERSION "1.0.0"
!define PUBLISHER "Tuvshuu"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\TerreSystem"

!include "MUI2.nsh"
!include "FileFunc.nsh"

Name "${APPNAME}"
OutFile "..\TerreSystem-Setup-${VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "${UNINSTKEY}" "InstallLocation"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APPNAME} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} суулгагч"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "${PUBLISHER}"

!define MUI_ICON "terre.ico"
!define MUI_UNICON "terre.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "side.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "side.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Terre System суулгах"
!define MUI_WELCOMEPAGE_TEXT "Terre System — таны хувийн AI туслах.$\r$\n$\r$\nМэйл, календарь, чатаа шалгаж, өдрийн мэдээллийг дуугаар уншина, файлаа цэгцэлж, School Manager-ийг удирдана.$\r$\n$\r$\nАнх асаахад ДЕМО горимоор ажиллана. Жинхэнэ холболтуудыг «Холболт тохируулах»-аар тохируулна.$\r$\n$\r$\nҮргэлжлүүлэхийн тулд «Дараах» дарна уу."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Terre System-ийг одоо асаах"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchUnelevated
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Холболт тохируулах (Gmail, Outlook, Telegram bot...)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION RunSetup
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Mongolian"

; Ажиллаж буй Terre-г зогсоох (зөвхөн энэ хавтсаас асаасан pythonw)
!macro StopTerre
  nsExec::Exec `powershell -NoProfile -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\*' } | Stop-Process -Force"`
  Sleep 800
!macroend

Function LaunchUnelevated
  ; Админ эрхгүйгээр асаана (explorer-ээр дамжуулж)
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\Terre System.exe"'
FunctionEnd

Function RunSetup
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\Холболт тохируулах.lnk"'
FunctionEnd

Section "Terre System (заавал)" SecMain
  SectionIn RO
  !insertmacro StopTerre
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\app\terre"
  File /r "..\stage\python"
  File /r "..\stage\app"
  File "..\stage\Terre System.exe"
  File "..\stage\terre.ico"

  ; Эхлэх цэс
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Terre System.lnk" "$INSTDIR\Terre System.exe" "" "$INSTDIR\terre.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Terre — тушаал өгөх.lnk" "$INSTDIR\Terre System.exe" "--quick" "$INSTDIR\terre.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Terre — дуугаар ярих.lnk" "$INSTDIR\Terre System.exe" "--voice" "$INSTDIR\terre.ico"
  SetOutPath "$INSTDIR\app"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Terre — холболт тохируулах.lnk" "$INSTDIR\python\python.exe" "-m terre.setup_auth" "$INSTDIR\terre.ico"
  CreateShortcut "$INSTDIR\Холболт тохируулах.lnk" "$INSTDIR\python\python.exe" "-m terre.setup_auth" "$INSTDIR\terre.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Устгах.lnk" "$INSTDIR\Uninstall.exe"
  SetOutPath "$INSTDIR"

  ; Устгагч
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\terre.ico"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" $0
SectionEnd

Section "Ширээний компьютер дээр товч" SecDesktop
  SetShellVarContext all
  CreateShortcut "$DESKTOP\Terre System.lnk" "$INSTDIR\Terre System.exe" "" "$INSTDIR\terre.ico"
SectionEnd

Section "Windows асахад автоматаар асаах" SecAutostart
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Terre System" '"$INSTDIR\Terre System.exe"'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Terre System програм, Python орчин (≈150 MB)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Ширээний компьютер дээр Terre System товч үүсгэнэ"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutostart} "Компьютер асахад Terre өөрөө асаж, өдрийн мэдээллийг уншина"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  !insertmacro StopTerre
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Terre System"
  SetShellVarContext all
  Delete "$DESKTOP\Terre System.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\Terre System.exe"
  Delete "$INSTDIR\terre.ico"
  Delete "$INSTDIR\Холболт тохируулах.lnk"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTKEY}"
  SetShellVarContext current
  MessageBox MB_YESNO|MB_ICONQUESTION "Terre-ийн тохиргоо, өгөгдлийг (%APPDATA%\Terre System) ч устгах уу?$\r$\n$\r$\nДахин суулгах бол «Үгүй» дарвал тохиргоо хадгалагдана." /SD IDNO IDNO +2
    RMDir /r "$APPDATA\Terre System"
SectionEnd
