"""Application Factory do SGE.

Toda a aplicacao e construida por :func:`create_app`, que recebe o nome do
ambiente e devolve uma instancia Flask pronta. Nenhum objeto ``Flask`` e
criado no momento do import, o que permite:

* subir a aplicacao com configuracoes diferentes (dev, teste, producao);
* criar uma instancia isolada por teste, sem vazamento de estado;
* evitar imports circulares entre models, services e blueprints.

Ordem de inicializacao (importa: cada etapa depende da anterior)::

    configuracao -> logging -> extensoes -> models -> blueprints
    -> handlers de erro -> hooks de requisicao -> jinja -> CLI
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import csrf, db, limiter, login_manager, migrate
from config import BaseConfig, obter_configuracao

__version__ = "1.0.0"

#: Blueprints registrados na aplicacao: (modulo, atributo, prefixo de URL).
#: Manter a lista declarativa torna trivial saber o que existe no sistema e
#: em qual URL, sem cacar ``register_blueprint`` espalhados pelo codigo.
BLUEPRINTS: tuple[tuple[str, str, str | None], ...] = (
    ("app.blueprints.auth", "bp", "/auth"),
    ("app.blueprints.painel", "bp", "/"),
    ("app.blueprints.alunos", "bp", "/alunos"),
    ("app.blueprints.professores", "bp", "/professores"),
    ("app.blueprints.funcionarios", "bp", "/funcionarios"),
    ("app.blueprints.responsaveis", "bp", "/responsaveis"),
    ("app.blueprints.turmas", "bp", "/turmas"),
    ("app.blueprints.disciplinas", "bp", "/disciplinas"),
    ("app.blueprints.matriculas", "bp", "/matriculas"),
    ("app.blueprints.frequencia", "bp", "/frequencia"),
    ("app.blueprints.notas", "bp", "/notas"),
    ("app.blueprints.boletim", "bp", "/boletim"),
    ("app.blueprints.horarios", "bp", "/horarios"),
    ("app.blueprints.avisos", "bp", "/avisos"),
    ("app.blueprints.relatorios", "bp", "/relatorios"),
    ("app.blueprints.usuarios", "bp", "/usuarios"),
    ("app.blueprints.configuracoes", "bp", "/configuracoes"),
    ("app.blueprints.backup", "bp", "/backup"),
    ("app.blueprints.auditoria", "bp", "/auditoria"),
    ("app.blueprints.api", "bp", "/api/v1"),
)

#: Blueprints ja implementados. A factory registra apenas estes, o que
#: mantem a aplicacao inicializavel durante o desenvolvimento incremental.
#: Ao concluir um modulo, basta acrescentar o nome aqui.
BLUEPRINTS_ATIVOS: set[str] = {caminho for caminho, _, _ in BLUEPRINTS}


def create_app(nome_configuracao: str | None = None) -> Flask:
    """Cria e configura uma instancia da aplicacao SGE."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="static",
        template_folder="templates",
    )

    # 1. Configuracao ------------------------------------------------------
    classe_config = obter_configuracao(nome_configuracao)
    app.config.from_object(classe_config)
    # Permite sobrescrever qualquer chave via instance/config.py sem tocar
    # no repositorio (util para credenciais especificas do servidor).
    app.config.from_pyfile("config.py", silent=True)
    classe_config.iniciar_app(app)

    _garantir_diretorio_instance(app)

    # 2. Logging -----------------------------------------------------------
    _configurar_logging(app)

    # 3. Proxy reverso -----------------------------------------------------
    # Em producao o Flask fica atras do Nginx; sem isso, todo request pareceria
    # vir de 127.0.0.1 e a auditoria de IP e o rate limiting seriam inuteis.
    if not app.debug and not app.testing:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

    # 4. Extensoes ---------------------------------------------------------
    _registrar_extensoes(app)

    # 5. Models ------------------------------------------------------------
    # O import popula o metadata do SQLAlchemy; sem ele o Alembic nao enxerga
    # as tabelas e o create_all() dos testes nao cria nada.
    with app.app_context():
        from app import models  # noqa: F401

    # 6. Blueprints --------------------------------------------------------
    _registrar_blueprints(app)

    # 7. Tratamento de erros ----------------------------------------------
    _registrar_handlers_erro(app)

    # 8. Hooks de requisicao ----------------------------------------------
    _registrar_hooks(app)

    # 9. Jinja: filtros, globais e contexto -------------------------------
    _configurar_jinja(app)

    # 10. Comandos de linha de comando ------------------------------------
    _registrar_comandos(app)

    app.logger.info(
        "SGE %s iniciado no ambiente '%s'",
        __version__,
        app.config.get("AMBIENTE", "desconhecido"),
    )
    return app


