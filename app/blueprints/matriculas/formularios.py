"""Formularios do modulo de matriculas."""

from __future__ import annotations

from wtforms import DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models.enums import SituacaoMatricula
from app.utils.formularios import FormularioBase, FormularioFiltro
from app.utils.validadores import DataNaoFutura


class MatriculaForm(FormularioBase):
    """Nova matricula de um aluno em uma turma.

    As opcoes de aluno e turma sao carregadas pela rota, porque dependem do
    ano letivo selecionado e do estado atual do banco.
    """

    aluno_id = SelectField(
        "Aluno",
        validators=[DataRequired(message="Selecione o aluno.")],
        coerce=str,
    )
    turma_id = SelectField(
        "Turma",
        validators=[DataRequired(message="Selecione a turma.")],
        coerce=str,
    )
    ano_letivo_id = SelectField(
        "Ano letivo",
        validators=[DataRequired(message="Selecione o ano letivo.")],
        coerce=str,
    )
    data_matricula = DateField(
        "Data da matricula",
        validators=[DataRequired(message="Informe a data."), DataNaoFutura()],
    )
    escola_origem = StringField(
        "Escola de origem",
        validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Preencher em caso de transferencia recebida"},
    )
    observacoes = TextAreaField(
        "Observacoes", validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 3},
    )

    enviar = SubmitField("Efetivar matricula")


class TransferirTurmaForm(FormularioBase):
    """Transferencia do aluno entre turmas do mesmo ano letivo."""

    nova_turma_id = SelectField(
        "Nova turma",
        validators=[DataRequired(message="Selecione a turma de destino.")],
        coerce=str,
    )
    motivo = TextAreaField(
        "Motivo da transferencia",
        validators=[Optional(), Length(max=500)],
        render_kw={"rows": 2, "placeholder": "Ex.: adequacao de turno"},
    )
    enviar = SubmitField("Transferir de turma")


class TransferirEscolaForm(FormularioBase):
    """Encerramento da matricula por transferencia para outra escola."""

    escola_destino = StringField(
        "Escola de destino",
        validators=[
            DataRequired(message="Informe a escola de destino."),
            Length(max=150),
        ],
    )
    motivo = TextAreaField(
        "Motivo", validators=[Optional(), Length(max=500)],
        render_kw={"rows": 2},
    )
    enviar = SubmitField("Confirmar transferencia")


class EncerrarMatriculaForm(FormularioBase):
    """Cancelamento ou trancamento da matricula."""

    motivo = TextAreaField(
        "Motivo",
        validators=[
            DataRequired(message="Informe o motivo para registro no historico."),
            Length(max=500),
        ],
        render_kw={"rows": 3},
    )
    enviar = SubmitField("Confirmar")


class FiltroMatriculaForm(FormularioFiltro):
    """Filtros da listagem de matriculas."""

    ano_letivo_id = SelectField(
        "Ano letivo", choices=[], validators=[Optional()], coerce=str
    )
    turma_id = SelectField("Turma", choices=[], validators=[Optional()], coerce=str)
    situacao = SelectField(
        "Situacao",
        choices=SituacaoMatricula.escolhas(incluir_vazio=True, rotulo_vazio="Todas"),
        validators=[Optional()],
    )
