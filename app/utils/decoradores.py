"""Decoradores de autorizacao e utilitarios de rota.

Complementam ``app/utils/permissoes.py`` aplicando as regras no nivel da
rota Flask e registrando as tentativas negadas na auditoria — um acesso
negado e um sinal de seguranca relevante, nao apenas um erro de navegacao.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.models.enums import PapelUsuario
from app.utils.permissoes import (
    usuario_tem_alguma_permissao,
    usuario_tem_permissao,
    usuario_tem_todas_permissoes,
)

#: Atributos que os decoradores penduram na view, para inspecao posterior.
#:
#: Existem para a varredura de ``tests/integration/test_escopo_de_rotas.py``,
#: que percorre o ``url_map`` e prova que nenhuma rota com id ficou apenas
#: com permissao funcional. Sem essa marca, a unica forma de verificar seria
#: ler o codigo — e a regra que a auditoria encontrou quebrada tres vezes
#: nao pode depender de alguem lembrar de ler.
ATRIBUTO_ESCOPO = "_escopos_validados"
ATRIBUTO_PERMISSOES = "_permissoes_exigidas"


def _marcar(wrapper: Callable, funcao: Callable, atributo: str, *valores) -> None:
    """Acumula uma marca no wrapper, preservando o que ja havia.

    ``functools.wraps`` copia o ``__dict__`` do embrulhado, entao decoradores
    empilhados somam suas marcas em vez de se sobrescrever.
    """
    herdados = tuple(getattr(funcao, atributo, ()))
    setattr(wrapper, atributo, (*herdados, *valores))


def _negar_acesso(motivo: str):
    """Trata uma tentativa de acesso negada de forma coerente.

    Requisicoes AJAX recebem 403 puro; navegacao normal recebe a pagina 403
    do sistema. Em ambos os casos o evento vai para a auditoria.
    """
    from app.services.auditoria_service import registrar_acesso_negado

    registrar_acesso_negado(motivo)
    abort(403)


def _usuario_valido() -> bool:
    return bool(
        current_user
        and getattr(current_user, "is_authenticated", False)
        and getattr(current_user, "is_active", False)
    )


def requer_permissao(*permissoes: str, exigir_todas: bool = False) -> Callable:
    """Exige que o usuario possua a(s) permissao(oes) informada(s).

    Por padrao basta **uma** das permissoes (util em rotas compartilhadas por
    perfis diferentes). Use ``exigir_todas=True`` para conjuncao.

        @bp.route("/alunos/novo")
        @login_required
        @requer_permissao(Permissao.ALUNO_CRIAR)
        def novo():
            ...

    Sobre o ``@login_required`` acima, que a primeira vista e redundante:
    este decorador de fato ja recusa quem nao esta autenticado. Ele fica
    porque as duas recusas nao sao equivalentes. O ``login_required`` passa
    pelo ``login_manager``, que exibe a mensagem "faca login para continuar"
    e guarda o destino pretendido; a recusa daqui e um redirect seco, pensada
    para o caso em que a sessao expirou no meio de uma acao. Remover a linha
    trocaria uma explicacao por uma tela de login sem contexto nenhum.
    """

    def decorador(funcao: Callable) -> Callable:
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            if not _usuario_valido():
                return redirect(url_for("auth.login", next=request.full_path))

            verificador = (
                usuario_tem_todas_permissoes
                if exigir_todas
                else usuario_tem_alguma_permissao
            )
            if not verificador(current_user, *permissoes):
                return _negar_acesso(
                    f"Permissao ausente: {', '.join(permissoes)}"
                )

            return funcao(*args, **kwargs)

        _marcar(wrapper, funcao, ATRIBUTO_PERMISSOES, *permissoes)
        return wrapper

    return decorador


def requer_papel(*papeis: PapelUsuario | str) -> Callable:
    """Restringe a rota a papeis especificos.

    Prefira :func:`requer_permissao`: amarrar rotas a papeis torna a matriz
    dificil de evoluir. Use este decorador apenas quando a restricao for
    realmente sobre o papel (ex.: area exclusiva do professor).
    """

    def decorador(funcao: Callable) -> Callable:
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            if not _usuario_valido():
                return redirect(url_for("auth.login", next=request.full_path))

            if not current_user.tem_papel(*papeis):
                alvos = ", ".join(
                    p.value if isinstance(p, PapelUsuario) else str(p) for p in papeis
                )
                return _negar_acesso(f"Papel exigido: {alvos}")

            return funcao(*args, **kwargs)

        return wrapper

    return decorador


def somente_equipe(funcao: Callable) -> Callable:
    """Restringe a rota a funcionarios da escola (bloqueia aluno/responsavel)."""

    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if not _usuario_valido():
            return redirect(url_for("auth.login", next=request.full_path))

        if not current_user.e_equipe_interna:
            return _negar_acesso("Rota restrita a equipe interna")

        return funcao(*args, **kwargs)

    return wrapper


def somente_administrador(funcao: Callable) -> Callable:
    """Restringe a rota ao papel de administrador."""

    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if not _usuario_valido():
            return redirect(url_for("auth.login", next=request.full_path))

        if not current_user.e_administrador:
            return _negar_acesso("Rota restrita a administradores")

        return funcao(*args, **kwargs)

    return wrapper


def confirmar_senha_atualizada(funcao: Callable) -> Callable:
    """Bloqueia a navegacao ate que a troca de senha obrigatoria ocorra.

    Aplicado globalmente por ``before_request``; existe tambem como decorador
    para rotas registradas fora do fluxo normal.
    """

    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if _usuario_valido() and current_user.deve_trocar_senha:
            flash(
                "Por seguranca, defina uma nova senha antes de continuar.",
                "warning",
            )
            return redirect(url_for("auth.alterar_senha"))
        return funcao(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Verificacoes de escopo (camada 2 da autorizacao)
# ---------------------------------------------------------------------------
def pode_acessar_turma(turma_id: int | None) -> bool:
    """Decide se o usuario atual pode ver os dados de uma turma.

    - Equipe administrativa (admin, direcao, secretaria): todas as turmas.
    - Professor: apenas turmas em que possui vinculo ativo.
    - Aluno: apenas a propria turma.
    - Responsavel: apenas as turmas dos alunos sob sua responsabilidade.
    """
    if not _usuario_valido() or turma_id is None:
        return False

    if current_user.tem_papel(
        PapelUsuario.ADMINISTRADOR, PapelUsuario.DIRECAO, PapelUsuario.SECRETARIA
    ):
        return True

    if current_user.e_professor:
        professor = current_user.professor
        return bool(professor and professor.leciona_para_turma(turma_id))

    if current_user.e_aluno and current_user.aluno:
        turma = current_user.aluno.turma_atual
        return bool(turma and turma.id == turma_id)

    if current_user.e_responsavel and current_user.responsavel:
        for aluno in current_user.responsavel.alunos:
            turma = aluno.turma_atual
            if turma and turma.id == turma_id:
                return True

    return False


def pode_acessar_aluno(aluno_id: int | None) -> bool:
    """Decide se o usuario atual pode ver a ficha de um aluno."""
    if not _usuario_valido() or aluno_id is None:
        return False

    if current_user.tem_papel(
        PapelUsuario.ADMINISTRADOR, PapelUsuario.DIRECAO, PapelUsuario.SECRETARIA
    ):
        return True

    if current_user.e_aluno and current_user.aluno:
        return current_user.aluno.id == aluno_id

    if current_user.e_responsavel and current_user.responsavel:
        return current_user.responsavel.e_responsavel_por(aluno_id)

    if current_user.e_professor and current_user.professor:
        # O professor ve apenas os alunos das turmas em que leciona.
        from app.extensions import db
        from app.models.enums import SituacaoMatricula
        from app.models.matricula import Matricula

        turmas_do_aluno = {
            linha[0]
            for linha in db.session.query(Matricula.turma_id)
            .filter(
                Matricula.aluno_id == aluno_id,
                Matricula.situacao == SituacaoMatricula.ATIVA,
                Matricula.excluido_em.is_(None),
            )
            .all()
        }
        return any(
            current_user.professor.leciona_para_turma(tid) for tid in turmas_do_aluno
        )

    return False


def pode_lancar_em_vinculo(turma_disciplina) -> bool:
    """Decide se o usuario pode lancar nota/frequencia em um vinculo.

    Regra: o professor titular lanca nas proprias turmas; administrador e
    direcao podem corrigir qualquer lancamento (com registro em auditoria);
    a secretaria nao lanca — lancamento e ato pedagogico.
    """
    if not _usuario_valido() or turma_disciplina is None:
        return False

    if current_user.tem_papel(PapelUsuario.ADMINISTRADOR, PapelUsuario.DIRECAO):
        return True

    if current_user.e_professor and current_user.professor:
        return turma_disciplina.professor_id == current_user.professor.id

    return False


def exigir_acesso_turma(nome_parametro: str = "turma_id") -> Callable:
    """Valida o escopo de turma a partir de um parametro da rota.

        @bp.route("/turmas/<int:turma_id>/diario")
        @exigir_acesso_turma()
        def diario(turma_id):
            ...
    """

    def decorador(funcao: Callable) -> Callable:
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            turma_id = kwargs.get(nome_parametro)
            if not pode_acessar_turma(turma_id):
                return _negar_acesso(f"Escopo negado para turma {turma_id}")
            return funcao(*args, **kwargs)

        _marcar(wrapper, funcao, ATRIBUTO_ESCOPO, nome_parametro)
        return wrapper

    return decorador


def exigir_vinculo(nome_parametro: str = "vinculo_id") -> Callable:
    """Valida se o usuario pode **lancar** no vinculo turma x disciplina.

    Complementa :func:`exigir_acesso_turma`, que autoriza apenas a leitura.
    Aqui a exigencia e maior: so o professor titular da disciplina (ou a
    direcao) escreve no diario e nas notas.

        @bp.route("/notas/<int:vinculo_id>", methods=["POST"])
        @exigir_vinculo()
        def lancar(vinculo_id):
            ...
    """

    def decorador(funcao: Callable) -> Callable:
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            from app.extensions import db
            from app.models.estrutura import TurmaDisciplina

            vinculo_id = kwargs.get(nome_parametro)
            vinculo = (
                db.session.get(TurmaDisciplina, vinculo_id)
                if vinculo_id is not None
                else None
            )

            if not pode_lancar_em_vinculo(vinculo):
                return _negar_acesso(
                    f"Escopo de lancamento negado para vinculo {vinculo_id}"
                )

            return funcao(*args, **kwargs)

        _marcar(wrapper, funcao, ATRIBUTO_ESCOPO, nome_parametro)
        return wrapper

    return decorador


def exigir_acesso_aluno(nome_parametro: str = "aluno_id") -> Callable:
    """Valida o escopo de aluno a partir de um parametro da rota."""

    def decorador(funcao: Callable) -> Callable:
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            aluno_id = kwargs.get(nome_parametro)
            if not pode_acessar_aluno(aluno_id):
                return _negar_acesso(f"Escopo negado para aluno {aluno_id}")
            return funcao(*args, **kwargs)

        _marcar(wrapper, funcao, ATRIBUTO_ESCOPO, nome_parametro)
        return wrapper

    return decorador


__all__ = [
    "ATRIBUTO_ESCOPO",
    "ATRIBUTO_PERMISSOES",
    "requer_permissao",
    "requer_papel",
    "somente_equipe",
    "somente_administrador",
    "confirmar_senha_atualizada",
    "pode_acessar_turma",
    "pode_acessar_aluno",
    "pode_lancar_em_vinculo",
    "exigir_acesso_turma",
    "exigir_acesso_aluno",
    "exigir_vinculo",
    "usuario_tem_permissao",
]
