"""Validadores de dominio brasileiro e validadores customizados de WTForms.

Separados dos formularios para que a mesma regra possa ser aplicada tambem
por services, comandos CLI e pela importacao em lote de alunos — evitando o
cenario em que um dado invalido entra no banco por um caminho que nao passa
pelo formulario.
"""

from __future__ import annotations

import re
from datetime import date

from wtforms.validators import ValidationError

from app.utils.seguranca import apenas_digitos

# ---------------------------------------------------------------------------
# Documentos brasileiros
# ---------------------------------------------------------------------------


def cpf_valido(cpf: str | None) -> bool:
    """Valida um CPF pelos dois digitos verificadores.

    Aceita com ou sem mascara. Rejeita sequencias repetidas (111.111.111-11),
    que passam no calculo mas nunca sao emitidas pela Receita Federal.
    """
    numeros = apenas_digitos(cpf)

    if len(numeros) != 11 or numeros == numeros[0] * 11:
        return False

    for tamanho in (9, 10):
        soma = sum(
            int(numeros[i]) * (tamanho + 1 - i) for i in range(tamanho)
        )
        digito = (soma * 10) % 11
        if digito == 10:
            digito = 0
        if digito != int(numeros[tamanho]):
            return False

    return True


def cnpj_valido(cnpj: str | None) -> bool:
    """Valida um CNPJ pelos dois digitos verificadores."""
    numeros = apenas_digitos(cnpj)

    if len(numeros) != 14 or numeros == numeros[0] * 14:
        return False

    pesos_primeiro = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_segundo = [6] + pesos_primeiro

    for pesos, posicao in ((pesos_primeiro, 12), (pesos_segundo, 13)):
        soma = sum(int(numeros[i]) * pesos[i] for i in range(posicao))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(numeros[posicao]):
            return False

    return True


def formatar_cpf(cpf: str | None) -> str:
    """Aplica a mascara ``000.000.000-00`` quando possivel."""
    numeros = apenas_digitos(cpf)
    if len(numeros) != 11:
        return cpf or ""
    return f"{numeros[:3]}.{numeros[3:6]}.{numeros[6:9]}-{numeros[9:]}"


def formatar_cnpj(cnpj: str | None) -> str:
    """Aplica a mascara ``00.000.000/0000-00`` quando possivel."""
    numeros = apenas_digitos(cnpj)
    if len(numeros) != 14:
        return cnpj or ""
    return (
        f"{numeros[:2]}.{numeros[2:5]}.{numeros[5:8]}"
        f"/{numeros[8:12]}-{numeros[12:]}"
    )


def formatar_telefone(telefone: str | None) -> str:
    """Aplica mascara de telefone fixo (10 digitos) ou celular (11)."""
    numeros = apenas_digitos(telefone)
    if len(numeros) == 11:
        return f"({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}"
    if len(numeros) == 10:
        return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
    return telefone or ""


def formatar_cep(cep: str | None) -> str:
    """Aplica a mascara ``00000-000``."""
    numeros = apenas_digitos(cep)
    if len(numeros) != 8:
        return cep or ""
    return f"{numeros[:5]}-{numeros[5:]}"


def telefone_valido(telefone: str | None) -> bool:
    """Aceita telefone fixo (10 digitos) ou celular (11, iniciando por 9)."""
    numeros = apenas_digitos(telefone)
    if len(numeros) not in (10, 11):
        return False
    if numeros[:2] < "11" or numeros[:2] > "99":  # DDD valido
        return False
    if len(numeros) == 11 and numeros[2] != "9":
        return False
    return True


def cep_valido(cep: str | None) -> bool:
    numeros = apenas_digitos(cep)
    return len(numeros) == 8 and numeros != "00000000"


# Siglas das 26 unidades federativas e do Distrito Federal.
UNIDADES_FEDERATIVAS: tuple[str, ...] = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
)


def uf_valida(uf: str | None) -> bool:
    return (uf or "").strip().upper() in UNIDADES_FEDERATIVAS


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------


def calcular_idade(nascimento: date | None, referencia: date | None = None) -> int | None:
    """Idade em anos completos na data de referencia (padrao: hoje)."""
    if not nascimento:
        return None
    referencia = referencia or date.today()
    idade = referencia.year - nascimento.year
    if (referencia.month, referencia.day) < (nascimento.month, nascimento.day):
        idade -= 1
    return max(idade, 0)


def data_nascimento_plausivel(nascimento: date | None, idade_maxima: int = 120) -> bool:
    """Rejeita datas no futuro e idades impossiveis (erro de digitacao)."""
    if not nascimento:
        return False
    hoje = date.today()
    if nascimento > hoje:
        return False
    idade = calcular_idade(nascimento, hoje) or 0
    return idade <= idade_maxima


