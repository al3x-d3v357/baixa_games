"""Helpers de layout + animacoes visiveis (CustomTkinter).

Tudo aqui roda na thread principal via `after` — nunca bloquear a UI.
Uso no Eclipse: Run As > Python Run > app.py (interpretador 3.10+).
"""
from __future__ import annotations


SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
BARRA_ANIM = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰", "▱▰▰▰▰", "▱▱▰▰▰"]


def animar_spinner(label, prefixo="Carregando", delay=120):
    """Troca o texto do label em loop: ⠋ Carregando... (visivel)."""
    try:
        estado = getattr(label, "_spin_i", 0)
        label.configure(text=f"{SPINNER[estado % len(SPINNER)]} {prefixo}...")
        label._spin_i = estado + 1
        label.after(delay, lambda: animar_spinner(label, prefixo, delay))
    except Exception:
        pass  # label destruido (trocou de pagina)


def parar_spinner(label, texto_final=""):
    """Para o spinner fixando um texto final."""
    try:
        label._spin_i = 10 ** 9  # proxima chamada cai longe, mas paramos aqui
        if texto_final:
            label.configure(text=texto_final)
    except Exception:
        pass


def pulsar_pill(label, ligado: bool, cor_a="#3b82f6", cor_b="#16a34a", delay=600):
    """Pisca a pill de status enquanto ha download ativo. Chamado 1x."""
    if getattr(label, "_pulse_on", False) and ligado:
        return  # ja pulsando
    label._pulse_on = ligado
    if not ligado:
        return

    def _passo(vez: int = 0):
        try:
            if not getattr(label, "_pulse_on", False):
                return
            if not label.winfo_exists():
                return
            label.configure(text_color=cor_a if vez % 2 == 0 else cor_b)
            label.after(delay, lambda: _passo(vez + 1))
        except Exception:
            pass

    _passo(0)


def parar_pulso(label, cor_final="#9aa3b2"):
    """Desliga o pulso e fixa a cor."""
    try:
        label._pulse_on = False
        if label.winfo_exists():
            label.configure(text_color=cor_final)
    except Exception:
        pass


def hover_card(card, borda_normal="#262b36", borda_hover="#3b82f6"):
    """Destaque visivel ao passar o mouse no cartao do jogo."""
    def _enter(_e=None):
        try:
            card.configure(border_color=borda_hover, border_width=2)
        except Exception:
            pass

    def _leave(_e=None):
        try:
            card.configure(border_color=borda_normal, border_width=1)
        except Exception:
            pass

    try:
        card.bind("<Enter>", _enter, add="+")
        card.bind("<Leave>", _leave, add="+")
        for filho in card.winfo_children():
            try:
                filho.bind("<Enter>", _enter, add="+")
                filho.bind("<Leave>", _leave, add="+")
            except Exception:
                pass
    except Exception:
        pass


def fade_in_modal(modal, largura_final=660, altura_final=620, passos=8, delay=18):
    """Cresce a janelinha do jogo do pequeno ao tamanho final (efeito pop)."""
    try:
        w0, h0 = max(200, largura_final // 2), max(200, altura_final // 2)

        def _passo(i: int = 1):
            try:
                if not modal.winfo_exists():
                    return
                w = w0 + (largura_final - w0) * i // passos
                h = h0 + (altura_final - h0) * i // passos
                modal.geometry(f"{w}x{h}")
                if i < passos:
                    modal.after(delay, lambda: _passo(i + 1))
            except Exception:
                pass

        modal.geometry(f"{w0}x{h0}")
        _passo(1)
    except Exception:
        pass


def barra_fake_infinita(bar, delay=90):
    """Anima uma CTkProgressBar em loop (usada no 'carregando pagina')."""
    try:
        pos = getattr(bar, "_fake_pos", 0.0) + 0.08
        if pos > 1.0:
            pos = 0.0
        bar._fake_pos = pos
        # vai-e-volta 0.15 <-> 0.85 para parecer atividade
        import math
        bar.set(0.5 + 0.35 * math.sin(pos * 6.28))
        bar.after(delay, lambda: barra_fake_infinita(bar, delay))
    except Exception:
        pass
