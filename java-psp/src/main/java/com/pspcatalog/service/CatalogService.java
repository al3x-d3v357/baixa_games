package com.pspcatalog.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.pspcatalog.model.Game;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Carrega catalogo-psp.json, filtra por busca tolerante (sem acento/case)
 * e cruza com a pasta de downloads (badge BAIXADO).
 * Equivalente a downloader.py: carregar_catalogo_cache + filtrar_catalogo + anotar_catalogo.
 */
public class CatalogService {

    private static final Pattern NAO_ALNUM = Pattern.compile("[^a-z0-9]+");
    private static final Pattern ESPACOS = Pattern.compile("\\s+");

    private final ObjectMapper mapper = new ObjectMapper();

    /** Procura o json ao lado do projeto Python, no resources ou no cwd. */
    public List<Game> carregar(Path pastaProjeto) throws IOException {
        Path candidato = acharCatalogo(pastaProjeto);
        if (candidato == null) {
            return new ArrayList<>();
        }
        String texto = Files.readString(candidato, StandardCharsets.UTF_8);
        JsonNode raiz = mapper.readTree(texto);
        JsonNode jogos = raiz.isArray() ? raiz : raiz.get("jogos");
        List<Game> lista = new ArrayList<>();
        if (jogos != null && jogos.isArray()) {
            for (JsonNode n : jogos) {
                Game g = mapper.treeToValue(n, Game.class);
                lista.add(g);
            }
        }
        return lista;
    }

    private Path acharCatalogo(Path pastaProjeto) {
        Path[] tentativas = {
            pastaProjeto.resolve("catalogo-psp.json"),
            pastaProjeto.resolve("..").resolve("catalogo-psp.json").normalize(),
            Path.of("catalogo-psp.json"),
            Path.of("..").resolve("catalogo-psp.json").normalize(),
        };
        // dentro do jar (resources)
        for (Path p : tentativas) {
            try {
                if (Files.isRegularFile(p) && Files.size(p) > 0) {
                    return p;
                }
            } catch (IOException ignored) {
            }
        }
        try (InputStream in = getClass().getResourceAsStream("/catalogo-psp.json")) {
            if (in != null) {
                Path tmp = Files.createTempFile("catalogo-psp", ".json");
                Files.write(tmp, in.readAllBytes());
                tmp.toFile().deleteOnExit();
                return tmp;
            }
        } catch (IOException ignored) {
        }
        return null;
    }

    /** Busca tolerante: "god of war" acha "God-of-War". Vazia = tudo. */
    public List<Game> filtrar(List<Game> catalogo, String busca) {
        String termo = normalizar(busca);
        if (termo.isEmpty()) {
            return new ArrayList<>(catalogo);
        }
        List<Game> out = new ArrayList<>();
        for (Game g : catalogo) {
            if (casa(termo, normalizar(g.getTitulo()))) {
                out.add(g);
            }
        }
        return out;
    }

    private boolean casa(String termo, String alvo) {
        if (termo.isEmpty() || alvo.isEmpty()) {
            return false;
        }
        if (alvo.contains(termo)) {
            return true;
        }
        String[] palavras = termo.split(" ");
        if (palavras.length < 2) {
            return false;
        }
        for (String p : palavras) {
            if (!alvo.contains(p)) {
                return false;
            }
        }
        return true;
    }

    /** Marca jaBaixado comparando stem normalizado com os arquivos da pasta. */
    public void anotarBaixados(List<Game> catalogo, Path pasta) {
        List<String> arquivos = new ArrayList<>();
        try (var stream = Files.list(pasta)) {
            stream.filter(Files::isRegularFile)
                .map(p -> p.getFileName().toString())
                .filter(n -> !n.endsWith(".part") && !n.startsWith(".baixador"))
                .forEach(arquivos::add);
        } catch (IOException e) {
            arquivos.clear();
        }
        List<String> stems = new ArrayList<>();
        for (String a : arquivos) {
            int ponto = a.lastIndexOf('.');
            stems.add(normalizar(ponto > 0 ? a.substring(0, ponto) : a));
        }
        for (Game g : catalogo) {
            String titulo = normalizar(g.getTitulo());
            boolean achou = false;
            String nome = "";
            for (int i = 0; i < stems.size(); i++) {
                String stem = stems.get(i);
                if (titulo.equals(stem) || titulo.contains(stem) || stem.contains(titulo)) {
                    achou = true;
                    nome = arquivos.get(i);
                    break;
                }
            }
            g.setJaBaixado(achou);
            g.setArquivoLocal(nome);
        }
    }

    public static String normalizar(String texto) {
        if (texto == null) {
            return "";
        }
        String s = texto.toLowerCase(Locale.ROOT).trim();
        s = Normalizer.normalize(s, Normalizer.Form.NFD).replaceAll("\\p{M}+", "");
        s = NAO_ALNUM.matcher(s).replaceAll(" ");
        return ESPACOS.matcher(s).replaceAll(" ").trim();
    }

    /** Remove caracteres inválidos para arquivo no Windows. */
    public static String sanitizar(String nome) {
        if (nome == null || nome.isBlank()) {
            return "arquivo";
        }
        String s = nome.trim().replaceAll("[<>:\"/\\\\|?*\\x00-\\x1f]", "_").replaceAll("\\s+", " ").strip();
        s = s.replaceAll("^[. ]+|[. ]+$", "");
        if (s.isEmpty()) {
            s = "arquivo";
        }
        return s.length() > 180 ? s.substring(0, 180) : s;
    }
}
