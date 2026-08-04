"""Formularios de avaliacoes e notas."""

from __future__ import annotations

from wtforms import (
    DateField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import TipoAvaliacao
from app.utils.formularios import CampoQuantidade, FormularioBase

#: Menor incremento aceito em nota maxima e peso.
#:
#: `min` e `step` andam juntos por uma razao pratica: num
#: ``<input type="number">`` os valores validos sao ``min + n*step``. Com
#: ``min=0.1`` e ``step=0.5`` a escada valida era 0,1 / 0,6 / 1,1 / 1,6... —
#: **nenhum numero redondo entrava nela**. As setinhas saiam de 1 e paravam
#: em 1,1, e quem insistisse chegava a 10,1. Era o que fazia peso e nota
#: maxima aparecerem sempre quebrados.
#:
#: Com os dois em 0,5 a escada vira 0,5 / 1 / 1,5 / 2 ... 10: inclui todo
#: numero redondo e ainda permite meio ponto, que a escola usa.
PASSO = 0.5


class AvaliacaoForm(FormularioBase):
    """Criacao e edicao de uma avaliacao.

    A ordem dos campos segue a pergunta que o professor faz: primeiro
    *quanto vale a prova* (nota maxima), depois *quanto ela pesa na media*.
    Peso antes de nota maxima invertia o raciocinio.
    """

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
    valor_maximo = CampoQuantidade(
        "Nota maxima",
        validators=[
            DataRequired(message="Informe quanto vale a avaliacao."),
            NumberRange(
                min=PASSO,
                max=1000,
                message="A nota maxima deve ser maior que zero.",
            ),
        ],
        default=10,
        places=None,
        render_kw={"inputmode": "decimal", "step": PASSO, "min": PASSO},
    )
    peso = CampoQuantidade(
        "Peso na media",
        validators=[
            DataRequired(message="Informe o peso."),
            NumberRange(
                min=PASSO, max=99, message="O peso deve ser maior que zero."
            ),
        ],
        default=1,
        places=None,
        render_kw={"inputmode": "decimal", "step": PASSO, "min": PASSO},
    )
    data_aplicacao = DateField("Data de aplicacao", validators=[Optional()])
    descricao = TextAreaField(
        "Descricao",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 2, "placeholder": "Conteudo cobrado, criterios..."},
    )

    enviar = SubmitField("Salvar avaliacao")
