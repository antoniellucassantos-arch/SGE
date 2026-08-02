"""Rotas do cadastro de responsaveis."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.responsaveis import bp
from app.blueprints.responsaveis.formularios import (
    FiltroResponsavelForm,
    ResponsavelForm,
)
from app.models.pessoas import Responsavel
from app.services import pessoa_service
from app.services.excecoes import ErroArquivo, ErroDominio
from app.utils.arquivos import responder_arquivo, substituir_imagem
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao
from app.utils.seguranca import gerar_senha_temporaria

PASTA_FOTOS = "responsaveis"

COLUNAS_ORDENAVEIS = {
    "nome": Responsavel.nome_normalizado,
    "situacao": Responsavel.situacao,
    "cadastro": Responsavel.criado_em,
}

CONTEXTO = {
    "titulo": "Responsavel",
    "titulo_plural": "Responsaveis",
    "icone": "bi-person-heart",
    "descricao": "Pais, maes e tutores legais dos alunos.",
    "pasta_fotos": PASTA_FOTOS,
    "parametro_id": "responsavel_id",
    "campo_identificador": None,
    "rotulo_identificador": None,
    "endpoints": {
        "listar": "responsaveis.listar",
        "novo": "responsaveis.novo",
        "editar": "responsaveis.editar",
        "detalhe": "responsaveis.detalhe",
        "excluir": "responsaveis.excluir",
        "criar_acesso": "responsaveis.criar_acesso",
        "foto": "responsaveis.foto",
    },
    "permissoes": {
        "criar": Permissao.RESPONSAVEL_CRIAR,
        "editar": Permissao.RESPONSAVEL_EDITAR,
        "excluir": Permissao.RESPONSAVEL_EXCLUIR,
    },
}


@bp.route("/")
@login_required
@requer_permissao(Permissao.RESPONSAVEL_VISUALIZAR)
def listar():
    """Lista os responsaveis com busca, filtros e paginacao."""
    form = FiltroResponsavelForm(request.args, meta={"csrf": False})

    consulta = pessoa_service.responsaveis.listar(
        termo=filtro_texto(form.busca.data),
        situacao=form.situacao.data or None,
    )
    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="nome"
    )

    return render_template(
        "pessoas/listar.html",
        ctx=CONTEXTO,
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
    )


@bp.route("/<int:responsavel_id>")
@login_required
@requer_permissao(Permissao.RESPONSAVEL_VISUALIZAR)
def detalhe(responsavel_id: int):
    """Ficha do responsavel com os alunos vinculados."""
    responsavel = pessoa_service.responsaveis.buscar(responsavel_id)
    return render_template(
        "responsaveis/detalhe.html", ctx=CONTEXTO, responsavel=responsavel
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.RESPONSAVEL_CRIAR)
def novo():
    """Cadastra um novo responsavel."""
    form = ResponsavelForm()

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, None)
            responsavel = pessoa_service.responsaveis.criar(dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Responsavel {responsavel.nome_exibicao} cadastrado. "
                "Vincule-o aos alunos pela ficha de cada aluno.",
                "success",
            )
            return redirect(
                url_for("responsaveis.detalhe", responsavel_id=responsavel.id)
            )

    return render_template(
        "responsaveis/formulario.html", ctx=CONTEXTO, form=form, registro=None
    )


@bp.route("/<int:responsavel_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.RESPONSAVEL_EDITAR)
def editar(responsavel_id: int):
    """Edita um responsavel existente."""
    responsavel = pessoa_service.responsaveis.buscar(responsavel_id)
    form = ResponsavelForm(obj=responsavel)

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, responsavel.foto)
            pessoa_service.responsaveis.atualizar(responsavel, dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Cadastro atualizado com sucesso.", "success")
            return redirect(
                url_for("responsaveis.detalhe", responsavel_id=responsavel.id)
            )

    return render_template(
        "responsaveis/formulario.html", ctx=CONTEXTO, form=form, registro=responsavel
    )


@bp.route("/<int:responsavel_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.RESPONSAVEL_EXCLUIR)
def excluir(responsavel_id: int):
    """Exclui logicamente o responsavel."""
    responsavel = pessoa_service.responsaveis.buscar(responsavel_id)
    nome = responsavel.nome_exibicao

    try:
        pessoa_service.responsaveis.excluir(responsavel, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("responsaveis.detalhe", responsavel_id=responsavel_id))

    flash(f"Responsavel {nome} excluido do cadastro.", "success")
    return redirect(url_for("responsaveis.listar"))


@bp.route("/<int:responsavel_id>/acesso", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_CRIAR)
def criar_acesso(responsavel_id: int):
    """Cria a conta de acesso do responsavel ao portal de acompanhamento."""
    responsavel = pessoa_service.responsaveis.buscar(responsavel_id)
    senha = gerar_senha_temporaria()

    try:
        usuario = pessoa_service.responsaveis.criar_acesso(responsavel, senha)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Acesso criado para {usuario.email}. Senha temporaria: {senha} — "
            "anote agora, ela nao sera exibida novamente. O responsavel podera "
            "acompanhar boletim, frequencia e avisos dos alunos vinculados.",
            "warning",
        )

    return redirect(url_for("responsaveis.detalhe", responsavel_id=responsavel_id))


def _processar_foto(form: ResponsavelForm, foto_atual: str | None) -> str | None:
    if not form.foto.data:
        return foto_atual
    return substituir_imagem(
        form.foto.data,
        foto_atual,
        PASTA_FOTOS,
        prefixo="resp",
        quadrada=True,
        largura_maxima=400,
    )


@bp.route("/<int:responsavel_id>/foto")
@login_required
@requer_permissao(Permissao.RESPONSAVEL_VISUALIZAR)
def foto(responsavel_id: int):
    """Entrega a foto do responsavel a quem pode visualizar o cadastro."""
    responsavel = pessoa_service.responsaveis.buscar(responsavel_id)
    return responder_arquivo(PASTA_FOTOS, responsavel.foto)
