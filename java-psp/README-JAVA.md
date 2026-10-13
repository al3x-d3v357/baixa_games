# Catálogo PSP — versão 100% Java (sem Python)

Recriação do zero em Java 17 + JavaFX 21. Nenhum `.py` é usado em tempo de execução.
O `catalogo-psp.json` (2207 jogos) é lido direto do disco.

## Estrutura

```
java-psp/
  pom.xml
  src/main/java/com/pspcatalog/
    Main.java                  -> app.py (_montar_tela, grade, fila UI)
    model/Game.java            -> item {titulo, url, capa}
    service/CatalogService.java -> carregar/filtrar/anotar (downloader.py)
    service/CoverCache.java     -> capas/ por md5 + memória (baixar_capa)
    service/DownloadManager.java -> fila 1-por-vez, resume .part+Range,
                                   pausar/continuar/cancelar, POST ?download
                                   do romsgames (baixar_inteligente)
    ui/GameCard.java            -> card vertical 180x300, capa 160x220
  src/main/resources/style.css  -> tema escuro
```

## Abrir no Eclipse

1. Instale JDK 17+ e o plugin **e(fx)clipse** (ou Eclipse com JavaFX SDK no module-path).
2. `File > Import > Existing Maven Projects >` selecione a pasta `java-psp`.
3. `Run As > Maven build...` com goal `javafx:run`.
   - Alternativa sem Maven: `Run As > Java Application` na classe `com.pspcatalog.Main`
     com VM args `--module-path <javafx-sdk>/lib --add-modules javafx.controls,javafx.media`.
4. O programa procura `catalogo-psp.json` na raiz do repo (um nível acima de `java-psp/`)
   e salva capas em `capas/` e jogos em `downloads/`, iguais às pastas do Python.

## Notas honestas (sem JDK nesta máquina: não compilado aqui)

- Sintaxe revisada por leitura; compile no Eclipse com JDK 17 para validar.
- Dependências Maven: `javafx-controls`, `javafx-media`, `jackson-databind`, `jsoup`
  (HTML do botão Save Game). Sem FastAPI/servidor: tudo in-process.
- Paridade intencional: paginação 100/pág, busca sem acento, `Range` + `.part`,
  `attach=` do romsgames, `Pular já baixados`, rodapé recolhível.
