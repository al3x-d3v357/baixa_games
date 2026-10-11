# 🎮 Catálogo PSP — 2207 jogos (com download)

Programa + arquivos de catálogo com **todos os jogos de PSP do romsgames.net**
(62 páginas lidas em 05/10/2026). Busque, marque com ✓ e baixe **um, vários ou TODOS**,
com resume, pausa e anti-duplicado.

## Arquivos do catálogo (já prontos — pode baixar / abrir direto)

| Arquivo | O que é |
|---|---|
| `catalogo-psp.json` | Base completa: 2207 jogos com título + URL + capa |
| `catalogo-psp.html` | Catálogo navegável offline: abra no navegador, busque e clique em “Página do jogo” |
| `catalogo-psp.csv` | Planilha (título;url;capa) — abre no Excel |
| `jogos-psp.txt` | Um título por linha (2207 linhas) |
| `app.py` | Programa catálogo (interface dark) |
| `gerar_catalogo.py` | Re-gera tudo do zero lendo as 62 páginas |

## 1. Usar o programa (2 cliques, sem instalar nada)

- **`Catalogo-PSP.bat`** — abre o catálogo (recomendado)
- `Baixador.bat` — mesmo programa (atalho antigo)
- Arquivos baixados vão para `downloads/` ao lado do programa

Aba **🗂 Catálogo (2207)** (já abre nela):
1. O catálogo embutido carrega sozinho — digite na busca (ex: `god of war`)
2. Marque com ✓ (ou `✓ Todos`), clique **⬇ Baixar marcados**
3. **⬇⬇ Baixar TUDO** baixa os visíveis (com confirmação — o pack inteiro passa de 1 TB!)
4. **📤 Exportar** salva marcados/visíveis em TXT, CSV ou HTML
5. `🌐 Atualizar do site` relê as 62 páginas (demora ~3 min); `🔄 Atualizar status` recruza com sua pasta (badge ✓ BAIXADO)
6. Aba **💾 Meus jogos**: o que já baixou + tamanho total + `.part` incompletos (dá p/ continuar)

Para gerar o `.exe`: 2 cliques em `Gerar-EXE.bat` → sai `dist/CatalogoPSP.exe`
(com o catálogo de 2207 embutido).

## 2. Regenerar o catálogo do zero

```bash
pip install -r requirements.txt
py gerar_catalogo.py        # lê as 62 páginas (~3 min) e reescreve json+html+csv+txt
Gerar-Catalogo.bat          # mesmo, por 2 cliques
```

## 3. Rodar com Python

```bash
pip install -r requirements.txt
python app.py
```

## 4. Via terminal

```bash
# ver o que já foi baixado
python cli.py --meus-jogos --saida downloads

# listar do cache embutido (sem reler o site) + busca
python cli.py --catalogo 0 --busca "god of war" --saida downloads

# reler o site (62 páginas, lento) e exportar
python cli.py --catalogo 0 --atualizar --exportar jogos.csv --busca "naruto"

# exportar o catálogo inteiro filtrado
python cli.py --exportar todos.txt --busca "" --saida downloads

# BAIXAR TUDO do catálogo (respeita --busca; pede confirmação; >1 TB no total!)
python cli.py --baixar-catalogo --saida downloads
python cli.py --baixar-catalogo --busca "tekken" --limite 5 --saida downloads

# baixar por lista/manual (modo antigo, 1 página só)
python cli.py --url https://www.romsgames.net/roms/playstation-portable/ --lista lista.txt --saida downloads
python cli.py --url https://www.romsgames.net/roms/playstation-portable/ --manual "tekken 6, god of war" --saida downloads
```

## Como funciona

- `downloader.py:listar_jogos_pagina` — extrai os cards (`-rom-` + `<img>`) de uma página
- `downloader.py:carregar_catalogo` — percorre as 62 páginas até vir vazia/repetida
- `downloader.py:baixar_inteligente` — página → botão Save Game (POST `?download`) → arquivo; nunca salva `.html`
- Resume em `.part` + `Range`; `ControleDownload` pausa/continua/cancela; manifesto anti-duplicado
- Cache: `catalogo-psp.json` (+ capas em `capas/`) carrega na hora; o `.exe` leva o catálogo embutido (`_MEIPASS` fallback)

## Pastas

- `downloads/` — jogos baixados (criada automaticamente)
- `capas/` — miniaturas em cache
- `lista.txt` — exemplo de lista de nomes
