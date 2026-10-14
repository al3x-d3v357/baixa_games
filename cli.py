"""Catalogo PSP — terminal: listar, exportar e baixar um, varios ou TODOS."""
import argparse
import sys
from pathlib import Path

from downloader import (
    ControleDownload,
    analisar_site,
    anotar_catalogo,
    baixar_inteligente,
    carregar_catalogo,
    carregar_catalogo_cache,
    carregar_termos_de_arquivo,
    escanear_baixados,
    filtrar_catalogo,
    filtrar_por_nomes,
    pular_ja_baixados,
)

URL_PADRAO = "https://www.romsgames.net/roms/playstation-portable/"


def _cmd_meus_jogos(pasta: str):
    itens = escanear_baixados(pasta)
    finais = [i for i in itens if not i["incompleto"]]
    parts = [i for i in itens if i["incompleto"]]
    total_mb = sum(i["bytes"] for i in finais) / 1024 / 1024
    print(f"Meus jogos em ./{pasta}/: {len(finais)} completo(s), {total_mb:.1f} MB, "
          f"{len(parts)} incompleto(s)")
    for i in finais:
        print(f"  [OK] {i['arquivo']} ({i['bytes'] / 1024 / 1024:.1f} MB, {i['modificado_em']})")
    for i in parts:
        print(f"  [..] {i['arquivo']} (incompleto — rode o download p/ continuar)")
    return 0


def _obter_catalogo(url: str, paginas: int, atualizar: bool):
    """Cache primeiro (2207 jogos embutidos); so le o site se pedir --atualizar."""
    from downloader import salvar_catalogo_cache
    if not atualizar:
        cache = carregar_catalogo_cache(".")
        if len(cache.get("jogos", [])) >= 100:
            print(f"Catalogo em cache: {len(cache['jogos'])} jogos "
                  f"(atualizado em {cache.get('atualizado_em','?')[:10]}).")
            print("Use --atualizar para reler o site.")
            return cache["jogos"]
    print(f"Lendo site ({paginas or 'todas 62'} pagina(s)): {url}")
    catalogo = carregar_catalogo(url, max_paginas=paginas, timeout=30,
                                 callback_log=lambda m: print(f"  > {m}"))
    try:
        salvar_catalogo_cache(catalogo, ".", url)
    except Exception:
        pass
    return catalogo


def _cmd_catalogo(url: str, paginas: int, busca: str, pasta: str, atualizar: bool,
                  exportar: str = ""):
    catalogo = _obter_catalogo(url, paginas, atualizar)
    anotar_catalogo(catalogo, pasta)
    visiveis = filtrar_catalogo(catalogo, busca)
    n_baix = sum(1 for j in catalogo if j.get("ja_baixado"))
    print(f"{len(visiveis)}/{len(catalogo)} jogos (busca='{busca or '—'}'), {n_baix} ja baixados:")
    for n, jogo in enumerate(visiveis[:100], 1):
        tag = "BAIXADO" if jogo.get("ja_baixado") else "novo"
        print(f"  [{tag:>7}] {n}. {jogo['titulo']}")
    if len(visiveis) > 100:
        print(f"  ... e mais {len(visiveis)-100} (use --busca para filtrar ou --exportar)")
    if exportar:
        _exportar(visiveis, exportar)
    return 0


def _exportar(jogos: list, destino: str):
    p = Path(destino)
    baixo = destino.lower()
    if baixo.endswith(".csv"):
        linhas = ["titulo;url;capa"]
        for j in jogos:
            t = (j.get("titulo", "") or "").replace(";", ",")
            linhas.append(f"{t};{j.get('url','')};{j.get('capa','')}")
        p.write_text("\n".join(linhas), encoding="utf-8")
    elif baixo.endswith((".html", ".htm")):
        import html as htmlmod
        cards = []
        for j in jogos:
            t = htmlmod.escape(j.get("titulo", "?"))
            u = htmlmod.escape(j.get("url", "#"), quote=True)
            cards.append(f"<p><a href='{u}'>{t}</a></p>")
        p.write_text("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                     f"<title>PSP ({len(jogos)})</title></head><body>"
                     f"<h1>{len(jogos)} jogos PSP</h1>" + "".join(cards) + "</body></html>",
                     encoding="utf-8")
    else:
        p.write_text("\n".join(j.get("titulo", "") for j in jogos), encoding="utf-8")
    print(f"Exportado {len(jogos)} jogo(s) -> {p}")