# ---------------------------------------------------------------------------
# Etapas da construcao
# ---------------------------------------------------------------------------
def _garantir_diretorio_instance(app: Flask) -> None:
    """Cria ``instance/`` antes do SQLite tentar gravar o arquivo la."""
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError as erro:  # pragma: no cover - permissao do sistema
        app.logger.warning("Nao foi possivel criar instance/: %s", erro)


def _configurar_logging(app: Flask) -> None:
    """Configura log em arquivo rotativo + console.

    Em producao, um erro sem rastro e um erro que ninguem conserta: o arquivo
    rotativo garante historico sem encher o disco.
    """
    if app.testing:
        return

    nivel = getattr(logging, app.config.get("LOG_NIVEL", "INFO").upper(), logging.INFO)

    # O Flask instala um handler proprio em app.logger no primeiro acesso.
    # Sem remove-lo, cada mensagem apareceria duas vezes no console.
    app.logger.handlers.clear()
    app.logger.propagate = False
    formato = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s "
        "[em %(pathname)s:%(lineno)d]",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    pasta_logs = app.config["PASTA_LOGS"]
    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            pasta_logs / app.config["LOG_ARQUIVO"],
            maxBytes=app.config["LOG_MAX_BYTES"],
            backupCount=app.config["LOG_BACKUP_COUNT"],
            encoding="utf-8",
        )
        arquivo.setFormatter(formato)
        arquivo.setLevel(nivel)
        app.logger.addHandler(arquivo)
    except OSError as erro:  # pragma: no cover - disco cheio/permissao
        app.logger.warning("Log em arquivo indisponivel: %s", erro)

    if app.debug:
        console = logging.StreamHandler()
        console.setFormatter(formato)
        console.setLevel(nivel)
        app.logger.addHandler(console)

    app.logger.setLevel(nivel)


def _registrar_extensoes(app: Flask) -> None:
    """Vincula as extensoes a esta instancia da aplicacao."""
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations", render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    # O rate limiting so e util com armazenamento compartilhado entre
    # processos; em desenvolvimento e teste ele apenas atrapalha.
    if app.config.get("RATELIMIT_ENABLED", True):
        limiter.init_app(app)

    # Cookie de sessao seguro tambem para o token CSRF.
    app.config.setdefault(
        "REMEMBER_COOKIE_SECURE", app.config.get("SESSION_COOKIE_SECURE", False)
    )


def _registrar_blueprints(app: Flask) -> None:
    """Importa e registra todos os blueprints declarados em ``BLUEPRINTS``."""
    from importlib import import_module

    for caminho_modulo, atributo, prefixo in BLUEPRINTS:
        if caminho_modulo not in BLUEPRINTS_ATIVOS:
            continue
        modulo = import_module(caminho_modulo)
        blueprint = getattr(modulo, atributo)
        app.register_blueprint(blueprint, url_prefix=prefixo)
        app.logger.debug("Blueprint registrado: %s -> %s", blueprint.name, prefixo)


