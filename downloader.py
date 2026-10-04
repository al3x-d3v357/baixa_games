"""Núcleo do baixador: analisa site, filtra por nome e baixa arquivos.

Melhorias (v2):
- `if`s achatados: guard clauses + predicados pequenos, sem pirâmide.
- Resume: baixa em `.part` e continua de onde parou via `Range`.
- Anti-duplicado: manifesto + `pular_ja_baixados` (não baixa 2x o mesmo).
- `ControleDownload`: pausar / continuar / cancelar sem matar a thread.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup


# Content-Type -> extensão (complementa o mimetypes padrão)
# NOTA: text/html propositalmente NÃO está aqui — nunca salvamos .html
# como resultado. Se cair numa página, resolvemos o botão/link real.
CONTENT_TYPE_PARA_EXT = {
    "application/x-iso9660-image": ".iso",
    "application/x-iso-image": ".iso",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/x-7z-compressed": ".7z",
    "video/mp4": ".mp4",
    "video/x-msvideo": ".avi",
    "audio/mpeg": ".mp3",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

# Extensões que indicam PÁGINA intermediária (não arquivo final).
EXTENSOES_PAGINA = frozenset({".html", ".htm", ".xhtml", ".php", ".aspx", ".asp", ".jsp", ""})

# Extensões genéricas de CDN (output.bin) — o nome real vem do
# Content-Disposition / downloadName, não da URL.
EXTENSOES_GENERICAS = frozenset({".bin", ".cgi", ".pl", ".out", ".download", ".file"})

# Quando busca .iso, aceita containers de ROM (o .iso vem dentro do .zip)
MAPA_EQUIVALENTES = {
    ".iso": frozenset({".iso", ".zip", ".7z", ".rar", ".cso", ".pbp", ".chd", ".rvz"}),
    ".zip": frozenset({".zip", ".7z", ".rar"}),
    ".7z": frozenset({".7z", ".zip", ".rar"}),
}

NOME_MANIFESTO = ".baixador-manifest.json"
SUFFIX_PART = ".part"

HEADERS_PADRAO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ---------------------------------------------------------------------------
# Exceções de controle (para distinguir pulo/cancelamento de erro real)
# ---------------------------------------------------------------------------

class DownloadJaExiste(Exception):
    """Levantada quando o arquivo já foi baixado antes (anti-duplicado)."""

    def __init__(self, destino: Path):
        super().__init__(f"Já baixado, pulando: {destino.name}")
        self.destino = destino


class DownloadCancelado(Exception):
    """Levantada quando o usuário cancela (o `.part` é mantido p/ resume)."""


# ---------------------------------------------------------------------------
# Controle pause / continue / cancel (thread-safe)
# ---------------------------------------------------------------------------

class ControleDownload:
    """Permite pausar/continuar/cancelar um download em outra thread.

    Uso na GUI: um controle por lote; botões chamam pausar()/continuar().
    Uso no núcleo: `esperar_se_pausado()` é chamado a cada bloco.
    """

    def __init__(self):
        self._pausado = threading.Event()   # set = pausado
        self._cancelado = threading.Event()  # set = cancelar

    def pausar(self):
        self._pausado.set()

    def continuar(self):
        self._pausado.clear()

    def cancelar(self):
        self._cancelado.set()
        self._pausado.clear()  # destrava quem estava pausado

    @property
    def pausado(self) -> bool:
        return self._pausado.is_set()

    @property
    def foi_cancelado(self) -> bool:
        return self._cancelado.is_set()

    def esperar_se_pausado(self, callback_log=None):
        avisado = False
        while self._pausado.is_set() and not self._cancelado.is_set():
            if not avisado and callback_log:
                callback_log("Pausado — aguardando continuar...")
                avisado = True
            time.sleep(0.2)
        if self._cancelado.is_set():
            raise DownloadCancelado()


# ---------------------------------------------------------------------------
# Normalização / predicados pequenos (aqui mora a simplificação dos `if`s)
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, separadores viram espaço — busca tolerante."""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def termo_casa(termo_norm: str, alvo_norm: str) -> bool:
    """True se o termo aparece no alvo: substring direta OU todas as palavras."""
    if not termo_norm or not alvo_norm:
        return False
    if termo_norm in alvo_norm:
        return True
    palavras = termo_norm.split()
    return len(palavras) > 1 and all(p in alvo_norm for p in palavras)


def sanitizar_nome(nome: str) -> str:
    """Remove caracteres inválidos para nome de arquivo no Windows."""
    nome = unquote(nome).strip()
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome)
    nome = re.sub(r"\s+", " ", nome).strip(" .")
    return nome[:180] if len(nome) > 180 else nome or "arquivo"


def extensao_de_url(url: str) -> str:
    """Extrai .ext do path da URL. Retorna '' se não houver."""
    nome = os.path.basename(urlparse(url).path)
    _, ext = os.path.splitext(unquote(nome))
    ext = ext.lower().split("?")[0]
    return ext if re.fullmatch(r"\.[a-z0-9]{1,10}", ext or "") else ""


def normalizar_extensoes(extensoes: list[str] | None) -> list[str]:
    """['iso', '.ZIP'] -> ['.iso', '.zip']. Vazio/None -> []."""
    return [
        e.lower() if e.startswith(".") else f".{e.lower()}"
        for e in (extensoes or []) if e.strip()
    ]


