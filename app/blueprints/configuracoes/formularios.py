"""Formularios de configuracao do sistema."""

from __future__ import annotations

from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

from app.models.enums import NivelEnsino, SituacaoAnoLetivo, Turno
from app.utils.formularios import IMAGENS_PERMITIDAS, OPCOES_UF, FormularioBase
from app.utils.validadores import CEP, CNPJ, Telefone


class EscolaForm(FormularioBase):
    """Dados institucionais e identidade visual da escola."""

    nome = StringField(
        "Razao social",
        validators=[DataRequired(message="Informe o nome da escola."), Length(max=150)],
    )
    nome_fantasia = StringField(
        "Nome de exibicao",
        validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Nome usado no sistema e nos documentos"},
    )
    cnpj = StringField(
        "CNPJ",
        validators=[Optional(), CNPJ()],
        render_kw={"placeholder": "00.000.000/0000-00", "data-mascara": "cnpj",
                   "inputmode": "numeric"},
    )
    codigo_inep = StringField(
        "Codigo INEP",
        validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "Codigo da escola no censo escolar"},
    )
    diretor = StringField("Diretor(a)", validators=[Optional(), Length(max=150)])
    secretario = StringField("Secretario(a)", validators=[Optional(), Length(max=150)])

    telefone = StringField(
        "Telefone",
        validators=[Optional(), Telefone()],
        render_kw={"data-mascara": "telefone", "inputmode": "tel"},
    )
    email = StringField(
        "E-mail",
        validators=[Optional(), Email(message="Informe um e-mail valido."), Length(max=150)],
    )
    site = StringField("Site", validators=[Optional(), Length(max=150)])

    cep = StringField(
        "CEP",
        validators=[Optional(), CEP()],
        render_kw={"data-mascara": "cep", "inputmode": "numeric"},
    )
    logradouro = StringField("Logradouro", validators=[Optional(), Length(max=150)])
    numero = StringField("Numero", validators=[Optional(), Length(max=15)])
    bairro = StringField("Bairro", validators=[Optional(), Length(max=80)])
    cidade = StringField("Cidade", validators=[Optional(), Length(max=80)])
    uf = SelectField("UF", choices=OPCOES_UF, validators=[Optional()])

    logo = FileField(
        "Logo da escola",
        validators=[FileAllowed(IMAGENS_PERMITIDAS, "Envie uma imagem PNG, JPG ou WEBP.")],
        render_kw={"accept": "image/png,image/jpeg,image/webp"},
    )
    mensagem_login = TextAreaField(
        "Mensagem na tela de login",
        validators=[Optional(), Length(max=500)],
        render_kw={"rows": 2, "placeholder": "Aviso exibido a todos antes do login"},
    )

    enviar = SubmitField("Salvar dados da escola")


class ParametrosForm(FormularioBase):
    """Parametros academicos padrao da escola."""

    media_aprovacao = DecimalField(
        "Media minima para aprovacao",
        validators=[DataRequired(), NumberRange(min=0, max=10)],
        places=2,
        render_kw={"inputmode": "decimal", "step": "0.1"},
    )
    media_recuperacao = DecimalField(
        "Media minima para recuperacao",
        validators=[DataRequired(), NumberRange(min=0, max=10)],
        places=2,
        render_kw={"inputmode": "decimal", "step": "0.1"},
    )
    frequencia_minima = DecimalField(
        "Frequencia minima (%)",
        validators=[DataRequired(), NumberRange(min=0, max=100)],
        places=2,
        render_kw={"inputmode": "decimal", "step": "1"},
    )
    nota_maxima = DecimalField(
        "Nota maxima",
        validators=[DataRequired(), NumberRange(min=1, max=100)],
        places=2,
        render_kw={"inputmode": "decimal", "step": "1"},
    )
    quantidade_periodos = SelectField(
        "Divisao do ano letivo",
        choices=[("4", "Bimestral (4 periodos)"), ("3", "Trimestral (3 periodos)"),
                 ("2", "Semestral (2 periodos)")],
        default="4",
    )
    backup_automatico = BooleanField("Backup automatico habilitado", default=True)
    backup_hora = StringField(
        "Horario do backup",
        validators=[Optional(), Length(max=5)],
        render_kw={"placeholder": "02:00", "type": "time"},
    )

    enviar = SubmitField("Salvar parametros")

    def validate(self, extra_validators=None) -> bool:
        if not super().validate(extra_validators):
            return False

        if self.media_recuperacao.data >= self.media_aprovacao.data:
            self.media_recuperacao.errors.append(
                "A media de recuperacao deve ser menor que a media de aprovacao."
            )
            return False

        return True


