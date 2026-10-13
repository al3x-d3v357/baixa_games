package com.pspcatalog.service;

import javafx.application.Platform;
import javafx.scene.image.Image;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Cache de capas em disco (capas/ + md5 da URL) e em memória.
 * Equivale a downloader.py: baixar_capa + app.py: caminho_capa_local + _thumbs.
 */
public class CoverCache {

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(15))
        .followRedirects(HttpClient.Redirect.NORMAL)
        .build();

    private final Path pastaCapas;
    private final Map<String, Image> memoria = new ConcurrentHashMap<>();

    public CoverCache(Path pastaProjeto) {
        this.pastaCapas = pastaProjeto.resolve("capas");
        try {
            Files.createDirectories(pastaCapas);
        } catch (IOException ignored) {
        }
    }

    /** Capa 160x220 com cover-fit (sem distorcer), ou null se ausente. */
    public Image obter(String urlCapa, int larg, int alt) {
        if (urlCapa == null || urlCapa.isBlank()) {
            return null;
        }
        String chave = urlCapa + "|" + larg + "x" + alt;
        Image hit = memoria.get(chave);
        if (hit != null) {
            return hit;
        }
        try {
            Path local = garantirLocal(urlCapa);
            if (local == null) {
                return null;
            }
            try (InputStream in = Files.newInputStream(local)) {
                // fundo escuro + preserveRatio faz o cover-fit na ImageView;
                // aqui só limitamos a largura pedida.
                Image img = new Image(in, larg, alt, true, true);
                if (!img.isError()) {
                    memoria.put(chave, img);
                    return img;
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /** Baixa em background e avisa na thread JavaFX para trocar a imagem. */
    public void preAquecer(java.util.List<com.pspcatalog.model.Game> jogos, Runnable aoTerminar) {
        Thread t = new Thread(() -> {
            for (var j : jogos) {
                try {
                    garantirLocal(j.getCapa());
                } catch (Exception ignored) {
                }
            }
            if (aoTerminar != null) {
                Platform.runLater(aoTerminar);
            }
        }, "capas-loader");
        t.setDaemon(true);
        t.start();
    }

    private Path garantirLocal(String urlCapa) throws Exception {
        if (urlCapa == null || urlCapa.isBlank()) {
            return null;
        }
        String ext = extensao(urlCapa);
        String nome = md5(urlCapa) + ext;
        Path dest = pastaCapas.resolve(nome);
        if (Files.isRegularFile(dest) && Files.size(dest) > 0) {
            return dest;
        }
        HttpRequest req = HttpRequest.newBuilder(URI.create(urlCapa))
            .timeout(Duration.ofSeconds(15))
            .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126")
            .GET().build();
        HttpResponse<byte[]> resp = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
        if (resp.statusCode() >= 400) {
            return null;
        }
        String ct = resp.headers().firstValue("Content-Type").orElse("");
        if (!ct.contains("image")) {
            return null;
        }
        byte[] corpo = resp.body();
        if (corpo == null || corpo.length == 0) {
            return null;
        }
        Files.write(dest, corpo);
        return dest;
    }

    private static String extensao(String url) {
        try {
            String path = URI.create(url).getPath();
            int ponto = path.lastIndexOf('.');
            String ext = ponto >= 0 ? path.substring(ponto).toLowerCase() : ".jpg";
            if (ext.length() > 5 || !ext.matches("\\.[a-z0-9]+")) {
                return ".jpg";
            }
            return ext;
        } catch (Exception e) {
            return ".jpg";
        }
    }

    private static String md5(String s) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        byte[] digest = md.digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return HexFormat.of().formatHex(digest);
    }
}
