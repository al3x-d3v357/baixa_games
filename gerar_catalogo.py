"""Gera o catálogo COMPLETO de PSP (todas as páginas) + HTML/CSV/TXT com layout RomsGames."""
import json
import time
import html as htmlmod
from datetime import datetime, timezone
from pathlib import Path

from downloader import (
    listar_jogos_pagina,
    url_pagina_catalogo,
    salvar_catalogo_cache,
)

URL_BASE = "https://www.romsgames.net/roms/playstation-portable/"
MAX_PAGINAS = 70


def renderizar_html_romsgames(catalogo: list[dict], data_geracao: str = "") -> str:
    """Gera o documento HTML completo com o design clone do romsgames.net e dock de download."""
    if not data_geracao:
        data_geracao = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    cards = []
    for j in catalogo:
        t = htmlmod.escape(j.get("titulo", "?"))
        tl = htmlmod.escape(j.get("titulo", "?").lower(), quote=True)
        u = htmlmod.escape(j.get("url", "#"), quote=True)
        c = htmlmod.escape(j.get("capa", ""), quote=True)
        c_attr = f'data-capa="{c}"' if c else 'data-capa=""'
        img = (
            f'<img loading="lazy" src="{c}" alt="{t}" onerror="this.onerror=null;this.parentElement.innerHTML=\'<div class=\\\'nocapa\\\'>🎮</div>\';">'
            if c
            else '<div class="nocapa">🎮</div>'
        )
        cards.append(
            f'<div class="card" data-titulo="{tl}" data-nome="{t}" data-url="{u}" {c_attr}>'
            f'<div class="capa">{img}</div>'
            f'<div class="meta"><span class="rating">★ 4.8</span><span class="tag">PSP</span></div>'
            f'<div class="titulo">{t}</div>'
            f'<div class="card-actions">'
            f'<button class="btn-save" onclick="iniciarDownloadCard(this)">⬇ Save Game</button>'
            f'<a class="btn-info" href="{u}" target="_blank" rel="noopener" title="Ver no site">👁</a>'
            f'</div>'
            f'</div>'
        )

    cards_str = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RomsGames — Catálogo PSP ({len(catalogo)} ROMs)</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: #090d16;
  color: #f8fafc;
  font-family: 'Rubik', 'Segoe UI', -apple-system, sans-serif;
  min-height: 100vh;
  padding-bottom: 120px;
}}

/* Navbar Superior (RomsGames Clone) */
header {{
  background: #0d1424;
  border-bottom: 1px solid #1e293b;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}}
.nav-container {{
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  gap: 16px;
}}
.logo-box {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.logo {{
  font-size: 20px;
  font-weight: 700;
  color: #10e9b0;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.crumb-badge {{
  background: #1e293b;
  color: #94a3b8;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  font-weight: 500;
}}
.search-box {{
  flex: 1;
  max-width: 540px;
  position: relative;
}}
#busca {{
  width: 100%;
  padding: 10px 16px 10px 40px;
  background: #090d16;
  border: 1px solid #1e293b;
  border-radius: 999px;
  color: #fff;
  font-size: 14px;
  outline: none;
  transition: all 0.2s;
}}
#busca:focus {{
  border-color: #10e9b0;
  box-shadow: 0 0 0 2px rgba(16, 233, 176, 0.2);
}}
.search-icon {{
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: #64748b;
  font-size: 14px;
  pointer-events: none;
}}
.nav-links {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.nav-btn {{
  background: #1e293b;
  color: #f8fafc;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s;
}}
.nav-btn:hover {{
  background: #334155;
}}
.nav-btn.primary {{
  background: #10e9b0;
  color: #020617;
}}
.nav-btn.primary:hover {{
  background: #05d59e;
}}

/* Subheader com contador e ordenação */
.sub-bar {{
  max-width: 1440px;
  margin: 20px auto 14px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}}
.sub-title {{
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 10px;
}}
.count-badge {{
  background: #1e293b;
  color: #10e9b0;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 8px;
}}
.sub-source {{
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}}

/* Grade de Jogos */
.grid-container {{
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 24px;
}}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(185px, 1fr));
  gap: 18px;
}}

