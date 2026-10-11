"""Catálogo PSP — 2207 jogos (customtkinter dark) + mini navegador + modo torrent.

Abas: 🗂 Catálogo (2207 jogos com capinhas) | 🌐 Navegador
(passeia pelo site aqui dentro: endereço, ◀ ▶ ⟳ 🏠, lista, jogo e links)
| 💾 Meus jogos.
Tudo roda dentro do programa, com internet para capas e downloads.
Clique em 👁 para abrir a telinha do jogo (capa grande, dados puxados
do site e botão de download) ou em ⬇ para mandar direto p/ a fila.
Os downloads funcionam igual torrent: fila com barra, velocidade,
tempo restante e pausar/continuar/cancelar por item.
Nada abre no navegador externo.
Requer: pip install -r requirements.txt  (customtkinter incluso)
"""
import hashlib
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk
from PIL import Image

from downloader import (
    ControleDownload,
    DownloadCancelado,
    DownloadJaExiste,
    anotar_catalogo,
    baixar_capa,
    baixar_inteligente,
    carregar_catalogo_cache,
    escanear_baixados,
    filtrar_catalogo,
    ja_baixado,
    navegar,
)
from ui_anim import (
    animar_spinner,
    fade_in_modal,
    hover_card,
    parar_pulso,
    pulsar_pill,
)

# Tema dark global
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

COR_FUNDO = "#0f1115"
COR_CARD = "#171a21"
COR_BORDA = "#262b36"
COR_TEXTO_FRACO = "#9aa3b2"
COR_VERDE = "#16a34a"
COR_VERDE_HOVER = "#15803d"
COR_AMBAR = "#d97706"
COR_VERMELHO = "#dc2626"
COR_AZUL = "#3b82f6"

FONTE_TITULO = ("Segoe UI", 16, "bold")
FONTE_SUB = ("Segoe UI", 11)
FONTE_NORMAL = ("Segoe UI", 12)
FONTE_MONO_PEQ = ("Consolas", 11)


def pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


PASTA_PADRAO = pasta_base() / "downloads"

SITE_INICIAL = "https://www.romsgames.net/roms/playstation-portable/"

CAT_POR_PAGINA = 100  # linhas por página (2207 de uma vez trava a UI)


def _dirs_base() -> list[Path]:
    """Locais onde o catálogo/capas podem estar: exe, script e _MEIPASS."""
    bases: list[Path] = [pasta_base()]
    try:
        aqui = Path(__file__).parent
        if aqui not in bases:
            bases.append(aqui)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass and Path(meipass) not in bases:
        bases.append(Path(meipass))
    return bases


def caminho_capa_local(url_capa: str) -> Path | None:
    """Devolve a capa salva em `capas/` sem usar a web (None se ausente).

    Usa o mesmo nome de arquivo do download de capas (md5 da URL + ext),
    procurando em todas as bases (pasta do exe, do script e _MEIPASS).
    """
    if not (url_capa or "").strip():
        return None
    ext = os.path.splitext(urlparse(url_capa).path)[1].lower() or ".jpg"
    if len(ext) > 5 or not re.fullmatch(r"\.[a-z0-9]+", ext):
        ext = ".jpg"
    nome = hashlib.md5(url_capa.encode("utf-8")).hexdigest() + ext
    for base in _dirs_base():
        cand = base / "capas" / nome
        try:
            if cand.exists() and cand.stat().st_size > 0:
                return cand
        except OSError:
            continue
    return None


def formatar_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def formatar_velocidade(bps: float) -> str:
    """Bytes/s -> '1,2 MB/s' (estilo torrent)."""
    if bps <= 0:
        return "—"
    if bps >= 1024 ** 2:
        return f"{bps / 1024 ** 2:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


def formatar_eta(segundos: float) -> str:
    """Segundos restantes -> '04:12' ou '—'."""
    if segundos is None or segundos < 0 or segundos == float("inf"):
        return "—"
    s = int(segundos)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def abrir_pasta(caminho: str):
    caminho = str(caminho)
    if sys.platform.startswith("win"):
        os.startfile(caminho)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho])


