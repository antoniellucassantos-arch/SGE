"""Estrutura academica: ano letivo, periodos, series, salas, disciplinas e turmas.

Estes models formam o "esqueleto" sobre o qual matriculas, notas, frequencia
e horarios se apoiam. Todos sao versionados por ano letivo, de modo que
alterar a grade de 2027 nunca reescreve o historico de 2026 — requisito
inegociavel para um sistema que emite documento escolar oficial.
"""

from __future__ import annotations

from datetime import date

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
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ExclusaoLogicaMixin, ModeloBase, TimestampMixin
from app.models.enums import NivelEnsino, SituacaoAnoLetivo, Turno
from app.utils.seguranca import normalizar_texto, remover_acentos


class AnoLetivo(ModeloBase, TimestampMixin):
    """Periodo anual que agrupa turmas, matriculas e lancamentos.

    Exatamente um ano letivo pode estar marcado como ``corrente``; ele define
    o contexto padrao de todas as telas do sistema.
    """

    __tablename__ = "anos_letivos"
    __table_args__ = (
        CheckConstraint("data_fim > data_inicio", name="periodo_valido"),
        CheckConstraint("ano >= 2000 AND ano <= 2100", name="ano_plausivel"),
    )

    ano: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, index=True
    )
    descricao: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    data_fim: Mapped[date] = mapped_column(Date, nullable=False)

    situacao: Mapped[SituacaoAnoLetivo] = mapped_column(
        SAEnum(
            SituacaoAnoLetivo,
            name="situacao_ano_letivo",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=SituacaoAnoLetivo.PLANEJAMENTO,
        index=True,
    )
    corrente: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Ano letivo usado como contexto padrao do sistema.",
    )

    # -- Regras academicas do ano (podem variar entre anos) ------------------
    media_aprovacao: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=6.00
    )
    media_recuperacao: Mapped[float] = mapped_column(
        Numeric(4, 2),
        nullable=False,
        default=4.00,
        doc="Media minima para ter direito a recuperacao.",
    )
    frequencia_minima: Mapped[float] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=75.00,
        doc="Percentual minimo de frequencia para aprovacao (LDB: 75%).",
    )
    nota_maxima: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=10.00
    )
    minimo_aulas_para_apurar_falta: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
        doc=(
            "Volume minimo de aulas antes de reprovar por falta. Evita "
            "reprovar alguem em marco por duas ausencias. Fica aqui, e nao "
            "fixo no codigo, porque a carga horaria varia entre escolas."
        ),
    )

    # -- Relacionamentos -----------------------------------------------------
    periodos = relationship(
        "PeriodoLetivo",
        back_populates="ano_letivo",
        cascade="all, delete-orphan",
        order_by="PeriodoLetivo.ordem",
        lazy="selectin",
    )
    turmas = relationship(
        "Turma", back_populates="ano_letivo", lazy="select"
    )
    matriculas = relationship(
        "Matricula", back_populates="ano_letivo", lazy="select"
    )

    # ------------------------------------------------------------------
    @property
    def esta_encerrado(self) -> bool:
        return self.situacao is SituacaoAnoLetivo.ENCERRADO

    @property
    def aceita_lancamentos(self) -> bool:
        """Ano encerrado vira somente leitura: protege o historico escolar."""
        return self.situacao is SituacaoAnoLetivo.EM_ANDAMENTO

    @property
    def total_dias_letivos(self) -> int:
        return (self.data_fim - self.data_inicio).days + 1

    def contem_data(self, dia: date) -> bool:
        return self.data_inicio <= dia <= self.data_fim

    def periodo_da_data(self, dia: date):
        """Descobre em qual bimestre/trimestre uma data cai."""
        for periodo in self.periodos:
            if periodo.data_inicio <= dia <= periodo.data_fim:
                return periodo
        return None

    def __str__(self) -> str:
        return str(self.ano)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnoLetivo {self.ano}>"


