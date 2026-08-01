"""Models de infraestrutura: configuracao da escola, auditoria e backups."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import ModeloBase, TimestampMixin, agora_utc
from app.models.enums import AcaoAuditoria


class ConfiguracaoEscola(ModeloBase, TimestampMixin):
    """Dados institucionais e parametros gerais do sistema.

    Tabela de **linha unica** (``id = 1``). Modelar como tabela, e nao como
    arquivo de configuracao, permite que a secretaria altere o cabecalho dos
    documentos, o logo e as regras academicas pela propria interface, sem
    depender de um desenvolvedor e sem reiniciar a aplicacao.
    """

    __tablename__ = "configuracoes_escola"

    # -- Identificacao institucional ----------------------------------------
    nome: Mapped[str] = mapped_column(
        String(150), nullable=False, default="Escola"
    )
    nome_fantasia: Mapped[str | None] = mapped_column(String(150), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    codigo_inep: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="Codigo da escola no censo escolar."
    )
    diretor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    secretario: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # -- Contato e endereco --------------------------------------------------
    telefone: Mapped[str | None] = mapped_column(String(11), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    site: Mapped[str | None] = mapped_column(String(150), nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    logradouro: Mapped[str | None] = mapped_column(String(150), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(15), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cidade: Mapped[str | None] = mapped_column(String(80), nullable=True)
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # -- Identidade visual ---------------------------------------------------
    logo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cor_primaria: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#1a56db"
    )

    # -- Parametros academicos padrao ---------------------------------------
    # Servem de valor inicial ao criar um ano letivo; cada ano guarda a
    # propria copia, para que uma mudanca de regra nao altere o passado.
    media_aprovacao: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=6.00
    )
    media_recuperacao: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=4.00
    )
    frequencia_minima: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=75.00
    )
    nota_maxima: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=10.00
    )
    quantidade_periodos: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4, doc="4 = bimestral, 3 = trimestral."
    )

    # -- Operacao ------------------------------------------------------------
    backup_automatico: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    backup_hora: Mapped[str] = mapped_column(
        String(5), nullable=False, default="02:00", doc="Horario HH:MM do backup."
    )
    mensagem_login: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Aviso exibido na tela de login."
    )

    # ------------------------------------------------------------------
    @classmethod
    def obter(cls) -> ConfiguracaoEscola:
        """Retorna a configuracao unica, criando-a na primeira execucao."""
        config = db.session.get(cls, 1)
        if config is None:
            config = cls(id=1, nome="Escola")
            db.session.add(config)
            db.session.commit()
        return config

    @property
    def endereco_completo(self) -> str:
        partes: list[str] = []
        if self.logradouro:
            partes.append(
                f"{self.logradouro}, {self.numero}" if self.numero else self.logradouro
            )
        if self.bairro:
            partes.append(self.bairro)
        if self.cidade:
            partes.append(f"{self.cidade}/{self.uf}" if self.uf else self.cidade)
        return " - ".join(partes)

    @property
    def nome_exibicao(self) -> str:
        return self.nome_fantasia or self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConfiguracaoEscola {self.nome}>"


class LogAuditoria(ModeloBase):
    """Trilha de auditoria imutavel de acoes sensiveis.

    Nao ha rota de edicao nem de exclusao para esta tabela — por definicao,
    uma trilha que pode ser alterada nao serve como evidencia. A limpeza de
    registros antigos e feita apenas por rotina administrativa explicita.
    """

    __tablename__ = "logs_auditoria"
    __table_args__ = (
        Index("ix_logs_entidade", "entidade", "entidade_id"),
        Index("ix_logs_usuario_data", "usuario_id", "criado_em"),
        Index("ix_logs_acao_data", "acao", "criado_em"),
    )

    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Nulo em eventos anonimos (ex.: falha de login com e-mail inexistente).",
    )
    usuario_nome: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        doc="Copia do nome no momento do evento: a trilha sobrevive a exclusao do usuario.",
    )

    acao: Mapped[AcaoAuditoria] = mapped_column(
        SAEnum(
            AcaoAuditoria,
            name="acao_auditoria",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )
    entidade: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    entidade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detalhes: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="JSON com os campos alterados (antes/depois)."
    )

    endereco_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    navegador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rota: Mapped[str | None] = mapped_column(String(255), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=agora_utc, index=True
    )

    usuario = relationship("Usuario", foreign_keys=[usuario_id], lazy="joined")

    @property
    def nome_responsavel(self) -> str:
        if self.usuario:
            return self.usuario.nome_completo
        return self.usuario_nome or "Sistema"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LogAuditoria {self.acao.value} {self.entidade}#{self.entidade_id}>"


class RegistroBackup(ModeloBase):
    """Historico de backups gerados pelo sistema."""

    __tablename__ = "registros_backup"

    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    caminho: Mapped[str] = mapped_column(String(500), nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    automatico: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sucesso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mensagem_erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    gerado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=agora_utc, index=True
    )

    gerado_por = relationship("Usuario", foreign_keys=[gerado_por_id], lazy="joined")

    @property
    def tamanho_legivel(self) -> str:
        """Formata o tamanho em unidade adequada (B, KB, MB, GB)."""
        tamanho = float(self.tamanho_bytes or 0)
        for unidade in ("B", "KB", "MB", "GB"):
            if tamanho < 1024 or unidade == "GB":
                return f"{tamanho:.1f} {unidade}".replace(".0 ", " ")
            tamanho /= 1024
        return f"{tamanho:.1f} GB"

    @property
    def origem(self) -> str:
        return "Automatico" if self.automatico else "Manual"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegistroBackup {self.nome_arquivo}>"