def _cmd_baixar_catalogo(url: str, paginas: int, busca: str, pasta: str, atualizar: bool,
                         permitir_resume: bool, pular_existentes: bool, tentativas: int,
                         limite: int = 0):
    catalogo = _obter_catalogo(url, paginas, atualizar)
    anotar_catalogo(catalogo, pasta)
    visiveis = filtrar_catalogo(catalogo, busca)
    if pular_existentes:
        visiveis = [j for j in visiveis if not j.get("ja_baixado")]
    if limite > 0:
        visiveis = visiveis[:limite]
    if not visiveis:
        print("Nada a baixar (todos ja baixados ou busca vazia).")
        return 0
    print(f"Baixando {len(visiveis)} jogo(s) do catalogo para ./{pasta}/ ...")
    print("AVISO: cada jogo tem ~0.5-1.5 GB. O catalogo inteiro passa de 1 TB!")
    resp = input("Continuar? [s/N] ").strip().lower()
    if resp not in ("s", "sim", "y", "yes"):
        print("Cancelado.")
        return 0
    controle = ControleDownload()
    ok, falha, pulados = 0, 0, 0
    for i, jogo in enumerate(visiveis, 1):
        item = {"texto": jogo.get("titulo", ""), "nome_arquivo": jogo.get("titulo", ""),
                "url": jogo["url"], "extensao_url": ""}
        try:
            print(f"[{i}/{len(visiveis)}] {jogo['titulo']} ...", flush=True)
            dest = baixar_inteligente(item["url"], pasta, nome_base=item.get("nome_arquivo"),
                                      termos=[jogo.get("titulo", "")], extensoes=[],
                                      controle=controle,
                                      permitir_resume=permitir_resume,
                                      pular_existentes=pular_existentes,
                                      tentativas=tentativas,
                                      callback_log=lambda m: print(f"    > {m}"))
            print(f"  OK -> {dest}")
            ok += 1
        except KeyboardInterrupt:
            print("\nPAUSADO — progresso salvo em .part. Rode de novo para continuar.")
            break
        except Exception as e:
            print(f"  FALHOU: {e}")
            falha += 1
    anotar_catalogo(catalogo, pasta)
    print(f"Pronto: {ok} ok, {falha} falhas.")
    return 0


def _cmd_info_torrent(fonte: str):
    from torrent_downloader import is_magnet, parse_torrent
    fonte = (fonte or "").strip()
    if is_magnet(fonte):
        print(f"Magnet: {fonte[:100]}...")
        print("(metadados como nome/tamanho so aparecem apos buscar peers no download.)")
        return 0
    try:
        info = parse_torrent(fonte)
    except Exception as e:
        print(f"ERRO ao ler .torrent: {e}")
        return 1
    gb = info["tamanho"] / 1024 / 1024 / 1024
    print(f"Nome: {info['nome']}")
    print(f"Tamanho: {gb:.2f} GB ({info['tamanho']} bytes) em {info['num_arquivos']} arquivo(s)")
    print(f"Info-hash: {info['info_hash']}")
    print(f"Trackers: {len(info['trackers'])}")
    for f in info["arquivos"][:20]:
        print(f"  - {f['caminho']} ({f['bytes'] / 1024 / 1024:.1f} MB)")
    if info["num_arquivos"] > 20:
        print(f"  ... e mais {info['num_arquivos'] - 20}")
    print(f"Magnet: {info['magnet'][:120]}...")
    return 0


def _cmd_torrent(fonte: str, pasta: str):
    from torrent_downloader import download_torrent, is_magnet, parse_torrent
    from downloader import ControleDownload
    fonte = (fonte or "").strip()
    if not is_magnet(fonte):
        try:
            info = parse_torrent(fonte)
            gb = info["tamanho"] / 1024 / 1024 / 1024
            print(f"Torrent: {info['nome']} ({gb:.2f} GB, {info['num_arquivos']} arquivo(s))")
        except Exception as e:
            print(f"ERRO ao ler .torrent: {e}")
            return 1
    else:
        print(f"Magnet: {fonte[:80]}...")
    print(f"Destino: ./{pasta}/ (Ctrl+C pausa; rode de novo p/ continuar)")
    controle = ControleDownload()
    try:
        dest = download_torrent(
            fonte, pasta, controle=controle,
            callback_log=lambda m: print(f"  > {m}"),
            callback_progress=lambda rec, tot: print(
                f"\r  {rec / 1024 / 1024:.0f}/{tot / 1024 / 1024:.0f} MB "
                f"({rec / tot * 100:.1f}%)" if tot else f"\r  {rec / 1024 / 1024:.0f} MB",
                end="", flush=True),
        )
    except KeyboardInterrupt:
        print("\nPAUSADO — progresso salvo na pasta. Rode de novo para continuar.")
        return 130
    except Exception as e:
        print(f"\nFALHOU: {e}")
        return 1
    print(f"\nOK -> {dest}")
    return 0


