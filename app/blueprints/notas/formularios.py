"""Formularios de avaliacoes e notas."""

from __future__ import annotations

from wtforms import (
    DateField,
    DecimalField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import TipoAvaliacao
from app.utils.formularios import FormularioBase


class AvaliacaoForm(FormularioBase):
    """Criacao e edicao de uma avaliacao."""

    nome = StringField(
        "Nome da avaliacao",
        validators=[
            DataRequired(message="Informe o nome da avaliacao."),
            Length(max=100),
        ],
        render_kw={"placeholder": "Ex.: Prova 1, Trabalho de pesquisa"},
    )
    periodo_id = SelectField(
        "Periodo",
        validators=[DataRequired(message="Selecione o periodo.")],
        coerce=str,
    )
    tipo = SelectField(
        "Tipo",
        choices=TipoAvaliacao.escolhas(),
        default=TipoAvaliacao.PROVA.value,
    )
    peso = DecimalField(
        "Peso",
        validators=[
            DataRequired(message="Informe o peso."),
            NumberRange(min=0.1, max=99, message="O peso deve ser maior que zero."),
        ],
        default=1,
        places=2,
        render_kw={"inputmode": "decimal", "step": "0.5"},
    )
    valor_maximo = DecimalField(
        "Valor maximo",
        validators=[
            DataRequired(message="Informe o valor maximo."),
            NumberRange(min=0.1, max=1000),
        ],
        default=10,
        places=2,
        render_kw={"inputmode": "decimal", "step": "0.5"},
    )
    data_aplicacao = DateField("Data de aplicacao", validators=[Optional()])
    descricao = TextAreaField(
        "Descricao",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 2, "placeholder": "Conteudo cobrado, criterios..."},
    )

    enviar = SubmitField("Salvar avaliacao")
