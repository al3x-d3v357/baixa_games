"""Gera o catalogo COMPLETO de PSP (todas as paginas) + HTML/CSV/TXT."""
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
MAX_PAGINAS = 70  # trava de seguranca (site tem 62)

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
            print(f"  ERRO pagina {pagina}: {e} - tentando de novo em 5s...")
            time.sleep(5)
            try:
                jogos = listar_jogos_pagina(url, timeout=30)
            except Exception as e2:
                print(f"  FALHOU 2x, parando: {e2}")
                break
        novos = [j for j in jogos if j["url"] not in vistos]
        print(f"  -> {len(jogos)} na pagina, {len(novos)} novos (total {len(catalogo)+len(novos)})")
        if not jogos or not novos:
            print("  Fim do catalogo.")
            break
        for j in novos:
            vistos.add(j["url"])
        catalogo.extend(novos)
        time.sleep(1.0)  # educado com o site
        # salva parcial a cada 10 paginas (se cair, nao perde tudo)
        if pagina % 10 == 0:
            salvar_catalogo_cache(catalogo, base, URL_BASE)
            print(f"  (parcial salvo: {len(catalogo)})")

    print(f"TOTAL: {len(catalogo)} jogos")
    dest_json = salvar_catalogo_cache(catalogo, base, URL_BASE)
    print(f"JSON: {dest_json}")

    # TXT simples (um titulo por linha) - util p/ lista.txt
    txt = base / "jogos-psp.txt"
    txt.write_text("\n".join(j["titulo"] for j in catalogo), encoding="utf-8")
    print(f"TXT: {txt}")

    # CSV titulo;url;capa
    csvp = base / "catalogo-psp.csv"
    linhas = ["titulo;url;capa"]
    for j in catalogo:
        t = j.get("titulo", "").replace(";", ",")
        linhas.append(f"{t};{j.get('url','')};{j.get('capa','')}")
    csvp.write_text("\n".join(linhas), encoding="utf-8")
    print(f"CSV: {csvp}")

    # HTML navegavel offline (busca JS + cards com capa)
    cards = []
    for j in catalogo:
        t = htmlmod.escape(j.get("titulo", "?"))
        tl = htmlmod.escape(j.get("titulo", "?").lower(), quote=True)
        u = htmlmod.escape(j.get("url", "#"), quote=True)
        c = htmlmod.escape(j.get("capa", ""), quote=True)
        img = f'<img loading="lazy" src="{c}" onerror="this.style.display=\'none\'">' if c else '<div class="nocapa">🎮</div>'
        cards.append(
            f'<div class="card" data-titulo="{tl}">'
            f'<div class="capa">{img}</div>'
            f'<div class="titulo">{t}</div>'
            f'<a class="btn" href="{u}" target="_blank" rel="noopener">Página do jogo</a>'
            f'</div>'
        )
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    html_doc = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catálogo PSP — {len(catalogo)} jogos</title>
<style>
body{{background:#0f1115;color:#e5e7eb;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:20px}}
h1{{margin:0}} .sub{{color:#9aa3b2;margin:6px 0 16px}}
#busca{{width:100%;max-width:520px;padding:12px;border-radius:10px;border:1px solid #262b36;background:#0f1319;color:#fff;font-size:15px;margin-bottom:6px}}
#cont{{color:#9aa3b2;margin:8px 0 16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}}
.card{{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:10px;text-align:center}}
.capa img{{width:100%;height:150px;object-fit:cover;border-radius:8px;background:#0b0d11}}
.nocapa{{height:150px;display:flex;align-items:center;justify-content:center;font-size:48px;background:#0b0d11;border-radius:8px}}
.titulo{{font-size:13px;min-height:36px;margin:8px 0}}
.btn{{display:inline-block;background:#16a34a;color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-size:13px;font-weight:bold}}
.btn:hover{{background:#15803d}}
</style></head><body>
<h1>🎮 Catálogo PSP — {len(catalogo)} jogos</h1>
<div class="sub">Fonte: romsgames.net • gerado em {agora} • baixe pelo programa (app.py) ou abra a página do jogo</div>
<input id="busca" placeholder="🔍 Buscar jogo... (ex: god of war)" oninput="filtrar()">
<div id="cont"></div>
<div class="grid" id="grid">
{''.join(cards)}
</div>
<script>
function filtrar(){{
  var q=document.getElementById('busca').value.toLowerCase().trim();
  var cards=document.querySelectorAll('.card'); var vis=0;
  cards.forEach(function(c){{
    var ok=!q||c.getAttribute('data-titulo').includes(q);
    c.style.display=ok?'':'none'; if(ok)vis++;
  }});
  document.getElementById('cont').textContent=vis+'/'+cards.length+' jogos';
}}
filtrar();
</script></body></html>"""
    htmlp = base / "catalogo-psp.html"
    htmlp.write_text(html_doc, encoding="utf-8")
    print(f"HTML: {htmlp} ({htmlp.stat().st_size/1024:.0f} KB)")
    print("PRONTO.")

if __name__ == "__main__":
    main()
