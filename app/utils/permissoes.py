"""Controle de acesso baseado em papeis (RBAC) do SGE.

Modelo de autorizacao em duas camadas
-------------------------------------
1. **Permissao funcional** (este modulo): o papel pode executar a acao?
   Ex.: professor pode lancar nota; responsavel nao.
2. **Escopo do recurso** (``app/utils/decoradores.py`` + services): o usuario
   pode agir sobre *aquele* registro especifico?
   Ex.: o professor pode lancar nota, mas apenas nas turmas que leciona.

Verificar somente a camada 1 e o erro que produz a vulnerabilidade de
*Broken Access Control* (OWASP A01) — trocar o id na URL e acessar o dado de
outra pessoa. As duas camadas sao obrigatorias em toda rota que recebe id.

Permissoes sao concedidas **explicitamente** por papel, sem heranca
hierarquica implicita. E mais verboso, mas torna a matriz auditavel: para
saber o que a secretaria pode fazer, basta ler uma lista.
"""

from __future__ import annotations

from app.models.enums import PapelUsuario


class Permissao:
    """Catalogo de permissoes no formato ``recurso.acao``.

    Constantes em vez de strings soltas: um erro de digitacao vira
    ``AttributeError`` na hora, e nao um acesso silenciosamente negado (ou,
    pior, concedido) em producao.
    """

    # -- Dashboard e painel --------------------------------------------------
    DASHBOARD_ADMINISTRATIVO = "dashboard.administrativo"
    DASHBOARD_PROFESSOR = "dashboard.professor"
    DASHBOARD_ALUNO = "dashboard.aluno"

    # -- Usuarios ------------------------------------------------------------
    USUARIO_VISUALIZAR = "usuario.visualizar"
    USUARIO_CRIAR = "usuario.criar"
    USUARIO_EDITAR = "usuario.editar"
    USUARIO_EXCLUIR = "usuario.excluir"
    USUARIO_REDEFINIR_SENHA = "usuario.redefinir_senha"

    # -- Alunos --------------------------------------------------------------
    ALUNO_VISUALIZAR = "aluno.visualizar"
    ALUNO_CRIAR = "aluno.criar"
    ALUNO_EDITAR = "aluno.editar"
    ALUNO_EXCLUIR = "aluno.excluir"
    ALUNO_VER_DADOS_SENSIVEIS = "aluno.ver_dados_sensiveis"

    # -- Professores ---------------------------------------------------------
    PROFESSOR_VISUALIZAR = "professor.visualizar"
    PROFESSOR_CRIAR = "professor.criar"
    PROFESSOR_EDITAR = "professor.editar"
    PROFESSOR_EXCLUIR = "professor.excluir"

    # -- Funcionarios --------------------------------------------------------
    FUNCIONARIO_VISUALIZAR = "funcionario.visualizar"
    FUNCIONARIO_CRIAR = "funcionario.criar"
    FUNCIONARIO_EDITAR = "funcionario.editar"
    FUNCIONARIO_EXCLUIR = "funcionario.excluir"

    # -- Responsaveis --------------------------------------------------------
    RESPONSAVEL_VISUALIZAR = "responsavel.visualizar"
    RESPONSAVEL_CRIAR = "responsavel.criar"
    RESPONSAVEL_EDITAR = "responsavel.editar"
    RESPONSAVEL_EXCLUIR = "responsavel.excluir"

    # -- Estrutura academica -------------------------------------------------
    TURMA_VISUALIZAR = "turma.visualizar"
    TURMA_CRIAR = "turma.criar"
    TURMA_EDITAR = "turma.editar"
    TURMA_EXCLUIR = "turma.excluir"

    DISCIPLINA_VISUALIZAR = "disciplina.visualizar"
    DISCIPLINA_CRIAR = "disciplina.criar"
    DISCIPLINA_EDITAR = "disciplina.editar"
    DISCIPLINA_EXCLUIR = "disciplina.excluir"

    # -- Matriculas ----------------------------------------------------------
    MATRICULA_VISUALIZAR = "matricula.visualizar"
    MATRICULA_CRIAR = "matricula.criar"
    MATRICULA_EDITAR = "matricula.editar"
    MATRICULA_TRANSFERIR = "matricula.transferir"
    MATRICULA_CANCELAR = "matricula.cancelar"

    # -- Frequencia ----------------------------------------------------------
    FREQUENCIA_VISUALIZAR = "frequencia.visualizar"
    FREQUENCIA_LANCAR = "frequencia.lancar"
    FREQUENCIA_JUSTIFICAR = "frequencia.justificar"

    # -- Notas e boletim -----------------------------------------------------
    NOTA_VISUALIZAR = "nota.visualizar"
    NOTA_LANCAR = "nota.lancar"
    NOTA_EDITAR_QUALQUER = "nota.editar_qualquer"
    AVALIACAO_GERENCIAR = "avaliacao.gerenciar"
    BOLETIM_VISUALIZAR = "boletim.visualizar"
    BOLETIM_EMITIR = "boletim.emitir"

    # -- Horarios ------------------------------------------------------------
    HORARIO_VISUALIZAR = "horario.visualizar"
    HORARIO_GERENCIAR = "horario.gerenciar"

    # -- Avisos --------------------------------------------------------------
    AVISO_VISUALIZAR = "aviso.visualizar"
    AVISO_CRIAR = "aviso.criar"
    AVISO_EDITAR_QUALQUER = "aviso.editar_qualquer"
    AVISO_EXCLUIR = "aviso.excluir"

    # -- Relatorios ----------------------------------------------------------
    RELATORIO_ACADEMICO = "relatorio.academico"
    RELATORIO_ADMINISTRATIVO = "relatorio.administrativo"
    RELATORIO_EXPORTAR = "relatorio.exportar"

    # -- Sistema -------------------------------------------------------------
    CONFIGURACAO_VISUALIZAR = "configuracao.visualizar"
    CONFIGURACAO_EDITAR = "configuracao.editar"
    AUDITORIA_VISUALIZAR = "auditoria.visualizar"
    BACKUP_EXECUTAR = "backup.executar"
    BACKUP_RESTAURAR = "backup.restaurar"


