@echo off
REM ============================================================
REM setup_scheduler.bat — Configura tarefas no Windows Task Scheduler
REM
REM Execute este arquivo como Administrador:
REM   Clique com botão direito → "Executar como administrador"
REM
REM Tarefas criadas:
REM   BlogReleases     — toda hora, dias úteis, 8h-18h
REM   BlogPauta        — toda segunda-feira às 9h
REM   BlogTelegramBot  — ao iniciar o sistema (daemon permanente)
REM ============================================================

SET PROJECT_DIR=C:\Users\DANILLO\Desktop\LP's IA\+blog claude
SET PYTHON=python

echo Configurando tarefas do +blog no Task Scheduler...
echo.

REM ── 1. Processar releases — toda hora, dias úteis, 8h-18h ─────────────────
echo [1/3] Criando tarefa BlogReleases...
schtasks /create /tn "BlogReleases" ^
  /tr "\"%PYTHON%\" \"%PROJECT_DIR%\execution\run_releases.py\"" ^
  /sc hourly /mo 1 /st 08:00 /et 18:00 /k ^
  /d MON,TUE,WED,THU,FRI ^
  /rl HIGHEST ^
  /f
if %errorlevel% equ 0 (
    echo    OK: BlogReleases criada ^(toda hora, seg-sex, 8h-18h^)
) else (
    echo    ERRO ao criar BlogReleases ^(codigo: %errorlevel%^)
)
echo.

REM ── 2. Gerar pauta — toda segunda às 9h ────────────────────────────────────
echo [2/3] Criando tarefa BlogPauta...
schtasks /create /tn "BlogPauta" ^
  /tr "\"%PYTHON%\" \"%PROJECT_DIR%\execution\run_pauta_generate.py\"" ^
  /sc weekly /d MON /st 09:00 ^
  /rl HIGHEST ^
  /f
if %errorlevel% equ 0 (
    echo    OK: BlogPauta criada ^(toda segunda, 9h^)
) else (
    echo    ERRO ao criar BlogPauta ^(codigo: %errorlevel%^)
)
echo.

REM ── 3. Bot Telegram — iniciar no boot do sistema ───────────────────────────
echo [3/3] Criando tarefa BlogTelegramBot...
schtasks /create /tn "BlogTelegramBot" ^
  /tr "\"%PYTHON%\" \"%PROJECT_DIR%\execution\telegram_bot.py\"" ^
  /sc onstart ^
  /delay 0000:30 ^
  /rl HIGHEST ^
  /f
if %errorlevel% equ 0 (
    echo    OK: BlogTelegramBot criada ^(inicia com o sistema^)
) else (
    echo    ERRO ao criar BlogTelegramBot ^(codigo: %errorlevel%^)
)
echo.

REM ── Iniciar o bot agora ────────────────────────────────────────────────────
echo Iniciando BlogTelegramBot agora...
schtasks /run /tn "BlogTelegramBot"
if %errorlevel% equ 0 (
    echo    Bot iniciado em background.
) else (
    echo    Nao foi possivel iniciar o bot agora. Ele iniciara no proximo boot.
)
echo.

echo ============================================================
echo Configuracao concluida!
echo.
echo Tarefas criadas:
echo   BlogReleases    - verifica emails toda hora ^(seg-sex, 8h-18h^)
echo   BlogPauta       - gera pautas toda segunda as 9h
echo   BlogTelegramBot - bot daemon ^(sempre ativo^)
echo.
echo Para verificar: schtasks /query /tn "BlogReleases"
echo Para remover:   schtasks /delete /tn "BlogReleases" /f
echo ============================================================
pause
