"""Configuracoes do SGE separadas por ambiente.

A aplicacao utiliza o padrao *Application Factory*: nenhuma configuracao e
lida no momento do import de modulos de dominio. Toda a configuracao e
resolvida aqui e injetada em ``create_app()``.

Ambientes disponiveis:

``development``
    SQLite local, debug ligado, cookies sem exigencia de HTTPS.
``testing``
    SQLite em memoria, CSRF desligado, rate limiting desligado.
``production``
    PostgreSQL, cookies seguros, debug desligado, exige ``SECRET_KEY`` real.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Caminhos base do projeto
# ---------------------------------------------------------------------------
# config/settings.py -> config/ -> raiz do projeto
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Carrega variaveis do arquivo .env (se existir) antes de qualquer leitura.
load_dotenv(BASE_DIR / ".env")


def _env_bool(chave: str, padrao: bool = False) -> bool:
    """Le uma variavel de ambiente booleana de forma tolerante.

    Aceita ``1/true/yes/on`` (em qualquer caixa) como verdadeiro.
    """
    valor = os.environ.get(chave)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_int(chave: str, padrao: int) -> int:
    """Le uma variavel de ambiente inteira, caindo no padrao se invalida."""
    valor = os.environ.get(chave)
    if valor is None or not valor.strip():
        return padrao
    try:
        return int(valor)
    except ValueError:
        return padrao


class BaseConfig:
    """Configuracao comum a todos os ambientes."""

    # -- Identidade da aplicacao -------------------------------------------
    APP_NOME = "SGE"
    APP_NOME_COMPLETO = "Sistema de Gestao Escolar"
    APP_VERSAO = "1.0.0"

    # -- Diretorios ---------------------------------------------------------
    BASE_DIR = BASE_DIR

    # Uploads ficam FORA de ``app/static/``. Tudo em ``static/`` e servido
    # diretamente pelo servidor web, sem passar por ``@login_required`` nem
    # por checagem de escopo — a foto de um aluno ficaria acessivel por URL
    # direta, sem login. Sao imagens de menores de idade.
    #
    # Aqui os arquivos so saem por rota autenticada
    # (ver ``app/utils/arquivos.py::responder_arquivo``).
    PASTA_UPLOADS = BASE_DIR / "uploads"
    PASTA_BACKUPS = BASE_DIR / "database" / "backups"
    PASTA_LOGS = BASE_DIR / "logs"

    #: Subpastas criadas na inicializacao, uma por tipo de anexo.
    SUBPASTAS_UPLOAD = (
        "alunos", "professores", "funcionarios",
        "responsaveis", "usuarios", "escola",
    )

    # -- Seguranca ----------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "sge-chave-insegura-apenas-para-dev")

    # Sessao: cookie assinado, inacessivel via JavaScript e restrito a
    # navegacoes same-site (mitiga CSRF e roubo de sessao via XSS).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "sge_sessao"
    SESSION_COOKIE_SECURE = False  # sobrescrito em producao

    # Sessao permanente com expiracao por inatividade.
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=_env_int("SESSAO_MINUTOS", 120)
    )
    SESSION_REFRESH_EACH_REQUEST = True

    # Protecao CSRF (Flask-WTF) valida por 2 horas, alinhada a sessao.
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 7200

    # Politica de senha (aplicada pelos validadores de formulario).
    SENHA_TAMANHO_MINIMO = _env_int("SENHA_TAMANHO_MINIMO", 8)
    SENHA_EXIGE_MAIUSCULA = _env_bool("SENHA_EXIGE_MAIUSCULA", True)
    SENHA_EXIGE_MINUSCULA = _env_bool("SENHA_EXIGE_MINUSCULA", True)
    SENHA_EXIGE_NUMERO = _env_bool("SENHA_EXIGE_NUMERO", True)
    SENHA_EXIGE_SIMBOLO = _env_bool("SENHA_EXIGE_SIMBOLO", False)

    # Bloqueio de conta por tentativas de login malsucedidas.
    LOGIN_MAX_TENTATIVAS = _env_int("LOGIN_MAX_TENTATIVAS", 5)
    LOGIN_BLOQUEIO_MINUTOS = _env_int("LOGIN_BLOQUEIO_MINUTOS", 15)

    # Validade do token de recuperacao de senha (em segundos).
    TOKEN_RECUPERACAO_VALIDADE = _env_int("TOKEN_RECUPERACAO_VALIDADE", 1800)

    # -- Banco de dados -----------------------------------------------------
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        # Reconecta conexoes ociosas antes de usa-las: evita o classico
        # "server closed the connection unexpectedly" em PostgreSQL.
        "pool_pre_ping": True,
    }

    # -- Uploads ------------------------------------------------------------
    # Limite global de payload: 8 MB (fotos de alunos, logo da escola, etc.).
    MAX_CONTENT_LENGTH = _env_int("MAX_UPLOAD_MB", 8) * 1024 * 1024
    EXTENSOES_IMAGEM_PERMITIDAS = {"png", "jpg", "jpeg", "webp"}
    FOTO_LARGURA_MAXIMA = 800  # px; imagens maiores sao redimensionadas

    # -- Paginacao ----------------------------------------------------------
    ITENS_POR_PAGINA = _env_int("ITENS_POR_PAGINA", 20)
    ITENS_POR_PAGINA_MAXIMO = 100

    # -- Rate limiting ------------------------------------------------------
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_LOGIN = os.environ.get("RATELIMIT_LOGIN", "10 per minute")
    RATELIMIT_RECUPERACAO = os.environ.get("RATELIMIT_RECUPERACAO", "5 per hour")

    # -- Backup -------------------------------------------------------------
    BACKUP_RETENCAO_DIAS = _env_int("BACKUP_RETENCAO_DIAS", 30)
    BACKUP_MAXIMO_ARQUIVOS = _env_int("BACKUP_MAXIMO_ARQUIVOS", 60)

    # -- Regras academicas padrao (podem ser sobrescritas em Configuracoes) --
    MEDIA_APROVACAO_PADRAO = 6.0
    MEDIA_RECUPERACAO_PADRAO = 4.0
    FREQUENCIA_MINIMA_PADRAO = 75.0

    # -- Logging ------------------------------------------------------------
    LOG_NIVEL = os.environ.get("LOG_NIVEL", "INFO")
    LOG_ARQUIVO = "sge.log"
    LOG_MAX_BYTES = 5 * 1024 * 1024
    LOG_BACKUP_COUNT = 10

    @classmethod
    def iniciar_app(cls, app) -> None:
        """Gancho para ajustes especificos de ambiente na Application Factory."""
        # Garante que os diretorios de trabalho existam antes do primeiro uso.
        for pasta in (cls.PASTA_UPLOADS, cls.PASTA_BACKUPS, cls.PASTA_LOGS):
            pasta.mkdir(parents=True, exist_ok=True)

        for subpasta in cls.SUBPASTAS_UPLOAD:
            (cls.PASTA_UPLOADS / subpasta).mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(BaseConfig):
    """Ambiente local do desenvolvedor: SQLite + debug."""

    DEBUG = True
    TESTING = False
    AMBIENTE = "development"

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'instance' / 'sge.db').as_posix()}",
    )

    # Recarrega templates sem reiniciar o servidor.
    TEMPLATES_AUTO_RELOAD = True
    SQLALCHEMY_ECHO = _env_bool("SQLALCHEMY_ECHO", False)

    LOG_NIVEL = os.environ.get("LOG_NIVEL", "DEBUG")


class TestingConfig(BaseConfig):
    """Ambiente de testes automatizados: banco em memoria, sem CSRF."""

    DEBUG = False
    TESTING = True
    AMBIENTE = "testing"

    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # Formularios sao submetidos diretamente pelos testes.
    WTF_CSRF_ENABLED = False
    # Rate limiting geraria falsos negativos ao repetir requisicoes.
    RATELIMIT_ENABLED = False

    # Argon2 e proposital e caro; nos testes isso torna a suite lenta.
    HASH_RAPIDO_EM_TESTES = True

    SERVER_NAME = "localhost.localdomain"


class ProductionConfig(BaseConfig):
    """Ambiente de producao: PostgreSQL, cookies seguros, sem debug."""

    DEBUG = False
    TESTING = False
    AMBIENTE = "production"

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")

    # Exige HTTPS para o envio dos cookies de sessao e CSRF.
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_SSL_STRICT = True

    PREFERRED_URL_SCHEME = "https"

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": _env_int("DB_POOL_SIZE", 10),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 20),
        "pool_recycle": 1800,
    }

    @classmethod
    def iniciar_app(cls, app) -> None:
        super().iniciar_app(app)

        # Falha rapido: subir em producao com a chave de desenvolvimento ou
        # sem banco configurado e um erro grave de operacao, nao um aviso.
        if app.config["SECRET_KEY"] == "sge-chave-insegura-apenas-para-dev":
            raise RuntimeError(
                "SECRET_KEY nao configurada. Defina a variavel de ambiente "
                "SECRET_KEY antes de iniciar o SGE em producao."
            )
        if not app.config.get("SQLALCHEMY_DATABASE_URI"):
            raise RuntimeError(
                "DATABASE_URL nao configurada. Informe a URI do PostgreSQL "
                "antes de iniciar o SGE em producao."
            )


CONFIGURACOES: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def obter_configuracao(nome: str | None = None) -> type[BaseConfig]:
    """Resolve a classe de configuracao a partir do nome ou do ambiente.

    A ordem de precedencia e: argumento explicito -> variavel ``APP_ENV``
    -> variavel ``FLASK_ENV`` -> ``default`` (desenvolvimento).
    """
    nome = (
        nome
        or os.environ.get("APP_ENV")
        or os.environ.get("FLASK_ENV")
        or "default"
    ).strip().lower()

    return CONFIGURACOES.get(nome, CONFIGURACOES["default"])
