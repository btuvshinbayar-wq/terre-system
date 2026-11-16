; Terre System.exe — жижиг эхлүүлэгч: суулгасан Python-оор terre-г консолгүй асаана
Unicode true
Target amd64-unicode
!include "FileFunc.nsh"
Name "Terre System"
OutFile "..\stage\Terre System.exe"
Icon "terre.ico"
RequestExecutionLevel user
SilentInstall silent
VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName" "Terre System"
VIAddVersionKey "FileDescription" "Terre System - хувийн AI туслах"
VIAddVersionKey "FileVersion" "1.0.0"
VIAddVersionKey "LegalCopyright" "Tuvshuu"

Section
  ${GetParameters} $1
  IfFileExists "$EXEDIR\python\pythonw.exe" +3
    MessageBox MB_ICONSTOP "Terre System бүрэн суугаагүй байна. Суулгагчийг дахин ажиллуулна уу."
    Quit
  SetOutPath "$EXEDIR\app"
  Exec '"$EXEDIR\python\pythonw.exe" -m terre $1'
SectionEnd