def _cmd_gt_busca(termo: str):
    from gamestorrents import buscar
    try:
        res = buscar(termo)
    except Exception as e:
        print(f"ERRO na busca: {e}")
        return 1
    print(f"{len(res)} resultado(s) para '{termo}':")
    for j in res[:30]:
        print(f"  - {j['titulo']} ({j['ano']})")
        print(f"    {j['url']}")
    return 0


def _cmd_gt_pagina(n: int):
    from gamestorrents import listar_jogos_pagina
    try:
        jogos, total = listar_jogos_pagina(n)
    except Exception as e:
        print(f"ERRO ao listar: {e}")
        return 1
    print(f"Pagina {n}/{total} ({len(jogos)} jogos):")
    for j in jogos:
        print(f"  - {j['titulo']}\n    {j['url']}")
    return 0


def _cmd_gt_jogo(url: str):
    from gamestorrents import detalhes_jogo
    try:
        d = detalhes_jogo(url)
    except Exception as e:
        print(f"ERRO ao abrir jogo: {e}")
        return 1
    print(f"{d['titulo']}\n{d['url']}")
    if not d["releases"]:
        print("Sem releases com torrent.")
        return 0
    for i, rel in enumerate(d["releases"], 1):
        print(f"  [{i}] {rel['fonte']} {rel['versao']} {rel['tamanho']} {rel['idiomas']}")
    return 0


def _cmd_gt_baixar(url: str, pasta: str, fonte: str):
    from gamestorrents import baixar_release, detalhes_jogo
    from downloader import ControleDownload
    try:
        d = detalhes_jogo(url)
    except Exception as e:
        print(f"ERRO ao abrir jogo: {e}")
        return 1
    rels = d["releases"]
    if fonte:
        pref = [r for r in rels if fonte.lower() in r["fonte"].lower()]
        rels = pref or rels
    if not rels:
        print("Sem releases com torrent.")
        return 1
    rel = rels[0]
    print(f"Release: {rel['fonte']} {rel['versao']} {rel['tamanho']}")
    print(f"Destino: ./{pasta}/ (Ctrl+C pausa; rode de novo p/ continuar)")
    try:
        dest = baixar_release(rel, pasta, controle=ControleDownload(),
                              callback_log=lambda m: print(f"  > {m}"))
    except KeyboardInterrupt:
        print("\nPAUSADO — progresso salvo na pasta. Rode de novo para continuar.")
        return 130
    except Exception as e:
        print(f"FALHOU: {e}")
        return 1
    print(f"OK -> {dest}")
    return 0


def _cmd_analisar(exe: str, com_defender: bool):
    from instalador import analisar_setup, texto_relatorio
    try:
        rep = analisar_setup(exe, com_defender=com_defender,
                             callback_log=lambda m: print(f"  > {m}"))
    except Exception as e:
        print(f"ERRO na analise: {e}")
        return 1
    print(texto_relatorio(rep))
    return 0 if rep.get("veredito") in ("ok", "atencao") else 2


def _cmd_deps():
    from instalador import detectar_dependencias
    try:
        deps = detectar_dependencias()
    except Exception as e:
        print(f"ERRO: {e}")
        return 1
    for d in deps:
        tag = "INSTALADO" if d["instalado"] else "AUSENTE"
        print(f"[{tag:>9}] {d['id']}: {d['nome']} {d.get('detalhe', '')}")
    return 0


def _cmd_instalar_dep(dep_id: str):
    from instalador import detectar_dependencias, instalar_dependencia
    deps = detectar_dependencias()
    dep = next((d for d in deps if d["id"] == dep_id), None)
    if dep is None:
        print(f"Dependencia desconhecida: {dep_id} (use --deps para listar)")
        return 1
    if dep["instalado"]:
        print(f"{dep['nome']} ja instalado.")
        return 0
    try:
        instalar_dependencia(dep, callback_log=lambda m: print(f"  > {m}"))
    except Exception as e:
        print(f"FALHOU: {e}")
        return 1
    print(f"OK: {dep['nome']} instalado.")
    return 0