class AnoLetivoForm(FormularioBase):
    """Criacao e edicao de ano letivo."""

    ano = IntegerField(
        "Ano",
        validators=[DataRequired(message="Informe o ano."),
                    NumberRange(min=2000, max=2100)],
        render_kw={"inputmode": "numeric"},
    )
    descricao = StringField(
        "Descricao", validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "Ex.: Ano Letivo 2026"},
    )
    data_inicio = DateField(
        "Inicio das aulas",
        validators=[DataRequired(message="Informe a data de inicio.")],
    )
    data_fim = DateField(
        "Termino das aulas",
        validators=[DataRequired(message="Informe a data de termino.")],
    )
    situacao = SelectField(
        "Situacao",
        choices=SituacaoAnoLetivo.escolhas(),
        default=SituacaoAnoLetivo.PLANEJAMENTO.value,
    )
    corrente = BooleanField("Definir como ano letivo corrente")

    media_aprovacao = DecimalField(
        "Media de aprovacao",
        validators=[DataRequired(), NumberRange(min=0, max=10)],
        places=2, default=6,
        render_kw={"inputmode": "decimal", "step": "0.1"},
    )
    media_recuperacao = DecimalField(
        "Media de recuperacao",
        validators=[DataRequired(), NumberRange(min=0, max=10)],
        places=2, default=4,
        render_kw={"inputmode": "decimal", "step": "0.1"},
    )
    frequencia_minima = DecimalField(
        "Frequencia minima (%)",
        validators=[DataRequired(), NumberRange(min=0, max=100)],
        places=2, default=75,
        render_kw={"inputmode": "decimal", "step": "1"},
    )

    enviar = SubmitField("Salvar ano letivo")

    def validate(self, extra_validators=None) -> bool:
        if not super().validate(extra_validators):
            return False

        if self.data_fim.data <= self.data_inicio.data:
            self.data_fim.errors.append(
                "O termino deve ser posterior ao inicio das aulas."
            )
            return False

        return True


class SerieForm(FormularioBase):
    """Cadastro de serie / etapa de ensino."""

    nome = StringField(
        "Nome da serie",
        validators=[DataRequired(message="Informe o nome."), Length(max=60)],
        render_kw={"placeholder": "Ex.: 6o Ano"},
    )
    nivel_ensino = SelectField(
        "Nivel de ensino", choices=NivelEnsino.escolhas(), validators=[DataRequired()]
    )
    ordem = IntegerField(
        "Ordem pedagogica",
        validators=[DataRequired(), NumberRange(min=0, max=99)],
        default=0,
        render_kw={"inputmode": "numeric"},
    )
    idade_recomendada = IntegerField(
        "Idade recomendada",
        validators=[Optional(), NumberRange(min=0, max=99)],
        render_kw={"inputmode": "numeric"},
    )
    ativa = BooleanField("Serie ativa", default=True)

    enviar = SubmitField("Salvar serie")


class SalaForm(FormularioBase):
    """Cadastro de sala de aula."""

    nome = StringField(
        "Nome da sala",
        validators=[DataRequired(message="Informe o nome."), Length(max=60)],
        render_kw={"placeholder": "Ex.: Sala 12"},
    )
    bloco = StringField("Bloco", validators=[Optional(), Length(max=40)])
    andar = StringField("Andar", validators=[Optional(), Length(max=20)])
    capacidade = IntegerField(
        "Capacidade",
        validators=[Optional(), NumberRange(min=1, max=200)],
        render_kw={"inputmode": "numeric"},
    )
    possui_projetor = BooleanField("Possui projetor")
    possui_ar_condicionado = BooleanField("Possui ar-condicionado")
    acessivel = BooleanField("Acessivel para cadeirantes")
    ativa = BooleanField("Sala ativa", default=True)
    observacoes = TextAreaField(
        "Observacoes", validators=[Optional(), Length(max=500)],
        render_kw={"rows": 2},
    )

    enviar = SubmitField("Salvar sala")


class TempoAulaForm(FormularioBase):
    """Cadastro de tempo de aula (slot da grade)."""

    turno = SelectField("Turno", choices=Turno.escolhas(), validators=[DataRequired()])
    ordem = IntegerField(
        "Ordem no turno",
        validators=[DataRequired(), NumberRange(min=1, max=20)],
        render_kw={"inputmode": "numeric"},
    )
    nome = StringField(
        "Nome",
        validators=[DataRequired(message="Informe o nome."), Length(max=40)],
        render_kw={"placeholder": "Ex.: 1o tempo"},
    )
    hora_inicio = StringField(
        "Inicio",
        validators=[DataRequired(message="Informe o horario de inicio.")],
        render_kw={"type": "time"},
    )
    hora_fim = StringField(
        "Termino",
        validators=[DataRequired(message="Informe o horario de termino.")],
        render_kw={"type": "time"},
    )
    e_intervalo = BooleanField("E intervalo / recreio")
    ativo = BooleanField("Ativo", default=True)

    enviar = SubmitField("Salvar tempo de aula")
