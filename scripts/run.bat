@echo off
REM ===========================================================================
REM  Campus Course Assistant - one-click launcher (ASCII ONLY)
REM
REM  This file must stay pure ASCII. cmd.exe parses .bat files using the OEM
REM  code page, so any Chinese characters here would show up as garbage.
REM  All Chinese text lives in run.ps1 (which is UTF-8 with BOM).
REM
REM  Why this wrapper exists:
REM  PowerShell's default ExecutionPolicy is "Restricted", which makes
REM  double-clicking a .ps1 open it in Notepad instead of running it.
REM  "Bypass" below applies ONLY to this single invocation - it does not
REM  change any machine-wide setting.
REM ===========================================================================

setlocal
chcp 65001 >nul 2>&1

set "PS1=%~dp0run.ps1"

if not exist "%PS1%" (
    echo [ERROR] run.ps1 not found next to this file.
    echo         Expected: %PS1%
    pause
    exit /b 1
)

REM Verify UTF-8 BOM. Without it, PowerShell 5.1 reads the file as ANSI/GBK
REM and the whole Chinese menu turns into mojibake.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$bytes = [System.IO.File]::ReadAllBytes('%PS1%'); if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) { Write-Host '[WARN] run.ps1 is missing the UTF-8 BOM - Chinese text may be garbled.' -ForegroundColor Yellow; Write-Host '       Fix: re-save the file as UTF-8 with BOM.' -ForegroundColor Yellow; exit 1 }"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"

endlocal
