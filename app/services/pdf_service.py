"""Geracao de documentos em PDF (boletins, declaracoes, listagens).

Escolha da biblioteca
---------------------
Usamos **ReportLab**, que e Python puro. A alternativa mais elegante seria
WeasyPrint (HTML/CSS -> PDF), mas ela depende do GTK, cuja instalacao no
Windows e um obstaculo real para o servidor de uma escola. ReportLab roda em
qualquer lugar onde o Python roda.

Os documentos sao gerados em memoria (``BytesIO``) e enviados direto ao
navegador: nada e gravado em disco, o que evita acumulo de arquivos
temporarios com dados de alunos no servidor.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from flask import Response, current_app
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.excecoes import ErroDominio

# ---------------------------------------------------------------------------
# Identidade visual dos documentos
# ---------------------------------------------------------------------------
COR_PRIMARIA = colors.HexColor("#1a56db")
COR_TEXTO = colors.HexColor("#111827")
COR_SUAVE = colors.HexColor("#4b5563")
COR_BORDA = colors.HexColor("#d1d5db")
COR_FUNDO_CABECALHO = colors.HexColor("#f3f4f6")
COR_SUCESSO = colors.HexColor("#057a55")
COR_PERIGO = colors.HexColor("#c81e1e")
COR_ALERTA = colors.HexColor("#c27803")


def _estilos() -> dict[str, ParagraphStyle]:
    """Folha de estilos usada em todos os documentos."""
    base = getSampleStyleSheet()

    return {
        "titulo": ParagraphStyle(
            "SGETitulo",
            parent=base["Title"],
            fontSize=15,
            leading=19,
            textColor=COR_PRIMARIA,
            spaceAfter=2,
            alignment=TA_CENTER,
        ),
        "subtitulo": ParagraphStyle(
            "SGESubtitulo",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            textColor=COR_SUAVE,
            alignment=TA_CENTER,
        ),
        "secao": ParagraphStyle(
            "SGESecao",
            parent=base["Heading2"],
            fontSize=11,
            leading=14,
            textColor=COR_PRIMARIA,
            spaceBefore=10,
            spaceAfter=5,
        ),
        "normal": ParagraphStyle(
            "SGENormal",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=COR_TEXTO,
            alignment=TA_LEFT,
        ),
        "pequeno": ParagraphStyle(
            "SGEPequeno",
            parent=base["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=COR_SUAVE,
        ),
        "rodape": ParagraphStyle(
            "SGERodape",
            parent=base["Normal"],
            fontSize=7,
            leading=9,
            textColor=COR_SUAVE,
            alignment=TA_CENTER,
        ),
    }


def _dados_escola() -> dict[str, str]:
    """Le os dados institucionais para o cabecalho dos documentos."""
    try:
        from app.models.sistema import ConfiguracaoEscola

        escola = ConfiguracaoEscola.obter()
        return {
            "nome": escola.nome_exibicao or "Escola",
            "endereco": escola.endereco_completo or "",
            "contato": " | ".join(
                filtro
                for filtro in (escola.telefone, escola.email, escola.site)
                if filtro
            ),
            "codigo_inep": escola.codigo_inep or "",
            "diretor": escola.diretor or "",
            "secretario": escola.secretario or "",
        }
    except Exception:  # noqa: BLE001 - documento nao pode falhar por config
        return {
            "nome": "Escola",
            "endereco": "",
            "contato": "",
            "codigo_inep": "",
            "diretor": "",
            "secretario": "",
        }


def _cabecalho(estilos, titulo: str) -> list:
    """Bloco de cabecalho institucional repetido em todos os documentos."""
    escola = _dados_escola()
    elementos: list = [
        Paragraph(escola["nome"], estilos["titulo"]),
    ]

    linha_contato = " &bull; ".join(
        parte for parte in (escola["endereco"], escola["contato"]) if parte
    )
    if linha_contato:
        elementos.append(Paragraph(linha_contato, estilos["subtitulo"]))

    if escola["codigo_inep"]:
        elementos.append(
            Paragraph(f"Codigo INEP: {escola['codigo_inep']}", estilos["subtitulo"])
        )

    elementos.append(Spacer(1, 0.35 * cm))

    # Faixa com o titulo do documento.
    faixa = Table([[titulo.upper()]], colWidths=[None])
    faixa.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COR_PRIMARIA),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elementos.append(faixa)
    elementos.append(Spacer(1, 0.4 * cm))

    return elementos


def _rodape(canvas, documento) -> None:
    """Numero de pagina e carimbo de emissao, desenhados em cada pagina."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(COR_SUAVE)

    largura, _ = documento.pagesize
    emissao = date.today().strftime("%d/%m/%Y")

    canvas.drawString(
        2 * cm, 1.2 * cm, f"Emitido em {emissao} pelo SGE - Sistema de Gestao Escolar"
    )
    canvas.drawRightString(largura - 2 * cm, 1.2 * cm, f"Pagina {documento.page}")

    canvas.setStrokeColor(COR_BORDA)
    canvas.line(2 * cm, 1.5 * cm, largura - 2 * cm, 1.5 * cm)

    canvas.restoreState()


