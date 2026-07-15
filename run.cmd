@echo off
cd /d "%~dp0"
if "%DEEPSEEK_API_KEY%"=="" (
  echo [!] DEEPSEEK_API_KEY не задан. Выполни: setx DEEPSEEK_API_KEY "<ключ>" и открой терминал заново.
  pause
  exit /b 1
)
start "" http://localhost:8321
python -m uvicorn app:app --port 8321