class Cartao(ctk.CTkFrame):
    """Frame-card padrão dark: fundo elevado + borda sutil.

    O título usa `pack` e o conteúdo vive em `corpo` (grid),
    evitando misturar gerenciadores de layout no mesmo contêiner.
    """

    def __init__(self, parent, titulo: str = "", **kwargs):
        super().__init__(parent, fg_color=COR_CARD, border_width=1,
                         border_color=COR_BORDA, corner_radius=12, **kwargs)
        if titulo:
            ctk.CTkLabel(self, text=titulo, font=("Segoe UI", 12, "bold"),
                         text_color="white").pack(anchor="w", padx=14, pady=(10, 2))
        self.corpo = ctk.CTkFrame(self, fg_color="transparent")
        self.corpo.pack(fill="x")  # sem expand: cartão mede só o conteúdo


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Catálogo PSP — 2207 jogos")
        self.geometry("1200x960")
        self.minsize(980, 880)
        self.configure(fg_color=COR_FUNDO)

        self.catalogo: list[dict] = []  # os 2207 jogos embutidos
        self.cat_checks: list[tuple[dict, ctk.BooleanVar]] = []  # página visível + marcado?
        self.cat_pagina = 0  # paginação do catálogo (100 por vez)
        self.nav_checks: list[tuple[dict, None]] = []  # linhas do navegador (p/ capas)
        self.meus_jogos: list[dict] = []
        self._thumbs: dict[str, ctk.CTkImage] = {}  # url capa -> imagem (evita GC)
        self._thumb_job = 0  # invalida loaders de capa de renderizações antigas
        self._fila_ui: queue.Queue = queue.Queue()  # workers pedem updates; principal executa
        self.fila_dl: list[dict] = []  # fila estilo torrent (compartilhada c/ worker)
        self._fila_lock = threading.Lock()
        self._seq_dl = 0
        self._worker_dl_rodando = False
        self.hist_voltar: list[str] = []  # mini navegador: voltar
        self.hist_avancar: list[str] = []  # mini navegador: avançar
        self.nav_atual: str | None = None  # página aberta no navegador
        self.nav_ocupado = False  # carregando página (trava ◀ ▶ Ir)
        self.var_resume = ctk.BooleanVar(value=True)
        self.var_pular = ctk.BooleanVar(value=True)

        self._montar_tela()
        self.after(120, self._processar_fila)  # drena pedidos das threads (único after recorrente)
        # animacao visivel enquanto o catalogo embutido carrega
        try:
            animar_spinner(self.lbl_cat_info, prefixo="Carregando catálogo")
        except Exception:
            pass
        self.logar("Catálogo PSP pronto: busque, clique em ⬇ Baixar no jogo ou marque vários.")
        self._carregar_cache_inicial()

    # ------------------------------------------------------------------ tela
    def _montar_tela(self):
        self.grid_columnconfigure(0, weight=1)
        # linha das abas nunca esmaga (minsize): era ela que sumia da tela
        self.grid_rowconfigure(2, weight=1, minsize=400)

        # ---- cabeçalho ----
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        topo.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(topo, text="🎮 Catálogo PSP — 2207 jogos", font=FONTE_TITULO,
                     text_color="white").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(topo, text="com capinhas • modo torrent • baixe aqui dentro",
                     font=FONTE_SUB, text_color=COR_TEXTO_FRACO).grid(row=1, column=0, sticky="w")
        self.pill_status = ctk.CTkLabel(topo, text="● parado", font=("Segoe UI", 11, "bold"),
                                        fg_color=COR_CARD, corner_radius=999, padx=12, pady=4,
                                        text_color=COR_TEXTO_FRACO)
        self.pill_status.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))

        # ---- destino (local; o catálogo já vem embutido, sem site) ----
        cfg = Cartao(self, titulo="💾 Destino")
        cfg.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        corpo = cfg.corpo
        corpo.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(corpo, text="Salvar em", font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).grid(
            row=0, column=0, sticky="w", padx=14, pady=(4, 2))
        self.ent_pasta = ctk.CTkEntry(corpo, font=FONTE_NORMAL, height=36,
                                      fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_pasta.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(4, 2))
        self.ent_pasta.insert(0, str(PASTA_PADRAO))
        ctk.CTkButton(corpo, text="📁", width=48, height=36, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_escolher_pasta).grid(row=0, column=2, padx=(0, 14), pady=(4, 2))

        opt = ctk.CTkFrame(corpo, fg_color="transparent")
        opt.grid(row=1, column=1, columnspan=2, sticky="e", padx=(0, 14), pady=(2, 6))
        ctk.CTkSwitch(opt, text="Resume", variable=self.var_resume,
                      font=FONTE_NORMAL).pack(side="left", padx=(0, 12))
        ctk.CTkSwitch(opt, text="Pular já baixados", variable=self.var_pular,
                      font=FONTE_NORMAL).pack(side="left")

        # ---- abas (só catálogo + baixados; nada de site) ----
        self.tabs = ctk.CTkTabview(self, fg_color="transparent",
                                   segmented_button_fg_color=COR_CARD,
                                   segmented_button_selected_color=COR_VERDE,
                                   text_color="white")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        self.tab_catalogo = self.tabs.add("🗂 Catálogo (2207)")
        self.tab_nav = self.tabs.add("🌐 Navegador")
        self.tab_meus = self.tabs.add("💾 Meus jogos")
        self._montar_aba_catalogo(self.tab_catalogo)
        self._montar_aba_navegador(self.tab_nav)
        self._montar_aba_meus(self.tab_meus)
        self.tabs.set("🗂 Catálogo (2207)")

        # ---- downloads estilo torrent (fila compartilhada) ----
        base = Cartao(self, titulo="⬇ Downloads")
        base.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        topo_dl = ctk.CTkFrame(base, fg_color="transparent")
        topo_dl.pack(fill="x", padx=14)
        self.lbl_vel_total = ctk.CTkLabel(topo_dl, text="fila vazia",
                                          font=("Segoe UI", 10),
                                          text_color=COR_TEXTO_FRACO)
        self.lbl_vel_total.pack(side="left")
        ctk.CTkButton(topo_dl, text="Limpar concluídos", width=140, height=28,
                      fg_color=COR_CARD, border_width=1, border_color=COR_BORDA,
                      font=("Segoe UI", 11),
                      command=self.acao_limpar_dl).pack(side="right")
        self.dl_scroll = ctk.CTkScrollableFrame(base, fg_color="#0f1319",
                                                border_width=1, border_color=COR_BORDA,
                                                corner_radius=8, height=130)
        self.dl_scroll.pack(fill="x", padx=14, pady=(4, 12))
        ctk.CTkLabel(self.dl_scroll, text="Nenhum download — clique em ⬇ num jogo para enfileirar.",
                     font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=10)

        card_log = Cartao(self, titulo="🧾 Log")
        card_log.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 14))
        self.log = ctk.CTkTextbox(card_log, font=FONTE_MONO_PEQ, height=95,
                                  fg_color="#0b0d11", text_color="#d1d5db",
                                  border_width=0, corner_radius=8)
        self.log.pack(fill="x", padx=14, pady=(2, 14))
        self.log.configure(state="disabled")

    # ----------------------------------------------------- aba: catálogo
    def _montar_aba_catalogo(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        barra = ctk.CTkFrame(tab, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        barra.grid_columnconfigure(0, weight=1)
        self.ent_busca_cat = ctk.CTkEntry(barra, font=FONTE_NORMAL, height=36,
                                          placeholder_text="🔍 Buscar no catálogo… (ex: god of war)",
                                          fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_busca_cat.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.ent_busca_cat.bind("<KeyRelease>", lambda _e: self._busca_cat_mudou())
        self.var_ocultar_baixados = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(barra, text="Ocultar já baixados", variable=self.var_ocultar_baixados,
                      font=FONTE_NORMAL, command=self._busca_cat_mudou).grid(row=0, column=1, padx=(0, 8))

        linha2 = ctk.CTkFrame(tab, fg_color="transparent")
        linha2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.btn_cat_status = ctk.CTkButton(linha2, text="🔄 Atualizar status", width=150, height=38,
                                            fg_color=COR_CARD, border_width=1, border_color=COR_BORDA,
                                            command=self.acao_atualizar_status_catalogo)
        self.btn_cat_status.grid(row=0, column=0, padx=(0, 6))
        self.lbl_cat_info = ctk.CTkLabel(linha2, text="carregando catálogo embutido…",
                                         font=("Segoe UI", 10), text_color=COR_TEXTO_FRACO)
        self.lbl_cat_info.grid(row=0, column=1, sticky="e", padx=(8, 0))
        linha2.grid_columnconfigure(1, weight=1)

        pag = ctk.CTkFrame(tab, fg_color="transparent")
        pag.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.btn_pag_ant = ctk.CTkButton(pag, text="◀ Anterior", width=110, height=32,
                                         fg_color=COR_CARD, border_width=1,
                                         border_color=COR_BORDA,
                                         command=lambda: self._pag_catalogo(-1))
        self.btn_pag_ant.pack(side="left")
        self.lbl_pag = ctk.CTkLabel(pag, text="", font=("Segoe UI", 11),
                                    text_color=COR_TEXTO_FRACO)
        self.lbl_pag.pack(side="left", padx=12)
        self.btn_pag_prox = ctk.CTkButton(pag, text="Próxima ▶", width=110, height=32,
                                          fg_color=COR_CARD, border_width=1,
                                          border_color=COR_BORDA,
                                          command=lambda: self._pag_catalogo(1))
        self.btn_pag_prox.pack(side="left")

        self.cat_scroll = ctk.CTkScrollableFrame(tab, fg_color="#0f1319",
                                                 border_width=1, border_color=COR_BORDA,
                                                 corner_radius=8, height=340)
        self.cat_scroll.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.lbl_cat_vazio = ctk.CTkLabel(self.cat_scroll,
                                          text="Carregando catálogo embutido (2207 jogos)…",
                                          font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO)
        self.lbl_cat_vazio.pack(padx=10, pady=16)

        rodape = ctk.CTkFrame(tab, fg_color="transparent")
        rodape.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.btn_cat_baixar = ctk.CTkButton(rodape, text="⬇ Baixar marcados", height=42,
                                            font=("Segoe UI", 12, "bold"),
                                            fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                                            command=self.acao_baixar_catalogo)
        self.btn_cat_baixar.grid(row=0, column=0, padx=(0, 6))
        self.btn_cat_tudo = ctk.CTkButton(rodape, text="⬇⬇ Baixar TUDO", width=150, height=42,
                      fg_color=COR_AMBAR, hover_color="#b45309", text_color="white",
                      font=("Segoe UI", 12, "bold"),
                      command=self.acao_baixar_tudo)
        self.btn_cat_tudo.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(rodape, text="✓ Todos", width=80, height=42, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=lambda: self._marcar_cat_todos(True)).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkButton(rodape, text="✕ Nenhum", width=80, height=42, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=lambda: self._marcar_cat_todos(False)).grid(row=0, column=3, padx=(0, 6))

    # --------------------------------------------------- aba: meus jogos
    def _montar_aba_meus(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        barra = ctk.CTkFrame(tab, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        barra.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(barra, text="🔄 Atualizar", width=130, height=38, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_atualizar_meus).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(barra, text="📁 Abrir pasta", width=130, height=38, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_abrir_pasta).grid(row=0, column=1)
        self.lbl_meus_info = ctk.CTkLabel(barra, text="—", font=("Segoe UI", 10),
                                          text_color=COR_TEXTO_FRACO)
        self.lbl_meus_info.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.meus_scroll = ctk.CTkScrollableFrame(tab, fg_color="#0f1319",
                                                  border_width=1, border_color=COR_BORDA,
                                                  corner_radius=8, height=340)
        self.meus_scroll.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # --------------------------------------------- ponte thread-safe p/ UI
    def emit(self, fn):
        """Enfileira atualização de UI vinda de worker thread (thread-safe)."""
        self._fila_ui.put(fn)

    def _processar_fila(self):
        """Roda na thread principal: executa os pedidos enfileirados."""
        try:
            for _ in range(100):
                try:
                    fn = self._fila_ui.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:
                    pass
        finally:
            try:
                if self.winfo_exists():
                    self.after(120, self._processar_fila)
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def logar(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, texto: str, cor: str = COR_TEXTO_FRACO):
        self.pill_status.configure(text=f"● {texto}", text_color=cor)

    def pasta_downloads(self) -> str:
        return self.ent_pasta.get().strip() or str(PASTA_PADRAO)

    def rodar_em_thread(self, alvo):
        threading.Thread(target=alvo, daemon=True).start()

    def _marcar_cat_todos(self, valor: bool):
        for _, var in self.cat_checks:
            var.set(valor)

    def _itens_cat_marcados(self) -> list[dict]:
        return [item for item, var in self.cat_checks if var.get()]

    # ----------------------------------------------------------------- ações
    def acao_escolher_pasta(self):
        d = filedialog.askdirectory()
        if d:
            self.ent_pasta.delete(0, "end")
            self.ent_pasta.insert(0, d)
            self._render_catalogo()  # re-cruza já-baixados com a nova pasta
            self.acao_atualizar_meus()

    # ------------------------------------------------- motor de download
    # --------------------------------------- downloads estilo torrent
    DL_COR = {"fila": COR_TEXTO_FRACO, "baixando": COR_AZUL, "pausado": COR_AMBAR,
              "concluido": COR_VERDE, "erro": COR_VERMELHO, "cancelado": COR_TEXTO_FRACO}
    DL_TXT = {"fila": "na fila", "baixando": "baixando", "pausado": "pausado",
              "concluido": "concluído", "erro": "erro", "cancelado": "cancelado"}

    def enfileirar_download(self, alvos: list[dict]):
        """Manda jogos p/ a fila (pode chamar a qualquer hora, como no torrent)."""
        if not alvos:
            return
        pasta = self.pasta_downloads()  # snapshot na thread principal
        resume, pular = self.var_resume.get(), self.var_pular.get()
        with self._fila_lock:
            for alvo in alvos:
                self._seq_dl += 1
                self.fila_dl.append({
                    "seq": self._seq_dl, "titulo": alvo.get("nome_arquivo", "?"),
                    "nome": alvo.get("nome_arquivo", "?"), "url": alvo.get("url", ""),
                    "pasta": pasta, "resume": resume, "pular": pular,
                    "estado": "fila", "rec": 0, "tot": 0, "vel": 0.0,
                    "controle": ControleDownload(), "widgets": {},
                    "erro": "", "destino": "", "nota": "",
                })
        self.logar(f"Enfileirado(s) {len(alvos)} jogo(s).")
        self._render_fila()
        self._garantir_worker_dl()

    def _achar_dl(self, seq: int) -> dict | None:
        with self._fila_lock:
            return next((it for it in self.fila_dl if it["seq"] == seq), None)

    def _garantir_worker_dl(self):
        if self._worker_dl_rodando:
            return
        self._worker_dl_rodando = True
        self.rodar_em_thread(self._worker_dl_bg)

    def _worker_dl_bg(self):
        """Baixa a fila um por vez (chamado na thread de fundo)."""
        try:
            while True:
                with self._fila_lock:
                    prox = next((it for it in self.fila_dl if it["estado"] == "fila"), None)
                    if prox is None:
                        break
                    prox["estado"] = "baixando"
                    prox["ult_t"] = time.time()
                    prox["ult_rec"] = 0
                    prox["ult_emit"] = 0.0
                self.emit(lambda: self._render_fila())
                self.emit(lambda p=prox["titulo"]: self.logar(f"Baixando {p} ..."))
                self._baixar_item(prox)
            self.emit(lambda: self.logar("Fila concluída."))
        finally:
            self._worker_dl_rodando = False
            self.emit(self._render_fila)
            self.emit(self._pos_download)

    def _baixar_item(self, item: dict):
        def prog(rec, tot):
            agora = time.time()
            dt = agora - item["ult_t"]
            if dt >= 0.5:
                item["vel"] = (rec - item["ult_rec"]) / dt if dt > 0 else 0.0
                item["ult_t"] = agora
                item["ult_rec"] = rec
            item["rec"] = rec
            item["tot"] = tot or 0
            if agora - item["ult_emit"] >= 0.5:
                item["ult_emit"] = agora
                self.emit(lambda: self._atualizar_linha_dl(item))
        def logm(m):
            self.emit(lambda: self.logar(f"  ↳ {m}"))
        try:
            dest = baixar_inteligente(
                item["url"], item["pasta"], nome_base=item["nome"],
                termos=[item["titulo"]], extensoes=[], timeout=120,
                callback_progress=prog, callback_log=logm,
                controle=item["controle"],
                permitir_resume=item["resume"],
                pular_existentes=item["pular"],
            )
            item.update(estado="concluido", destino=str(dest))
            self.emit(lambda d=str(dest), n=item["titulo"]: self.logar(f"✅ {n} -> {d}"))
        except DownloadJaExiste as e:
            item.update(estado="concluido", destino=str(e.destino), nota="já existia")
            self.emit(lambda n=item["titulo"]: self.logar(f"PULADO (já existe): {n}"))
        except DownloadCancelado:
            item["estado"] = "cancelado"
            self.emit(lambda n=item["titulo"]: self.logar(
                f"Download cancelado (.part mantido): {n}"))
        except Exception as e:
            item.update(estado="erro", erro=str(e)[:200])
            self.emit(lambda e=str(e), n=item["titulo"]: self.logar(f"❌ FALHOU {n}: {e}"))
        self.emit(lambda: self._render_fila())
        self.emit(self._pos_download)

    def acao_dl_pausar(self, seq: int):
        it = self._achar_dl(seq)
        if it and it["estado"] == "baixando":
            it["controle"].pausar()
            it["estado"] = "pausado"
            self.logar(f"⏸ Pausado: {it['titulo']} (.part mantido p/ continuar)")
            self._render_fila()

    def acao_dl_continuar(self, seq: int):
        it = self._achar_dl(seq)
        if it and it["estado"] == "pausado":
            it["controle"].continuar()
            it["estado"] = "baixando"
            self.logar(f"▶ Continuando: {it['titulo']}")
            self._render_fila()

    def acao_dl_cancelar(self, seq: int):
        it = self._achar_dl(seq)
        if it is None:
            return
        if it["estado"] in ("baixando", "pausado"):
            it["controle"].cancelar()  # o worker marca como cancelado
            self.logar(f"✖ Cancelando: {it['titulo']}...")
        else:  # na fila / terminado: some da lista na hora
            with self._fila_lock:
                self.fila_dl = [x for x in self.fila_dl if x["seq"] != seq]
            self._render_fila()

    def acao_limpar_dl(self):
        with self._fila_lock:
            self.fila_dl = [x for x in self.fila_dl
                            if x["estado"] in ("fila", "baixando", "pausado")]
        self._render_fila()

    def _info_linha_dl(self, it: dict) -> tuple[float, str]:
        """(fração 0-1, texto 'vel • ETA • % • baixado/total')."""
        rec, tot, vel = it.get("rec", 0), it.get("tot", 0), it.get("vel", 0.0)
        if it.get("estado") == "concluido":
            return 1.0, "concluído" + (f" ({it['nota']})" if it.get("nota") else "")
        if tot:
            pct = rec / tot
            eta = (tot - rec) / vel if vel > 0 else -1
            return pct, (f"{formatar_velocidade(vel)}  •  ETA {formatar_eta(eta)}  •  "
                         f"{int(pct * 100)}%  •  {formatar_bytes(rec)}/{formatar_bytes(tot)}")
        if rec:
            return 0.0, f"{formatar_velocidade(vel)}  •  {formatar_bytes(rec)} baixados"
        return 0.0, self.DL_TXT.get(it.get("estado"), "")

    def _linha_dl(self, it: dict):
        linha = ctk.CTkFrame(self.dl_scroll, fg_color="transparent")
        linha.pack(fill="x", padx=6, pady=3)
        topo = ctk.CTkFrame(linha, fg_color="transparent")
        topo.pack(fill="x")
        nome = it["titulo"] if len(it["titulo"]) <= 48 else it["titulo"][:47] + "…"
        ctk.CTkLabel(topo, text=nome, font=("Segoe UI", 11),
                     text_color="#e5e7eb").pack(side="left")
        est = it.get("estado", "fila")
        lbl_est = ctk.CTkLabel(topo, text=self.DL_TXT.get(est, est),
                               font=("Segoe UI", 10, "bold"),
                               text_color=self.DL_COR.get(est, COR_TEXTO_FRACO))
        lbl_est.pack(side="left", padx=(8, 0))
        ctk.CTkButton(topo, text="✖", width=32, height=26, fg_color=COR_VERMELHO,
                      hover_color="#991b1b", font=("Segoe UI", 11, "bold"),
                      command=lambda s=it["seq"]: self.acao_dl_cancelar(s)).pack(side="right")
        btn_go = ctk.CTkButton(topo, text="▶", width=32, height=26, fg_color=COR_CARD,
                               border_width=1, border_color=COR_BORDA,
                               command=lambda s=it["seq"]: self.acao_dl_continuar(s))
        btn_go.pack(side="right", padx=(0, 4))
        btn_pausa = ctk.CTkButton(topo, text="⏸", width=32, height=26, fg_color=COR_AMBAR,
                                  hover_color="#b45309",
                                  command=lambda s=it["seq"]: self.acao_dl_pausar(s))
        btn_pausa.pack(side="right", padx=(0, 4))
        if est != "baixando":
            btn_pausa.configure(state="disabled")
        if est != "pausado":
            btn_go.configure(state="disabled")
        bar = ctk.CTkProgressBar(linha, height=10, corner_radius=999,
                                 progress_color=COR_VERDE)
        bar.pack(fill="x", pady=(2, 0))
        lbl_info = ctk.CTkLabel(linha, text="", font=("Segoe UI", 10),
                                text_color=COR_TEXTO_FRACO)
        lbl_info.pack(anchor="w")
        it["widgets"] = {"est": lbl_est, "pausa": btn_pausa, "go": btn_go,
                         "bar": bar, "info": lbl_info}
        self._atualizar_linha_dl(it)

    def _atualizar_linha_dl(self, it: dict):
        """Atualiza só a linha do item (chamado ~2x/s durante o download)."""
        w = it.get("widgets") or {}
        if not w:
            return
        try:
            frac, texto = self._info_linha_dl(it)
            w["bar"].set(max(0.0, min(1.0, frac)))
            w["info"].configure(text=texto)
        except Exception:
            pass  # linha foi redesenhada no meio da atualização

    def _render_fila(self):
        """Redesenha a fila (enfileirou, mudou de estado, terminou)."""
        if not hasattr(self, "dl_scroll"):
            return
        for w in self.dl_scroll.winfo_children():
            w.destroy()
        if not self.fila_dl:
            ctk.CTkLabel(self.dl_scroll,
                         text="Nenhum download — clique em ⬇ num jogo para enfileirar.",
                         font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=10)
        for it in self.fila_dl:
            self._linha_dl(it)
        ativos = [i for i in self.fila_dl
                  if i["estado"] in ("baixando", "pausado", "fila")]
        vel = sum(i.get("vel", 0.0) for i in self.fila_dl if i["estado"] == "baixando")
        if ativos:
            n_baix = sum(1 for i in ativos if i["estado"] == "baixando")
            self.set_status(f"{n_baix} baixando + {len(ativos) - n_baix} na fila", COR_AZUL)
            self.lbl_vel_total.configure(
                text=f"{len(ativos)} na fila  •  {formatar_velocidade(vel)} no total")
            try:
                pulsar_pill(self.pill_status, True)  # pisca azul/verde (visivel)
            except Exception:
                pass
        else:
            n_ok = sum(1 for i in self.fila_dl if i["estado"] == "concluido")
            self.set_status(f"pronto ({n_ok} concluídos)" if self.fila_dl else "parado",
                            COR_VERDE if self.fila_dl else COR_TEXTO_FRACO)
            self.lbl_vel_total.configure(
                text=f"{n_ok} concluído(s) — Limpar concluídos libera a lista"
                if self.fila_dl else "fila vazia")
            try:
                parar_pulso(self.pill_status,
                            COR_VERDE if self.fila_dl else COR_TEXTO_FRACO)
            except Exception:
                pass

    def _pos_download(self):
        """Após baixar: atualiza badges do catálogo e a aba Meus jogos."""
        try:
            anotar_catalogo(self.catalogo, self.pasta_downloads())
        except Exception:
            pass
        self._render_catalogo()
        self.acao_atualizar_meus()

    # ------------------------------------------------------- catálogo
    def _carregar_cache_inicial(self):
        try:
            cache = carregar_catalogo_cache(pasta_base())
        except Exception:
            return
        if cache.get("jogos"):
            self.catalogo = cache["jogos"]
            try:
                anotar_catalogo(self.catalogo, self.pasta_downloads())
            except Exception:
                pass
            self._render_catalogo()
            n = sum(1 for j in self.catalogo if j.get("ja_baixado"))
            self.logar(f"Catálogo embutido: {len(self.catalogo)} jogos ({n} já baixados).")
            self.set_status(f"catálogo: {len(self.catalogo)} jogos", COR_VERDE)
        else:
            self.lbl_cat_info.configure(text="❌ catalogo-psp.json não encontrado",
                                        text_color=COR_VERMELHO)
            self.logar("ERRO: catalogo-psp.json não encontrado ao lado do programa.")

    def acao_atualizar_status_catalogo(self):
        """Re-cruza o catálogo com a pasta (quem já foi baixado ganha badge)."""
        if not self.catalogo:
            self.logar("Nenhum catálogo carregado.")
            return
        try:
            anotar_catalogo(self.catalogo, self.pasta_downloads())
        except Exception as e:
            self.logar(f"ERRO ao verificar baixados: {e}")
            return
        n = sum(1 for j in self.catalogo if j.get("ja_baixado"))
        self.logar(f"Status atualizado: {n}/{len(self.catalogo)} já baixados.")
        self._render_catalogo()

    def _jogos_visiveis(self) -> list[dict]:
        busca = self.ent_busca_cat.get().strip() if hasattr(self, "ent_busca_cat") else ""
        visiveis = filtrar_catalogo(self.catalogo, busca)
        if self.var_ocultar_baixados.get():
            visiveis = [j for j in visiveis if not j.get("ja_baixado")]
        return visiveis

    def _busca_cat_mudou(self):
        """Busca/filtro mudou: volta p/ a página 1 e redesenha."""
        self.cat_pagina = 0
        self._render_catalogo()

    def _pag_catalogo(self, delta: int):
        self.cat_pagina = max(0, self.cat_pagina + delta)
        self._render_catalogo()
        try:
            self.cat_scroll._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def _render_catalogo(self):
        if not hasattr(self, "cat_scroll"):
            return
        for w in self.cat_scroll.winfo_children():
            w.destroy()
        self.cat_checks = []
        self._thumb_job += 1  # invalida loaders de capa anteriores
        visiveis = self._jogos_visiveis()
        n_baixados = sum(1 for j in self.catalogo if j.get("ja_baixado"))
        self.lbl_cat_info.configure(
            text=f"{len(visiveis)}/{len(self.catalogo)} jogos  •  {n_baixados} já baixados",
            text_color=COR_TEXTO_FRACO)
        total = len(visiveis)
        paginas = max(1, (total + CAT_POR_PAGINA - 1) // CAT_POR_PAGINA)
        self.cat_pagina = max(0, min(self.cat_pagina, paginas - 1))
        ini = self.cat_pagina * CAT_POR_PAGINA
        if hasattr(self, "lbl_pag"):
            fim = min(ini + CAT_POR_PAGINA, total)
            self.lbl_pag.configure(
                text=f"Página {self.cat_pagina + 1}/{paginas}  •  {ini + 1 if total else 0}–{fim} de {total}")
            self.btn_pag_ant.configure(state="normal" if self.cat_pagina > 0 else "disabled")
            self.btn_pag_prox.configure(
                state="normal" if self.cat_pagina < paginas - 1 else "disabled")
        if not self.catalogo:
            ctk.CTkLabel(self.cat_scroll,
                         text="❌ catalogo-psp.json não encontrado ao lado do programa.",
                         font=FONTE_NORMAL, text_color=COR_VERMELHO).pack(padx=10, pady=16)
            return
        if not visiveis:
            ctk.CTkLabel(self.cat_scroll, text="Nenhum jogo para essa busca.",
                         font=FONTE_NORMAL, text_color=COR_AMBAR).pack(padx=10, pady=16)
            return
        mostrar = visiveis[ini:ini + CAT_POR_PAGINA]  # 100 por vez: rápido
        self._grade_jogos(self.cat_scroll, mostrar, botoes="catalogo", colunas=4)
        # com internet: baixa as capinhas e guarda em capas/ (sem internet: mostra 🎮)
        self._carregar_thumbs_job(self._thumb_job, [j for j in mostrar if j.get("capa")][:100],
                                  buscar_web=True)

    def _grade_jogos(self, pai_scroll, jogos: list[dict], botoes: str = "catalogo",
                     colunas: int = 4):
        """Grade horizontal de cartões (4 por linha): capa em cima, botões embaixo."""
        grade = ctk.CTkFrame(pai_scroll, fg_color="transparent")
        grade.pack(fill="x", padx=2, pady=2)
        for c in range(colunas):
            grade.grid_columnconfigure(c, weight=1)
        for i, jogo in enumerate(jogos):
            self._cartao_jogo(grade, jogo, botoes).grid(
                row=i // colunas, column=i % colunas, padx=6, pady=6, sticky="nsew")

    def _cartao_jogo(self, grade, jogo: dict, botoes: str = "catalogo"):
        """Um cartão da grade: capão, título, badge e botões."""
        card = ctk.CTkFrame(grade, fg_color=COR_CARD, border_width=1,
                            border_color=COR_BORDA, corner_radius=14)
        thumb = ctk.CTkLabel(card, text="🎮", width=160, height=160,
                             fg_color="#0b0d11", corner_radius=10,
                             font=("Segoe UI", 36))
        thumb.pack(padx=8, pady=(8, 4))
        jogo["_thumb_label"] = thumb  # temporário, só p/ o loader desta renderização
        jogo["_thumb_size"] = 160
        titulo = jogo.get("titulo", "?")
        if len(titulo) > 40:
            titulo = titulo[:39] + "…"
        ctk.CTkLabel(card, text=titulo, font=("Segoe UI", 11), text_color="#e5e7eb",
                     wraplength=190, height=40, justify="center").pack(padx=6)
        baixado = jogo.get("ja_baixado")
        if botoes != "catalogo":  # no navegador confere na hora (disco + manifesto)
            try:
                baixado = bool(ja_baixado(self.pasta_downloads(), jogo.get("titulo"),
                                          jogo.get("url", "")))
            except Exception:
                baixado = False
        if baixado:
            ctk.CTkLabel(card, text="✓ BAIXADO", font=("Segoe UI", 10, "bold"),
                         fg_color="#14532d", text_color="#86efac",
                         corner_radius=6, padx=8, pady=1).pack(pady=(0, 2))
        barra = ctk.CTkFrame(card, fg_color="transparent")
        barra.pack(fill="x", padx=6, pady=(2, 8))
        if botoes == "catalogo":
            var = ctk.BooleanVar(value=not jogo.get("ja_baixado"))
            ctk.CTkCheckBox(barra, variable=var, corner_radius=6, text="",
                            width=24).pack(side="left")
            self.cat_checks.append((jogo, var))
        else:
            ctk.CTkButton(barra, text="Abrir", width=56, height=30,
                          fg_color=COR_CARD, border_width=1, border_color=COR_BORDA,
                          font=("Segoe UI", 11),
                          command=lambda u=jogo["url"]: self.navegar_para(u)).pack(side="left")
            self.nav_checks.append((jogo, None))
        ctk.CTkButton(barra, text="👁", width=36, height=30, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      font=("Segoe UI", 13),
                      command=lambda j=jogo: self.ver_detalhe(j)).pack(side="left", padx=4)
        ctk.CTkButton(barra, text="⬇ Baixar", width=72, height=30,
                      fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                      font=("Segoe UI", 11, "bold"),
                      command=lambda j=jogo: self.acao_baixar_um(j)).pack(side="left")
        hover_card(card)  # brilho azul ao passar o mouse (animacao visivel)
        return card

    def _carregar_thumbs_job(self, job: int, jogos: list[dict], buscar_web: bool = False):
        """Garante as capas em `capas/` (thread) e aplica na thread principal.

        Com `buscar_web=True` baixa o que falta; senão usa só o disco local.
        """
        if not jogos:
            return
        def bg():
            for jogo in jogos:
                if job != self._thumb_job:
                    return  # renderização mais nova assumiu
                capa = jogo.get("capa", "")
                if not capa:
                    continue
                if buscar_web:
                    try:
                        baixar_capa(capa, pasta_base())
                    except Exception:
                        pass
            self.emit( lambda: self._aplicar_thumbs(job))
        threading.Thread(target=bg, daemon=True).start()

    def _aplicar_thumbs(self, job: int):
        """Cola as capas nos cartões (cache por URL + tamanho)."""
        if job != self._thumb_job:
            return
        for jogo, _var in list(self.cat_checks) + list(self.nav_checks):
            capa = jogo.get("capa", "")
            label = jogo.pop("_thumb_label", None)
            size = jogo.pop("_thumb_size", 120)
            if label is None or not capa:
                continue
            try:
                if not label.winfo_exists():
                    continue
            except Exception:
                continue
            chave = (capa, size)
            if chave not in self._thumbs:
                local = caminho_capa_local(capa)
                if local is None:
                    continue
                try:
                    base = Image.open(str(local)).convert("RGB")
                    img = base.resize((size, size))
                    self._thumbs[chave] = ctk.CTkImage(light_image=img, dark_image=img,
                                                      size=(size, size))
                except Exception:
                    continue
            try:
                label.configure(text="", image=self._thumbs[chave])
            except Exception:
                pass

    def _alvo_de_jogo(self, jogo: dict) -> dict:
        return {"texto": jogo.get("titulo", ""), "nome_arquivo": jogo.get("titulo", ""),
                "url": jogo.get("url", ""), "extensao_url": ""}

    def acao_baixar_catalogo(self):
        marcados = self._itens_cat_marcados()
        if not marcados:
            messagebox.showinfo("Catálogo", "Marque ao menos um jogo com ✓.")
            return
        alvos = []
        for jogo in marcados:
            if jogo.get("ja_baixado") and self.var_pular.get():
                self.logar(f"PULADO (já existe): {jogo.get('titulo')}")
                continue
            alvos.append(self._alvo_de_jogo(jogo))
        if not alvos:
            messagebox.showinfo("Catálogo", "Todos os marcados já foram baixados. ✔")
            return
        self.enfileirar_download(alvos)

    def acao_baixar_um(self, jogo: dict):
        """Manda UM jogo p/ a fila direto pelo botão ⬇ da linha."""
        if jogo.get("ja_baixado") and self.var_pular.get():
            messagebox.showinfo("Catálogo", f"Este jogo já foi baixado. ✔\n\n{jogo.get('titulo')}")
            return
        self.enfileirar_download([self._alvo_de_jogo(jogo)])

    def acao_baixar_tudo(self):
        """Manda TODOS os visíveis (filtro atual) p/ a fila — tudo se sem busca."""
        visiveis = self._jogos_visiveis()
        if not visiveis:
            messagebox.showinfo("Catálogo", "Nada visível para baixar (ajuste a busca).")
            return
        n = len(visiveis)
        if not messagebox.askyesno(
            "Baixar TUDO?",
            f"Vai baixar {n} jogo(s) (~1 GB cada em média = pode passar de 1 TB!).\n"
            f"Já baixados serão pulados.\n\nContinuar?"):
            return
        alvos = []
        for jogo in visiveis:
            if jogo.get("ja_baixado") and self.var_pular.get():
                continue
            alvos.append(self._alvo_de_jogo(jogo))
        if not alvos:
            messagebox.showinfo("Catálogo", "Todos os visíveis já foram baixados. ✔")
            return
        self.enfileirar_download(alvos)

    # --------------------------------------------------- aba: navegador
    def _montar_aba_navegador(self, tab):
        """Mini navegador do site: endereço, ◀ ▶ ⟳ 🏠 e páginas aqui dentro."""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(tab, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        nav.grid_columnconfigure(4, weight=1)
        self.btn_nav_voltar = ctk.CTkButton(nav, text="◀", width=44, height=36,
                                            fg_color=COR_CARD, border_width=1,
                                            border_color=COR_BORDA,
                                            command=self.acao_nav_voltar, state="disabled")
        self.btn_nav_voltar.grid(row=0, column=0, padx=(0, 6))
        self.btn_nav_avancar = ctk.CTkButton(nav, text="▶", width=44, height=36,
                                             fg_color=COR_CARD, border_width=1,
                                             border_color=COR_BORDA,
                                             command=self.acao_nav_avancar, state="disabled")
        self.btn_nav_avancar.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(nav, text="⟳", width=44, height=36, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_nav_recarregar).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkButton(nav, text="🏠", width=44, height=36, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_nav_home).grid(row=0, column=3, padx=(0, 6))
        self.ent_nav_url = ctk.CTkEntry(nav, font=FONTE_NORMAL, height=36,
                                        placeholder_text="Endereço da página… (Enter = Ir)",
                                        fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_nav_url.grid(row=0, column=4, sticky="ew", padx=(0, 8))
        self.ent_nav_url.bind("<Return>", lambda _e: self.acao_nav_ir())
        self.ent_nav_url.insert(0, SITE_INICIAL)
        ctk.CTkButton(nav, text="Ir", width=70, height=36,
                      fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                      font=("Segoe UI", 12, "bold"),
                      command=self.acao_nav_ir).grid(row=0, column=5)

        self.lbl_nav_info = ctk.CTkLabel(tab, text="Clique em Ir (ou 🏠) para abrir o site aqui dentro.",
                                         font=("Segoe UI", 10), text_color=COR_TEXTO_FRACO)
        self.lbl_nav_info.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.nav_scroll = ctk.CTkScrollableFrame(tab, fg_color="#0f1319",
                                                 border_width=1, border_color=COR_BORDA,
                                                 corner_radius=8, height=340)
        self.nav_scroll.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        ctk.CTkLabel(self.nav_scroll, text="O site abre aqui dentro — sem sair do programa.",
                     font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=16)

    def _normalizar_endereco(self, texto: str) -> str:
        t = (texto or "").strip()
        if not t:
            raise ValueError("Digite o endereço da página.")
        if "://" not in t:
            t = "https://" + t.lstrip("/")
        if urlparse(t).scheme.lower() not in ("http", "https"):
            raise ValueError("Endereço inválido (use http ou https).")
        return t

    def acao_nav_ir(self):
        try:
            url = self._normalizar_endereco(self.ent_nav_url.get())
        except ValueError as e:
            messagebox.showwarning("Navegador", str(e))
            return
        self.navegar_para(url)

    def acao_nav_home(self):
        self.ent_nav_url.delete(0, "end")
        self.ent_nav_url.insert(0, SITE_INICIAL)
        self.navegar_para(SITE_INICIAL)

    def acao_nav_voltar(self):
        if self.nav_ocupado or not self.hist_voltar:
            return
        if self.nav_atual:
            self.hist_avancar.append(self.nav_atual)
        self.navegar_para(self.hist_voltar.pop(), registrar=False)

    def acao_nav_avancar(self):
        if self.nav_ocupado or not self.hist_avancar:
            return
        if self.nav_atual:
            self.hist_voltar.append(self.nav_atual)
        self.navegar_para(self.hist_avancar.pop(), registrar=False)

    def acao_nav_recarregar(self):
        if self.nav_ocupado or not self.nav_atual:
            return
        self.navegar_para(self.nav_atual, registrar=False)

    def navegar_para(self, url: str, registrar: bool = True):
        """Abre a URL no mini navegador (thread de fundo, UI na principal)."""
        if self.nav_ocupado:
            return
        if registrar and self.nav_atual and self.nav_atual != url:
            self.hist_voltar.append(self.nav_atual)
            self.hist_avancar.clear()
        self.nav_ocupado = True
        self._atualizar_botoes_nav()
        self.lbl_nav_info.configure(text="⏳ Abrindo página…", text_color=COR_AZUL)
        for w in self.nav_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.nav_scroll, text="⏳ Carregando página…",
                     font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=16)
        self.rodar_em_thread(lambda: self._navegar_bg(url))

    def _navegar_bg(self, url: str):
        try:
            pagina = navegar(url, timeout=30)
        except Exception as e:
            self.emit(lambda: self._nav_erro(url, str(e)))
            return
        self.emit(lambda: self._render_nav(pagina))

    def _nav_erro(self, url: str, erro: str):
        self.nav_ocupado = False
        self._atualizar_botoes_nav()
        self.lbl_nav_info.configure(text=f"❌ Falha ao abrir: {erro}", text_color=COR_VERMELHO)
        for w in self.nav_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.nav_scroll,
                     text="Não consegui abrir a página.\nConfira a internet e tente de novo.",
                     font=FONTE_NORMAL, text_color=COR_AMBAR).pack(padx=10, pady=16)
        self.logar(f"ERRO no navegador ({url}): {erro}")

    def _atualizar_botoes_nav(self):
        base = "disabled" if self.nav_ocupado else "normal"
        self.btn_nav_voltar.configure(state=base if self.hist_voltar else "disabled")
        self.btn_nav_avancar.configure(state=base if self.hist_avancar else "disabled")

    def _render_nav(self, pagina: dict):
        self.nav_ocupado = False
        self.nav_checks = []
        self._thumb_job += 1  # a vista visível (navegador) assume o loader de capas
        self.nav_atual = pagina.get("url_final", "")
        for w in self.nav_scroll.winfo_children():
            w.destroy()
        self.ent_nav_url.delete(0, "end")
        self.ent_nav_url.insert(0, self.nav_atual)
        self._atualizar_botoes_nav()
        tipo = pagina.get("tipo")
        if tipo == "lista":
            jogos = pagina["jogos"]
            self.lbl_nav_info.configure(text=f"{len(jogos)} jogo(s) nesta página",
                                        text_color=COR_TEXTO_FRACO)
            self._grade_jogos(self.nav_scroll, jogos, botoes="navegador", colunas=4)
            self._linha_paginacao(pagina.get("prev"), pagina.get("next"))
            self._carregar_thumbs_job(self._thumb_job,
                                      [j for j in jogos if j.get("capa")][:120],
                                      buscar_web=True)
        elif tipo == "jogo":
            d = pagina["detalhe"]
            self.lbl_nav_info.configure(text="Página do jogo — clique em BAIXAR",
                                        text_color=COR_TEXTO_FRACO)
            self._cabecalho_nav_jogo(d)
            rel = pagina.get("jogos") or []
            if rel:
                ctk.CTkLabel(self.nav_scroll, text="Relacionados:",
                             font=("Segoe UI", 12, "bold"),
                             text_color="white").pack(anchor="w", padx=10, pady=(12, 2))
                self._grade_jogos(self.nav_scroll, rel[:60], botoes="navegador", colunas=4)
                self._carregar_thumbs_job(self._thumb_job,
                                          [j for j in rel if j.get("capa")][:60],
                                          buscar_web=True)
        else:
            links = pagina.get("links") or []
            self.lbl_nav_info.configure(text=f"Página ({len(links)} links)",
                                        text_color=COR_TEXTO_FRACO)
            if not links:
                ctk.CTkLabel(self.nav_scroll, text="Página sem links clicáveis.",
                             font=FONTE_NORMAL, text_color=COR_AMBAR).pack(padx=10, pady=16)
                return
            for link in links:
                linha = ctk.CTkFrame(self.nav_scroll, fg_color="transparent")
                linha.pack(fill="x", padx=6, pady=2)
                txt = link["texto"] if len(link["texto"]) <= 70 else link["texto"][:69] + "…"
                ctk.CTkLabel(linha, text="🔗 " + txt, font=("Segoe UI", 11),
                             text_color="#e5e7eb").pack(side="left")
                ctk.CTkButton(linha, text="Abrir", width=70, height=30,
                              fg_color=COR_CARD, border_width=1, border_color=COR_BORDA,
                              command=lambda u=link["url"]: self.navegar_para(u)).pack(
                                  side="right", padx=(6, 2))

    def _cabecalho_nav_jogo(self, d: dict):
        """Topo da página do jogo: capa grande, dados e botão BAIXAR."""
        cartao = ctk.CTkFrame(self.nav_scroll, fg_color=COR_CARD, border_width=1,
                              border_color=COR_BORDA, corner_radius=12)
        cartao.pack(fill="x", padx=6, pady=4)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.pack(fill="x", padx=14, pady=14)
        thumb = ctk.CTkLabel(topo, text="🎮", width=110, height=110,
                             fg_color="#0b0d11", corner_radius=10,
                             font=("Segoe UI", 36))
        thumb.pack(side="left", padx=(0, 12))
        if d.get("capa"):
            pseudo = {"capa": d["capa"], "_thumb_label": thumb, "_thumb_size": 110}
            self.nav_checks.append((pseudo, None))
            self._carregar_thumbs_job(self._thumb_job, [pseudo], buscar_web=True)
        infos = ctk.CTkFrame(topo, fg_color="transparent")
        infos.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(infos, text=d.get("titulo") or "?", font=("Segoe UI", 15, "bold"),
                     text_color="white", wraplength=620, justify="left").pack(anchor="w")
        meta = "  •  ".join(p for p in (
            f"Região: {d['regiao']}" if d.get("regiao") else "",
            f"Tamanho: {d['tamanho']}" if d.get("tamanho") else "",
            f"Nota: {d['nota']} ({d['votos']} votos)" if d.get("nota") else "",
        ) if p)
        if meta:
            ctk.CTkLabel(infos, text=meta, font=("Segoe UI", 11),
                         text_color=COR_TEXTO_FRACO).pack(anchor="w", pady=(4, 0))
        ctk.CTkButton(infos, text="⬇  BAIXAR ESTE JOGO", height=44,
                      font=("Segoe UI", 13, "bold"),
                      fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                      command=lambda: self.acao_baixar_um(
                          {"titulo": d.get("titulo", "?"),
                           "url": d.get("url") or (self.nav_atual or ""),
                           "capa": d.get("capa", "")})).pack(anchor="w", pady=(10, 0))

    def _linha_paginacao(self, prev, next_):
        if not prev and not next_:
            return
        faixa = ctk.CTkFrame(self.nav_scroll, fg_color="transparent")
        faixa.pack(fill="x", padx=6, pady=8)
        if prev:
            ctk.CTkButton(faixa, text="◀ Anterior", width=130, fg_color=COR_CARD,
                          border_width=1, border_color=COR_BORDA,
                          command=lambda: self.navegar_para(prev)).pack(side="left")
        if next_:
            ctk.CTkButton(faixa, text="Próxima ▶", width=130, fg_color=COR_CARD,
                          border_width=1, border_color=COR_BORDA,
                          command=lambda: self.navegar_para(next_)).pack(side="right")

    # ------------------------------------------------ telinha do jogo
    def ver_detalhe(self, jogo: dict):
        """Abre a telinha do jogo: capa, dados do site e botão de download."""
        url = (jogo.get("url") or "").strip()
        if not url:
            return
        modal = ctk.CTkToplevel(self)
        modal.title((jogo.get("titulo") or "Jogo")[:60])
        modal.geometry("660x620")
        modal.minsize(560, 520)
        modal.configure(fg_color=COR_FUNDO)
        modal._imgs = []  # evita garbage collector nas capas
        try:
            modal.transient(self)
            fade_in_modal(modal)  # efeito pop de abertura (visivel)
        except Exception:
            pass
        ctk.CTkLabel(modal, text="⏳ Buscando informações no site…",
                     font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(expand=True)
        self.rodar_em_thread(lambda: self._detalhe_bg(modal, jogo))

    def _detalhe_bg(self, modal, jogo: dict):
        try:
            pagina = navegar(jogo.get("url", ""), timeout=30)
        except Exception as e:
            self.emit(lambda: self._detalhe_erro(modal, str(e)))
            return
        d = dict(pagina.get("detalhe") or {})
        if not d.get("titulo"):
            d["titulo"] = jogo.get("titulo", "?")
        if not d.get("url"):
            d["url"] = jogo.get("url", "")
        capa_local = None
        for cand in (d.get("capa") or "", jogo.get("capa") or ""):
            if cand:
                capa_local = baixar_capa(cand, pasta_base())
                if capa_local is not None:
                    break
        rel = pagina.get("jogos") or [] if pagina.get("tipo") == "jogo" else []
        self.emit(lambda: self._preencher_detalhe(modal, d, rel, capa_local))

    def _detalhe_erro(self, modal, erro: str):
        try:
            if not modal.winfo_exists():
                return
            for w in modal.winfo_children():
                w.destroy()
            ctk.CTkLabel(modal, text=f"❌ Não abri a página.\n{erro}",
                         font=FONTE_NORMAL, text_color=COR_AMBAR).pack(expand=True)
            ctk.CTkButton(modal, text="Fechar", width=120,
                          command=modal.destroy).pack(pady=12)
        except Exception:
            pass  # modal já fechado

    def _preencher_detalhe(self, modal, d: dict, rel: list, capa_local):
        try:
            if not modal.winfo_exists():
                return
            for w in modal.winfo_children():
                w.destroy()
        except Exception:
            return
        corpo = ctk.CTkScrollableFrame(modal, fg_color="transparent", height=540)
        corpo.pack(fill="both", expand=True, padx=6, pady=6)

        topo = ctk.CTkFrame(corpo, fg_color="transparent")
        topo.pack(fill="x", padx=10, pady=(8, 4))
        img_lbl = ctk.CTkLabel(topo, text="🎮", width=180, height=180,
                               fg_color="#0b0d11", corner_radius=12,
                               font=("Segoe UI", 48))
        img_lbl.pack(side="left", padx=(0, 14))
        if capa_local:
            try:
                img = Image.open(str(capa_local)).convert("RGB").resize((180, 180))
                foto = ctk.CTkImage(light_image=img, dark_image=img, size=(180, 180))
                modal._imgs.append(foto)
                img_lbl.configure(text="", image=foto)
            except Exception:
                pass
        info = ctk.CTkFrame(topo, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(info, text=d.get("titulo") or "?", font=("Segoe UI", 16, "bold"),
                     text_color="white", wraplength=400, justify="left").pack(anchor="w")
        for rot, val in (("Região", d.get("regiao")), ("Tamanho", d.get("tamanho")),
                         ("Nota", f"{d['nota']} ({d['votos']} votos)" if d.get("nota") else "")):
            ctk.CTkLabel(info, text=f"{rot}: {val or '?'}", font=("Segoe UI", 11),
                         text_color=COR_TEXTO_FRACO if not val else "#e5e7eb").pack(
                             anchor="w", pady=(2, 0))

        ctk.CTkLabel(corpo, text="📝 Sobre o jogo", font=("Segoe UI", 12, "bold"),
                     text_color="white").pack(anchor="w", padx=14, pady=(8, 0))
        txt = ctk.CTkTextbox(corpo, font=("Segoe UI", 11), fg_color="#0f1319",
                             border_width=1, border_color=COR_BORDA,
                             corner_radius=8, height=110)
        txt.pack(fill="x", padx=14, pady=(2, 6))
        txt.insert("1.0", d.get("descricao") or "Sem descrição no site.")
        txt.configure(state="disabled")

        faixa = ctk.CTkFrame(corpo, fg_color="transparent")
        faixa.pack(fill="x", padx=14, pady=(4, 6))
        ctk.CTkButton(faixa, text="⬇  BAIXAR ESTE JOGO", height=46,
                      font=("Segoe UI", 13, "bold"),
                      fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                      command=lambda: self.enfileirar_download([{
                          "texto": d.get("titulo", ""), "nome_arquivo": d.get("titulo", ""),
                          "url": d.get("url", ""), "extensao_url": ""}])).pack(
                              fill="x", pady=(0, 6))
        linha2 = ctk.CTkFrame(faixa, fg_color="transparent")
        linha2.pack(fill="x")
        ctk.CTkButton(linha2, text="🌐 Abrir no navegador", height=36, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=lambda: (modal.destroy(),
                                       self.tabs.set("🌐 Navegador"),
                                       self.navegar_para(d.get("url", "")))).pack(
                                           side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(linha2, text="Fechar", height=36, width=120, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=modal.destroy).pack(side="left")

        if rel:
            ctk.CTkLabel(corpo, text="🎮 Relacionados:", font=("Segoe UI", 12, "bold"),
                         text_color="white").pack(anchor="w", padx=14, pady=(8, 0))
            for r in rel[:8]:
                nome = r.get("titulo", "?")
                if len(nome) > 52:
                    nome = nome[:51] + "…"
                ctk.CTkButton(corpo, text="👁  " + nome, height=32, anchor="w",
                              fg_color="transparent", hover_color=COR_CARD,
                              text_color="#e5e7eb", font=("Segoe UI", 11),
                              command=lambda j=r: (modal.destroy(), self.ver_detalhe(j))).pack(
                                  fill="x", padx=14, pady=1)

    # ------------------------------------------------------ meus jogos
    def acao_atualizar_meus(self):
        if not hasattr(self, "meus_scroll"):
            return
        for w in self.meus_scroll.winfo_children():
            w.destroy()
        try:
            self.meus_jogos = escanear_baixados(self.pasta_downloads())
        except Exception as e:
            self.logar(f"ERRO ao escanear pasta: {e}")
            return
        finais = [m for m in self.meus_jogos if not m["incompleto"]]
        parts = [m for m in self.meus_jogos if m["incompleto"]]
        total_b = sum(m["bytes"] for m in finais)
        self.lbl_meus_info.configure(
            text=f"{len(finais)} jogo(s)  •  {formatar_bytes(total_b)}  •  "
                 f"{len(parts)} incompleto(s)")
        if not self.meus_jogos:
            ctk.CTkLabel(self.meus_scroll, text="Nada baixado ainda — a pasta está vazia.",
                         font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=16)
            return
        for m in finais:
            linha = ctk.CTkFrame(self.meus_scroll, fg_color="transparent")
            linha.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(linha, text="✅", font=FONTE_NORMAL).pack(side="left", padx=(0, 8))
            nome = m["arquivo"] if len(m["arquivo"]) <= 60 else m["arquivo"][:59] + "…"
            ctk.CTkLabel(linha, text=nome, font=("Segoe UI", 11),
                         text_color="#e5e7eb").pack(side="left")
            ctk.CTkLabel(linha, text=f"{formatar_bytes(m['bytes'])}  •  {m['modificado_em']}",
                         font=("Segoe UI", 10), text_color=COR_TEXTO_FRACO).pack(side="right")
        for m in parts:
            linha = ctk.CTkFrame(self.meus_scroll, fg_color="transparent")
            linha.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(linha, text="⏳", font=FONTE_NORMAL).pack(side="left", padx=(0, 8))
            nome = m["arquivo"] if len(m["arquivo"]) <= 60 else m["arquivo"][:59] + "…"
            ctk.CTkLabel(linha, text=nome, font=("Segoe UI", 11),
                         text_color=COR_TEXTO_FRACO).pack(side="left")
            ctk.CTkLabel(linha, text=f"{formatar_bytes(m['bytes'])}  •  incompleto (dá p/ continuar)",
                         font=("Segoe UI", 10), text_color=COR_AMBAR).pack(side="right")

    def acao_abrir_pasta(self):
        pasta = self.pasta_downloads()
        Path(pasta).mkdir(parents=True, exist_ok=True)
        try:
            abrir_pasta(pasta)
        except Exception as e:
            messagebox.showerror("Erro", f"Não abri a pasta: {e}")


if __name__ == "__main__":
    App().mainloop()
