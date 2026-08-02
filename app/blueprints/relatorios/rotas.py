"""Rotas de relatorios e exportacoes."""

from __future__ import annotations

from flask import g, render_template, request
from flask_login import current_user, login_required

from app.blueprints.relatorios import bp
from app.extensions import db
from app.services import (
    auditoria_service,
    pdf_service,
    relatorio_service,
    turma_service,
)
from app.services.excecoes import (
    ErroPermissao,
    RegistroNaoEncontrado,
)
from app.utils.decoradores import pode_acessar_turma, requer_permissao
from app.utils.permissoes import Permissao, usuario_tem_permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


def _definicao(chave: str) -> dict:
    """Recupera a definicao do relatorio, exigindo a permissao especifica.

    Cada relatorio declara a propria permissao (``relatorio.academico`` ou
    ``relatorio.administrativo``). Checar apenas ``RELATORIO_EXPORTAR`` nas
    rotas de exportacao permitiria pular a tela de visualizacao e baixar
    qualquer relatorio — por isso a checagem vive aqui, em um unico lugar
    usado pelas tres rotas.
    """
    definicao = relatorio_service.RELATORIOS.get(chave)
    if definicao is None:
        raise RegistroNaoEncontrado("Relatorio nao encontrado.")

    if not usuario_tem_permissao(current_user, definicao["permissao"]):
        raise ErroPermissao(
            "Voce nao tem permissao para acessar este relatorio."
        )

    return definicao


def _filtros_da_url() -> dict:
    """Le e **valida** os filtros vindos da querystring.

    O ``turma_id`` chega pela URL e nao passa por nenhum decorador de rota —
    ``exigir_acesso_turma()`` le de ``kwargs`` (parametros de rota), nao de
    ``request.args``. Sem a validacao explicita abaixo, um professor com
    permissao de relatorio academico acessava as notas de qualquer turma da
    escola apenas trocando o numero na barra de enderecos.
    """
    ano = request.args.get("ano_letivo_id", "")
    turma = request.args.get("turma_id", "")

    turma_id = int(turma) if turma.isdigit() else None
    if turma_id is not None and not pode_acessar_turma(turma_id):
        raise ErroPermissao("Voce nao tem acesso aos dados desta turma.")

    return {
        "ano_letivo_id": int(ano) if ano.isdigit() else _ano_letivo_id(),
        "turma_id": turma_id,
        "situacao": request.args.get("situacao") or None,
    }


def _auditar_exportacao(dados: dict, formato: str, filtros: dict) -> None:
    """Registra a exportacao **antes** de entregar o arquivo.

    Duas razoes para registrar antes:

    1. Uma falha na geracao nao pode resultar em exportacao nao auditada —
       a tentativa de extrair dados pessoais ja e o evento relevante.
    2. A LGPD exige saber *o que* saiu. Titulo e quantidade nao bastam:
       sem os filtros aplicados nao ha como reconstituir quais alunos
       estavam no arquivo.
    """
    auditoria_service.registrar_exportacao(
        dados["titulo"],
        formato,
        len(dados["linhas"]),
    )
    auditoria_service.registrar(
        auditoria_service.AcaoAuditoria.EXPORTACAO,
        descricao=f"Filtros da exportacao: {dados['titulo']} ({formato})",
        detalhes={
            "ano_letivo_id": filtros.get("ano_letivo_id"),
            "turma_id": filtros.get("turma_id"),
            "situacao": filtros.get("situacao"),
            "registros": len(dados["linhas"]),
        },
    )
    _confirmar()


def _confirmar() -> None:
    """Confirma a transacao da auditoria sem derrubar a entrega do arquivo."""
    from flask import current_app

    try:
        db.session.commit()
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("Falha ao auditar exportacao: %s", erro)


