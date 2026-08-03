"""Cadastros de pessoas: alunos, professores, funcionarios e responsaveis.

Todos herdam :class:`PessoaMixin` (dados civis + endereco) e
:class:`VinculoUsuarioMixin` (conta de acesso opcional). Consulte
``app/models/mixins.py`` para a justificativa da modelagem escolhida.
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

from app.extensions import db
from app.models.base import ExclusaoLogicaMixin, ModeloBase, TimestampMixin
from app.models.enums import EstadoCivil, Parentesco
from app.models.mixins import PessoaMixin, VinculoUsuarioMixin
from app.utils.seguranca import normalizar_texto


class Aluno(
    ModeloBase, PessoaMixin, VinculoUsuarioMixin, TimestampMixin, ExclusaoLogicaMixin
):
    """Estudante da escola.

    O aluno existe independentemente de matricula: ele pode estar cadastrado
    e ainda nao matriculado, ou ter concluido os estudos e permanecer no
    sistema para emissao de historico escolar.
    """

    __tablename__ = "alunos"
    __table_args__ = (
        Index("ix_alunos_situacao_nome", "situacao", "nome_normalizado"),
    )

    codigo: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        doc="Codigo interno permanente do aluno (RA). Gerado pelo sistema.",
    )

    #: Campos que exigem ``aluno.ver_dados_sensiveis``.
    #:
    #: Reune duas coisas com pesos diferentes na LGPD, e de proposito:
    #:
    #: * **Saude** — dado sensivel (art. 11), coletado pelo interesse vital
    #:   do aluno. So a equipe que precisa agir em uma emergencia deve ver.
    #: * **Documentos** — nao sao "sensiveis" na letra da lei, mas CPF, RG,
    #:   NIS e cartao SUS de um menor de idade identificam a pessoa e valem
    #:   dinheiro num vazamento. O professor nao precisa deles para dar aula.
    #:
    #: A lista vive no model, e nao no service, porque e propriedade do
    #: dado: qualquer camada que serialize um aluno precisa da mesma
    #: resposta sobre o que pode sair.
    CAMPOS_SENSIVEIS: frozenset[str] = frozenset(
        {
            # Documentos
            "cpf",
            "rg",
            "rg_orgao_emissor",
            "certidao_nascimento",
            "nis",
            "cartao_sus",
            # Saude
            "tipo_sanguineo",
            "alergias",
            "medicamentos_continuos",
            "condicoes_saude",
            "possui_deficiencia",
            "descricao_deficiencia",
            "necessita_acompanhante",
        }
    )

    # -- Documentacao civil complementar -------------------------------------
    naturalidade: Mapped[str | None] = mapped_column(String(80), nullable=True)
    uf_naturalidade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    nacionalidade: Mapped[str] = mapped_column(
        String(60), nullable=False, default="Brasileira"
    )
    certidao_nascimento: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nis: Mapped[str | None] = mapped_column(
        String(11), nullable=True, doc="Numero de Identificacao Social (bolsa familia)."
    )
    cartao_sus: Mapped[str | None] = mapped_column(String(15), nullable=True)

    # -- Informacoes de saude e apoio ----------------------------------------
    # Dados sensiveis (LGPD art. 11): coletados apenas pelo interesse vital do
    # aluno e visiveis somente a equipe interna, nunca a outros responsaveis.
    tipo_sanguineo: Mapped[str | None] = mapped_column(String(3), nullable=True)
    alergias: Mapped[str | None] = mapped_column(Text, nullable=True)
    medicamentos_continuos: Mapped[str | None] = mapped_column(Text, nullable=True)
    condicoes_saude: Mapped[str | None] = mapped_column(Text, nullable=True)
    possui_deficiencia: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    descricao_deficiencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    necessita_acompanhante: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # -- Beneficios e logistica ----------------------------------------------
    bolsista: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    percentual_bolsa: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    usa_transporte_escolar: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    autorizado_sair_sozinho: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Autorizacao expressa do responsavel para saida desacompanhada.",
    )
    autoriza_uso_imagem: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Consentimento LGPD para uso de imagem em midias da escola.",
    )

    data_cadastro: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )

    # -- Relacionamentos -----------------------------------------------------
    usuario = relationship("Usuario", back_populates="aluno")
    vinculos_responsaveis = relationship(
        "AlunoResponsavel",
        back_populates="aluno",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AlunoResponsavel.ordem_contato",
    )
    matriculas = relationship(
        "Matricula",
        back_populates="aluno",
        lazy="select",
        order_by="desc(Matricula.id)",
    )

    # ------------------------------------------------------------------
    @property
    def responsaveis(self) -> list[Responsavel]:
        return [v.responsavel for v in self.vinculos_responsaveis if v.responsavel]

    @property
    def responsavel_principal(self) -> Responsavel | None:
        """Primeiro contato na ordem definida pela secretaria."""
        for vinculo in self.vinculos_responsaveis:
            if vinculo.responsavel:
                return vinculo.responsavel
        return None

    @property
    def responsavel_financeiro(self) -> Responsavel | None:
        for vinculo in self.vinculos_responsaveis:
            if vinculo.responsavel_financeiro:
                return vinculo.responsavel
        return self.responsavel_principal

    @property
    def matricula_atual(self):
        """Matricula ativa no ano letivo corrente, se houver."""
        from app.models.enums import SituacaoMatricula
        from app.models.matricula import Matricula

        return (
            db.session.query(Matricula)
            .join(Matricula.ano_letivo)
            .filter(
                Matricula.aluno_id == self.id,
                Matricula.situacao == SituacaoMatricula.ATIVA,
                Matricula.excluido_em.is_(None),
            )
            .order_by(Matricula.id.desc())
            .first()
        )

    @property
    def turma_atual(self):
        matricula = self.matricula_atual
        return matricula.turma if matricula else None

    @property
    def esta_matriculado(self) -> bool:
        return self.matricula_atual is not None

    @property
    def tem_alerta_saude(self) -> bool:
        """Sinaliza na ficha se ha informacao critica de saude."""
        return bool(
            self.alergias
            or self.medicamentos_continuos
            or self.condicoes_saude
            or self.possui_deficiencia
        )

    @staticmethod
    def gerar_codigo(ano: int | None = None) -> str:
        """Gera o RA no formato ``AAAANNNNN`` (ano + sequencial).

        Usa o maior codigo ja existente para o ano em vez de contar linhas:
        contar quebraria se um aluno fosse excluido, gerando codigo duplicado.
        """
        ano = ano or date.today().year
        prefixo = str(ano)

        ultimo = (
            db.session.query(func.max(Aluno.codigo))
            .filter(Aluno.codigo.like(f"{prefixo}%"))
            .scalar()
        )

        sequencial = 1
        if ultimo and len(ultimo) > len(prefixo):
            try:
                sequencial = int(ultimo[len(prefixo):]) + 1
            except ValueError:
                sequencial = 1

        return f"{prefixo}{sequencial:05d}"

    def __str__(self) -> str:
        return self.nome_exibicao

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Aluno {self.codigo} {self.nome_completo}>"


class Professor(
    ModeloBase, PessoaMixin, VinculoUsuarioMixin, TimestampMixin, ExclusaoLogicaMixin
):
    """Docente da escola."""

    __tablename__ = "professores"

    registro_funcional: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True
    )
    formacao: Mapped[str | None] = mapped_column(
        String(150), nullable=True, doc="Curso de graduacao."
    )
    titulacao: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
        doc="Maior titulacao: Graduacao, Especializacao, Mestrado, Doutorado.",
    )
    instituicao_formacao: Mapped[str | None] = mapped_column(String(150), nullable=True)
    data_admissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_desligamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    carga_horaria_semanal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, doc="Carga horaria contratual (horas)."
    )
    estado_civil: Mapped[EstadoCivil] = mapped_column(
        SAEnum(
            EstadoCivil,
            name="estado_civil",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=EstadoCivil.NAO_INFORMADO,
    )

    usuario = relationship("Usuario", back_populates="professor")
    turmas_disciplinas = relationship(
        "TurmaDisciplina", back_populates="professor", lazy="select"
    )
    turmas_regidas = relationship(
        "Turma",
        back_populates="professor_regente",
        foreign_keys="Turma.professor_regente_id",
        lazy="select",
    )

    # ------------------------------------------------------------------
    @property
    def disciplinas_lecionadas(self) -> list:
        """Disciplinas distintas que o professor leciona no momento."""
        vistas: dict[int, object] = {}
        for vinculo in self.turmas_disciplinas:
            if vinculo.ativa and vinculo.disciplina:
                vistas.setdefault(vinculo.disciplina.id, vinculo.disciplina)
        return list(vistas.values())

    @property
    def carga_horaria_atribuida(self) -> int:
        """Soma das aulas semanais efetivamente atribuidas ao professor."""
        return sum(
            v.carga_horaria_semanal for v in self.turmas_disciplinas if v.ativa
        )

    @property
    def tem_sobrecarga(self) -> bool:
        """Alerta a coordenacao quando a atribuicao excede o contrato."""
        return self.carga_horaria_atribuida > self.carga_horaria_semanal

    def leciona_para_turma(self, turma_id: int) -> bool:
        """Base do controle de acesso: o professor so ve suas proprias turmas."""
        return any(
            v.turma_id == turma_id and v.ativa for v in self.turmas_disciplinas
        )

    @staticmethod
    def gerar_registro_funcional() -> str:
        """Gera matricula funcional sequencial no formato ``PROF00001``."""
        ultimo = (
            db.session.query(func.max(Professor.registro_funcional))
            .filter(Professor.registro_funcional.like("PROF%"))
            .scalar()
        )
        sequencial = 1
        if ultimo:
            try:
                sequencial = int(ultimo.replace("PROF", "")) + 1
            except ValueError:
                sequencial = 1
        return f"PROF{sequencial:05d}"

    def __str__(self) -> str:
        return self.nome_exibicao

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Professor {self.registro_funcional} {self.nome_completo}>"


class Funcionario(
    ModeloBase, PessoaMixin, VinculoUsuarioMixin, TimestampMixin, ExclusaoLogicaMixin
):
    """Colaborador administrativo ou de apoio (secretaria, portaria, limpeza)."""

    __tablename__ = "funcionarios"

    matricula_funcional: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True
    )
    cargo: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    setor: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    data_admissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_desligamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    carga_horaria_semanal: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40
    )
    estado_civil: Mapped[EstadoCivil] = mapped_column(
        SAEnum(
            EstadoCivil,
            name="estado_civil",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=EstadoCivil.NAO_INFORMADO,
    )

    usuario = relationship("Usuario", back_populates="funcionario")

    @property
    def tempo_casa_anos(self) -> int | None:
        if not self.data_admissao:
            return None
        fim = self.data_desligamento or date.today()
        return max(0, (fim - self.data_admissao).days // 365)

    @staticmethod
    def gerar_matricula_funcional() -> str:
        ultimo = (
            db.session.query(func.max(Funcionario.matricula_funcional))
            .filter(Funcionario.matricula_funcional.like("FUNC%"))
            .scalar()
        )
        sequencial = 1
        if ultimo:
            try:
                sequencial = int(ultimo.replace("FUNC", "")) + 1
            except ValueError:
                sequencial = 1
        return f"FUNC{sequencial:05d}"

    def __str__(self) -> str:
        return self.nome_exibicao

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Funcionario {self.matricula_funcional} {self.cargo}>"


class Responsavel(
    ModeloBase, PessoaMixin, VinculoUsuarioMixin, TimestampMixin, ExclusaoLogicaMixin
):
    """Responsavel legal ou financeiro por um ou mais alunos."""

    __tablename__ = "responsaveis"

    profissao: Mapped[str | None] = mapped_column(String(80), nullable=True)
    local_trabalho: Mapped[str | None] = mapped_column(String(150), nullable=True)
    telefone_trabalho: Mapped[str | None] = mapped_column(String(11), nullable=True)
    estado_civil: Mapped[EstadoCivil] = mapped_column(
        SAEnum(
            EstadoCivil,
            name="estado_civil",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=EstadoCivil.NAO_INFORMADO,
    )

    usuario = relationship("Usuario", back_populates="responsavel")
    vinculos_alunos = relationship(
        "AlunoResponsavel",
        back_populates="responsavel",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def alunos(self) -> list[Aluno]:
        return [v.aluno for v in self.vinculos_alunos if v.aluno]

    @property
    def ids_alunos(self) -> set[int]:
        """Conjunto usado pelo controle de acesso do portal do responsavel."""
        return {v.aluno_id for v in self.vinculos_alunos}

    def e_responsavel_por(self, aluno_id: int) -> bool:
        return aluno_id in self.ids_alunos

    def __str__(self) -> str:
        return self.nome_exibicao

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Responsavel {self.id} {self.nome_completo}>"


class AlunoResponsavel(ModeloBase, TimestampMixin):
    """Vinculo N:N entre aluno e responsavel, com qualificacao do papel.

    A tabela carrega atributos proprios (parentesco, quem paga, quem pode
    buscar na escola), o que a torna uma entidade de dominio e nao uma
    simples tabela de juncao.
    """

    __tablename__ = "alunos_responsaveis"
    __table_args__ = (
        UniqueConstraint("aluno_id", "responsavel_id", name="vinculo_unico"),
        CheckConstraint(
            "ordem_contato >= 1 AND ordem_contato <= 10", name="ordem_plausivel"
        ),
    )

    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    responsavel_id: Mapped[int] = mapped_column(
        ForeignKey("responsaveis.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parentesco: Mapped[Parentesco] = mapped_column(
        SAEnum(
            Parentesco,
            name="parentesco",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
        default=Parentesco.OUTRO,
    )
    responsavel_legal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Responde juridicamente pelo aluno.",
    )
    responsavel_financeiro: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    autorizado_buscar: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Autorizado a retirar o aluno da escola.",
    )
    ordem_contato: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Ordem de acionamento em caso de emergencia.",
    )
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)

    aluno = relationship("Aluno", back_populates="vinculos_responsaveis")
    responsavel = relationship(
        "Responsavel", back_populates="vinculos_alunos", lazy="joined"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AlunoResponsavel aluno={self.aluno_id} "
            f"responsavel={self.responsavel_id} ({self.parentesco.value})>"
        )


# ---------------------------------------------------------------------------
# Listeners de normalizacao
# ---------------------------------------------------------------------------
for _modelo in (Aluno, Professor, Funcionario, Responsavel):

    @db.event.listens_for(_modelo, "before_insert")
    @db.event.listens_for(_modelo, "before_update")
    def _normalizar_pessoa(mapper, connection, alvo, **_kw) -> None:  # noqa: ARG001
        alvo.normalizar_pessoa()


@db.event.listens_for(Funcionario, "before_insert")
@db.event.listens_for(Funcionario, "before_update")
def _normalizar_funcionario(mapper, connection, alvo: Funcionario) -> None:  # noqa: ARG001
    alvo.cargo = normalizar_texto(alvo.cargo)
    alvo.setor = normalizar_texto(alvo.setor) or None


@db.event.listens_for(Aluno, "before_insert")
def _garantir_codigo_aluno(mapper, connection, alvo: Aluno) -> None:  # noqa: ARG001
    """Garante RA mesmo quando o aluno e criado fora do service (seed, CLI)."""
    if not alvo.codigo:
        alvo.codigo = Aluno.gerar_codigo()


__all__ = [
    "Aluno",
    "Professor",
    "Funcionario",
    "Responsavel",
    "AlunoResponsavel",
]
