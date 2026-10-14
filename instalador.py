"""Analise de seguranca + instalacao de jogos (repacks Inno Setup, ex: FitGirl).

Analise (nada eh executado, so leitura):
- hashes SHA-256/MD5, tamanho, assinatura Authenticode (quase todo repack
  eh NotSigned — normal, nao eh veredito sozinho);
- Microsoft Defender de verdade via MpCmdRun (-Scan -ScanType 3);
- estrutura PE via `pefile` (opcional): secoes com entropia alta (packer),
  imports tipicos de injecao (CreateRemoteThread, WriteProcessMemory...).

Instalacao:
- instala Inno Setup em silencioso (/VERYSILENT /DIR=... /NORESTART) ou
  interativo, no diretorio que o usuario escolher;
- dependencias: detecta VC++ 2015-2022 (x64/x86), DirectX e .NET Desktop
  no registro e oferece instalar o que faltar (URLs oficiais Microsoft
  verificadas + winget como alternativa).
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

MPCMDRUN = Path(r"C:\Program Files\Windows Defender\MpCmdRun.exe")
MPCMDRUN_X86 = Path(r"C:\Program Files (x86)\Windows Defender\MpCmdRun.exe")

IMPORTS_SUSPEITOS = frozenset({
    "createremotethread", "createremotethreadex", "writeprocessmemory",
    "readprocessmemory", "virtualallocex", "rtlcreateuserthread",
    "setwindowshookex", "setsystemhook", "ntunmapviewofsection",
    "zwunmapviewofsection", "virtualprotectex", "queueuserapc",
    "ntqueueapcthread", "createdevice", "deviceiocontrol",
    "samconnect", "lsalookup", "cryptencrypt", "httpopenrequest",
    "urldownloadtofile", "winexec", "shellexecute",
})

SECOES_PADRAO = frozenset({
    ".text", ".itext", ".data", ".rdata", ".idata", ".edata", ".reloc", ".rsrc",
    ".tls", ".pdata", ".xdata", ".bss", ".crt", ".gfids", ".00cfg", ".didat",
})


# ---------------------------------------------------------------------------
# Hashes + assinatura
# ---------------------------------------------------------------------------

def hashes_arquivo(caminho: str | Path, callback_log=None) -> dict:
    """SHA-256 + MD5 + tamanho (leitura em blocos, sem carregar tudo na RAM)."""
    p = Path(caminho)
    h256, hmd5, total = hashlib.sha256(), hashlib.md5(), 0
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h256.update(bloco)
            hmd5.update(bloco)
            total += len(bloco)
            if callback_log and total % (64 * 1024 * 1024) < 1024 * 1024:
                callback_log(f"Calculando hash... {total / 1024 / 1024:.0f} MB")
    return {"sha256": h256.hexdigest(), "md5": hmd5.hexdigest(), "bytes": total}


def verificar_assinatura(caminho: str | Path, timeout: int = 60) -> dict:
    """Status Authenticode via PowerShell. Repack Normal = NotSigned."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-AuthenticodeSignature -LiteralPath '{caminho}').Status"],
            capture_output=True, text=True, timeout=timeout)
        status = (r.stdout or "").strip() or "Desconhecido"
    except Exception as e:
        status = f"nao verificado ({e})"
    return {"status": status, "assinado": status.lower() == "valid"}


# ---------------------------------------------------------------------------
# Microsoft Defender (scan real, somente leitura)
# ---------------------------------------------------------------------------

def _mpcmdrun() -> Path | None:
    for cand in (MPCMDRUN, MPCMDRUN_X86):
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return shutil.which("MpCmdRun.exe")


def escanear_defender(caminho: str | Path, timeout: int = 900,
                      callback_log=None) -> dict:
    """Roda o Defender no arquivo. Retorna {limpo, saida, codigo}.

    Codigo 0 = sem ameaca; 2 = ameaca encontrada. Nunca executa o arquivo.
    """
    exe = _mpcmdrun()
    if exe is None:
        return {"limpo": None, "codigo": -1,
                "saida": "Microsoft Defender nao encontrado neste PC."}
    if callback_log:
        callback_log("Escaneando com o Microsoft Defender (pode levar minutos)...")
    try:
        r = subprocess.run(
            [str(exe), "-Scan", "-ScanType", "3", "-File", str(caminho),
             "-DisableRemediation"],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"limpo": None, "codigo": -2, "saida": "Tempo esgotado no scan."}
    except Exception as e:
        return {"limpo": None, "codigo": -3, "saida": f"Falha ao escanear: {e}"}
    saida = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    # MpCmdRun: 0 = sem ameaca, 2 = ameaca encontrada.
    limpo = True if r.returncode == 0 else (False if r.returncode == 2 else None)
    return {"limpo": limpo, "codigo": r.returncode, "saida": saida[-2000:]}


