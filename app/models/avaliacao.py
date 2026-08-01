"""Avaliacoes, notas e consolidacao de resultado por disciplina.

Regra de calculo adotada
------------------------
A media do periodo e uma **media ponderada** pelos pesos das avaliacoes,
normalizada para a escala do ano letivo::

    media = soma(nota_i x peso_i) / soma(peso_i)

Avaliacoes de recuperacao ficam fora da media do periodo: elas *substituem*
o resultado quando forem maiores, conforme a pratica pedagogica mais comum
no ensino brasileiro. A regra concreta vive em ``services/nota_service.py``;
aqui ficam apenas os dados e as propriedades derivadas mais simples.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase, TimestampMixin
from app.models.enums import ResultadoFinal, TipoAvaliacao


class Avaliacao(ModeloBase, TimestampMixin):
    """Instrumento avaliativo aplicado a uma turma em uma disciplina."""

    __tablename__ = "avaliacoes"
    __table_args__ = (
        CheckConstraint("peso > 0", name="peso_positivo"),
        CheckConstraint("valor_maximo > 0", name="valor_maximo_positivo"),
        Index("ix_avaliacoes_vinculo_periodo", "turma_disciplina_id", "periodo_id"),
    )

    turma_disciplina_id: Mapped[int] = mapped_column(
        ForeignKey("turmas_disciplinas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    periodo_id: Mapped[int] = mapped_column(
        ForeignKey("periodos_letivos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo: Mapped[TipoAvaliacao] = mapped_column(
        SAEnum(
            TipoAvaliacao,
            name="tipo_avaliacao",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=TipoAvaliacao.PROVA,
        index=True,
    )
    peso: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("1.00")
    )
    valor_maximo: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("10.00")
    )
    data_aplicacao: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)

    publicada: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Enquanto falsa, as notas ficam visiveis apenas ao professor.",
    )
    criada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    turma_disciplina = relationship(
        "TurmaDisciplina", back_populates="avaliacoes", lazy="joined"
    )
    periodo = relationship("PeriodoLetivo", back_populates="avaliacoes", lazy="joined")
    notas = relationship(
        "Nota", back_populates="avaliacao", cascade="all, delete-orphan", lazy="select"
    )
    criada_por = relationship("Usuario", foreign_keys=[criada_por_id])

    # ------------------------------------------------------------------
    @property
    def e_recuperacao(self) -> bool:
        """Recuperacao nao entra na media ponderada do periodo."""
        return self.tipo is TipoAvaliacao.RECUPERACAO

    @property
    def descricao_completa(self) -> str:
        vinculo = self.turma_disciplina
        return f"{self.nome} - {vinculo.descricao if vinculo else '?'}"

    def total_lancadas(self) -> int:
        """Quantas notas ja foram efetivamente informadas."""
        from sqlalchemy import func

        from app.extensions import db

        return (
            db.session.query(func.count(Nota.id))
            .filter(Nota.avaliacao_id == self.id, Nota.valor.isnot(None))
            .scalar()
            or 0
        )

    def __str__(self) -> str:
        return self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Avaliacao {self.id} {self.nome}>"


class Nota(ModeloBase, TimestampMixin):
    """Nota de um aluno em uma avaliacao.

    O valor e ``nullable`` de proposito: a linha e criada para todos os alunos
    da turma quando a avaliacao e aberta, e o campo vazio representa "nota
    ainda nao lancada" — diferente de zero, que representa "o aluno tirou
    zero". Confundir os dois casos e um erro comum e grave em boletim.
    """

    __tablename__ = "notas"
    __table_args__ = (
        UniqueConstraint("avaliacao_id", "matricula_id", name="nota_unica"),
        CheckConstraint("valor IS NULL OR valor >= 0", name="nota_nao_negativa"),
        Index("ix_notas_matricula", "matricula_id"),
    )

    avaliacao_id: Mapped[int] = mapped_column(
        ForeignKey("avaliacoes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matricula_id: Mapped[int] = mapped_column(
        ForeignKey("matriculas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    valor: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ausente: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Aluno faltou a avaliacao (conta zero, mas e sinalizado no boletim).",
    )
    observacao: Mapped[str | None] = mapped_column(String(255), nullable=True)

    lancada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    alterada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    avaliacao = relationship("Avaliacao", back_populates="notas", lazy="joined")
    matricula = relationship("Matricula", back_populates="notas")
    lancada_por = relationship("Usuario", foreign_keys=[lancada_por_id])
    alterada_por = relationship("Usuario", foreign_keys=[alterada_por_id])

    # ------------------------------------------------------------------
    @property
    def foi_lancada(self) -> bool:
        return self.valor is not None or self.ausente

    @property
    def valor_efetivo(self) -> Decimal:
        """Valor usado nos calculos: ausencia vale zero."""
        if self.ausente:
            return Decimal("0.00")
        return self.valor if self.valor is not None else Decimal("0.00")

    @property
    def valor_exibicao(self) -> str:
        """Texto para telas e boletim, distinguindo 'sem nota' de zero."""
        if self.ausente:
            return "F"
        if self.valor is None:
            return "-"
        return f"{self.valor:.1f}".replace(".", ",")

    @property
    def percentual(self) -> float | None:
        """Aproveitamento relativo ao valor maximo da avaliacao."""
        if not self.foi_lancada or not self.avaliacao:
            return None
        maximo = self.avaliacao.valor_maximo or Decimal("10")
        if maximo <= 0:
            return None
        return round(float(self.valor_efetivo / maximo) * 100, 1)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Nota avaliacao={self.avaliacao_id} "
            f"matricula={self.matricula_id} valor={self.valor}>"
        )


class ResultadoDisciplina(ModeloBase, TimestampMixin):
    """Consolidacao do desempenho do aluno em uma disciplina no ano.

    Tabela derivada, recalculada pelo ``nota_service``. Existe por dois
    motivos praticos: (1) o boletim de uma turma de 40 alunos precisaria de
    dezenas de agregacoes em tempo real a cada abertura de tela; (2) o
    resultado apurado no fechamento do ano deve permanecer congelado, mesmo
    que as regras de calculo mudem em anos seguintes.
    """

    __tablename__ = "resultados_disciplinas"
    __table_args__ = (
        UniqueConstraint(
            "matricula_id", "turma_disciplina_id", name="resultado_unico"
        ),
        Index("ix_resultados_situacao", "resultado"),
    )

    matricula_id: Mapped[int] = mapped_column(
        ForeignKey("matriculas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turma_disciplina_id: Mapped[int] = mapped_column(
        ForeignKey("turmas_disciplinas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Medias por periodo: ate 4 bimestres (ou 3 trimestres, deixando o 4o nulo).
    media_periodo_1: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    media_periodo_2: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    media_periodo_3: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    media_periodo_4: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    media_anual: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    nota_recuperacao: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    media_final: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    total_aulas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_faltas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    percentual_frequencia: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    resultado: Mapped[ResultadoFinal] = mapped_column(
        SAEnum(
            ResultadoFinal,
            name="resultado_final",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=ResultadoFinal.CURSANDO,
        index=True,
    )
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    matricula = relationship("Matricula", back_populates="resultados")
    turma_disciplina = relationship("TurmaDisciplina", lazy="joined")

    # ------------------------------------------------------------------
    def medias_por_periodo(self) -> list[Decimal | None]:
        return [
            self.media_periodo_1,
            self.media_periodo_2,
            self.media_periodo_3,
            self.media_periodo_4,
        ]

    def definir_media_periodo(self, ordem: int, valor: Decimal | None) -> None:
        """Grava a media do periodo pela ordem (1 a 4)."""
        if 1 <= ordem <= 4:
            setattr(self, f"media_periodo_{ordem}", valor)

    @property
    def nome_disciplina(self) -> str:
        vinculo = self.turma_disciplina
        return vinculo.disciplina.nome if vinculo and vinculo.disciplina else "?"

    @property
    def aprovado(self) -> bool:
        return self.resultado in {
            ResultadoFinal.APROVADO,
            ResultadoFinal.APROVADO_CONSELHO,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ResultadoDisciplina matricula={self.matricula_id} "
            f"media={self.media_final} {self.resultado.value}>"
        )
