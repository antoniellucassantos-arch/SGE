"""Model de matricula: o vinculo do aluno com uma turma em um ano letivo.

Papel central na modelagem
--------------------------
Notas, frequencia e resultados apontam para ``Matricula``, e **nunca**
diretamente para ``Aluno``. O motivo e historico: um aluno reprovado cursa a
mesma disciplina duas vezes, em anos diferentes. Se as notas apontassem para
o aluno, os dois anos se misturariam e o historico escolar sairia errado.
Ancorando em ``Matricula``, cada ano letivo mantem seu proprio conjunto
isolado e auditavel de lancamentos.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
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
from app.models.base import ExclusaoLogicaMixin, ModeloBase, TimestampMixin
from app.models.enums import ResultadoFinal, SituacaoMatricula


class Matricula(ModeloBase, TimestampMixin, ExclusaoLogicaMixin):
    """Vinculo aluno x turma x ano letivo."""

    __tablename__ = "matriculas"
    __table_args__ = (
        # Um aluno nao pode ter duas matriculas no mesmo ano letivo.
        # A regra "apenas uma ativa" e reforcada no service, porque uma
        # matricula cancelada e outra ativa no mesmo ano sao legitimas
        # (ex.: aluno cancelou e voltou no segundo semestre).
        UniqueConstraint(
            "aluno_id", "ano_letivo_id", "turma_id", name="matricula_unica"
        ),
        Index("ix_matriculas_turma_situacao", "turma_id", "situacao"),
        Index("ix_matriculas_ano_situacao", "ano_letivo_id", "situacao"),
    )

    numero: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        doc="Numero oficial da matricula, impresso em declaracoes.",
    )

    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    turma_id: Mapped[int] = mapped_column(
        ForeignKey("turmas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ano_letivo_id: Mapped[int] = mapped_column(
        ForeignKey("anos_letivos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    data_matricula: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )
    data_saida: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="Data de transferencia, cancelamento ou conclusao."
    )

    situacao: Mapped[SituacaoMatricula] = mapped_column(
        SAEnum(
            SituacaoMatricula,
            name="situacao_matricula",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=SituacaoMatricula.ATIVA,
        index=True,
    )
    resultado_final: Mapped[ResultadoFinal] = mapped_column(
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

    # -- Consolidacao anual --------------------------------------------------
    # Valores derivados, recalculados pelo service ao fechar o ano. Sao
    # persistidos de proposito: o historico escolar precisa refletir o que foi
    # apurado na epoca, mesmo que uma regra de calculo mude depois.
    media_geral: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    percentual_frequencia: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    total_faltas: Mapped[int | None] = mapped_column(nullable=True)

    escola_origem: Mapped[str | None] = mapped_column(
        String(150), nullable=True, doc="Preenchido em caso de transferencia recebida."
    )
    escola_destino: Mapped[str | None] = mapped_column(
        String(150), nullable=True, doc="Preenchido em caso de transferencia emitida."
    )
    motivo_saida: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Relacionamentos -----------------------------------------------------
    aluno = relationship("Aluno", back_populates="matriculas", lazy="joined")
    turma = relationship("Turma", back_populates="matriculas", lazy="joined")
    ano_letivo = relationship("AnoLetivo", back_populates="matriculas", lazy="joined")

    notas = relationship(
        "Nota", back_populates="matricula", cascade="all, delete-orphan", lazy="select"
    )
    frequencias = relationship(
        "Frequencia",
        back_populates="matricula",
        cascade="all, delete-orphan",
        lazy="select",
    )
    resultados = relationship(
        "ResultadoDisciplina",
        back_populates="matricula",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def esta_ativa(self) -> bool:
        return self.situacao is SituacaoMatricula.ATIVA

    @property
    def aceita_lancamentos(self) -> bool:
        """Impede lancar nota/falta em matricula encerrada ou ano fechado."""
        if self.situacao is not SituacaoMatricula.ATIVA:
            return False
        return bool(self.ano_letivo and self.ano_letivo.aceita_lancamentos)

    @property
    def nome_aluno(self) -> str:
        return self.aluno.nome_exibicao if self.aluno else "?"

    @property
    def descricao(self) -> str:
        turma = self.turma.identificacao_curta if self.turma else "?"
        return f"{self.nome_aluno} - {turma}"

    # ------------------------------------------------------------------
    # Transicoes de situacao
    # ------------------------------------------------------------------
    def transferir(self, escola_destino: str, motivo: str | None = None) -> None:
        self.situacao = SituacaoMatricula.TRANSFERIDA
        self.data_saida = date.today()
        self.escola_destino = escola_destino
        self.motivo_saida = motivo

    def cancelar(self, motivo: str | None = None) -> None:
        self.situacao = SituacaoMatricula.CANCELADA
        self.data_saida = date.today()
        self.motivo_saida = motivo

    def trancar(self, motivo: str | None = None) -> None:
        self.situacao = SituacaoMatricula.TRANCADA
        self.motivo_saida = motivo

    def reativar(self) -> None:
        self.situacao = SituacaoMatricula.ATIVA
        self.data_saida = None
        self.motivo_saida = None

    def concluir(self, resultado: ResultadoFinal) -> None:
        self.situacao = SituacaoMatricula.CONCLUIDA
        self.resultado_final = resultado
        self.data_saida = self.data_saida or date.today()

    # ------------------------------------------------------------------
    # Geracao do numero de matricula
    # ------------------------------------------------------------------
    @staticmethod
    def gerar_numero(ano: int) -> str:
        """Numero no formato ``AAAA-NNNNN``, sequencial dentro do ano.

        Baseia-se no maior numero existente (e nao na contagem) para que
        exclusoes nao provoquem colisao de numero oficial.
        """
        prefixo = f"{ano}-"
        ultimo = (
            db.session.query(func.max(Matricula.numero))
            .filter(Matricula.numero.like(f"{prefixo}%"))
            .scalar()
        )

        sequencial = 1
        if ultimo:
            try:
                sequencial = int(ultimo.split("-")[1]) + 1
            except (IndexError, ValueError):
                sequencial = 1

        return f"{prefixo}{sequencial:05d}"

    def __str__(self) -> str:
        return self.numero

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Matricula {self.numero} {self.situacao.value}>"


@db.event.listens_for(Matricula, "before_insert")
def _garantir_numero_matricula(mapper, connection, alvo: Matricula) -> None:  # noqa: ARG001
    """Rede de seguranca para criacoes fora do service (seed, importacao)."""
    if not alvo.numero:
        ano = alvo.ano_letivo.ano if alvo.ano_letivo else date.today().year
        alvo.numero = Matricula.gerar_numero(ano)
