@echo off
REM Cria o programinha instalador do Catalogo PSP (exe + setup)
REM Requer: Python 3.12 + Inno Setup 6 (ISCC no PATH)
cd /d "%~dp0"
echo [1/3] Instalando dependencias...
pip install -r requirements.txt
echo.
echo [2/3] Gerando CatalogoPSP.exe (pode demorar 2-5 min)...
pyinstaller --noconfirm --clean CatalogoPSP.spec
if errorlevel 1 (
  echo ERRO no PyInstaller. Veja o log acima.
  pause
  exit /b 1
)
echo.
echo [3/3] Gerando instalador (Inno Setup)...
where ISCC >nul 2>nul
if errorlevel 1 (
  echo ISCC nao encontrado. Instale o Inno Setup 6 em https://jrsoftware.org/isinfo.php
  echo O exe ja esta pronto em dist\CatalogoPSP.exe
  pause
  exit /b 0
)
ISCC instalador\CatalogoPSP.iss
if errorlevel 1 (
  echo ERRO no Inno Setup.
  pause
  exit /b 1
)
echo.
echo PRONTO: dist\CatalogoPSP-Setup-2.1.exe
pause
