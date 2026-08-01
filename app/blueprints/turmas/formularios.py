"""Formularios de turmas e da grade de disciplinas."""

from __future__ import annotations

from wtforms import (
    BooleanField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models.enums import Turno
from app.utils.formularios import FormularioBase, FormularioFiltro


class TurmaForm(FormularioBase):
    """Criacao e edicao de turma.

    As opcoes de serie, ano letivo, sala e professor sao carregadas pela
    rota (``carregar_opcoes``), porque dependem do estado do banco.
    """

    nome = StringField(
        "Identificacao da turma",
        validators=[
            DataRequired(message="Informe a identificacao da turma."),
            Length(max=50),
        ],
        render_kw={"placeholder": "Ex.: A, B, Unica"},
    )
    ano_letivo_id = SelectField(
        "Ano letivo",
        validators=[DataRequired(message="Selecione o ano letivo.")],
        coerce=str,
    )
    serie_id = SelectField(
        "Serie",
        validators=[DataRequired(message="Selecione a serie.")],
        coerce=str,
    )
    turno = SelectField("Turno", choices=Turno.escolhas(), validators=[DataRequired()])
    sala_id = SelectField("Sala", validators=[Optional()], coerce=str)
    professor_regente_id = SelectField(
        "Professor regente", validators=[Optional()], coerce=str
    )
    capacidade = IntegerField(
        "Capacidade maxima",
        validators=[
            DataRequired(message="Informe a capacidade da turma."),
            NumberRange(min=1, max=100, message="Informe entre 1 e 100 alunos."),
        ],
        default=30,
        render_kw={"inputmode": "numeric"},
    )
    ativa = BooleanField("Turma ativa", default=True)
    observacoes = TextAreaField(
        "Observacoes", validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 3},
    )

    enviar = SubmitField("Salvar turma")

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)
        # SelectField devolve string; o banco espera inteiro ou None.
        for campo in ("ano_letivo_id", "serie_id", "sala_id", "professor_regente_id"):
            valor = dados.get(campo)
            dados[campo] = int(valor) if (valor or "").isdigit() else None
        return dados


class FiltroTurmaForm(FormularioFiltro):
    """Filtros da listagem de turmas."""

    ano_letivo_id = SelectField("Ano letivo", choices=[], validators=[Optional()], coerce=str)
    serie_id = SelectField("Serie", choices=[], validators=[Optional()], coerce=str)
    turno = SelectField(
        "Turno",
        choices=Turno.escolhas(incluir_vazio=True, rotulo_vazio="Todos"),
        validators=[Optional()],
    )


class AtribuirDisciplinaForm(FormularioBase):
    """Atribuicao de uma disciplina (e do professor) a uma turma."""

    disciplina_id = SelectField(
        "Disciplina",
        validators=[DataRequired(message="Selecione a disciplina.")],
        coerce=str,
    )
    professor_id = SelectField("Professor", validators=[Optional()], coerce=str)
    carga_horaria_semanal = IntegerField(
        "Aulas por semana",
        validators=[
            DataRequired(message="Informe a quantidade de aulas semanais."),
            NumberRange(min=1, max=20),
        ],
        default=2,
        render_kw={"inputmode": "numeric"},
    )
    enviar = SubmitField("Atribuir disciplina")


class EditarVinculoForm(FormularioBase):
    """Edicao de um vinculo turma x disciplina existente."""

    professor_id = SelectField("Professor", validators=[Optional()], coerce=str)
    carga_horaria_semanal = IntegerField(
        "Aulas por semana",
        validators=[DataRequired(), NumberRange(min=1, max=20)],
        default=2,
    )
    ativa = BooleanField("Vinculo ativo", default=True)
    enviar = SubmitField("Salvar alteracoes")


class DisciplinaForm(FormularioBase):
    """Cadastro e edicao de disciplina."""

    nome = StringField(
        "Nome da disciplina",
        validators=[
            DataRequired(message="Informe o nome da disciplina."),
            Length(min=2, max=100),
        ],
        render_kw={"placeholder": "Ex.: Matematica"},
    )
    codigo = StringField(
        "Codigo",
        validators=[
            DataRequired(message="Informe um codigo curto."),
            Length(min=2, max=20),
        ],
        render_kw={"placeholder": "Ex.: MAT", "style": "text-transform: uppercase;"},
    )
    carga_horaria = IntegerField(
        "Carga horaria anual (horas)",
        validators=[Optional(), NumberRange(min=0, max=2000)],
        default=80,
        render_kw={"inputmode": "numeric"},
    )
    cor = StringField(
        "Cor na grade",
        validators=[Optional(), Length(max=7)],
        default="#1a56db",
        render_kw={"type": "color"},
    )
    descricao = TextAreaField(
        "Descricao / ementa",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    ativa = BooleanField("Disciplina ativa", default=True)

    enviar = SubmitField("Salvar disciplina")


class FiltroDisciplinaForm(FormularioFiltro):
    """Filtros da listagem de disciplinas."""

    ativa = SelectField(
        "Situacao",
        choices=[("", "Todas"), ("1", "Ativas"), ("0", "Inativas")],
        validators=[Optional()],
    )
