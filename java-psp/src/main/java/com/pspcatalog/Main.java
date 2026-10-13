package com.pspcatalog;

import com.pspcatalog.model.Game;
import com.pspcatalog.service.CatalogService;
import com.pspcatalog.service.CoverCache;
import com.pspcatalog.service.DownloadManager;
import com.pspcatalog.ui.GameCard;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Scene;
import javafx.scene.control.Button;
import javafx.scene.control.CheckBox;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressBar;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.FlowPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import javafx.stage.DirectoryChooser;
import javafx.stage.Stage;

import java.io.File;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Catálogo PSP 100% Java (sem Python): header compacto, grid vertical 160x220,
 * fila de downloads recolhível. Equivale a app.py + downloader.py.
 *
 * Abrir no Eclipse: File > Import > Existing Maven Projects > pasta java-psp.
 * Executar: Run As > Maven build... goals "javafx:run" (ou Run As > Java Application
 * na classe Main com o JavaFX SDK no module-path).
 */
public class Main extends Application {

    private static final int POR_PAGINA = 100;

    private final CatalogService catalogo = new CatalogService();
    private CoverCache capas;
    private DownloadManager downloads;

    private List<Game> todos = new ArrayList<>();
    private List<Game> visiveis = new ArrayList<>();
    private final List<GameCard> cards = new ArrayList<>();
    private int pagina = 0;

    private Path pastaProjeto;
    private Path pastaDownloads;

    private TextField busca;
    private Label lblPagina;
    private Label lblInfo;
    private Label lblStatus;
    private FlowPane grid;
    private VBox painelDownloads;
    private VBox listaDownloads;
    private boolean recolhido = false;
    private CheckBox chkPular;
    private VBox logBox;

    @Override
    public void start(Stage stage) {
        pastaProjeto = Path.of("").toAbsolutePath();
        // se executado de dentro de java-psp/, o catalogo mora um nível acima
        pastaDownloads = pastaProjeto.resolve("downloads");
        if (!pastaDownloads.toFile().exists() && pastaProjeto.endsWith("java-psp")) {
            pastaProjeto = pastaProjeto.getParent();
            pastaDownloads = pastaProjeto.resolve("downloads");
        }
        capas = new CoverCache(pastaProjeto);
        downloads = new DownloadManager(true);
        downloads.setLog(this::logar);

        BorderPane root = new BorderPane();
        root.getStylesheets().add(getClass().getResource("/style.css").toExternalForm());

        root.setTop(montarTopo(stage));
        root.setCenter(montarCentro());
        root.setBottom(montarRodape());

        Scene scene = new Scene(root, 1200, 800);
        stage.setTitle("Catálogo PSP — 2207 jogos (Java)");
        stage.setScene(scene);
        stage.show();

        carregarEmFundo();
    }

