"""Rotas do cadastro de professores."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.professores import bp
from app.blueprints.professores.formularios import (
    FiltroProfessorForm,
    ProfessorForm,
)
from app.extensions import db
from app.models.estrutura import Turma, TurmaDisciplina
from app.models.pessoas import Professor
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

PASTA_FOTOS = "professores"

COLUNAS_ORDENAVEIS = {
    "nome": Professor.nome_normalizado,
    "registro": Professor.registro_funcional,
    "admissao": Professor.data_admissao,
    "situacao": Professor.situacao,
}

#: Contexto que parametriza os templates genericos de cadastro de pessoas.
CONTEXTO = {
    "titulo": "Professor",
    "titulo_plural": "Professores",
    "icone": "bi-person-video3",
    "descricao": "Corpo docente, formacao e disciplinas atribuidas.",
    "pasta_fotos": PASTA_FOTOS,
    "parametro_id": "professor_id",
    "campo_identificador": "registro_funcional",
    "rotulo_identificador": "Registro",
    "endpoints": {
        "listar": "professores.listar",
        "novo": "professores.novo",
        "editar": "professores.editar",
        "detalhe": "professores.detalhe",
        "excluir": "professores.excluir",
        "criar_acesso": "professores.criar_acesso",
        "foto": "professores.foto",
    },
    "permissoes": {
        "criar": Permissao.PROFESSOR_CRIAR,
        "editar": Permissao.PROFESSOR_EDITAR,
        "excluir": Permissao.PROFESSOR_EXCLUIR,
    },
}


@bp.route("/")
@login_required
@requer_permissao(Permissao.PROFESSOR_VISUALIZAR)
def listar():
    """Lista os professores com busca, filtros e paginacao."""
    form = FiltroProfessorForm(request.args, meta={"csrf": False})

    consulta = pessoa_service.professores.listar(
        termo=filtro_texto(form.busca.data),
        situacao=form.situacao.data or None,
        titulacao=form.titulacao.data or None,
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


@bp.route("/<int:professor_id>")
@login_required
@requer_permissao(Permissao.PROFESSOR_VISUALIZAR)
def detalhe(professor_id: int):
    """Ficha do professor com as turmas e disciplinas atribuidas."""
    professor = pessoa_service.professores.buscar(professor_id)
    ano_letivo = getattr(g, "ano_letivo", None)

    consulta = (
        db.session.query(TurmaDisciplina)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            TurmaDisciplina.professor_id == professor.id,
            Turma.excluido_em.is_(None),
        )
    )
    if ano_letivo:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo.id)

    return render_template(
        "professores/detalhe.html",
        ctx=CONTEXTO,
        professor=professor,
        vinculos=consulta.all(),
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.PROFESSOR_CRIAR)
def novo():
    """Cadastra um novo professor."""
    form = ProfessorForm()

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, None)
            professor = pessoa_service.professores.criar(dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Professor {professor.nome_exibicao} cadastrado "
                f"(registro {professor.registro_funcional}).",
                "success",
            )
            return redirect(
                url_for("professores.detalhe", professor_id=professor.id)
            )

    return render_template(
        "professores/formulario.html", ctx=CONTEXTO, form=form, registro=None
    )


@bp.route("/<int:professor_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.PROFESSOR_EDITAR)
def editar(professor_id: int):
    """Edita um professor existente."""
    professor = pessoa_service.professores.buscar(professor_id)
    form = ProfessorForm(obj=professor)

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, professor.foto)
            pessoa_service.professores.atualizar(professor, dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Cadastro atualizado com sucesso.", "success")
            return redirect(
                url_for("professores.detalhe", professor_id=professor.id)
            )

    return render_template(
        "professores/formulario.html", ctx=CONTEXTO, form=form, registro=professor
    )


@bp.route("/<int:professor_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.PROFESSOR_EXCLUIR)
def excluir(professor_id: int):
    """Exclui logicamente o professor."""
    professor = pessoa_service.professores.buscar(professor_id)
    nome = professor.nome_exibicao

    try:
        pessoa_service.professores.excluir(professor, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("professores.detalhe", professor_id=professor_id))

    flash(f"Professor {nome} excluido do cadastro.", "success")
    return redirect(url_for("professores.listar"))


@bp.route("/<int:professor_id>/acesso", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_CRIAR)
def criar_acesso(professor_id: int):
    """Cria a conta de acesso do professor com senha temporaria."""
    professor = pessoa_service.professores.buscar(professor_id)
    senha = gerar_senha_temporaria()

    try:
        usuario = pessoa_service.professores.criar_acesso(professor, senha)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        # A senha aparece uma unica vez, para a secretaria repassar ao
        # professor. Ela nao fica armazenada em texto puro em lugar nenhum.
        flash(
            f"Conta criada para {usuario.email}. Senha temporaria: {senha} — "
            "anote agora, ela nao sera exibida novamente. A troca sera "
            "exigida no primeiro acesso.",
            "warning",
        )

    return redirect(url_for("professores.detalhe", professor_id=professor_id))


def _processar_foto(form: ProfessorForm, foto_atual: str | None) -> str | None:
    if not form.foto.data:
        return foto_atual
    return substituir_imagem(
        form.foto.data,
        foto_atual,
        PASTA_FOTOS,
        prefixo="prof",
        quadrada=True,
        largura_maxima=400,
    )


@bp.route("/<int:professor_id>/foto")
@login_required
@requer_permissao(Permissao.PROFESSOR_VISUALIZAR)
def foto(professor_id: int):
    """Entrega a foto do professor a quem pode visualizar o cadastro."""
    professor = pessoa_service.professores.buscar(professor_id)
    return responder_arquivo(PASTA_FOTOS, professor.foto)
