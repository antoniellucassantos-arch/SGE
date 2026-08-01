"""Model de usuario: identidade, credenciais e controle de acesso.

Modelagem de pessoas no SGE
---------------------------
``Usuario`` guarda **identidade e credenciais**. Os dados especificos de cada
papel ficam em tabelas de perfil (``Aluno``, ``Professor``, ``Funcionario``,
``Responsavel``), ligadas a ``Usuario`` por relacao 1:1 opcional.

Essa separacao resolve tres problemas reais de uma escola:

1. **Alunos pequenos nao tem login.** ``Aluno.usuario_id`` e opcional, entao
   a secretaria cadastra a crianca sem inventar um e-mail para ela.
2. **Uma pessoa pode acumular papeis.** Um professor que tambem e pai de
   aluno usa o mesmo login para os dois perfis, sem cadastro duplicado.
3. **Desligamento nao apaga historico.** Desativar o ``Usuario`` corta o
   acesso, mas o perfil e todo o historico academico permanecem intactos.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import ExclusaoLogicaMixin, ModeloBase, TimestampMixin, agora_utc
from app.models.enums import PapelUsuario
from app.utils.seguranca import (
    gerar_hash_senha,
    normalizar_email,
    normalizar_texto,
    precisa_reidratar_hash,
    remover_acentos,
    verificar_senha,
)


class Usuario(ModeloBase, TimestampMixin, ExclusaoLogicaMixin, UserMixin):
    """Conta de acesso ao sistema."""

    __tablename__ = "usuarios"
    __table_args__ = (
        # Listagens administrativas quase sempre filtram por papel + situacao.
        Index("ix_usuarios_papel_ativo", "papel", "ativo"),
        # Suporta a busca textual da tela de usuarios.
        Index("ix_usuarios_nome_normalizado", "nome_normalizado"),
    )

    # -- Identidade ----------------------------------------------------------
    nome_completo: Mapped[str] = mapped_column(
        String(150), nullable=False, doc="Nome civil completo do usuario."
    )
    nome_normalizado: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        default="",
        doc="Nome sem acentos e em minusculas, usado para busca.",
    )
    email: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
        index=True,
        doc="E-mail de login. Sempre armazenado em minusculas.",
    )
    cpf: Mapped[str | None] = mapped_column(
        String(11),
        nullable=True,
        unique=True,
        index=True,
        doc="CPF somente com digitos. Opcional, mas unico quando informado.",
    )
    telefone: Mapped[str | None] = mapped_column(String(11), nullable=True)
    foto: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Nome do arquivo de avatar dentro de uploads/usuarios.",
    )

    # -- Credenciais ---------------------------------------------------------
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    senha_alterada_em: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    deve_trocar_senha: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Forca a troca de senha no proximo acesso (primeiro login/reset).",
    )

    # -- Autorizacao ---------------------------------------------------------
    papel: Mapped[PapelUsuario] = mapped_column(
        SAEnum(
            PapelUsuario,
            name="papel_usuario",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,  # portavel entre SQLite e PostgreSQL
        ),
        nullable=False,
        index=True,
    )
    ativo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    # -- Controle de acesso e seguranca --------------------------------------
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    tentativas_falhas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    bloqueado_ate: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        doc="Bloqueio temporario apos excesso de tentativas de login.",
    )

    # -- Perfis (1:1 opcionais) ----------------------------------------------
    aluno = relationship(
        "Aluno", back_populates="usuario", uselist=False, lazy="selectin"
    )
    professor = relationship(
        "Professor", back_populates="usuario", uselist=False, lazy="selectin"
    )
    funcionario = relationship(
        "Funcionario", back_populates="usuario", uselist=False, lazy="selectin"
    )
    responsavel = relationship(
        "Responsavel", back_populates="usuario", uselist=False, lazy="selectin"
    )

    # ------------------------------------------------------------------
    # Normalizacao de dados
    # ------------------------------------------------------------------
    def sincronizar_derivados(self) -> None:
        """Recalcula campos derivados antes de gravar.

        Chamado pelo listener de ``before_insert``/``before_update``, o que
        garante consistencia mesmo quando o registro e alterado por um
        service, por um comando CLI ou pelo seed.
        """
        self.nome_completo = normalizar_texto(self.nome_completo)
        self.nome_normalizado = remover_acentos(self.nome_completo)
        self.email = normalizar_email(self.email)

    # ------------------------------------------------------------------
    # Senha
    # ------------------------------------------------------------------
    def definir_senha(self, senha: str, exigir_troca: bool = False) -> None:
        """Grava o hash da nova senha e zera o estado de bloqueio."""
        self.senha_hash = gerar_hash_senha(senha)
        self.senha_alterada_em = agora_utc()
        self.deve_trocar_senha = exigir_troca
        self.tentativas_falhas = 0
        self.bloqueado_ate = None

    def conferir_senha(self, senha: str) -> bool:
        """Verifica a senha e migra o hash quando o algoritmo esta defasado.

        A reidratacao acontece de forma transparente: o usuario nunca percebe
        que a senha dele passou de PBKDF2 para Argon2id.
        """
        if not verificar_senha(self.senha_hash, senha):
            return False

        if precisa_reidratar_hash(self.senha_hash):
            self.senha_hash = gerar_hash_senha(senha)

        return True

    # ------------------------------------------------------------------
    # Bloqueio por tentativas
    # ------------------------------------------------------------------
    @property
    def esta_bloqueado(self) -> bool:
        """Indica bloqueio temporario ativo por excesso de tentativas."""
        return self.bloqueado_ate is not None and self.bloqueado_ate > agora_utc()

    @property
    def minutos_restantes_bloqueio(self) -> int:
        """Minutos que faltam para o desbloqueio automatico."""
        if not self.esta_bloqueado:
            return 0
        restante = self.bloqueado_ate - agora_utc()
        return max(1, int(restante.total_seconds() // 60) + 1)

    def registrar_falha_login(
        self, max_tentativas: int = 5, minutos_bloqueio: int = 15
    ) -> bool:
        """Contabiliza uma tentativa malsucedida.

        Retorna ``True`` se a conta acabou de ser bloqueada, permitindo que a
        rota registre o evento na auditoria com a gravidade correta.
        """
        self.tentativas_falhas = (self.tentativas_falhas or 0) + 1

        if self.tentativas_falhas >= max_tentativas:
            self.bloqueado_ate = agora_utc() + timedelta(minutes=minutos_bloqueio)
            self.tentativas_falhas = 0
            return True

        return False

    def registrar_login(self, endereco_ip: str | None = None) -> None:
        """Marca um login bem-sucedido e limpa contadores de seguranca."""
        self.ultimo_login_em = agora_utc()
        self.ultimo_login_ip = (endereco_ip or "")[:45] or None
        self.tentativas_falhas = 0
        self.bloqueado_ate = None

    def desbloquear(self) -> None:
        """Desbloqueio manual feito por um administrador."""
        self.tentativas_falhas = 0
        self.bloqueado_ate = None

    # ------------------------------------------------------------------
    # Flask-Login
    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        """Contas inativas, excluidas ou bloqueadas nao autenticam."""
        return bool(self.ativo) and not self.esta_excluido and not self.esta_bloqueado

    def get_id(self) -> str:
        return str(self.id)

    # ------------------------------------------------------------------
    # Papeis e conveniencias de apresentacao
    # ------------------------------------------------------------------
    def tem_papel(self, *papeis: PapelUsuario | str) -> bool:
        """Verifica se o usuario possui algum dos papeis informados."""
        alvos = {p.value if isinstance(p, PapelUsuario) else str(p) for p in papeis}
        return self.papel.value in alvos

    @property
    def e_administrador(self) -> bool:
        return self.papel is PapelUsuario.ADMINISTRADOR

    @property
    def e_direcao(self) -> bool:
        return self.papel is PapelUsuario.DIRECAO

    @property
    def e_secretaria(self) -> bool:
        return self.papel is PapelUsuario.SECRETARIA

    @property
    def e_professor(self) -> bool:
        return self.papel is PapelUsuario.PROFESSOR

    @property
    def e_aluno(self) -> bool:
        return self.papel is PapelUsuario.ALUNO

    @property
    def e_responsavel(self) -> bool:
        return self.papel is PapelUsuario.RESPONSAVEL

    @property
    def e_equipe_interna(self) -> bool:
        """Perfis que enxergam a area administrativa do sistema."""
        return self.papel.e_equipe_interna

    @property
    def primeiro_nome(self) -> str:
        return (self.nome_completo or "").split(" ")[0]

    @property
    def iniciais(self) -> str:
        """Iniciais para o avatar textual quando nao ha foto."""
        partes = [p for p in (self.nome_completo or "").split(" ") if p]
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[-1][0]).upper()

    @property
    def perfil_vinculado(self):
        """Retorna o perfil correspondente ao papel do usuario, se existir."""
        mapa = {
            PapelUsuario.ALUNO: self.aluno,
            PapelUsuario.PROFESSOR: self.professor,
            PapelUsuario.RESPONSAVEL: self.responsavel,
        }
        return mapa.get(self.papel) or self.funcionario

    def __repr__(self) -> str:  # pragma: no cover - auxilio a depuracao
        return f"<Usuario {self.id} {self.email} ({self.papel.value})>"


# ---------------------------------------------------------------------------
# Listeners: mantem os campos derivados sempre coerentes
# ---------------------------------------------------------------------------
@db.event.listens_for(Usuario, "before_insert")
@db.event.listens_for(Usuario, "before_update")
def _normalizar_usuario(mapper, connection, alvo: Usuario) -> None:  # noqa: ARG001
    alvo.sincronizar_derivados()
