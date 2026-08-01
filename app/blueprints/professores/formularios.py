"""Formularios do cadastro de professores."""

from __future__ import annotations

from wtforms import DateField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import Length, NumberRange, Optional

from app.models.enums import SituacaoCadastro
from app.utils.formularios import (
    EstadoCivilMixin,
    FormularioFiltro,
    FormularioPessoa,
)
from app.utils.validadores import DataNaoFutura

#: Titulacoes reconhecidas pela LDB.
TITULACOES = [
    ("", "Nao informada"),
    ("Magisterio", "Magisterio"),
    ("Graduacao", "Graduacao"),
    ("Especializacao", "Especializacao"),
    ("Mestrado", "Mestrado"),
    ("Doutorado", "Doutorado"),
    ("Pos-doutorado", "Pos-doutorado"),
]


class ProfessorForm(FormularioPessoa, EstadoCivilMixin):
    """Cadastro e edicao de professor."""

    registro_funcional = StringField(
        "Registro funcional",
        validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "Gerado automaticamente se vazio"},
    )
    formacao = StringField(
        "Formacao",
        validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Ex.: Licenciatura em Matematica"},
    )
    titulacao = SelectField("Titulacao", choices=TITULACOES, validators=[Optional()])
    instituicao_formacao = StringField(
        "Instituicao de formacao",
        validators=[Optional(), Length(max=150)],
    )
    data_admissao = DateField(
        "Data de admissao", validators=[Optional(), DataNaoFutura()]
    )
    data_desligamento = DateField("Data de desligamento", validators=[Optional()])
    carga_horaria_semanal = IntegerField(
        "Carga horaria semanal (horas)",
        validators=[Optional(), NumberRange(min=1, max=60)],
        default=20,
        render_kw={"inputmode": "numeric"},
    )

    enviar = SubmitField("Salvar professor")

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
        for campo in ("registro_funcional", "titulacao", "formacao",
                      "instituicao_formacao"):
            if campo in dados and not (dados[campo] or "").strip():
                dados[campo] = None
        return dados


class FiltroProfessorForm(FormularioFiltro):
    """Filtros da listagem de professores."""

    situacao = SelectField(
        "Situacao",
        choices=SituacaoCadastro.escolhas(incluir_vazio=True, rotulo_vazio="Todas"),
        validators=[Optional()],
    )
    titulacao = SelectField("Titulacao", choices=TITULACOES, validators=[Optional()])
