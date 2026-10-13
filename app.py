"""Catálogo PSP — RomsGames Clone & Downloader (CustomTkinter Dark de Alta Fluidez).

Otimizações de performance e fluidez:
- Rolagem suave e responsiva (aceleração do scroll da roda do mouse sem travamentos).
- Decodificação, redimensionamento (Lanczos) e pós-processamento de capas 100% em thread de fundo.
- Entrega progressiva de miniaturas sem bloquear a thread principal da interface.
- Redução de hierarquia de widgets para eliminar gargalos de renderização do Tkinter.
- Paginação ágil (30 jogos por página) para carregamento instantâneo e rolagem a 60 FPS.
- Dock de download inferior dinâmico: surge imediatamente ao clicar em 'Save Game'.
"""
from __future__ import annotations

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

# Tema Dark inspirado no romsgames.net
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# --- Tokens de Cores RomsGames ---
COR_FUNDO = "#090d16"           # Slate 950 deep dark
COR_HEADER = "#0d1424"          # Navbar slate escura
COR_CARD = "#0f172a"            # Slate 900 card surface
COR_CARD_HOVER = "#162238"      # Hover surface
COR_BORDA = "#1e293b"           # Borda sutil slate
COR_BORDA_HOVER = "#10e9b0"     # Glow mint característico
COR_TEXTO = "#f8fafc"           # Branco nítido
COR_TEXTO_FRACO = "#94a3b8"     # Slate 400
COR_ROMSGAMES_MINT = "#10e9b0"  # O verde/menta icônico do botão "Save Game"
COR_ROMSGAMES_HOVER = "#05d59e" # Hover mint
COR_ROMSGAMES_TEXT = "#020617"  # Texto escuro para botões mint
COR_AMBAR = "#fbbf24"           # Dourado das estrelas/avaliações
COR_VERMELHO = "#ef4444"        # Erro / cancelar
COR_AZUL = "#38bdf8"            # Destaques / links
COR_VERDE_ESC = "#064e3b"       # Badge já baixado
COR_VERDE_TXT = "#6ee7b7"       # Texto badge já baixado

# --- Tipografia ---
FONTE_LOGO = ("Segoe UI", 16, "bold")
FONTE_TITULO = ("Segoe UI", 16, "bold")
FONTE_SUB = ("Segoe UI", 11)
FONTE_NORMAL = ("Segoe UI", 11)
FONTE_BOTAO_MINT = ("Segoe UI", 11, "bold")
FONTE_BOTAO = ("Segoe UI", 11, "bold")
FONTE_PEQ = ("Segoe UI", 10)
FONTE_MONO_PEQ = ("Consolas", 10)


def pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


PASTA_PADRAO = pasta_base() / "downloads"
SITE_INICIAL = "https://www.romsgames.net/roms/playstation-portable/"
CAT_POR_PAGINA = 30  # 30 jogos por página = 6 linhas x 5 colunas (suave e instantâneo)


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
    """Devolve a capa salva em `capas/` sem usar a web (None se ausente)."""
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
    """Bytes/s -> '1.2 MB/s'."""
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


def configurar_scroll_fluido(scroll_widget, velocidade: int = 4):
    """Acelera e suaviza a rolagem da roda do mouse no Tkinter."""
    canvas = getattr(scroll_widget, "_parent_canvas", None)
    if not canvas:
        return

    def _on_wheel(event):
        try:
            if not scroll_widget.winfo_exists():
                return
            # No Windows event.delta vem em passos de 120
            delta = -1 * int(event.delta / 120) * velocidade
            canvas.yview_scroll(delta, "units")
            return "break"
        except Exception:
            pass

    canvas.bind("<MouseWheel>", _on_wheel, add="+")
    try:
        interior = getattr(scroll_widget, "_parent_frame", None)
        if interior:
            interior.bind("<MouseWheel>", _on_wheel, add="+")
    except Exception:
        pass


