package com.pspcatalog.service;

import com.pspcatalog.model.Game;
import javafx.application.Platform;
import javafx.beans.property.DoubleProperty;
import javafx.beans.property.SimpleDoubleProperty;
import javafx.beans.property.SimpleStringProperty;
import javafx.beans.property.StringProperty;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;

/**
 * Fila de downloads estilo torrent: um por vez, com resume (.part + Range),
 * pausar/continuar/cancelar, velocidade e ETA.
 * Equivale a downloader.py: baixar_inteligente + ControleDownload
 * e app.py: _worker_dl_bg + _info_linha_dl.
 */
public class DownloadManager {

    public enum Estado { FILA, BAIXANDO, PAUSADO, CONCLUIDO, ERRO, CANCELADO }

    public static class Item {
        private final int seq;
        private final Game game;
        private final Path pasta;
        private volatile Estado estado = Estado.FILA;
        private volatile long recebido = 0;
        private volatile long total = 0;
        private volatile double velocidadeBps = 0;
        private volatile String erro = "";
        private volatile Path destino;
        private final AtomicBoolean pausado = new AtomicBoolean(false);
        private final AtomicBoolean cancelado = new AtomicBoolean(false);

        private final DoubleProperty progresso = new SimpleDoubleProperty(0);
        private final StringProperty info = new SimpleStringProperty("na fila");

        public Item(int seq, Game game, Path pasta) {
            this.seq = seq;
            this.game = game;
            this.pasta = pasta;
        }

