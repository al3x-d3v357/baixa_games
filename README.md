# Baixador Universal — por nome (lista ou manual)

Coloque um **site**, ele **analisa a página**, procura arquivos pelo **nome**
(via `lista.txt` ou digitado manual), **clica no download** e salva numa
**pastinha com o formato correto** (`.iso`, `.zip`, `.pdf`...).

## 1. Programa local (sem instalar nada, 2 cliques)

- `BaixadorUniversal.exe` — programa pronto, só dar 2 cliques
- `Baixador.bat` — alternativa: abre com Python local
- Arquivos baixados vão para `downloads/` ao lado do programa

Para gerar o .exe de novo: 2 cliques em `Gerar-EXE.bat` (saída em `dist/`).

## 2. Rodar com Python

```bash
pip install -r requirements.txt
python app.py
```

Interface dark moderna (`customtkinter`): cabeçalho com status,
cards de origem/destino, switches de Resume e Pular-já-baixados,
lista de encontrados com ✓ (botões Todos/Nenhum), barra de progresso
do arquivo + do lote, e log escuro.

## 2b. Abas: Catálogo e Meus jogos

- **🗂 Catálogo** — `🌐 Carregar catálogo do site` lê as páginas do site
  (escolha 1–10 páginas ou tudo) e lista **todos os jogos com capa, título e busca**.
  Cada jogo mostra badge **✓ BAIXADO** se o cruzamento com a sua pasta
  achar o arquivo (tolera acento, `:`→`_`, `(USA)` etc.). Marque com ✓ e
  clique **Baixar marcados**; **🔍 Detalhes** mostra região, tamanho e nota.
  O catálogo fica em cache (`catalogo-psp.json`, capas em `capas/`) para abrir na hora.
- **💾 Meus jogos** — escaneia a pasta `downloads/`: quantos jogos, espaço
  total, data de cada um e `.part` incompletos (dá p/ continuar). Botão
  **📁 Abrir pasta** e **🔄 Atualizar** (também atualiza sozinho após baixar).

Via terminal:

```bash
# ver o que já foi baixado
python cli.py --meus-jogos --saida downloads

# listar o catálogo do site com status BAIXADO/novo (1 página + busca)
python cli.py --catalogo 1 --busca "god of war" \
  --url https://www.romsgames.net/roms/playstation-portable/ --saida downloads
```

1. Cole o **Site** e clique **Analisar site**
2. Digite os nomes (um por linha) OU clique **Carregar lista.txt**
3. Em extensões deixe `.iso` ou apague para **qualquer tipo**
4. Clique **Buscar na página** → selecione → **Baixar selecionados**
5. Arquivos vão para `downloads/` com nome + extensão corretos

## 3. Usar via terminal

```bash
# manual
python cli.py --url https://exemplo.com/downloads --manual "ubuntu,debian" --ext .iso

# via lista
python cli.py --url https://exemplo.com/downloads --lista lista.txt --ext .iso --saida downloads

# qualquer tipo de arquivo
python cli.py --url https://exemplo.com/downloads --lista lista.txt --saida downloads
```

## Como funciona

- `downloader.py:analisar_site` — baixa o HTML e extrai `<a href>`, `data-url`, `src`
- `downloader.py:filtrar_por_nomes` — busca parcial, sem acento/case, + filtro `.iso,.zip` (dedup por URL)
- `downloader.py:baixar_inteligente` — resolve página → botão → arquivo (nunca salva `.html`),
  descobre a extensão real via URL → `Content-Disposition` → `Content-Type`
- `downloader.py:pular_ja_baixados` — anti-duplicado: confere pasta + `.baixador-manifest.json`
  e pula quem já foi baixado (sem baixar 2x)
- Resume: baixa em `nome.zip.part` com `Range`; pausa, queda de rede ou Ctrl+C
  continua de onde parou. Servidor sem `Range` recomeça do zero sozinho.
- `ControleDownload` — GUI tem ⏸ Pausar / ▶ Continuar / ✖ Cancelar (o `.part` é mantido)

```bash
# CLI: pula existentes + resume (padrão); Ctrl+C pausa e mantém .part
python cli.py --url https://exemplo.com/downloads --lista lista.txt --saida downloads

# desliga resume / força baixar tudo de novo
python cli.py --url https://exemplo.com/downloads --lista lista.txt --sem-resume --refazer
```

## Pastas

- `downloads/` — arquivos salvos (criada automaticamente)
- `lista.txt` — exemplo de lista de nomes
