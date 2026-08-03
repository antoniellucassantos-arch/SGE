"""Servico de backup e restauracao do banco de dados.

Estrategia por banco
--------------------
**SQLite (desenvolvimento e escolas pequenas)** — usa a API oficial
``sqlite3.Connection.backup()``, que copia o banco de forma consistente
mesmo com a aplicacao em uso. Copiar o arquivo com ``shutil.copy`` seria
mais simples, porem pode capturar um estado corrompido se houver escrita em
andamento.

**PostgreSQL (producao)** — invoca ``pg_dump``. O comando e montado como
lista de argumentos (nunca string com ``shell=True``), e a senha vai por
variavel de ambiente ``PGPASSWORD``, jamais na linha de comando, onde
ficaria visivel para qualquer usuario do servidor.

Retencao
--------
Backups antigos sao removidos automaticamente segundo dois criterios
combinados (idade e quantidade), evitando que o disco encha silenciosamente.
"""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app

from app.extensions import db
from app.models.base import agora_utc
from app.models.enums import AcaoAuditoria
from app.models.sistema import RegistroBackup
from app.services import auditoria_service
from app.services.excecoes import ErroDominio, ErroRegraNegocio


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def _pasta_backups() -> Path:
    pasta = Path(current_app.config["PASTA_BACKUPS"])
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _uri_banco() -> str:
    return current_app.config.get("SQLALCHEMY_DATABASE_URI", "")


def _e_sqlite() -> bool:
    return _uri_banco().startswith("sqlite")


def _caminho_sqlite() -> Path:
    """Extrai o caminho do arquivo a partir da URI do SQLAlchemy."""
    uri = _uri_banco()
    caminho = uri.replace("sqlite:///", "").replace("sqlite://", "")
    if not caminho or caminho == ":memory:":
        raise ErroRegraNegocio(
            "Nao e possivel fazer backup de um banco em memoria."
        )
    return Path(caminho)


def _nome_arquivo(automatico: bool) -> str:
    carimbo = agora_utc().strftime("%Y%m%d_%H%M%S")
    origem = "auto" if automatico else "manual"
    extensao = "sqlite3.gz" if _e_sqlite() else "sql.gz"
    return f"sge_{carimbo}_{origem}.{extensao}"


# ---------------------------------------------------------------------------
# Geracao
# ---------------------------------------------------------------------------
def gerar_backup(
    automatico: bool = False, usuario_id: int | None = None
) -> RegistroBackup:
    """Gera um backup completo do banco.

    Sempre retorna um :class:`RegistroBackup` — inclusive em caso de falha,
    com ``sucesso=False`` e a mensagem de erro. Assim a escola enxerga a
    tentativa malsucedida no historico, em vez de simplesmente nao ver
    backup nenhum.
    """
    nome = _nome_arquivo(automatico)
    destino = _pasta_backups() / nome

    registro = RegistroBackup(
        nome_arquivo=nome,
        caminho=str(destino),
        automatico=automatico,
        gerado_por_id=usuario_id,
        criado_em=agora_utc(),
        sucesso=False,
        tamanho_bytes=0,
    )

    try:
        if _e_sqlite():
            _backup_sqlite(destino)
        else:
            _backup_postgresql(destino)

        registro.tamanho_bytes = destino.stat().st_size
        registro.sucesso = True

    except ErroDominio as erro:
        registro.mensagem_erro = erro.mensagem
        current_app.logger.error("Backup falhou: %s", erro.mensagem)
    except Exception as erro:  # noqa: BLE001
        registro.mensagem_erro = str(erro)[:500]
        current_app.logger.exception("Backup falhou")
    finally:
        # Arquivo parcial de um backup que falhou nao pode ficar no disco:
        # alguem poderia tentar restaura-lo.
        if not registro.sucesso and destino.exists():
            destino.unlink(missing_ok=True)

        db.session.add(registro)
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

    if registro.sucesso:
        auditoria_service.registrar(
            AcaoAuditoria.BACKUP,
            entidade="RegistroBackup",
            entidade_id=registro.id,
            descricao=f"Backup gerado: {nome} ({registro.tamanho_legivel})",
            usuario_id=usuario_id,
        )
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

        aplicar_retencao()

    return registro