def _formatar_nota(valor) -> str:
    """Nota com virgula decimal; travessao quando ausente."""
    if valor is None:
        return "—"
    return f"{float(valor):.1f}".replace(".", ",")


def _cor_resultado(resultado) -> colors.Color:
    valor = getattr(resultado, "value", str(resultado or ""))
    if valor in ("aprovado", "aprovado_conselho"):
        return COR_SUCESSO
    if valor in ("reprovado", "reprovado_falta"):
        return COR_PERIGO
    if valor == "recuperacao":
        return COR_ALERTA
    return COR_SUAVE


# ---------------------------------------------------------------------------
# Boletim
# ---------------------------------------------------------------------------
def gerar_boletim(dados: dict[str, Any]) -> BytesIO:
    """Gera o boletim individual de um aluno."""
    buffer = BytesIO()
    estilos = _estilos()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
        title=f"Boletim - {dados['aluno'].nome_exibicao}",
        author="SGE",
    )

    elementos = _montar_boletim(dados, estilos)

    try:
        documento.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    except Exception as erro:  # noqa: BLE001
        current_app.logger.error("Falha ao gerar boletim: %s", erro)
        raise ErroDominio("Nao foi possivel gerar o boletim em PDF.") from erro

    buffer.seek(0)
    return buffer


def gerar_boletins_turma(turma, boletins: list[dict[str, Any]]) -> BytesIO:
    """Gera os boletins de toda a turma em um unico arquivo."""
    buffer = BytesIO()
    estilos = _estilos()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
        title=f"Boletins - {turma.nome_completo}",
        author="SGE",
    )

    elementos: list = []
    for indice, dados in enumerate(boletins):
        if indice:
            elementos.append(PageBreak())
        elementos.extend(_montar_boletim(dados, estilos))

    try:
        documento.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    except Exception as erro:  # noqa: BLE001
        current_app.logger.error("Falha ao gerar boletins da turma: %s", erro)
        raise ErroDominio("Nao foi possivel gerar os boletins em PDF.") from erro

    buffer.seek(0)
    return buffer


