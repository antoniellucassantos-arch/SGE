"""Enumeracoes de dominio do SGE.

Todas as enumeracoes herdam de :class:`EnumDominio`, que agrega comportamento
util para a camada de apresentacao (rotulo legivel, cor do badge Bootstrap e
geracao de ``choices`` para WTForms) sem espalhar ``if/elif`` pelos templates.

Persistencia: os valores sao gravados no banco como *strings curtas* e
estaveis (ex.: ``"ativo"``). Isso mantem o dump do banco legivel e evita o
problema classico de ``Enum`` nativo do PostgreSQL, cuja alteracao exige
migration com ``ALTER TYPE``.
"""

from __future__ import annotations

from enum import Enum


class EnumDominio(str, Enum):
    """Enum base com rotulo e cor para exibicao.

    Herdar de ``str`` faz o valor ser serializado de forma transparente pelo
    SQLAlchemy, pelo Jinja2 e por eventuais respostas JSON.
    """

    def __new__(cls, valor: str, rotulo: str = "", cor: str = "secondary"):
        obj = str.__new__(cls, valor)
        obj._value_ = valor
        obj.rotulo = rotulo or valor.replace("_", " ").capitalize()
        obj.cor = cor
        return obj

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def escolhas(cls, incluir_vazio: bool = False, rotulo_vazio: str = "Todos"):
        """Retorna ``[(valor, rotulo), ...]`` pronto para ``SelectField``."""
        opcoes = [(membro.value, membro.rotulo) for membro in cls]
        if incluir_vazio:
            opcoes.insert(0, ("", rotulo_vazio))
        return opcoes

    @classmethod
    def valores(cls) -> list[str]:
        """Lista apenas os valores persistidos (util em validadores)."""
        return [membro.value for membro in cls]

    @classmethod
    def de_valor(cls, valor: str | None):
        """Converte uma string em membro do enum, ou ``None`` se invalida."""
        if valor is None:
            return None
        try:
            return cls(valor)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Usuarios e acesso
# ---------------------------------------------------------------------------
class PapelUsuario(EnumDominio):
    """Perfis de acesso do sistema (base do controle RBAC).

    A ordem de declaracao reflete a hierarquia administrativa e e usada para
    ordenar listagens; ela **nao** implica heranca de permissoes: cada
    permissao e concedida explicitamente em ``app/utils/permissoes.py``.
    """

    ADMINISTRADOR = ("administrador", "Administrador", "danger")
    DIRECAO = ("direcao", "Direcao", "primary")
    SECRETARIA = ("secretaria", "Secretaria", "info")
    PROFESSOR = ("professor", "Professor", "success")
    ALUNO = ("aluno", "Aluno", "warning")
    RESPONSAVEL = ("responsavel", "Responsavel", "secondary")

    @property
    def e_equipe_interna(self) -> bool:
        """Indica perfis funcionarios da escola (acesso administrativo)."""
        return self in {
            PapelUsuario.ADMINISTRADOR,
            PapelUsuario.DIRECAO,
            PapelUsuario.SECRETARIA,
            PapelUsuario.PROFESSOR,
        }


# ---------------------------------------------------------------------------
# Situacoes genericas de cadastro
# ---------------------------------------------------------------------------
class SituacaoCadastro(EnumDominio):
    """Situacao de cadastros de pessoas (aluno, professor, funcionario)."""

    ATIVO = ("ativo", "Ativo", "success")
    INATIVO = ("inativo", "Inativo", "secondary")
    TRANSFERIDO = ("transferido", "Transferido", "warning")
    FORMADO = ("formado", "Formado", "info")
    DESLIGADO = ("desligado", "Desligado", "dark")


class Sexo(EnumDominio):
    MASCULINO = ("masculino", "Masculino", "primary")
    FEMININO = ("feminino", "Feminino", "danger")
    NAO_INFORMADO = ("nao_informado", "Nao informado", "secondary")