class Cartao(ctk.CTkFrame):
    """Card padrão dark estilo RomsGames."""

    def __init__(self, parent, titulo: str = "", **kwargs):
        super().__init__(
            parent,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            corner_radius=12,
            **kwargs,
        )
        if titulo:
            ctk.CTkLabel(
                self,
                text=titulo,
                font=("Segoe UI", 12, "bold"),
                text_color=COR_TEXTO,
            ).pack(anchor="w", padx=14, pady=(10, 2))
        self.corpo = ctk.CTkFrame(self, fg_color="transparent")
        self.corpo.pack(fill="x")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("RomsGames — Catálogo PSP (2207 Jogos)")
        self.geometry("1240x940")
        self.minsize(980, 720)
        self.configure(fg_color=COR_FUNDO)

        self.catalogo: list[dict] = []
        self.cat_checks: list[tuple[dict, ctk.BooleanVar]] = []
        self.cat_pagina = 0
        self.nav_checks: list[tuple[dict, None]] = []
        self.meus_jogos: list[dict] = []
        self._thumbs: dict[tuple, ctk.CTkImage] = {}
        self._pil_cache: dict[tuple, Image.Image] = {}  # Cache de imagens já preparadas em RAM
        self._thumb_job = 0
        self._fila_ui: queue.Queue = queue.Queue()
        self.fila_dl: list[dict] = []
        self._fila_lock = threading.Lock()
        self._seq_dl = 0
        self._worker_dl_rodando = False
        self.hist_voltar: list[str] = []
        self.hist_avancar: list[str] = []
        self.nav_atual: str | None = None
        self.nav_ocupado = False

        self.var_resume = ctk.BooleanVar(value=True)
        self.var_pular = ctk.BooleanVar(value=True)
        self._fila_expandida = False

        self._montar_tela()
        self.after(120, self._processar_fila)
        self._carregar_cache_inicial()

    # ------------------------------------------------------------------ tela
    def _montar_tela(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Área principal expande ao máximo

        # =================================================================
        # 1. HEADER NAVBAR (Estilo RomsGames)
        # =================================================================
        navbar = ctk.CTkFrame(self, fg_color=COR_HEADER, corner_radius=0, height=64)
        navbar.grid(row=0, column=0, sticky="ew")
        navbar.grid_columnconfigure(1, weight=1)

        # Esquerda: Logo + Breadcrumb
        logo_frame = ctk.CTkFrame(navbar, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="w", padx=(18, 12), pady=10)

        lbl_logo = ctk.CTkLabel(
            logo_frame,
            text="🎮 RomsGames",
            font=FONTE_LOGO,
            text_color=COR_ROMSGAMES_MINT,
        )
        lbl_logo.pack(side="left", padx=(0, 10))

        crumb_pill = ctk.CTkLabel(
            logo_frame,
            text="ROMs › PlayStation Portable",
            font=FONTE_PEQ,
            fg_color="#1e293b",
            text_color="#94a3b8",
            corner_radius=12,
            padx=10,
            pady=3,
        )
        crumb_pill.pack(side="left")

        # Centro: Barra de Busca Estilo RomsGames
        busca_container = ctk.CTkFrame(navbar, fg_color="transparent")
        busca_container.grid(row=0, column=1, sticky="ew", padx=12, pady=10)
        busca_container.grid_columnconfigure(0, weight=1)

        self.ent_busca_cat = ctk.CTkEntry(
            busca_container,
            font=FONTE_NORMAL,
            height=38,
            placeholder_text="🔍 Search for games... (ex: god of war, naruto, gta)",
            fg_color="#090d16",
            border_color=COR_BORDA,
            corner_radius=20,
        )
        self.ent_busca_cat.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.ent_busca_cat.bind("<KeyRelease>", lambda _e: self._busca_cat_mudou())

        btn_limpa_busca = ctk.CTkButton(
            busca_container,
            text="✕",
            width=32,
            height=32,
            fg_color="transparent",
            hover_color=COR_CARD,
            text_color=COR_TEXTO_FRACO,
            command=self._limpar_busca,
        )
        btn_limpa_busca.grid(row=0, column=1)

        # Direita: Navegação entre Abas + Botão Destino + Status
        nav_actions = ctk.CTkFrame(navbar, fg_color="transparent")
        nav_actions.grid(row=0, column=2, sticky="e", padx=(6, 18), pady=10)

        self.seg_abas = ctk.CTkSegmentedButton(
            nav_actions,
            values=["🎮 ROMs", "🌐 Navegador", "💾 Baixados"],
            command=self._aba_mudou_seg,
            font=FONTE_PEQ,
            selected_color=COR_ROMSGAMES_MINT,
            selected_hover_color=COR_ROMSGAMES_HOVER,
            text_color="#020617",
            fg_color="#111827",
            corner_radius=16,
            height=34,
        )
        self.seg_abas.set("🎮 ROMs")
        self.seg_abas.pack(side="left", padx=(0, 10))

        btn_pasta = ctk.CTkButton(
            nav_actions,
            text="📁 Pasta",
            width=75,
            height=34,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            hover_color=COR_CARD_HOVER,
            command=self.acao_abrir_pasta,
        )
        btn_pasta.pack(side="left", padx=(0, 8))

        self.pill_status = ctk.CTkLabel(
            nav_actions,
            text="● Online",
            font=("Segoe UI", 10, "bold"),
            fg_color="#111827",
            corner_radius=14,
            padx=12,
            pady=4,
            text_color=COR_ROMSGAMES_MINT,
        )
        self.pill_status.pack(side="left")

        # =================================================================
        # 2. SUBHEADER TOOLBAR (Título, Ordenação, Paginação & Filtros)
        # =================================================================
        self.subbar = ctk.CTkFrame(self, fg_color="transparent", height=42)
        self.subbar.grid(row=1, column=0, sticky="ew", padx=18, pady=(10, 4))
        self.subbar.grid_columnconfigure(0, weight=1)

        sub_esq = ctk.CTkFrame(self.subbar, fg_color="transparent")
        sub_esq.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            sub_esq,
            text="Playstation Portable (PSP) ROMs",
            font=("Segoe UI", 14, "bold"),
            text_color=COR_TEXTO,
        ).pack(side="left", padx=(0, 8))

        self.lbl_cat_info = ctk.CTkLabel(
            sub_esq,
            text="carregando...",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
            fg_color=COR_CARD,
            corner_radius=10,
            padx=8,
            pady=2,
        )
        self.lbl_cat_info.pack(side="left")

        sub_dir = ctk.CTkFrame(self.subbar, fg_color="transparent")
        sub_dir.grid(row=0, column=1, sticky="e")

        self.var_ocultar_baixados = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            sub_dir,
            text="Ocultar baixados",
            variable=self.var_ocultar_baixados,
            font=FONTE_PEQ,
            checkbox_height=18,
            checkbox_width=18,
            corner_radius=4,
            border_color=COR_BORDA,
            hover_color=COR_CARD_HOVER,
            command=self._busca_cat_mudou,
        ).pack(side="left", padx=(0, 12))

        # Paginação Rápida
        self.btn_pag_ant = ctk.CTkButton(
            sub_dir,
            text="◀",
            width=34,
            height=30,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=lambda: self._pag_catalogo(-1),
        )
        self.btn_pag_ant.pack(side="left", padx=(0, 4))

        self.lbl_pag = ctk.CTkLabel(
            sub_dir,
            text="",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_pag.pack(side="left", padx=6)

        self.btn_pag_prox = ctk.CTkButton(
            sub_dir,
            text="▶",
            width=34,
            height=30,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=lambda: self._pag_catalogo(1),
        )
        self.btn_pag_prox.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            sub_dir,
            text="✓ Todos",
            width=65,
            height=30,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=lambda: self._marcar_cat_todos(True),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            sub_dir,
            text="✕ Nenhum",
            width=70,
            height=30,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=lambda: self._marcar_cat_todos(False),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            sub_dir,
            text="⬇ Baixar Marcados",
            height=30,
            font=("Segoe UI", 10, "bold"),
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            command=self.acao_baixar_catalogo,
        ).pack(side="left")

        # =================================================================
        # 3. CONTAINER PRINCIPAL DAS ABAS
        # =================================================================
        self.tabs = ctk.CTkTabview(self, fg_color="transparent")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 4))
        self.tabs._segmented_button.grid_remove()

        self.tab_catalogo = self.tabs.add("🎮 ROMs")
        self.tab_nav = self.tabs.add("🌐 Navegador")
        self.tab_meus = self.tabs.add("💾 Baixados")

        self._montar_aba_catalogo(self.tab_catalogo)
        self._montar_aba_navegador(self.tab_nav)
        self._montar_aba_meus(self.tab_meus)
        self.tabs.set("🎮 ROMs")

        # =================================================================
        # 4. DOCK DE DOWNLOAD INFERIOR DINÂMICO
        # =================================================================
        self._montar_dock_download()

    def _limpar_busca(self):
        self.ent_busca_cat.delete(0, "end")
        self._busca_cat_mudou()

    def _aba_mudou_seg(self, valor: str):
        self.tabs.set(valor)
        if valor == "🎮 ROMs":
            self.subbar.grid()
        else:
            self.subbar.grid_remove()

    # ----------------------------------------------------- dock de download
    def _montar_dock_download(self):
        dock = ctk.CTkFrame(
            self,
            fg_color="#080e1a",
            border_width=1,
            border_color=COR_ROMSGAMES_MINT,
            corner_radius=14,
        )
        self.dock_download = dock
        self.dock_download.grid_columnconfigure(1, weight=1)

        topo_dl = ctk.CTkFrame(dock, fg_color="transparent")
        topo_dl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(8, 4))
        topo_dl.grid_columnconfigure(1, weight=1)

        self.lbl_dl_icone = ctk.CTkLabel(
            topo_dl,
            text="⬇",
            font=("Segoe UI", 16, "bold"),
            text_color=COR_ROMSGAMES_MINT,
            width=28,
        )
        self.lbl_dl_icone.grid(row=0, column=0, padx=(0, 8))

        tit_box = ctk.CTkFrame(topo_dl, fg_color="transparent")
        tit_box.grid(row=0, column=1, sticky="w")

        self.lbl_dl_titulo = ctk.CTkLabel(
            tit_box,
            text="Iniciando download...",
            font=("Segoe UI", 12, "bold"),
            text_color=COR_TEXTO,
        )
        self.lbl_dl_titulo.pack(side="left", padx=(0, 8))

        self.pill_dl_estado = ctk.CTkLabel(
            tit_box,
            text="⚡ BAIXANDO",
            font=("Segoe UI", 9, "bold"),
            fg_color="#0284c7",
            text_color="white",
            corner_radius=6,
            padx=8,
            pady=1,
        )
        self.pill_dl_estado.pack(side="left", padx=(0, 8))

        self.lbl_dl_fila_count = ctk.CTkLabel(
            tit_box,
            text="",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_dl_fila_count.pack(side="left")

        ctrl_box = ctk.CTkFrame(topo_dl, fg_color="transparent")
        ctrl_box.grid(row=0, column=2, sticky="e")

        self.btn_dl_pausa = ctk.CTkButton(
            ctrl_box,
            text="⏸ Pausar",
            width=70,
            height=28,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self._acao_pausar_atual,
        )
        self.btn_dl_pausa.pack(side="left", padx=(0, 4))

        self.btn_dl_continuar = ctk.CTkButton(
            ctrl_box,
            text="▶ Continuar",
            width=80,
            height=28,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self._acao_continuar_atual,
        )
        self.btn_dl_continuar.pack(side="left", padx=(0, 4))

        self.btn_dl_cancelar = ctk.CTkButton(
            ctrl_box,
            text="✖ Cancelar",
            width=78,
            height=28,
            font=FONTE_PEQ,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="white",
            command=self._acao_cancelar_atual,
        )
        self.btn_dl_cancelar.pack(side="left", padx=(0, 6))

        self.btn_dl_pasta = ctk.CTkButton(
            ctrl_box,
            text="📁 Abrir Pasta",
            width=90,
            height=28,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_abrir_pasta,
        )
        self.btn_dl_pasta.pack(side="left", padx=(0, 6))

        self.btn_dl_toggle_fila = ctk.CTkButton(
            ctrl_box,
            text="📋 Fila",
            width=60,
            height=28,
            font=FONTE_PEQ,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self._toggle_expandir_fila,
        )
        self.btn_dl_toggle_fila.pack(side="left", padx=(0, 4))

        self.btn_dl_fechar = ctk.CTkButton(
            ctrl_box,
            text="✕",
            width=28,
            height=28,
            font=("Segoe UI", 11, "bold"),
            fg_color="transparent",
            hover_color=COR_CARD,
            text_color=COR_TEXTO_FRACO,
            command=self._ocultar_dock_download,
        )
        self.btn_dl_fechar.pack(side="left")

        self.bar_dl_principal = ctk.CTkProgressBar(
            dock,
            height=12,
            corner_radius=6,
            progress_color=COR_ROMSGAMES_MINT,
            fg_color="#1e293b",
        )
        self.bar_dl_principal.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(2, 4))
        self.bar_dl_principal.set(0.0)

        metricas = ctk.CTkFrame(dock, fg_color="transparent")
        metricas.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 8))
        metricas.grid_columnconfigure(1, weight=1)

        self.lbl_dl_pct = ctk.CTkLabel(
            metricas,
            text="0%",
            font=("Segoe UI", 11, "bold"),
            text_color=COR_ROMSGAMES_MINT,
        )
        self.lbl_dl_pct.pack(side="left", padx=(0, 10))

        self.lbl_dl_detalhes = ctk.CTkLabel(
            metricas,
            text="Conectando aos servidores do romsgames.net...",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_dl_detalhes.pack(side="left")

        self.lbl_dl_destino = ctk.CTkLabel(
            metricas,
            text=f"Destino: {self.pasta_downloads()}",
            font=FONTE_PEQ,
            text_color="#64748b",
        )
        self.lbl_dl_destino.pack(side="right")

        self.fila_scroll = ctk.CTkScrollableFrame(
            dock,
            fg_color="#090d16",
            border_width=1,
            border_color=COR_BORDA,
            corner_radius=8,
            height=100,
        )
        configurar_scroll_fluido(self.fila_scroll, velocidade=3)
        self.dock_download.grid_remove()

    def _mostrar_dock_download(self):
        self.dock_download.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 10))

    def _ocultar_dock_download(self):
        self.dock_download.grid_remove()

    def _toggle_expandir_fila(self):
        self._fila_expandida = not self._fila_expandida
        if self._fila_expandida:
            self.fila_scroll.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 8))
            self.btn_dl_toggle_fila.configure(fg_color=COR_ROMSGAMES_MINT, text_color=COR_ROMSGAMES_TEXT)
        else:
            self.fila_scroll.grid_remove()
            self.btn_dl_toggle_fila.configure(fg_color=COR_CARD, text_color=COR_TEXTO)

    def _acao_pausar_atual(self):
        with self._fila_lock:
            ativo = next((it for it in self.fila_dl if it["estado"] == "baixando"), None)
        if ativo:
            self.acao_dl_pausar(ativo["seq"])

    def _acao_continuar_atual(self):
        with self._fila_lock:
            pausado = next((it for it in self.fila_dl if it["estado"] == "pausado"), None)
        if pausado:
            self.acao_dl_continuar(pausado["seq"])

    def _acao_cancelar_atual(self):
        with self._fila_lock:
            alvo = next((it for it in self.fila_dl if it["estado"] in ("baixando", "pausado", "fila")), None)
        if alvo:
            self.acao_dl_cancelar(alvo["seq"])

    # ----------------------------------------------------- aba: catálogo
    def _montar_aba_catalogo(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.cat_scroll = ctk.CTkScrollableFrame(
            tab,
            fg_color="#070b13",
            border_width=0,
            corner_radius=10,
        )
        self.cat_scroll.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        # Ativa rolagem suave acelerada
        configurar_scroll_fluido(self.cat_scroll, velocidade=4)

        self.lbl_cat_vazio = ctk.CTkLabel(
            self.cat_scroll,
            text="Carregando catálogo de jogos PSP (2207 títulos)...",
            font=FONTE_NORMAL,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_cat_vazio.pack(padx=10, pady=24)

    # --------------------------------------------------- aba: meus jogos
    def _montar_aba_meus(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        barra = ctk.CTkFrame(tab, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        barra.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(
            barra,
            text="🔄 Atualizar Lista",
            width=140,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_atualizar_meus,
        ).grid(row=0, column=0, padx=(0, 6))

        ctk.CTkButton(
            barra,
            text="📁 Abrir Pasta de Downloads",
            width=180,
            height=34,
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            command=self.acao_abrir_pasta,
        ).grid(row=0, column=1)

        self.lbl_meus_info = ctk.CTkLabel(
            barra,
            text="—",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_meus_info.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.meus_scroll = ctk.CTkScrollableFrame(
            tab,
            fg_color="#070b13",
            border_width=1,
            border_color=COR_BORDA,
            corner_radius=8,
        )
        self.meus_scroll.grid(row=1, column=0, sticky="nsew")
        configurar_scroll_fluido(self.meus_scroll, velocidade=4)

    # --------------------------------------------- ponte thread-safe p/ UI
    def emit(self, fn):
        self._fila_ui.put(fn)

    def _processar_fila(self):
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
                    self.after(60, self._processar_fila)
            except Exception:
                pass

    # ---------------------------------------------------------------- helpers
    def logar(self, _msg: str):
        pass

    def set_status(self, texto: str, cor: str = COR_ROMSGAMES_MINT):
        self.pill_status.configure(text=f"● {texto}", text_color=cor)

    def pasta_downloads(self) -> str:
        return str(PASTA_PADRAO)

    def rodar_em_thread(self, alvo):
        threading.Thread(target=alvo, daemon=True).start()

    def _marcar_cat_todos(self, valor: bool):
        for _, var in self.cat_checks:
            var.set(valor)

    def _itens_cat_marcados(self) -> list[dict]:
        return [item for item, var in self.cat_checks if var.get()]

    # ------------------------------------------------- motor de download
    DL_COR = {
        "fila": COR_TEXTO_FRACO,
        "baixando": "#0284c7",
        "pausado": COR_AMBAR,
        "concluido": COR_ROMSGAMES_MINT,
        "erro": COR_VERMELHO,
        "cancelado": COR_TEXTO_FRACO,
    }
    DL_TXT = {
        "fila": "⏳ NA FILA",
        "baixando": "⚡ BAIXANDO",
        "pausado": "⏸ PAUSADO",
        "concluido": "✅ CONCLUÍDO",
        "erro": "❌ ERRO",
        "cancelado": "✕ CANCELADO",
    }

    def enfileirar_download(self, alvos: list[dict]):
        """Manda jogos para a fila e exibe o dock inferior imediatamente."""
        if not alvos:
            return
        pasta = self.pasta_downloads()
        resume, pular = self.var_resume.get(), self.var_pular.get()

        with self._fila_lock:
            for alvo in alvos:
                self._seq_dl += 1
                self.fila_dl.append({
                    "seq": self._seq_dl,
                    "titulo": alvo.get("nome_arquivo", "?"),
                    "nome": alvo.get("nome_arquivo", "?"),
                    "url": alvo.get("url", ""),
                    "pasta": pasta,
                    "resume": resume,
                    "pular": pular,
                    "estado": "fila",
                    "rec": 0,
                    "tot": 0,
                    "vel": 0.0,
                    "controle": ControleDownload(),
                    "widgets": {},
                    "erro": "",
                    "destino": "",
                    "nota": "",
                })

        self._mostrar_dock_download()
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
                self.emit(self._render_fila)
                self._baixar_item(prox)
        finally:
            self._worker_dl_rodando = False
            self.emit(self._render_fila)
            self.emit(self._pos_download)

    def _baixar_item(self, item: dict):
        def prog(rec, tot):
            agora = time.time()
            dt = agora - item["ult_t"]
            if dt >= 0.35:
                item["vel"] = (rec - item["ult_rec"]) / dt if dt > 0 else 0.0
                item["ult_t"] = agora
                item["ult_rec"] = rec
            item["rec"] = rec
            item["tot"] = tot or 0
            if agora - item["ult_emit"] >= 0.25:
                item["ult_emit"] = agora
                self.emit(lambda: self._atualizar_linha_dl(item))

        def logm(_m):
            pass

        try:
            dest = baixar_inteligente(
                item["url"],
                item["pasta"],
                nome_base=item["nome"],
                termos=[item["titulo"]],
                extensoes=[],
                timeout=120,
                callback_progress=prog,
                callback_log=logm,
                controle=item["controle"],
                permitir_resume=item["resume"],
                pular_existentes=item["pular"],
            )
            item.update(estado="concluido", destino=str(dest))
        except DownloadJaExiste as e:
            item.update(estado="concluido", destino=str(e.destino), nota="já existia")
        except DownloadCancelado:
            item["estado"] = "cancelado"
        except Exception as e:
            item.update(estado="erro", erro=str(e)[:200])

        self.emit(self._render_fila)
        self.emit(self._pos_download)

    def acao_dl_pausar(self, seq: int):
        it = self._achar_dl(seq)
        if it and it["estado"] == "baixando":
            it["controle"].pausar()
            it["estado"] = "pausado"
            self._render_fila()

    def acao_dl_continuar(self, seq: int):
        it = self._achar_dl(seq)
        if it and it["estado"] == "pausado":
            it["controle"].continuar()
            it["estado"] = "baixando"
            self._render_fila()

    def acao_dl_cancelar(self, seq: int):
        it = self._achar_dl(seq)
        if it is None:
            return
        if it["estado"] in ("baixando", "pausado"):
            it["controle"].cancelar()
        else:
            with self._fila_lock:
                self.fila_dl = [x for x in self.fila_dl if x["seq"] != seq]
        self._render_fila()

    def _info_linha_dl(self, it: dict) -> tuple[float, str, str]:
        rec, tot, vel = it.get("rec", 0), it.get("tot", 0), it.get("vel", 0.0)
        if it.get("estado") == "concluido":
            return 1.0, "100%", "Download concluído com sucesso!" + (f" ({it['nota']})" if it.get("nota") else "")
        if tot:
            pct = rec / tot
            eta = (tot - rec) / vel if vel > 0 else -1
            txt = f"{formatar_velocidade(vel)}  •  ETA {formatar_eta(eta)}  •  {formatar_bytes(rec)} de {formatar_bytes(tot)}"
            return pct, f"{int(pct * 100)}%", txt
        if rec:
            return 0.0, "—", f"{formatar_velocidade(vel)}  •  {formatar_bytes(rec)} baixados"
        return 0.0, "0%", "Preparando conexão..."

    def _atualizar_linha_dl(self, it: dict):
        try:
            frac, pct_str, detalhes = self._info_linha_dl(it)
            self.bar_dl_principal.set(max(0.0, min(1.0, frac)))
            self.lbl_dl_pct.configure(text=pct_str)
            self.lbl_dl_detalhes.configure(text=detalhes)
        except Exception:
            pass

    def _render_fila(self):
        with self._fila_lock:
            ativos = [i for i in self.fila_dl if i["estado"] in ("baixando", "pausado", "fila")]
            ativo = next((i for i in self.fila_dl if i["estado"] == "baixando"), None)
            if not ativo:
                ativo = next((i for i in self.fila_dl if i["estado"] == "pausado"), None)
            if not ativo and self.fila_dl:
                ativo = self.fila_dl[-1]

        if not ativo and not ativos:
            return

        self._mostrar_dock_download()

        titulo = ativo["titulo"]
        if len(titulo) > 52:
            titulo = titulo[:51] + "…"
        self.lbl_dl_titulo.configure(text=titulo)

        est = ativo.get("estado", "fila")
        self.pill_dl_estado.configure(
            text=self.DL_TXT.get(est, est),
            fg_color=self.DL_COR.get(est, "#0284c7"),
        )

        n_fila = len(ativos)
        if n_fila > 1:
            self.lbl_dl_fila_count.configure(text=f"({n_fila} downloads pendentes)")
        else:
            self.lbl_dl_fila_count.configure(text="")

        if est == "baixando":
            self.btn_dl_pausa.configure(state="normal")
            self.btn_dl_continuar.configure(state="disabled")
            self.set_status("Baixando...", COR_ROMSGAMES_MINT)
            try:
                pulsar_pill(self.pill_status, True)
            except Exception:
                pass
        elif est == "pausado":
            self.btn_dl_pausa.configure(state="disabled")
            self.btn_dl_continuar.configure(state="normal")
            self.set_status("Pausado", COR_AMBAR)
            try:
                parar_pulso(self.pill_status, COR_AMBAR)
            except Exception:
                pass
        else:
            self.btn_dl_pausa.configure(state="disabled")
            self.btn_dl_continuar.configure(state="disabled")
            self.set_status("Online", COR_ROMSGAMES_MINT)
            try:
                parar_pulso(self.pill_status, COR_ROMSGAMES_MINT)
            except Exception:
                pass

        self._atualizar_linha_dl(ativo)

        if self._fila_expandida and hasattr(self, "fila_scroll"):
            for w in self.fila_scroll.winfo_children():
                w.destroy()
            for it in self.fila_dl:
                linha = ctk.CTkFrame(self.fila_scroll, fg_color="transparent")
                linha.pack(fill="x", padx=6, pady=2)
                t = it["titulo"] if len(it["titulo"]) <= 40 else it["titulo"][:39] + "…"
                ctk.CTkLabel(linha, text=t, font=FONTE_PEQ, text_color=COR_TEXTO).pack(side="left")
                e = it["estado"]
                ctk.CTkLabel(
                    linha,
                    text=self.DL_TXT.get(e, e),
                    font=("Segoe UI", 9, "bold"),
                    text_color=self.DL_COR.get(e, COR_TEXTO_FRACO),
                ).pack(side="left", padx=8)
                ctk.CTkButton(
                    linha,
                    text="✖",
                    width=24,
                    height=20,
                    fg_color=COR_VERMELHO,
                    font=("Segoe UI", 9, "bold"),
                    command=lambda s=it["seq"]: self.acao_dl_cancelar(s),
                ).pack(side="right")

    def _pos_download(self):
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
            self.set_status(f"Catálogo pronto ({len(self.catalogo)} jogos)", COR_ROMSGAMES_MINT)
        else:
            self.lbl_cat_info.configure(text="❌ catalogo-psp.json não encontrado", text_color=COR_VERMELHO)

    def _jogos_visiveis(self) -> list[dict]:
        busca = self.ent_busca_cat.get().strip() if hasattr(self, "ent_busca_cat") else ""
        visiveis = filtrar_catalogo(self.catalogo, busca)
        if self.var_ocultar_baixados.get():
            visiveis = [j for j in visiveis if not j.get("ja_baixado")]
        return visiveis

    def _busca_cat_mudou(self):
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
        self._thumb_job += 1
        visiveis = self._jogos_visiveis()
        n_baixados = sum(1 for j in self.catalogo if j.get("ja_baixado"))
        self.lbl_cat_info.configure(
            text=f"{len(visiveis)}/{len(self.catalogo)} jogos • {n_baixados} baixados",
        )
        total = len(visiveis)
        paginas = max(1, (total + CAT_POR_PAGINA - 1) // CAT_POR_PAGINA)
        self.cat_pagina = max(0, min(self.cat_pagina, paginas - 1))
        ini = self.cat_pagina * CAT_POR_PAGINA

        if hasattr(self, "lbl_pag"):
            fim = min(ini + CAT_POR_PAGINA, total)
            self.lbl_pag.configure(text=f"Página {self.cat_pagina + 1}/{paginas} ({ini + 1 if total else 0}–{fim})")
            self.btn_pag_ant.configure(state="normal" if self.cat_pagina > 0 else "disabled")
            self.btn_pag_prox.configure(state="normal" if self.cat_pagina < paginas - 1 else "disabled")

        if not self.catalogo:
            ctk.CTkLabel(
                self.cat_scroll,
                text="❌ catalogo-psp.json não encontrado ao lado do programa.",
                font=FONTE_NORMAL,
                text_color=COR_VERMELHO,
            ).pack(padx=10, pady=24)
            return

        if not visiveis:
            ctk.CTkLabel(
                self.cat_scroll,
                text="Nenhum jogo encontrado com esse termo.",
                font=FONTE_NORMAL,
                text_color=COR_AMBAR,
            ).pack(padx=10, pady=24)
            return

        mostrar = visiveis[ini:ini + CAT_POR_PAGINA]
        itens_thumb = self._grade_jogos(self.cat_scroll, mostrar, colunas=5)
        # Processamento 100% assíncrono em background
        self._carregar_thumbs_job(self._thumb_job, itens_thumb, buscar_web=True)

    # =====================================================================
    # GRADE E CARTÕES DE JOGOS OTIMIZADOS
    # =====================================================================
    def _grade_jogos(self, pai_scroll, jogos: list[dict], colunas: int = 5) -> list[tuple[dict, ctk.CTkLabel]]:
        """Grade leve e responsiva com encaminhamento direto de rolagem."""
        grade = ctk.CTkFrame(pai_scroll, fg_color="transparent")
        grade.pack(fill="x", padx=6, pady=4)
        for c in range(colunas):
            grade.grid_columnconfigure(c, weight=1)

        pares_thumb = []
        for i, jogo in enumerate(jogos):
            card, thumb = self._cartao_jogo(pai_scroll, grade, jogo)
            card.grid(
                row=i // colunas,
                column=i % colunas,
                padx=8,
                pady=8,
                sticky="nsew",
            )
            if jogo.get("capa"):
                pares_thumb.append((jogo, thumb))
        return pares_thumb

    def _cartao_jogo(self, pai_scroll, grade, jogo: dict) -> tuple[ctk.CTkFrame, ctk.CTkLabel]:
        """Cartão ultra fluído com suporte total à roda do mouse sem travamento."""
        card = ctk.CTkFrame(
            grade,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            corner_radius=14,
        )

        def _forward_wheel(event):
            try:
                canvas = getattr(pai_scroll, "_parent_canvas", None)
                if canvas:
                    delta = -1 * int(event.delta / 120) * 4
                    canvas.yview_scroll(delta, "units")
                    return "break"
            except Exception:
                pass

        card.bind("<MouseWheel>", _forward_wheel, add="+")

        # Capa vertical estilo pôster RomsGames (175x238)
        thumb = ctk.CTkLabel(
            card,
            text="🎮\nPSP",
            width=175,
            height=238,
            fg_color="#060911",
            corner_radius=10,
            font=("Segoe UI", 24, "bold"),
            text_color="#334155",
        )
        thumb.pack(padx=10, pady=(10, 6))
        thumb.bind("<MouseWheel>", _forward_wheel, add="+")

        # Selos de Avaliação e Plataforma combinados (sem frame aninhado extra)
        lbl_meta = ctk.CTkLabel(
            card,
            text="★ 4.8  •  PSP",
            font=("Segoe UI", 10, "bold"),
            text_color=COR_AMBAR,
        )
        lbl_meta.pack(padx=10, pady=(0, 2))
        lbl_meta.bind("<MouseWheel>", _forward_wheel, add="+")

        # Título formatado com bom contraste e quebra elegante
        titulo = jogo.get("titulo", "?")
        t_curto = titulo if len(titulo) <= 42 else titulo[:41] + "…"
        lbl_tit = ctk.CTkLabel(
            card,
            text=t_curto,
            font=("Segoe UI", 11, "bold"),
            text_color=COR_TEXTO,
            wraplength=170,
            height=34,
            justify="center",
        )
        lbl_tit.pack(padx=8, pady=(0, 4))
        lbl_tit.bind("<MouseWheel>", _forward_wheel, add="+")

        # Badge verde elegante se já baixado
        if jogo.get("ja_baixado"):
            ctk.CTkLabel(
                card,
                text="✓ BAIXADO",
                font=("Segoe UI", 9, "bold"),
                fg_color=COR_VERDE_ESC,
                text_color=COR_VERDE_TXT,
                corner_radius=6,
                padx=8,
                pady=1,
            ).pack(pady=(0, 4))

        # Ações do Card: Seleção + Detalhes (👁) + Botão Oficial "Save Game"
        acoes = ctk.CTkFrame(card, fg_color="transparent")
        acoes.pack(fill="x", padx=10, pady=(2, 10))

        var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            acoes,
            variable=var,
            corner_radius=4,
            text="",
            width=20,
            checkbox_height=18,
            checkbox_width=18,
            border_color=COR_BORDA,
            hover_color=COR_CARD_HOVER,
        ).pack(side="left", padx=(0, 4))
        self.cat_checks.append((jogo, var))

        btn_ver = ctk.CTkButton(
            acoes,
            text="👁",
            width=32,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            hover_color=COR_CARD_HOVER,
            font=("Segoe UI", 12),
            command=lambda j=jogo: self.ver_detalhe(j),
        )
        btn_ver.pack(side="left", padx=(0, 6))

        btn_save = ctk.CTkButton(
            acoes,
            text="⬇ Save Game",
            height=34,
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            font=FONTE_BOTAO_MINT,
            corner_radius=17,
            command=lambda j=jogo: self.acao_baixar_um(j),
        )
        btn_save.pack(side="left", fill="x", expand=True)

        hover_card(card, borda_normal=COR_BORDA, borda_hover=COR_ROMSGAMES_MINT)
        return card, thumb

    # --------------------------------------------------- carregamento 100% assíncrono de capas
    def _carregar_thumbs_job(self, job: int, pares_thumb: list[tuple[dict, ctk.CTkLabel]], buscar_web: bool = True):
        """Processa decodificação e resize das capas 100% na thread de fundo."""
        if not pares_thumb:
            return

        def bg():
            size = (175, 238)
            for jogo, label in pares_thumb:
                if job != self._thumb_job:
                    return
                capa = jogo.get("capa", "")
                if not capa:
                    continue
                chave = (capa, size)

                pil_fundo = self._pil_cache.get(chave)
                if pil_fundo is None:
                    if buscar_web:
                        try:
                            baixar_capa(capa, pasta_base())
                        except Exception:
                            pass
                    local = caminho_capa_local(capa)
                    if local is None:
                        continue
                    try:
                        base = Image.open(str(local)).convert("RGB")
                        w, h = size
                        base.thumbnail((w, h), Image.LANCZOS)
                        pil_fundo = Image.new("RGB", (w, h), (6, 9, 17))
                        pil_fundo.paste(base, ((w - base.width) // 2, (h - base.height) // 2))
                        self._pil_cache[chave] = pil_fundo
                    except Exception:
                        continue

                if job != self._thumb_job:
                    return

                # Entrega de alta velocidade para a thread principal (sem travar)
                self.emit(lambda lbl=label, ch=chave, sz=size, img=pil_fundo: self._aplicar_uma_thumb(lbl, ch, sz, img))

        threading.Thread(target=bg, daemon=True).start()

    def _aplicar_uma_thumb(self, label, chave: tuple, size: tuple, pil_fundo: Image.Image):
        try:
            if not label.winfo_exists():
                return
            if chave not in self._thumbs:
                self._thumbs[chave] = ctk.CTkImage(light_image=pil_fundo, dark_image=pil_fundo, size=size)
            label.configure(text="", image=self._thumbs[chave])
        except Exception:
            pass

    def _alvo_de_jogo(self, jogo: dict) -> dict:
        return {
            "texto": jogo.get("titulo", ""),
            "nome_arquivo": jogo.get("titulo", ""),
            "url": jogo.get("url", ""),
            "extensao_url": "",
        }

    def acao_baixar_catalogo(self):
        marcados = self._itens_cat_marcados()
        if not marcados:
            messagebox.showinfo("Catálogo", "Selecione ao menos um jogo marcando a caixa de seleção.")
            return
        alvos = []
        for jogo in marcados:
            if jogo.get("ja_baixado") and self.var_pular.get():
                continue
            alvos.append(self._alvo_de_jogo(jogo))
        if not alvos:
            messagebox.showinfo("Catálogo", "Todos os jogos marcados já foram baixados. ✔")
            return
        self.enfileirar_download(alvos)

    def acao_baixar_um(self, jogo: dict):
        if jogo.get("ja_baixado") and self.var_pular.get():
            if not messagebox.askyesno(
                "Já Baixado",
                f"O jogo '{jogo.get('titulo')}' já foi baixado anteriormente.\nDeseja baixar novamente?",
            ):
                return
        self.enfileirar_download([self._alvo_de_jogo(jogo)])

    # =====================================================================
    # MODAL DE DETALHES DO JOGO (CLONE ROMSGAMES)
    # =====================================================================
    def ver_detalhe(self, jogo: dict):
        url = (jogo.get("url") or "").strip()
        if not url:
            return
        modal = ctk.CTkToplevel(self)
        modal.title((jogo.get("titulo") or "Jogo")[:60])
        modal.geometry("720x640")
        modal.minsize(620, 540)
        modal.configure(fg_color=COR_FUNDO)
        modal._imgs = []
        try:
            modal.transient(self)
            fade_in_modal(modal, largura_final=720, altura_final=640)
        except Exception:
            pass

        ctk.CTkLabel(
            modal,
            text="⏳ Conectando à página do romsgames.net...",
            font=FONTE_NORMAL,
            text_color=COR_TEXTO_FRACO,
        ).pack(expand=True)
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
            ctk.CTkLabel(
                modal,
                text=f"❌ Falha ao carregar dados do jogo:\n{erro}",
                font=FONTE_NORMAL,
                text_color=COR_AMBAR,
            ).pack(expand=True)
            ctk.CTkButton(modal, text="Fechar", width=120, command=modal.destroy).pack(pady=14)
        except Exception:
            pass

    def _preencher_detalhe(self, modal, d: dict, rel: list, capa_local):
        try:
            if not modal.winfo_exists():
                return
            for w in modal.winfo_children():
                w.destroy()
        except Exception:
            return

        corpo = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=12, pady=12)
        configurar_scroll_fluido(corpo, velocidade=4)

        ctk.CTkLabel(
            corpo,
            text="🎮 Roms Games › ROMs › Playstation Portable",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        ).pack(anchor="w", padx=6, pady=(0, 8))

        topo = ctk.CTkFrame(corpo, fg_color=COR_CARD, border_width=1, border_color=COR_BORDA, corner_radius=14)
        topo.pack(fill="x", padx=4, pady=(0, 10))

        miolo = ctk.CTkFrame(topo, fg_color="transparent")
        miolo.pack(fill="x", padx=16, pady=16)

        img_lbl = ctk.CTkLabel(
            miolo,
            text="🎮",
            width=200,
            height=270,
            fg_color="#060911",
            corner_radius=10,
            font=("Segoe UI", 48),
        )
        img_lbl.pack(side="left", padx=(0, 18))

        if capa_local:
            try:
                base = Image.open(str(capa_local)).convert("RGB")
                base.thumbnail((200, 270), Image.LANCZOS)
                fundo = Image.new("RGB", (200, 270), (6, 9, 17))
                fundo.paste(base, ((200 - base.width) // 2, (270 - base.height) // 2))
                foto = ctk.CTkImage(light_image=fundo, dark_image=fundo, size=(200, 270))
                modal._imgs.append(foto)
                img_lbl.configure(text="", image=foto)
            except Exception:
                pass

        info = ctk.CTkFrame(miolo, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            info,
            text=d.get("titulo") or "?",
            font=("Segoe UI", 18, "bold"),
            text_color=COR_TEXTO,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        tag_row = ctk.CTkFrame(info, fg_color="transparent")
        tag_row.pack(anchor="w", pady=(2, 8))

        ctk.CTkLabel(
            tag_row,
            text="★ 4.8 / 5.0 (18.6k votos)",
            font=("Segoe UI", 11, "bold"),
            text_color=COR_AMBAR,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            tag_row,
            text="Playstation Portable ROM",
            font=FONTE_PEQ,
            fg_color="#1e293b",
            text_color="#94a3b8",
            corner_radius=6,
            padx=8,
            pady=2,
        ).pack(side="left")

        meta_items = [
            ("Região", d.get("regiao") or "United States (English)"),
            ("Tamanho Estimado", d.get("tamanho") or "~950 MB"),
            ("Compatibilidade", "PPSSPP / Console PSP Oficial"),
        ]
        for rot, val in meta_items:
            linha_meta = ctk.CTkFrame(info, fg_color="transparent")
            linha_meta.pack(anchor="w", pady=1)
            ctk.CTkLabel(linha_meta, text=f"{rot}:", font=("Segoe UI", 10, "bold"), text_color=COR_TEXTO_FRACO).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(linha_meta, text=val, font=FONTE_PEQ, text_color=COR_TEXTO).pack(side="left")

        btn_modal_save = ctk.CTkButton(
            info,
            text="⬇  SAVE GAME",
            height=46,
            font=("Segoe UI", 13, "bold"),
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            corner_radius=23,
            command=lambda: (
                modal.destroy(),
                self.acao_baixar_um({
                    "titulo": d.get("titulo", ""),
                    "url": d.get("url", ""),
                    "capa": d.get("capa", ""),
                }),
            ),
        )
        btn_modal_save.pack(fill="x", pady=(14, 6))

        b_sub = ctk.CTkFrame(info, fg_color="transparent")
        b_sub.pack(fill="x")

        ctk.CTkButton(
            b_sub,
            text="🌐 Abrir no Navegador",
            height=32,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=lambda: (
                modal.destroy(),
                self.seg_abas.set("🌐 Navegador"),
                self._aba_mudou_seg("🌐 Navegador"),
                self.navegar_para(d.get("url", "")),
            ),
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(
            b_sub,
            text="Fechar",
            height=32,
            width=80,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=modal.destroy,
        ).pack(side="left")

        desc_card = ctk.CTkFrame(corpo, fg_color=COR_CARD, border_width=1, border_color=COR_BORDA, corner_radius=12)
        desc_card.pack(fill="x", padx=4, pady=6)

        ctk.CTkLabel(
            desc_card,
            text="📝 Sobre o jogo (Overview)",
            font=("Segoe UI", 12, "bold"),
            text_color=COR_TEXTO,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        txt = ctk.CTkTextbox(
            desc_card,
            font=("Segoe UI", 11),
            fg_color="#090d16",
            border_width=0,
            corner_radius=8,
            height=90,
        )
        txt.pack(fill="x", padx=14, pady=(0, 12))
        txt.insert("1.0", d.get("descricao") or f"{d.get('titulo')} ROM download disponível para jogar no emulador PPSSPP ou no console PSP original com máxima qualidade.")
        txt.configure(state="disabled")

        if rel:
            ctk.CTkLabel(
                corpo,
                text="🎮 Jogos Relacionados:",
                font=("Segoe UI", 12, "bold"),
                text_color=COR_TEXTO,
            ).pack(anchor="w", padx=6, pady=(8, 4))

            for r in rel[:5]:
                nome = r.get("titulo", "?")
                ctk.CTkButton(
                    corpo,
                    text=f"👁  {nome}",
                    height=30,
                    anchor="w",
                    fg_color=COR_CARD,
                    border_width=1,
                    border_color=COR_BORDA,
                    text_color=COR_TEXTO,
                    font=FONTE_PEQ,
                    command=lambda j=r: (modal.destroy(), self.ver_detalhe(j)),
                ).pack(fill="x", padx=4, pady=2)

    # --------------------------------------------------- aba: navegador
    def _montar_aba_navegador(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        nav = ctk.CTkFrame(tab, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        nav.grid_columnconfigure(4, weight=1)

        self.btn_nav_voltar = ctk.CTkButton(
            nav,
            text="◀",
            width=38,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_nav_voltar,
            state="disabled",
        )
        self.btn_nav_voltar.grid(row=0, column=0, padx=(0, 4))

        self.btn_nav_avancar = ctk.CTkButton(
            nav,
            text="▶",
            width=38,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_nav_avancar,
            state="disabled",
        )
        self.btn_nav_avancar.grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(
            nav,
            text="⟳",
            width=38,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_nav_recarregar,
        ).grid(row=0, column=2, padx=(0, 4))

        ctk.CTkButton(
            nav,
            text="🏠",
            width=38,
            height=34,
            fg_color=COR_CARD,
            border_width=1,
            border_color=COR_BORDA,
            command=self.acao_nav_home,
        ).grid(row=0, column=3, padx=(0, 6))

        self.ent_nav_url = ctk.CTkEntry(
            nav,
            font=FONTE_NORMAL,
            height=34,
            placeholder_text="Endereço da página... (Enter = Ir)",
            fg_color="#090d16",
            border_color=COR_BORDA,
            corner_radius=17,
        )
        self.ent_nav_url.grid(row=0, column=4, sticky="ew", padx=(0, 6))
        self.ent_nav_url.bind("<Return>", lambda _e: self.acao_nav_ir())
        self.ent_nav_url.insert(0, SITE_INICIAL)

        ctk.CTkButton(
            nav,
            text="Ir",
            width=65,
            height=34,
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            font=FONTE_BOTAO_MINT,
            corner_radius=17,
            command=self.acao_nav_ir,
        ).grid(row=0, column=5)

        self.lbl_nav_info = ctk.CTkLabel(
            tab,
            text="Navegue pelas páginas oficiais do romsgames.net diretamente aqui dentro.",
            font=FONTE_PEQ,
            text_color=COR_TEXTO_FRACO,
        )
        self.lbl_nav_info.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.nav_scroll = ctk.CTkScrollableFrame(
            tab,
            fg_color="#070b13",
            border_width=1,
            border_color=COR_BORDA,
            corner_radius=8,
        )
        self.nav_scroll.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        configurar_scroll_fluido(self.nav_scroll, velocidade=4)

    def _normalizar_endereco(self, texto: str) -> str:
        t = (texto or "").strip()
        if not t:
            raise ValueError("Digite o endereço da página.")
        if "://" not in t:
            t = "https://" + t.lstrip("/")
        if urlparse(t).scheme.lower() not in ("http", "https"):
            raise ValueError("Endereço inválido.")
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
        if self.nav_ocupado:
            return
        if registrar and self.nav_atual and self.nav_atual != url:
            self.hist_voltar.append(self.nav_atual)
            self.hist_avancar.clear()
        self.nav_ocupado = True
        self._atualizar_botoes_nav()
        self.lbl_nav_info.configure(text="⏳ Carregando página...", text_color=COR_AZUL)
        for w in self.nav_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.nav_scroll,
            text="⏳ Carregando conteúdo do romsgames.net...",
            font=FONTE_NORMAL,
            text_color=COR_TEXTO_FRACO,
        ).pack(padx=10, pady=24)
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
        ctk.CTkLabel(
            self.nav_scroll,
            text="Não foi possível abrir a página.\nVerifique a conexão e tente novamente.",
            font=FONTE_NORMAL,
            text_color=COR_AMBAR,
        ).pack(padx=10, pady=24)

    def _atualizar_botoes_nav(self):
        base = "disabled" if self.nav_ocupado else "normal"
        self.btn_nav_voltar.configure(state=base if self.hist_voltar else "disabled")
        self.btn_nav_avancar.configure(state=base if self.hist_avancar else "disabled")

    def _render_nav(self, pagina: dict):
        self.nav_ocupado = False
        self.nav_checks = []
        self._thumb_job += 1
        self.nav_atual = pagina.get("url_final", "")
        for w in self.nav_scroll.winfo_children():
            w.destroy()
        self.ent_nav_url.delete(0, "end")
        self.ent_nav_url.insert(0, self.nav_atual)
        self._atualizar_botoes_nav()
        tipo = pagina.get("tipo")

        if tipo == "lista":
            jogos = pagina["jogos"]
            self.lbl_nav_info.configure(text=f"{len(jogos)} jogos encontrados nesta página", text_color=COR_TEXTO_FRACO)
            pares = self._grade_jogos(self.nav_scroll, jogos, colunas=5)
            self._carregar_thumbs_job(self._thumb_job, pares, buscar_web=True)
        elif tipo == "jogo":
            d = pagina["detalhe"]
            self.lbl_nav_info.configure(text="Página do jogo — Clique em Save Game para baixar", text_color=COR_ROMSGAMES_MINT)
            self._cabecalho_nav_jogo(d)
        else:
            links = pagina.get("links") or []
            self.lbl_nav_info.configure(text=f"Página com {len(links)} links", text_color=COR_TEXTO_FRACO)
            for link in links[:60]:
                linha = ctk.CTkFrame(self.nav_scroll, fg_color="transparent")
                linha.pack(fill="x", padx=6, pady=2)
                txt = link["texto"] if len(link["texto"]) <= 70 else link["texto"][:69] + "…"
                ctk.CTkLabel(linha, text="🔗 " + txt, font=FONTE_PEQ, text_color=COR_TEXTO).pack(side="left")
                ctk.CTkButton(
                    linha,
                    text="Abrir",
                    width=65,
                    height=26,
                    fg_color=COR_CARD,
                    border_width=1,
                    border_color=COR_BORDA,
                    command=lambda u=link["url"]: self.navegar_para(u),
                ).pack(side="right")

    def _cabecalho_nav_jogo(self, d: dict):
        cartao = ctk.CTkFrame(self.nav_scroll, fg_color=COR_CARD, border_width=1, border_color=COR_BORDA, corner_radius=14)
        cartao.pack(fill="x", padx=8, pady=8)
        topo = ctk.CTkFrame(cartao, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=16)

        thumb = ctk.CTkLabel(topo, text="🎮", width=120, height=160, fg_color="#060911", corner_radius=10, font=("Segoe UI", 36))
        thumb.pack(side="left", padx=(0, 16))
        if d.get("capa"):
            pseudo = {"capa": d["capa"]}
            self._carregar_thumbs_job(self._thumb_job, [(pseudo, thumb)], buscar_web=True)

        infos = ctk.CTkFrame(topo, fg_color="transparent")
        infos.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(infos, text=d.get("titulo") or "?", font=("Segoe UI", 16, "bold"), text_color=COR_TEXTO).pack(anchor="w")
        ctk.CTkLabel(infos, text="★ 4.8  •  Playstation Portable ROM", font=FONTE_PEQ, text_color=COR_AMBAR).pack(anchor="w", pady=(2, 6))

        ctk.CTkButton(
            infos,
            text="⬇  SAVE GAME",
            height=40,
            font=FONTE_BOTAO_MINT,
            fg_color=COR_ROMSGAMES_MINT,
            text_color=COR_ROMSGAMES_TEXT,
            hover_color=COR_ROMSGAMES_HOVER,
            corner_radius=20,
            command=lambda: self.acao_baixar_um({
                "titulo": d.get("titulo", "?"),
                "url": d.get("url") or (self.nav_atual or ""),
                "capa": d.get("capa", ""),
            }),
        ).pack(anchor="w")

    # ------------------------------------------------------ meus jogos
    def acao_atualizar_meus(self):
        if not hasattr(self, "meus_scroll"):
            return
        for w in self.meus_scroll.winfo_children():
            w.destroy()
        try:
            self.meus_jogos = escanear_baixados(self.pasta_downloads())
        except Exception:
            return

        finais = [m for m in self.meus_jogos if not m["incompleto"]]
        parts = [m for m in self.meus_jogos if m["incompleto"]]
        total_b = sum(m["bytes"] for m in finais)
        self.lbl_meus_info.configure(
            text=f"{len(finais)} concluídos • {formatar_bytes(total_b)} • {len(parts)} incompletos"
        )

        if not self.meus_jogos:
            ctk.CTkLabel(
                self.meus_scroll,
                text="Nenhum jogo baixado ainda na pasta downloads.",
                font=FONTE_NORMAL,
                text_color=COR_TEXTO_FRACO,
            ).pack(padx=10, pady=24)
            return

        for m in finais:
            linha = ctk.CTkFrame(self.meus_scroll, fg_color=COR_CARD, border_width=1, border_color=COR_BORDA, corner_radius=8)
            linha.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(linha, text="✅", font=FONTE_NORMAL).pack(side="left", padx=10)
            nome = m["arquivo"]
            ctk.CTkLabel(linha, text=nome, font=FONTE_NORMAL, text_color=COR_TEXTO).pack(side="left")
            ctk.CTkLabel(linha, text=f"{formatar_bytes(m['bytes'])} • {m['modificado_em']}", font=FONTE_PEQ, text_color=COR_TEXTO_FRACO).pack(side="right", padx=10)

        for m in parts:
            linha = ctk.CTkFrame(self.meus_scroll, fg_color=COR_CARD, border_width=1, border_color=COR_BORDA, corner_radius=8)
            linha.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(linha, text="⏳", font=FONTE_NORMAL).pack(side="left", padx=10)
            nome = m["arquivo"]
            ctk.CTkLabel(linha, text=nome, font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(side="left")
            ctk.CTkLabel(linha, text=f"{formatar_bytes(m['bytes'])} • Incompleto (resume disponível)", font=FONTE_PEQ, text_color=COR_AMBAR).pack(side="right", padx=10)

    def acao_abrir_pasta(self):
        pasta = self.pasta_downloads()
        Path(pasta).mkdir(parents=True, exist_ok=True)
        try:
            abrir_pasta(pasta)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta: {e}")


if __name__ == "__main__":
    App().mainloop()
