@echo off
REM Programa local - Baixador Universal (2 cliques, sem digitar comando)
cd /d "%~dp0"
if not exist downloads mkdir downloads
python app.py
if errorlevel 1 (
  echo.
  echo ERRO ao abrir. Tentando instalar dependencias...
  pip install -r requirements.txt
  python app.py
)
pause
