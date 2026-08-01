"""Formularios de avisos e comunicados."""

from __future__ import annotations

from datetime import date

from wtforms import (
    BooleanField,
    DateField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional

from app.models.enums import PrioridadeAviso, PublicoAviso
from app.utils.formularios import FormularioBase, FormularioFiltro


class AvisoForm(FormularioBase):
    """Criacao e edicao de um aviso."""

    titulo = StringField(
        "Titulo",
        validators=[
            DataRequired(message="Informe o titulo do aviso."),
            Length(min=3, max=150),
        ],
        render_kw={"placeholder": "Ex.: Reuniao de pais - 1o bimestre"},
    )
    mensagem = TextAreaField(
        "Mensagem",
        validators=[
            DataRequired(message="Escreva a mensagem do aviso."),
            Length(min=10, max=8000),
        ],
        render_kw={"rows": 8},
    )
    resumo = StringField(
        "Resumo",
        validators=[Optional(), Length(max=255)],
        render_kw={"placeholder": "Chamada curta exibida na listagem (opcional)"},
    )

    publico = SelectField(
        "Publico-alvo",
        choices=PublicoAviso.escolhas(),
        default=PublicoAviso.TODOS.value,
    )
    turma_id = SelectField("Turma", choices=[], validators=[Optional()], coerce=str)
    prioridade = SelectField(
        "Prioridade",
        choices=PrioridadeAviso.escolhas(),
        default=PrioridadeAviso.NORMAL.value,
    )

    data_inicio = DateField(
        "Publicar a partir de",
        validators=[DataRequired(message="Informe a data de inicio.")],
        default=date.today,
    )
    data_fim = DateField(
        "Exibir ate",
        validators=[Optional()],
    )

    publicado = BooleanField("Publicado", default=True)
    fixado = BooleanField("Fixar no topo")

    enviar = SubmitField("Salvar aviso")

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)
        valor = dados.get("turma_id")
        dados["turma_id"] = int(valor) if (valor or "").isdigit() else None
        if not (dados.get("resumo") or "").strip():
            dados["resumo"] = None
        return dados


class FiltroAvisoForm(FormularioFiltro):
    """Filtros da listagem de avisos."""

    publico = SelectField(
        "Publico",
        choices=PublicoAviso.escolhas(incluir_vazio=True, rotulo_vazio="Todos"),
        validators=[Optional()],
    )
