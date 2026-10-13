package com.pspcatalog.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** Um jogo do catálogo. Espelha catalogo-psp.json: {titulo, url, capa}. */
@JsonIgnoreProperties(ignoreUnknown = true)
public class Game {

    @JsonProperty("titulo")
    private String titulo = "";

    @JsonProperty("url")
    private String url = "";

    @JsonProperty("capa")
    private String capa = "";

    private boolean jaBaixado = false;
    private String arquivoLocal = "";

    public Game() {
    }

    public Game(String titulo, String url, String capa) {
        this.titulo = titulo;
        this.url = url;
        this.capa = capa;
    }

    public String getTitulo() {
        return titulo == null ? "" : titulo;
    }

    public String getUrl() {
        return url == null ? "" : url;
    }

    public String getCapa() {
        return capa == null ? "" : capa;
    }

    public boolean isJaBaixado() {
        return jaBaixado;
    }

    public void setJaBaixado(boolean jaBaixado) {
        this.jaBaixado = jaBaixado;
    }

    public String getArquivoLocal() {
        return arquivoLocal;
    }

    public void setArquivoLocal(String arquivoLocal) {
        this.arquivoLocal = arquivoLocal;
    }

    @Override
    public String toString() {
        return getTitulo();
    }
}
