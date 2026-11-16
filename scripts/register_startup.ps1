# Puts a Terre System shortcut in the Windows Startup folder (no admin rights needed).
# Remove: delete "Terre System.lnk" from  shell:startup
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { Write-Host "Run scripts\install.ps1 first." -ForegroundColor Red; exit 1 }

$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Terre System.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "-m terre"
$s.WorkingDirectory = $root
$s.Description = "Terre System personal agent"
$s.Save()
Write-Host "Terre System will start automatically at login: $lnk" -ForegroundColor Green
