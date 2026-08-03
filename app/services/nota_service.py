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

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from flask import has_request_context
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.avaliacao import Avaliacao, Nota, ResultadoDisciplina
from app.models.enums import (
    PapelUsuario,
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
    ErroPermissao,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)
from app.utils.decoradores import pode_lancar_em_vinculo

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


def matriculas_da_turma(
    turma_id: int, incluir_inativas: bool = False
) -> list[Matricula]:
    """Matriculas da turma em ordem alfabetica.

    Args:
        incluir_inativas: inclui transferidos, trancados e concluidos.

    O padrao continua sendo apenas as ativas — e o que interessa para lancar
    nota e fazer chamada. Mas um aluno transferido em outubro precisa de
    boletim parcial e de correcao de nota; sem esta opcao, ele ficava
    inalcancavel pelos fluxos de historico.
    """
    consulta = (
        db.session.query(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .filter(
            Matricula.turma_id == turma_id,
            Matricula.excluido_em.is_(None),
        )
    )

    if not incluir_inativas:
        consulta = consulta.filter(Matricula.situacao == SituacaoMatricula.ATIVA)

    return consulta.order_by(Aluno.nome_normalizado).all()


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


def _garantir_periodo_aberto(
    avaliacao: Avaliacao, permitir_encerrado: bool = False
) -> bool:
    """Bloqueia alteracoes em periodo ou ano letivo encerrado.

    Chamada por **toda** operacao que altera resultado — lancar nota, editar,
    excluir ou publicar avaliacao. Antes, a trava existia apenas na criacao
    da avaliacao: o periodo fechava, o boletim saia, o aluno era reprovado e
    o professor ainda conseguia abrir a grade e mudar a nota.

    Args:
        permitir_encerrado: Autoriza a alteracao excepcional. Reservado a
            direcao e administracao (conselho de classe, correcao de erro
            apurado depois do fechamento).

    Returns:
        ``True`` quando o periodo estava encerrado e a alteracao foi liberada
        excepcionalmente — sinal para o chamador registrar a auditoria
        reforcada.

    Raises:
        ErroRegraNegocio: periodo ou ano encerrado, sem autorizacao especial.
        ErroPermissao: reabertura solicitada por quem nao pode reabrir.
    """
    periodo = avaliacao.periodo
    vinculo = avaliacao.turma_disciplina
    turma = vinculo.turma if vinculo else None
    ano_letivo = turma.ano_letivo if turma else None

    motivos: list[str] = []
    if periodo is not None and periodo.encerrado:
        motivos.append(f"o periodo '{periodo.nome}' esta encerrado")
    if ano_letivo is not None and not ano_letivo.aceita_lancamentos:
        motivos.append(f"o ano letivo de {ano_letivo.ano} nao esta em andamento")

    if not motivos:
        return False

    if not permitir_encerrado:
        raise ErroRegraNegocio(
            f"Nao e possivel alterar: {' e '.join(motivos)}. "
            "A reabertura so pode ser feita pela direcao."
        )

    # A excecao existe, mas nao e livre: so direcao e administracao reabrem.
    if has_request_context() and current_user and current_user.is_authenticated:
        if not current_user.tem_papel(
            PapelUsuario.ADMINISTRADOR, PapelUsuario.DIRECAO
        ):
            raise ErroPermissao(
                "Apenas a direcao pode alterar lancamentos de um periodo "
                "encerrado."
            )

    return True


def atualizar_avaliacao(
    avaliacao: Avaliacao,
    dados: dict[str, Any],
    permitir_periodo_encerrado: bool = False,
) -> Avaliacao:
    """Atualiza os dados de uma avaliacao."""
    _garantir_periodo_aberto(avaliacao, permitir_periodo_encerrado)

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


def excluir_avaliacao(
    avaliacao: Avaliacao, permitir_periodo_encerrado: bool = False
) -> None:
    """Exclui a avaliacao e todas as notas associadas.

    Bloqueada quando ja ha notas lancadas: apagar notas de uma turma inteira
    e irreversivel e nunca deve acontecer por um clique acidental.
    """
    _garantir_periodo_aberto(avaliacao, permitir_periodo_encerrado)

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


def publicar_avaliacao(
    avaliacao: Avaliacao,
    publicar: bool = True,
    permitir_periodo_encerrado: bool = False,
) -> Avaliacao:
    """Libera (ou oculta) as notas para alunos e responsaveis.

    Ocultar uma avaliacao depois do fechamento muda o boletim que a familia
    ja viu — por isso a operacao respeita a mesma trava de periodo.
    """
    _garantir_periodo_aberto(avaliacao, permitir_periodo_encerrado)

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


def _garantir_autorizacao_de_lancamento(avaliacao: Avaliacao) -> None:
    """Verifica, **dentro do service**, quem pode lancar nota.

    A protecao de rota (``@requer_permissao`` + escopo do vinculo) cobre a
    interface web, mas nao a API nem a CLI — que chamam o service direto.
    Deixar a unica guarda no decorador significa que qualquer caminho novo
    nasce desprotegido.

    Quando nao ha contexto de requisicao (comandos ``flask``, seed,
    migracoes de dados), a operacao e considerada confiavel: quem executa
    ali ja tem acesso ao servidor e ao banco.
    """
    if not has_request_context():
        return

    if not pode_lancar_em_vinculo(avaliacao.turma_disciplina):
        raise ErroPermissao(
            "Apenas o professor titular da disciplina (ou a direcao) pode "
            "lancar notas nesta turma."
        )


def salvar_notas(
    avaliacao: Avaliacao,
    valores: dict[int, str],
    ausencias: set[int] | None = None,
    usuario_id: int | None = None,
    permitir_periodo_encerrado: bool = False,
) -> int:
    """Grava as notas de uma avaliacao.

    Args:
        valores: ``{matricula_id: valor_textual}``. Vazio significa
            "nota nao lancada" e limpa o campo.
        ausencias: matriculas marcadas como ausentes na avaliacao.
        permitir_periodo_encerrado: libera alteracao apos o fechamento.
            Restrito a direcao e administracao; gera auditoria reforcada.

    Returns:
        Quantidade de notas efetivamente alteradas.

    Raises:
        ErroPermissao: usuario sem vinculo com a disciplina.
        ErroRegraNegocio: periodo ou ano letivo encerrado.
        ErroValidacao: nota fora do intervalo da avaliacao.
    """
    _garantir_autorizacao_de_lancamento(avaliacao)
    reaberto = _garantir_periodo_aberto(avaliacao, permitir_periodo_encerrado)

    ausencias = ausencias or set()
    permitidas = {m.id for m in matriculas_da_turma(avaliacao.turma_disciplina.turma_id)}

    existentes = {
        n.matricula_id: n
        for n in db.session.query(Nota).filter(Nota.avaliacao_id == avaliacao.id)
    }

    maximo = avaliacao.valor_maximo or Decimal("10")
    alteradas = 0
    problemas: list[str] = []

    # Valores anteriores, para a auditoria de alteracao pos-fechamento: sem
    # eles nao ha como reconstituir o boletim originalmente emitido.
    anteriores: dict[int, str] = {}

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
            anteriores[matricula_id] = registro.valor_exibicao
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
        detalhes: dict[str, Any] = {"alteradas": alteradas}
        descricao = (
            f"Notas lancadas em {avaliacao.nome}: {alteradas} alteracao(oes)"
        )

        if reaberto:
            # Alteracao apos o fechamento muda um boletim ja emitido. O log
            # precisa permitir reconstituir o que foi trocado, por quem e a
            # partir de qual valor.
            descricao = (
                f"ALTERACAO EM PERIODO ENCERRADO — {avaliacao.nome}: "
                f"{alteradas} nota(s) modificada(s)"
            )
            detalhes["periodo_encerrado"] = True
            detalhes["valores_anteriores"] = anteriores

        auditoria_service.registrar_atualizacao(
            "Avaliacao", avaliacao.id, descricao, detalhes
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
# Carregamento em lote
# ---------------------------------------------------------------------------
class LoteConsolidacao:
    """Dados de uma turma inteira, carregados de uma vez so.

    Motivo de existir: a consolidacao de fechamento de periodo percorre
    ``aluno x disciplina x periodo``. Consultando sob demanda, uma turma de
    40 alunos com 12 disciplinas e 4 bimestres passa de duas mil idas ao
    banco — e cada uma delas devolve pouquissimas linhas. Com o lote sao
    quatro consultas, independentemente do tamanho da turma.

    O lote e **opcional** em toda a cadeia de calculo: quando ausente, cada
    funcao consulta o banco como sempre fez. Isso mantem barato o caminho de
    uma nota so (abrir o boletim de um aluno) e evita que a otimizacao do
    fechamento contamine o resto do servico.

    Nao guarda nada entre requisicoes: e construido, usado e descartado
    dentro da mesma operacao. Cache de longa duracao sobre nota seria uma
    forma criativa de exibir boletim desatualizado.
    """

    def __init__(self, matricula_ids: Sequence[int]) -> None:
        self.matricula_ids = list(matricula_ids)
        self._notas: dict[tuple[int, int], list[tuple[Nota, Avaliacao]]] = {}
        self._frequencia: dict[tuple[int, int | None], dict[str, Any]] = {}
        self._resultados: dict[tuple[int, int], ResultadoDisciplina] = {}
        self._periodos: dict[int, list[PeriodoLetivo]] = {}
        self._vinculos: dict[int, list[TurmaDisciplina]] = {}
        self._carregar()

    # -- Construcao --------------------------------------------------------
    def _carregar(self) -> None:
        if not self.matricula_ids:
            return

        linhas = (
            db.session.query(Nota, Avaliacao)
            .join(Avaliacao, Nota.avaliacao_id == Avaliacao.id)
            .filter(Nota.matricula_id.in_(self.matricula_ids))
            .all()
        )
        for nota, avaliacao in linhas:
            chave = (nota.matricula_id, avaliacao.turma_disciplina_id)
            self._notas.setdefault(chave, []).append((nota, avaliacao))

        self._frequencia = frequencia_service.apurar_frequencia_em_lote(
            self.matricula_ids
        )

        for resultado in (
            db.session.query(ResultadoDisciplina)
            .filter(ResultadoDisciplina.matricula_id.in_(self.matricula_ids))
            .all()
        ):
            self._resultados[
                (resultado.matricula_id, resultado.turma_disciplina_id)
            ] = resultado

    # -- Consulta ----------------------------------------------------------
    def notas(self, matricula_id: int, vinculo_id: int):
        return self._notas.get((matricula_id, vinculo_id), [])

    def frequencia(
        self, matricula_id: int, vinculo_id: int | None = None
    ) -> dict[str, Any]:
        apuracao = self._frequencia.get((matricula_id, vinculo_id))
        if apuracao is None:
            return frequencia_service.apurar_frequencia_em_lote([matricula_id]).get(
                (matricula_id, vinculo_id),
                {
                    "total_aulas": 0,
                    "total_faltas": 0,
                    "total_presencas": 0,
                    "percentual": None,
                },
            )
        return apuracao

    def resultado(self, matricula_id: int, vinculo_id: int):
        return self._resultados.get((matricula_id, vinculo_id))

    def registrar_resultado(self, resultado: ResultadoDisciplina) -> None:
        """Guarda um resultado recem-criado para nao recarrega-lo depois."""
        self._resultados[
            (resultado.matricula_id, resultado.turma_disciplina_id)
        ] = resultado

    def periodos(self, ano_letivo_id: int) -> list[PeriodoLetivo]:
        """Memoriza os periodos: sao os mesmos para a turma inteira."""
        if ano_letivo_id not in self._periodos:
            self._periodos[ano_letivo_id] = periodos_do_ano(ano_letivo_id)
        return self._periodos[ano_letivo_id]

    def vinculos(self, turma_id: int) -> list[TurmaDisciplina]:
        """Memoriza as disciplinas: idem, iguais para todos os alunos."""
        if turma_id not in self._vinculos:
            self._vinculos[turma_id] = (
                db.session.query(TurmaDisciplina)
                .filter(
                    TurmaDisciplina.turma_id == turma_id,
                    TurmaDisciplina.ativa.is_(True),
                )
                .all()
            )
        return self._vinculos[turma_id]


def _notas_do_vinculo(
    matricula_id: int, vinculo_id: int, lote: LoteConsolidacao | None = None
) -> list[tuple[Nota, Avaliacao]]:
    """Todas as ``(Nota, Avaliacao)`` do aluno em uma disciplina.

    Ponto unico de acesso: com lote, le da memoria; sem lote, consulta o
    banco. Os filtros por periodo e por tipo de avaliacao ficam em Python,
    nos chamadores — assim existe **uma** forma da consulta, e nao duas que
    precisam ser mantidas identicas.
    """
    if lote is not None:
        return lote.notas(matricula_id, vinculo_id)

    return (
        db.session.query(Nota, Avaliacao)
        .join(Avaliacao, Nota.avaliacao_id == Avaliacao.id)
        .filter(
            Nota.matricula_id == matricula_id,
            Avaliacao.turma_disciplina_id == vinculo_id,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Calculo de medias
# ---------------------------------------------------------------------------
def calcular_media_periodo(
    matricula_id: int,
    vinculo_id: int,
    periodo_id: int,
    lote: LoteConsolidacao | None = None,
) -> Decimal | None:
    """Media ponderada do aluno em um periodo.

    Retorna ``None`` quando nenhuma nota foi lancada — diferente de zero,
    que significa desempenho nulo.
    """
    linhas = [
        (nota, avaliacao)
        for nota, avaliacao in _notas_do_vinculo(matricula_id, vinculo_id, lote)
        if avaliacao.periodo_id == periodo_id
        # Nenhuma recuperacao entra na media ponderada: elas substituem o
        # resultado, e nao compoem com ele.
        and not avaliacao.tipo.e_recuperacao
    ]

    soma_pesos = Decimal("0")
    soma_valores = Decimal("0")
    houve_lancamento = False

    for nota, avaliacao in linhas:
        if not nota.foi_lancada:
            continue

        houve_lancamento = True
        peso = Decimal(str(avaliacao.peso or 1))

        # Escala unica em todo o calculo — ver `_normalizar`.
        valor = _normalizar(nota.valor_efetivo, avaliacao) or Decimal("0")

        soma_valores += valor * peso
        soma_pesos += peso

    if not houve_lancamento or soma_pesos == 0:
        return None

    media = soma_valores / soma_pesos

    # A recuperacao do periodo substitui a media quando for maior.
    recuperacao = _nota_recuperacao(matricula_id, vinculo_id, periodo_id, lote)
    if recuperacao is not None and recuperacao > media:
        media = recuperacao

    return _arredondar(media)


def _normalizar(valor: Decimal | None, avaliacao: Avaliacao) -> Decimal | None:
    """Converte a nota para a escala 0-10 usada em todos os calculos.

    Uma avaliacao pode valer 20, 100 ou qualquer outro maximo. Sem esta
    conversao, uma recuperacao cadastrada valendo 100 seria sempre maior que
    a media e substituiria tudo — o aluno "passaria" com 50 de 100, que
    equivale a 5,0.
    """
    if valor is None:
        return None

    maximo = Decimal(str(avaliacao.valor_maximo or 10))
    if maximo <= 0 or maximo == Decimal("10"):
        return _arredondar(valor)

    return _arredondar((Decimal(str(valor)) / maximo) * Decimal("10"))


def _nota_recuperacao(
    matricula_id: int,
    vinculo_id: int,
    periodo_id: int | None = None,
    lote: LoteConsolidacao | None = None,
) -> Decimal | None:
    """Maior nota de recuperacao, normalizada para a escala 0-10.

    Args:
        periodo_id: quando informado, busca a **recuperacao do periodo**
            (``TipoAvaliacao.RECUPERACAO``); quando ausente, busca a
            **recuperacao final** (``RECUPERACAO_FINAL``).

    A distincao existe porque antes o mesmo registro era contado duas vezes:
    a recuperacao do 2o bimestre ja substituia a media daquele periodo e, na
    apuracao anual, reaparecia como recuperacao final, substituindo a media
    do ano inteiro. Um aluno com 4,0 / rec 7,0 / 4,0 / 4,0 terminava com
    7,0 em vez de 4,75.
    """
    tipo = (
        TipoAvaliacao.RECUPERACAO if periodo_id else TipoAvaliacao.RECUPERACAO_FINAL
    )

    candidatas = [
        (nota, avaliacao)
        for nota, avaliacao in _notas_do_vinculo(matricula_id, vinculo_id, lote)
        if avaliacao.tipo is tipo
        and nota.valor is not None
        and (periodo_id is None or avaliacao.periodo_id == periodo_id)
    ]

    # O maximo e calculado apos a normalizacao: comparar valores em escalas
    # diferentes no SQL (`func.max`) daria o resultado errado.
    normalizadas = [
        _normalizar(nota.valor, avaliacao) for nota, avaliacao in candidatas
    ]
    validas = [valor for valor in normalizadas if valor is not None]

    return max(validas) if validas else None


def calcular_resultado_disciplina(
    matricula: Matricula,
    vinculo: TurmaDisciplina,
    lote: LoteConsolidacao | None = None,
    confirmar: bool = True,
) -> ResultadoDisciplina:
    """Consolida medias, frequencia e resultado de um aluno na disciplina.

    O resultado e persistido em ``ResultadoDisciplina`` para que o boletim
    nao precise recalcular tudo a cada abertura de tela, e para congelar a
    apuracao feita segundo as regras vigentes no ano.

    Args:
        lote: dados da turma pre-carregados (ver :class:`LoteConsolidacao`).
        confirmar: quando ``False``, deixa a transacao aberta para quem
            chamou fechar. Usado no fechamento de periodo, onde um commit
            por aluno por disciplina custaria centenas de fsync.
    """
    ano_letivo = matricula.ano_letivo
    periodos = (
        lote.periodos(matricula.ano_letivo_id)
        if lote is not None
        else periodos_do_ano(matricula.ano_letivo_id)
    )

    resultado = (
        lote.resultado(matricula.id, vinculo.id)
        if lote is not None
        else (
            db.session.query(ResultadoDisciplina)
            .filter(
                ResultadoDisciplina.matricula_id == matricula.id,
                ResultadoDisciplina.turma_disciplina_id == vinculo.id,
            )
            .first()
        )
    )
    if resultado is None:
        resultado = ResultadoDisciplina(
            matricula_id=matricula.id, turma_disciplina_id=vinculo.id
        )
        db.session.add(resultado)
        if lote is not None:
            lote.registrar_resultado(resultado)

    # --- Medias por periodo ---
    # Percorre TODOS os periodos do ano. O antigo `periodos[:4]` descartava
    # o quinto em silencio, produzindo media anual errada sem aviso nenhum.
    medias: list[Decimal] = []
    for periodo in periodos:
        media = calcular_media_periodo(matricula.id, vinculo.id, periodo.id, lote)
        resultado.definir_media_periodo(periodo.ordem, media)
        if media is not None:
            medias.append(media)

    resultado.media_anual = (
        _arredondar(sum(medias) / len(medias)) if medias else None
    )

    # --- Recuperacao final ---
    # Sem `periodo_id`, `_nota_recuperacao` busca apenas RECUPERACAO_FINAL:
    # a recuperacao de bimestre ja foi aplicada na media daquele periodo.
    resultado.nota_recuperacao = _nota_recuperacao(
        matricula.id, vinculo.id, lote=lote
    )

    media_final = resultado.media_anual
    if resultado.nota_recuperacao is not None and (
        media_final is None or resultado.nota_recuperacao > media_final
    ):
        media_final = resultado.nota_recuperacao
    resultado.media_final = media_final

    # --- Frequencia ---
    apuracao = (
        lote.frequencia(matricula.id, vinculo.id)
        if lote is not None
        else frequencia_service.apurar_frequencia(matricula.id, vinculo.id)
    )
    resultado.total_aulas = apuracao["total_aulas"]
    resultado.total_faltas = apuracao["total_faltas"]
    resultado.percentual_frequencia = (
        _arredondar(apuracao["percentual"])
        if apuracao["percentual"] is not None
        else None
    )

    # --- Resultado ---
    resultado.resultado = _apurar_resultado(
        resultado,
        ano_letivo,
        total_periodos=len(periodos),
        periodos_lancados=len(medias),
    )

    if confirmar:
        _confirmar("Falha ao consolidar resultado")
    return resultado


def _apurar_resultado(
    resultado: ResultadoDisciplina,
    ano_letivo: AnoLetivo | None,
    total_periodos: int = 0,
    periodos_lancados: int = 0,
) -> ResultadoFinal:
    """Decide o resultado final segundo as regras do ano letivo.

    Ordem das verificacoes:

    1. **Frequencia** — a LDB reprova por falta independentemente da nota, e
       isso vale a qualquer momento do ano: um aluno que ja perdeu 30% das
       aulas em agosto nao "melhora" ate dezembro.
    2. **Ano em andamento** — com periodos ainda por lancar, o resultado e
       CURSANDO. Antes, um 7,0 no 1o bimestre fazia o boletim exibir
       APROVADO de marco a dezembro.
    3. **Media** — comparada com os limites do proprio ano letivo.
    """
    media_aprovacao = Decimal(str(ano_letivo.media_aprovacao if ano_letivo else 6))
    media_recuperacao = Decimal(str(ano_letivo.media_recuperacao if ano_letivo else 4))
    frequencia_minima = Decimal(str(ano_letivo.frequencia_minima if ano_letivo else 75))
    minimo_aulas = (
        ano_letivo.minimo_aulas_para_apurar_falta if ano_letivo else 20
    )

    # --- 1. Frequencia ---
    # O limiar de aulas evita reprovar alguem em marco por duas ausencias.
    # Ele vem do ano letivo: a carga horaria varia entre escolas.
    if (
        resultado.percentual_frequencia is not None
        and resultado.total_aulas >= minimo_aulas
        and Decimal(str(resultado.percentual_frequencia)) < frequencia_minima
    ):
        return ResultadoFinal.REPROVADO_FALTA

    # --- 2. Ainda sem nota ---
    if resultado.media_final is None:
        return ResultadoFinal.CURSANDO

    # --- 3. Ano ainda em andamento ---
    # So faz sentido dizer "aprovado" ou "reprovado" quando todos os periodos
    # tiverem media, ou quando o ano letivo estiver encerrado.
    ano_encerrado = bool(ano_letivo and ano_letivo.esta_encerrado)
    if not ano_encerrado and periodos_lancados < total_periodos:
        return ResultadoFinal.CURSANDO

    # --- 4. Media ---
    media = Decimal(str(resultado.media_final))

    if media >= media_aprovacao:
        return ResultadoFinal.APROVADO
    if media >= media_recuperacao:
        return ResultadoFinal.RECUPERACAO
    return ResultadoFinal.REPROVADO


def consolidar_matricula(
    matricula: Matricula,
    lote: LoteConsolidacao | None = None,
    confirmar: bool = True,
) -> list[ResultadoDisciplina]:
    """Recalcula o resultado do aluno em todas as disciplinas da turma."""
    vinculos = (
        lote.vinculos(matricula.turma_id)
        if lote is not None
        else (
            db.session.query(TurmaDisciplina)
            .filter(
                TurmaDisciplina.turma_id == matricula.turma_id,
                TurmaDisciplina.ativa.is_(True),
            )
            .all()
        )
    )

    resultados = [
        calcular_resultado_disciplina(matricula, vinculo, lote, confirmar=False)
        for vinculo in vinculos
    ]

    # Atualiza a consolidacao anual da propria matricula.
    medias = [
        Decimal(str(r.media_final)) for r in resultados if r.media_final is not None
    ]
    matricula.media_geral = (
        _arredondar(sum(medias) / len(medias)) if medias else None
    )

    apuracao_geral = (
        lote.frequencia(matricula.id)
        if lote is not None
        else frequencia_service.apurar_frequencia(matricula.id)
    )
    matricula.total_faltas = apuracao_geral["total_faltas"]
    matricula.percentual_frequencia = (
        _arredondar(apuracao_geral["percentual"])
        if apuracao_geral["percentual"] is not None
        else None
    )

    if confirmar:
        _confirmar("Falha ao consolidar matricula")
    return resultados


def consolidar_turma(turma: Turma, incluir_inativas: bool = False) -> int:
    """Recalcula os resultados de todos os alunos de uma turma.

    Operacao pesada, executada sob demanda no fechamento de periodo.

    Carrega os dados da turma inteira de uma vez e grava tudo em **um**
    commit. Antes, cada aluno em cada disciplina disparava um commit e
    dezenas de consultas: uma turma de 40 alunos com 12 disciplinas passava
    de 480 transacoes, e a secretaria assistia a barra de progresso por
    minutos. O commit unico tambem torna a operacao atomica — ou a turma
    inteira fecha, ou nada muda, sem deixar metade dos boletins consolidados
    com regras diferentes da outra metade.

    Args:
        incluir_inativas: alcanca tambem transferidos e trancados. Necessario
            no fechamento do ano, quando o historico de quem saiu no meio do
            periodo tambem precisa ficar consolidado.
    """
    matriculas = matriculas_da_turma(turma.id, incluir_inativas)
    lote = LoteConsolidacao([matricula.id for matricula in matriculas])

    for matricula in matriculas:
        consolidar_matricula(matricula, lote, confirmar=False)

    total = len(matriculas)
    _confirmar("Falha ao consolidar a turma")

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
                for p in periodos
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
