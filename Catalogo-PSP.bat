@echo off
REM Catalogo PSP - abre a interface com os 2207 jogos (2 cliques)
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