def _montar_boletim(dados: dict[str, Any], estilos) -> list:
    """Monta os elementos de um boletim individual."""
    aluno = dados["aluno"]
    matricula = dados["matricula"]
    turma = dados["turma"]
    ano_letivo = dados["ano_letivo"]
    # Todos os periodos entram no boletim. Truncar em quatro escondia o
    # ultimo periodo de escolas que trabalham com cinco ou mais.
    periodos = dados["periodos"]

    elementos = _cabecalho(estilos, "Boletim Escolar")

    # --- Identificacao do aluno ---
    identificacao = [
        ["Aluno:", aluno.nome_exibicao, "Codigo:", aluno.codigo],
        [
            "Turma:",
            turma.nome_completo if turma else "—",
            "Matricula:",
            matricula.numero,
        ],
        [
            "Ano letivo:",
            str(ano_letivo.ano) if ano_letivo else "—",
            "Situacao:",
            matricula.situacao.rotulo,
        ],
    ]

    tabela_identificacao = Table(
        identificacao, colWidths=[2.2 * cm, 7.3 * cm, 2.2 * cm, 5.3 * cm]
    )
    tabela_identificacao.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), COR_TEXTO),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOX", (0, 0), (-1, -1), 0.5, COR_BORDA),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, COR_BORDA),
                ("BACKGROUND", (0, 0), (0, -1), COR_FUNDO_CABECALHO),
                ("BACKGROUND", (2, 0), (2, -1), COR_FUNDO_CABECALHO),
            ]
        )
    )
    elementos.append(tabela_identificacao)
    elementos.append(Spacer(1, 0.45 * cm))

    # --- Tabela de notas ---
    cabecalho = ["Disciplina"]
    cabecalho += [p.nome.replace("Bimestre", "Bim").replace("Trimestre", "Tri")
                  for p in periodos]
    cabecalho += ["Media", "Faltas", "Freq.", "Situacao"]

    linhas = [cabecalho]
    estilo_celula = []

    for indice, linha in enumerate(dados["linhas"], start=1):
        medias = list(linha["medias"])[: len(periodos)]
        while len(medias) < len(periodos):
            medias.append(None)

        situacao = linha["situacao"]
        registro = [
            linha["disciplina"].nome if linha["disciplina"] else "—",
            *[_formatar_nota(m) for m in medias],
            _formatar_nota(linha["media_final"]),
            str(linha["faltas"]) if linha["faltas"] is not None else "—",
            (
                f"{float(linha['frequencia']):.0f}%".replace(".", ",")
                if linha["frequencia"] is not None
                else "—"
            ),
            getattr(situacao, "rotulo", "—"),
        ]
        linhas.append(registro)

        # Cor da coluna de situacao conforme o resultado apurado.
        estilo_celula.append(
            ("TEXTCOLOR", (-1, indice), (-1, indice), _cor_resultado(situacao))
        )

        # Destaca a media final quando abaixo do minimo de aprovacao.
        minimo = float(ano_letivo.media_aprovacao) if ano_letivo else 6.0
        if linha["media_final"] is not None and float(linha["media_final"]) < minimo:
            estilo_celula.append(
                ("TEXTCOLOR", (-4, indice), (-4, indice), COR_PERIGO)
            )

    # Larguras calculadas a partir do espaco util da pagina (A4 retrato menos
    # as margens de 2 cm). Com numero variavel de periodos, medidas fixas
    # estourariam a folha — o ReportLab nao reduz a tabela sozinho.
    largura_util = A4[0] - 4 * cm
    colunas_fixas = [1.6 * cm, 1.3 * cm, 1.4 * cm, 2.6 * cm]
    disponivel = largura_util - sum(colunas_fixas)

    largura_periodo = 1.5 * cm
    largura_disciplina = disponivel - largura_periodo * len(periodos)
    if largura_disciplina < 3.2 * cm:
        # Muitos periodos: aperta as colunas de nota, preservando espaco
        # minimo para o nome da disciplina continuar legivel.
        largura_disciplina = 3.2 * cm
        largura_periodo = (disponivel - largura_disciplina) / max(len(periodos), 1)

    colunas = (
        [largura_disciplina]
        + [largura_periodo] * len(periodos)
        + colunas_fixas
    )

    tabela_notas = Table(linhas, colWidths=colunas, repeatRows=1)
    tabela_notas.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COR_PRIMARIA),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, COR_BORDA),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, COR_BORDA),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COR_FUNDO_CABECALHO]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                *estilo_celula,
            ]
        )
    )
    elementos.append(tabela_notas)
    elementos.append(Spacer(1, 0.4 * cm))

    # --- Resumo geral ---
    resumo = [
        [
            "Media geral:",
            _formatar_nota(dados["media_geral"]),
            "Frequencia geral:",
            (
                f"{float(dados['frequencia_geral']):.1f}%".replace(".", ",")
                if dados["frequencia_geral"] is not None
                else "—"
            ),
            "Resultado:",
            matricula.resultado_final.rotulo,
        ]
    ]
    tabela_resumo = Table(
        resumo, colWidths=[2.4 * cm, 2 * cm, 3 * cm, 2 * cm, 2.2 * cm, 5.4 * cm]
    )
    tabela_resumo.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (-1, 0), (-1, 0), _cor_resultado(matricula.resultado_final)),
                ("BOX", (0, 0), (-1, -1), 0.5, COR_BORDA),
                ("BACKGROUND", (0, 0), (-1, -1), COR_FUNDO_CABECALHO),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elementos.append(tabela_resumo)
    elementos.append(Spacer(1, 0.3 * cm))

    # --- Legenda ---
    minimo = float(ano_letivo.media_aprovacao) if ano_letivo else 6.0
    frequencia = float(ano_letivo.frequencia_minima) if ano_letivo else 75.0
    elementos.append(
        Paragraph(
            f"Media minima para aprovacao: {_formatar_nota(minimo)} &bull; "
            f"Frequencia minima exigida: {frequencia:.0f}% &bull; "
            "F = falta na avaliacao &bull; — = nao lancado",
            estilos["pequeno"],
        )
    )
    elementos.append(Spacer(1, 1.2 * cm))

    # --- Assinaturas ---
    escola = _dados_escola()
    assinaturas = [
        ["_" * 34, "", "_" * 34],
        [
            escola["secretario"] or "Secretaria Escolar",
            "",
            escola["diretor"] or "Direcao",
        ],
    ]
    tabela_assinaturas = Table(assinaturas, colWidths=[6.5 * cm, 4 * cm, 6.5 * cm])
    tabela_assinaturas.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 1), (-1, 1), COR_SUAVE),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
            ]
        )
    )
    elementos.append(tabela_assinaturas)

    return elementos


