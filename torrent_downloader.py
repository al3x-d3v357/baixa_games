"""Suporte a BitTorrent: parse de .torrent + download via libtorrent.

Sem dependencias novas para INSPECIONAR o .torrent (bencode puro).
Para BAIXAR de verdade usa `libtorrent` (pip install libtorrent);
se ele nao estiver instalado, o app mostra a info + magnet e oferece
abrir no cliente externo (qBittorrent/Transmission/uTorrent).

Uso:
    from torrent_downloader import parse_torrent, download_torrent, is_magnet
    info = parse_torrent("jogo.torrent")
    download_torrent("jogo.torrent", "downloads",
                     callback_progress=lambda rec, tot: ...,
                     controle=ControleDownload())
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from downloader import ControleDownload, DownloadCancelado
except Exception:  # pragma: no cover - import circular improvavel
    ControleDownload = None  # type: ignore
    DownloadCancelado = Exception  # type: ignore


# ---------------------------------------------------------------------------
# bencode minimo (puro-python, sem deps)
# ---------------------------------------------------------------------------

def _bdecode(data: bytes) -> tuple[object, int]:
    """Decodifica um valor bencode a partir de data. Retorna (valor, prox_indice)."""
    if not data:
        raise ValueError("Torrent vazio ou corrompido.")
    c = data[0:1]
    if c == b"i":
        fim = data.index(b"e", 1)
        return int(data[1:fim]), fim + 1
    if c == b"l":
        lst: list = []
        i = 1
        while data[i:i + 1] != b"e":
            v, ni = _bdecode(data[i:])
            lst.append(v)
            i += ni
        return lst, i + 1
    if c == b"d":
        d: dict = {}
        i = 1
        while data[i:i + 1] != b"e":
            k, ni = _bdecode(data[i:])
            i += ni
            v, ni = _bdecode(data[i:])
            i += ni
            d[k] = v
        return d, i + 1
    if c.isdigit():
        sep = data.index(b":", 0)
        tam = int(data[:sep])
        ini = sep + 1
        return data[ini:ini + tam], ini + tam
    raise ValueError(f"Byte bencode invalido: {c!r}")


def bdecode(data: bytes) -> object:
    val, _ = _bdecode(data)
    return val


def _bencode(val: object) -> bytes:
    if isinstance(val, int):
        return b"i" + str(val).encode() + b"e"
    if isinstance(val, bytes):
        return str(len(val)).encode() + b":" + val
    if isinstance(val, str):
        b = val.encode("utf-8")
        return str(len(b)).encode() + b":" + b
    if isinstance(val, list):
        return b"l" + b"".join(_bencode(i) for i in val) + b"e"
    if isinstance(val, dict):
        items = sorted(val.items(), key=lambda kv: kv[0])
        out = b"d"
        for k, v in items:
            out += _bencode(k) + _bencode(v)
        return out + b"e"
    raise TypeError(f"Tipo nao suportado p/ bencode: {type(val)}")


def _txt(v: object) -> str:
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.decode("utf-8", errors="replace")
    return str(v or "")


# ---------------------------------------------------------------------------
# Parse / magnet
# ---------------------------------------------------------------------------

def is_magnet(fonte: str) -> bool:
    return (fonte or "").strip().lower().startswith("magnet:")


def is_torrent_url(fonte: str) -> bool:
    try:
        p = urlparse((fonte or "").strip())
    except Exception:
        return False
    return p.scheme in ("http", "https") and p.path.lower().endswith(".torrent")


def parse_torrent_bytes(dados: bytes) -> dict:
    root = bdecode(dados)
    if not isinstance(root, dict) or b"info" not in root:
        raise ValueError("Arquivo .torrent invalido (sem dicionario 'info').")
    info = root[b"info"]
    if not isinstance(info, dict):
        raise ValueError("Arquivo .torrent invalido (info corrompido).")
    info_hash = hashlib.sha1(_bencode(info)).hexdigest()

    nome = _txt(info.get(b"name", b"torrent"))
    piece_len = int(info.get(b"piece length", 0) or 0)
    arquivos: list[dict] = []
    total = 0
    if b"files" in info and isinstance(info[b"files"], list):
        for f in info[b"files"]:
            if not isinstance(f, dict):
                continue
            partes = [ _txt(p) for p in (f.get(b"path", []) or []) ]
            rel = "/".join(p for p in partes if p) or "arquivo"
            tam = int(f.get(b"length", 0) or 0)
            total += tam
            arquivos.append({"caminho": rel, "bytes": tam})
    else:
        total = int(info.get(b"length", 0) or 0)
        arquivos.append({"caminho": nome, "bytes": total})

    trackers: list[str] = []
    ann = _txt(root.get(b"announce", b""))
    if ann:
        trackers.append(ann)
    al = root.get(b"announce-list", [])
    if isinstance(al, list):
        for tier in al:
            if isinstance(tier, list):
                for t in tier:
                    s = _txt(t)
                    if s and s not in trackers:
                        trackers.append(s)

    magnet = build_magnet(info_hash, nome, trackers)
    return {
        "nome": nome[:200] or "torrent",
        "tamanho": total,
        "arquivos": arquivos,
        "num_arquivos": len(arquivos),
        "announce": ann,
        "trackers": trackers,
        "info_hash": info_hash,
        "magnet": magnet,
        "piece_length": piece_len,
        "comment": _txt(root.get(b"comment", b"")),
        "created_by": _txt(root.get(b"created by", b"")),
    }


def parse_torrent(fonte: str | Path) -> dict:
    """Le um .torrent do disco e devolve o dicionario de info."""
    p = Path(str(fonte))
    if not p.exists():
        raise FileNotFoundError(f"Arquivo .torrent nao encontrado: {p}")
    return parse_torrent_bytes(p.read_bytes())


def build_magnet(info_hash: str, nome: str = "", trackers: list[str] | None = None) -> str:
    from urllib.parse import quote
    mag = f"magnet:?xt=urn:btih:{info_hash}"
    if nome:
        mag += f"&dn={quote(nome)}"
    for t in (trackers or [])[:10]:
        mag += f"&tr={quote(t, safe='')}"
    return mag


# ---------------------------------------------------------------------------
# Motor de download (libtorrent) + fallback externo
# ---------------------------------------------------------------------------

def libtorrent_disponivel() -> bool:
    try:
        import libtorrent  # noqa: F401
        return True
    except Exception:
        return False


def _baixar_arquivo_torrent(url: str, destino_tmp: Path, timeout: int = 60) -> Path:
    import requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    destino_tmp.parent.mkdir(parents=True, exist_ok=True)
    destino_tmp.write_bytes(r.content)
    # valida que eh torrent mesmo
    parse_torrent_bytes(r.content)
    return destino_tmp


def abrir_com_cliente_externo(fonte: str) -> str:
    """Abre .torrent/magnet no cliente padrao do SO. Retorna mensagem p/ UI."""
    f = (fonte or "").strip()
    if not f:
        raise ValueError("Nenhum .torrent ou magnet informado.")
    if sys.platform.startswith("win"):
        os.startfile(f)  # noqa: S606
        return "Aberto no cliente torrent padrao do Windows."
    if sys.platform == "darwin":
        subprocess.Popen(["open", f])
        return "Aberto no cliente torrent padrao do macOS."
    for cmd in (["xdg-open", f], ["qbittorrent", f], ["transmission-gtk", f]):
        try:
            subprocess.Popen(cmd)
            return f"Aberto via: {' '.join(cmd)}"
        except OSError:
            continue
    raise RuntimeError("Nenhum cliente torrent encontrado. Instale o qBittorrent.")


def download_torrent(
    fonte: str,
    pasta: str | Path,
    callback_progress=None,
    callback_log=None,
    controle=None,
    timeout_metadata: int = 180,
    sequencial: bool = False,
) -> Path:
    """Baixa um .torrent / magnet / URL-de-.torrent com libtorrent.

    - `fonte`: caminho .torrent, magnet:, ou http(s) p/ .torrent.
    - `pasta`: onde salvar o conteudo.
    - `controle`: ControleDownload (pausar/continuar/cancelar).
    - Retorna o Path final (arquivo ou pasta do torrent).
    """
    try:
        import libtorrent as lt
    except Exception as e:
        raise RuntimeError(
            "libtorrent nao instalado. Rode: pip install libtorrent  "
            "ou use 'Abrir no cliente externo'. "
            f"({e})"
        )

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    f = (fonte or "").strip()
    if not f:
        raise ValueError("Informe o .torrent, magnet ou URL.")

    # URL http(s) -> baixa o .torrent primeiro
    tmp_torrent: Path | None = None
    if is_torrent_url(f):
        tmp_torrent = pasta / "_tmp_download.torrent"
        if callback_log:
            callback_log(f"Baixando .torrent de: {f}")
        _baixar_arquivo_torrent(f, tmp_torrent)
        f = str(tmp_torrent)

    ses = lt.session({"listen_interfaces": "0.0.0.0:6881",
                      "enable_dht": True, "enable_lsd": True,
                      "enable_upnp": True, "enable_natpmp": True})
    try:
        ses.set_download_rate_limit(0)
        params: dict = {"save_path": str(pasta)}
        eh_mag = is_magnet(f)
        handle = None
        if eh_mag:
            params["url"] = f
            handle = lt.add_magnet_uri(ses, f, params)
            if callback_log:
                callback_log("Magnet adicionado. Buscando metadados (peers/DHT)...")
            for _ in range(timeout_metadata * 2):
                if controle is not None and getattr(controle, "foi_cancelado", False):
                    raise DownloadCancelado()
                if handle.has_metadata():
                    break
                time.sleep(0.5)
            if not handle.has_metadata():
                raise RuntimeError(
                    "Sem metadados apos %ds. Sem seeders ou DHT bloqueado." % timeout_metadata)
        else:
            pf = Path(f)
            if not pf.exists():
                raise FileNotFoundError(f"Arquivo .torrent nao encontrado: {pf}")
            ti = lt.torrent_info(str(pf))
            params["ti"] = ti
            handle = ses.add_torrent(params)

        if sequencial:
            try:
                handle.set_sequential_download(True)
            except Exception:
                pass

        # resume automatico do libtorrent: continua o que ja existe na pasta
        nome = handle.name() if handle.has_metadata() else Path(f).stem
        if callback_log:
            callback_log(f"Torrent: {nome}")

        if controle is not None and getattr(controle, "pausado", False):
            try:
                handle.pause()
            except Exception:
                pass

        ultimo_emit = 0.0
        while True:
            if controle is not None:
                if getattr(controle, "foi_cancelado", False):
                    try:
                        ses.pause()
                    except Exception:
                        pass
                    raise DownloadCancelado()
                try:
                    if getattr(controle, "pausado", False):
                        try:
                            handle.pause()
                        except Exception:
                            pass
                        if callback_log and (time.time() - ultimo_emit > 2):
                            callback_log("Torrent pausado — aguardando continuar...")
                            ultimo_emit = time.time()
                        time.sleep(0.4)
                        continue
                    else:
                        try:
                            if handle.is_paused():
                                handle.resume()
                        except Exception:
                            pass
                except DownloadCancelado:
                    raise

            st = handle.status()
            total = int(getattr(st, "total_wanted", 0) or 0)
            feito = int(getattr(st, "total_wanted_done", 0) or 0)
            if callback_progress and (time.time() - ultimo_emit >= 0.3 or st.is_seeding):
                ultimo_emit = time.time()
                try:
                    callback_progress(feito, total)
                except Exception:
                    pass
            if callback_log and getattr(st, "state", None) is not None:
                pass  # estado detalhado vai via callback_progress na GUI
            if st.is_seeding:
                break
            time.sleep(0.5)

        dest = pasta / (handle.name() or nome)
        if callback_log:
            callback_log(f"Torrent concluido: {dest}")
        return dest
    finally:
        try:
            ses.pause()
        except Exception:
            pass
        if tmp_torrent is not None and tmp_torrent.exists():
            try:
                tmp_torrent.unlink()
            except OSError:
                pass


def status_torrent_para_texto(state_int: int) -> str:
    return {
        0: "na fila", 1: "checando", 2: "baixando metadados",
        3: "baixando", 4: "finalizando", 5: "semeando",
        6: "alocando", 7: "checando resume",
    }.get(int(state_int), "baixando")
