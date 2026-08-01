"""Bases e campos reutilizaveis de formulario.

Alunos, professores, funcionarios e responsaveis compartilham os mesmos
blocos de dados civis, documentos, contato e endereco. Concentra-los aqui
evita repetir ~40 campos em quatro arquivos — e garante que um ajuste de
validacao (ex.: passar a exigir celular) valha para todos os cadastros.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    DateField,
    EmailField,
    SelectField,
    StringField,
    TelField,
    TextAreaField,
)
from wtforms.validators import Email, Length, Optional

from app.models.enums import EstadoCivil, Sexo, SituacaoCadastro
from app.utils.validadores import (
    CEP,
    CPF,
    UNIDADES_FEDERATIVAS,
    DataNaoFutura,
    IdadePlausivel,
    NomeCompleto,
    Telefone,
)

#: Extensoes aceitas em campos de imagem.
IMAGENS_PERMITIDAS = ("png", "jpg", "jpeg", "webp")

#: Opcoes de UF prontas para ``SelectField``.
OPCOES_UF = [("", "UF")] + [(uf, uf) for uf in UNIDADES_FEDERATIVAS]


class FormularioBase(FlaskForm):
    """Base de todos os formularios do sistema.

    Existe para centralizar utilitarios de transporte de erros vindos da
    camada de servico (regras que so podem ser validadas contra o banco).
    """

    def aplicar_erros(self, erros_por_campo: dict[str, list[str]] | None) -> None:
        """Anexa erros produzidos por um service aos campos correspondentes."""
        for campo, mensagens in (erros_por_campo or {}).items():
            if hasattr(self, campo):
                getattr(self, campo).errors.extend(mensagens)

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        """Dados do formulario prontos para o service.

        Remove campos de controle (CSRF, botoes, uploads) que nao sao
        colunas do model, evitando que a rota precise montar o dicionario
        campo a campo.
        """
        ignorar = (ignorar or set()) | {"csrf_token", "enviar", "submit"}
        return {
            nome: campo.data
            for nome, campo in self._fields.items()
            if nome not in ignorar and not isinstance(campo, FileField)
        }


class DadosPessoaisMixin:
    """Identificacao civil comum a todos os cadastros de pessoas."""

    nome_completo = StringField(
        "Nome completo",
        validators=[
            Length(min=3, max=150, message="Informe entre 3 e 150 caracteres."),
            NomeCompleto(),
        ],
        render_kw={"placeholder": "Nome civil completo", "autocomplete": "name"},
    )
    nome_social = StringField(
        "Nome social",
        validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Se diferente do nome civil"},
    )
    data_nascimento = DateField(
        "Data de nascimento",
        validators=[Optional(), DataNaoFutura(), IdadePlausivel(0, 120)],
    )
    sexo = SelectField("Sexo", choices=Sexo.escolhas(), default=Sexo.NAO_INFORMADO.value)

    cpf = StringField(
        "CPF",
        validators=[Optional(), CPF()],
        render_kw={"placeholder": "000.000.000-00", "data-mascara": "cpf",
                   "inputmode": "numeric"},
    )
    rg = StringField(
        "RG", validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "Numero do RG"},
    )
    rg_orgao_emissor = StringField(
        "Orgao emissor", validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "SSP/SP"},
    )


class ContatoMixin:
    """Telefones e e-mail."""

    telefone = TelField(
        "Telefone fixo",
        validators=[Optional(), Telefone()],
        render_kw={"placeholder": "(00) 0000-0000", "data-mascara": "telefone",
                   "inputmode": "tel"},
    )
    celular = TelField(
        "Celular",
        validators=[Optional(), Telefone()],
        render_kw={"placeholder": "(00) 00000-0000", "data-mascara": "telefone",
                   "inputmode": "tel", "autocomplete": "tel"},
    )
    email = EmailField(
        "E-mail",
        validators=[Optional(), Email(message="Informe um e-mail valido."),
                    Length(max=150)],
        render_kw={"placeholder": "email@exemplo.com", "autocomplete": "email",
                   "inputmode": "email"},
    )


class EnderecoMixin:
    """Endereco residencial no padrao dos Correios."""

    cep = StringField(
        "CEP",
        validators=[Optional(), CEP()],
        render_kw={"placeholder": "00000-000", "data-mascara": "cep",
                   "inputmode": "numeric", "autocomplete": "postal-code"},
    )
    logradouro = StringField(
        "Logradouro", validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Rua, avenida, travessa...",
                   "autocomplete": "street-address"},
    )
    numero = StringField(
        "Numero", validators=[Optional(), Length(max=15)],
        render_kw={"placeholder": "123"},
    )
    complemento = StringField(
        "Complemento", validators=[Optional(), Length(max=80)],
        render_kw={"placeholder": "Apto, bloco, casa"},
    )
    bairro = StringField(
        "Bairro", validators=[Optional(), Length(max=80)],
    )
    cidade = StringField(
        "Cidade", validators=[Optional(), Length(max=80)],
        render_kw={"autocomplete": "address-level2"},
    )
    uf = SelectField("UF", choices=OPCOES_UF, validators=[Optional()])


class SituacaoMixin:
    """Situacao do cadastro, observacoes e foto."""

    situacao = SelectField(
        "Situacao",
        choices=SituacaoCadastro.escolhas(),
        default=SituacaoCadastro.ATIVO.value,
    )
    observacoes = TextAreaField(
        "Observacoes",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 3, "placeholder": "Informacoes complementares"},
    )
    foto = FileField(
        "Foto",
        validators=[
            FileAllowed(
                IMAGENS_PERMITIDAS,
                "Envie uma imagem PNG, JPG ou WEBP.",
            )
        ],
        render_kw={"accept": "image/png,image/jpeg,image/webp"},
    )


class EstadoCivilMixin:
    """Estado civil (nao se aplica a alunos)."""

    estado_civil = SelectField(
        "Estado civil",
        choices=EstadoCivil.escolhas(),
        default=EstadoCivil.NAO_INFORMADO.value,
    )


class FormularioPessoa(
    FormularioBase,
    DadosPessoaisMixin,
    ContatoMixin,
    EnderecoMixin,
    SituacaoMixin,
):
    """Formulario completo de pessoa, sem os campos especificos de cada papel.

    Subclasses acrescentam o que e proprio do seu dominio (RA e dados de
    saude no aluno, registro funcional no professor, cargo no funcionario).
    """

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)
        # Campos vazios viram None: strings vazias em colunas unique
        # (CPF, e-mail) colidiriam entre si no banco.
        for campo in ("cpf", "rg", "telefone", "celular", "email", "cep", "uf"):
            if campo in dados and not (dados[campo] or "").strip():
                dados[campo] = None
        return dados


# ---------------------------------------------------------------------------
# Formulario de filtros de listagem
# ---------------------------------------------------------------------------
class FormularioFiltro(FlaskForm):
    """Base dos filtros de listagem.

    Sem CSRF: filtros sao submetidos por ``GET`` e nao alteram estado, entao
    o token so poluiria a URL sem agregar seguranca.
    """

    class Meta:
        csrf = False

    busca = StringField(
        "Buscar",
        validators=[Optional(), Length(max=100)],
        render_kw={
            "placeholder": "Nome, codigo ou CPF...",
            "autocomplete": "off",
            "type": "search",
        },
    )