def eh_pagina(ext: str) -> bool:
    return (ext or "").lower() in EXTENSOES_PAGINA


def eh_generico_cdn(ext: str) -> bool:
    return (ext or "").lower() in EXTENSOES_GENERICAS


def eh_conteudo_html(content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    return "text/html" in ct or "application/xhtml" in ct


def extensao_para_content_type(content_type: str) -> str:
    """Content-Type -> .ext, ignorando html/bin. Retorna '' se desconhecido."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct or "text/html" in ct or "application/xhtml" in ct:
        return ""
    ext = CONTENT_TYPE_PARA_EXT.get(ct, "")
    if ext or "octet-stream" in ct:
        return "" if ext in (".html", ".htm", ".bin") else ext
    try:
        adivinhada = mimetypes.guess_extension(ct) or ""
    except Exception:
        return ""
    return "" if adivinhada in (".html", ".htm", ".bin") else adivinhada


def extensoes_aceitas(exts_norm: list[str]) -> set[str]:
    """Filtro + equivalentes (.iso aceita .zip/.cso/...). Vazio = todas."""
    aceitas: set[str] = set()
    for e in exts_norm:
        aceitas.add(e)
        aceitas |= MAPA_EQUIVALENTES.get(e, set())
    return aceitas


def link_casa_termos(link: dict, termos_norm: list[str]) -> bool:
    """Predicado único de nome — substitui o `if` espalhado no filtro."""
    if not termos_norm:
        return True
    alvo = normalizar(f"{link.get('texto', '')} {link.get('nome_arquivo', '')} {link.get('url', '')}")
    return any(termo_casa(t, alvo) for t in termos_norm)


def link_casa_extensao(link: dict, exts_norm: list[str]) -> bool:
    """Páginas sempre passam (o arquivo está DENTRO delas)."""
    if not exts_norm:
        return True
    ext = (link.get("extensao_url") or "").lower()
    return not ext or ext in exts_norm or eh_pagina(ext)


# ---------------------------------------------------------------------------
# Análise do site
# ---------------------------------------------------------------------------

def _novo_item(url_abs: str, texto: str, nome: str) -> dict:
    return {
        "texto": (texto or "")[:200],
        "nome_arquivo": sanitizar_nome(nome or texto or "arquivo")[:200],
        "url": url_abs,
        "extensao_url": extensao_de_url(url_abs),
    }


def analisar_site(url_site: str, timeout: int = 20) -> list[dict]:
    """Baixa o HTML do site e extrai todos os links candidatos a arquivo."""
    resp = requests.get(url_site, headers=HEADERS_PADRAO, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    achados: list[dict] = []
    vistos: set[str] = set()

    def registrar(url_abs: str, texto: str, nome: str) -> None:
        # guard clauses: uma condição por linha, sem aninhar
        if not url_abs or url_abs in vistos:
            return
        if url_abs.startswith(("javascript:", "mailto:", "tel:", "#")):
            return
        vistos.add(url_abs)
        achados.append(_novo_item(url_abs, texto, nome))

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url_abs = urljoin(url_site, href)
        texto = a.get_text(" ", strip=True) or os.path.basename(urlparse(url_abs).path)
        nome = unquote(os.path.basename(urlparse(url_abs).path)) or texto
        registrar(url_abs, texto, nome)

    for tag in soup.find_all(attrs={"data-url": True}):
        url_abs = urljoin(url_site, tag["data-url"])
        registrar(url_abs, tag.get_text(" ", strip=True) or "botao-download",
                  os.path.basename(urlparse(url_abs).path) or "botao-download")

    for tag in soup.find_all(["source", "button", "div"]):
        for attr in ("src", "data-href", "data-link"):
            if not tag.has_attr(attr):
                continue
            url_abs = urljoin(url_site, tag[attr])
            if extensao_de_url(url_abs):
                registrar(url_abs, tag.get_text(" ", strip=True) or "recurso",
                          os.path.basename(urlparse(url_abs).path))
    return achados


def filtrar_por_nomes(
    links: list[dict],
    termos: list[str] | None = None,
    extensoes: list[str] | None = None,
) -> list[dict]:
    """Filtra links por nome + extensão, sem duplicar URLs.

    Termos vazios = retorna tudo (respeitando extensão).
    Páginas (.html/.php/sem extensão) sempre passam.
    """
    termos_norm = [normalizar(t) for t in (termos or []) if t.strip()]
    exts_norm = normalizar_extensoes(extensoes)
    vistos: set[str] = set()
    resultado = []
    for link in links:
        url = link.get("url", "")
        if url in vistos:
            continue
        if not link_casa_termos(link, termos_norm):
            continue
        if not link_casa_extensao(link, exts_norm):
            continue
        vistos.add(url)
        resultado.append(link)
    return resultado


def carregar_termos_de_arquivo(caminho: str | Path) -> list[str]:
    """Lê lista.txt: um nome por linha, ignora vazias e linhas com #."""
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo de lista não encontrado: {p}")
    return [
        linha.strip() for linha in p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if linha.strip() and not linha.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# Manifesto + anti-duplicado ("já baixou, não baixa de novo")
# ---------------------------------------------------------------------------

def _caminho_manifesto(pasta: Path) -> Path:
    return pasta / NOME_MANIFESTO


def carregar_manifesto(pasta: str | Path) -> dict:
    """Lê o JSON de concluídos. Arquivo ausente/corrompido -> {}."""
    caminho = _caminho_manifesto(Path(pasta))
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _salvar_manifesto(pasta: Path, dados: dict) -> None:
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        _caminho_manifesto(pasta).write_text(
            json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # manifesto é auxiliar — nunca pode quebrar o download


def marcar_concluido(pasta: str | Path, destino: Path, url: str = "") -> None:
    """Registra arquivo final no manifesto (chave = nome normalizado)."""
    pasta = Path(pasta)
    try:
        tamanho = destino.stat().st_size if destino.exists() else 0
    except OSError:
        tamanho = 0
    chave = f"{normalizar(destino.stem)}|{(destino.suffix or '').lower()}"
    dados = carregar_manifesto(pasta)
    dados[chave] = {
        "arquivo": destino.name,
        "url": url,
        "bytes": tamanho,
        "concluido_em": datetime.now(timezone.utc).isoformat(),
    }
    if url:
        dados[f"url::{url}"] = {"arquivo": destino.name, "bytes": tamanho}
    _salvar_manifesto(pasta, dados)


def _arquivo_existente_por_nome(pasta: Path, nome_base: str | None) -> Path | None:
    """Procura na pasta um arquivo final com o mesmo nome (exato ou fuzzy)."""
    if not nome_base or not pasta.exists():
        return None
    candidato = pasta / sanitizar_nome(unquote(nome_base))
    if candidato.exists() and candidato.is_file() and candidato.stat().st_size > 0:
        return candidato
    # fuzzy: mesmo stem normalizado + mesma extensão (ex: "God-of-War" == "god of war")
    base_norm = normalizar(Path(nome_base).stem)
    base_ext = Path(nome_base).suffix.lower()
    if not base_norm:
        return None
    for atual in pasta.glob("*"):
        if not atual.is_file() or atual.name in (NOME_MANIFESTO,) or atual.suffix == SUFFIX_PART:
            continue
        if atual.suffix.lower() != base_ext and base_ext:
            continue
        if normalizar(atual.stem) == base_norm and atual.stat().st_size > 0:
            return atual
    return None


def ja_baixado(pasta: str | Path, nome_base: str | None = None, url: str = "") -> Path | None:
    """Devolve o Path existente se já baixado, senão None.

    Ordem: 1) arquivo por nome na pasta, 2) registro url->arquivo no manifesto.
    `.part` (incompleto) NÃO conta como baixado — é para resume.
    """
    pasta = Path(pasta)
    achado = _arquivo_existente_por_nome(pasta, nome_base)
    if achado is not None:
        return achado
    if url:
        reg = carregar_manifesto(pasta).get(f"url::{url}")
        if isinstance(reg, dict):
            dest = pasta / reg.get("arquivo", "")
            if dest.exists() and dest.stat().st_size > 0:
                return dest
    return None


def pular_ja_baixados(itens: list[dict], pasta: str | Path) -> tuple[list[dict], list[dict]]:
    """Separa (pendentes, já_baixados). Também remove URLs repetidas na lista.

    Cada item pulado ganha a chave `arquivo_existente` com o Path encontrado.
    """
    pasta = Path(pasta)
    pendentes: list[dict] = []
    pulados: list[dict] = []
    urls_vistas: set[str] = set()
    for item in itens:
        url = item.get("url", "")
        if url in urls_vistas:  # duplicado dentro da própria lista
            pulados.append({**item, "motivo_pulo": "url repetida na lista"})
            continue
        urls_vistas.add(url)
        existente = ja_baixado(pasta, item.get("nome_arquivo"), url)
        if existente is not None:
            pulados.append({**item, "arquivo_existente": str(existente),
                            "motivo_pulo": "arquivo já existe na pasta"})
            continue
        pendentes.append(item)
    return pendentes, pulados


# ---------------------------------------------------------------------------
# Nome final (sem `if` em pirâmide: prioridades resolvidas em sequência)
# ---------------------------------------------------------------------------

def _nome_do_servidor(content_disp: str) -> str:
    if not content_disp:
        return ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disp)
    return unquote(m.group(1).strip()) if m else ""


def _escolher_extensao(ext_url: str, ext_srv: str, ext_base: str, content_type: str) -> str:
    ext_ct = extensao_para_content_type(content_type)
    if eh_generico_cdn(ext_url) or eh_pagina(ext_url):
        return ext_srv or ext_base or ext_ct
    return ext_url or ext_srv or ext_base or ext_ct


def _escolher_base(nome_servidor: str, nome_base: str | None, url: str) -> str:
    for candidata in (nome_servidor, nome_base or ""):
        _, eb = os.path.splitext(candidata)
        if candidata and not eh_pagina(eb) and not eh_generico_cdn(eb):
            return candidata
    crua = nome_servidor or nome_base or os.path.basename(urlparse(url).path) or "arquivo"
    _, eb = os.path.splitext(crua)
    if eh_pagina(eb) or eh_generico_cdn(eb):
        return nome_servidor or nome_base or "arquivo"
    return crua


def descobrir_nome_final(url: str, pasta: Path, nome_base: str | None,
                         content_type: str = "", content_disp: str = "") -> Path:
    """Define caminho final garantindo a extensão correta (nunca .html)."""
    pasta.mkdir(parents=True, exist_ok=True)
    if eh_conteudo_html(content_type):
        raise RuntimeError(
            "URL retornou página HTML, não arquivo. "
            "O resolvedor vai procurar o botão de download dentro dela."
        )
    nome_servidor = _nome_do_servidor(content_disp)
    ext_final = _escolher_extensao(
        extensao_de_url(url),
        extensao_de_url(nome_servidor) if nome_servidor else "",
        os.path.splitext(nome_base or "")[1].lower() if nome_base else "",
        content_type,
    )
    base = sanitizar_nome(unquote(_escolher_base(nome_servidor, nome_base, url)))
    base_sem_ext, _ = os.path.splitext(base)
    nome_final = base_sem_ext + ext_final if ext_final else base
    if nome_final.lower().endswith((".html", ".htm")):
        raise RuntimeError(f"Resolvido apenas HTML ({nome_final}). Sem botão de download válido.")
    destino = pasta / sanitizar_nome(nome_final)
    if not destino.exists():
        return destino
    stem, suffix = os.path.splitext(destino.name)
    i = 1
    while (pasta / f"{stem} ({i}){suffix}").exists():
        i += 1
    return pasta / f"{stem} ({i}){suffix}"


# ---------------------------------------------------------------------------
# Resolução página -> arquivo (botão de download)
# ---------------------------------------------------------------------------

def _extrair_candidatos_download(html: str, base_url: str) -> list[dict]:
    """Extrai da página de detalhe todos os candidatos a botão/arquivo."""
    soup = BeautifulSoup(html, "lxml")
    cands: list[dict] = []
    vistos: set[str] = set()

    def push(url: str, texto: str, eh_botao: bool):
        if not (url or "").strip():
            return
        url_abs = urljoin(base_url, url.strip())
        if not url_abs or url_abs in vistos:
            return
        if url_abs.startswith(("javascript:", "mailto:", "tel:", "#")):
            return
        vistos.add(url_abs)
        cands.append({
            "texto": (texto or "")[:200],
            "nome_arquivo": sanitizar_nome(unquote(os.path.basename(urlparse(url_abs).path)) or (texto or "botao-download"))[:200],
            "url": url_abs,
            "extensao_url": extensao_de_url(url_abs),
            "eh_botao": eh_botao,
        })

    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        cls = " ".join(a.get("class", [])).lower()
        eh_botao = bool(a.has_attr("download")) or "download" in cls or "btn" in cls
        if not eh_botao and normalizar(txt):
            eh_botao = any(p in normalizar(txt) for p in ("download", "baixar", "obter"))
        push(a["href"], txt or os.path.basename(urlparse(a["href"]).path), eh_botao)

    for tag in soup.find_all(attrs={"data-url": True}):
        push(tag["data-url"], tag.get_text(" ", strip=True) or "botao-download", True)

    # Botões tipo romsgames: <button data-media-id="16680">Save Game</button>
    for tag in soup.find_all(attrs={"data-media-id": True}):
        mid = (tag.get("data-media-id") or "").strip()
        if not mid:
            continue
        form = soup.find("form", id="download-form")
        action = form.get("action", "").strip() if form else base_url
        push(urljoin(base_url, action) + f"?download&mediaId={mid}",
             tag.get_text(" ", strip=True) or f"botao-media-{mid}", True)

    for tag in soup.find_all(["button", "source", "div", "form"]):
        for attr in ("src", "data-href", "data-link", "action"):
            if tag.has_attr(attr):
                push(tag[attr], tag.get_text(" ", strip=True) or "botao", True)
        onclick = tag.get("onclick", "") or ""
        for m in re.finditer(r"""(?:window\.location|href)\s*=\s*['"]([^'"]+)['"]""", onclick):
            push(m.group(1), tag.get_text(" ", strip=True) or "botao-onclick", True)
        for m in re.finditer(r"""['"](/[^'"]+\.\w{2,4}(?:\?[^'"]*)?)['"]""", onclick):
            push(m.group(1), tag.get_text(" ", strip=True) or "botao-onclick", True)

    meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
    if meta and meta.get("content", ""):
        m = re.search(r"url=(.+)", meta["content"], re.I)
        if m:
            push(m.group(1).strip(" '\""), "meta-refresh", True)
    return cands


def _pontuar_candidato(c: dict, termos_norm: list[str], exts_norm: list[str]) -> int:
    """Pontuação por tabela (sem cadeia de `if/else`): maior = melhor botão."""
    ext = (c.get("extensao_url") or "").lower()
    pts_ext = 5  # sem extensão: pode ser botão com URL limpa
    if exts_norm:
        pts_ext = 50 if ext in exts_norm else (0 if (not ext or eh_pagina(ext)) else -30)
    elif ext and not eh_pagina(ext):
        pts_ext = 20
    pts = pts_ext + (20 if c.get("eh_botao") else 0)
    alvo = normalizar(f"{c.get('texto', '')} {c.get('nome_arquivo', '')} {c.get('url', '')}")
    for t in termos_norm:
        if t and t in alvo:
            pts += 30
        elif t and len(t.split()) > 1 and all(p in alvo for p in t.split()):
            pts += 20
    if any(p in normalizar(c.get("texto", "")) for p in ("download", "baixar")):
        pts += 10
    return pts


def _resolver_romsgames(url_pagina: str, html: str, timeout: int = 20) -> str | None:
    """romsgames.net: botão Save Game -> POST ?download -> JSON com downloadUrl."""
    if "romsgames.net" not in url_pagina:
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
        btn = soup.find(attrs={"data-media-id": True})
        form = soup.find("form", id="download-form")
        if btn is None or form is None:
            return None
        media_id = (btn.get("data-media-id") or "").strip()
        if not media_id:
            return None
        action = (form.get("action") or "").strip() or url_pagina
        r = requests.post(
            urljoin(url_pagina, action) + "?download",
            headers={**HEADERS_PADRAO, "Accept": "application/json",
                     "Referer": url_pagina, "X-Requested-With": "XMLHttpRequest"},
            data={"mediaId": media_id},
            timeout=timeout,
        )
        r.raise_for_status()
        j = r.json()
        durl, dnome = j.get("downloadUrl", ""), j.get("downloadName", "")
        if not durl:
            return None
        durl_abs = urljoin(url_pagina, durl)
        if dnome and "attach=" not in durl_abs:
            durl_abs += ("&" if "?" in durl_abs else "?") + f"attach={dnome}"
        return durl_abs
    except Exception:
        return None


def resolver_download(url_pagina: str, termos: list[str] | None = None,
                      extensoes: list[str] | None = None, timeout: int = 20) -> str:
    """Dada uma PÁGINA, encontra a URL do ARQUIVO (melhor botão)."""
    termos_norm = [normalizar(t) for t in (termos or []) if t.strip()]
    exts_norm = normalizar_extensoes(extensoes)

    r = requests.get(url_pagina, headers=HEADERS_PADRAO, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    if not eh_conteudo_html(r.headers.get("Content-Type", "")):
        return r.url  # redirect já caiu direto no arquivo

    via_post = _resolver_romsgames(r.url, r.text, timeout=timeout)
    if via_post:
        return via_post

    cands = _extrair_candidatos_download(r.text, r.url)
    if not cands:
        raise RuntimeError(
            f"Página sem links de download: {url_pagina}. "
            "Nenhum <a>, botão ou data-url encontrado."
        )
    com_nome = [c for c in cands
                if not termos_norm or link_casa_termos(c, termos_norm)]
    base = com_nome or cands
    if exts_norm:
        arquivos = [c for c in base if (c.get("extensao_url") or "").lower() in exts_norm]
        base = arquivos or base
    melhor = max(base, key=lambda c: _pontuar_candidato(c, termos_norm, exts_norm))

    so_paginas = all(eh_pagina((c.get("extensao_url") or "").lower()) for c in base)
    if eh_pagina((melhor.get("extensao_url") or "").lower()) and so_paginas:
        raise RuntimeError(
            f"Só encontrei páginas HTML em {url_pagina} (ex: {melhor['url']}). "
            "Sem botão de arquivo. Confira se o site exige JavaScript/login."
        )
    return melhor["url"]


# ---------------------------------------------------------------------------
# Download com resume (.part + Range) + anti-duplicado + pause/cancel
# ---------------------------------------------------------------------------

def _headers_para(url_arquivo: bool, referer: str | None) -> dict:
    h = {"User-Agent": HEADERS_PADRAO["User-Agent"]}
    if url_arquivo:
        h["Accept"] = "*/*"
    else:
        h.update({k: v for k, v in HEADERS_PADRAO.items() if k != "User-Agent"})
    if referer:
        h["Referer"] = referer
    return h


def _gravar_stream_com_resume(
    url_final: str,
    destino_final: Path,
    referer: str | None,
    timeout: int,
    permitir_resume: bool,
    controle: ControleDownload | None,
    callback_progress=None,
    callback_log=None,
) -> Path:
    """Baixa a URL (que já é arquivo) com resume. Retorna o destino final."""
    destino_final.parent.mkdir(parents=True, exist_ok=True)
    part = destino_final.with_name(destino_final.name + SUFFIX_PART)
    baixados = 0
    if part.exists():
        if permitir_resume:
            baixados = part.stat().st_size
            if callback_log and baixados > 0:
                callback_log(f"Continuando de onde parou ({baixados / 1024 / 1024:.1f} MB já baixados)...")
        else:
            part.unlink()

    headers = _headers_para(True, referer)
    if baixados > 0:
        headers["Range"] = f"bytes={baixados}-"

    with requests.get(url_final, headers=headers, stream=True,
                       timeout=timeout, allow_redirects=True) as r:
        if r.status_code == 416:  # faixa além do fim = .part já está completo
            part.rename(destino_final)
            marcar_concluido(destino_final.parent, destino_final, url_final)
            return destino_final
        r.raise_for_status()
        retomou = r.status_code == 206
        if baixados > 0 and not retomou:
            if callback_log:  # servidor ignorou o Range: recomeça do zero
                callback_log("Servidor não aceitou continuar — recomeçando do zero.")
            baixados = 0
        total = int(r.headers.get("Content-Length", 0) or 0) or None
        total = (baixados + total) if (total and retomou) else total
        modo = "ab" if (retomou and baixados > 0) else "wb"
        recebidos = baixados
        with open(part, modo) as f:
            for bloco in r.iter_content(chunk_size=1024 * 256):
                if controle is not None:
                    controle.esperar_se_pausado(callback_log)  # levanta DownloadCancelado
                if not bloco:
                    continue
                f.write(bloco)
                recebidos += len(bloco)
                if callback_progress:
                    callback_progress(recebidos, total)
    # Troca atômica: só aparece o nome final quando está 100% completo
    if destino_final.exists():  # corrida: outro download criou o nome no meio
        destino_final = descobrir_nome_final(url_final, destino_final.parent, destino_final.name)
    part.rename(destino_final)
    marcar_concluido(destino_final.parent, destino_final, url_final)
    return destino_final


def baixar_inteligente(url: str, pasta: str | Path, nome_base: str | None = None,
                       termos: list[str] | None = None, extensoes: list[str] | None = None,
                       timeout: int = 60, callback_progress=None, callback_log=None,
                       controle: ControleDownload | None = None,
                       permitir_resume: bool = True,
                       pular_existentes: bool = True,
                       tentativas: int = 3) -> Path:
    """Baixa de verdade: resolve páginas até achar o arquivo; nunca salva .html.

    - `pular_existentes=True`: se o nome já está na pasta/manifesto, devolve
      o Path existente sem baixar de novo (log avisa "já existe").
    - `permitir_resume=True`: usa `.part` + `Range` para continuar de onde
      parou após pausa, queda de rede ou Ctrl+C.
    - `controle`: `ControleDownload` para pausar/continuar/cancelar.
    - `tentativas`: retries de rede com espera progressiva.
    """
    pasta = Path(pasta)
    exts_norm = normalizar_extensoes(extensoes)
    aceitas = extensoes_aceitas(exts_norm)

    if pular_existentes:
        existente = ja_baixado(pasta, nome_base, url)
        if existente is not None:
            if callback_log:
                callback_log(f"Já existe na pasta, pulando: {existente.name}")
            return existente

    atual, referer, ultimo_erro = url, None, None
    for nivel in range(3):  # página -> detalhe -> arquivo (máx 3 níveis)
        if controle is not None:
            controle.esperar_se_pausado(callback_log)
        for tentativa in range(1, tentativas + 1):
            try:
                with requests.get(atual, headers=_headers_para("static.romsgames.net" in atual, referer),
                                  stream=True, timeout=timeout, allow_redirects=True) as r:
                    r.raise_for_status()
                    url_final, ct, cd = r.url, r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
                    if eh_conteudo_html(ct) or (eh_pagina(extensao_de_url(url_final)) and not cd):
                        r.close()
                        referer = referer or url_final
                        if callback_log:
                            callback_log(f"Página detectada, procurando botão em: {url_final}")
                        nova = resolver_download(url_final, termos, extensoes, timeout=timeout)
                        if nova in (atual, url_final):
                            raise RuntimeError(f"Download travou na mesma página: {nova}")
                        if callback_log:
                            callback_log(f"Botão encontrado: {nova}")
                        atual, referer = nova, url_final
                        break  # sai do retry, avança um nível (página resolvida)

                    destino_tentativa = descobrir_nome_final(url_final, pasta, nome_base, ct, cd)
                    if exts_norm:
                        ext_dest = os.path.splitext(destino_tentativa.name)[1].lower()
                        if ext_dest and ext_dest not in aceitas and nivel == 0:
                            raise RuntimeError(
                                f"Arquivo {ext_dest} ignorado (filtro {exts_norm}): {url_final}"
                            )
                    # Nível>0 (veio do botão do site): aceita mesmo fora do
                    # filtro — ex: buscou .iso mas o site entrega .zip.
                    return _gravar_stream_com_resume(
                        url_final, destino_tentativa, referer or atual, timeout,
                        permitir_resume, controle, callback_progress, callback_log)
            except (DownloadCancelado, DownloadJaExiste, RuntimeError):
                raise
            except Exception as e:  # erro de rede: retry, depois tenta resolver botão
                ultimo_erro = e
                if tentativa < tentativas:
                    if callback_log:
                        callback_log(f"Falha de rede (tentativa {tentativa}/{tentativas}): {e} — repetindo...")
                    time.sleep(min(2 ** tentativa, 8))
                    continue
                try:
                    nova = resolver_download(atual, termos, extensoes, timeout=timeout)
                    if nova != atual:
                        atual = nova
                        break
                except Exception:
                    pass
                raise
        else:
            break
    raise RuntimeError(
        f"Não encontrei o arquivo (só páginas HTML) após 3 níveis a partir de {url}. "
        f"Último erro: {ultimo_erro}. O site pode exigir JavaScript ou login."
    )


def baixar_arquivo(url: str, pasta: str | Path, nome_base: str | None = None,
                   timeout: int = 60, callback_progress=None,
                   termos: list[str] | None = None, extensoes: list[str] | None = None,
                   controle: ControleDownload | None = None,
                   permitir_resume: bool = True,
                   pular_existentes: bool = True) -> Path:
    """Compat: nunca salva .html — resolve o botão; com resume + anti-duplicado."""
    return baixar_inteligente(url, pasta, nome_base, termos, extensoes,
                              timeout, callback_progress, None,
                              controle, permitir_resume, pular_existentes)


# ---------------------------------------------------------------------------
# Catálogo do site (todos os jogos) + Meus jogos (o que já foi baixado)
# ---------------------------------------------------------------------------

NOME_CACHE_CATALOGO = "catalogo-psp.json"
PASTA_CAPAS = "capas"

REGIOES_CONHECIDAS = (
    "united states", "europe", "japan", "germany", "france", "spain",
    "italy", "united kingdom", "australia", "korea", "china",
    "english", "usa",
)


def url_pagina_catalogo(url_base: str, numero: int) -> str:
    """Página 1 = URL base; demais = `?page=N&sort=popularity` (padrão romsgames)."""
    base = url_base.rstrip("/")
    if numero <= 1:
        return url_base
    sep = "&" if "?" in base else "?"
    return f"{base}/{sep}page={numero}&sort=popularity"


def listar_jogos_pagina(url_pagina: str, timeout: int = 20) -> list[dict]:
    """Extrai os cards de jogos de UMA página de listagem.

    Cada jogo: {titulo, url (detalhe), capa}. Levanta RequestException em falha.
    """
    resp = requests.get(url_pagina, headers=HEADERS_PADRAO, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    jogos: list[dict] = []
    vistos: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if "-rom-" not in href:  # cards de jogo têm `/...-rom-nome-do-jogo/`
            continue
        img = a.find("img")
        if img is None:  # sem capa = link de navegação, não card
            continue
        url_abs = urljoin(url_pagina, href)
        if url_abs in vistos:
            continue
        vistos.add(url_abs)
        titulo = (a.get_text(" ", strip=True)
                  or (img.get("alt") or "").strip()
                  or os.path.basename(urlparse(url_abs).path).replace("-", " "))
        capa = urljoin(url_pagina, (img.get("src") or "").strip())
        if "no-cover" in capa:
            capa = ""
        titulo = " ".join(titulo.split())
        if titulo:
            jogos.append({"titulo": titulo[:200], "url": url_abs, "capa": capa})
    return jogos


def carregar_catalogo(url_base: str, max_paginas: int = 5, timeout: int = 20,
                      callback_progress=None, callback_log=None,
                      controle: ControleDownload | None = None) -> list[dict]:
    """Percorre as páginas e devolve o catálogo (sem repetir jogos).

    Para quando a página vem vazia/repetida ou atinge `max_paginas`.
    `max_paginas<=0` = sem limite (o site tem ~60 páginas p/ PSP).
    """
    catalogo: list[dict] = []
    urls_vistas: set[str] = set()
    pagina = 1
    while True:
        if controle is not None:
            controle.esperar_se_pausado(callback_log)
        if max_paginas > 0 and pagina > max_paginas:
            break
        url = url_pagina_catalogo(url_base, pagina)
        if callback_log:
            callback_log(f"Lendo página {pagina}: {url}")
        jogos = listar_jogos_pagina(url, timeout=timeout)
        novos = [j for j in jogos if j["url"] not in urls_vistas]
        if not jogos or not novos:  # fim do catálogo (ou site mudou o layout)
            break
        for j in novos:
            urls_vistas.add(j["url"])
        catalogo.extend(novos)
        if callback_progress:
            callback_progress(len(catalogo), None)
        pagina += 1
    return catalogo


def detalhes_jogo(url_detalhe: str, timeout: int = 20) -> dict:
    """Busca região, tamanho, nota e nº de votos na página do jogo (best-effort).

    Campos ausentes vêm como "". Levanta RequestException em falha de rede.
    """
    r = requests.get(url_detalhe, headers=HEADERS_PADRAO, timeout=timeout,
                     allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    texto = soup.get_text(" ", strip=True)

    titulo = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        titulo = og["content"].split("|")[0].strip()
    if not titulo and soup.find("h1"):
        titulo = soup.find("h1").get_text(" ", strip=True)
    titulo = re.sub(r"\s*-\s*Playstation Portable.*$", "", titulo, flags=re.I).strip()
    titulo = re.sub(r"\s+ROM\s*$", "", titulo, flags=re.I).strip()

    regiao = ""
    texto_norm = normalizar(texto)
    for reg in REGIOES_CONHECIDAS:
        if reg in texto_norm:
            m = re.search(rf"([A-Za-z ]*\({reg}[^)]*\)|{reg}\s*\([A-Za-z ]*\))",
                          texto, re.IGNORECASE)
            regiao = m.group(1).strip() if m else reg.title()
            break

    tamanho = ""
    m = re.search(r"(\d+(?:[.,]\d+)?\s*(?:GB|MB|KB))", texto)
    if m:
        tamanho = m.group(1)

    nota, votos = "", ""
    m = re.search(r"(\d\.\d{1,2})\s*\|\s*([\d,\.]+)", texto)
    if m:
        nota, votos = m.group(1), m.group(2)

    capa = ""
    ogimg = soup.find("meta", attrs={"property": "og:image"})
    if ogimg and ogimg.get("content"):
        capa = ogimg["content"]
    if not capa:
        img = soup.find("img", alt=re.compile(re.escape(titulo[:20]), re.I)) if titulo else None
        if img and img.get("src"):
            capa = urljoin(r.url, img["src"])
    return {"titulo": titulo, "url": r.url, "regiao": regiao, "tamanho": tamanho,
            "nota": nota, "votos": votos, "capa": capa}


def filtrar_catalogo(catalogo: list[dict], busca: str = "") -> list[dict]:
    """Busca tolerante (sem acento/case) no título. Vazia = tudo."""
    termo = normalizar(busca or "")
    if not termo:
        return list(catalogo)
    return [j for j in catalogo if termo_casa(termo, normalizar(j.get("titulo", "")))]


def escanear_baixados(pasta: str | Path) -> list[dict]:
    """Lista o que está na pasta: {arquivo, caminho, bytes, modificado_em, incompleto}.

    `.part` = download incompleto (dá p/ continuar). Manifesto é ignorado.
    Ordena do mais recente para o mais antigo.
    """
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    itens: list[dict] = []
    for arq in pasta.iterdir():
        if not arq.is_file() or arq.name in (NOME_MANIFESTO, NOME_CACHE_CATALOGO):
            continue
        try:
            st = arq.stat()
        except OSError:
            continue
        incompleto = arq.suffix == SUFFIX_PART
        itens.append({
            "arquivo": arq.name,
            "caminho": str(arq),
            "bytes": st.st_size,
            "modificado_em": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
            "incompleto": incompleto,
        })
    itens.sort(key=lambda i: (i["incompleto"], i["arquivo"]))
    return itens


def _titulo_casa_arquivo(titulo_norm: str, stem_norm: str) -> bool:
    """Diz se um arquivo da pasta é (provavelmente) o jogo do catálogo."""
    if not titulo_norm or not stem_norm:
        return False
    if titulo_norm == stem_norm or titulo_norm in stem_norm or stem_norm in titulo_norm:
        return True
    curto, longo = sorted((titulo_norm, stem_norm), key=len)
    return len(curto.split()) > 1 and all(p in longo for p in curto.split())


def anotar_catalogo(catalogo: list[dict], pasta: str | Path) -> list[dict]:
    """Marca cada jogo com `ja_baixado` + `arquivo_local` (cruza com a pasta).

    Retorna o próprio catálogo (modificado in-place) para encadear.
    """
    pasta = Path(pasta)
    arquivos = escanear_baixados(pasta)
    finais = [a for a in arquivos if not a["incompleto"]]
    stems = [(normalizar(Path(a["arquivo"]).stem), a["arquivo"]) for a in finais]
    for jogo in catalogo:
        titulo_norm = normalizar(jogo.get("titulo", ""))
        achado = next((arq for stem, arq in stems
                       if _titulo_casa_arquivo(titulo_norm, stem)), "")
        jogo["ja_baixado"] = bool(achado)
        jogo["arquivo_local"] = achado
    return catalogo


def salvar_catalogo_cache(catalogo: list[dict], pasta_cache: str | Path,
                          url_base: str = "") -> Path:
    """Salva o catálogo em JSON p/ não recarregar o site toda vez."""
    pasta_cache = Path(pasta_cache)
    pasta_cache.mkdir(parents=True, exist_ok=True)
    dest = pasta_cache / NOME_CACHE_CATALOGO
    dest.write_text(json.dumps({
        "url_base": url_base,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "total": len(catalogo),
        "jogos": catalogo,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def carregar_catalogo_cache(pasta_cache: str | Path) -> dict:
    """Lê o cache. Ausente/corrompido -> {"jogos": [], ...} vazio."""
    caminho = Path(pasta_cache) / NOME_CACHE_CATALOGO
    if not caminho.exists():
        return {"jogos": [], "atualizado_em": "", "url_base": ""}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"jogos": [], "atualizado_em": "", "url_base": ""}
    if not isinstance(dados, dict) or not isinstance(dados.get("jogos"), list):
        return {"jogos": [], "atualizado_em": "", "url_base": ""}
    return dados


def baixar_capa(url_capa: str, pasta_cache: str | Path, timeout: int = 15) -> Path | None:
    """Baixa a capa do jogo p/ cache local (`capas/`). Retorna o Path ou None.

    Nunca levanta: falha de rede/capa ausente -> None (a interface mostra
    um quadrado vazio no lugar). Arquivo é reutilizado se já existir.
    """
    if not (url_capa or "").strip():
        return None
    try:
        pasta = Path(pasta_cache) / PASTA_CAPAS
        pasta.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(urlparse(url_capa).path)[1].lower() or ".jpg"
        if len(ext) > 5 or not re.fullmatch(r"\.[a-z0-9]+", ext):
            ext = ".jpg"
        import hashlib
        nome = hashlib.md5(url_capa.encode("utf-8")).hexdigest() + ext
        dest = pasta / nome
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        r = requests.get(url_capa, headers={"User-Agent": HEADERS_PADRAO["User-Agent"]},
                         timeout=timeout)
        r.raise_for_status()
        if "image" not in r.headers.get("Content-Type", ""):
            return None
        dest.write_bytes(r.content)
        return dest if dest.stat().st_size > 0 else None
    except Exception:
        return None
