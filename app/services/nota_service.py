"""Regras de negocio de avaliacoes, notas e apuracao de resultado.

Regra de calculo adotada
------------------------
**Media do periodo** = media ponderada das avaliacoes do periodo::

    media = soma(nota_i x peso_i) / soma(peso_i)

Avaliacoes do tipo ``RECUPERACAO`` ficam **fora** dessa media: elas
substituem o resultado do periodo quando forem maiores, pratica pedagogica
predominante no ensino brasileiro.

**Media anual** = media aritmetica simples das medias de periodo lancadas.
Se houver recuperacao final, a media final e a maior entre a media anual e a
nota de recuperacao.

**Resultado** considera as duas exigencias legais, nesta ordem:
1. Frequencia minima (LDB: 75%) — reprova por falta mesmo com media alta.
2. Media minima de aprovacao definida no ano letivo.

Os parametros (media de aprovacao, de recuperacao e frequencia minima) vem
do ``AnoLetivo``, e nao de constantes no codigo: cada ano guarda as regras
que valiam na epoca, de modo que uma mudanca futura nao reescreve o
historico ja apurado.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.avaliacao import Avaliacao, Nota, ResultadoDisciplina
from app.models.enums import (
    ResultadoFinal,
    SituacaoMatricula,
    TipoAvaliacao,
)
from app.models.estrutura import AnoLetivo, PeriodoLetivo, Turma, TurmaDisciplina
from app.models.matricula import Matricula
from app.models.pessoas import Aluno
from app.services import auditoria_service, frequencia_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)

#: Duas casas decimais, arredondamento comercial (0,005 -> 0,01).
CASAS = Decimal("0.01")


def _arredondar(valor: Decimal | float | None) -> Decimal | None:
    if valor is None:
        return None
    return Decimal(str(valor)).quantize(CASAS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def buscar_avaliacao(avaliacao_id: int | str | None) -> Avaliacao:
    avaliacao = Avaliacao.buscar_por_id(avaliacao_id)
    if avaliacao is None:
        raise RegistroNaoEncontrado("Avaliacao nao encontrada.")
    return avaliacao


def avaliacoes_do_vinculo(
    vinculo_id: int, periodo_id: int | None = None
) -> list[Avaliacao]:
    """Avaliacoes de uma disciplina, opcionalmente filtradas por periodo."""
    consulta = db.session.query(Avaliacao).filter(
        Avaliacao.turma_disciplina_id == vinculo_id
    )
    if periodo_id:
        consulta = consulta.filter(Avaliacao.periodo_id == periodo_id)

    return consulta.order_by(Avaliacao.periodo_id, Avaliacao.data_aplicacao).all()


def periodos_do_ano(ano_letivo_id: int) -> list[PeriodoLetivo]:
    return (
        db.session.query(PeriodoLetivo)
        .filter(PeriodoLetivo.ano_letivo_id == ano_letivo_id)
        .order_by(PeriodoLetivo.ordem)
        .all()
    )


def matriculas_da_turma(turma_id: int) -> list[Matricula]:
    """Matriculas ativas da turma em ordem alfabetica."""
    return (
        db.session.query(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .filter(
            Matricula.turma_id == turma_id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .order_by(Aluno.nome_normalizado)
        .all()
    )


# ---------------------------------------------------------------------------
# Avaliacoes
# ---------------------------------------------------------------------------
def criar_avaliacao(
    vinculo: TurmaDisciplina,
    periodo_id: int,
    nome: str,
    tipo: TipoAvaliacao | str,
    peso: Decimal | float = 1,
    valor_maximo: Decimal | float = 10,
    data_aplicacao=None,
    descricao: str | None = None,
    usuario_id: int | None = None,
) -> Avaliacao:
    """Cria uma avaliacao e ja prepara as linhas de nota da turma.

    Criar as linhas vazias de imediato permite distinguir "nota nao lancada"
    de "aluno tirou zero" — confundir os dois casos e um erro grave em
    boletim.
    """
    _validar_periodo(periodo_id, vinculo)

    if Decimal(str(peso)) <= 0:
        raise ErroValidacao(
            "O peso da avaliacao deve ser maior que zero.",
            erros_por_campo={"peso": ["Informe um peso positivo."]},
        )

    avaliacao = Avaliacao(
        turma_disciplina_id=vinculo.id,
        periodo_id=periodo_id,
        nome=(nome or "").strip(),
        tipo=tipo if isinstance(tipo, TipoAvaliacao) else TipoAvaliacao.de_valor(tipo)
        or TipoAvaliacao.PROVA,
        peso=Decimal(str(peso)),
        valor_maximo=Decimal(str(valor_maximo)),
        data_aplicacao=data_aplicacao,
        descricao=(descricao or "").strip() or None,
        criada_por_id=usuario_id,
        publicada=False,
    )

    db.session.add(avaliacao)
    db.session.flush()  # precisa do id para criar as notas

    for matricula in matriculas_da_turma(vinculo.turma_id):
        db.session.add(
            Nota(
                avaliacao_id=avaliacao.id,
                matricula_id=matricula.id,
                valor=None,
                ausente=False,
            )
        )

    _confirmar("Falha ao criar avaliacao")

    auditoria_service.registrar_criacao(
        "Avaliacao",
        avaliacao.id,
        f"Avaliacao criada: {avaliacao.nome} - {vinculo.descricao}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return avaliacao


def _validar_periodo(periodo_id: int, vinculo: TurmaDisciplina) -> None:
    """Garante periodo valido, aberto e pertencente ao ano letivo da turma."""
    periodo = db.session.get(PeriodoLetivo, periodo_id)
    if periodo is None:
        raise RegistroNaoEncontrado("Periodo letivo nao encontrado.")

    turma = vinculo.turma
    if turma and periodo.ano_letivo_id != turma.ano_letivo_id:
        raise ErroRegraNegocio(
            "O periodo selecionado pertence a outro ano letivo."
        )

    if periodo.encerrado:
        raise ErroRegraNegocio(
            f"O periodo '{periodo.nome}' esta encerrado e nao aceita novas "
            "avaliacoes."
        )

    ano_letivo = turma.ano_letivo if turma else None
    if ano_letivo and not ano_letivo.aceita_lancamentos:
        raise ErroRegraNegocio(
            f"O ano letivo de {ano_letivo.ano} nao esta em andamento."
        )


def atualizar_avaliacao(avaliacao: Avaliacao, dados: dict[str, Any]) -> Avaliacao:
    """Atualiza os dados de uma avaliacao."""
    antes = avaliacao.para_dicionario()
    avaliacao.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, avaliacao.para_dicionario()
    )
    if not alteracoes:
        return avaliacao

    _confirmar("Falha ao atualizar avaliacao")
    auditoria_service.registrar_atualizacao(
        "Avaliacao", avaliacao.id,
        f"Avaliacao atualizada: {avaliacao.nome}", alteracoes,
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return avaliacao


def excluir_avaliacao(avaliacao: Avaliacao) -> None:
    """Exclui a avaliacao e todas as notas associadas.

    Bloqueada quando ja ha notas lancadas: apagar notas de uma turma inteira
    e irreversivel e nunca deve acontecer por um clique acidental.
    """
    lancadas = avaliacao.total_lancadas()
    if lancadas:
        raise ErroRegraNegocio(
            f"Esta avaliacao ja possui {lancadas} nota(s) lancada(s). "
            "Zere as notas antes de excluir, ou mantenha o registro para "
            "preservar o historico."
        )

    nome = avaliacao.nome
    identificador = avaliacao.id
    db.session.delete(avaliacao)
    _confirmar("Falha ao excluir avaliacao")

    auditoria_service.registrar_exclusao(
        "Avaliacao", identificador, f"Avaliacao excluida: {nome}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def publicar_avaliacao(avaliacao: Avaliacao, publicar: bool = True) -> Avaliacao:
    """Libera (ou oculta) as notas para alunos e responsaveis."""
    avaliacao.publicada = publicar
    _confirmar("Falha ao publicar avaliacao")

    auditoria_service.registrar_atualizacao(
        "Avaliacao",
        avaliacao.id,
        f"Avaliacao {'publicada' if publicar else 'ocultada'}: {avaliacao.nome}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return avaliacao


# ---------------------------------------------------------------------------
# Lancamento de notas
# ---------------------------------------------------------------------------
def preparar_grade(vinculo: TurmaDisciplina, periodo_id: int) -> dict[str, Any]:
    """Monta a grade de lancamento: alunos nas linhas, avaliacoes nas colunas."""
    avaliacoes = avaliacoes_do_vinculo(vinculo.id, periodo_id)
    matriculas = matriculas_da_turma(vinculo.turma_id)

    ids_avaliacoes = [a.id for a in avaliacoes]
    notas_existentes: dict[tuple[int, int], Nota] = {}

    if ids_avaliacoes:
        for nota in (
            db.session.query(Nota)
            .filter(Nota.avaliacao_id.in_(ids_avaliacoes))
            .all()
        ):
            notas_existentes[(nota.avaliacao_id, nota.matricula_id)] = nota

    linhas = []
    for matricula in matriculas:
        celulas = []
        for avaliacao in avaliacoes:
            celulas.append(
                {
                    "avaliacao": avaliacao,
                    "nota": notas_existentes.get((avaliacao.id, matricula.id)),
                }
            )

        linhas.append(
            {
                "matricula": matricula,
                "aluno": matricula.aluno,
                "celulas": celulas,
                "media": calcular_media_periodo(matricula.id, vinculo.id, periodo_id),
            }
        )

    return {"avaliacoes": avaliacoes, "linhas": linhas}


def salvar_notas(
    avaliacao: Avaliacao,
    valores: dict[int, str],
    ausencias: set[int] | None = None,
    usuario_id: int | None = None,
) -> int:
    """Grava as notas de uma avaliacao.

    Args:
        valores: ``{matricula_id: valor_textual}``. Vazio significa
            "nota nao lancada" e limpa o campo.
        ausencias: matriculas marcadas como ausentes na avaliacao.

    Returns:
        Quantidade de notas efetivamente alteradas.
    """
    ausencias = ausencias or set()
    permitidas = {m.id for m in matriculas_da_turma(avaliacao.turma_disciplina.turma_id)}

    existentes = {
        n.matricula_id: n
        for n in db.session.query(Nota).filter(Nota.avaliacao_id == avaliacao.id)
    }

    maximo = avaliacao.valor_maximo or Decimal("10")
    alteradas = 0
    problemas: list[str] = []

    # O campo de nota fica desabilitado quando o aluno e marcado como ausente,
    # e navegadores nao enviam campos desabilitados. Por isso o conjunto a
    # processar e a **uniao** das notas informadas com as ausencias marcadas.
    # Ids fora da turma sao descartados: protege contra POST manipulado.
    alvos = (set(valores) | ausencias) & permitidas

    for matricula_id in alvos:
        texto = valores.get(matricula_id, "")

        registro = existentes.get(matricula_id)
        if registro is None:
            registro = Nota(avaliacao_id=avaliacao.id, matricula_id=matricula_id)
            db.session.add(registro)
            existentes[matricula_id] = registro

        ausente = matricula_id in ausencias
        valor = _converter_nota(texto)

        if valor is not None and (valor < 0 or valor > maximo):
            problemas.append(
                f"Nota {valor} fora do intervalo permitido (0 a {maximo})."
            )
            continue

        if registro.valor != valor or registro.ausente != ausente:
            registro.valor = None if ausente else valor
            registro.ausente = ausente
            registro.alterada_por_id = usuario_id
            if registro.lancada_por_id is None:
                registro.lancada_por_id = usuario_id
            alteradas += 1

    if problemas:
        db.session.rollback()
        raise ErroValidacao(" ".join(dict.fromkeys(problemas)))

    _confirmar("Falha ao salvar notas")

    if alteradas:
        auditoria_service.registrar_atualizacao(
            "Avaliacao",
            avaliacao.id,
            f"Notas lancadas em {avaliacao.nome}: {alteradas} alteracao(oes)",
            {"alteradas": alteradas},
        )
        _confirmar("Falha ao registrar auditoria", propagar=False)

    return alteradas


def _converter_nota(texto: str | None) -> Decimal | None:
    """Converte o texto do formulario em ``Decimal``, aceitando virgula."""
    if texto is None:
        return None

    limpo = str(texto).strip().replace(",", ".")
    if not limpo:
        return None

    try:
        return _arredondar(Decimal(limpo))
    except (ValueError, ArithmeticError):
        raise ErroValidacao(
            f"Valor de nota invalido: '{texto}'. Use apenas numeros."
        ) from None


# ---------------------------------------------------------------------------
# Calculo de medias
# ---------------------------------------------------------------------------
def calcular_media_periodo(
    matricula_id: int, vinculo_id: int, periodo_id: int
) -> Decimal | None:
    """Media ponderada do aluno em um periodo.

    Retorna ``None`` quando nenhuma nota foi lancada — diferente de zero,
    que significa desempenho nulo.
    """
    linhas = (
        db.session.query(Nota, Avaliacao)
        .join(Avaliacao, Nota.avaliacao_id == Avaliacao.id)
        .filter(
            Nota.matricula_id == matricula_id,
            Avaliacao.turma_disciplina_id == vinculo_id,
            Avaliacao.periodo_id == periodo_id,
            Avaliacao.tipo != TipoAvaliacao.RECUPERACAO,
        )
        .all()
    )

    soma_pesos = Decimal("0")
    soma_valores = Decimal("0")
    houve_lancamento = False

    for nota, avaliacao in linhas:
        if not nota.foi_lancada:
            continue

        houve_lancamento = True
        peso = Decimal(str(avaliacao.peso or 1))
        maximo = Decimal(str(avaliacao.valor_maximo or 10))

        # Normaliza para a escala 0-10 quando a avaliacao vale outro maximo
        # (ex.: um trabalho de 20 pontos).
        valor = nota.valor_efetivo
        if maximo and maximo != Decimal("10"):
            valor = (valor / maximo) * Decimal("10")

        soma_valores += valor * peso
        soma_pesos += peso

    if not houve_lancamento or soma_pesos == 0:
        return None

    media = soma_valores / soma_pesos

    # A recuperacao do periodo substitui a media quando for maior.
    recuperacao = _nota_recuperacao(matricula_id, vinculo_id, periodo_id)
    if recuperacao is not None and recuperacao > media:
        media = recuperacao

    return _arredondar(media)


def _nota_recuperacao(
    matricula_id: int, vinculo_id: int, periodo_id: int | None = None
) -> Decimal | None:
    """Maior nota de recuperacao lancada no escopo informado."""
    consulta = (
        db.session.query(func.max(Nota.valor))
        .join(Avaliacao, Nota.avaliacao_id == Avaliacao.id)
        .filter(
            Nota.matricula_id == matricula_id,
            Avaliacao.turma_disciplina_id == vinculo_id,
            Avaliacao.tipo == TipoAvaliacao.RECUPERACAO,
            Nota.valor.isnot(None),
        )
    )
    if periodo_id:
        consulta = consulta.filter(Avaliacao.periodo_id == periodo_id)

    valor = consulta.scalar()
    return _arredondar(valor) if valor is not None else None


def calcular_resultado_disciplina(
    matricula: Matricula, vinculo: TurmaDisciplina
) -> ResultadoDisciplina:
    """Consolida medias, frequencia e resultado de um aluno na disciplina.

    O resultado e persistido em ``ResultadoDisciplina`` para que o boletim
    nao precise recalcular tudo a cada abertura de tela, e para congelar a
    apuracao feita segundo as regras vigentes no ano.
    """
    ano_letivo = matricula.ano_letivo
    periodos = periodos_do_ano(matricula.ano_letivo_id)

    resultado = (
        db.session.query(ResultadoDisciplina)
        .filter(
            ResultadoDisciplina.matricula_id == matricula.id,
            ResultadoDisciplina.turma_disciplina_id == vinculo.id,
        )
        .first()
    )
    if resultado is None:
        resultado = ResultadoDisciplina(
            matricula_id=matricula.id, turma_disciplina_id=vinculo.id
        )
        db.session.add(resultado)

    # --- Medias por periodo ---
    medias: list[Decimal] = []
    for periodo in periodos[:4]:
        media = calcular_media_periodo(matricula.id, vinculo.id, periodo.id)
        resultado.definir_media_periodo(periodo.ordem, media)
        if media is not None:
            medias.append(media)

    resultado.media_anual = (
        _arredondar(sum(medias) / len(medias)) if medias else None
    )

    # --- Recuperacao final ---
    resultado.nota_recuperacao = _nota_recuperacao(matricula.id, vinculo.id)

    media_final = resultado.media_anual
    if resultado.nota_recuperacao is not None:
        if media_final is None or resultado.nota_recuperacao > media_final:
            media_final = resultado.nota_recuperacao
    resultado.media_final = media_final

    # --- Frequencia ---
    apuracao = frequencia_service.apurar_frequencia(matricula.id, vinculo.id)
    resultado.total_aulas = apuracao["total_aulas"]
    resultado.total_faltas = apuracao["total_faltas"]
    resultado.percentual_frequencia = (
        _arredondar(apuracao["percentual"])
        if apuracao["percentual"] is not None
        else None
    )

    # --- Resultado ---
    resultado.resultado = _apurar_resultado(resultado, ano_letivo)

    _confirmar("Falha ao consolidar resultado")
    return resultado


def _apurar_resultado(
    resultado: ResultadoDisciplina, ano_letivo: AnoLetivo | None
) -> ResultadoFinal:
    """Decide o resultado final segundo as regras do ano letivo.

    A frequencia e verificada **antes** da media: a LDB reprova por falta
    independentemente do desempenho academico.
    """
    media_aprovacao = Decimal(str(ano_letivo.media_aprovacao if ano_letivo else 6))
    media_recuperacao = Decimal(str(ano_letivo.media_recuperacao if ano_letivo else 4))
    frequencia_minima = Decimal(str(ano_letivo.frequencia_minima if ano_letivo else 75))

    # Ainda sem nota: o aluno esta cursando.
    if resultado.media_final is None:
        return ResultadoFinal.CURSANDO

    # Reprovacao por falta so e apurada com volume minimo de aulas, para nao
    # reprovar alguem no inicio do ano por causa de duas ausencias.
    if (
        resultado.percentual_frequencia is not None
        and resultado.total_aulas >= 20
        and Decimal(str(resultado.percentual_frequencia)) < frequencia_minima
    ):
        return ResultadoFinal.REPROVADO_FALTA

    media = Decimal(str(resultado.media_final))

    if media >= media_aprovacao:
        return ResultadoFinal.APROVADO
    if media >= media_recuperacao:
        return ResultadoFinal.RECUPERACAO
    return ResultadoFinal.REPROVADO


def consolidar_matricula(matricula: Matricula) -> list[ResultadoDisciplina]:
    """Recalcula o resultado do aluno em todas as disciplinas da turma."""
    vinculos = (
        db.session.query(TurmaDisciplina)
        .filter(
            TurmaDisciplina.turma_id == matricula.turma_id,
            TurmaDisciplina.ativa.is_(True),
        )
        .all()
    )

    resultados = [
        calcular_resultado_disciplina(matricula, vinculo) for vinculo in vinculos
    ]

    # Atualiza a consolidacao anual da propria matricula.
    medias = [
        Decimal(str(r.media_final)) for r in resultados if r.media_final is not None
    ]
    matricula.media_geral = (
        _arredondar(sum(medias) / len(medias)) if medias else None
    )

    apuracao_geral = frequencia_service.apurar_frequencia(matricula.id)
    matricula.total_faltas = apuracao_geral["total_faltas"]
    matricula.percentual_frequencia = (
        _arredondar(apuracao_geral["percentual"])
        if apuracao_geral["percentual"] is not None
        else None
    )

    _confirmar("Falha ao consolidar matricula")
    return resultados


def consolidar_turma(turma: Turma) -> int:
    """Recalcula os resultados de todos os alunos de uma turma.

    Operacao pesada, executada sob demanda no fechamento de periodo.
    """
    total = 0
    for matricula in matriculas_da_turma(turma.id):
        consolidar_matricula(matricula)
        total += 1

    auditoria_service.registrar(
        auditoria_service.AcaoAuditoria.ATUALIZACAO,
        entidade="Turma",
        entidade_id=turma.id,
        descricao=f"Resultados consolidados: {turma.nome_completo} ({total} alunos)",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return total


# ---------------------------------------------------------------------------
# Boletim
# ---------------------------------------------------------------------------
def montar_boletim(matricula: Matricula) -> dict[str, Any]:
    """Monta a estrutura completa do boletim de um aluno."""
    periodos = periodos_do_ano(matricula.ano_letivo_id)

    vinculos = (
        db.session.query(TurmaDisciplina)
        .filter(
            TurmaDisciplina.turma_id == matricula.turma_id,
            TurmaDisciplina.ativa.is_(True),
        )
        .all()
    )

    resultados = {
        r.turma_disciplina_id: r
        for r in db.session.query(ResultadoDisciplina).filter(
            ResultadoDisciplina.matricula_id == matricula.id
        )
    }

    linhas = []
    for vinculo in vinculos:
        resultado = resultados.get(vinculo.id)

        # Sem consolidacao previa, calcula em tempo real para nao exibir uma
        # tela vazia ao usuario.
        medias = (
            resultado.medias_por_periodo()
            if resultado
            else [
                calcular_media_periodo(matricula.id, vinculo.id, p.id)
                for p in periodos[:4]
            ]
        )

        linhas.append(
            {
                "vinculo": vinculo,
                "disciplina": vinculo.disciplina,
                "professor": vinculo.professor,
                "medias": medias,
                "resultado": resultado,
                "media_final": resultado.media_final if resultado else None,
                "frequencia": (
                    resultado.percentual_frequencia if resultado else None
                ),
                "faltas": resultado.total_faltas if resultado else None,
                "situacao": (
                    resultado.resultado if resultado else ResultadoFinal.CURSANDO
                ),
            }
        )

    return {
        "matricula": matricula,
        "aluno": matricula.aluno,
        "turma": matricula.turma,
        "ano_letivo": matricula.ano_letivo,
        "periodos": periodos,
        "linhas": linhas,
        "media_geral": matricula.media_geral,
        "frequencia_geral": matricula.percentual_frequencia,
    }


# ---------------------------------------------------------------------------
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
