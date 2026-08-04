"""Regras de consentimento e base legal (LGPD).

A pergunta que este servico responde e sempre a mesma:

    a escola pode usar este dado deste aluno para esta finalidade?

:func:`pode_tratar` e o unico lugar que decide isso. Todo codigo que for
publicar uma foto, mandar uma campanha ou liberar a saida de um aluno
pergunta aqui — nao le o booleano do cadastro, nem consulta a tabela direto.

Distincao que atravessa o modulo: **nem toda finalidade depende de
consentimento**. Matricula, historico e diario de classe se apoiam em
obrigacao legal e contrato; a escola nao pode parar de emitir historico se a
familia disser nao. Pedir consentimento para isso seria enganoso — daria a
impressao de uma escolha que nao existe. Ver ``FinalidadeTratamento``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import AcaoAuditoria, FinalidadeTratamento
from app.models.lgpd import ConsentimentoLGPD
from app.models.pessoas import Aluno, Responsavel
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)

#: Campos do cadastro do aluno mantidos em sincronia com o registro de
#: consentimento. Existiam antes desta tabela e continuam alimentando a tela
#: de cadastro e os filtros de listagem.
#:
#: A tabela e a fonte da verdade; estes campos sao copia denormalizada,
#: atualizada por :func:`registrar`. Codigo novo pergunta a `pode_tratar()`.
CAMPOS_ESPELHADOS: dict[FinalidadeTratamento, str] = {
    FinalidadeTratamento.USO_DE_IMAGEM: "autoriza_uso_imagem",
    FinalidadeTratamento.SAIDA_DESACOMPANHADA: "autorizado_sair_sozinho",
}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def buscar(consentimento_id: int | str | None) -> ConsentimentoLGPD:
    registro = ConsentimentoLGPD.buscar_por_id(consentimento_id)
    if registro is None:
        raise RegistroNaoEncontrado("Registro de consentimento nao encontrado.")
    return registro


def historico(aluno_id: int) -> list[ConsentimentoLGPD]:
    """Todas as decisoes ja registradas, da mais recente para a mais antiga."""
    return (
        db.session.query(ConsentimentoLGPD)
        .filter(ConsentimentoLGPD.aluno_id == aluno_id)
        .order_by(desc(ConsentimentoLGPD.id))
        .all()
    )


def decisao_vigente(
    aluno_id: int, finalidade: FinalidadeTratamento
) -> ConsentimentoLGPD | None:
    """Ultimo registro desta finalidade, revogado ou nao.

    Devolve o registro mesmo quando ele nega ou foi revogado: quem pergunta
    precisa distinguir "a familia disse nao" de "ninguem perguntou ainda".
    """
    return (
        db.session.query(ConsentimentoLGPD)
        .filter(
            ConsentimentoLGPD.aluno_id == aluno_id,
            ConsentimentoLGPD.finalidade == finalidade,
        )
        .order_by(desc(ConsentimentoLGPD.id))
        .first()
    )


def pode_tratar(aluno_id: int, finalidade: FinalidadeTratamento) -> bool:
    """Decide se a escola pode usar o dado para esta finalidade.

    Finalidade apoiada em obrigacao legal, contrato ou tutela da saude
    dispensa autorizacao — e por isso responde ``True`` mesmo sem registro
    nenhum. Nao e uma brecha: e a lei dizendo que o historico escolar sai
    independentemente de a familia gostar.
    """
    if not finalidade.exige_consentimento:
        return True

    decisao = decisao_vigente(aluno_id, finalidade)
    return bool(decisao and decisao.vigente)


def painel(aluno_id: int) -> list[dict[str, Any]]:
    """Estado de cada finalidade, para a tela do aluno."""
    return [
        {
            "finalidade": finalidade,
            "decisao": decisao_vigente(aluno_id, finalidade),
            "autorizado": pode_tratar(aluno_id, finalidade),
        }
        for finalidade in FinalidadeTratamento
    ]


def pendencias(aluno_id: int) -> list[FinalidadeTratamento]:
    """Finalidades que exigem consentimento e ainda nao foram perguntadas.

    Diferente de "negadas": um "nao" registrado e uma decisao tomada, nao
    uma pendencia. A secretaria precisa saber de quem falta perguntar.
    """
    return [
        finalidade
        for finalidade in FinalidadeTratamento.que_exigem_consentimento()
        if decisao_vigente(aluno_id, finalidade) is None
    ]


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def registrar(
    aluno: Aluno,
    finalidade: FinalidadeTratamento | str,
    concedido: bool,
    responsavel: Responsavel | None = None,
    autor=None,
    documento: str | None = None,
    observacao: str | None = None,
    data_decisao: date | None = None,
) -> ConsentimentoLGPD:
    """Grava uma decisao da familia sobre uma finalidade.

    Nunca sobrescreve: cada decisao e um registro novo, e o anterior vira
    historico. E o que permite provar depois que o consentimento existiu na
    epoca da foto publicada — ver o docstring de ``app/models/lgpd.py``.

    Args:
        responsavel: quem decidiu. Obrigatorio quando a finalidade depende
            de consentimento: "alguem autorizou" nao prova nada.
        autor: usuario da escola que registrou (para a auditoria).
    """
    finalidade = _resolver_finalidade(finalidade)

    if finalidade.exige_consentimento and responsavel is None:
        raise ErroValidacao(
            "Informe qual responsavel tomou a decisao.",
            erros_por_campo={
                "responsavel_id": [
                    "Consentimento sem responsavel identificado nao tem "
                    "valor probatorio."
                ]
            },
        )

    if responsavel is not None and not responsavel.e_responsavel_por(aluno.id):
        raise ErroRegraNegocio(
            f"{responsavel.nome_completo} nao consta como responsavel deste "
            "aluno."
        )

    registro = ConsentimentoLGPD(
        aluno_id=aluno.id,
        finalidade=finalidade,
        base_legal=finalidade.base_legal,
        concedido=bool(concedido),
        data_decisao=data_decisao or date.today(),
        responsavel_id=responsavel.id if responsavel else None,
        responsavel_nome=responsavel.nome_completo if responsavel else None,
        registrado_por_id=getattr(autor, "id", None),
        documento=(documento or "").strip() or None,
        observacao=(observacao or "").strip() or None,
    )
    db.session.add(registro)

    _espelhar_no_cadastro(aluno, finalidade, registro.vigente)
    _confirmar("Falha ao registrar consentimento")

    auditoria_service.registrar(
        AcaoAuditoria.CONSENTIMENTO,
        entidade="Aluno",
        entidade_id=aluno.id,
        descricao=(
            f"{finalidade.rotulo}: "
            f"{'concedido' if registro.concedido else 'negado'} por "
            f"{registro.nome_de_quem_decidiu}"
        ),
        detalhes={
            "finalidade": finalidade.value,
            "base_legal": finalidade.base_legal.value,
            "concedido": registro.concedido,
            "documento": registro.documento,
        },
        usuario_id=getattr(autor, "id", None),
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return registro


def revogar(consentimento: ConsentimentoLGPD, autor=None) -> ConsentimentoLGPD:
    """Encerra um consentimento vigente.

    So vale para finalidade que se apoia em consentimento. Revogar uma
    finalidade de obrigacao legal nao faria efeito nenhum — a escola
    continuaria obrigada a tratar o dado — e registrar essa revogacao daria
    a familia a impressao falsa de que o tratamento parou.
    """
    if not consentimento.finalidade.revogavel:
        raise ErroRegraNegocio(
            f"'{consentimento.finalidade.rotulo}' se apoia em "
            f"{consentimento.base_legal.rotulo} e nao depende de "
            "consentimento — nao ha o que revogar."
        )

    if consentimento.revogado_em is not None:
        raise ErroRegraNegocio("Este consentimento ja havia sido revogado.")

    consentimento.revogar()

    aluno = consentimento.aluno
    if aluno is not None:
        _espelhar_no_cadastro(aluno, consentimento.finalidade, False)

    _confirmar("Falha ao revogar consentimento")

    auditoria_service.registrar(
        AcaoAuditoria.CONSENTIMENTO,
        entidade="Aluno",
        entidade_id=consentimento.aluno_id,
        descricao=f"{consentimento.finalidade.rotulo}: consentimento revogado",
        detalhes={"finalidade": consentimento.finalidade.value},
        usuario_id=getattr(autor, "id", None),
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return consentimento


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def _resolver_finalidade(valor: FinalidadeTratamento | str) -> FinalidadeTratamento:
    if isinstance(valor, FinalidadeTratamento):
        return valor

    finalidade = FinalidadeTratamento.de_valor(valor)
    if finalidade is None:
        raise ErroValidacao(f"Finalidade desconhecida: '{valor}'.")
    return finalidade


def _espelhar_no_cadastro(
    aluno: Aluno, finalidade: FinalidadeTratamento, autorizado: bool
) -> None:
    """Mantem o booleano do cadastro em sincronia com o registro.

    Duas fontes de verdade divergem — foi o que a auditoria encontrou em
    outros pontos deste sistema. Aqui elas nao divergem porque so este
    servico escreve nas duas, e o booleano nunca e consultado para decidir:
    quem decide e `pode_tratar()`.
    """
    campo = CAMPOS_ESPELHADOS.get(finalidade)
    if campo is not None:
        setattr(aluno, campo, autorizado)


def _confirmar(mensagem: str, propagar: bool = True) -> None:
    from flask import current_app

    try:
        db.session.commit()
    except IntegrityError as erro:
        db.session.rollback()
        current_app.logger.warning("%s (integridade): %s", mensagem, erro)
        if propagar:
            raise ErroConflito("Ja existe um registro com estes dados.") from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