def _cmd_instalar_jogo(setup: str, destino: str, silencioso: bool):
    from instalador import instalar_jogo
    if not destino:
        print("Informe --destino DIR (ex: --destino C:\\Jogos\\Meu Jogo)")
        return 1
    try:
        res = instalar_jogo(setup, destino, silencioso,
                            callback_log=lambda m: print(f"  > {m}"))
    except Exception as e:
        print(f"FALHOU: {e}")
        return 1
    print(f"OK: jogo instalado em {res['destino']}")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Catalogo PSP (2207 jogos): listar, exportar e baixar.")
    ap.add_argument("--url", default=URL_PADRAO, help="URL da listagem (padrao: PSP)")
    ap.add_argument("--lista", default="", help="Caminho do lista.txt (um nome por linha)")
    ap.add_argument("--manual", default="", help='Nomes manuais separados por virgula. Ex: "god of war, tekken"')
    ap.add_argument("--ext", default="", help='Filtro de extensao. Ex: ".iso" ou ".iso,.zip" (vazio = qualquer)')
    ap.add_argument("--saida", default="downloads", help="Pasta onde salvar (padrao: downloads)")
    ap.add_argument("--sem-resume", action="store_true", help="Desliga o resume")
    ap.add_argument("--refazer", action="store_true", help="Baixa tudo de novo mesmo se ja existir")
    ap.add_argument("--tentativas", type=int, default=3, help="Retries por arquivo (padrao: 3)")
    ap.add_argument("--catalogo", type=int, default=-1, metavar="N",
                    help="Lista o catalogo (N paginas, 0=todas 62). Padrao: usa cache embutido")
    ap.add_argument("--busca", default="", help="Filtra por nome. Ex: --busca 'god of war'")
    ap.add_argument("--atualizar", action="store_true",
                    help="Rele o site em vez de usar o cache (lento: 62 paginas)")
    ap.add_argument("--exportar", default="", metavar="ARQ",
                    help="Exporta o catalogo filtrado (txt/csv/html). Ex: --exportar jogos.csv")
    ap.add_argument("--baixar-catalogo", action="store_true",
                    help="Baixa TODOS os jogos do catalogo (respeita --busca). CUIDADO: >1 TB!")
    ap.add_argument("--limite", type=int, default=0, help="Com --baixar-catalogo, baixa so os N primeiros")
    ap.add_argument("--meus-jogos", action="store_true", help="Lista o que ja foi baixado")
    ap.add_argument("--torrent", default="", metavar="FONTE",
                    help="Baixa via BitTorrent: caminho .torrent, magnet: ou URL de .torrent")
    ap.add_argument("--info-torrent", default="", metavar="FONTE",
                    help="So mostra nome/tamanho/arquivos do .torrent ou magnet (sem baixar)")
    ap.add_argument("--gt-busca", default="", metavar="TEXTO",
                    help="Busca jogos PC no GamesTorrents (ex: --gt-busca 'demon slayer')")
    ap.add_argument("--gt-pagina", type=int, default=0, metavar="N",
                    help="Lista a pagina N do catalogo GamesTorrents (/juegos-pc/)")
    ap.add_argument("--gt-jogo", default="", metavar="URL",
                    help="Mostra os releases (fonte/versao/tamanho) de um jogo do GamesTorrents")
    ap.add_argument("--gt-baixar", default="", metavar="URL",
                    help="Baixa um jogo do GamesTorrents via torrent (resolve anti-bot + motor torrent)")
    ap.add_argument("--gt-fonte", default="", metavar="NOME",
                    help="Com --gt-baixar, prefere o release desta fonte (ex: FitGirl). Padrao: primeiro")
    ap.add_argument("--analisar", default="", metavar="EXE",
                    help="Analisa um setup.exe (Defender + assinatura + PE) sem instalar")
    ap.add_argument("--sem-defender", action="store_true",
                    help="Com --analisar, pula o scan do Defender")
    ap.add_argument("--deps", action="store_true",
                    help="Lista dependencias (VC++, DirectX, .NET) e o que falta instalar")
    ap.add_argument("--instalar-dep", default="", metavar="ID",
                    help="Instala uma dependencia (vcx64, vcx86, dotnet8, directx)")
    ap.add_argument("--instalar-jogo", default="", metavar="SETUP",
                    help="Instala o jogo a partir do setup.exe (Inno Setup)")
    ap.add_argument("--destino", default="", metavar="DIR",
                    help="Pasta de instalacao (com --instalar-jogo). Ex: C:\\Jogos\\Meu Jogo")
    ap.add_argument("--interativo", action="store_true",
                    help="Com --instalar-jogo, mostra o instalador (padrao: silencioso)")
    args = ap.parse_args()

    if args.analisar:
        sys.exit(_cmd_analisar(args.analisar, not args.sem_defender))
    if args.deps:
        sys.exit(_cmd_deps())
    if args.instalar_dep:
        sys.exit(_cmd_instalar_dep(args.instalar_dep))
    if args.instalar_jogo:
        sys.exit(_cmd_instalar_jogo(args.instalar_jogo, args.destino, not args.interativo))

    if args.gt_busca:
        sys.exit(_cmd_gt_busca(args.gt_busca))
    if args.gt_pagina:
        sys.exit(_cmd_gt_pagina(args.gt_pagina))
    if args.gt_jogo:
        sys.exit(_cmd_gt_jogo(args.gt_jogo))
    if args.gt_baixar:
        sys.exit(_cmd_gt_baixar(args.gt_baixar, args.saida, args.gt_fonte))

    if args.info_torrent:
        sys.exit(_cmd_info_torrent(args.info_torrent))
    if args.torrent:
        sys.exit(_cmd_torrent(args.torrent, args.saida))
    if args.meus_jogos:
        sys.exit(_cmd_meus_jogos(args.saida))
    if args.baixar_catalogo:
        sys.exit(_cmd_baixar_catalogo(args.url, args.catalogo if args.catalogo >= 0 else 0,
                                      args.busca, args.saida, args.atualizar,
                                      not args.sem_resume, not args.refazer,
                                      args.tentativas, args.limite))
    if args.catalogo >= 0 or args.exportar:
        pags = args.catalogo if args.catalogo >= 0 else 0
        sys.exit(_cmd_catalogo(args.url, pags, args.busca, args.saida, args.atualizar, args.exportar))

    if not args.url:
        ap.error("--url e obrigatorio (ou use --catalogo / --meus-jogos)")

    termos: list[str] = []
    if args.lista:
        termos += carregar_termos_de_arquivo(args.lista)
    if args.manual:
        termos += [t.strip() for t in args.manual.split(",") if t.strip()]

    extensoes = [e.strip() for e in args.ext.split(",") if e.strip()] if args.ext else []
    permitir_resume = not args.sem_resume
    pular_existentes = not args.refazer
    controle = ControleDownload()

    print(f"[1/3] Analisando site: {args.url}")
    try:
        links = analisar_site(args.url)
    except Exception as e:
        print(f"ERRO ao analisar site: {e}")
        sys.exit(1)
    print(f"      Encontrados {len(links)} links na pagina.")

    encontrados = filtrar_por_nomes(links, termos, extensoes)
    print(f"[2/3] Termos={termos or '— (vazio = baixar tudo)'} | Ext={extensoes or 'qualquer'}")
    print(f"      {len(encontrados)} arquivo(s) apos filtro.")

    if not encontrados:
        print("Nada para baixar.")
        for l in links[:10]:
            print(f"  - {l['nome_arquivo']} | {l['texto'][:60]} | {l['url']}")
        sys.exit(0)

    pendentes, pulados = (encontrados, [])
    if pular_existentes:
        pendentes, pulados = pular_ja_baixados(encontrados, args.saida)
        for p in pulados:
            print(f"  = PULADO (ja existe): {p.get('nome_arquivo')}")
    if not pendentes:
        print(f"Tudo ja baixado ({len(pulados)} pulados). Nada a fazer.")
        sys.exit(0)

    print(f"[3/3] Baixando {len(pendentes)} para ./{args.saida}/ ...")
    ok, falha = 0, 0
    for item in pendentes:
        try:
            print(f"  > {item['nome_arquivo']} ({item['url']}) ...", end=" ", flush=True)
            dest = baixar_inteligente(item["url"], args.saida, nome_base=item.get("nome_arquivo"),
                                      termos=termos, extensoes=extensoes,
                                      controle=controle,
                                      permitir_resume=permitir_resume,
                                      pular_existentes=pular_existentes,
                                      tentativas=args.tentativas,
                                      callback_log=lambda m: print(f"\n    > {m}"))
            print(f"OK -> {dest}")
            ok += 1
        except KeyboardInterrupt:
            print("\nPAUSADO — progresso salvo em .part. Rode de novo para continuar.")
            controle.cancelar()
            sys.exit(130)
        except Exception as e:
            print(f"FALHOU: {e}")
            falha += 1
    print(f"Pronto: {ok} ok, {len(pulados)} pulados, {falha} falhas.")


if __name__ == "__main__":
    main()