def _registrar_handlers_erro(app: Flask) -> None:
    """Paginas de erro amigaveis; nunca expor rastro de pilha ao usuario."""
    from app.services.excecoes import ErroDominio

    def _quer_json() -> bool:
        return (
            request.path.startswith("/api/")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.accept_mimetypes.best == "application/json"
        )

    @app.errorhandler(400)
    def erro_400(erro):
        if _quer_json():
            return {"erro": "Requisicao invalida"}, 400
        return render_template("erros/400.html"), 400

    @app.errorhandler(403)
    def erro_403(erro):
        if _quer_json():
            return {"erro": "Acesso negado"}, 403
        return render_template("erros/403.html"), 403

    @app.errorhandler(404)
    def erro_404(erro):
        if _quer_json():
            return {"erro": "Recurso nao encontrado"}, 404
        return render_template("erros/404.html"), 404

    @app.errorhandler(413)
    def erro_413(erro):
        limite = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        if _quer_json():
            return {"erro": f"Arquivo maior que {limite} MB"}, 413
        return render_template("erros/413.html", limite_mb=limite), 413

    @app.errorhandler(429)
    def erro_429(erro):
        if _quer_json():
            return {"erro": "Muitas requisicoes. Aguarde um instante."}, 429
        return render_template("erros/429.html"), 429

    @app.errorhandler(500)
    def erro_500(erro):
        # Rollback obrigatorio: sem ele a sessao fica "suja" e todas as
        # requisicoes seguintes desta conexao falhariam em cascata.
        db.session.rollback()
        app.logger.exception("Erro interno nao tratado")
        if _quer_json():
            return {"erro": "Erro interno do servidor"}, 500
        return render_template("erros/500.html"), 500

    @app.errorhandler(ErroDominio)
    def erro_dominio(erro: ErroDominio):
        """Converte excecoes de negocio em resposta adequada ao cliente."""
        app.logger.info("Erro de dominio: %s", erro.mensagem)

        if _quer_json():
            return {"erro": erro.mensagem}, erro.codigo_http

        # Falhas de autorizacao e recursos inexistentes devolvem o codigo HTTP
        # correto, e nao um redirect com mensagem. Motivos:
        #   1. Um 302 sinalizaria "sua requisicao foi aceita", quando na
        #      verdade foi negada — enganoso para o usuario e para o cliente.
        #   2. Monitoramento e testes precisam distinguir acesso negado de
        #      navegacao normal.
        #
        # A pagina e renderizada aqui, e nao com ``abort()``: uma excecao
        # levantada dentro de um error handler nao e redespachada pelo Flask
        # para outro handler — ela sobe como erro nao tratado.
        from flask import flash, redirect, url_for

        if erro.codigo_http in (403, 404):
            return (
                render_template(f"erros/{erro.codigo_http}.html"),
                erro.codigo_http,
            )

        # Erros de regra de negocio (capacidade da turma, matricula
        # duplicada) sao previsiveis e corrigiveis: a pessoa volta para onde
        # estava, com a explicacao do que impediu a operacao.
        flash(erro.mensagem, "danger")
        destino = request.referrer or url_for("painel.index")
        return redirect(destino)


def _registrar_hooks(app: Flask) -> None:
    """Hooks executados a cada requisicao."""
    from flask import flash, g, redirect, session, url_for
    from flask_login import current_user

    #: Rotas acessiveis mesmo com troca de senha pendente.
    ROTAS_LIVRES = {
        "auth.login",
        "auth.logout",
        "auth.alterar_senha",
        "auth.recuperar_senha",
        "auth.redefinir_senha",
        "static",
    }

    @app.before_request
    def preparar_requisicao():
        # Sessao permanente com expiracao deslizante por inatividade.
        session.permanent = True

        if not current_user.is_authenticated:
            return None

        # Troca de senha obrigatoria (primeiro acesso ou reset administrativo).
        if current_user.deve_trocar_senha and request.endpoint not in ROTAS_LIVRES:
            if not request.path.startswith("/static"):
                flash(
                    "Por seguranca, defina uma nova senha antes de continuar.",
                    "warning",
                )
                return redirect(url_for("auth.alterar_senha"))

        # Ano letivo corrente disponivel em toda a requisicao (evita repetir
        # a mesma consulta em dezenas de rotas e templates).
        g.ano_letivo = _carregar_ano_letivo_corrente()
        return None

    @app.after_request
    def aplicar_cabecalhos_seguranca(resposta):
        """Cabecalhos de defesa aplicados a todas as respostas.

        Implementados manualmente em vez de via Flask-Talisman para manter a
        lista explicita e auditavel, e uma dependencia a menos.
        """
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resposta.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )

        # CSP: todo CSS/JS e servido localmente, entao nao ha necessidade de
        # liberar CDNs. 'unsafe-inline' em style e concessao pontual ao
        # Bootstrap e aos estilos inline dos graficos.
        resposta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )

        if app.config.get("SESSION_COOKIE_SECURE"):
            resposta.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return resposta

    @app.teardown_appcontext
    def encerrar_sessao(excecao=None):
        """Devolve a conexao ao pool ao final de cada contexto."""
        if excecao:
            db.session.rollback()
        db.session.remove()


