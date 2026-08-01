"""Registro de aulas e controle de frequencia.

Modelagem em duas tabelas
-------------------------
``Aula`` representa o evento (a aula que aconteceu, com conteudo ministrado)
e ``Frequencia`` representa a situacao de cada aluno naquela aula.

A alternativa — gravar apenas as faltas — foi descartada de proposito: sem o
registro da aula nao ha como distinguir "aluno presente" de "chamada nunca
feita", e o percentual de frequencia do boletim ficaria incorreto. Com o
registro explicito da aula, a coordenacao consegue cobrar chamadas pendentes.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
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
from app.models.base import ModeloBase, TimestampMixin
from app.models.enums import SituacaoPresenca


class Aula(ModeloBase, TimestampMixin):
    """Aula efetivamente ministrada (diario de classe)."""

    __tablename__ = "aulas"
    __table_args__ = (
        # Duas aulas da mesma disciplina no mesmo dia sao legitimas (aulas
        # geminadas), por isso a unicidade inclui a ordem dentro do dia.
        UniqueConstraint(
            "turma_disciplina_id", "data_aula", "ordem_no_dia", name="aula_unica"
        ),
        Index("ix_aulas_data", "data_aula"),
    )

    turma_disciplina_id: Mapped[int] = mapped_column(
        ForeignKey("turmas_disciplinas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data_aula: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ordem_no_dia: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="1 para a primeira aula do dia, 2 para a geminada seguinte.",
    )
    quantidade_aulas: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Quantas aulas do calendario este registro representa.",
    )

    conteudo: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Conteudo ministrado (exigido pelo diario)."
    )
    tarefa_casa: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    chamada_realizada: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Marca se a frequencia ja foi registrada para esta aula.",
    )
    registrada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    turma_disciplina = relationship(
        "TurmaDisciplina", back_populates="aulas", lazy="joined"
    )
    frequencias = relationship(
        "Frequencia",
        back_populates="aula",
        cascade="all, delete-orphan",
        lazy="select",
    )
    registrada_por = relationship("Usuario", foreign_keys=[registrada_por_id])

    # ------------------------------------------------------------------
    def contar_por_situacao(self) -> dict[str, int]:
        """Resumo da chamada agregado no banco, sem carregar as linhas."""
        linhas = (
            db.session.query(Frequencia.situacao, func.count(Frequencia.id))
            .filter(Frequencia.aula_id == self.id)
            .group_by(Frequencia.situacao)
            .all()
        )
        resumo = {situacao.value: 0 for situacao in SituacaoPresenca}
        for situacao, total in linhas:
            chave = situacao.value if hasattr(situacao, "value") else str(situacao)
            resumo[chave] = total
        return resumo

    @property
    def total_faltas(self) -> int:
        return (
            db.session.query(func.count(Frequencia.id))
            .filter(
                Frequencia.aula_id == self.id,
                Frequencia.situacao == SituacaoPresenca.FALTA,
            )
            .scalar()
            or 0
        )

    @property
    def descricao(self) -> str:
        vinculo = self.turma_disciplina
        rotulo = vinculo.descricao if vinculo else "?"
        return f"{rotulo} - {self.data_aula.strftime('%d/%m/%Y')}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Aula {self.id} {self.data_aula}>"


class Frequencia(ModeloBase, TimestampMixin):
    """Situacao de presenca de um aluno em uma aula especifica."""

    __tablename__ = "frequencias"
    __table_args__ = (
        UniqueConstraint("aula_id", "matricula_id", name="frequencia_unica"),
        Index("ix_frequencias_matricula_situacao", "matricula_id", "situacao"),
    )

    aula_id: Mapped[int] = mapped_column(
        ForeignKey("aulas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matricula_id: Mapped[int] = mapped_column(
        ForeignKey("matriculas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    situacao: Mapped[SituacaoPresenca] = mapped_column(
        SAEnum(
            SituacaoPresenca,
            name="situacao_presenca",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=SituacaoPresenca.PRESENTE,
        index=True,
    )
    justificativa: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registrada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    aula = relationship("Aula", back_populates="frequencias")
    matricula = relationship("Matricula", back_populates="frequencias")
    registrada_por = relationship("Usuario", foreign_keys=[registrada_por_id])

    @property
    def presente(self) -> bool:
        """Conta como presenca no calculo legal de frequencia."""
        return self.situacao.conta_presenca

    @property
    def e_falta(self) -> bool:
        return self.situacao is SituacaoPresenca.FALTA

    def justificar(self, motivo: str) -> None:
        """Converte a falta em falta justificada."""
        self.situacao = SituacaoPresenca.FALTA_JUSTIFICADA
        self.justificativa = motivo

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Frequencia aula={self.aula_id} matricula={self.matricula_id} "
            f"{self.situacao.value}>"
        )