# ---------------------------------------------------------------------------
# Validadores WTForms
# ---------------------------------------------------------------------------


class CPF:
    """Valida o campo como CPF brasileiro. Campo vazio e ignorado.

    Deixar o campo vazio passar e proposital: a obrigatoriedade e expressa
    por ``DataRequired``, mantendo cada validador com uma unica
    responsabilidade.
    """

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or "CPF invalido. Confira os digitos informados."

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        if not cpf_valido(field.data):
            raise ValidationError(self.mensagem)


class CNPJ:
    """Valida o campo como CNPJ brasileiro. Campo vazio e ignorado."""

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or "CNPJ invalido. Confira os digitos informados."

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        if not cnpj_valido(field.data):
            raise ValidationError(self.mensagem)


class Telefone:
    """Valida telefone fixo ou celular brasileiro com DDD."""

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or (
            "Telefone invalido. Use o formato (00) 00000-0000."
        )

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        if not telefone_valido(field.data):
            raise ValidationError(self.mensagem)


class CEP:
    """Valida CEP com 8 digitos."""

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or "CEP invalido. Use o formato 00000-000."

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        if not cep_valido(field.data):
            raise ValidationError(self.mensagem)


class DataNaoFutura:
    """Impede datas posteriores a hoje (nascimento, matricula, aula...)."""

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or "A data nao pode ser futura."

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        valor = field.data
        if isinstance(valor, date) and valor > date.today():
            raise ValidationError(self.mensagem)


class IdadePlausivel:
    """Garante que a data de nascimento resulte em uma idade coerente."""

    def __init__(
        self,
        idade_minima: int = 0,
        idade_maxima: int = 120,
        mensagem: str | None = None,
    ) -> None:
        self.idade_minima = idade_minima
        self.idade_maxima = idade_maxima
        self.mensagem = mensagem

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        idade = calcular_idade(field.data)
        if idade is None or not (self.idade_minima <= idade <= self.idade_maxima):
            raise ValidationError(
                self.mensagem
                or (
                    "Data de nascimento invalida: a idade deve estar entre "
                    f"{self.idade_minima} e {self.idade_maxima} anos."
                )
            )


class PoliticaSenha:
    """Aplica a politica de senha configurada em ``config``.

    Le a configuracao da aplicacao em tempo de execucao para que a escola
    possa endurecer a politica sem alterar codigo.
    """

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem

    def __call__(self, form, field) -> None:
        if not field.data:
            return

        from flask import current_app

        from app.utils.seguranca import avaliar_politica_senha

        cfg = current_app.config
        problemas = avaliar_politica_senha(
            field.data,
            tamanho_minimo=cfg.get("SENHA_TAMANHO_MINIMO", 8),
            exige_maiuscula=cfg.get("SENHA_EXIGE_MAIUSCULA", True),
            exige_minuscula=cfg.get("SENHA_EXIGE_MINUSCULA", True),
            exige_numero=cfg.get("SENHA_EXIGE_NUMERO", True),
            exige_simbolo=cfg.get("SENHA_EXIGE_SIMBOLO", False),
        )
        if problemas:
            raise ValidationError(self.mensagem or " ".join(problemas))


class NomeCompleto:
    """Exige nome e sobrenome, rejeitando digitos.

    Cadastro de aluno com nome incompleto gera documento escolar invalido;
    barrar na entrada e mais barato do que corrigir depois.
    """

    def __init__(self, mensagem: str | None = None) -> None:
        self.mensagem = mensagem or (
            "Informe o nome completo (nome e sobrenome), sem numeros."
        )

    def __call__(self, form, field) -> None:
        if not field.data:
            return
        valor = re.sub(r"\s+", " ", field.data).strip()
        if re.search(r"\d", valor):
            raise ValidationError(self.mensagem)
        partes = [p for p in valor.split(" ") if len(p) >= 2]
        if len(partes) < 2:
            raise ValidationError(self.mensagem)


class ValorEntre:
    """Valida faixa numerica aceitando ``None`` (campo opcional)."""

    def __init__(
        self,
        minimo: float,
        maximo: float,
        mensagem: str | None = None,
    ) -> None:
        self.minimo = minimo
        self.maximo = maximo
        self.mensagem = mensagem

    def __call__(self, form, field) -> None:
        if field.data is None:
            return
        if not (self.minimo <= float(field.data) <= self.maximo):
            raise ValidationError(
                self.mensagem
                or f"O valor deve estar entre {self.minimo} e {self.maximo}."
            )
