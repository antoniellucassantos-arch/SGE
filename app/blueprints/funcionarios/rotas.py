"""Rotas do cadastro de funcionarios."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.funcionarios import bp
from app.blueprints.funcionarios.formularios import (
    FiltroFuncionarioForm,
    FuncionarioForm,
)
from app.models.pessoas import Funcionario
from app.services import pessoa_service
from app.services.excecoes import ErroArquivo, ErroDominio
from app.utils.arquivos import substituir_imagem
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao
from app.utils.seguranca import gerar_senha_temporaria

PASTA_FOTOS = "funcionarios"

COLUNAS_ORDENAVEIS = {
    "nome": Funcionario.nome_normalizado,
    "registro": Funcionario.matricula_funcional,
    "cargo": Funcionario.cargo,
    "admissao": Funcionario.data_admissao,
    "situacao": Funcionario.situacao,
}

CONTEXTO = {
    "titulo": "Funcionario",
    "titulo_plural": "Funcionarios",
    "icone": "bi-person-badge",
    "descricao": "Equipe administrativa e de apoio da escola.",
    "pasta_fotos": PASTA_FOTOS,
    "parametro_id": "funcionario_id",
    "campo_identificador": "matricula_funcional",
    "rotulo_identificador": "Matricula",
    "endpoints": {
        "listar": "funcionarios.listar",
        "novo": "funcionarios.novo",
        "editar": "funcionarios.editar",
        "detalhe": "funcionarios.detalhe",
        "excluir": "funcionarios.excluir",
        "criar_acesso": "funcionarios.criar_acesso",
    },
    "permissoes": {
        "criar": Permissao.FUNCIONARIO_CRIAR,
        "editar": Permissao.FUNCIONARIO_EDITAR,
        "excluir": Permissao.FUNCIONARIO_EXCLUIR,
    },
}


@bp.route("/")
@login_required
@requer_permissao(Permissao.FUNCIONARIO_VISUALIZAR)
def listar():
    """Lista os funcionarios com busca, filtros e paginacao."""
    form = FiltroFuncionarioForm(request.args, meta={"csrf": False})

    consulta = pessoa_service.funcionarios.listar(
        termo=filtro_texto(form.busca.data),
        situacao=form.situacao.data or None,
        setor=form.setor.data or None,
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


@bp.route("/<int:funcionario_id>")
@login_required
@requer_permissao(Permissao.FUNCIONARIO_VISUALIZAR)
def detalhe(funcionario_id: int):
    """Ficha do funcionario."""
    funcionario = pessoa_service.funcionarios.buscar(funcionario_id)
    return render_template(
        "funcionarios/detalhe.html", ctx=CONTEXTO, funcionario=funcionario
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.FUNCIONARIO_CRIAR)
def novo():
    """Cadastra um novo funcionario."""
    form = FuncionarioForm()

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, None)
            funcionario = pessoa_service.funcionarios.criar(dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Funcionario {funcionario.nome_exibicao} cadastrado "
                f"(matricula {funcionario.matricula_funcional}).",
                "success",
            )
            return redirect(
                url_for("funcionarios.detalhe", funcionario_id=funcionario.id)
            )

    return render_template(
        "funcionarios/formulario.html", ctx=CONTEXTO, form=form, registro=None
    )


@bp.route("/<int:funcionario_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.FUNCIONARIO_EDITAR)
def editar(funcionario_id: int):
    """Edita um funcionario existente."""
    funcionario = pessoa_service.funcionarios.buscar(funcionario_id)
    form = FuncionarioForm(obj=funcionario)

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, funcionario.foto)
            pessoa_service.funcionarios.atualizar(funcionario, dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Cadastro atualizado com sucesso.", "success")
            return redirect(
                url_for("funcionarios.detalhe", funcionario_id=funcionario.id)
            )

    return render_template(
        "funcionarios/formulario.html", ctx=CONTEXTO, form=form, registro=funcionario
    )


@bp.route("/<int:funcionario_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.FUNCIONARIO_EXCLUIR)
def excluir(funcionario_id: int):
    """Exclui logicamente o funcionario."""
    funcionario = pessoa_service.funcionarios.buscar(funcionario_id)
    nome = funcionario.nome_exibicao

    try:
        pessoa_service.funcionarios.excluir(funcionario, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("funcionarios.detalhe", funcionario_id=funcionario_id))

    flash(f"Funcionario {nome} excluido do cadastro.", "success")
    return redirect(url_for("funcionarios.listar"))


@bp.route("/<int:funcionario_id>/acesso", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_CRIAR)
def criar_acesso(funcionario_id: int):
    """Cria a conta de acesso do funcionario com senha temporaria."""
    funcionario = pessoa_service.funcionarios.buscar(funcionario_id)
    senha = gerar_senha_temporaria()

    try:
        usuario = pessoa_service.funcionarios.criar_acesso(funcionario, senha)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Conta criada para {usuario.email}. Senha temporaria: {senha} — "
            "anote agora, ela nao sera exibida novamente. Ajuste o perfil de "
            "acesso em Usuarios, se necessario.",
            "warning",
        )

    return redirect(url_for("funcionarios.detalhe", funcionario_id=funcionario_id))


def _processar_foto(form: FuncionarioForm, foto_atual: str | None) -> str | None:
    if not form.foto.data:
        return foto_atual
    return substituir_imagem(
        form.foto.data,
        foto_atual,
        PASTA_FOTOS,
        prefixo="func",
        quadrada=True,
        largura_maxima=400,
    )
