"""Regras de negocio do cadastro de alunos."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import Parentesco, SituacaoCadastro, SituacaoMatricula
from app.models.matricula import Matricula
from app.models.pessoas import Aluno, AlunoResponsavel, Responsavel
from app.models.usuario import Usuario
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)
from app.utils.seguranca import apenas_digitos, remover_acentos
from app.utils.validadores import cpf_valido

# ---------------------------------------------------------------------------
# Dados sensiveis
# ---------------------------------------------------------------------------
#: Atributos derivados que revelam a mesma informacao dos campos protegidos.
#:
#: ``tem_alerta_saude`` e so um booleano, mas "este aluno tem uma condicao de
#: saude" ja e informacao de saude — e era exibido como icone na listagem para
#: qualquer um com ``aluno.visualizar``.
_DERIVADOS_SENSIVEIS: frozenset[str] = frozenset({"tem_alerta_saude"})


def pode_ver_dados_sensiveis(usuario=None) -> bool:
    """Decide se o usuario pode enxergar saude e documentos do aluno.

    A resposta vem da matriz de permissoes, e nao de uma lista de papeis
    repetida na rota: duas fontes de verdade divergem no dia em que a escola
    criar um papel novo — e a que fica desatualizada e sempre a mais
    permissiva.
    """
    from flask_login import current_user

    from app.utils.permissoes import Permissao, usuario_tem_permissao

    return usuario_tem_permissao(
        current_user if usuario is None else usuario,
        Permissao.ALUNO_VER_DADOS_SENSIVEIS,
    )


class FichaAluno:
    """Aluno com os campos sensiveis ja removidos, conforme a permissao.

    Existe porque esconder o ``<td>`` no template nao esconde nada: o dado
    ja viajou ate o navegador e esta no HTML, a um Ctrl+U de distancia. Pior,
    a protecao passa a depender de nenhum template futuro esquecer o
    ``{% if %}`` — uma garantia que nao se sustenta.

    Entregando esta ficha em vez do model, nao ha o que vazar: os atributos
    protegidos simplesmente valem ``None``. Todo o resto e delegado ao aluno
    original, entao os templates continuam escritos do mesmo jeito.
    """

    __slots__ = ("_aluno", "_completa")

    def __init__(self, aluno: Aluno, completa: bool) -> None:
        object.__setattr__(self, "_aluno", aluno)
        object.__setattr__(self, "_completa", completa)

    def __getattr__(self, nome: str) -> Any:
        if not self._completa and (
            nome in Aluno.CAMPOS_SENSIVEIS or nome in _DERIVADOS_SENSIVEIS
        ):
            # Booleano protegido vira `False`, e nao `None`: um `None` em
            # `{% if aluno.possui_deficiencia %}` funciona igual, mas em
            # comparacao direta no Python nao.
            return False if nome in _BOOLEANOS_SENSIVEIS else None
        return getattr(self._aluno, nome)

    def __setattr__(self, nome: str, valor: Any) -> None:
        raise AttributeError(
            "FichaAluno e somente leitura. Para alterar, use o proprio model."
        )

    def __repr__(self) -> str:  # pragma: no cover
        estado = "completa" if self._completa else "restrita"
        return f"<FichaAluno {self._aluno.codigo} ({estado})>"


#: Campos sensiveis de tipo booleano — ver `FichaAluno.__getattr__`.
_BOOLEANOS_SENSIVEIS: frozenset[str] = frozenset(
    {"possui_deficiencia", "necessita_acompanhante", "tem_alerta_saude"}
)


def montar_ficha(aluno: Aluno, usuario=None) -> FichaAluno:
    """Embrulha o aluno na visao permitida ao usuario."""
    return FichaAluno(aluno, pode_ver_dados_sensiveis(usuario))


def montar_fichas(alunos, usuario=None) -> list[FichaAluno]:
    """Versao em lote, para listagens.

    A permissao e resolvida uma vez so: ela nao muda no meio de uma pagina.
    """
    completa = pode_ver_dados_sensiveis(usuario)
    return [FichaAluno(aluno, completa) for aluno in alunos]


def serializar(aluno: Aluno, usuario=None) -> dict[str, Any]:
    """Aluno em ``dict``, ja filtrado pela permissao do usuario.

    Usado pela API e por qualquer exportacao. Aqui os campos protegidos sao
    **omitidos**, nao zerados: um ``"cpf": null`` no JSON informa que o campo
    existe e que o usuario nao tem acesso — enquanto a ausencia nao informa
    nada.
    """
    excluir = None if pode_ver_dados_sensiveis(usuario) else Aluno.CAMPOS_SENSIVEIS
    return aluno.para_dicionario(excluir=excluir)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def consulta_base():
    """Query base de alunos nao excluidos logicamente."""
    return db.session.query(Aluno).filter(Aluno.excluido_em.is_(None))


def buscar(aluno_id: int | str | None) -> Aluno:
    """Recupera um aluno ativo pelo id.

    Raises:
        RegistroNaoEncontrado: id invalido, inexistente ou excluido.
    """
    aluno = Aluno.buscar_por_id(aluno_id)
    if aluno is None or aluno.esta_excluido:
        raise RegistroNaoEncontrado("Aluno nao encontrado.")
    return aluno


def listar(
    termo: str | None = None,
    situacao: str | None = None,
    turma_id: int | None = None,
    ano_letivo_id: int | None = None,
    somente_sem_turma: bool = False,
):
    """Monta a consulta de listagem com os filtros da tela.

    Retorna a *query* (nao a lista) para que a rota aplique ordenacao e
    paginacao — o banco continua sendo quem descarta as linhas.
    """
    consulta = consulta_base()

    if termo:
        # A busca usa o campo normalizado (sem acentos, minusculo), que e
        # indexado: "jose" encontra "Jose" sem varredura completa da tabela.
        alvo = f"%{remover_acentos(termo)}%"
        digitos = apenas_digitos(termo)

        filtros = [
            Aluno.nome_normalizado.like(alvo),
            Aluno.codigo.like(f"%{termo}%"),
        ]
        if digitos:
            filtros.append(Aluno.cpf.like(f"%{digitos}%"))

        consulta = consulta.filter(or_(*filtros))

    if situacao:
        consulta = consulta.filter(Aluno.situacao == situacao)

    if turma_id or somente_sem_turma or ano_letivo_id:
        subconsulta = db.session.query(Matricula.aluno_id).filter(
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        if turma_id:
            subconsulta = subconsulta.filter(Matricula.turma_id == turma_id)
        if ano_letivo_id:
            subconsulta = subconsulta.filter(
                Matricula.ano_letivo_id == ano_letivo_id
            )

        if somente_sem_turma:
            consulta = consulta.filter(Aluno.id.notin_(subconsulta))
        else:
            consulta = consulta.filter(Aluno.id.in_(subconsulta))

    return consulta


def buscar_por_cpf(cpf: str | None) -> Aluno | None:
    """Localiza um aluno pelo CPF (somente digitos)."""
    digitos = apenas_digitos(cpf)
    if len(digitos) != 11:
        return None
    return consulta_base().filter(Aluno.cpf == digitos).first()


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------
def _validar_cpf_unico(cpf: str | None, aluno_id: int | None = None) -> None:
    """Impede CPF duplicado entre alunos e valida os digitos verificadores."""
    digitos = apenas_digitos(cpf)
    if not digitos:
        return

    if not cpf_valido(digitos):
        raise ErroValidacao(
            "CPF invalido.", erros_por_campo={"cpf": ["Confira os digitos informados."]}
        )

    consulta = consulta_base().filter(Aluno.cpf == digitos)
    if aluno_id:
        consulta = consulta.filter(Aluno.id != aluno_id)

    existente = consulta.first()
    if existente:
        raise ErroConflito(
            f"O CPF informado ja pertence ao aluno {existente.nome_completo} "
            f"(codigo {existente.codigo})."
        )


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def criar(dados: dict[str, Any], usuario_id: int | None = None) -> Aluno:
    """Cadastra um novo aluno.

    O codigo (RA) e gerado pelo sistema e nunca vem do formulario.
    """
    _validar_cpf_unico(dados.get("cpf"))

    aluno = Aluno()
    aluno.atualizar_campos(**dados)
    aluno.codigo = Aluno.gerar_codigo()

    db.session.add(aluno)
    _confirmar("Falha ao cadastrar aluno")

    auditoria_service.registrar_criacao(
        "Aluno",
        aluno.id,
        f"Aluno cadastrado: {aluno.nome_completo} ({aluno.codigo})",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return aluno


def atualizar(
    aluno: Aluno, dados: dict[str, Any], usuario_id: int | None = None
) -> Aluno:
    """Atualiza um aluno existente registrando o que mudou."""
    _validar_cpf_unico(dados.get("cpf"), aluno_id=aluno.id)

    antes = aluno.para_dicionario()
    aluno.atualizar_campos(**dados)
    depois = aluno.para_dicionario()

    alteracoes = auditoria_service.calcular_alteracoes(antes, depois)
    if not alteracoes:
        return aluno

    _confirmar("Falha ao atualizar aluno")

    auditoria_service.registrar_atualizacao(
        "Aluno",
        aluno.id,
        f"Aluno atualizado: {aluno.nome_completo} ({aluno.codigo})",
        alteracoes,
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return aluno


def excluir(aluno: Aluno, usuario_id: int | None = None) -> None:
    """Exclui logicamente o aluno.

    Nunca ha remocao fisica: a escola tem obrigacao legal de preservar o
    historico escolar, e um aluno com matricula ativa nao pode sequer ser
    inativado sem antes encerrar a matricula.
    """
    matricula_ativa = (
        db.session.query(Matricula)
        .filter(
            Matricula.aluno_id == aluno.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .first()
    )
    if matricula_ativa:
        raise ErroRegraNegocio(
            "Este aluno possui matricula ativa. Cancele ou transfira a "
            "matricula antes de excluir o cadastro."
        )

    aluno.excluir(usuario_id)
    aluno.situacao = SituacaoCadastro.INATIVO

    _confirmar("Falha ao excluir aluno")

    auditoria_service.registrar_exclusao(
        "Aluno",
        aluno.id,
        f"Aluno excluido: {aluno.nome_completo} ({aluno.codigo})",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def restaurar(aluno: Aluno) -> Aluno:
    """Desfaz a exclusao logica de um aluno."""
    aluno.restaurar()
    aluno.situacao = SituacaoCadastro.ATIVO
    _confirmar("Falha ao restaurar aluno")

    auditoria_service.registrar_atualizacao(
        "Aluno", aluno.id, f"Aluno restaurado: {aluno.nome_completo}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return aluno


# ---------------------------------------------------------------------------
# Vinculo com responsaveis
# ---------------------------------------------------------------------------
def vincular_responsavel(
    aluno: Aluno,
    responsavel_id: int,
    parentesco: Parentesco | str,
    responsavel_legal: bool = True,
    responsavel_financeiro: bool = False,
    autorizado_buscar: bool = True,
    ordem_contato: int = 1,
) -> AlunoResponsavel:
    """Cria (ou atualiza) o vinculo entre um aluno e um responsavel."""
    responsavel = db.session.get(Responsavel, responsavel_id)
    if responsavel is None or responsavel.esta_excluido:
        raise RegistroNaoEncontrado("Responsavel nao encontrado.")

    vinculo = (
        db.session.query(AlunoResponsavel)
        .filter(
            AlunoResponsavel.aluno_id == aluno.id,
            AlunoResponsavel.responsavel_id == responsavel_id,
        )
        .first()
    )

    if vinculo is None:
        vinculo = AlunoResponsavel(aluno_id=aluno.id, responsavel_id=responsavel_id)
        db.session.add(vinculo)

    vinculo.parentesco = (
        parentesco if isinstance(parentesco, Parentesco)
        else Parentesco.de_valor(parentesco) or Parentesco.OUTRO
    )
    vinculo.responsavel_legal = responsavel_legal
    vinculo.responsavel_financeiro = responsavel_financeiro
    vinculo.autorizado_buscar = autorizado_buscar
    vinculo.ordem_contato = max(1, min(int(ordem_contato or 1), 10))

    # Apenas um responsavel financeiro por aluno: a cobranca precisa de um
    # unico destinatario inequivoco.
    if responsavel_financeiro:
        db.session.query(AlunoResponsavel).filter(
            AlunoResponsavel.aluno_id == aluno.id,
            AlunoResponsavel.responsavel_id != responsavel_id,
        ).update({"responsavel_financeiro": False}, synchronize_session=False)

    _confirmar("Falha ao vincular responsavel")

    auditoria_service.registrar_atualizacao(
        "Aluno",
        aluno.id,
        f"Responsavel vinculado a {aluno.nome_completo}: "
        f"{responsavel.nome_completo} ({vinculo.parentesco.rotulo})",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return vinculo


def desvincular_responsavel(aluno: Aluno, responsavel_id: int) -> None:
    """Remove o vinculo entre aluno e responsavel."""
    vinculo = (
        db.session.query(AlunoResponsavel)
        .filter(
            AlunoResponsavel.aluno_id == aluno.id,
            AlunoResponsavel.responsavel_id == responsavel_id,
        )
        .first()
    )
    if vinculo is None:
        raise RegistroNaoEncontrado("Vinculo nao encontrado.")

    # Todo aluno menor de idade precisa de ao menos um responsavel legal
    # cadastrado — exigencia do ECA e da propria rotina da escola.
    restantes = (
        db.session.query(AlunoResponsavel)
        .filter(
            AlunoResponsavel.aluno_id == aluno.id,
            AlunoResponsavel.id != vinculo.id,
            AlunoResponsavel.responsavel_legal.is_(True),
        )
        .count()
    )
    idade = aluno.idade
    if vinculo.responsavel_legal and restantes == 0 and (idade is None or idade < 18):
        raise ErroRegraNegocio(
            "Este e o unico responsavel legal do aluno. Vincule outro "
            "responsavel antes de remover este."
        )

    nome_responsavel = (
        vinculo.responsavel.nome_completo if vinculo.responsavel else "?"
    )
    db.session.delete(vinculo)
    _confirmar("Falha ao desvincular responsavel")

    auditoria_service.registrar_atualizacao(
        "Aluno",
        aluno.id,
        f"Responsavel desvinculado de {aluno.nome_completo}: {nome_responsavel}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


# ---------------------------------------------------------------------------
# Conta de acesso
# ---------------------------------------------------------------------------
def vincular_usuario(aluno: Aluno, usuario: Usuario) -> Aluno:
    """Associa uma conta de acesso ao aluno."""
    if usuario.aluno and usuario.aluno.id != aluno.id:
        raise ErroConflito(
            "Esta conta de acesso ja esta vinculada a outro aluno."
        )

    aluno.usuario_id = usuario.id
    _confirmar("Falha ao vincular conta de acesso")

    auditoria_service.registrar_atualizacao(
        "Aluno",
        aluno.id,
        f"Conta de acesso vinculada ao aluno {aluno.nome_completo}: {usuario.email}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return aluno


# ---------------------------------------------------------------------------
# Estatisticas da ficha
# ---------------------------------------------------------------------------
def resumo_academico(aluno: Aluno) -> dict[str, Any]:
    """Dados agregados exibidos na ficha do aluno."""
    from sqlalchemy import func

    from app.models.enums import SituacaoPresenca
    from app.models.frequencia import Frequencia

    matricula = aluno.matricula_atual
    if matricula is None:
        return {
            "matricula": None,
            "total_matriculas": len(aluno.matriculas),
        }

    total_aulas = (
        db.session.query(func.count(Frequencia.id))
        .filter(Frequencia.matricula_id == matricula.id)
        .scalar()
        or 0
    )
    total_faltas = (
        db.session.query(func.count(Frequencia.id))
        .filter(
            Frequencia.matricula_id == matricula.id,
            Frequencia.situacao == SituacaoPresenca.FALTA,
        )
        .scalar()
        or 0
    )

    return {
        "matricula": matricula,
        "turma": matricula.turma,
        "total_aulas": total_aulas,
        "total_faltas": total_faltas,
        "percentual_frequencia": (
            round((total_aulas - total_faltas) / total_aulas * 100, 1)
            if total_aulas
            else None
        ),
        "total_matriculas": len(aluno.matriculas),
    }


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def _confirmar(mensagem: str, propagar: bool = True) -> None:
    """Confirma a transacao traduzindo falhas em excecoes de dominio."""
    from flask import current_app

    try:
        db.session.commit()
    except IntegrityError as erro:
        db.session.rollback()
        current_app.logger.warning("%s (integridade): %s", mensagem, erro)
        if propagar:
            raise ErroConflito(
                "Ja existe um registro com estes dados. Verifique CPF e codigo."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