    // ---- topo compacto: logo + busca + paginação + baixar marcados ----
    private HBox montarTopo(Stage stage) {
        HBox top = new HBox(12);
        top.getStyleClass().add("top-bar");
        top.setAlignment(Pos.CENTER_LEFT);

        Label logo = new Label("🎮 PSP Catalog");
        logo.getStyleClass().add("logo");

        busca = new TextField();
        busca.setPromptText("🔍 Buscar… (ex: god of war)");
        busca.getStyleClass().add("search-field");
        HBox.setHgrow(busca, Priority.ALWAYS);
        busca.textProperty().addListener((o, a, b) -> {
            pagina = 0;
            aplicarFiltro();
        });

        Button btnPasta = new Button("📁");
        btnPasta.getStyleClass().add("btn-secondary");
        btnPasta.setOnAction(e -> {
            DirectoryChooser dc = new DirectoryChooser();
            dc.setTitle("Pasta de downloads");
            dc.setInitialDirectory(pastaDownloads.toFile().exists()
                ? pastaDownloads.toFile() : new File("."));
            File f = dc.showDialog(stage);
            if (f != null) {
                pastaDownloads = f.toPath();
                catalogo.anotarBaixados(todos, pastaDownloads);
                aplicarFiltro();
                logar("Pasta: " + pastaDownloads);
            }
        });

        Button btnAnt = new Button("◀");
        Button btnProx = new Button("▶");
        btnAnt.getStyleClass().add("btn-secondary");
        btnProx.getStyleClass().add("btn-secondary");
        lblPagina = new Label("—");
        lblPagina.getStyleClass().add("muted");
        btnAnt.setOnAction(e -> {
            pagina = Math.max(0, pagina - 1);
            renderizar();
        });
        btnProx.setOnAction(e -> {
            pagina++;
            renderizar();
        });
        HBox pag = new HBox(6, btnAnt, lblPagina, btnProx);
        pag.setAlignment(Pos.CENTER);

        Button btnBaixar = new Button("⬇ Baixar marcados");
        btnBaixar.getStyleClass().add("btn-primary");
        btnBaixar.setOnAction(e -> baixarMarcados());

        top.getChildren().addAll(logo, busca, btnPasta, pag, btnBaixar);
        return top;
    }

    // ---- centro: scroll + grid de cards verticais ----
    private ScrollPane montarCentro() {
        grid = new FlowPane();
        grid.setHgap(16);
        grid.setVgap(16);
        grid.setPadding(new Insets(20));
        grid.setAlignment(Pos.TOP_LEFT);
        lblInfo = new Label("Carregando catálogo…");
        lblInfo.getStyleClass().add("muted");
        grid.getChildren().add(lblInfo);

        ScrollPane scroll = new ScrollPane(grid);
        scroll.setFitToWidth(true);
        scroll.setStyle("-fx-background: transparent; -fx-background-color: transparent;");
        return scroll;
    }

    // ---- rodapé recolhível: status + fila + log ----
    private VBox montarRodape() {
        VBox base = new VBox(6);
        base.getStyleClass().add("bottom-panel");

        HBox status = new HBox(12);
        status.setAlignment(Pos.CENTER_LEFT);
        lblStatus = new Label("fila vazia");
        lblStatus.getStyleClass().add("muted");
        javafx.scene.layout.Region esp = new javafx.scene.layout.Region();
        HBox.setHgrow(esp, Priority.ALWAYS);
        chkPular = new CheckBox("Pular já baixados");
        chkPular.setSelected(true);
        chkPular.getStyleClass().add("muted");
        Button btnToggle = new Button("–");
        btnToggle.getStyleClass().add("btn-secondary");
        btnToggle.setOnAction(e -> alternarRodape());
        status.getChildren().addAll(lblStatus, esp, chkPular, btnToggle);

        painelDownloads = new VBox(4);
        listaDownloads = new VBox(4);
        painelDownloads.getChildren().add(listaDownloads);

        logBox = new VBox(2);
        base.getChildren().addAll(status, painelDownloads);
        return base;
    }

    private void alternarRodape() {
        recolhido = !recolhido;
        painelDownloads.setVisible(!recolhido);
        painelDownloads.setManaged(!recolhido);
    }

    // ---- dados ----
    private void carregarEmFundo() {
        new Thread(() -> {
            try {
                todos = catalogo.carregar(pastaProjeto);
            } catch (Exception e) {
                List<Game> copia = todos;
                Platform.runLater(() -> logar("ERRO catalogo-psp.json: " + e.getMessage()));
                todos = copia;
            }
            try {
                catalogo.anotarBaixados(todos, pastaDownloads);
            } catch (Exception ignored) {
            }
            List<Game> primeira = todos.stream().filter(g -> g.getCapa() != null && !g.getCapa().isBlank())
                .limit(100).toList();
            capas.preAquecer(primeira, this::renderizar);
            Platform.runLater(() -> {
                aplicarFiltro();
                logar("Catálogo: " + todos.size() + " jogos.");
            });
        }, "catalogo-loader").start();
    }