class EstadoCivil(EnumDominio):
    SOLTEIRO = ("solteiro", "Solteiro(a)", "secondary")
    CASADO = ("casado", "Casado(a)", "secondary")
    DIVORCIADO = ("divorciado", "Divorciado(a)", "secondary")
    VIUVO = ("viuvo", "Viuvo(a)", "secondary")
    UNIAO_ESTAVEL = ("uniao_estavel", "Uniao estavel", "secondary")
    NAO_INFORMADO = ("nao_informado", "Nao informado", "secondary")


class Parentesco(EnumDominio):
    """Vinculo entre o responsavel e o aluno."""

    MAE = ("mae", "Mae", "danger")
    PAI = ("pai", "Pai", "primary")
    AVO = ("avo", "Avo/Avo", "info")
    TIO = ("tio", "Tio(a)", "info")
    IRMAO = ("irmao", "Irmao(a)", "info")
    TUTOR_LEGAL = ("tutor_legal", "Tutor legal", "warning")
    OUTRO = ("outro", "Outro", "secondary")


# ---------------------------------------------------------------------------
# Estrutura academica
# ---------------------------------------------------------------------------
class NivelEnsino(EnumDominio):
    INFANTIL = ("infantil", "Educacao Infantil", "warning")
    FUNDAMENTAL_I = ("fundamental_i", "Ensino Fundamental I", "info")
    FUNDAMENTAL_II = ("fundamental_ii", "Ensino Fundamental II", "primary")
    MEDIO = ("medio", "Ensino Medio", "success")
    EJA = ("eja", "EJA", "secondary")


class Turno(EnumDominio):
    MATUTINO = ("matutino", "Matutino", "warning")
    VESPERTINO = ("vespertino", "Vespertino", "info")
    NOTURNO = ("noturno", "Noturno", "dark")
    INTEGRAL = ("integral", "Integral", "primary")


class SituacaoAnoLetivo(EnumDominio):
    PLANEJAMENTO = ("planejamento", "Em planejamento", "secondary")
    EM_ANDAMENTO = ("em_andamento", "Em andamento", "success")
    ENCERRADO = ("encerrado", "Encerrado", "dark")


class SituacaoMatricula(EnumDominio):
    ATIVA = ("ativa", "Ativa", "success")
    TRANCADA = ("trancada", "Trancada", "warning")
    TRANSFERIDA = ("transferida", "Transferida", "info")
    CANCELADA = ("cancelada", "Cancelada", "danger")
    CONCLUIDA = ("concluida", "Concluida", "primary")

    @property
    def e_encerrada(self) -> bool:
        """Matriculas encerradas nao aceitam novos lancamentos."""
        return self in {
            SituacaoMatricula.TRANSFERIDA,
            SituacaoMatricula.CANCELADA,
            SituacaoMatricula.CONCLUIDA,
        }


class ResultadoFinal(EnumDominio):
    """Resultado consolidado do aluno na disciplina ou no ano letivo."""

    APROVADO = ("aprovado", "Aprovado", "success")
    APROVADO_CONSELHO = ("aprovado_conselho", "Aprovado pelo conselho", "info")
    RECUPERACAO = ("recuperacao", "Em recuperacao", "warning")
    REPROVADO = ("reprovado", "Reprovado", "danger")
    REPROVADO_FALTA = ("reprovado_falta", "Reprovado por falta", "danger")
    CURSANDO = ("cursando", "Cursando", "secondary")


class TipoAvaliacao(EnumDominio):
    PROVA = ("prova", "Prova", "primary")
    TRABALHO = ("trabalho", "Trabalho", "info")
    SEMINARIO = ("seminario", "Seminario", "info")
    PARTICIPACAO = ("participacao", "Participacao", "secondary")
    PROJETO = ("projeto", "Projeto", "success")
    RECUPERACAO = ("recuperacao", "Recuperacao", "warning")
    OUTRO = ("outro", "Outro", "secondary")