def _carregar_ano_letivo_corrente():
    """Busca o ano letivo marcado como corrente.

    Tolerante a falhas de proposito: antes da primeira migration a tabela
    ainda nao existe, e a aplicacao precisa subir mesmo assim.
    """
    try:
        from app.models.estrutura import AnoLetivo

        return (
            db.session.query(AnoLetivo)
            .filter(AnoLetivo.corrente.is_(True))
            .first()
        )
    except Exception:  # noqa: BLE001 - banco ainda nao migrado
        return None


def _configurar_jinja(app: Flask) -> None:
    """Registra filtros, funcoes globais e variaveis de contexto do Jinja2."""
    from app.utils import formatadores

    # -- Filtros -----------------------------------------------------------
    app.jinja_env.filters.update(
        {
            "data": formatadores.formatar_data,
            "data_hora": formatadores.formatar_data_hora,
            "hora": formatadores.formatar_hora,
            "data_extenso": formatadores.formatar_data_extenso,
            "moeda": formatadores.formatar_moeda,
            "nota": formatadores.formatar_nota,
            "percentual": formatadores.formatar_percentual,
            "cpf": formatadores.formatar_cpf_seguro,
            "telefone": formatadores.formatar_telefone_seguro,
            "cep": formatadores.formatar_cep_seguro,
            "tempo_relativo": formatadores.tempo_relativo,
            "truncar": formatadores.truncar,
            "primeiro_nome": formatadores.primeiro_nome,
            "sim_nao": formatadores.sim_nao,
            "quebra_linha": formatadores.quebra_linha,
        }
    )

    # -- Funcoes globais ---------------------------------------------------
    from app.utils.permissoes import Permissao, usuario_tem_permissao

    def tem_permissao(permissao: str) -> bool:
        """Usado nos templates para esconder acoes indisponiveis.

        Esconder o botao e apenas usabilidade; a rota continua protegida
        pelo decorador. Nunca confiar somente nisto.
        """
        from flask_login import current_user as usuario

        return usuario_tem_permissao(usuario, permissao)

    app.jinja_env.globals.update(
        {
            "tem_permissao": tem_permissao,
            "Permissao": Permissao,
            "APP_NOME": app.config["APP_NOME"],
            "APP_VERSAO": __version__,
        }
    )

    # -- Contexto disponivel em todos os templates -------------------------
    @app.context_processor
    def injetar_contexto():
        from datetime import date

        from flask import g

        from app.models.sistema import ConfiguracaoEscola

        try:
            escola = ConfiguracaoEscola.obter()
        except Exception:  # noqa: BLE001 - banco ainda nao migrado
            escola = None

        return {
            "escola": escola,
            "ano_letivo_atual": getattr(g, "ano_letivo", None),
            "hoje": date.today(),
        }


def _registrar_comandos(app: Flask) -> None:
    """Registra os comandos ``flask ...`` do projeto."""
    from app.cli import registrar_comandos

    registrar_comandos(app)


__all__ = ["create_app", "__version__", "BaseConfig"]