# ---------------------------------------------------------------------------
# Listagens genericas
# ---------------------------------------------------------------------------
def gerar_listagem(
    titulo: str,
    cabecalhos: list[str],
    linhas: list[list[str]],
    orientacao_paisagem: bool = False,
    observacao: str | None = None,
) -> BytesIO:
    """Gera um PDF tabular a partir de dados ja formatados.

    Usada por todos os relatorios do sistema, o que garante cabecalho,
    rodape e tipografia identicos em qualquer documento emitido pela escola.
    """
    buffer = BytesIO()
    estilos = _estilos()
    tamanho = landscape(A4) if orientacao_paisagem else A4

    documento = SimpleDocTemplate(
        buffer,
        pagesize=tamanho,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
        title=titulo,
        author="SGE",
    )

    elementos = _cabecalho(estilos, titulo)

    if not linhas:
        elementos.append(
            Paragraph("Nenhum registro encontrado para os filtros aplicados.",
                      estilos["normal"])
        )
    else:
        dados = [cabecalhos] + linhas
        tabela = Table(dados, repeatRows=1)
        tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), COR_PRIMARIA),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (0, 0), (-1, -1), 0.5, COR_BORDA),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, COR_BORDA),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, COR_FUNDO_CABECALHO]),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ]
            )
        )
        elementos.append(tabela)
        elementos.append(Spacer(1, 0.3 * cm))
        elementos.append(
            Paragraph(f"Total de registros: {len(linhas)}", estilos["pequeno"])
        )

    if observacao:
        elementos.append(Spacer(1, 0.2 * cm))
        elementos.append(Paragraph(observacao, estilos["pequeno"]))

    try:
        documento.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    except Exception as erro:  # noqa: BLE001
        current_app.logger.error("Falha ao gerar listagem PDF: %s", erro)
        raise ErroDominio("Nao foi possivel gerar o documento em PDF.") from erro

    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Declaracao de matricula
