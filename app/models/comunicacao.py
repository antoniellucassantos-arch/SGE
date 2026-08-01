"""Avisos e comunicados entre a escola e a comunidade escolar."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import ExclusaoLogicaMixin, ModeloBase, TimestampMixin, agora_utc
from app.models.enums import PapelUsuario, PrioridadeAviso, PublicoAviso


class Aviso(ModeloBase, TimestampMixin, ExclusaoLogicaMixin):
    """Comunicado publicado para um segmento da comunidade escolar."""

    __tablename__ = "avisos"
    __table_args__ = (
        Index("ix_avisos_publico_publicado", "publico", "publicado"),
        Index("ix_avisos_vigencia", "data_inicio", "data_fim"),
    )

    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    resumo: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="Chamada curta exibida na listagem."
    )

    publico: Mapped[PublicoAviso] = mapped_column(
        SAEnum(
            PublicoAviso,
            name="publico_aviso",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=PublicoAviso.TODOS,
        index=True,
    )
    prioridade: Mapped[PrioridadeAviso] = mapped_column(
        SAEnum(
            PrioridadeAviso,
            name="prioridade_aviso",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=PrioridadeAviso.NORMAL,
        index=True,
    )

    turma_id: Mapped[int | None] = mapped_column(
        ForeignKey("turmas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Obrigatorio quando o publico e uma turma especifica.",
    )
    autor_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # -- Publicacao e vigencia ----------------------------------------------
    publicado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    fixado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Avisos fixados aparecem no topo da lista.",
    )
    data_inicio: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, index=True
    )
    data_fim: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="Data limite de exibicao. Nulo = sem expiracao."
    )
    anexo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    autor = relationship("Usuario", foreign_keys=[autor_id], lazy="joined")
    turma = relationship("Turma", lazy="joined")
    leituras = relationship(
        "AvisoLeitura",
        back_populates="aviso",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ------------------------------------------------------------------
    @property
    def esta_vigente(self) -> bool:
        hoje = date.today()
        if not self.publicado or self.esta_excluido:
            return False
        if self.data_inicio > hoje:
            return False
        return self.data_fim is None or self.data_fim >= hoje

    @property
    def texto_resumido(self) -> str:
        """Resumo informado ou os primeiros 150 caracteres da mensagem."""
        if self.resumo:
            return self.resumo
        texto = (self.mensagem or "").strip()
        return texto[:150] + "..." if len(texto) > 150 else texto

    @property
    def nome_autor(self) -> str:
        return self.autor.nome_completo if self.autor else "Sistema"

    def total_leituras(self) -> int:
        return (
            db.session.query(func.count(AvisoLeitura.id))
            .filter(
                AvisoLeitura.aviso_id == self.id,
                AvisoLeitura.lido_em.isnot(None),
            )
            .scalar()
            or 0
        )

    def foi_lido_por(self, usuario_id: int) -> bool:
        return (
            db.session.query(AvisoLeitura.id)
            .filter(
                AvisoLeitura.aviso_id == self.id,
                AvisoLeitura.usuario_id == usuario_id,
                AvisoLeitura.lido_em.isnot(None),
            )
            .first()
            is not None
        )

    def destinado_a(self, usuario) -> bool:
        """Decide se um usuario especifico deve ver este aviso.

        Centralizar a regra aqui evita que cada tela reimplemente a
        segmentacao — e diverja dela.
        """
        if not self.esta_vigente or usuario is None:
            return False

        if self.publico is PublicoAviso.TODOS:
            return True
        if self.publico is PublicoAviso.EQUIPE:
            return usuario.e_equipe_interna
        if self.publico is PublicoAviso.PROFESSORES:
            return usuario.papel is PapelUsuario.PROFESSOR
        if self.publico is PublicoAviso.ALUNOS:
            return usuario.papel is PapelUsuario.ALUNO
        if self.publico is PublicoAviso.RESPONSAVEIS:
            return usuario.papel is PapelUsuario.RESPONSAVEL

        if self.publico is PublicoAviso.TURMA:
            if usuario.e_equipe_interna:
                return True
            return self._alcanca_turma(usuario)

        return False

    def _alcanca_turma(self, usuario) -> bool:
        """Verifica se aluno ou responsavel esta ligado a turma do aviso."""
        if not self.turma_id:
            return False

        if usuario.papel is PapelUsuario.ALUNO and usuario.aluno:
            turma = usuario.aluno.turma_atual
            return bool(turma and turma.id == self.turma_id)

        if usuario.papel is PapelUsuario.RESPONSAVEL and usuario.responsavel:
            for aluno in usuario.responsavel.alunos:
                turma = aluno.turma_atual
                if turma and turma.id == self.turma_id:
                    return True

        return False

    def __str__(self) -> str:
        return self.titulo

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Aviso {self.id} {self.titulo[:30]}>"


class AvisoLeitura(ModeloBase):
    """Confirmacao de leitura de um aviso por um usuario.

    Sem esta tabela nao ha como a escola provar que um comunicado importante
    (reuniao de pais, alteracao de calendario) chegou ao responsavel.
    """

    __tablename__ = "avisos_leituras"
    __table_args__ = (
        UniqueConstraint("aviso_id", "usuario_id", name="leitura_unica"),
        Index("ix_avisos_leituras_usuario", "usuario_id", "lido_em"),
    )

    aviso_id: Mapped[int] = mapped_column(
        ForeignKey("avisos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lido_em: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=agora_utc
    )

    aviso = relationship("Aviso", back_populates="leituras")
    usuario = relationship("Usuario", lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AvisoLeitura aviso={self.aviso_id} usuario={self.usuario_id}>"
