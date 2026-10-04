"""Baixador PSP — interface dark moderna (customtkinter).

Abas: ⬇ Baixar | 🗂 Catálogo do site | 💾 Meus jogos.
Requer: pip install -r requirements.txt  (customtkinter incluso)
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from downloader import (
    ControleDownload,
    DownloadCancelado,
    DownloadJaExiste,
    analisar_site,
    anotar_catalogo,
    baixar_capa,
    baixar_inteligente,
    carregar_catalogo,
    carregar_catalogo_cache,
    carregar_termos_de_arquivo,
    detalhes_jogo,
    escanear_baixados,
    filtrar_catalogo,
    filtrar_por_nomes,
    pular_ja_baixados,
    salvar_catalogo_cache,
)

URL_PADRAO = "https://www.romsgames.net/roms/playstation-portable/"
LISTA_TESTE = """God of War: Ghost of Sparta
Grand Theft Auto: Vice City Stories
God of War: Chains of Olympus
Naruto Shippuden: Ultimate Ninja Impact
Need for Speed: Most Wanted - 5-1-0
Dragon Ball Z - Shin Budokai 2
Assassin's Creed: Bloodlines
Pro Evolution Soccer 2014
Mortal Kombat: Unchained
WWE SmackDown Vs. RAW 2010 Featuring ECW
Tekken 6
FIFA Street 2
Grand Theft Auto: Liberty City Stories
Gran Turismo
Dante's Inferno"""

PAGINAS_OPCOES = {"1 página (~36 jogos)": 1, "2 páginas (~72)": 2,
                  "3 páginas (~108)": 3, "5 páginas (~180)": 5,
                  "10 páginas (~360)": 10, "Tudo (~2200, lento)": 0}

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