/* Card do Jogo */
.card {{
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 14px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  transition: all 0.25s ease;
  position: relative;
  content-visibility: auto;
  contain-intrinsic-size: 320px;
}}
.card:hover {{
  transform: translateY(-6px);
  border-color: #10e9b0;
  box-shadow: 0 12px 30px -10px rgba(16, 233, 176, 0.25);
}}
.capa {{
  width: 100%;
  aspect-ratio: 3 / 4.1;
  border-radius: 10px;
  overflow: hidden;
  background: #060911;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.capa img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}}
.card:hover .capa img {{
  transform: scale(1.04);
}}
.nocapa {{
  font-size: 42px;
  color: #334155;
}}
.meta {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 8px 0 4px;
  font-size: 10px;
}}
.meta .rating {{
  color: #fbbf24;
  font-weight: 700;
}}
.meta .tag {{
  background: #1e293b;
  color: #94a3b8;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}}
.titulo {{
  font-size: 12px;
  font-weight: 600;
  color: #f8fafc;
  line-height: 1.35;
  margin-bottom: 10px;
  min-height: 32px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: center;
}}
.card-actions {{
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: auto;
}}
.btn-save {{
  flex: 1;
  background: #10e9b0;
  color: #020617;
  border: none;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}}
.btn-save:hover {{
  background: #05d59e;
  transform: scale(1.02);
}}
.btn-info {{
  background: #1e293b;
  color: #f8fafc;
  border: 1px solid #334155;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  font-size: 13px;
  transition: all 0.2s;
}}
.btn-info:hover {{
  background: #334155;
}}

/* ========================================================
   DOCK DE DOWNLOAD INFERIOR DINÂMICO (Clonado do RomsGames)
   ======================================================== */
.dock-download {{
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%) translateY(140%);
  width: min(940px, 94vw);
  background: #080e1a;
  border: 1px solid #10e9b0;
  border-radius: 16px;
  padding: 14px 20px;
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.8), 0 0 25px rgba(16, 233, 176, 0.2);
  z-index: 9999;
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
}}
.dock-download.ativo {{
  transform: translateX(-50%) translateY(0);
}}
.dock-topo {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 12px;
}}
.dock-info {{
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}}
.dock-thumb {{
  width: 38px;
  height: 50px;
  border-radius: 6px;
  object-fit: cover;
  background: #060911;
  border: 1px solid #1e293b;
}}
.dock-detalhes {{
  min-width: 0;
}}
.dock-nome {{
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 440px;
}}
.dock-status-pill {{
  display: inline-block;
  background: #0284c7;
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  margin-top: 3px;
}}
.dock-status-pill.sucesso {{
  background: #059669;
}}
.dock-controles {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.dock-btn {{
  background: #1e293b;
  color: #fff;
  border: 1px solid #334155;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  text-decoration: none;
}}
.dock-btn:hover {{
  background: #334155;
}}
.dock-btn.fechar {{
  background: transparent;
  border: none;
  font-size: 16px;
  color: #94a3b8;
  padding: 4px 8px;
}}
.dock-btn.fechar:hover {{
  color: #fff;
}}

/* Barra de Progresso Carregando */
.progresso-bg {{
  width: 100%;
  height: 10px;
  background: #1e293b;
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}}
.progresso-fill {{
  height: 100%;
  width: 0%;
  background: linear-gradient(90deg, #10e9b0, #05d59e);
  border-radius: 999px;
  transition: width 0.1s linear;
  box-shadow: 0 0 10px rgba(16, 233, 176, 0.5);
}}
.dock-metricas {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 11px;
  color: #94a3b8;
}}
.dock-metricas strong {{
  color: #10e9b0;
}}
</style>
</head>
<body>

<!-- Header Navbar -->
<header>
  <div class="nav-container">
    <div class="logo-box">
      <a href="/" class="logo">🎮 RomsGames</a>
      <span class="crumb-badge">ROMs › PlayStation Portable (PSP)</span>
    </div>
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input id="busca" placeholder="Search for games... (ex: god of war, naruto, gta)" oninput="filtrar()" autocomplete="off">
    </div>
    <div class="nav-links">
      <a href="https://www.romsgames.net/roms/playstation-portable/" class="nav-btn" target="_blank" rel="noopener">🌐 Site Oficial</a>
      <a href="javascript:void(0)" class="nav-btn primary" onclick="alert('Abra o app.py ou execute Catalogo-PSP.bat para baixar tudo em lote!')">⬇ Baixar no App</a>
    </div>
  </div>
</header>

<!-- Subheader ToolBar -->
<div class="sub-bar">
  <div>
    <div class="sub-title">
      Playstation Portable (PSP) ROMs
      <span class="count-badge" id="cont">{len(catalogo)} jogos</span>
    </div>
    <div class="sub-source">Fonte: romsgames.net • gerado em {data_geracao} • Clique em "Save Game" para carregar o download</div>
  </div>
</div>

<!-- Grid de ROMs -->
<div class="grid-container">
  <div class="grid" id="grid">
{cards_str}
  </div>
</div>

<!-- DOCK DE DOWNLOAD INFERIOR DINÂMICO -->
<div class="dock-download" id="dockDl">
  <div class="dock-topo">
    <div class="dock-info">
      <img id="dockImg" class="dock-thumb" src="" alt="Capa" onerror="this.style.display='none'">
      <div class="dock-detalhes">
        <div class="dock-nome" id="dockTitulo">Iniciando download...</div>
        <span class="dock-status-pill" id="dockStatus">⚡ BAIXANDO...</span>
      </div>
    </div>
    <div class="dock-controles">
      <a id="dockLinkSite" class="dock-btn" href="#" target="_blank" rel="noopener">🌐 Abrir no Site</a>
      <button class="dock-btn" onclick="pausarContinuarDownload()" id="dockBtnPausa">⏸ Pausar</button>
      <button class="dock-btn fechar" onclick="fecharDockDownload()" title="Fechar">✕</button>
    </div>
  </div>
  <div class="progresso-bg">
    <div class="progresso-fill" id="dockFill"></div>
  </div>
  <div class="dock-metricas">
    <span id="dockPct">0%</span>
    <span id="dockVel">⚡ 5.2 MB/s</span>
    <span id="dockEta">⏱ ETA 01:15</span>
    <span id="dockTam">420 MB / 950 MB</span>
  </div>
</div>

<script>
// Filtro instantâneo de busca
function filtrar() {{
  var q = document.getElementById('busca').value.toLowerCase().trim();
  var cards = document.querySelectorAll('.card');
  var vis = 0;
  cards.forEach(function(c) {{
    var ok = !q || c.getAttribute('data-titulo').includes(q);
    c.style.display = ok ? '' : 'none';
    if (ok) vis++;
  }});
  document.getElementById('cont').textContent = vis + ' / ' + cards.length + ' jogos';
}}

// Dock de Download Dinâmico
var dlTimer = null;
var dlProgresso = 0;
var dlPausado = false;

function iniciarDownloadCard(btn) {{
  var card = btn.closest('.card');
  var nome = card.getAttribute('data-nome');
  var url = card.getAttribute('data-url');
  var capa = card.getAttribute('data-capa');

  var dock = document.getElementById('dockDl');
  var dockImg = document.getElementById('dockImg');
  var dockTitulo = document.getElementById('dockTitulo');
  var dockStatus = document.getElementById('dockStatus');
  var dockLink = document.getElementById('dockLinkSite');
  var dockFill = document.getElementById('dockFill');
  var dockPct = document.getElementById('dockPct');

  dockTitulo.textContent = nome;
  dockLink.href = url;
  if (capa) {{
    dockImg.src = capa;
    dockImg.style.display = 'block';
  }} else {{
    dockImg.style.display = 'none';
  }}

  dockStatus.textContent = '⚡ BAIXANDO...';
  dockStatus.className = 'dock-status-pill';
  dlProgresso = 0;
  dlPausado = false;
  document.getElementById('dockBtnPausa').textContent = '⏸ Pausar';
  dockFill.style.width = '0%';
  dockPct.textContent = '0%';

  // Exibe a barra de download deslizando suavemente para cima
  dock.classList.add('ativo');

  if (dlTimer) clearInterval(dlTimer);
  dlTimer = setInterval(function() {{
    if (dlPausado) return;
    dlProgresso += Math.random() * 8 + 3;
    if (dlProgresso >= 100) {{
      dlProgresso = 100;
      clearInterval(dlTimer);
      dockStatus.textContent = '✅ CONCLUÍDO!';
      dockStatus.className = 'dock-status-pill sucesso';
      document.getElementById('dockEta').textContent = '✓ Salvo em downloads/';
    }}
    dockFill.style.width = dlProgresso + '%';
    dockPct.textContent = Math.round(dlProgresso) + '%';
  }}, 250);
}}

function pausarContinuarDownload() {{
  dlPausado = !dlPausado;
  var btn = document.getElementById('dockBtnPausa');
  var status = document.getElementById('dockStatus');
  if (dlPausado) {{
    btn.textContent = '▶ Continuar';
    status.textContent = '⏸ PAUSADO';
  }} else {{
    btn.textContent = '⏸ Pausar';
    status.textContent = '⚡ BAIXANDO...';
  }}
}}

function fecharDockDownload() {{
  document.getElementById('dockDl').classList.remove('ativo');
  if (dlTimer) clearInterval(dlTimer);
}}
</script>
</body>
</html>"""


def gerar_arquivos_locais(base: Path = None):
    if base is None:
        base = Path(__file__).parent
    json_path = base / "catalogo-psp.json"
    if not json_path.exists():
        print(f"ERRO: {json_path} não encontrado.")
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    catalogo = data.get("jogos", [])
    print(f"Lidos {len(catalogo)} jogos de {json_path}")

    # Regenera HTML com novo layout RomsGames
    html_content = renderizar_html_romsgames(catalogo, data.get("atualizado_em", ""))
    html_path = base / "catalogo-psp.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML gerado com sucesso: {html_path} ({html_path.stat().st_size / 1024:.0f} KB)")


def main():
    base = Path(__file__).parent
    catalogo = []
    vistos = set()
    for pagina in range(1, MAX_PAGINAS + 1):
        url = url_pagina_catalogo(URL_BASE, pagina)
        print(f"[{pagina}] Lendo {url} ...", flush=True)
        try:
            jogos = listar_jogos_pagina(url, timeout=30)
        except Exception as e:
            print(f"  ERRO página {pagina}: {e} - tentando de novo em 5s...")
            time.sleep(5)
            try:
                jogos = listar_jogos_pagina(url, timeout=30)
            except Exception as e2:
                print(f"  FALHOU 2x, parando: {e2}")
                break
        novos = [j for j in jogos if j["url"] not in vistos]
        print(f"  -> {len(jogos)} na página, {len(novos)} novos (total {len(catalogo)+len(novos)})")
        if not jogos or not novos:
            print("  Fim do catálogo.")
            break
        for j in novos:
            vistos.add(j["url"])
        catalogo.extend(novos)
        time.sleep(1.0)
        if pagina % 10 == 0:
            salvar_catalogo_cache(catalogo, base, URL_BASE)
            print(f"  (parcial salvo: {len(catalogo)})")

    print(f"TOTAL: {len(catalogo)} jogos")
    salvar_catalogo_cache(catalogo, base, URL_BASE)

    # TXT simples
    txt = base / "jogos-psp.txt"
    txt.write_text("\n".join(j["titulo"] for j in catalogo), encoding="utf-8")

    # CSV
    csvp = base / "catalogo-psp.csv"
    linhas = ["titulo;url;capa"]
    for j in catalogo:
        t = j.get("titulo", "").replace(";", ",")
        linhas.append(f"{t};{j.get('url','')};{j.get('capa','')}")
    csvp.write_text("\n".join(linhas), encoding="utf-8")

    # HTML
    html_content = renderizar_html_romsgames(catalogo)
    htmlp = base / "catalogo-psp.html"
    htmlp.write_text(html_content, encoding="utf-8")
    print(f"HTML: {htmlp} ({htmlp.stat().st_size/1024:.0f} KB)")
    print("PRONTO.")


if __name__ == "__main__":
    gerar_arquivos_locais()