# ---------------------------------------------------------------------------
# Estrutura PE (pefile, opcional)
# ---------------------------------------------------------------------------

def _entropia(dados: bytes) -> float:
    if not dados:
        return 0.0
    freq = [0] * 256
    for b in dados:
        freq[b] += 1
    n = len(dados)
    return -sum((c / n) * math.log2(c / n) for c in freq if c)


def info_pe(caminho: str | Path) -> dict:
    """Secoes/entropia/imports. Vazio {} se pefile ausente ou nao-PE."""
    try:
        import pefile
    except Exception:
        return {"indisponivel": "pip install pefile"}
    try:
        pe = pefile.PE(str(caminho), fast_load=False)
    except Exception:
        return {"indisponivel": "nao eh um executavel PE valido"}
    secoes = []
    for s in pe.sections:
        try:
            nome = s.Name.decode("utf-8", errors="replace").rstrip("\x00").lower()
        except Exception:
            nome = "?"
        ent = _entropia(s.get_data()[:2_000_000])
        secoes.append({"nome": nome, "entropia": round(ent, 2),
                       "tamanho": s.SizeOfRawData,
                       "suspeita": ent > 7.2 or (nome not in SECOES_PADRAO and nome not in ("", "?"))})
    achados: set[str] = set()
    try:
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
            for imp in entry.imports or []:
                nome = (imp.name.decode("utf-8", errors="ignore").lower()
                        if getattr(imp, "name", None) else "")
                if nome in IMPORTS_SUSPEITOS:
                    achados.add(nome)
    except Exception:
        pass
    try:
        mach = hex(pe.FILE_HEADER.Machine)
    except Exception:
        mach = "?"
    return {"arquitetura": mach, "secoes": secoes,
            "empacotado_provavel": any(s["suspeita"] and s["entropia"] > 7.2 for s in secoes),
            "imports_suspeitos": sorted(achados)}


# ---------------------------------------------------------------------------
# Analise completa
# ---------------------------------------------------------------------------

def analisar_setup(caminho: str | Path, com_defender: bool = True,
                   callback_log=None) -> dict:
    """Junta tudo e da o veredito: ok | atencao | ameaca | inconclusivo."""
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"Executavel nao encontrado: {p}")
    if callback_log:
        callback_log(f"Analisando {p.name}...")
    rep = {"arquivo": p.name, "caminho": str(p)}
    rep.update(hashes_arquivo(p, callback_log))
    rep["assinatura"] = verificar_assinatura(p)
    rep["pe"] = info_pe(p)
    alertas: list[str] = []
    if not rep["assinatura"]["assinado"]:
        alertas.append(f"Sem assinatura digital ({rep['assinatura']['status']}) — comum em repacks; o scan do Defender vale mais.")
    pe = rep["pe"]
    if pe.get("empacotado_provavel"):
        alertas.append("Secoes com entropia alta (possivel packer/ofuscacao).")
    if pe.get("imports_suspeitos"):
        alertas.append("Imports sensiveis: " + ", ".join(pe["imports_suspeitos"]))
    if com_defender:
        rep["defender"] = escanear_defender(p, callback_log=callback_log)
        d = rep["defender"]
        if d["limpo"] is False:
            return {**rep, "veredito": "ameaca",
                    "mensagem": "⛔ DEFENDER ENCONTROU AMEACA — nao instale.", "alertas": alertas}
        if d["limpo"] is None:
            alertas.append("Scan do Defender inconclusivo: " + d["saida"][:200])
        else:
            rep["def_verde"] = True
    if rep.get("def_verde") and not alertas:
        veredito, msg = "ok", "✅ Limpo no Defender, sem indicadores suspeitos."
    elif rep.get("def_verde"):
        veredito, msg = "atencao", "⚠️ Limpo no Defender, mas com pontos de atencao (veja abaixo)."
    else:
        veredito, msg = "inconclusivo", "❓ Sem confirmacao do Defender — revise os alertas."
    return {**rep, "veredito": veredito, "mensagem": msg, "alertas": alertas}


