"""Integracao GamesTorrents (jogos PC via BitTorrent).

Fluxo do site (engenharia reversa de /assets/download.*.js):
1. pagina do jogo -> secao #releases -> links /descarga/<hash>/ (torrent e magnet)
2. POST /descarga/<hash>/ {action: prepare} -> {challenge, difficulty, needs_captcha}
3. proof-of-work: SHA-256("challenge:nonce") com `difficulty` nibbles zero
4. POST /descarga/<hash>/ {action: download, challenge, nonce} ->
   .torrent (application/x-bittorrent) ou JSON {kind: magnet, magnet_uri}

Tambem expoe busca instantanea via /api/search/ e listagem /juegos-pc/?page=N.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

GAMETORRENTS_BASE = "https://www.gamestorrents.app"
LOCALE_PADRAO = "es"

HEADERS_GT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,es;q=0.8,en;q=0.7",
}

LIMITE_TORRENT_BYTES = 10 * 1024 * 1024
MAX_NONCE = 2_000_000


class CaptchaNecessario(Exception):
    """O site exigiu hCaptcha (bloqueio anti-bot): so pelo navegador."""


def _sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS_GT)
    return s


# ---------------------------------------------------------------------------
# Busca instantanea (API JSON, sem protecao)
# ---------------------------------------------------------------------------

def buscar(termo: str, locale: str = LOCALE_PADRAO, timeout: int = 20) -> list[dict]:
    """Busca via /api/search/. Retorna [{titulo, url, capa, ano}]."""
    termo = (termo or "").strip()
    if not termo:
        return []
    r = _sessao().get(f"{GAMETORRENTS_BASE}/api/search/",
                      params={"q": termo, "locale": locale}, timeout=timeout)
    r.raise_for_status()
    out = []
    for it in (r.json().get("results") or []):
        url = urljoin(GAMETORRENTS_BASE, it.get("url", ""))
        capa = (it.get("image_original") or "").strip()
        capa = urljoin(GAMETORRENTS_BASE, capa) if capa.startswith("/") else (capa or it.get("image", ""))
        out.append({"titulo": it.get("title", "?")[:200], "url": url,
                    "capa": capa, "ano": str(it.get("year", ""))})
    return out


# ---------------------------------------------------------------------------
# Listagem /juegos-pc/?page=N
# ---------------------------------------------------------------------------

def url_listagem(pagina: int = 1) -> str:
    return f"{GAMETORRENTS_BASE}/juegos-pc/" + (f"?page={pagina}" if pagina > 1 else "")


def listar_jogos_pagina(url_ou_num: str | int, timeout: int = 20) -> tuple[list[dict], int]:
    """Devolve (jogos, total_paginas). Cada jogo: {titulo, url, capa}."""
    url = url_listagem(int(url_ou_num)) if isinstance(url_ou_num, int) else url_ou_num
    r = _sessao().get(url, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    jogos: list[dict] = []
    for art in soup.select("article.game-card"):
        a = art.select_one("h3 a") or art.select_one("a[href]")
        if not a or not a.get("href"):
            continue
        for sp in a.select("span.sr-only"):
            sp.decompose()
        titulo = " ".join(a.get_text(" ", strip=True).split())[:200]
        img = art.select_one("img")
        capa = ""
        if img:
            capa = (img.get("data-media-original") or img.get("src") or "").strip()
            if capa.startswith("/"):
                capa = urljoin(GAMETORRENTS_BASE, capa)
        if titulo:
            jogos.append({"titulo": titulo, "url": urljoin(url, a["href"]), "capa": capa})
    total = 1
    nav = soup.select_one("nav.pagination")
    if nav:
        import re
        m = re.search(r"(\d+)\s+de\s+(\d+)", nav.get_text(" ", strip=True))
        if m:
            total = int(m.group(2))
    return jogos, total


# ---------------------------------------------------------------------------
# Detalhe do jogo + releases (/descarga/)
# ---------------------------------------------------------------------------

def detalhes_jogo(url_jogo: str, timeout: int = 20) -> dict:
    """Extrai titulo, capa e releases [{fonte, versao, tamanho, idiomas, edicao,
    torrent_url, magnet_url}] da pagina do jogo."""
    r = _sessao().get(url_jogo, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    og = lambda p: (soup.find("meta", attrs={"property": p}) or {}).get("content", "")
    titulo = (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "") or og("og:title")
    titulo = " ".join(titulo.split())[:200] or "?"
    capa = og("og:image") or ""
    desc = og("og:description") or ""
    releases: list[dict] = []
    for art in soup.select("article.release-entry"):
        campos = {}
        for div in art.select("dl div"):
            dt, dd = div.find("dt"), div.find("dd")
            if dt and dd:
                campos[dt.get_text(" ", strip=True).lower()] = dd.get_text(" ", strip=True)
        lang = art.select_one(".release-languages dd")
        ed = art.select_one(".release-edition")
        torrent_url = magnet_url = ""
        for a in art.select('a[href^="/descarga/"], a[href^="/en/download/"], a[href^="/download/"]'):
            href = urljoin(r.url, a["href"])
            txt = a.get_text(" ", strip=True).lower()
            if "magnet" in txt:
                magnet_url = magnet_url or href
            else:
                torrent_url = torrent_url or href
        releases.append({
            "fonte": (art.get("data-release-source") or "").strip() or "?",
            "versao": campos.get("versión del juego", ""),
            "tamanho": campos.get("tamaño de la descarga", ""),
            "idiomas": lang.get_text(" ", strip=True) if lang else "",
            "edicao": ed.get_text(" ", strip=True)[:200] if ed else "",
            "torrent_url": torrent_url,
            "magnet_url": magnet_url,
        })
    return {"titulo": titulo, "url": r.url, "capa": capa, "descricao": desc[:800],
            "releases": releases}


# ---------------------------------------------------------------------------
# Resolucao /descarga/ (prepare + proof-of-work + download)
# ---------------------------------------------------------------------------

def _prova_trabalho(challenge: str, difficulty: int,
                    callback_log=None) -> str:
    """Encontra o nonce: SHA-256('challenge:nonce') com N nibbles zero."""
    if not challenge or not (1 <= int(difficulty) <= 6):
        raise RuntimeError("Desafio anti-bot invalido.")
    difficulty = int(difficulty)
    ini = time.time()
    n = 0
    while n < MAX_NONCE:
        dg = hashlib.sha256(f"{challenge}:{n}".encode()).digest()
        for i in range(difficulty):
            b = dg[i >> 1]
            if ((b >> 4) if i % 2 == 0 else (b & 15)) != 0:
                break
        else:
            if callback_log:
                callback_log(f"Verificacao anti-bot resolvida em {time.time() - ini:.1f}s.")
            return str(n)
        n += 1
        if n % 200_000 == 0 and callback_log:
            callback_log(f"Verificacao anti-bot... ({n // 1000}k tentativas)")
    raise RuntimeError("Nao resolvi o desafio anti-bot (tente de novo).")


def resolver_descarga(descarga_url: str, timeout: int = 60,
                      callback_log=None) -> tuple[str, bytes | str, str]:
    """Resolve /descarga/<hash>/ -> ('torrent', bytes, filename) ou
    ('magnet', magnet_uri, ''). Levanta CaptchaNecessario se o site exigir."""
    s = _sessao()
    s.headers["Referer"] = descarga_url
    s.get(descarga_url, timeout=timeout).raise_for_status()
    prep = s.post(descarga_url, data={"action": "prepare", "response": "json"},
                  headers={"Accept": "application/json, application/x-bittorrent"},
                  timeout=timeout)
    prep.raise_for_status()
    pj = prep.json()
    if pj.get("needs_captcha"):
        raise CaptchaNecessario(
            "O site exigiu verificacao hCaptcha. Abra o link no navegador, "
            f"baixe o .torrent e use a aba Torrent: {descarga_url}")
    nonce = _prova_trabalho(pj.get("challenge", ""), pj.get("difficulty", 0), callback_log)
    if callback_log:
        callback_log("Baixando .torrent/magnet do GamesTorrents...")
    fin = s.post(descarga_url,
                 data={"action": "download", "challenge": pj["challenge"],
                       "nonce": nonce, "response": "json", "h-captcha-response": ""},
                 headers={"Accept": "application/json, application/x-bittorrent"},
                 timeout=timeout)
    fin.raise_for_status()
    ct = fin.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ct == "application/x-bittorrent":
        if not (fin.content[:1] == b"d" and fin.content[-1:] == b"e"):
            raise RuntimeError("Resposta invalida do servidor (nao eh .torrent).")
        cd = fin.headers.get("Content-Disposition", "")
        import re
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
        nome = (m.group(1).strip() if m else "jogo.torrent")
        if not nome.lower().endswith(".torrent"):
            nome += ".torrent"
        return "torrent", fin.content, nome
    try:
        j = fin.json()
    except Exception:
        raise RuntimeError("Resposta inesperada do servidor.")
    if isinstance(j, dict) and j.get("kind") == "magnet" and str(j.get("magnet_uri", "")).startswith("magnet:"):
        return "magnet", j["magnet_uri"], ""
    if isinstance(j, dict) and j.get("error"):
        raise RuntimeError(f"GamesTorrents: {j['error']}"[:300])
    raise RuntimeError("Nao recebi o torrent nem o magnet.")


def baixar_release(release: dict, pasta: str | Path, preferir: str = "torrent",
                   callback_log=None, callback_progress=None, controle=None) -> Path:
    """Resolve um release (dict de detalhes_jogo) e baixa via motor torrent.

    Retorna o caminho final do jogo. Precisa de libtorrent instalado.
    """
    from torrent_downloader import download_torrent, parse_torrent_bytes
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    turl, murl = release.get("torrent_url", ""), release.get("magnet_url", "")
    alvo = turl if (preferir == "torrent" and turl) or not murl else murl
    if not alvo:
        raise RuntimeError("Release sem link de descarga.")
    kind, dados, nome = resolver_descarga(alvo, callback_log=callback_log)
    if kind == "magnet":
        return download_torrent(dados, pasta, callback_progress=callback_progress,
                                callback_log=callback_log, controle=controle)
    info = parse_torrent_bytes(dados)
    tmp = pasta / f"_gt_{info['info_hash']}.torrent"
    tmp.write_bytes(dados)
    try:
        return download_torrent(str(tmp), pasta, callback_progress=callback_progress,
                                callback_log=callback_log, controle=controle)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
