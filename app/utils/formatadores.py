"""Formatadores para a camada de apresentacao (filtros Jinja2).

Regra do projeto: o banco armazena dados **crus e em UTC**; a formatacao
para o padrao brasileiro acontece exclusivamente aqui. Isso mantem os
calculos consistentes e concentra em um unico arquivo qualquer mudanca de
formato ou de fuso.

Todos os formatadores toleram ``None`` e retornam um marcador neutro em vez
de quebrar a renderizacao — uma tela de aluno nao pode dar erro 500 porque um
telefone opcional esta vazio.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.utils.validadores import (
    formatar_cep as _mascara_cep,
)
from app.utils.validadores import (
    formatar_cpf as _mascara_cpf,
)
from app.utils.validadores import (
    formatar_telefone as _mascara_telefone,
)

#: Exibido quando o valor esta ausente.
VAZIO = "—"

#: Fuso horario da escola. Todo o banco grava UTC; a conversao acontece na
#: exibicao. Brasilia nao adota mais horario de verao, entao o deslocamento
#: fixo e correto e evita a dependencia de uma tzdata externa.
FUSO_ESCOLA = timezone(timedelta(hours=-3))

MESES = (
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

DIAS_SEMANA = (
    "segunda-feira", "terca-feira", "quarta-feira",
    "quinta-feira", "sexta-feira", "sabado", "domingo",
)


def _para_horario_local(valor: datetime) -> datetime:
    """Converte um ``datetime`` UTC *naive* para o fuso da escola."""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(FUSO_ESCOLA)


# ---------------------------------------------------------------------------
# Datas e horas
# ---------------------------------------------------------------------------
def formatar_data(valor: date | datetime | None, padrao: str = VAZIO) -> str:
    """``31/07/2026``"""
    if valor is None:
        return padrao
    if isinstance(valor, datetime):
        valor = _para_horario_local(valor).date()
    return valor.strftime("%d/%m/%Y")


def formatar_data_hora(valor: datetime | None, padrao: str = VAZIO) -> str:
    """``31/07/2026 14:30``"""
    if valor is None:
        return padrao
    return _para_horario_local(valor).strftime("%d/%m/%Y %H:%M")


def formatar_hora(valor: time | datetime | None, padrao: str = VAZIO) -> str:
    """``14:30``"""
    if valor is None:
        return padrao
    if isinstance(valor, datetime):
        return _para_horario_local(valor).strftime("%H:%M")
    return valor.strftime("%H:%M")


def formatar_data_extenso(valor: date | datetime | None, padrao: str = VAZIO) -> str:
    """``31 de julho de 2026`` — usado em declaracoes e documentos."""
    if valor is None:
        return padrao
    if isinstance(valor, datetime):
        valor = _para_horario_local(valor).date()
    return f"{valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def formatar_dia_semana(valor: date | datetime | None, padrao: str = VAZIO) -> str:
    if valor is None:
        return padrao
    if isinstance(valor, datetime):
        valor = _para_horario_local(valor).date()
    return DIAS_SEMANA[valor.weekday()]


def tempo_relativo(valor: datetime | None, padrao: str = VAZIO) -> str:
    """``ha 5 minutos``, ``ontem``, ``ha 3 dias``.

    Usado na lista de atividades recentes do dashboard, onde a distancia no
    tempo comunica melhor que o carimbo exato.
    """
    if valor is None:
        return padrao

    agora = datetime.now(UTC)
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)

    diferenca = agora - valor
    segundos = int(diferenca.total_seconds())

    if segundos < 0:
        return formatar_data_hora(valor)
    if segundos < 60:
        return "agora mesmo"
    if segundos < 3600:
        minutos = segundos // 60
        return f"ha {minutos} minuto{'s' if minutos > 1 else ''}"
    if segundos < 86400:
        horas = segundos // 3600
        return f"ha {horas} hora{'s' if horas > 1 else ''}"

    dias = segundos // 86400
    if dias == 1:
        return "ontem"
    if dias < 30:
        return f"ha {dias} dias"
    if dias < 365:
        meses = dias // 30
        return f"ha {meses} {'mes' if meses == 1 else 'meses'}"

    anos = dias // 365
    return f"ha {anos} ano{'s' if anos > 1 else ''}"


def duracao_legivel(minutos: int | None, padrao: str = VAZIO) -> str:
    """``1h30`` a partir de uma quantidade de minutos."""
    if minutos is None:
        return padrao
    horas, resto = divmod(int(minutos), 60)
    if horas and resto:
        return f"{horas}h{resto:02d}"
    if horas:
        return f"{horas}h"
    return f"{resto}min"


# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------
def _para_decimal(valor) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def formatar_moeda(valor, padrao: str = VAZIO) -> str:
    """``R$ 1.234,56`` no formato brasileiro."""
    numero = _para_decimal(valor)
    if numero is None:
        return padrao
    inteiro, _, decimal = f"{numero:,.2f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    return f"R$ {inteiro},{decimal}"


def formatar_nota(valor, casas: int = 1, padrao: str = VAZIO) -> str:
    """``8,5`` — nota com virgula decimal."""
    numero = _para_decimal(valor)
    if numero is None:
        return padrao
    return f"{numero:.{casas}f}".replace(".", ",")


def formatar_quantidade(valor, padrao: str = VAZIO) -> str:
    """``1`` · ``10`` · ``2,5`` — numero sem zero decimal inutil.

    Diferente de :func:`formatar_nota`, que sempre mostra uma casa: nota
    "8,0" comunica precisao e faz sentido num boletim. Ja peso "1,0" e nota
    maxima "10,0" nao — sao quantidades, e o zero a direita so faz o
    professor procurar um decimal que nao existe.
    """
    numero = _para_decimal(valor)
    if numero is None:
        return padrao

    if numero == numero.to_integral_value():
        return str(numero.quantize(Decimal(1)))

    return f"{numero.normalize():f}".replace(".", ",")


def formatar_percentual(valor, casas: int = 1, padrao: str = VAZIO) -> str:
    """``87,5%``"""
    numero = _para_decimal(valor)
    if numero is None:
        return padrao
    return f"{numero:.{casas}f}".replace(".", ",") + "%"


def formatar_numero(valor, padrao: str = VAZIO) -> str:
    """``1.234`` — separador de milhar brasileiro."""
    if valor is None:
        return padrao
    try:
        return f"{int(valor):,}".replace(",", ".")
    except (ValueError, TypeError):
        return padrao


# ---------------------------------------------------------------------------
# Documentos e contatos
# ---------------------------------------------------------------------------
def formatar_cpf_seguro(valor: str | None, padrao: str = VAZIO) -> str:
    return _mascara_cpf(valor) if valor else padrao


def formatar_telefone_seguro(valor: str | None, padrao: str = VAZIO) -> str:
    return _mascara_telefone(valor) if valor else padrao


def formatar_cep_seguro(valor: str | None, padrao: str = VAZIO) -> str:
    return _mascara_cep(valor) if valor else padrao


def mascarar_cpf(valor: str | None, padrao: str = VAZIO) -> str:
    """``***.456.789-**`` — exibicao parcial para telas de consulta ampla.

    Minimizacao de dados (LGPD art. 6, III): a listagem nao precisa expor o
    CPF completo; a ficha individual, com permissao especifica, expoe.
    """
    if not valor:
        return padrao
    digitos = "".join(c for c in valor if c.isdigit())
    if len(digitos) != 11:
        return padrao
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def truncar(texto: str | None, limite: int = 80, sufixo: str = "...") -> str:
    """Corta o texto respeitando a ultima palavra inteira."""
    if not texto:
        return ""
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    cortado = texto[:limite].rsplit(" ", 1)[0]
    return f"{cortado}{sufixo}"


def primeiro_nome(nome: str | None, padrao: str = "") -> str:
    if not nome:
        return padrao
    return nome.strip().split(" ")[0]


def nome_abreviado(nome: str | None, padrao: str = VAZIO) -> str:
    """``Maria S. Oliveira`` — cabe em listagens estreitas no celular."""
    if not nome:
        return padrao
    partes = [p for p in nome.strip().split(" ") if p]
    if len(partes) <= 2:
        return nome
    meio = [f"{p[0]}." for p in partes[1:-1] if len(p) > 2]
    return " ".join([partes[0], *meio, partes[-1]])


def sim_nao(valor, sim: str = "Sim", nao: str = "Nao") -> str:
    return sim if valor else nao


def quebra_linha(texto: str | None) -> str:
    """Converte quebras de linha em ``<br>``.

    Seguro por construcao: o Jinja2 escapa o texto **antes** deste filtro
    rodar (autoescape ativo), entao apenas as tags geradas aqui sao HTML.
    """
    from markupsafe import Markup, escape

    if not texto:
        return ""
    return Markup(str(escape(texto)).replace("\n", "<br>"))


def pluralizar(quantidade: int, singular: str, plural: str | None = None) -> str:
    """``1 aluno`` / ``5 alunos``"""
    plural = plural or f"{singular}s"
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def iniciais(nome: str | None) -> str:
    """Iniciais para avatares textuais."""
    partes = [p for p in (nome or "").split(" ") if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


__all__ = [
    "VAZIO",
    "FUSO_ESCOLA",
    "formatar_data",
    "formatar_data_hora",
    "formatar_hora",
    "formatar_data_extenso",
    "formatar_dia_semana",
    "tempo_relativo",
    "duracao_legivel",
    "formatar_moeda",
    "formatar_nota",
    "formatar_percentual",
    "formatar_numero",
    "formatar_cpf_seguro",
    "formatar_telefone_seguro",
    "formatar_cep_seguro",
    "mascarar_cpf",
    "truncar",
    "primeiro_nome",
    "nome_abreviado",
    "sim_nao",
    "quebra_linha",
    "pluralizar",
    "iniciais",
]
