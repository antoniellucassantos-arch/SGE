"""Mixins de colunas compartilhadas entre os cadastros de pessoas.

Por que mixins de coluna e nao uma tabela ``pessoas`` unica?
------------------------------------------------------------
Uma tabela ``pessoas`` com heranca *joined-table* seria academicamente mais
"normalizada", mas cobraria um ``JOIN`` extra em **toda** consulta de aluno,
professor e responsavel — inclusive nas listagens paginadas e nos relatorios,
que sao justamente os pontos mais sensiveis com milhares de alunos.

Repetir *colunas* entre tabelas nao viola normalizacao: normalizacao trata de
redundancia de **dados** dentro de uma relacao, nao de semelhanca estrutural
entre relacoes distintas. Cada CPF continua existindo uma unica vez, em uma
unica linha, com restricao de unicidade propria.

A identidade compartilhada entre papeis (quando a mesma pessoa e professora e
mae de aluno) e resolvida pelo vinculo com ``Usuario``, e nao pela
duplicacao de dados.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column

from app.models.enums import Sexo, SituacaoCadastro
from app.utils.seguranca import apenas_digitos, normalizar_texto, remover_acentos
from app.utils.validadores import (
    calcular_idade,
    formatar_cep,
    formatar_cpf,
    formatar_telefone,
)


@declarative_mixin
class EnderecoMixin:
    """Endereco residencial no formato dos Correios."""

    @declared_attr
    def cep(cls) -> Mapped[str | None]:
        return mapped_column(String(8), nullable=True, doc="CEP somente digitos.")

    @declared_attr
    def logradouro(cls) -> Mapped[str | None]:
        return mapped_column(String(150), nullable=True)

    @declared_attr
    def numero(cls) -> Mapped[str | None]:
        return mapped_column(String(15), nullable=True)

    @declared_attr
    def complemento(cls) -> Mapped[str | None]:
        return mapped_column(String(80), nullable=True)

    @declared_attr
    def bairro(cls) -> Mapped[str | None]:
        return mapped_column(String(80), nullable=True)

    @declared_attr
    def cidade(cls) -> Mapped[str | None]:
        return mapped_column(String(80), nullable=True)

    @declared_attr
    def uf(cls) -> Mapped[str | None]:
        return mapped_column(String(2), nullable=True)

    @property
    def endereco_completo(self) -> str:
        """Endereco em linha unica para exibicao e documentos impressos."""
        partes: list[str] = []

        if self.logradouro:
            linha = self.logradouro
            if self.numero:
                linha += f", {self.numero}"
            if self.complemento:
                linha += f" - {self.complemento}"
            partes.append(linha)

        if self.bairro:
            partes.append(self.bairro)

        if self.cidade:
            partes.append(f"{self.cidade}/{self.uf}" if self.uf else self.cidade)

        if self.cep:
            partes.append(f"CEP {formatar_cep(self.cep)}")

        return " - ".join(partes)

    @property
    def tem_endereco(self) -> bool:
        return bool(self.logradouro and self.cidade)

    def normalizar_endereco(self) -> None:
        """Padroniza os campos de endereco antes de gravar."""
        self.cep = apenas_digitos(self.cep) or None
        self.logradouro = normalizar_texto(self.logradouro) or None
        self.bairro = normalizar_texto(self.bairro) or None
        self.cidade = normalizar_texto(self.cidade) or None
        self.uf = (self.uf or "").strip().upper()[:2] or None


@declarative_mixin
class PessoaMixin(EnderecoMixin):
    """Dados civis comuns a alunos, professores, funcionarios e responsaveis."""

    # -- Identificacao -------------------------------------------------------
    @declared_attr
    def nome_completo(cls) -> Mapped[str]:
        return mapped_column(String(150), nullable=False)

    @declared_attr
    def nome_normalizado(cls) -> Mapped[str]:
        return mapped_column(
            String(150),
            nullable=False,
            default="",
            index=True,
            doc="Nome sem acentos e em minusculas, usado nas buscas.",
        )

    @declared_attr
    def nome_social(cls) -> Mapped[str | None]:
        return mapped_column(
            String(150),
            nullable=True,
            doc="Nome social, quando diferente do nome civil (Decreto 8.727/2016).",
        )

    @declared_attr
    def data_nascimento(cls) -> Mapped[date | None]:
        return mapped_column(Date, nullable=True, index=True)

    @declared_attr
    def sexo(cls) -> Mapped[Sexo]:
        return mapped_column(
            SAEnum(
                Sexo,
                name="sexo",
                values_callable=lambda enum: [m.value for m in enum],
                native_enum=False,
            ),
            nullable=False,
            default=Sexo.NAO_INFORMADO,
        )

    # -- Documentos ----------------------------------------------------------
    @declared_attr
    def cpf(cls) -> Mapped[str | None]:
        return mapped_column(String(11), nullable=True, unique=True, index=True)

    @declared_attr
    def rg(cls) -> Mapped[str | None]:
        return mapped_column(String(20), nullable=True)

    @declared_attr
    def rg_orgao_emissor(cls) -> Mapped[str | None]:
        return mapped_column(String(20), nullable=True)

    # -- Contato -------------------------------------------------------------
    @declared_attr
    def telefone(cls) -> Mapped[str | None]:
        return mapped_column(String(11), nullable=True)

    @declared_attr
    def celular(cls) -> Mapped[str | None]:
        return mapped_column(String(11), nullable=True, index=True)

    @declared_attr
    def email(cls) -> Mapped[str | None]:
        return mapped_column(String(150), nullable=True, index=True)

    # -- Situacao e observacoes ---------------------------------------------
    @declared_attr
    def situacao(cls) -> Mapped[SituacaoCadastro]:
        return mapped_column(
            SAEnum(
                SituacaoCadastro,
                name="situacao_cadastro",
                values_callable=lambda enum: [m.value for m in enum],
                native_enum=False,
            ),
            nullable=False,
            default=SituacaoCadastro.ATIVO,
            index=True,
        )

    @declared_attr
    def observacoes(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def foto(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Propriedades de apresentacao
    # ------------------------------------------------------------------
    @property
    def nome_exibicao(self) -> str:
        """Nome social quando informado; caso contrario, o nome civil."""
        return self.nome_social or self.nome_completo

    @property
    def primeiro_nome(self) -> str:
        return (self.nome_exibicao or "").split(" ")[0]

    @property
    def iniciais(self) -> str:
        partes = [p for p in (self.nome_exibicao or "").split(" ") if p]
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[-1][0]).upper()

    @property
    def idade(self) -> int | None:
        return calcular_idade(self.data_nascimento)

    @property
    def cpf_formatado(self) -> str:
        return formatar_cpf(self.cpf)

    @property
    def telefone_formatado(self) -> str:
        return formatar_telefone(self.celular or self.telefone)

    @property
    def contato_principal(self) -> str:
        """Melhor canal de contato disponivel, em ordem de preferencia."""
        return self.telefone_formatado or self.email or "Nao informado"

    @property
    def esta_ativo(self) -> bool:
        return self.situacao is SituacaoCadastro.ATIVO

    # ------------------------------------------------------------------
    # Normalizacao
    # ------------------------------------------------------------------
    def normalizar_pessoa(self) -> None:
        """Padroniza documentos, contatos e campos de busca antes de gravar."""
        self.nome_completo = normalizar_texto(self.nome_completo)
        self.nome_social = normalizar_texto(self.nome_social) or None
        self.nome_normalizado = remover_acentos(
            f"{self.nome_completo} {self.nome_social or ''}"
        )
        self.cpf = apenas_digitos(self.cpf) or None
        self.rg = normalizar_texto(self.rg) or None
        self.telefone = apenas_digitos(self.telefone) or None
        self.celular = apenas_digitos(self.celular) or None
        self.email = (self.email or "").strip().lower() or None
        self.normalizar_endereco()


@declarative_mixin
class VinculoUsuarioMixin:
    """Liga um perfil a uma conta de acesso opcional."""

    @declared_attr
    def usuario_id(cls) -> Mapped[int | None]:
        return mapped_column(
            ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
            index=True,
            doc="Conta de acesso vinculada. Nulo quando o perfil nao tem login.",
        )

    @property
    def possui_acesso(self) -> bool:
        """Indica se o perfil consegue efetivamente entrar no sistema."""
        return self.usuario_id is not None and bool(
            getattr(self.usuario, "ativo", False)
        )