# ---------------------------------------------------------------------------
# Matriz de permissoes por papel
# ---------------------------------------------------------------------------
_P = Permissao

#: Catalogo completo, derivado da propria classe :class:`Permissao`.
#:
#: Derivar em vez de manter uma lista a mao garante que uma permissao nova
#: entre automaticamente no conjunto do administrador. Uma lista manual
#: esqueceria a proxima — e o esquecimento so apareceria como "acesso negado
#: para o admin", que ninguem imagina ser um bug de cadastro de permissao.
TODAS_PERMISSOES: frozenset[str] = frozenset(
    valor
    for nome, valor in vars(_P).items()
    if not nome.startswith("_") and isinstance(valor, str)
)

#: Permissoes concedidas a todo usuario autenticado, independentemente do papel.
#:
#: Ficam **so** aqui: repeti-las nos conjuntos por papel criaria cinco lugares
#: para manter em sincronia, e um dia a remocao sairia de quatro deles.
PERMISSOES_COMUNS: frozenset[str] = frozenset(
    {
        _P.AVISO_VISUALIZAR,
    }
)

#: Sentinela de acesso irrestrito. Nunca sai deste modulo: ``permissoes_do_papel``
#: a expande para o catalogo completo antes de devolver qualquer coisa.
ACESSO_TOTAL = "*"

#: Permissoes do administrador.
PERMISSOES_ADMINISTRADOR: frozenset[str] = frozenset({ACESSO_TOTAL})