        public int getSeq() { return seq; }
        public Game getGame() { return game; }
        public Estado getEstado() { return estado; }
        public DoubleProperty progressoProperty() { return progresso; }
        public StringProperty infoProperty() { return info; }
        public String getErro() { return erro; }
        public Path getDestino() { return destino; }
    }

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(30))
        .followRedirects(HttpClient.Redirect.NORMAL)
        .build();

    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "dl-worker");
        t.setDaemon(true);
        return t;
    });

    private final Deque<Item> fila = new ArrayDeque<>();
    private final AtomicInteger seq = new AtomicInteger(0);
    private final AtomicBoolean workerRodando = new AtomicBoolean(false);
    private final boolean pularExistentes;
    private Consumer<String> log = s -> { };

    public DownloadManager(boolean pularExistentes) {
        this.pularExistentes = pularExistentes;
    }

    public void setLog(Consumer<String> log) {
        this.log = log;
    }

    public synchronized Item enfileirar(Game game, Path pasta) {
        Item it = new Item(seq.incrementAndGet(), game, pasta);
        fila.addLast(it);
        garantirWorker();
        return it;
    }

    public synchronized List<Item> snapshot() {
        return List.copyOf(fila);
    }

    public void pausar(Item it) {
        if (it.estado == Estado.BAIXANDO) {
            it.pausado.set(true);
            setEstado(it, Estado.PAUSADO, "pausado");
        }
    }

    public void continuar(Item it) {
        if (it.estado == Estado.PAUSADO) {
            it.pausado.set(false);
            synchronized (it) {
                it.notifyAll();
            }
        }
    }

    public void cancelar(Item it) {
        it.cancelado.set(true);
        it.pausado.set(false);
        synchronized (it) {
            it.notifyAll();
        }
    }

    public void limparConcluidos() {
        synchronized (this) {
            fila.removeIf(it -> it.estado == Estado.CONCLUIDO
                || it.estado == Estado.ERRO || it.estado == Estado.CANCELADO);
        }
    }

    private void garantirWorker() {
        if (workerRodando.compareAndSet(false, true)) {
            executor.submit(this::loop);
        }
    }

    private void loop() {
        try {
            while (true) {
                Item prox;
                synchronized (this) {
                    prox = fila.stream().filter(i -> i.estado == Estado.FILA).findFirst().orElse(null);
                    if (prox == null) {
                        return;
                    }
                }
                baixar(prox);
            }
        } finally {
            workerRodando.set(false);
            synchronized (this) {
                boolean resta = fila.stream().anyMatch(i -> i.estado == Estado.FILA);
                if (resta) {
                    garantirWorker();
                }
            }
        }
    }

    private void baixar(Item it) {
        setEstado(it, Estado.BAIXANDO, "baixando");
        log("Baixando " + it.game.getTitulo() + " ...");
        try {
            Path pasta = it.pasta;
            Files.createDirectories(pasta);

            if (pularExistentes) {
                Path existente = acharExistente(pasta, it.game.getTitulo());
                if (existente != null) {
                    it.destino = existente;
                    setEstado(it, Estado.CONCLUIDO, "concluído (já existia)");
                    log("PULADO (já existe): " + it.game.getTitulo());
                    return;
                }
            }

            String urlArquivo = resolverArquivo(it.game.getUrl(), it.game.getTitulo());
            String nomeBase = CatalogService.sanitizar(it.game.getTitulo());
            Path destinoFinal = destinoLivre(pasta, nomeBase, ".iso");
            Path part = destinoFinal.resolveSibling(destinoFinal.getFileName() + ".part");

            long jaBaixados = Files.isRegularFile(part) ? Files.size(part) : 0;
            if (jaBaixados > 0) {
                log("Continuando de onde parou (" + (jaBaixados / 1024 / 1024) + " MB)...");
            }

            HttpRequest.Builder rb = HttpRequest.newBuilder(URI.create(urlArquivo))
                .timeout(Duration.ofSeconds(120))
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126")
                .header("Accept", "*/*")
                .GET();
            if (jaBaixados > 0) {
                rb.header("Range", "bytes=" + jaBaixados + "-");
            }
            HttpResponse<InputStream> resp = http.send(rb.build(), HttpResponse.BodyHandlers.ofInputStream());
            if (resp.statusCode() == 416) {
                Files.move(part, destinoFinal, StandardCopyOption.REPLACE_EXISTING);
                it.destino = destinoFinal;
                setEstado(it, Estado.CONCLUIDO, "concluído");
                return;
            }
            if (resp.statusCode() >= 400) {
                throw new IOException("HTTP " + resp.statusCode() + " em " + urlArquivo);
            }
            boolean retomou = resp.statusCode() == 206;
            long contentLen = resp.headers().firstValueAsLong("Content-Length").orElse(0);
            it.total = (contentLen > 0 && retomou) ? jaBaixados + contentLen : contentLen;
            if (jaBaixados > 0 && !retomou) {
                jaBaixados = 0; // servidor ignorou o Range
            }

            long recebidos = jaBaixados;
            long t0 = System.nanoTime();
            long ultimoEmit = 0;
            StandardOpenOption[] modo = (retomou && jaBaixados > 0)
                ? new StandardOpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.APPEND}
                : new StandardOpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING};
            try (InputStream in = resp.body();
                 OutputStream out = Files.newOutputStream(part, modo)) {
                byte[] buf = new byte[256 * 1024];
                int n;
                while ((n = in.read(buf)) != -1) {
                    if (it.cancelado.get()) {
                        throw new Cancelado();
                    }
                    while (it.pausado.get() && !it.cancelado.get()) {
                        setEstado(it, Estado.PAUSADO, "pausado");
                        synchronized (it) {
                            it.wait(200);
                        }
                        setEstado(it, Estado.BAIXANDO, "baixando");
                    }
                    out.write(buf, 0, n);
                    recebidos += n;
                    it.recebido = recebidos;
                    long agora = System.nanoTime();
                    double dt = (agora - t0) / 1e9;
                    if (dt > 0.5) {
                        it.velocidadeBps = recebidos / dt;
                    }
                    if (agora - ultimoEmit > 500_000_000L) {
                        ultimoEmit = agora;
                        atualizarProgresso(it);
                    }
                }
            }
            Files.move(part, destinoFinal, StandardCopyOption.REPLACE_EXISTING);
            it.destino = destinoFinal;
            setEstado(it, Estado.CONCLUIDO, "concluído");
            log("OK: " + it.game.getTitulo() + " -> " + destinoFinal);
        } catch (Cancelado e) {
            setEstado(it, Estado.CANCELADO, "cancelado");
            log("Cancelado (.part mantido): " + it.game.getTitulo());
        } catch (Exception e) {
            it.erro = String.valueOf(e.getMessage());
            setEstado(it, Estado.ERRO, "erro: " + it.erro);
            log("FALHOU " + it.game.getTitulo() + ": " + e);
        }
    }

    /** Página do jogo -> URL do arquivo (botão Save Game do romsgames ou melhor link). */
    private String resolverArquivo(String urlPagina, String titulo) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(urlPagina))
            .timeout(Duration.ofSeconds(30))
            .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126")
            .GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        String ct = resp.headers().firstValue("Content-Type").orElse("");
        if (!ct.contains("html")) {
            return urlPagina; // já caiu direto no arquivo
        }
        String html = resp.body();
        // romsgames: <button data-media-id> + <form id="download-form">
        if (urlPagina.contains("romsgames.net")) {
            try {
                Document doc = Jsoup.parse(html, urlPagina);
                Element btn = doc.selectFirst("[data-media-id]");
                Element form = doc.selectFirst("form#download-form");
                if (btn != null && form != null) {
                    String mediaId = btn.attr("data-media-id").strip();
                    String action = form.attr("action").strip();
                    if (action.isEmpty()) {
                        action = urlPagina;
                    }
                    String endpoint = action + "?download";
                    String corpo = "mediaId=" + URLEncoder.encode(mediaId, StandardCharsets.UTF_8);
                    HttpRequest post = HttpRequest.newBuilder(URI.create(endpoint))
                        .timeout(Duration.ofSeconds(30))
                        .header("User-Agent", "Mozilla/5.0 Chrome/126")
                        .header("Accept", "application/json")
                        .header("Referer", urlPagina)
                        .header("X-Requested-With", "XMLHttpRequest")
                        .header("Content-Type", "application/x-www-form-urlencoded")
                        .POST(HttpRequest.BodyPublishers.ofString(corpo)).build();
                    HttpResponse<String> pj = http.send(post, HttpResponse.BodyHandlers.ofString());
                    var node = new com.fasterxml.jackson.databind.ObjectMapper().readTree(pj.body());
                    String durl = node.path("downloadUrl").asText("");
                    String dnome = node.path("downloadName").asText("");
                    if (!durl.isEmpty()) {
                        if (!durl.startsWith("http")) {
                            durl = URI.create(urlPagina).resolve(durl).toString();
                        }
                        if (!dnome.isEmpty() && !durl.contains("attach=")) {
                            durl += (durl.contains("?") ? "&" : "?") + "attach=" + URLEncoder.encode(dnome, StandardCharsets.UTF_8);
                        }
                        return durl;
                    }
                }
            } catch (Exception ignored) {
            }
        }
        // fallback: melhor <a> com texto download/baixar
        Document doc = Jsoup.parse(html, urlPagina);
        for (Element a : doc.select("a[href]")) {
            String txt = a.text().toLowerCase();
            String href = a.absUrl("href");
            if (href.isEmpty()) {
                continue;
            }
            if (txt.contains("download") || txt.contains("baixar") || a.hasAttr("download")) {
                return href;
            }
        }
        throw new IOException("Página sem botão de download: " + urlPagina);
    }

    private Path acharExistente(Path pasta, String titulo) {
        String alvo = CatalogService.normalizar(titulo);
        try (var stream = Files.list(pasta)) {
            for (Path p : (Iterable<Path>) stream::iterator) {
                if (!Files.isRegularFile(p)) {
                    continue;
                }
                String nome = p.getFileName().toString();
                if (nome.endsWith(".part") || nome.startsWith(".baixador")) {
                    continue;
                }
                int ponto = nome.lastIndexOf('.');
                String stem = ponto > 0 ? nome.substring(0, ponto) : nome;
                String norm = CatalogService.normalizar(stem);
                if (alvo.equals(norm) || alvo.contains(norm) || norm.contains(alvo)) {
                    return p;
                }
            }
        } catch (IOException ignored) {
        }
        return null;
    }

    private Path destinoLivre(Path pasta, String nomeBase, String extPadrao) {
        Path dest = pasta.resolve(nomeBase + extPadrao);
        if (!Files.exists(dest) && !Files.exists(Path.of(dest + ".part"))) {
            return dest;
        }
        String stem = nomeBase;
        int i = 1;
        while (Files.exists(pasta.resolve(stem + " (" + i + ")" + extPadrao))) {
            i++;
        }
        return pasta.resolve(stem + " (" + i + ")" + extPadrao);
    }

    private void atualizarProgresso(Item it) {
        double frac = it.total > 0 ? (double) it.recebido / it.total : 0;
        String texto;
        if (it.total > 0) {
            long eta = it.velocidadeBps > 0 ? (long) ((it.total - it.recebido) / it.velocidadeBps) : -1;
            texto = String.format("%s • ETA %s • %d%% • %s/%s",
                fmtVel(it.velocidadeBps), fmtEta(eta), (int) (frac * 100),
                fmtBytes(it.recebido), fmtBytes(it.total));
        } else if (it.recebido > 0) {
            texto = String.format("%s • %s baixados", fmtVel(it.velocidadeBps), fmtBytes(it.recebido));
        } else {
            texto = it.estado.name().toLowerCase();
        }
        final double f = Math.max(0, Math.min(1, frac));
        final String t = texto;
        Platform.runLater(() -> {
            it.progresso.set(f);
            it.info.set(t);
        });
    }

    private void setEstado(Item it, Estado e, String infoTexto) {
        it.estado = e;
        Platform.runLater(() -> {
            it.info.set(infoTexto);
            if (e == Estado.CONCLUIDO) {
                it.progresso.set(1);
            }
        });
    }

    private void log(String s) {
        try {
            log.accept(s);
        } catch (Exception ignored) {
        }
    }

    private static String fmtBytes(long n) {
        if (n >= 1024L * 1024 * 1024) {
            return String.format("%.2f GB", n / 1024.0 / 1024 / 1024);
        }
        if (n >= 1024L * 1024) {
            return String.format("%.1f MB", n / 1024.0 / 1024);
        }
        if (n >= 1024) {
            return String.format("%d KB", n / 1024);
        }
        return n + " B";
    }

    private static String fmtVel(double bps) {
        if (bps <= 0) {
            return "—";
        }
        if (bps >= 1024 * 1024) {
            return String.format("%.1f MB/s", bps / 1024 / 1024);
        }
        if (bps >= 1024) {
            return String.format("%d KB/s", (long) (bps / 1024));
        }
        return String.format("%d B/s", (long) bps);
    }

    private static String fmtEta(long s) {
        if (s < 0) {
            return "—";
        }
        if (s >= 3600) {
            return String.format("%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60);
        }
        return String.format("%02d:%02d", s / 60, s % 60);
    }

    private static class Cancelado extends Exception {
    }

    public Future<?> shutdown() {
        return executor.submit(() -> { });
    }
}