def texto_relatorio(rep: dict) -> str:
    """Relatorio legivel p/ a caixa de texto da interface."""
    gb = lambda n: f"{n / 1024 / 1024:.1f} MB" if n < 1024**3 else f"{n / 1024**3:.2f} GB"
    L = [f"Arquivo: {rep.get('arquivo', '?')}",
         f"Tamanho: {gb(rep.get('bytes', 0))}",
         f"SHA-256: {rep.get('sha256', '?')}",
         f"MD5: {rep.get('md5', '?')}",
         f"Assinatura: {(rep.get('assinatura') or {}).get('status', '?')}", ""]
    d = rep.get("defender")
    if d:
        estado = "LIMPO ✅" if d["limpo"] else ("AMEACA ⛔" if d["limpo"] is False else "INCONCLUSIVO ❓")
        L += [f"Microsoft Defender: {estado} (codigo {d.get('codigo')})"]
        if d.get("saida"):
            L += [d["saida"][:600], ""]
    pe = rep.get("pe", {})
    if pe.get("arquitetura"):
        L.append(f"PE: {pe['arquitetura']} | packer provavel: {'sim' if pe.get('empacotado_provavel') else 'nao'}")
        for s in pe.get("secoes", [])[:12]:
            L.append(f"  secao {s['nome'] or '?'}: entropia {s['entropia']}" + (" ⚠️" if s["suspeita"] else ""))
        if pe.get("imports_suspeitos"):
            L.append("Imports sensiveis: " + ", ".join(pe["imports_suspeitos"]))
        L.append("")
    if rep.get("alertas"):
        L.append("Pontos de atencao:")
        L += [f"  - {a}" for a in rep["alertas"]]
        L.append("")
    L.append("VEREDITO: " + rep.get("mensagem", "?"))
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Dependencias (deteccao via registro + instalacao oficial)
# ---------------------------------------------------------------------------

def _reg_flag(chave: str, valor: str = "Installed") -> tuple[bool, str]:
    """Le HKLM (e Wow6432Node). Retorna (instalado, detalhe)."""
    import winreg
    for base in (winreg.HKEY_LOCAL_MACHINE,):
        prefixo = "SOFTWARE\\"
        alts = [chave]
        if chave.startswith(prefixo):
            alts.append("SOFTWARE\\Wow6432Node\\" + chave[len(prefixo):])
        for sub in alts:
            try:
                with winreg.OpenKey(base, sub) as k:
                    v, _ = winreg.QueryValueEx(k, valor)
                    try:
                        ver, _ = winreg.QueryValueEx(k, "Version")
                    except OSError:
                        ver = v
                    if v:
                        return True, str(ver)
            except OSError:
                continue
    return False, ""


DEPENDENCIAS = [
    {"id": "vcx64", "nome": "Visual C++ 2015-2022 (x64)",
     "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
     "args": ["/install", "/quiet", "/norestart"]},
    {"id": "vcx86", "nome": "Visual C++ 2015-2022 (x86)",
     "url": "https://aka.ms/vs/17/release/vc_redist.x86.exe",
     "args": ["/install", "/quiet", "/norestart"]},
    {"id": "dotnet8", "nome": ".NET 8 Desktop Runtime (x64)",
     "winget": "Microsoft.DotNet.DesktopRuntime.8", "args": []},
    {"id": "directx", "nome": "DirectX End-User Runtime",
     "winget": "Microsoft.DirectX", "args": []},
]


def detectar_dependencias() -> list[dict]:
    """Checa o que esta instalado. Cada item: {id, nome, instalado, detalhe, ...}."""
    import winreg
    out = []
    for dep in DEPENDENCIAS:
        d = dict(dep)
        if d["id"] == "vcx64":
            ok, ver = _reg_flag(r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64")
            # Rekord Wow6432Node nao serve p/ x64; checa nativo:
            if not ok:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64") as k:
                        v, _ = winreg.QueryValueEx(k, "Installed")
                        ok = bool(v)
                        try:
                            ver, _ = winreg.QueryValueEx(k, "Version")
                        except OSError:
                            pass
                except OSError:
                    pass
            d.update(instalado=ok, detalhe=f"versao {ver}" if ok and ver else "")
        elif d["id"] == "vcx86":
            ok, ver = _reg_flag(r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86")
            d.update(instalado=ok, detalhe=f"versao {ver}" if ok and ver else "")
        elif d["id"] == "dotnet8":
            ok, det = False, ""
            try:
                r = subprocess.run(["dotnet", "--list-runtimes"], capture_output=True,
                                   text=True, timeout=30)
                for linha in (r.stdout or "").splitlines():
                    if "Microsoft.WindowsDesktop.App 8." in linha:
                        ok, det = True, linha.strip()
                        break
            except Exception:
                pass
            d.update(instalado=ok, detalhe=det)
        elif d["id"] == "directx":
            ok, det = False, ""
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\DirectX") as k:
                    ver, _ = winreg.QueryValueEx(k, "Version")
                    ok, det = True, f"versao {ver}"
            except OSError:
                pass
            if not ok and Path(r"C:\Windows\System32\d3dx9_43.dll").exists():
                ok, det = True, "d3dx9 presente"
            d.update(instalado=ok, detalhe=det)
        out.append(d)
    return out


def _baixar(url: str, destino: Path, callback_log=None, timeout: int = 300) -> Path:
    import requests
    if callback_log:
        callback_log(f"Baixando {Path(url).name or 'instalador'}...")
    with requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                      stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0) or 0)
        feito = 0
        with open(destino, "wb") as f:
            for bloco in r.iter_content(chunk_size=1024 * 256):
                if not bloco:
                    continue
                f.write(bloco)
                feito += len(bloco)
                if callback_log and total and feito % (8 * 1024 * 1024) < 256 * 1024:
                    callback_log(f"  {feito / 1024 / 1024:.0f}/{total / 1024 / 1024:.0f} MB")
    return destino