def formatar_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


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
        self.corpo.pack(fill="both", expand=True)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Baixador PSP — dark")
        self.geometry("1020x860")
        self.minsize(920, 740)
        self.configure(fg_color=COR_FUNDO)

        self.links_analisados: list[dict] = []
        self.links_filtrados: list[dict] = []
        self.checks: list[tuple[dict, ctk.BooleanVar]] = []  # encontrados + marcado?
        self.catalogo: list[dict] = []  # todos os jogos do site
        self.cat_checks: list[tuple[dict, ctk.BooleanVar]] = []  # visíveis + marcado?
        self.meus_jogos: list[dict] = []
        self._thumbs: dict[str, ctk.CTkImage] = {}  # url capa -> imagem (evita GC)
        self._thumb_job = 0  # invalida loaders de capa de renderizações antigas
        self._fila_ui: queue.Queue = queue.Queue()  # workers pedem updates; principal executa
        self.baixando = False
        self.carregando_cat = False
        self.controle = ControleDownload()
        self.var_resume = ctk.BooleanVar(value=True)
        self.var_pular = ctk.BooleanVar(value=True)
        self.var_paginas = ctk.StringVar(value="3 páginas (~108)")

        self._montar_tela()
        self.after(120, self._processar_fila)  # drena pedidos das threads (único after recorrente)
        self.logar("Pronto. Aba Catálogo: carregue os jogos do site e escolha o que baixar.")
        self.logar("Aba Meus jogos: veja o que já foi baixado (evita repetidos).")
        self._carregar_cache_inicial()

    # ------------------------------------------------------------------ tela
    def _montar_tela(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ---- cabeçalho ----
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        topo.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(topo, text="⬇ Baixador PSP", font=FONTE_TITULO,
                     text_color="white").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(topo, text="catálogo do site • escolha os jogos • baixe — com resume e anti-duplicado",
                     font=FONTE_SUB, text_color=COR_TEXTO_FRACO).grid(row=1, column=0, sticky="w")
        self.pill_status = ctk.CTkLabel(topo, text="● parado", font=("Segoe UI", 11, "bold"),
                                        fg_color=COR_CARD, corner_radius=999, padx=12, pady=4,
                                        text_color=COR_TEXTO_FRACO)
        self.pill_status.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))

        # ---- origem / destino (compartilhado pelas abas) ----
        cfg = Cartao(self, titulo="🌐 Origem e destino")
        cfg.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        corpo = cfg.corpo
        corpo.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(corpo, text="Site", font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).grid(
            row=0, column=0, sticky="w", padx=14, pady=(4, 2))
        self.ent_url = ctk.CTkEntry(corpo, font=FONTE_NORMAL, height=36,
                                    fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_url.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(4, 2))
        self.ent_url.insert(0, URL_PADRAO)
        ctk.CTkButton(corpo, text="Analisar", width=110, height=36,
                      command=self.acao_analisar).grid(row=0, column=2, padx=(0, 14), pady=(4, 2))

        ctk.CTkLabel(corpo, text="Salvar em", font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).grid(
            row=1, column=0, sticky="w", padx=14, pady=2)
        self.ent_pasta = ctk.CTkEntry(corpo, font=FONTE_NORMAL, height=36,
                                      fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_pasta.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.ent_pasta.insert(0, str(PASTA_PADRAO))
        ctk.CTkButton(corpo, text="📁", width=48, height=36, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_escolher_pasta).grid(row=1, column=2, padx=(0, 14), pady=2)

        ctk.CTkLabel(corpo, text="Extensões", font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).grid(
            row=2, column=0, sticky="w", padx=14, pady=(2, 4))
        self.ent_ext = ctk.CTkEntry(corpo, font=FONTE_NORMAL, height=36, width=200,
                                    placeholder_text="vazio = todas (.zip, .iso...)",
                                    fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_ext.grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(2, 4))

        opt = ctk.CTkFrame(corpo, fg_color="transparent")
        opt.grid(row=2, column=2, sticky="e", padx=(0, 14), pady=(2, 4))
        ctk.CTkSwitch(opt, text="Resume", variable=self.var_resume,
                      font=FONTE_NORMAL).pack(side="left", padx=(0, 12))
        ctk.CTkSwitch(opt, text="Pular já baixados", variable=self.var_pular,
                      font=FONTE_NORMAL).pack(side="left")

        # ---- abas ----
        self.tabs = ctk.CTkTabview(self, fg_color="transparent",
                                   segmented_button_fg_color=COR_CARD,
                                   segmented_button_selected_color=COR_VERDE,
                                   text_color="white")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        self.tab_baixar = self.tabs.add("⬇ Baixar")
        self.tab_catalogo = self.tabs.add("🗂 Catálogo")
        self.tab_meus = self.tabs.add("💾 Meus jogos")
        self._montar_aba_baixar(self.tab_baixar)
        self._montar_aba_catalogo(self.tab_catalogo)
        self._montar_aba_meus(self.tab_meus)

        # ---- progresso + log (compartilhados) ----
        base = Cartao(self, titulo="📊 Progresso")
        base.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.lbl_arquivo = ctk.CTkLabel(base, text="aguardando…", font=FONTE_NORMAL,
                                        text_color=COR_TEXTO_FRACO)
        self.lbl_arquivo.pack(anchor="w", padx=14)
        self.bar_arquivo = ctk.CTkProgressBar(base, height=12, corner_radius=999,
                                              progress_color=COR_VERDE)
        self.bar_arquivo.pack(fill="x", padx=14, pady=(4, 2))
        self.bar_arquivo.set(0)
        self.bar_total = ctk.CTkProgressBar(base, height=8, corner_radius=999,
                                            progress_color=COR_AZUL)
        self.bar_total.pack(fill="x", padx=14, pady=(2, 12))
        self.bar_total.set(0)

        card_log = Cartao(self, titulo="🧾 Log")
        card_log.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 14))
        self.log = ctk.CTkTextbox(card_log, font=FONTE_MONO_PEQ, height=110,
                                  fg_color="#0b0d11", text_color="#d1d5db",
                                  border_width=0, corner_radius=8)
        self.log.pack(fill="x", padx=14, pady=(2, 14))
        self.log.configure(state="disabled")

    # ------------------------------------------------------- aba: baixar
    def _montar_aba_baixar(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        self.btn_teste = ctk.CTkButton(
            tab, text="⬇  BAIXAR LISTA DE TESTE  —  1 clique",
            font=("Segoe UI", 14, "bold"), height=52, corner_radius=12,
            fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
            command=self.acao_teste_unico,
        )
        self.btn_teste.grid(row=0, column=0, sticky="ew", pady=(4, 0))

        faixa = ctk.CTkFrame(tab, fg_color="transparent")
        faixa.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.btn_lista = ctk.CTkButton(faixa, text="📄 lista.txt", width=120, fg_color=COR_CARD,
                                       border_width=1, border_color=COR_BORDA,
                                       command=self.acao_carregar_lista)
        self.btn_lista.grid(row=0, column=0, padx=(0, 6))
        self.btn_buscar = ctk.CTkButton(faixa, text="🔍 Só buscar", width=120, fg_color=COR_CARD,
                                        border_width=1, border_color=COR_BORDA,
                                        command=self.acao_buscar)
        self.btn_buscar.grid(row=0, column=1, padx=(0, 6))
        self.btn_todos = ctk.CTkButton(faixa, text="✓ Todos", width=90, fg_color=COR_CARD,
                                       border_width=1, border_color=COR_BORDA,
                                       command=lambda: self._marcar_todos(True))
        self.btn_todos.grid(row=0, column=2, padx=(0, 6))
        self.btn_nenhum = ctk.CTkButton(faixa, text="✕ Nenhum", width=90, fg_color=COR_CARD,
                                        border_width=1, border_color=COR_BORDA,
                                        command=lambda: self._marcar_todos(False))
        self.btn_nenhum.grid(row=0, column=3, padx=(0, 6))
        self.btn_pausar = ctk.CTkButton(faixa, text="⏸ Pausar", width=110, fg_color=COR_AMBAR,
                                        hover_color="#b45309", text_color="white",
                                        command=self.acao_pausar, state="disabled")
        self.btn_pausar.grid(row=0, column=4, padx=(0, 6))
        self.btn_continuar = ctk.CTkButton(faixa, text="▶ Continuar", width=120, fg_color=COR_CARD,
                                          border_width=1, border_color=COR_BORDA,
                                          command=self.acao_continuar, state="disabled")
        self.btn_continuar.grid(row=0, column=5, padx=(0, 6))
        self.btn_cancelar = ctk.CTkButton(faixa, text="✖ Cancelar", width=110, fg_color=COR_VERMELHO,
                                         hover_color="#991b1b", text_color="white",
                                         command=self.acao_cancelar, state="disabled")
        self.btn_cancelar.grid(row=0, column=6)

        meio = ctk.CTkFrame(tab, fg_color="transparent")
        meio.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        tab.grid_rowconfigure(2, weight=1)
        meio.grid_columnconfigure(0, weight=1)
        meio.grid_columnconfigure(1, weight=2)
        meio.grid_rowconfigure(0, weight=1)

        card_nomes = Cartao(meio, titulo="📝 Lista de teste (15 jogos)")
        card_nomes.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(card_nomes, text="um por linha — pode colar '1. Nome do jogo'",
                     font=("Segoe UI", 10), text_color=COR_TEXTO_FRACO).pack(anchor="w", padx=14)
        self.txt_termos = ctk.CTkTextbox(card_nomes, font=FONTE_NORMAL, fg_color="#0f1319",
                                         border_width=1, border_color=COR_BORDA, corner_radius=8)
        self.txt_termos.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.txt_termos.insert("1.0", LISTA_TESTE)

        card_res = Cartao(meio, titulo="🎮 Encontrados")
        card_res.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.lbl_contadores = ctk.CTkLabel(card_res, text="—", font=("Segoe UI", 10),
                                           text_color=COR_TEXTO_FRACO)
        self.lbl_contadores.pack(anchor="w", padx=14)
        self.lista_scroll = ctk.CTkScrollableFrame(card_res, fg_color="#0f1319",
                                                   border_width=1, border_color=COR_BORDA,
                                                   corner_radius=8)
        self.lista_scroll.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        ctk.CTkLabel(self.lista_scroll, text="Analise o site para listar os jogos aqui…",
                     font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=16)

    # ----------------------------------------------------- aba: catálogo
    def _montar_aba_catalogo(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        barra = ctk.CTkFrame(tab, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        barra.grid_columnconfigure(0, weight=1)
        self.ent_busca_cat = ctk.CTkEntry(barra, font=FONTE_NORMAL, height=36,
                                          placeholder_text="🔍 Buscar no catálogo… (ex: god of war)",
                                          fg_color="#0f1319", border_color=COR_BORDA)
        self.ent_busca_cat.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.ent_busca_cat.bind("<KeyRelease>", lambda _e: self._render_catalogo())
        self.var_ocultar_baixados = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(barra, text="Ocultar já baixados", variable=self.var_ocultar_baixados,
                      font=FONTE_NORMAL, command=self._render_catalogo).grid(row=0, column=1, padx=(0, 8))

        linha2 = ctk.CTkFrame(tab, fg_color="transparent")
        linha2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.btn_cat_carregar = ctk.CTkButton(linha2, text="🌐 Carregar catálogo do site",
                                              fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                                              font=("Segoe UI", 12, "bold"), height=38,
                                              command=self.acao_carregar_catalogo)
        self.btn_cat_carregar.grid(row=0, column=0, padx=(0, 6))
        self.opt_paginas = ctk.CTkOptionMenu(linha2, values=list(PAGINAS_OPCOES),
                                             variable=self.var_paginas, height=38, width=170,
                                             fg_color=COR_CARD, button_color=COR_BORDA)
        self.opt_paginas.grid(row=0, column=1, padx=(0, 6))
        self.btn_cat_status = ctk.CTkButton(linha2, text="🔄 Atualizar status", width=150, height=38,
                                            fg_color=COR_CARD, border_width=1, border_color=COR_BORDA,
                                            command=self.acao_atualizar_status_catalogo)
        self.btn_cat_status.grid(row=0, column=2, padx=(0, 6))
        self.lbl_cat_info = ctk.CTkLabel(linha2, text="nenhum catálogo carregado",
                                         font=("Segoe UI", 10), text_color=COR_TEXTO_FRACO)
        self.lbl_cat_info.grid(row=0, column=3, sticky="e", padx=(8, 0))
        linha2.grid_columnconfigure(3, weight=1)

        self.cat_scroll = ctk.CTkScrollableFrame(tab, fg_color="#0f1319",
                                                 border_width=1, border_color=COR_BORDA,
                                                 corner_radius=8)
        self.cat_scroll.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.lbl_cat_vazio = ctk.CTkLabel(self.cat_scroll,
                                          text="Clique em «Carregar catálogo do site» para ver todos os jogos aqui…",
                                          font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO)
        self.lbl_cat_vazio.pack(padx=10, pady=16)

        rodape = ctk.CTkFrame(tab, fg_color="transparent")
        rodape.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.btn_cat_baixar = ctk.CTkButton(rodape, text="⬇ Baixar marcados", height=42,
                                            font=("Segoe UI", 12, "bold"),
                                            fg_color=COR_VERDE, hover_color=COR_VERDE_HOVER,
                                            command=self.acao_baixar_catalogo)
        self.btn_cat_baixar.grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(rodape, text="🔍 Detalhes", width=120, height=42, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=self.acao_detalhes_catalogo).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(rodape, text="✓ Todos", width=90, height=42, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=lambda: self._marcar_cat_todos(True)).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkButton(rodape, text="✕ Nenhum", width=90, height=42, fg_color=COR_CARD,
                      border_width=1, border_color=COR_BORDA,
                      command=lambda: self._marcar_cat_todos(False)).grid(row=0, column=3)

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
                                                  corner_radius=8)
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

    def termos_digitados(self) -> list[str]:
        import re
        out = []
        for linha in self.txt_termos.get("1.0", "end").splitlines():
            linha = linha.strip()
            if linha and linha[0].isdigit():  # "1. God of War..." -> "God of War..."
                linha = re.sub(r"^\d+[\.\)\-:\s]+", "", linha).strip()
            if linha:
                out.append(linha)
        return out

    def extensoes_digitadas(self) -> list[str]:
        raw = self.ent_ext.get().strip()
        return [e.strip() for e in raw.split(",") if e.strip()] if raw else []

    def travar(self, travado: bool):
        st = "disabled" if travado else "normal"
        self.baixando = travado
        self.btn_teste.configure(state=st, text="⏳ Baixando... aguarde" if travado
                                 else "⬇  BAIXAR LISTA DE TESTE  —  1 clique")
        self.btn_cat_baixar.configure(state=st)
        for b in (self.btn_pausar, self.btn_continuar, self.btn_cancelar):
            b.configure(state="normal" if travado else "disabled")

    def rodar_em_thread(self, alvo):
        threading.Thread(target=alvo, daemon=True).start()

    def _marcar_todos(self, valor: bool):
        for _, var in self.checks:
            var.set(valor)

    def _itens_marcados(self) -> list[dict]:
        return [item for item, var in self.checks if var.get()]

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

    def acao_carregar_lista(self):
        arq = filedialog.askopenfilename(filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        if not arq:
            return
        try:
            termos = carregar_termos_de_arquivo(arq)
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self.txt_termos.delete("1.0", "end")
        self.txt_termos.insert("1.0", "\n".join(termos))
        self.logar(f"Lista carregada ({len(termos)} nomes): {arq}")

    def acao_pausar(self):
        if not self.baixando:
            return
        self.controle.pausar()
        self.logar("⏸ Pausado — o progresso foi salvo (.part). Aperte Continuar.")
        self.set_status("pausado", COR_AMBAR)

    def acao_continuar(self):
        if not self.baixando:
            return
        self.controle.continuar()
        self.logar("▶ Continuando de onde parou...")

    def acao_cancelar(self):
        if not self.baixando:
            return
        self.controle.cancelar()
        self.logar("✖ Cancelando... (.part mantido para continuar depois)")

    # ------------------------------------------------- motor de download
    def _executar_download(self, alvos: list[dict], termos: list[str], exts: list[str],
                           pasta: str, permitir_resume: bool, pular_existentes: bool):
        """Baixa a lista (chamado dentro da thread de fundo)."""
        self.emit( lambda: self.set_status(f"baixando 0/{len(alvos)}", COR_AZUL))
        ok, pulados_na_hora, falhas = 0, 0, 0
        for i, item in enumerate(alvos, 1):
            if self.controle.foi_cancelado:
                self.emit( lambda: self.logar("Lote cancelado pelo usuário."))
                break
            nome = item.get("nome_arquivo", "?")
            self.emit( lambda n=nome, a=i, t=len(alvos): self.lbl_arquivo.configure(
                text=f"[{a}/{t}] {n}"))
            self.emit( lambda: self.bar_total.set((i - 1) / max(len(alvos), 1)))
            self.emit( lambda n=nome: self.logar(f"Baixando {n} ..."))
            try:
                def prog(rec, tot, _n=nome, _i=i, _t=len(alvos)):
                    if tot:
                        self.emit( lambda: self.bar_arquivo.set(rec / tot))
                        mb_r, mb_t = rec / 1024 / 1024, tot / 1024 / 1024
                        pct = int(rec / tot * 100)
                        self.emit( lambda: self.lbl_arquivo.configure(
                            text=f"[{_i}/{_t}] {_n} — {mb_r:.1f}/{mb_t:.1f} MB ({pct}%)"))
                def logm(m):
                    self.emit( lambda: self.logar(f"  ↳ {m}"))
                dest = baixar_inteligente(
                    item["url"], pasta, nome_base=item.get("nome_arquivo"),
                    termos=termos, extensoes=exts, timeout=120,
                    callback_progress=prog, callback_log=logm,
                    controle=self.controle,
                    permitir_resume=permitir_resume,
                    pular_existentes=pular_existentes,
                )
                ok += 1
                self.emit( lambda d=str(dest), n=nome: self.logar(f"✅ {n} -> {d}"))
            except DownloadJaExiste:
                pulados_na_hora += 1
                self.emit( lambda n=nome: self.logar(f"PULADO (já existe): {n}"))
            except DownloadCancelado:
                self.emit( lambda: self.logar("Download cancelado (.part mantido)."))
                break
            except Exception as e:
                falhas += 1
                self.emit( lambda e=str(e), n=nome: self.logar(f"❌ FALHOU {n}: {e}"))
            self.emit( lambda a=i, t=len(alvos): self.set_status(f"baixando {a}/{t}", COR_AZUL))
            self.emit( lambda a=i, t=len(alvos): self.bar_total.set(a / max(t, 1)))
        self.emit( lambda: self.bar_arquivo.set(0))
        self.emit( lambda: self.lbl_arquivo.configure(text="concluído"))
        self.emit( lambda: self.logar(
            f"Concluído: {ok} baixados, {pulados_na_hora} pulados, {falhas} falhas → {pasta}"))
        self.emit( lambda: self.set_status(f"pronto {ok}/{len(alvos)}", COR_VERDE))
        self.emit( self._pos_download)  # re-cruza catálogo + meus jogos
        return ok, pulados_na_hora, falhas

    def _pos_download(self):
        """Após baixar: atualiza badges do catálogo e a aba Meus jogos."""
        try:
            anotar_catalogo(self.catalogo, self.pasta_downloads())
        except Exception:
            pass
        self._render_catalogo()
        self.acao_atualizar_meus()

    def acao_teste_unico(self):
        if self.baixando:
            return
        # Snapshot dos campos NA thread principal (tkinter não é thread-safe).
        params = (self.ent_url.get().strip(), self.pasta_downloads(),
                  self.termos_digitados(), self.extensoes_digitadas(),
                  self.var_resume.get(), self.var_pular.get())
        self.controle = ControleDownload()
        self.travar(True)
        self.bar_arquivo.set(0)
        self.bar_total.set(0)
        self.rodar_em_thread(lambda: self._teste_bg(*params))

    def _teste_bg(self, url: str, pasta: str, termos: list[str], exts: list[str],
                  permitir_resume: bool, pular_existentes: bool):
        try:
            self.emit( lambda: self.set_status("analisando site...", COR_AZUL))
            self.emit( lambda: self.logar(f"Analisando: {url}"))
            links = analisar_site(url, timeout=30)
            self.links_analisados = links
            self.emit( lambda: self.logar(f"Encontrados {len(links)} links na página."))

            filtrados = filtrar_por_nomes(links, termos, exts)
            self.links_filtrados = filtrados
            self.emit( lambda: self._mostrar_filtrados(filtrados, termos, exts))
            if not filtrados:
                self.emit( lambda: self.logar("Nada encontrado. Confira os nomes."))
                self.emit( lambda: self.set_status("nada encontrado", COR_AMBAR))
                return

            pendentes, pulados = filtrados, []
            if pular_existentes:
                pendentes, pulados = pular_ja_baixados(filtrados, pasta)
                for p in pulados:
                    nome = p.get("nome_arquivo", "?")
                    self.emit( lambda n=nome: self.logar(f"PULADO (já existe): {n}"))
                if pulados:
                    self.emit( lambda: self.logar(
                        f"{len(pulados)} já baixado(s) — pulados sem baixar de novo."))
                self.emit( lambda: self._mostrar_filtrados(pendentes, termos, exts))
            if not pendentes:
                self.emit( lambda: self.logar("Tudo já baixado. Nada a fazer."))
                self.emit( lambda: self.set_status(f"tudo pronto ({len(pulados)} pulados)", COR_VERDE))
                self.emit( lambda: messagebox.showinfo(
                    "Tudo pronto", f"Nada a baixar — {len(pulados)} arquivo(s) já estavam na pasta."))
                return

            self.emit( lambda: self.logar("Baixando apenas os itens marcados com ✓."))
            marcados = {id(it) for it in self._itens_marcados()}
            alvos = [it for it in pendentes if id(it) in marcados] or pendentes
            ok, _, falhas = self._executar_download(alvos, termos, exts, pasta,
                                                    permitir_resume, pular_existentes)
            if not self.controle.foi_cancelado:
                self.emit( lambda: messagebox.showinfo(
                    "Pronto", f"{ok} baixado(s), {len(pulados)} pulado(s), {falhas} falha(s) em:\n{pasta}"))
        except Exception as e:
            self.emit( lambda: self.logar(f"ERRO geral: {e}"))
        finally:
            self.emit( lambda: self.travar(False))

    def _mostrar_filtrados(self, filtrados, termos, exts):
        for w in self.lista_scroll.winfo_children():
            w.destroy()
        self.checks = []
        if not filtrados:
            ctk.CTkLabel(self.lista_scroll, text="Nada encontrado — confira os nomes.",
                         font=FONTE_NORMAL, text_color=COR_AMBAR).pack(padx=10, pady=16)
        for it in filtrados:
            var = ctk.BooleanVar(value=True)
            linha = ctk.CTkCheckBox(
                self.lista_scroll, variable=var, corner_radius=6,
                text=f"{it['nome_arquivo']}  •  {it['texto'][:60]}",
                font=("Segoe UI", 11), text_color="#e5e7eb")
            linha.pack(anchor="w", padx=10, pady=4)
            self.checks.append((it, var))
        self.lbl_contadores.configure(
            text=f"{len(filtrados)}/{len(termos)} localizados  •  ext={exts or 'todas'}  •  ✓ marcados serão baixados")
        self.logar(f"Filtro: {len(filtrados)}/{len(termos)} jogo(s) localizados (ext={exts or 'todas'}).")

    def acao_analisar(self):
        url = self.ent_url.get().strip()
        if not url or url == "https://":
            messagebox.showwarning("Atenção", "Digite a URL do site.")
            return
        self.logar(f"Analisando: {url} ...")
        self.rodar_em_thread(lambda: self._analisar_bg(url))

    def _analisar_bg(self, url: str):
        try:
            self.links_analisados = analisar_site(url, timeout=30)
        except Exception as e:
            self.emit( lambda: self.logar(f"ERRO ao analisar: {e}"))
            return
        self.emit( lambda: self.logar(f"Encontrados {len(self.links_analisados)} links."))
        self.emit( self.acao_buscar)

    def acao_buscar(self):
        if not self.links_analisados:
            self.logar("Clique em Analisar primeiro.")
            return
        termos = self.termos_digitados()
        exts = self.extensoes_digitadas()
        self.links_filtrados = filtrar_por_nomes(self.links_analisados, termos, exts)
        self._mostrar_filtrados(self.links_filtrados, termos, exts)

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
            self.logar(f"Catálogo em cache: {len(self.catalogo)} jogos "
                       f"(atualizado em {cache.get('atualizado_em', '?')[:10]}). "
                       "Clique em Carregar para atualizar.")

    def acao_carregar_catalogo(self):
        if self.carregando_cat or self.baixando:
            return
        url = self.ent_url.get().strip()
        if not url or url == "https://":
            messagebox.showwarning("Atenção", "Digite a URL da listagem (ex: .../playstation-portable/).")
            return
        max_pag = PAGINAS_OPCOES.get(self.var_paginas.get(), 3)  # snapshot (thread principal)
        rotulo = self.var_paginas.get()
        self.carregando_cat = True
        self.btn_cat_carregar.configure(state="disabled", text="⏳ Lendo o site...")
        self.set_status("lendo catálogo...", COR_AZUL)
        self.rodar_em_thread(lambda: self._carregar_catalogo_bg(url, max_pag, rotulo))

    def _carregar_catalogo_bg(self, url: str, max_pag: int, rotulo: str):
        try:
            self.emit( lambda: self.logar(f"Carregando catálogo ({rotulo})..."))
            def logm(m):
                self.emit( lambda: self.logar(f"  ↳ {m}"))
            catalogo = carregar_catalogo(url, max_paginas=max_pag, timeout=30,
                                         callback_log=logm, controle=self.controle)
            if not catalogo:
                raise RuntimeError("O site não devolveu nenhum jogo. Confira a URL ou sua internet.")
            try:
                salvar_catalogo_cache(catalogo, pasta_base(), url)
            except Exception:
                pass
            self.catalogo = catalogo
            self.emit( lambda: self.logar(f"Catálogo pronto: {len(catalogo)} jogos."))
            self.emit( self.acao_atualizar_status_catalogo)
            self.emit( lambda: self.set_status(f"catálogo: {len(catalogo)} jogos", COR_VERDE))
        except Exception as e:
            msg = f"ERRO ao carregar catálogo: {e}"
            self.emit( lambda: self.logar(msg))
            self.emit( lambda: self.set_status("falha no catálogo", COR_VERMELHO))
            self.emit( lambda: self.lbl_cat_info.configure(
                text=f"❌ Falha ao ler o site: {e}", text_color=COR_VERMELHO))
        finally:
            self.carregando_cat = False
            self.emit( lambda: self.btn_cat_carregar.configure(state="normal",
                                                                  text="🌐 Carregar catálogo do site"))

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
        if not self.catalogo:
            ctk.CTkLabel(self.cat_scroll,
                         text="Clique em «Carregar catálogo do site» para ver todos os jogos aqui…",
                         font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=16)
            return
        if not visiveis:
            ctk.CTkLabel(self.cat_scroll, text="Nenhum jogo para essa busca.",
                         font=FONTE_NORMAL, text_color=COR_AMBAR).pack(padx=10, pady=16)
            return
        mostrar = visiveis[:2000]  # trava de segurança p/ catálogos gigantes
        for jogo in mostrar:
            var = ctk.BooleanVar(value=not jogo.get("ja_baixado"))
            linha = ctk.CTkFrame(self.cat_scroll, fg_color="transparent")
            linha.pack(fill="x", padx=6, pady=2)
            thumb = ctk.CTkLabel(linha, text="🎮", width=56, height=56,
                                 fg_color="#0b0d11", corner_radius=8,
                                 font=("Segoe UI", 20))
            thumb.pack(side="left", padx=(0, 8))
            jogo["_thumb_label"] = thumb  # temporário, só p/ o loader desta renderização
            chk = ctk.CTkCheckBox(linha, variable=var, corner_radius=6, text="",
                                  width=24)
            chk.pack(side="left")
            titulo = jogo.get("titulo", "?")
            if len(titulo) > 64:
                titulo = titulo[:63] + "…"
            ctk.CTkLabel(linha, text=titulo, font=("Segoe UI", 11),
                         text_color="#e5e7eb").pack(side="left")
            if jogo.get("ja_baixado"):
                ctk.CTkLabel(linha, text="✓ BAIXADO", font=("Segoe UI", 10, "bold"),
                             fg_color="#14532d", text_color="#86efac",
                             corner_radius=6, padx=8, pady=1).pack(side="right", padx=(6, 2))
            self.cat_checks.append((jogo, var))
        if len(visiveis) > 2000:
            ctk.CTkLabel(self.cat_scroll,
                         text=f"… e mais {len(visiveis) - 2000} (refine a busca)",
                         font=FONTE_NORMAL, text_color=COR_TEXTO_FRACO).pack(padx=10, pady=8)
        self._carregar_thumbs_job(self._thumb_job, [j for j in mostrar if j.get("capa")][:150])

    def _carregar_thumbs_job(self, job: int, jogos: list[dict]):
        """Baixa as capas em thread e aplica na thread principal."""
        if not jogos:
            return
        def bg():
            prontas: list[tuple[str, str]] = []  # (url capa, caminho local)
            for jogo in jogos:
                if job != self._thumb_job:
                    return  # renderização mais nova assumiu
                capa = jogo.get("capa", "")
                if capa and capa not in self._thumbs:
                    local = baixar_capa(capa, pasta_base())
                    if local is not None:
                        prontas.append((capa, str(local)))
            self.emit( lambda: self._aplicar_thumbs(job, prontas))
        threading.Thread(target=bg, daemon=True).start()

    def _aplicar_thumbs(self, job: int, prontas: list[tuple[str, str]]):
        if job != self._thumb_job:
            return
        for capa, caminho in prontas:
            try:
                img = Image.open(caminho).convert("RGB").resize((56, 56))
                self._thumbs[capa] = ctk.CTkImage(light_image=img, dark_image=img,
                                                 size=(56, 56))
            except Exception:
                continue
        for jogo, _var in self.cat_checks:
            capa = jogo.get("capa", "")
            label = jogo.pop("_thumb_label", None)
            if label is not None and label.winfo_exists() and capa in self._thumbs:
                try:
                    label.configure(text="", image=self._thumbs[capa])
                except Exception:
                    pass

    def acao_baixar_catalogo(self):
        if self.baixando:
            return
        marcados = self._itens_cat_marcados()
        if not marcados:
            messagebox.showinfo("Catálogo", "Marque ao menos um jogo com ✓.")
            return
        pasta = self.pasta_downloads()
        # tira da lista quem o cruzamento já apontou como baixado
        alvos = []
        for jogo in marcados:
            if jogo.get("ja_baixado") and self.var_pular.get():
                self.logar(f"PULADO (já existe): {jogo.get('titulo')}")
                continue
            alvos.append({"texto": jogo.get("titulo", ""), "nome_arquivo": jogo.get("titulo", ""),
                          "url": jogo["url"], "extensao_url": ""})
        if not alvos:
            messagebox.showinfo("Catálogo", "Todos os marcados já foram baixados. ✔")
            return
        termos = [j.get("titulo", "") for j in marcados]
        exts = self.extensoes_digitadas()
        resume, pular = self.var_resume.get(), self.var_pular.get()  # snapshot (thread principal)
        self.controle = ControleDownload()
        self.travar(True)
        self.bar_arquivo.set(0)
        self.bar_total.set(0)
        self.logar(f"Baixando {len(alvos)} jogo(s) do catálogo...")
        self.rodar_em_thread(lambda: self._bg_wrapper(
            lambda: self._executar_download(alvos, termos, exts, pasta, resume, pular),
            pasta))

    def _bg_wrapper(self, fn, pasta: str):
        try:
            fn()
        except Exception as e:
            self.emit( lambda: self.logar(f"ERRO geral: {e}"))
        finally:
            self.emit( lambda: self.travar(False))

    def acao_detalhes_catalogo(self):
        marcados = self._itens_cat_marcados()[:5]  # no máx 5 p/ não demorar
        if not marcados:
            messagebox.showinfo("Detalhes", "Marque ao menos um jogo com ✓.")
            return
        self.logar(f"Buscando detalhes de {len(marcados)} jogo(s)...")
        self.rodar_em_thread(lambda: self._detalhes_bg(marcados))

    def _detalhes_bg(self, jogos: list[dict]):
        linhas = []
        for jogo in jogos:
            try:
                d = detalhes_jogo(jogo["url"], timeout=20)
                for k in ("titulo", "regiao", "tamanho", "nota", "votos"):
                    if d.get(k):
                        jogo[k] = d[k]
                linhas.append(
                    f"• {d.get('titulo') or jogo.get('titulo')}\n"
                    f"  Região: {d.get('regiao') or '?'}  •  Tamanho: {d.get('tamanho') or '?'}  •  "
                    f"Nota: {d.get('nota') or '?'} ({d.get('votos') or '?'} votos)")
            except Exception as e:
                linhas.append(f"• {jogo.get('titulo')}: falhou ({e})")
        texto = "\n".join(linhas)
        for ln in linhas:
            self.emit( lambda l=ln: self.logar(l.replace("\n", " ")))
        self.emit( lambda: messagebox.showinfo("Detalhes dos jogos", texto))

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
