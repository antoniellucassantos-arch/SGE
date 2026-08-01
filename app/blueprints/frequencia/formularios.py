"""Formularios do diario de classe."""

from __future__ import annotations

from datetime import date

from wtforms import DateField, IntegerField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.utils.formularios import FormularioBase
from app.utils.validadores import DataNaoFutura


class AulaForm(FormularioBase):
    """Registro de uma aula no diario de classe."""

    data_aula = DateField(
        "Data da aula",
        validators=[DataRequired(message="Informe a data da aula."), DataNaoFutura()],
        default=date.today,
    )
    quantidade_aulas = IntegerField(
        "Quantidade de aulas",
        validators=[
            DataRequired(message="Informe quantas aulas este registro representa."),
            NumberRange(min=1, max=6),
        ],
        default=1,
        render_kw={"inputmode": "numeric"},
    )
    conteudo = TextAreaField(
        "Conteudo ministrado",
        validators=[
            DataRequired(message="Descreva o conteudo trabalhado na aula."),
            Length(max=2000),
        ],
        render_kw={"rows": 3, "placeholder": "Ex.: Equacoes do 2o grau - formula de Bhaskara"},
    )
    tarefa_casa = TextAreaField(
        "Tarefa de casa",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 2},
    )
    observacoes = TextAreaField(
        "Observacoes",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 2, "placeholder": "Ocorrencias relevantes da aula"},
    )

    enviar = SubmitField("Registrar aula")


class JustificarFaltaForm(FormularioBase):
    """Justificativa de uma falta especifica."""

    motivo = TextAreaField(
        "Motivo da justificativa",
        validators=[
            DataRequired(message="Informe o motivo apresentado pelo responsavel."),
            Length(max=255),
        ],
        render_kw={"rows": 2, "placeholder": "Ex.: atestado medico apresentado em 12/03"},
    )
    enviar = SubmitField("Justificar falta")