PERMISSOES_DIRECAO: frozenset[str] = frozenset(
    {
        _P.DASHBOARD_ADMINISTRATIVO,
        # Pessoas: visualiza e edita, mas nao gerencia contas de acesso.
        _P.USUARIO_VISUALIZAR,
        _P.ALUNO_VISUALIZAR, _P.ALUNO_CRIAR, _P.ALUNO_EDITAR,
        _P.ALUNO_VER_DADOS_SENSIVEIS,
        _P.PROFESSOR_VISUALIZAR, _P.PROFESSOR_CRIAR, _P.PROFESSOR_EDITAR,
        _P.FUNCIONARIO_VISUALIZAR, _P.FUNCIONARIO_CRIAR, _P.FUNCIONARIO_EDITAR,
        _P.RESPONSAVEL_VISUALIZAR, _P.RESPONSAVEL_CRIAR, _P.RESPONSAVEL_EDITAR,
        # Estrutura academica
        _P.TURMA_VISUALIZAR, _P.TURMA_CRIAR, _P.TURMA_EDITAR,
        _P.DISCIPLINA_VISUALIZAR, _P.DISCIPLINA_CRIAR, _P.DISCIPLINA_EDITAR,
        # Vida escolar
        _P.MATRICULA_VISUALIZAR, _P.MATRICULA_CRIAR, _P.MATRICULA_EDITAR,
        _P.MATRICULA_TRANSFERIR, _P.MATRICULA_CANCELAR,
        _P.FREQUENCIA_VISUALIZAR, _P.FREQUENCIA_JUSTIFICAR,
        _P.NOTA_VISUALIZAR, _P.NOTA_EDITAR_QUALQUER, _P.AVALIACAO_GERENCIAR,
        _P.BOLETIM_VISUALIZAR, _P.BOLETIM_EMITIR,
        _P.HORARIO_VISUALIZAR, _P.HORARIO_GERENCIAR,
        # Comunicacao e relatorios (AVISO_VISUALIZAR vem de PERMISSOES_COMUNS)
        _P.AVISO_CRIAR, _P.AVISO_EDITAR_QUALQUER,
        _P.AVISO_EXCLUIR,
        _P.RELATORIO_ACADEMICO, _P.RELATORIO_ADMINISTRATIVO,
        _P.RELATORIO_EXPORTAR,
        # Sistema (leitura)
        _P.CONFIGURACAO_VISUALIZAR,
        _P.AUDITORIA_VISUALIZAR,
    }
)

PERMISSOES_SECRETARIA: frozenset[str] = frozenset(
    {
        _P.DASHBOARD_ADMINISTRATIVO,
        _P.ALUNO_VISUALIZAR, _P.ALUNO_CRIAR, _P.ALUNO_EDITAR,
        _P.ALUNO_VER_DADOS_SENSIVEIS,
        _P.PROFESSOR_VISUALIZAR, _P.PROFESSOR_CRIAR, _P.PROFESSOR_EDITAR,
        _P.FUNCIONARIO_VISUALIZAR, _P.FUNCIONARIO_CRIAR, _P.FUNCIONARIO_EDITAR,
        _P.RESPONSAVEL_VISUALIZAR, _P.RESPONSAVEL_CRIAR, _P.RESPONSAVEL_EDITAR,
        _P.TURMA_VISUALIZAR, _P.TURMA_CRIAR, _P.TURMA_EDITAR,
        _P.DISCIPLINA_VISUALIZAR, _P.DISCIPLINA_CRIAR, _P.DISCIPLINA_EDITAR,
        _P.MATRICULA_VISUALIZAR, _P.MATRICULA_CRIAR, _P.MATRICULA_EDITAR,
        _P.MATRICULA_TRANSFERIR, _P.MATRICULA_CANCELAR,
        _P.FREQUENCIA_VISUALIZAR, _P.FREQUENCIA_JUSTIFICAR,
        # Secretaria consulta e emite documento, mas nao lanca nota:
        # lancamento e ato pedagogico, de responsabilidade do professor.
        _P.NOTA_VISUALIZAR,
        _P.BOLETIM_VISUALIZAR, _P.BOLETIM_EMITIR,
        _P.HORARIO_VISUALIZAR, _P.HORARIO_GERENCIAR,
        _P.AVISO_CRIAR,
        _P.RELATORIO_ACADEMICO, _P.RELATORIO_ADMINISTRATIVO,
        _P.RELATORIO_EXPORTAR,
    }
)

PERMISSOES_PROFESSOR: frozenset[str] = frozenset(
    {
        _P.DASHBOARD_PROFESSOR,
        # Ve alunos, mas nao os dados sensiveis de saude.
        _P.ALUNO_VISUALIZAR,
        _P.TURMA_VISUALIZAR,
        _P.DISCIPLINA_VISUALIZAR,
        _P.MATRICULA_VISUALIZAR,
        # Escopo restrito as proprias turmas, garantido pelos decoradores.
        _P.FREQUENCIA_VISUALIZAR, _P.FREQUENCIA_LANCAR,
        _P.NOTA_VISUALIZAR, _P.NOTA_LANCAR, _P.AVALIACAO_GERENCIAR,
        _P.BOLETIM_VISUALIZAR,
        _P.HORARIO_VISUALIZAR,
        _P.AVISO_CRIAR,
        _P.RELATORIO_ACADEMICO,
    }
)