def instalar_dependencia(dep: dict, callback_log=None, timeout: int = 900) -> int:
    """Baixa (URL oficial) ou via winget e instala silencioso. Retorna exit code."""
    if dep.get("url"):
        tmp = Path(tempfile.gettempdir()) / f"dep_{dep['id']}.exe"
        _baixar(dep["url"], tmp, callback_log)
        cmd = [str(tmp), *dep.get("args", [])]
    elif dep.get("winget"):
        if not shutil.which("winget"):
            raise RuntimeError("winget nao encontrado neste PC.")
        cmd = ["winget", "install", "-e", "--id", dep["winget"], "--silent",
               "--accept-package-agreements", "--accept-source-agreements"]
    else:
        raise RuntimeError("Dependencia sem metodo de instalacao.")
    if callback_log:
        callback_log(f"Instalando {dep['nome']} (silencioso, pode levar minutos)...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if callback_log:
        tail = ((r.stdout or "") + (r.stderr or ""))[-500:]
        callback_log(f"Concluido (codigo {r.returncode}). {tail}")
    if r.returncode not in (0, 3010):  # 3010 = ok, pede reboot
        raise RuntimeError(f"Falha ao instalar {dep['nome']} (codigo {r.returncode}).")
    return r.returncode


# ---------------------------------------------------------------------------
# Instalacao do jogo (Inno Setup)
# ---------------------------------------------------------------------------

def instalar_jogo(setup: str | Path, destino: str | Path, silencioso: bool = True,
                  callback_log=None, timeout: int = 7200) -> dict:
    """Roda o setup.exe da FitGirl no diretorio escolhido.

    Inno Setup: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="...".
    Retorna {codigo, destino, desinstalador}.
    """
    setup, destino = Path(setup), Path(destino)
    if not setup.exists():
        raise FileNotFoundError(f"setup.exe nao encontrado: {setup}")
    destino.mkdir(parents=True, exist_ok=True)
    if silencioso:
        cmd = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
               f'/DIR={destino}']
    else:
        cmd = [str(setup), "/NORESTART", f'/DIR={destino}']
    if callback_log:
        callback_log(f"Instalando em {destino} ({'silencioso' if silencioso else 'interativo'})...")
        callback_log("Repaks FitGirl levam de 10 min a 1h+ (descompactacao pesada). Nao feche.")
    ini = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    ultima = time.time()
    assert proc.stdout is not None
    for linha in proc.stdout:
        if callback_log and (time.time() - ultima > 20):
            ultima = time.time()
            decorrido = int(time.time() - ini)
            callback_log(f"  instalando... {decorrido // 60}min (o setup ainda esta rodando)")
    codigo = proc.wait(timeout=timeout)
    if codigo not in (0,):
        raise RuntimeError(f"Setup terminou com codigo {codigo}.")
    unins = destino / "unins000.exe"
    return {"codigo": codigo, "destino": str(destino),
            "desinstalador": str(unins) if unins.exists() else ""}


def criar_atalho(executavel: str | Path, nome: str = "") -> Path:
    """Cria atalho na Area de Trabalho via WScript.Shell. Retorna o .lnk."""
    exe = Path(executavel)
    nome = nome or exe.stem
    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
    lnk = desktop / f"{nome}.lnk"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{exe}';$s.WorkingDirectory='{exe.parent}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=60)
    return lnk


def localizar_setups(pastas: list[str | Path] | None = None) -> list[Path]:
    """Procura setup*.exe nas pastas de download. Retorna os encontrados."""
    bases = [Path(p) for p in (pastas or ["downloads", "dist/downloads"])]
    achados: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        achados += sorted(base.rglob("setup*.exe"))
        achados += sorted(base.rglob("Setup*.exe"))
    vistos, unicos = set(), []
    for a in achados:
        if a not in vistos and a.is_file():
            vistos.add(a)
            unicos.append(a)
    return unicos[:20]