def _backup_sqlite(destino: Path) -> None:
    """Copia o banco SQLite de forma consistente e comprime o resultado."""
    origem = _caminho_sqlite()
    if not origem.exists():
        raise ErroRegraNegocio(f"Arquivo do banco nao encontrado: {origem}")

    temporario = destino.with_suffix(".tmp")

    try:
        # A API de backup do sqlite3 garante consistencia transacional,
        # diferente de uma copia bruta do arquivo.
        #
        # `closing()` e obrigatorio: `with sqlite3.connect(...)` gerencia
        # apenas a transacao, nao fecha a conexao. Sem fechar, o arquivo
        # temporario continua aberto e o Windows recusa remove-lo
        # (WinError 32), fazendo todo backup falhar.
        with closing(sqlite3.connect(str(origem))) as conexao_origem:
            with closing(sqlite3.connect(str(temporario))) as conexao_destino:
                conexao_origem.backup(conexao_destino)

        with open(temporario, "rb") as entrada:
            with gzip.open(destino, "wb", compresslevel=6) as saida:
                shutil.copyfileobj(entrada, saida)
    finally:
        temporario.unlink(missing_ok=True)


def _backup_postgresql(destino: Path) -> None:
    """Executa ``pg_dump`` e comprime a saida."""
    uri = urlparse(_uri_banco().replace("postgresql+psycopg", "postgresql"))

    comando = [
        "pg_dump",
        "--host", uri.hostname or "localhost",
        "--port", str(uri.port or 5432),
        "--username", uri.username or "postgres",
        "--dbname", (uri.path or "/").lstrip("/"),
        "--no-owner",
        "--no-acl",
        "--clean",
        "--if-exists",
    ]

    ambiente = os.environ.copy()
    if uri.password:
        # A senha vai por variavel de ambiente: em argv ela apareceria no
        # `ps` de qualquer usuario do servidor.
        ambiente["PGPASSWORD"] = uri.password

    try:
        processo = subprocess.run(  # noqa: S603 - argumentos controlados
            comando,
            env=ambiente,
            capture_output=True,
            check=False,
            timeout=600,
        )
    except FileNotFoundError as erro:
        raise ErroRegraNegocio(
            "O comando 'pg_dump' nao foi encontrado no servidor. "
            "Instale os utilitarios do PostgreSQL para habilitar o backup."
        ) from erro
    except subprocess.TimeoutExpired as erro:
        raise ErroRegraNegocio(
            "O backup excedeu o tempo limite de 10 minutos."
        ) from erro

    if processo.returncode != 0:
        detalhe = (processo.stderr or b"").decode("utf-8", "replace")[:300]
        raise ErroRegraNegocio(f"Falha no pg_dump: {detalhe}")

    with gzip.open(destino, "wb", compresslevel=6) as saida:
        saida.write(processo.stdout)


# ---------------------------------------------------------------------------
# Consulta e manutencao
# ---------------------------------------------------------------------------
def listar(limite: int = 50) -> list[RegistroBackup]:
    """Historico de backups, do mais recente para o mais antigo."""
    return (
        db.session.query(RegistroBackup)
        .order_by(RegistroBackup.criado_em.desc())
        .limit(limite)
        .all()
    )


def buscar(backup_id: int | str | None) -> RegistroBackup:
    from app.services.excecoes import RegistroNaoEncontrado

    registro = RegistroBackup.buscar_por_id(backup_id)
    if registro is None:
        raise RegistroNaoEncontrado("Backup nao encontrado.")
    return registro


def estatisticas() -> dict:
    """Resumo exibido na tela de backup."""
    registros = listar(limite=500)
    bem_sucedidos = [r for r in registros if r.sucesso]

    return {
        "total": len(registros),
        "sucesso": len(bem_sucedidos),
        "falhas": len(registros) - len(bem_sucedidos),
        "espaco_bytes": sum(r.tamanho_bytes or 0 for r in bem_sucedidos),
        "ultimo": bem_sucedidos[0] if bem_sucedidos else None,
    }