    private void aplicarFiltro() {
        visiveis = catalogo.filtrar(todos, busca == null ? "" : busca.getText());
        if (chkPular != null && chkPular.isSelected()) {
            // mantém visíveis mas desmarca os já baixados (mesma regra do app.py)
        }
        pagina = Math.max(0, pagina);
        renderizar();
    }

    private void renderizar() {
        cards.clear();
        grid.getChildren().clear();
        int total = visiveis.size();
        int paginas = Math.max(1, (total + POR_PAGINA - 1) / POR_PAGINA);
        pagina = Math.max(0, Math.min(pagina, paginas - 1));
        int ini = pagina * POR_PAGINA;
        int fim = Math.min(ini + POR_PAGINA, total);
        lblPagina.setText("Pág. " + (pagina + 1) + "/" + paginas + " • " + (total == 0 ? 0 : ini + 1) + "–" + fim + " de " + total);
        if (total == 0) {
            Label vazio = new Label(todos.isEmpty() ? "catalogo-psp.json não encontrado." : "Nenhum jogo para essa busca.");
            vazio.getStyleClass().add("muted");
            grid.getChildren().add(vazio);
            return;
        }
        for (Game g : visiveis.subList(ini, fim)) {
            GameCard card = new GameCard(g, capas, this::baixarUm);
            cards.add(card);
            grid.getChildren().add(card);
        }
    }

    private void baixarUm(Game g) {
        if (g.isJaBaixado() && chkPular.isSelected()) {
            logar("PULADO (já existe): " + g.getTitulo());
            return;
        }
        DownloadManager.Item it = downloads.enfileirar(g, pastaDownloads);
        adicionarLinhaDownload(it);
        logar("Enfileirado: " + g.getTitulo());
    }

    private void baixarMarcados() {
        List<Game> marcados = new ArrayList<>();
        for (GameCard c : cards) {
            if (c.isMarcado()) {
                marcados.add(c.getGame());
            }
        }
        if (marcados.isEmpty()) {
            logar("Marque ao menos um jogo com ✓.");
            return;
        }
        for (Game g : marcados) {
            baixarUm(g);
        }
    }

    private void adicionarLinhaDownload(DownloadManager.Item it) {
        Platform.runLater(() -> {
            HBox linha = new HBox(8);
            linha.setAlignment(Pos.CENTER_LEFT);
            Label nome = new Label(it.getGame().getTitulo());
            nome.setMaxWidth(420);
            ProgressBar bar = new ProgressBar(0);
            bar.setPrefWidth(220);
            bar.progressProperty().bind(it.progressoProperty());
            Label info = new Label();
            info.textProperty().bind(it.infoProperty());
            info.getStyleClass().add("muted");
            Button btnPausa = new Button("⏸");
            Button btnGo = new Button("▶");
            Button btnX = new Button("✖");
            btnPausa.getStyleClass().add("btn-secondary");
            btnGo.getStyleClass().add("btn-secondary");
            btnX.getStyleClass().add("btn-secondary");
            btnPausa.setOnAction(e -> downloads.pausar(it));
            btnGo.setOnAction(e -> downloads.continuar(it));
            btnX.setOnAction(e -> {
                downloads.cancelar(it);
                listaDownloads.getChildren().remove(linha);
            });
            linha.getChildren().addAll(nome, bar, info, btnPausa, btnGo, btnX);
            listaDownloads.getChildren().add(linha);
            lblStatus.setText(listaDownloads.getChildren().size() + " na fila");
            if (recolhido) {
                alternarRodape();
            }
        });
    }

    private void logar(String msg) {
        Platform.runLater(() -> {
            lblStatus.setText(msg);
            System.out.println("[psp] " + msg);
        });
    }

    public static void main(String[] args) {
        launch(args);
    }
}