class PeriodoLetivo(ModeloBase, TimestampMixin):
    """Bimestre, trimestre ou semestre dentro de um ano letivo."""

    __tablename__ = "periodos_letivos"
    __table_args__ = (
        UniqueConstraint("ano_letivo_id", "ordem", name="ordem_unica_no_ano"),
        CheckConstraint("data_fim > data_inicio", name="periodo_valido"),
        CheckConstraint("ordem >= 1 AND ordem <= 8", name="ordem_plausivel"),
    )

    ano_letivo_id: Mapped[int] = mapped_column(
        ForeignKey("anos_letivos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nome: Mapped[str] = mapped_column(String(50), nullable=False)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    data_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    data_fim: Mapped[date] = mapped_column(Date, nullable=False)
    encerrado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Periodo encerrado bloqueia novos lancamentos de nota.",
    )

    ano_letivo = relationship("AnoLetivo", back_populates="periodos")
    avaliacoes = relationship(
        "Avaliacao", back_populates="periodo", lazy="select"
    )

    @property
    def esta_vigente(self) -> bool:
        return self.data_inicio <= date.today() <= self.data_fim

    def __str__(self) -> str:
        return self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PeriodoLetivo {self.nome} ({self.ano_letivo_id})>"


class Serie(ModeloBase, TimestampMixin):
    """Etapa de ensino (1o Ano do Fundamental, 3a Serie do Medio, etc.).

    E independente do ano letivo: a serie "9o Ano" existe todos os anos, e as
    turmas concretas e que sao anuais.
    """

    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("nome", "nivel_ensino", name="serie_unica_por_nivel"),
    )

    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    nivel_ensino: Mapped[NivelEnsino] = mapped_column(
        SAEnum(
            NivelEnsino,
            name="nivel_ensino",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        index=True,
    )
    ordem: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        index=True,
        doc="Ordem pedagogica global, usada na progressao entre series.",
    )
    idade_recomendada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    turmas = relationship("Turma", back_populates="serie", lazy="select")

    @property
    def nome_completo(self) -> str:
        return f"{self.nome} - {self.nivel_ensino.rotulo}"

    def __str__(self) -> str:
        return self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Serie {self.nome}>"


class Sala(ModeloBase, TimestampMixin):
    """Espaco fisico onde as aulas acontecem."""

    __tablename__ = "salas"

    nome: Mapped[str] = mapped_column(
        String(60), nullable=False, unique=True, index=True
    )
    bloco: Mapped[str | None] = mapped_column(String(40), nullable=True)
    andar: Mapped[str | None] = mapped_column(String(20), nullable=True)
    capacidade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possui_projetor: Mapped[bool] = mapped_column(Boolean, default=False)
    possui_ar_condicionado: Mapped[bool] = mapped_column(Boolean, default=False)
    acessivel: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Sala com acessibilidade para cadeirantes."
    )
    ativa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    turmas = relationship("Turma", back_populates="sala", lazy="select")

    @property
    def identificacao(self) -> str:
        return f"{self.nome} ({self.bloco})" if self.bloco else self.nome

    def __str__(self) -> str:
        return self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sala {self.nome}>"


class Disciplina(ModeloBase, TimestampMixin, ExclusaoLogicaMixin):
    """Componente curricular (Matematica, Historia, Educacao Fisica...)."""

    __tablename__ = "disciplinas"
    __table_args__ = (
        Index("ix_disciplinas_nome_normalizado", "nome_normalizado"),
    )

    nome: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    nome_normalizado: Mapped[str] = mapped_column(
        String(100), nullable=False, default=""
    )
    codigo: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        doc="Sigla curta usada em boletins e grades (ex.: MAT, PORT).",
    )
    carga_horaria: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Carga horaria anual em horas."
    )
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    cor: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default="#0d6efd",
        doc="Cor hexadecimal usada na grade de horarios.",
    )
    ativa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    turmas_disciplinas = relationship(
        "TurmaDisciplina", back_populates="disciplina", lazy="select"
    )

    def sincronizar_derivados(self) -> None:
        self.nome = normalizar_texto(self.nome)
        self.nome_normalizado = remover_acentos(self.nome)
        self.codigo = (self.codigo or "").strip().upper()

    def __str__(self) -> str:
        return self.nome

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Disciplina {self.codigo} {self.nome}>"


