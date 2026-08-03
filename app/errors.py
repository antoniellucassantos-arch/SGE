"""Tratamento de erro da aplicacao.

Regra que vale para todos os handlers: nunca expor rastro de pilha ao
usuario, e nunca transformar uma falha em resposta de sucesso. O codigo HTTP
e a unica coisa que o monitoramento e o cliente JSON enxergam.
"""

from __future__ import annotations

from flask import Flask, render_template, request

from app.extensions import db


def prefere_json() -> bool:
    """Decide se o cliente espera JSON em vez de HTML.

    Fica aqui, e nao dentro do registrador de handlers, porque os hooks de
    requisicao precisam da mesma decisao. Duas copias dessa regra
    divergiriam na primeira mudanca.
    """
    return (
        request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def configurar_handlers_erro(app: Flask) -> None:
    """Paginas de erro amigaveis; nunca expor rastro de pilha ao usuario."""
    from app.services.excecoes import ErroDominio

    @app.errorhandler(400)
    def erro_400(erro):
        if prefere_json():
            return {"erro": "Requisicao invalida"}, 400
        return render_template("erros/400.html"), 400

    @app.errorhandler(403)
    def erro_403(erro):
        if prefere_json():
            return {"erro": "Acesso negado"}, 403
        return render_template("erros/403.html"), 403

    @app.errorhandler(404)
    def erro_404(erro):
        if prefere_json():
            return {"erro": "Recurso nao encontrado"}, 404
        return render_template("erros/404.html"), 404

    @app.errorhandler(413)
    def erro_413(erro):
        limite = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        if prefere_json():
            return {"erro": f"Arquivo maior que {limite} MB"}, 413
        return render_template("erros/413.html", limite_mb=limite), 413

    @app.errorhandler(429)
    def erro_429(erro):
        if prefere_json():
            return {"erro": "Muitas requisicoes. Aguarde um instante."}, 429
        return render_template("erros/429.html"), 429

    @app.errorhandler(500)
    def erro_500(erro):
        # Rollback obrigatorio: sem ele a sessao fica "suja" e todas as
        # requisicoes seguintes desta conexao falhariam em cascata.
        db.session.rollback()
        app.logger.exception("Erro interno nao tratado")
        if prefere_json():
            return {"erro": "Erro interno do servidor"}, 500
        return render_template("erros/500.html"), 500

    @app.errorhandler(ErroDominio)
    def erro_dominio(erro: ErroDominio):
        """Converte excecoes de negocio em resposta adequada ao cliente."""
        app.logger.info("Erro de dominio: %s", erro.mensagem)

        # Um `ErroPermissao` vindo do service e um acesso negado como
        # qualquer outro. Os decoradores ja registravam o evento; quem
        # levanta a excecao no meio do fluxo, nao — e e justamente o caso
        # das validacoes de escopo por querystring, o vetor mais provavel de
        # tentativa de leitura de dados alheios.
        if erro.codigo_http == 403:
            from app.services.auditoria_service import registrar_acesso_negado

            registrar_acesso_negado(erro.mensagem)

        if prefere_json():
            return {"erro": erro.mensagem}, erro.codigo_http

        # Falhas de autorizacao e recursos inexistentes devolvem o codigo HTTP
        # correto, e nao um redirect com mensagem. Motivos:
        #   1. Um 302 sinalizaria "sua requisicao foi aceita", quando na
        #      verdade foi negada — enganoso para o usuario e para o cliente.
        #   2. Monitoramento e testes precisam distinguir acesso negado de
        #      navegacao normal.
        #
        # A pagina e renderizada aqui, e nao com ``abort()``: uma excecao
        # levantada dentro de um error handler nao e redespachada pelo Flask
        # para outro handler — ela sobe como erro nao tratado.
        from flask import flash, redirect

        from app.utils.navegacao import destino_seguro

        if erro.codigo_http in (403, 404):
            return (
                render_template(f"erros/{erro.codigo_http}.html"),
                erro.codigo_http,
            )

        # Falha de infraestrutura (ErroOperacaoBanco) nao pode virar um 302
        # silencioso: sem status 5xx e sem stack trace, o incidente jamais
        # aparece no monitoramento.
        if erro.codigo_http >= 500:
            db.session.rollback()
            app.logger.exception(
                "Erro de dominio com falha interna: %s", erro.mensagem
            )
            return render_template("erros/500.html"), erro.codigo_http

        # Erros de regra de negocio (capacidade da turma, matricula
        # duplicada) sao previsiveis e corrigiveis: a pessoa volta para onde
        # estava, com a explicacao do que impediu a operacao.
        #
        # Erros por campo, quando houver, sao exibidos junto da mensagem
        # principal — sem isso o usuario recebe "dados invalidos" e nao
        # descobre qual campo corrigir.
        flash(erro.mensagem, "danger")
        for campo, mensagens in getattr(erro, "erros_por_campo", {}).items():
            for mensagem in mensagens:
                flash(f"{campo}: {mensagem}", "warning")

        # O Referer e controlado pelo cliente: sem validacao, um link que
        # dispare um erro previsivel joga o usuario autenticado para fora.
        return redirect(destino_seguro(request.referrer))


__all__ = ["configurar_handlers_erro", "prefere_json"]
