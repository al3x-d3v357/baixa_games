@echo off
REM Regenera o catalogo COMPLETO (62 paginas, ~2207 jogos) + HTML/CSV/TXT
cd /d "%~dp0"
pip install -r requirements.txt
py gerar_catalogo.py
pause