# ---------------------------------------------------------------------------
# Catalogo e visualizacao
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(
    Permissao.RELATORIO_ACADEMICO, Permissao.RELATORIO_ADMINISTRATIVO
)
def index():
    """Catalogo de relatorios disponiveis ao usuario."""
    disponiveis = {
        chave: dados
        for chave, dados in relatorio_service.RELATORIOS.items()
        if usuario_tem_permissao(current_user, dados["permissao"])
    }

    return render_template("relatorios/index.html", relatorios=disponiveis)


@bp.route("/<chave>")
@login_required
@requer_permissao(
    Permissao.RELATORIO_ACADEMICO, Permissao.RELATORIO_ADMINISTRATIVO
)
def visualizar(chave: str):
    """Exibe um relatorio em tela."""
    definicao = _definicao(chave)
    filtros = _filtros_da_url()
    dados = relatorio_service.gerar_dados(chave, **filtros)

    return render_template(
        "relatorios/visualizar.html",
        chave=chave,
        definicao=definicao,
        dados=dados,
        filtros=filtros,
        anos=turma_service.anos_letivos(),
        # O <select> so pode oferecer as turmas do escopo do usuario: alem de
        # nao vazar os nomes, evita entregar a lista de ids validos para
        # manipulacao da querystring.
        turmas=turma_service.listar_turmas(
            ano_letivo_id=filtros["ano_letivo_id"],
            somente_ativas=True,
            usuario=current_user,
        ).all(),
    )


# ---------------------------------------------------------------------------
# Exportacoes
# ---------------------------------------------------------------------------
@bp.route("/<chave>/excel")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_excel(chave: str):
    """Exporta o relatorio em planilha Excel."""
    _definicao(chave)  # valida a permissao especifica do relatorio
    filtros = _filtros_da_url()
    dados = relatorio_service.gerar_dados(chave, **filtros)

    _auditar_exportacao(dados, "Excel", filtros)

    buffer = relatorio_service.gerar_excel(dados)
    return relatorio_service.responder_excel(
        buffer, f"relatorio_{chave}.xlsx"
    )


@bp.route("/<chave>/pdf")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_pdf(chave: str):
    """Exporta o relatorio em PDF."""
    _definicao(chave)
    filtros = _filtros_da_url()
    dados = relatorio_service.gerar_dados(chave, **filtros)

    # Auditoria antes da geracao: um PDF que falha ao renderizar nao pode
    # resultar em tentativa de exportacao sem registro.
    _auditar_exportacao(dados, "PDF", filtros)

    buffer = pdf_service.gerar_listagem(
        titulo=dados["titulo"],
        cabecalhos=dados["cabecalhos"],
        linhas=dados["linhas"],
        orientacao_paisagem=dados.get("paisagem", False),
        observacao=dados.get("observacao"),
    )

    return pdf_service.responder_pdf(buffer, f"relatorio_{chave}.pdf")


# ---------------------------------------------------------------------------
# Atalhos usados por outras telas
# ---------------------------------------------------------------------------
#: Parametros que fazem sentido repassar de uma listagem para a exportacao.
FILTROS_REPASSAVEIS = ("ano_letivo_id", "turma_id", "situacao")


@bp.route("/exportar/alunos")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_alunos():
    """Exporta a listagem de alunos com os filtros da tela de alunos."""
    from flask import redirect, url_for

    # Repassar `**request.args` cru colidiria com o parametro `chave` da
    # rota de destino (`?chave=x` -> TypeError -> 500).
    filtros = {
        nome: valor
        for nome, valor in request.args.items()
        if nome in FILTROS_REPASSAVEIS and valor
    }

    return redirect(
        url_for("relatorios.exportar_excel", chave="alunos", **filtros)
    )


@bp.route("/frequencia")
@login_required
@requer_permissao(Permissao.RELATORIO_ACADEMICO)
def frequencia():
    """Atalho para o relatorio de frequencia em risco."""
    from flask import redirect, url_for

    return redirect(url_for("relatorios.visualizar", chave="frequencia"))
