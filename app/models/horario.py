"""Grade de horarios: tempos de aula e alocacao semanal.

Duas entidades:

``TempoAula``
    Define os "slots" da escola (1o tempo 07:00-07:50, intervalo, etc.). Sao
    poucos registros, reutilizados por todas as turmas.
``Horario``
    Aloca um ``TurmaDisciplina`` em um dia da semana e um tempo de aula.

Conflitos (mesmo professor em duas turmas no mesmo horario, ou duas turmas na
mesma sala) sao detectados por ``services/horario_service.py``. A restricao
de unicidade no banco cobre o caso mais simples — a mesma turma nao pode ter
duas aulas no mesmo tempo — e serve como ultima linha de defesa.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase, TimestampMixin
from app.models.enums import DiaSemana, Turno


class TempoAula(ModeloBase, TimestampMixin):
    """Faixa de horario padronizada da escola (1o tempo, 2o tempo, recreio)."""

    __tablename__ = "tempos_aula"
    __table_args__ = (
        UniqueConstraint("turno", "ordem", name="tempo_unico_por_turno"),
        CheckConstraint("hora_fim > hora_inicio", name="intervalo_valido"),
    )

    turno: Mapped[Turno] = mapped_column(
        SAEnum(
            Turno,
            name="turno",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )
    ordem: Mapped[int] = mapped_column(
        Integer, nullable=False, doc="Posicao do tempo dentro do turno."
    )
    nome: Mapped[str] = mapped_column(
        String(40), nullable=False, doc='Ex.: "1o tempo", "Intervalo".'
    )
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fim: Mapped[time] = mapped_column(Time, nullable=False)
    e_intervalo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Intervalos aparecem na grade mas nao recebem disciplina.",
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    horarios = relationship("Horario", back_populates="tempo_aula", lazy="select")

    @property
    def faixa(self) -> str:
        return (
            f"{self.hora_inicio.strftime('%H:%M')} - "
            f"{self.hora_fim.strftime('%H:%M')}"
        )

    @property
    def duracao_minutos(self) -> int:
        inicio = self.hora_inicio.hour * 60 + self.hora_inicio.minute
        fim = self.hora_fim.hour * 60 + self.hora_fim.minute
        return max(0, fim - inicio)

    def __str__(self) -> str:
        return f"{self.nome} ({self.faixa})"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TempoAula {self.turno.value} {self.ordem} {self.faixa}>"


class Horario(ModeloBase, TimestampMixin):
    """Alocacao de uma disciplina na grade semanal de uma turma."""

    __tablename__ = "horarios"
    __table_args__ = (
        UniqueConstraint(
            "turma_id", "dia_semana", "tempo_aula_id", name="horario_unico_turma"
        ),
        Index("ix_horarios_dia_tempo", "dia_semana", "tempo_aula_id"),
    )

    turma_id: Mapped[int] = mapped_column(
        ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turma_disciplina_id: Mapped[int] = mapped_column(
        ForeignKey("turmas_disciplinas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tempo_aula_id: Mapped[int] = mapped_column(
        ForeignKey("tempos_aula.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sala_id: Mapped[int | None] = mapped_column(
        ForeignKey("salas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Sala especifica da aula (laboratorio, quadra). Nulo usa a sala da turma.",
    )

    dia_semana: Mapped[DiaSemana] = mapped_column(
        SAEnum(
            DiaSemana,
            name="dia_semana",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )

    turma = relationship("Turma", back_populates="horarios")
    turma_disciplina = relationship(
        "TurmaDisciplina", back_populates="horarios", lazy="joined"
    )
    tempo_aula = relationship("TempoAula", back_populates="horarios", lazy="joined")
    sala = relationship("Sala", lazy="joined")

    # ------------------------------------------------------------------
    @property
    def disciplina(self):
        return self.turma_disciplina.disciplina if self.turma_disciplina else None

    @property
    def professor(self):
        return self.turma_disciplina.professor if self.turma_disciplina else None

    @property
    def nome_disciplina(self) -> str:
        disciplina = self.disciplina
        return disciplina.nome if disciplina else "?"

    @property
    def cor(self) -> str:
        """Cor da disciplina, usada para colorir a grade visual."""
        disciplina = self.disciplina
        return disciplina.cor if disciplina else "#6c757d"

    @property
    def sala_efetiva(self):
        """Sala especifica do horario ou, na ausencia, a sala fixa da turma."""
        return self.sala or (self.turma.sala if self.turma else None)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Horario turma={self.turma_id} dia={self.dia_semana.value} "
            f"tempo={self.tempo_aula_id}>"
        )