# ---------------------------------------------------------------------------
def gerar_declaracao_matricula(matricula) -> BytesIO:
    """Emite a declaracao de matricula do aluno."""
    buffer = BytesIO()
    estilos = _estilos()
    escola = _dados_escola()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=2 * cm,
        title=f"Declaracao de matricula - {matricula.nome_aluno}",
        author="SGE",
    )

    aluno = matricula.aluno
    turma = matricula.turma
    ano = matricula.ano_letivo.ano if matricula.ano_letivo else date.today().year

    corpo = ParagraphStyle(
        "Corpo",
        parent=estilos["normal"],
        fontSize=11,
        leading=20,
        alignment=4,  # justificado
        firstLineIndent=1.2 * cm,
    )

    texto = (
        f"Declaramos, para os devidos fins, que <b>{aluno.nome_exibicao}</b>"
        + (
            f", portador(a) do CPF {aluno.cpf_formatado}"
            if aluno.cpf
            else ""
        )
        + (
            f", nascido(a) em {aluno.data_nascimento.strftime('%d/%m/%Y')}"
            if aluno.data_nascimento
            else ""
        )
        + f", encontra-se regularmente matriculado(a) nesta instituicao de ensino "
        f"sob o numero <b>{matricula.numero}</b>, cursando "
        f"<b>{turma.serie.nome if turma and turma.serie else 'serie nao informada'}</b>"
        f" - turma {turma.nome if turma else '—'}, no turno "
        f"{turma.turno.rotulo.lower() if turma else '—'}, "
        f"durante o ano letivo de <b>{ano}</b>."
    )

    elementos = _cabecalho(estilos, "Declaracao de Matricula")
    elementos.append(Spacer(1, 0.8 * cm))
    elementos.append(Paragraph(texto, corpo))
    elementos.append(Spacer(1, 1 * cm))

    cidade = escola["endereco"].split(" - ")[-2] if " - " in escola["endereco"] else ""
    local_data = (
        f"{cidade}, {date.today().strftime('%d de %B de %Y')}"
        if cidade
        else date.today().strftime("%d/%m/%Y")
    )
    elementos.append(
        Paragraph(local_data, ParagraphStyle(
            "Data", parent=estilos["normal"], alignment=TA_CENTER, fontSize=10
        ))
    )
    elementos.append(Spacer(1, 1.6 * cm))

    assinatura = Table(
        [["_" * 40], [escola["secretario"] or "Secretaria Escolar"]],
        colWidths=[None],
    )
    assinatura.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 1), (-1, 1), COR_SUAVE),
            ]
        )
    )
    elementos.append(assinatura)

    try:
        documento.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    except Exception as erro:  # noqa: BLE001
        current_app.logger.error("Falha ao gerar declaracao: %s", erro)
        raise ErroDominio("Nao foi possivel gerar a declaracao em PDF.") from erro

    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Resposta HTTP
# ---------------------------------------------------------------------------
def responder_pdf(buffer: BytesIO, nome_arquivo: str) -> Response:
    """Envia o PDF ao navegador para exibicao em nova aba.

    ``inline`` (e nao ``attachment``) porque o usuario quase sempre quer
    conferir o documento antes de imprimir ou salvar.
    """
    resposta = Response(buffer.getvalue(), mimetype="application/pdf")
    resposta.headers["Content-Disposition"] = f'inline; filename="{nome_arquivo}"'
    resposta.headers["Content-Length"] = str(buffer.getbuffer().nbytes)
    # Documentos com dados de alunos nao devem ficar em cache de proxy.
    resposta.headers["Cache-Control"] = "private, no-store"
    return resposta
