@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalar-Revit2026.ps1" > "%~dp0instalacao.log" 2>&1
if errorlevel 1 (
 echo A instalacao falhou. Consulte instalacao.log nesta pasta.
) else (
 echo Instalacao concluida. Abra o Revit 2026 e procure TOPOBIM.
)
pause