class SituacaoPresenca(EnumDominio):
    """Situacao do aluno em uma aula especifica."""

    PRESENTE = ("presente", "Presente", "success")
    FALTA = ("falta", "Falta", "danger")
    FALTA_JUSTIFICADA = ("falta_justificada", "Falta justificada", "warning")
    ATRASO = ("atraso", "Atraso", "info")

    @property
    def conta_presenca(self) -> bool:
        """Define se a situacao conta como presenca no calculo de frequencia.

        Regra adotada: atraso e falta justificada contam como presenca para
        fins de frequencia legal, mas sao registrados separadamente para que
        a coordenacao consiga acompanhar o comportamento do aluno.
        """
        return self in {
            SituacaoPresenca.PRESENTE,
            SituacaoPresenca.ATRASO,
            SituacaoPresenca.FALTA_JUSTIFICADA,
        }


class DiaSemana(EnumDominio):
    """Dias letivos usados na grade de horarios.

    O valor persistido e o indice ISO (1 = segunda), o que permite ordenar a
    grade diretamente no banco e comparar com ``date.isoweekday()``.
    """

    SEGUNDA = ("1", "Segunda-feira", "primary")
    TERCA = ("2", "Terca-feira", "primary")
    QUARTA = ("3", "Quarta-feira", "primary")
    QUINTA = ("4", "Quinta-feira", "primary")
    SEXTA = ("5", "Sexta-feira", "primary")
    SABADO = ("6", "Sabado", "info")

    @property
    def indice(self) -> int:
        return int(self.value)

    @property
    def abreviacao(self) -> str:
        return self.rotulo[:3].upper()


# ---------------------------------------------------------------------------
# Comunicacao
# ---------------------------------------------------------------------------
class PublicoAviso(EnumDominio):
    """Segmentacao do publico-alvo de um aviso."""

    TODOS = ("todos", "Todos os usuarios", "primary")
    EQUIPE = ("equipe", "Equipe interna", "dark")
    PROFESSORES = ("professores", "Professores", "success")
    ALUNOS = ("alunos", "Alunos", "warning")
    RESPONSAVEIS = ("responsaveis", "Responsaveis", "info")
    TURMA = ("turma", "Turma especifica", "secondary")


class PrioridadeAviso(EnumDominio):
    BAIXA = ("baixa", "Baixa", "secondary")
    NORMAL = ("normal", "Normal", "primary")
    ALTA = ("alta", "Alta", "warning")
    URGENTE = ("urgente", "Urgente", "danger")


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
class AcaoAuditoria(EnumDominio):
    """Acoes registradas na trilha de auditoria."""

    CRIACAO = ("criacao", "Criacao", "success")
    ATUALIZACAO = ("atualizacao", "Atualizacao", "info")
    EXCLUSAO = ("exclusao", "Exclusao", "danger")
    LOGIN = ("login", "Login", "primary")
    LOGOUT = ("logout", "Logout", "secondary")
    LOGIN_FALHOU = ("login_falhou", "Falha de login", "warning")
    SENHA_ALTERADA = ("senha_alterada", "Senha alterada", "warning")
    SENHA_RECUPERADA = ("senha_recuperada", "Senha recuperada", "warning")
    ACESSO_NEGADO = ("acesso_negado", "Acesso negado", "danger")
    BACKUP = ("backup", "Backup", "dark")
    RESTAURACAO = ("restauracao", "Restauracao", "danger")
    EXPORTACAO = ("exportacao", "Exportacao", "info")


__all__ = [
    "EnumDominio",
    "PapelUsuario",
    "SituacaoCadastro",
    "Sexo",
    "EstadoCivil",
    "Parentesco",
    "NivelEnsino",
    "Turno",
    "SituacaoAnoLetivo",
    "SituacaoMatricula",
    "ResultadoFinal",
    "TipoAvaliacao",
    "SituacaoPresenca",
    "DiaSemana",
    "PublicoAviso",
    "PrioridadeAviso",
    "AcaoAuditoria",
]
