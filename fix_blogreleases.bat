@echo off
echo Corrigindo tarefa BlogReleases...
echo.

schtasks /delete /tn "BlogReleases" /f 2>nul
echo [1/2] Tarefa antiga removida (ou nao existia).

call "%~dp0setup_scheduler.bat"

echo.
echo [2/2] Verificando resultado...
schtasks /query /tn "BlogReleases"
pause
