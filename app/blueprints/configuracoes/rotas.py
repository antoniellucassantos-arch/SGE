"""Rotas de configuracao do sistema."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.blueprints.configuracoes import bp
from app.blueprints.configuracoes.formularios import (
    AnoLetivoForm,
    EscolaForm,
    ParametrosForm,
    SalaForm,
    SerieForm,
    TempoAulaForm,
)
from app.extensions import db
from app.models.estrutura import PeriodoLetivo, Sala, Serie
from app.models.horario import TempoAula
from app.services import configuracao_service
from app.services.excecoes import ErroArquivo, ErroDominio, RegistroNaoEncontrado
from app.utils.arquivos import responder_arquivo, substituir_imagem
from app.utils.decoradores import requer_permissao
from app.utils.permissoes import Permissao

PASTA_LOGO = "escola"


# ---------------------------------------------------------------------------
# Dados da escola
# ---------------------------------------------------------------------------
@bp.route("/", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_VISUALIZAR)
def index():
    """Dados institucionais da escola."""
    escola = configuracao_service.obter_escola()
    form = EscolaForm(obj=escola)
    somente_leitura = not _pode_editar()

    if form.validate_on_submit():
        if somente_leitura:
            flash("Voce nao tem permissao para alterar as configuracoes.", "danger")
            return redirect(url_for("configuracoes.index"))

        try:
            dados = form.dados_limpos()
            if form.logo.data:
                dados["logo"] = substituir_imagem(
                    form.logo.data,
                    escola.logo,
                    PASTA_LOGO,
                    prefixo="logo",
                    largura_maxima=400,
                )
            configuracao_service.atualizar_escola(dados)
        except ErroArquivo as erro:
            form.logo.errors.append(erro.mensagem)
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash("Dados da escola atualizados.", "success")
            return redirect(url_for("configuracoes.index"))

    return render_template(
        "configuracoes/escola.html",
        form=form,
        escola=escola,
        somente_leitura=somente_leitura,
    )


def _pode_editar() -> bool:
    from flask_login import current_user

    from app.utils.permissoes import usuario_tem_permissao

    return usuario_tem_permissao(current_user, Permissao.CONFIGURACAO_EDITAR)


@bp.route("/parametros", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_VISUALIZAR)
def parametros():
    """Parametros academicos padrao."""
    escola = configuracao_service.obter_escola()
    form = ParametrosForm(obj=escola)
    somente_leitura = not _pode_editar()

    if not form.is_submitted():
        form.quantidade_periodos.data = str(escola.quantidade_periodos or 4)

    if form.validate_on_submit():
        if somente_leitura:
            flash("Voce nao tem permissao para alterar as configuracoes.", "danger")
            return redirect(url_for("configuracoes.parametros"))

        dados = form.dados_limpos()
        dados["quantidade_periodos"] = int(dados.get("quantidade_periodos") or 4)

        try:
            configuracao_service.atualizar_escola(dados)
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash(
                "Parametros salvos. Eles valem como padrao para novos anos "
                "letivos; anos ja criados mantem as proprias regras.",
                "success",
            )
            return redirect(url_for("configuracoes.parametros"))

    return render_template(
        "configuracoes/parametros.html", form=form, somente_leitura=somente_leitura
    )


# ---------------------------------------------------------------------------
# Anos letivos
# ---------------------------------------------------------------------------
@bp.route("/anos-letivos")
@login_required
@requer_permissao(Permissao.CONFIGURACAO_VISUALIZAR)
def anos_letivos():
    """Lista os anos letivos cadastrados."""
    return render_template(
        "configuracoes/anos_letivos.html",
        anos=configuracao_service.listar_anos(),
        pode_editar=_pode_editar(),
    )


@bp.route("/anos-letivos/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def novo_ano_letivo():
    """Cria um ano letivo com os periodos padrao."""
    form = AnoLetivoForm()

    if not form.is_submitted():
        escola = configuracao_service.obter_escola()
        form.media_aprovacao.data = escola.media_aprovacao
        form.media_recuperacao.data = escola.media_recuperacao
        form.frequencia_minima.data = escola.frequencia_minima

    if form.validate_on_submit():
        try:
            ano = configuracao_service.criar_ano_letivo(form.dados_limpos())
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Ano letivo {ano.ano} criado com "
                f"{len(ano.periodos)} periodo(s).",
                "success",
            )
            return redirect(url_for("configuracoes.anos_letivos"))

    return render_template("configuracoes/ano_letivo_form.html", form=form, ano=None)


@bp.route("/anos-letivos/<int:ano_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def editar_ano_letivo(ano_id: int):
    """Edita um ano letivo e seus periodos."""
    ano = configuracao_service.buscar_ano(ano_id)
    form = AnoLetivoForm(obj=ano)

    if not form.is_submitted():
        form.situacao.data = ano.situacao.value

    if form.validate_on_submit():
        try:
            configuracao_service.atualizar_ano_letivo(ano, form.dados_limpos())
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash("Ano letivo atualizado.", "success")
            return redirect(url_for("configuracoes.anos_letivos"))

    return render_template("configuracoes/ano_letivo_form.html", form=form, ano=ano)


@bp.route("/anos-letivos/<int:ano_id>/definir-corrente", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def definir_ano_corrente(ano_id: int):
    """Define o ano letivo usado como contexto padrao do sistema."""
    ano = configuracao_service.buscar_ano(ano_id)

    try:
        configuracao_service.definir_como_corrente(ano)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(f"Ano letivo {ano.ano} definido como corrente.", "success")

    return redirect(url_for("configuracoes.anos_letivos"))


@bp.route("/anos-letivos/<int:ano_id>/encerrar", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def encerrar_ano_letivo(ano_id: int):
    """Encerra o ano letivo e bloqueia novos lancamentos."""
    ano = configuracao_service.buscar_ano(ano_id)

    try:
        configuracao_service.encerrar_ano_letivo(ano)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Ano letivo {ano.ano} encerrado. Notas e frequencia deste ano "
            "passam a ser somente leitura.",
            "success",
        )

    return redirect(url_for("configuracoes.anos_letivos"))


@bp.route("/anos-letivos/<int:ano_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def excluir_ano_letivo(ano_id: int):
    """Exclui um ano letivo sem turmas."""
    ano = configuracao_service.buscar_ano(ano_id)
    numero = ano.ano

    try:
        configuracao_service.excluir_ano_letivo(ano)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(f"Ano letivo {numero} excluido.", "success")

    return redirect(url_for("configuracoes.anos_letivos"))


@bp.route("/periodos/<int:periodo_id>/alternar", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def alternar_periodo(periodo_id: int):
    """Abre ou encerra um periodo para lancamento de notas."""
    periodo = db.session.get(PeriodoLetivo, periodo_id)
    if periodo is None:
        raise RegistroNaoEncontrado("Periodo nao encontrado.")

    configuracao_service.alternar_periodo(periodo)
    flash(
        f"Periodo {periodo.nome} "
        f"{'encerrado' if periodo.encerrado else 'reaberto'}.",
        "success",
    )
    return redirect(url_for("configuracoes.anos_letivos"))


# ---------------------------------------------------------------------------
# Estrutura: series, salas e tempos de aula
# ---------------------------------------------------------------------------
@bp.route("/estrutura", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_VISUALIZAR)
def estrutura():
    """Series, salas e tempos de aula em uma unica tela."""
    form_serie = SerieForm()
    form_sala = SalaForm()
    form_tempo = TempoAulaForm()

    return render_template(
        "configuracoes/estrutura.html",
        series=configuracao_service.listar_series(),
        salas=configuracao_service.listar_salas(),
        tempos=configuracao_service.listar_tempos(),
        form_serie=form_serie,
        form_sala=form_sala,
        form_tempo=form_tempo,
        pode_editar=_pode_editar(),
    )


@bp.route("/series", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def salvar_serie():
    """Cria ou atualiza uma serie."""
    serie_id = request.form.get("serie_id", "")
    serie = db.session.get(Serie, int(serie_id)) if serie_id.isdigit() else None

    form = SerieForm()
    if not form.validate_on_submit():
        flash(_primeiro_erro(form), "danger")
        return redirect(url_for("configuracoes.estrutura"))

    try:
        configuracao_service.salvar_serie(form.dados_limpos(), serie)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Serie salva.", "success")

    return redirect(url_for("configuracoes.estrutura"))


@bp.route("/series/<int:serie_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def excluir_serie(serie_id: int):
    serie = db.session.get(Serie, serie_id)
    if serie is None:
        raise RegistroNaoEncontrado("Serie nao encontrada.")

    try:
        configuracao_service.excluir_serie(serie)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Serie excluida.", "success")

    return redirect(url_for("configuracoes.estrutura"))


@bp.route("/salas", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def salvar_sala():
    """Cria ou atualiza uma sala."""
    sala_id = request.form.get("sala_id", "")
    sala = db.session.get(Sala, int(sala_id)) if sala_id.isdigit() else None

    form = SalaForm()
    if not form.validate_on_submit():
        flash(_primeiro_erro(form), "danger")
        return redirect(url_for("configuracoes.estrutura"))

    try:
        configuracao_service.salvar_sala(form.dados_limpos(), sala)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Sala salva.", "success")

    return redirect(url_for("configuracoes.estrutura"))


@bp.route("/salas/<int:sala_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def excluir_sala(sala_id: int):
    sala = db.session.get(Sala, sala_id)
    if sala is None:
        raise RegistroNaoEncontrado("Sala nao encontrada.")

    try:
        configuracao_service.excluir_sala(sala)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Sala excluida.", "success")

    return redirect(url_for("configuracoes.estrutura"))


@bp.route("/tempos-aula", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def salvar_tempo():
    """Cria ou atualiza um tempo de aula."""
    tempo_id = request.form.get("tempo_id", "")
    tempo = db.session.get(TempoAula, int(tempo_id)) if tempo_id.isdigit() else None

    form = TempoAulaForm()
    if not form.validate_on_submit():
        flash(_primeiro_erro(form), "danger")
        return redirect(url_for("configuracoes.estrutura"))

    try:
        configuracao_service.salvar_tempo(form.dados_limpos(), tempo)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Tempo de aula salvo.", "success")

    return redirect(url_for("configuracoes.estrutura"))


@bp.route("/tempos-aula/<int:tempo_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.CONFIGURACAO_EDITAR)
def excluir_tempo(tempo_id: int):
    tempo = db.session.get(TempoAula, tempo_id)
    if tempo is None:
        raise RegistroNaoEncontrado("Tempo de aula nao encontrado.")

    try:
        configuracao_service.excluir_tempo(tempo)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Tempo de aula excluido.", "success")

    return redirect(url_for("configuracoes.estrutura"))


def _primeiro_erro(form) -> str:
    """Primeira mensagem de erro do formulario, para exibicao em flash."""
    for mensagens in form.errors.values():
        if mensagens:
            return mensagens[0]
    return "Dados invalidos."


@bp.route("/logo")
def logo():
    """Entrega o logo da escola.

    Unica rota de upload sem autenticacao, e de proposito: o logo aparece na
    tela de login, antes de qualquer sessao existir. Um logo institucional e
    informacao publica — diferente de foto de aluno.
    """
    escola = configuracao_service.obter_escola()
    return responder_arquivo(PASTA_LOGO, escola.logo)
