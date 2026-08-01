"""Formularios do cadastro de funcionarios."""

from __future__ import annotations

from wtforms import DateField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import SituacaoCadastro
from app.utils.formularios import (
    EstadoCivilMixin,
    FormularioFiltro,
    FormularioPessoa,
)
from app.utils.validadores import DataNaoFutura

#: Setores tipicos de uma escola. Campo livre no model; a lista aqui apenas
#: padroniza a digitacao e alimenta o filtro da listagem.
SETORES = [
    ("", "Nao informado"),
    ("Secretaria", "Secretaria"),
    ("Coordenacao", "Coordenacao"),
    ("Direcao", "Direcao"),
    ("Financeiro", "Financeiro"),
    ("Biblioteca", "Biblioteca"),
    ("Portaria", "Portaria"),
    ("Limpeza", "Limpeza"),
    ("Cozinha", "Cozinha"),
    ("Manutencao", "Manutencao"),
    ("Tecnologia", "Tecnologia"),
    ("Apoio pedagogico", "Apoio pedagogico"),
]


class FuncionarioForm(FormularioPessoa, EstadoCivilMixin):
    """Cadastro e edicao de funcionario."""

    matricula_funcional = StringField(
        "Matricula funcional",
        validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "Gerada automaticamente se vazia"},
    )
    cargo = StringField(
        "Cargo",
        validators=[
            DataRequired(message="Informe o cargo do funcionario."),
            Length(max=80),
        ],
        render_kw={"placeholder": "Ex.: Auxiliar administrativo"},
    )
    setor = SelectField("Setor", choices=SETORES, validators=[Optional()])
    data_admissao = DateField(
        "Data de admissao", validators=[Optional(), DataNaoFutura()]
    )
    data_desligamento = DateField("Data de desligamento", validators=[Optional()])
    carga_horaria_semanal = IntegerField(
        "Carga horaria semanal (horas)",
        validators=[Optional(), NumberRange(min=1, max=60)],
        default=40,
        render_kw={"inputmode": "numeric"},
    )

    enviar = SubmitField("Salvar funcionario")

    def validate(self, extra_validators=None) -> bool:
        if not super().validate(extra_validators):
            return False

        if (
            self.data_admissao.data
            and self.data_desligamento.data
            and self.data_desligamento.data < self.data_admissao.data
        ):
            self.data_desligamento.errors.append(
                "O desligamento nao pode ser anterior a admissao."
            )
            return False

        return True

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)
        for campo in ("matricula_funcional", "setor"):
            if campo in dados and not (dados[campo] or "").strip():
                dados[campo] = None
        return dados


class FiltroFuncionarioForm(FormularioFiltro):
    """Filtros da listagem de funcionarios."""

    situacao = SelectField(
        "Situacao",
        choices=SituacaoCadastro.escolhas(incluir_vazio=True, rotulo_vazio="Todas"),
        validators=[Optional()],
    )
    setor = SelectField("Setor", choices=SETORES, validators=[Optional()])
