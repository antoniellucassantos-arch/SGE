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
    """Instrumentos avaliativos.

    As duas recuperacoes sao tipos **distintos** de proposito. Antes havia
    apenas ``RECUPERACAO``, e a mesma nota era usada duas vezes: uma para
    substituir a media do periodo e outra, de novo, como recuperacao final —
    inflando a media anual em silencio.
    """

    PROVA = ("prova", "Prova", "primary")
    TRABALHO = ("trabalho", "Trabalho", "info")
    SEMINARIO = ("seminario", "Seminario", "info")
    PARTICIPACAO = ("participacao", "Participacao", "secondary")
    PROJETO = ("projeto", "Projeto", "success")
    RECUPERACAO = ("recuperacao", "Recuperacao do periodo", "warning")
    RECUPERACAO_FINAL = ("recuperacao_final", "Recuperacao final", "danger")
    OUTRO = ("outro", "Outro", "secondary")

    @property
    def e_recuperacao(self) -> bool:
        """Recuperacoes ficam fora da media ponderada do periodo."""
        return self in {
            TipoAvaliacao.RECUPERACAO,
            TipoAvaliacao.RECUPERACAO_FINAL,
        }


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

    # A trilha registrava quem *alterou* a ficha de um aluno, nunca quem a
    # *leu*. A LGPD exige rastrear a leitura quando o dado e de saude de
    # menor de idade (art. 11 e art. 37): sem isso, um vazamento nao tem como
    # ser investigado — a escola sabe que a ficha saiu, mas nao por qual
    # conta.
    ACESSO_DADO_PESSOAL = (
        "acesso_dado_pessoal", "Acesso a dado pessoal", "warning"
    )
    CONSENTIMENTO = ("consentimento", "Consentimento LGPD", "primary")


# ---------------------------------------------------------------------------
# LGPD
# ---------------------------------------------------------------------------
class BaseLegalLGPD(EnumDominio):
    """Hipoteses legais que autorizam o tratamento (LGPD, arts. 7 e 11).

    Toda finalidade precisa de **uma** base legal. Consentimento e apenas uma
    delas, e nao e a mais comum numa escola: matricula, historico e diario de
    classe sao obrigacao legal, e pedir consentimento para eles seria
    enganoso — a escola nao pode parar de emitir historico se a familia
    disser nao.

    Distinguir as bases importa na pratica: so o que se apoia em
    consentimento pode ser revogado.
    """

    OBRIGACAO_LEGAL = (
        "obrigacao_legal", "Obrigacao legal (art. 7, II)", "secondary"
    )
    EXECUCAO_CONTRATO = (
        "execucao_contrato", "Execucao de contrato (art. 7, V)", "secondary"
    )
    TUTELA_DA_SAUDE = (
        "tutela_da_saude", "Tutela da saude (art. 11, II, f)", "danger"
    )
    PROTECAO_DA_VIDA = (
        "protecao_da_vida", "Protecao da vida (art. 7, VII)", "danger"
    )
    CONSENTIMENTO = ("consentimento", "Consentimento (art. 7, I)", "primary")


class FinalidadeTratamento(EnumDominio):
    """Para que a escola trata os dados do aluno.

    A base legal e atributo da **finalidade**, nao da decisao individual: a
    escola nao escolhe aluno a aluno se o dado de saude e tratado sob tutela
    da saude ou sob consentimento — isso e fixado pela lei. Amarrar os dois
    aqui impede que se registre uma combinacao incoerente.

    ``exige_consentimento`` deriva da base legal, com uma excecao proposital:
    saude se apoia na tutela da saude (art. 11, II, "f"), entao a escola
    **pode** tratar mesmo sem autorizacao assinada — mas coleta a autorizacao
    do responsavel assim mesmo, porque e o que permite ligar para o medico e
    porque a familia tem direito de saber o que a escola guarda.

    Este conjunto e o padrao de uma escola brasileira. Ajuste-o com o
    encarregado de dados (DPO) da escola: acrescentar finalidade e
    acrescentar um membro aqui.
    """

    def __new__(
        cls,
        valor: str,
        rotulo: str = "",
        cor: str = "secondary",
        base_legal: BaseLegalLGPD | None = None,
        revogavel: bool = False,
        descricao: str = "",
    ):
        obj = str.__new__(cls, valor)
        obj._value_ = valor
        obj.rotulo = rotulo or valor.replace("_", " ").capitalize()
        obj.cor = cor
        obj.base_legal = base_legal or BaseLegalLGPD.CONSENTIMENTO
        obj.revogavel = revogavel
        obj.descricao = descricao
        return obj

    @property
    def exige_consentimento(self) -> bool:
        """Se a familia precisa autorizar antes de a escola tratar."""
        return self.base_legal is BaseLegalLGPD.CONSENTIMENTO

    VIDA_ESCOLAR = (
        "vida_escolar",
        "Matricula e vida escolar",
        "secondary",
        BaseLegalLGPD.EXECUCAO_CONTRATO,
        False,
        "Cadastro, matricula, turma, boletim e frequencia.",
    )
    REGISTRO_OBRIGATORIO = (
        "registro_obrigatorio",
        "Registro academico obrigatorio",
        "secondary",
        BaseLegalLGPD.OBRIGACAO_LEGAL,
        False,
        "Historico escolar, diario de classe e censo escolar.",
    )
    SAUDE_E_EMERGENCIA = (
        "saude_e_emergencia",
        "Saude e emergencia",
        "danger",
        BaseLegalLGPD.TUTELA_DA_SAUDE,
        False,
        "Alergia, medicamento continuo e condicao de saude, para socorro.",
    )
    SAIDA_DESACOMPANHADA = (
        "saida_desacompanhada",
        "Saida desacompanhada",
        "warning",
        BaseLegalLGPD.CONSENTIMENTO,
        True,
        "Autorizacao para o aluno sair da escola sozinho.",
    )
    USO_DE_IMAGEM = (
        "uso_de_imagem",
        "Uso de imagem",
        "info",
        BaseLegalLGPD.CONSENTIMENTO,
        True,
        "Foto e video em mural, site e material da escola.",
    )
    COMUNICACAO_INSTITUCIONAL = (
        "comunicacao_institucional",
        "Comunicacao nao essencial",
        "info",
        BaseLegalLGPD.CONSENTIMENTO,
        True,
        "Mensagens alem dos avisos academicos: eventos, campanhas, pesquisas.",
    )
    COMPARTILHAMENTO_EXTERNO = (
        "compartilhamento_externo",
        "Compartilhamento com terceiros",
        "warning",
        BaseLegalLGPD.CONSENTIMENTO,
        True,
        "Envio a parceiros: fotografo, sistema de transporte, plano de saude.",
    )

    @classmethod
    def que_exigem_consentimento(cls) -> list[FinalidadeTratamento]:
        return [membro for membro in cls if membro.exige_consentimento]


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
    "BaseLegalLGPD",
    "FinalidadeTratamento",
]
