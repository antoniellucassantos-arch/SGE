"""Formularios do cadastro de responsaveis."""

from __future__ import annotations

from wtforms import SelectField, StringField, SubmitField, TelField
from wtforms.validators import DataRequired, Length, Optional

from app.models.enums import SituacaoCadastro
from app.utils.formularios import (
    EstadoCivilMixin,
    FormularioFiltro,
    FormularioPessoa,
)
from app.utils.validadores import CPF, Telefone


class ResponsavelForm(FormularioPessoa, EstadoCivilMixin):
    """Cadastro e edicao de responsavel."""

    profissao = StringField(
        "Profissao",
        validators=[Optional(), Length(max=80)],
        render_kw={"placeholder": "Ex.: Comerciante"},
    )
    local_trabalho = StringField(
        "Local de trabalho",
        validators=[Optional(), Length(max=150)],
    )
    telefone_trabalho = TelField(
        "Telefone do trabalho",
        validators=[Optional(), Telefone()],
        render_kw={"placeholder": "(00) 0000-0000", "data-mascara": "telefone",
                   "inputmode": "tel"},
    )

    enviar = SubmitField("Salvar responsavel")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # O CPF do responsavel e obrigatorio: e o documento usado em
        # contratos, declaracoes e na cobranca de mensalidades.
        self.cpf.validators = [
            DataRequired(message="Informe o CPF do responsavel."),
            CPF(),
        ]
        self.cpf.flags.required = True

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)
        for campo in ("profissao", "local_trabalho", "telefone_trabalho"):
            if campo in dados and not (dados[campo] or "").strip():
                dados[campo] = None
        return dados


class FiltroResponsavelForm(FormularioFiltro):
    """Filtros da listagem de responsaveis."""

    situacao = SelectField(
        "Situacao",
        choices=SituacaoCadastro.escolhas(incluir_vazio=True, rotulo_vazio="Todas"),
        validators=[Optional()],
    )
