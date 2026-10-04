@echo off
REM Gera BaixadorUniversal.exe local (1 arquivo, com janela, sem console)
cd /d "%~dp0"
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name BaixadorUniversal --collect-all customtkinter --add-data "lista.txt;." app.py
echo.
echo Pronto: dist\BaixadorUniversal.exe
pause
