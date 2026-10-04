"""Uso via terminal: lista.txt ou nomes manuais (v2: resume + anti-duplicado)."""
import argparse
import sys
from pathlib import Path

from downloader import (
    ControleDownload,
    analisar_site,
    anotar_catalogo,
    baixar_inteligente,
    carregar_catalogo,
    carregar_termos_de_arquivo,
    escanear_baixados,
    filtrar_catalogo,
    filtrar_por_nomes,
    pular_ja_baixados,
)


def _cmd_meus_jogos(pasta: str):
    from downloader import NOME_MANIFESTO
    itens = escanear_baixados(pasta)
    finais = [i for i in itens if not i["incompleto"]]
    parts = [i for i in itens if i["incompleto"]]
    total_mb = sum(i["bytes"] for i in finais) / 1024 / 1024
    print(f"Meus jogos em ./{pasta}/: {len(finais)} completo(s), {total_mb:.1f} MB, "
          f"{len(parts)} incompleto(s)")
    for i in finais:
        print(f"  ✅ {i['arquivo']} ({i['bytes'] / 1024 / 1024:.1f} MB, {i['modificado_em']})")
    for i in parts:
        print(f"  ⏳ {i['arquivo']} (incompleto — rode o download p/ continuar)")
    return 0


def _cmd_catalogo(url: str, paginas: int, busca: str, pasta: str):
    print(f"Carregando catálogo ({paginas or 'todas'} página(s)): {url}")
    try:
        catalogo = carregar_catalogo(url, max_paginas=paginas, timeout=30,
                                     callback_log=lambda m: print(f"  ↳ {m}"))
    except Exception as e:
        print(f"ERRO ao carregar catálogo: {e}")
        return 1
    from downloader import salvar_catalogo_cache
    try:
        salvar_catalogo_cache(catalogo, ".", url)
    except Exception:
        pass
    anotar_catalogo(catalogo, pasta)
    visiveis = filtrar_catalogo(catalogo, busca)
    n_baix = sum(1 for j in catalogo if j.get("ja_baixado"))
    print(f"{len(visiveis)}/{len(catalogo)} jogos (busca='{busca or '—'}'), {n_baix} já baixados:")
    for n, jogo in enumerate(visiveis, 1):
        tag = "BAIXADO" if jogo.get("ja_baixado") else "novo"
        print(f"  [{tag:>7}] {n}. {jogo['titulo']}")
    return 0


def main():
    try:  # console Windows (cp1252) quebra com ✅/↳ — força UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Baixador universal: analisa site e baixa por nome.")
    ap.add_argument("--url", default="", help="URL do site a analisar. Ex: https://exemplo.com/downloads")
    ap.add_argument("--lista", default="", help="Caminho do lista.txt (um nome por linha)")
    ap.add_argument("--manual", default="", help='Nomes manuais separados por vírgula. Ex: "ubuntu 22, debian 12"')
    ap.add_argument("--ext", default="", help='Filtro de extensão. Ex: ".iso" ou ".iso,.zip" (vazio = qualquer)')
    ap.add_argument("--saida", default="downloads", help="Pasta onde salvar (padrão: downloads)")
    ap.add_argument("--sem-resume", action="store_true",
                    help="Desliga o resume (recomeça .part do zero em vez de continuar)")
    ap.add_argument("--refazer", action="store_true",
                    help="Baixa tudo de novo mesmo se o arquivo já existir (desliga anti-duplicado)")
    ap.add_argument("--tentativas", type=int, default=3, help="Retries de rede por arquivo (padrão: 3)")
    ap.add_argument("--catalogo", type=int, default=0, metavar="N",
                    help="Só lista o catálogo do site (N páginas, 0=todas) com status BAIXADO/novo, sem baixar")
    ap.add_argument("--busca", default="", help="Filtra o --catalogo por nome. Ex: --busca 'god of war'")
    ap.add_argument("--meus-jogos", action="store_true",
                    help="Só lista o que já foi baixado na pasta --saida (tamanhos + incompletos)")
    args = ap.parse_args()

    if args.meus_jogos:
        sys.exit(_cmd_meus_jogos(args.saida))
    if args.catalogo:
        if not args.url:
            ap.error("--catalogo precisa de --url (ex: .../roms/playstation-portable/)")
        sys.exit(_cmd_catalogo(args.url, args.catalogo, args.busca, args.saida))

    if not args.url:
        ap.error("--url é obrigatório para baixar (ou use --catalogo / --meus-jogos só para listar)")

    termos: list[str] = []
    if args.lista:
        termos += carregar_termos_de_arquivo(args.lista)
    if args.manual:
        termos += [t.strip() for t in args.manual.split(",") if t.strip()]

    extensoes = [e.strip() for e in args.ext.split(",") if e.strip()] if args.ext else []
    permitir_resume = not args.sem_resume
    pular_existentes = not args.refazer
    controle = ControleDownload()  # Ctrl+C chama controle.cancelar()

    print(f"[1/3] Analisando site: {args.url}")
    try:
        links = analisar_site(args.url)
    except Exception as e:
        print(f"ERRO ao analisar site: {e}")
        sys.exit(1)
    print(f"      Encontrados {len(links)} links na página.")

    encontrados = filtrar_por_nomes(links, termos, extensoes)
    print(f"[2/3] Termos={termos or '— (vazio = baixar tudo)'} | Ext={extensoes or 'qualquer'}")
    print(f"      {len(encontrados)} arquivo(s) após filtro.")

    if not encontrados:
        print("Nada para baixar. Dica: confira os nomes ou deixe --manual vazio para listar tudo.")
        for l in links[:10]:
            print(f"  - {l['nome_arquivo']} | {l['texto'][:60]} | {l['url']}")
        sys.exit(0)

    pendentes, pulados = (encontrados, [])
    if pular_existentes:
        pendentes, pulados = pular_ja_baixados(encontrados, args.saida)
        for p in pulados:
            print(f"  = PULADO (já existe): {p.get('nome_arquivo')} "
                  f"[{p.get('motivo_pulo', 'arquivo já existe na pasta')}]")
    if not pendentes:
        print(f"Tudo já baixado ({len(pulados)} pulados). Nada a fazer.")
        sys.exit(0)

    print(f"[3/3] Baixando {len(pendentes)} para ./{args.saida}/ "
          f"(resume={'on' if permitir_resume else 'off'}, Ctrl+C pausa e mantém .part) ...")
    ok, falha = 0, 0
    for item in pendentes:
        try:
            print(f"  ↓ {item['nome_arquivo']} ({item['url']}) ...", end=" ", flush=True)
            dest = baixar_inteligente(item["url"], args.saida, nome_base=item.get("nome_arquivo"),
                                      termos=termos, extensoes=extensoes,
                                      controle=controle,
                                      permitir_resume=permitir_resume,
                                      pular_existentes=pular_existentes,
                                      tentativas=args.tentativas,
                                      callback_log=lambda m: print(f"\n    ↳ {m}"))
            print(f"OK -> {dest}")
            ok += 1
        except KeyboardInterrupt:
            print("\nPAUSADO pelo usuário — progresso salvo em .part. Rode de novo para continuar.")
            controle.cancelar()
            sys.exit(130)
        except Exception as e:
            print(f"FALHOU: {e}")
            falha += 1
    print(f"Pronto: {ok} ok, {len(pulados)} pulados, {falha} falhas.")


if __name__ == "__main__":
    main()