def aplicar_retencao() -> int:
    """Remove backups fora da politica de retencao.

    Dois criterios combinados: idade maxima em dias e quantidade maxima de
    arquivos. O backup mais recente bem-sucedido nunca e removido, mesmo que
    esteja fora da janela — a escola jamais deve ficar sem nenhuma copia.
    """
    dias = current_app.config.get("BACKUP_RETENCAO_DIAS", 30)
    maximo = current_app.config.get("BACKUP_MAXIMO_ARQUIVOS", 60)

    registros = (
        db.session.query(RegistroBackup)
        .filter(RegistroBackup.sucesso.is_(True))
        .order_by(RegistroBackup.criado_em.desc())
        .all()
    )

    if not registros:
        return 0

    limite_data = agora_utc() - timedelta(days=dias)
    protegido = registros[0].id  # o mais recente nunca e removido

    removidos = 0
    for indice, registro in enumerate(registros):
        if registro.id == protegido:
            continue

        fora_da_janela = registro.criado_em < limite_data
        excede_quantidade = indice >= maximo

        if fora_da_janela or excede_quantidade:
            _remover_arquivo(registro)
            db.session.delete(registro)
            removidos += 1

    if removidos:
        try:
            db.session.commit()
            current_app.logger.info("Retencao de backup: %d removido(s)", removidos)
        except Exception:  # noqa: BLE001
            db.session.rollback()
            removidos = 0

    return removidos


def excluir(registro: RegistroBackup, usuario_id: int | None = None) -> None:
    """Remove um backup do disco e do historico."""
    nome = registro.nome_arquivo
    _remover_arquivo(registro)

    db.session.delete(registro)
    try:
        db.session.commit()
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        raise ErroDominio("Nao foi possivel excluir o registro do backup.") from erro

    auditoria_service.registrar(
        AcaoAuditoria.EXCLUSAO,
        entidade="RegistroBackup",
        descricao=f"Backup removido: {nome}",
        usuario_id=usuario_id,
    )
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


def _remover_arquivo(registro: RegistroBackup) -> None:
    """Apaga o arquivo garantindo que ele esta dentro da pasta de backups."""
    try:
        pasta = _pasta_backups().resolve()
        caminho = Path(registro.caminho).resolve()

        if not caminho.is_relative_to(pasta):
            current_app.logger.warning(
                "Backup fora da pasta esperada, remocao ignorada: %s", caminho
            )
            return

        caminho.unlink(missing_ok=True)
    except OSError as erro:
        current_app.logger.warning("Falha ao remover arquivo de backup: %s", erro)


def caminho_para_download(registro: RegistroBackup) -> Path:
    """Valida e devolve o caminho do arquivo para envio ao navegador."""
    if not registro.sucesso:
        raise ErroRegraNegocio(
            "Este backup falhou e nao possui arquivo para download."
        )

    pasta = _pasta_backups().resolve()
    caminho = Path(registro.caminho).resolve()

    # Impede que um caminho adulterado no banco sirva qualquer arquivo do
    # servidor (path traversal).
    if not caminho.is_relative_to(pasta) or not caminho.exists():
        raise ErroRegraNegocio(
            "O arquivo deste backup nao esta mais disponivel no servidor."
        )

    return caminho


# ---------------------------------------------------------------------------
# Restauracao
# ---------------------------------------------------------------------------
def instrucoes_restauracao(registro: RegistroBackup) -> dict[str, str]:
    """Instrucoes de restauracao para execucao manual pelo administrador.

    A restauracao **nao** e automatizada de propósito: ela sobrescreve o
    banco inteiro e e irreversivel. Um clique acidental na interface web
    poderia destruir o ano letivo da escola. O procedimento exige acesso ao
    servidor, o que garante que uma pessoa tecnica esteja conduzindo — e que
    um backup do estado atual seja feito antes.
    """
    arquivo = registro.nome_arquivo

    if _e_sqlite():
        destino = _caminho_sqlite()
        comandos = (
            f"# 1. Pare a aplicacao\n"
            f"# 2. Faca backup do banco atual\n"
            f"copy \"{destino}\" \"{destino}.antes-da-restauracao\"\n\n"
            f"# 3. Descompacte e substitua\n"
            f"python -c \"import gzip,shutil; "
            f"shutil.copyfileobj(gzip.open(r'{registro.caminho}','rb'), "
            f"open(r'{destino}','wb'))\"\n\n"
            f"# 4. Reinicie a aplicacao e valide com: flask verificar-saude"
        )
    else:
        comandos = (
            f"# 1. Pare a aplicacao\n"
            f"# 2. Faca um dump do estado atual antes de restaurar\n"
            f"flask backup\n\n"
            f"# 3. Restaure o dump\n"
            f"gunzip -c {registro.caminho} | psql \"$DATABASE_URL\"\n\n"
            f"# 4. Reinicie a aplicacao e valide com: flask verificar-saude"
        )

    return {
        "arquivo": arquivo,
        "comandos": comandos,
        "banco": "SQLite" if _e_sqlite() else "PostgreSQL",
    }
