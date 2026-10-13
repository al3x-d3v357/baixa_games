package com.pspcatalog.ui;

import com.pspcatalog.model.Game;
import com.pspcatalog.service.CoverCache;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.CheckBox;
import javafx.scene.control.Label;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;

import java.util.function.Consumer;

/**
 * Card vertical 180x300: capa 160x220 em cima, título azul embaixo,
 * linha de ação [✓] [Baixar]. Hover azul via style.css (.game-card:hover).
 */
public class GameCard extends VBox {

    private final Game game;
    private final CheckBox check = new CheckBox();

    public GameCard(Game game, CoverCache capas, Consumer<Game> aoBaixar) {
        super(8);
        this.game = game;
        getStyleClass().add("game-card");
        setPrefSize(180, 300);
        setMaxWidth(180);
        setAlignment(Pos.TOP_CENTER);

        ImageView cover = new ImageView();
        cover.setFitWidth(160);
        cover.setFitHeight(220);
        cover.setPreserveRatio(true);
        cover.setSmooth(true);
        Image img = capas.obter(game.getCapa(), 160, 220);
        if (img != null) {
            cover.setImage(img);
        }
        // placeholder escuro quando sem capa (mantém a proporção vertical)
        if (cover.getImage() == null) {
            cover.setStyle("-fx-background-color: #1b2838;");
        }

        String titulo = game.getTitulo();
        if (titulo.length() > 42) {
            titulo = titulo.substring(0, 41) + "…";
        }
        Label lbl = new Label(titulo);
        lbl.getStyleClass().add("game-title");
        lbl.setWrapText(true);
        lbl.setMaxWidth(160);
        lbl.setPrefHeight(40);
        lbl.setAlignment(Pos.CENTER);

        HBox barra = new HBox(6);
        barra.setAlignment(Pos.CENTER);
        check.setSelected(!game.isJaBaixado());
        Button btn = new Button("⬇ Baixar");
        btn.getStyleClass().add("btn-primary");
        btn.setOnAction(e -> aoBaixar.accept(game));
        barra.getChildren().addAll(check, btn);

        if (game.isJaBaixado()) {
            Label badge = new Label("✓ BAIXADO");
            badge.getStyleClass().add("badge-ok");
            getChildren().addAll(cover, lbl, badge, barra);
        } else {
            getChildren().addAll(cover, lbl, barra);
        }
    }

    public Game getGame() {
        return game;
    }

    public boolean isMarcado() {
        return check.isSelected();
    }
}
