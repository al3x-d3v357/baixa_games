@echo off
REM Gera CatalogoPSP.exe (1 arquivo, com janela, sem console, catalogo+capas embutidos)
cd /d "%~dp0"
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name CatalogoPSP --collect-all customtkinter --add-data "catalogo-psp.json;." --add-data "capas;capas" app.py
echo.
echo Pronto: dist\CatalogoPSP.exe
pause