#: Aluno e responsavel tem exatamente as mesmas permissoes funcionais — e
#: isso e proposital, nao um descuido.
#:
#: A diferenca entre os dois nao e *o que* podem fazer (ver nota, ver
#: frequencia, ver boletim), e sim *sobre quem*: o aluno ve a si mesmo, o
#: responsavel ve os dependentes. Essa distincao e de escopo, e escopo e
#: camada 2 — ``pode_acessar_aluno()`` em ``decoradores.py``.
#:
#: Consequencia pratica que precisa ficar registrada: para estes dois papeis
#: a camada 1 nao protege quase nada. **Toda** rota que eles alcancam depende
#: do decorador de escopo estar presente. Esquecer um ``@exigir_acesso_aluno``
#: aqui nao produz um erro visivel — produz um responsavel lendo o boletim do
#: filho de outra pessoa.
PERMISSOES_ALUNO: frozenset[str] = frozenset(
    {
        _P.DASHBOARD_ALUNO,
        _P.NOTA_VISUALIZAR,
        _P.FREQUENCIA_VISUALIZAR,
        _P.BOLETIM_VISUALIZAR,
        _P.HORARIO_VISUALIZAR,
    }
)

PERMISSOES_RESPONSAVEL: frozenset[str] = PERMISSOES_ALUNO

MATRIZ_PERMISSOES: dict[PapelUsuario, frozenset[str]] = {
    PapelUsuario.ADMINISTRADOR: PERMISSOES_ADMINISTRADOR,
    PapelUsuario.DIRECAO: PERMISSOES_DIRECAO,
    PapelUsuario.SECRETARIA: PERMISSOES_SECRETARIA,
    PapelUsuario.PROFESSOR: PERMISSOES_PROFESSOR,
    PapelUsuario.ALUNO: PERMISSOES_ALUNO,
    PapelUsuario.RESPONSAVEL: PERMISSOES_RESPONSAVEL,
}


# ---------------------------------------------------------------------------
# API de consulta
# ---------------------------------------------------------------------------
def permissoes_do_papel(papel: PapelUsuario | str | None) -> frozenset[str]:
    """Conjunto de permissoes concedidas a um papel.

    A sentinela ``"*"`` e expandida aqui e nunca chega a quem chama. Antes
    ela vazava no retorno, o que criava duas formas de perguntar a mesma
    coisa — e a mais obvia (``permissao in permissoes_do_papel(papel)``)
    respondia **errado justamente para o administrador**, negando acesso em
    silencio. Uma unica forma correta e melhor que duas, sendo uma
    armadilha.
    """
    if papel is None:
        return frozenset()

    if isinstance(papel, str):
        papel = PapelUsuario.de_valor(papel)
        if papel is None:
            return frozenset()

    concedidas = MATRIZ_PERMISSOES.get(papel, frozenset())
    if ACESSO_TOTAL in concedidas:
        return TODAS_PERMISSOES

    return concedidas | PERMISSOES_COMUNS


def papel_tem_permissao(papel: PapelUsuario | str | None, permissao: str) -> bool:
    """Verifica se um papel possui a permissao."""
    return permissao in permissoes_do_papel(papel)


def usuario_tem_permissao(usuario, permissao: str) -> bool:
    """Verifica a permissao de um usuario autenticado.

    Contas inativas, excluidas ou bloqueadas perdem todas as permissoes,
    mesmo que a sessao ainda exista — importante para que a desativacao de um
    funcionario desligado tenha efeito imediato.
    """
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    if not getattr(usuario, "is_active", False):
        return False

    return papel_tem_permissao(getattr(usuario, "papel", None), permissao)


def usuario_tem_alguma_permissao(usuario, *permissoes: str) -> bool:
    """``True`` se o usuario possuir ao menos uma das permissoes."""
    return any(usuario_tem_permissao(usuario, p) for p in permissoes)


def usuario_tem_todas_permissoes(usuario, *permissoes: str) -> bool:
    """``True`` somente se o usuario possuir todas as permissoes."""
    return all(usuario_tem_permissao(usuario, p) for p in permissoes)


def descrever_matriz() -> dict[str, list[str]]:
    """Matriz completa em formato legivel, usada na documentacao e nos testes."""
    return {
        papel.value: sorted(permissoes_do_papel(papel))
        for papel in PapelUsuario
    }