class Turma(ModeloBase, TimestampMixin, ExclusaoLogicaMixin):
    """Agrupamento anual de alunos de uma mesma serie e turno."""

    __tablename__ = "turmas"
    __table_args__ = (
        UniqueConstraint(
            "ano_letivo_id", "serie_id", "nome", name="turma_unica_no_ano"
        ),
        CheckConstraint("capacidade > 0", name="capacidade_positiva"),
        Index("ix_turmas_ano_turno", "ano_letivo_id", "turno"),
    )

    nome: Mapped[str] = mapped_column(
        String(50), nullable=False, doc='Identificacao curta, ex.: "A", "B".'
    )
    ano_letivo_id: Mapped[int] = mapped_column(
        ForeignKey("anos_letivos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    serie_id: Mapped[int] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sala_id: Mapped[int | None] = mapped_column(
        ForeignKey("salas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    professor_regente_id: Mapped[int | None] = mapped_column(
        ForeignKey("professores.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Professor responsavel pela turma (regente/conselheiro).",
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
    capacidade: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    ativa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Relacionamentos -----------------------------------------------------
    ano_letivo = relationship("AnoLetivo", back_populates="turmas")
    serie = relationship("Serie", back_populates="turmas", lazy="joined")
    sala = relationship("Sala", back_populates="turmas", lazy="joined")
    professor_regente = relationship(
        "Professor", back_populates="turmas_regidas", foreign_keys=[professor_regente_id]
    )
    matriculas = relationship(
        "Matricula", back_populates="turma", lazy="select"
    )
    turmas_disciplinas = relationship(
        "TurmaDisciplina",
        back_populates="turma",
        cascade="all, delete-orphan",
        lazy="select",
    )
    horarios = relationship(
        "Horario", back_populates="turma", cascade="all, delete-orphan", lazy="select"
    )

    # ------------------------------------------------------------------
    @property
    def nome_completo(self) -> str:
        """Identificacao legivel usada em telas e relatorios."""
        serie = self.serie.nome if self.serie else "?"
        return f"{serie} {self.nome} - {self.turno.rotulo}"

    @property
    def identificacao_curta(self) -> str:
        serie = self.serie.nome if self.serie else "?"
        return f"{serie} {self.nome}"

    def contar_matriculas_ativas(self) -> int:
        """Conta alunos ativos sem carregar a colecao inteira na memoria.

        Com milhares de alunos, ``len(turma.matriculas)`` traria todas as
        linhas para o Python apenas para descobrir um numero.
        """
        from app.extensions import db
        from app.models.enums import SituacaoMatricula
        from app.models.matricula import Matricula

        return (
            db.session.query(func.count(Matricula.id))
            .filter(
                Matricula.turma_id == self.id,
                Matricula.situacao == SituacaoMatricula.ATIVA,
                Matricula.excluido_em.is_(None),
            )
            .scalar()
            or 0
        )

    @property
    def vagas_disponiveis(self) -> int:
        return max(0, self.capacidade - self.contar_matriculas_ativas())

    @property
    def esta_lotada(self) -> bool:
        return self.vagas_disponiveis <= 0

    @property
    def taxa_ocupacao(self) -> float:
        """Percentual de ocupacao, usado nos indicadores do dashboard."""
        if not self.capacidade:
            return 0.0
        return round(self.contar_matriculas_ativas() / self.capacidade * 100, 1)

    def __str__(self) -> str:
        return self.nome_completo

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Turma {self.identificacao_curta}>"


class TurmaDisciplina(ModeloBase, TimestampMixin):
    """Vinculo turma x disciplina x professor dentro de um ano letivo.

    E a entidade central do modulo academico: aulas, avaliacoes, notas e
    horarios apontam para este vinculo, e nao diretamente para a turma ou a
    disciplina. Isso permite responder com uma unica consulta a pergunta
    "quem leciona o que, para quem" e sustenta todo o controle de permissao
    do professor.
    """

    __tablename__ = "turmas_disciplinas"
    __table_args__ = (
        UniqueConstraint(
            "turma_id", "disciplina_id", name="disciplina_unica_por_turma"
        ),
        Index("ix_turmas_disciplinas_professor", "professor_id"),
    )

    turma_id: Mapped[int] = mapped_column(
        ForeignKey("turmas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    disciplina_id: Mapped[int] = mapped_column(
        ForeignKey("disciplinas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    professor_id: Mapped[int | None] = mapped_column(
        ForeignKey("professores.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Nulo enquanto a coordenacao nao designou o docente.",
    )
    carga_horaria_semanal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, doc="Aulas por semana."
    )
    ativa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    turma = relationship("Turma", back_populates="turmas_disciplinas", lazy="joined")
    disciplina = relationship(
        "Disciplina", back_populates="turmas_disciplinas", lazy="joined"
    )
    professor = relationship(
        "Professor", back_populates="turmas_disciplinas", lazy="joined"
    )

    aulas = relationship(
        "Aula",
        back_populates="turma_disciplina",
        cascade="all, delete-orphan",
        lazy="select",
    )
    avaliacoes = relationship(
        "Avaliacao",
        back_populates="turma_disciplina",
        cascade="all, delete-orphan",
        lazy="select",
    )
    horarios = relationship(
        "Horario",
        back_populates="turma_disciplina",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def descricao(self) -> str:
        turma = self.turma.identificacao_curta if self.turma else "?"
        disciplina = self.disciplina.nome if self.disciplina else "?"
        return f"{disciplina} - {turma}"

    @property
    def nome_professor(self) -> str:
        return self.professor.nome_exibicao if self.professor else "Sem professor"

    def __str__(self) -> str:
        return self.descricao

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TurmaDisciplina {self.descricao}>"


# ---------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------
from app.extensions import db  # noqa: E402  (import tardio evita ciclo)


@db.event.listens_for(Disciplina, "before_insert")
@db.event.listens_for(Disciplina, "before_update")
def _normalizar_disciplina(mapper, connection, alvo: Disciplina) -> None:  # noqa: ARG001
    alvo.sincronizar_derivados()


@db.event.listens_for(Turma, "before_insert")
@db.event.listens_for(Turma, "before_update")
def _normalizar_turma(mapper, connection, alvo: Turma) -> None:  # noqa: ARG001
    alvo.nome = normalizar_texto(alvo.nome).upper()
