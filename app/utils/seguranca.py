"""Primitivas de seguranca do SGE: hash de senha e tokens assinados.

Este modulo e deliberadamente livre de dependencias de models para poder ser
usado por qualquer camada (models, services, CLI) sem risco de import
circular.

Escolha do algoritmo de hash
----------------------------
Utilizamos **Argon2id**, vencedor da Password Hashing Competition e
recomendacao atual da OWASP, em vez do PBKDF2 padrao do Werkzeug. Argon2id
e resistente tanto a ataques por GPU quanto a ataques *side-channel*, o que
importa aqui porque o banco contem dados de menores de idade.

Os hashes ficam com prefixo ``$argon2id$``; qualquer hash legado gerado pelo
Werkzeug (``pbkdf2:sha256$...``) continua sendo verificado corretamente e e
migrado de forma transparente no proximo login bem-sucedido.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Hash de senha
# ---------------------------------------------------------------------------
# Parametros calibrados para ~50-100 ms por hash em hardware modesto: forte o
# suficiente contra forca bruta offline, rapido o suficiente para nao travar
# o login em um servidor compartilhado.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def gerar_hash_senha(senha: str) -> str:
    """Gera o hash Argon2id de uma senha em texto puro."""
    if not senha:
        raise ValueError("A senha nao pode ser vazia.")
    return _hasher.hash(senha)


def verificar_senha(hash_armazenado: str | None, senha: str) -> bool:
    """Compara a senha informada com o hash armazenado.

    Aceita hashes Argon2id e hashes legados do Werkzeug. Retorna ``False``
    para qualquer entrada invalida em vez de propagar excecao, para que a
    rota de login nunca vaze detalhes internos.
    """
    if not hash_armazenado or not senha:
        return False

    if hash_armazenado.startswith("$argon2"):
        try:
            return _hasher.verify(hash_armazenado, senha)
        except (VerificationError, InvalidHashError, ValueError, TypeError):
            # VerificationError e a raiz da hierarquia do argon2 e cobre
            # tanto senha incorreta (VerifyMismatchError) quanto hash
            # corrompido no banco ("Decoding failed"). Capturar apenas o
            # mismatch deixaria um hash adulterado derrubar o login com 500.
            return False

    # Compatibilidade com hashes gerados por versoes anteriores/Werkzeug.
    try:
        return check_password_hash(hash_armazenado, senha)
    except (ValueError, TypeError):
        return False


def precisa_reidratar_hash(hash_armazenado: str | None) -> bool:
    """Indica se o hash deve ser regerado (algoritmo antigo ou custo defasado).

    Chamado apos um login bem-sucedido para migrar as senhas gradualmente,
    sem exigir que nenhum usuario troque a senha.
    """
    if not hash_armazenado:
        return True
    if not hash_armazenado.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(hash_armazenado)
    except (InvalidHashError, ValueError):
        return True


def gerar_hash_werkzeug(senha: str) -> str:
    """Hash rapido (PBKDF2 com poucas iteracoes) para uso exclusivo em testes.

    Argon2 e proposital e caro; usa-lo em centenas de fixtures tornaria a
    suite de testes lenta sem ganho de cobertura.
    """
    return generate_password_hash(senha, method="pbkdf2:sha256:1000")


# ---------------------------------------------------------------------------
# Politica de senha
# ---------------------------------------------------------------------------
# Senhas obvias sao a porta de entrada mais explorada em sistemas escolares,
# onde muitos usuarios reaproveitam senhas triviais.
SENHAS_PROIBIDAS: frozenset[str] = frozenset(
    {
        "12345678", "123456789", "1234567890", "123456", "senha123",
        "password", "password1", "qwerty123", "abc12345", "escola123",
        "professor", "admin123", "administrador", "sge12345", "aluno123",
        "mudar123", "trocar123", "primeiroacesso", "12341234", "11111111",
    }
)


def avaliar_politica_senha(
    senha: str,
    tamanho_minimo: int = 8,
    exige_maiuscula: bool = True,
    exige_minuscula: bool = True,
    exige_numero: bool = True,
    exige_simbolo: bool = False,
) -> list[str]:
    """Valida a senha contra a politica configurada.

    Retorna a lista de problemas encontrados; lista vazia significa senha
    aceita. Devolver *todos* os problemas de uma vez evita o antipadrao de
    obrigar o usuario a descobrir as regras uma por uma.
    """
    problemas: list[str] = []

    if len(senha) < tamanho_minimo:
        problemas.append(
            f"A senha deve ter no minimo {tamanho_minimo} caracteres."
        )
    if exige_maiuscula and not re.search(r"[A-Z]", senha):
        problemas.append("A senha deve conter ao menos uma letra maiuscula.")
    if exige_minuscula and not re.search(r"[a-z]", senha):
        problemas.append("A senha deve conter ao menos uma letra minuscula.")
    if exige_numero and not re.search(r"\d", senha):
        problemas.append("A senha deve conter ao menos um numero.")
    if exige_simbolo and not re.search(r"[^A-Za-z0-9]", senha):
        problemas.append(
            "A senha deve conter ao menos um caractere especial (!@#$...)."
        )
    if senha.lower() in SENHAS_PROIBIDAS:
        problemas.append("Esta senha e muito comum. Escolha outra.")
    # Quatro caracteres iguais seguidos ("aaaa1234") indicam senha de
    # preenchimento, nao uma escolha deliberada do usuario.
    if re.search(r"(.)\1{3,}", senha):
        problemas.append("A senha nao pode repetir o mesmo caractere quatro vezes seguidas.")
    if re.search(r"(0123|1234|2345|3456|4567|5678|6789|abcd|qwer)", senha.lower()):
        problemas.append("A senha nao pode conter sequencias obvias.")

    return problemas


def gerar_senha_temporaria(tamanho: int = 12) -> str:
    """Gera uma senha aleatoria forte para primeiro acesso ou reset.

    Garante ao menos um caractere de cada classe exigida pela politica
    padrao, evitando o caso em que a senha sorteada nao passa na propria
    validacao do sistema.
    """
    tamanho = max(tamanho, 8)
    maiusculas = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # sem I e O (confusao visual)
    minusculas = "abcdefghijkmnopqrstuvwxyz"  # sem l
    numeros = "23456789"                      # sem 0 e 1
    simbolos = "!@#$%&*?"
    alfabeto = maiusculas + minusculas + numeros + simbolos

    obrigatorios = [
        secrets.choice(maiusculas),
        secrets.choice(minusculas),
        secrets.choice(numeros),
        secrets.choice(simbolos),
    ]
    restantes = [secrets.choice(alfabeto) for _ in range(tamanho - len(obrigatorios))]

    caracteres = obrigatorios + restantes
    # ``SystemRandom.shuffle`` usa a mesma fonte de entropia de ``secrets``.
    secrets.SystemRandom().shuffle(caracteres)
    return "".join(caracteres)


# ---------------------------------------------------------------------------
# Tokens assinados (recuperacao de senha, confirmacao de e-mail)
# ---------------------------------------------------------------------------
def _serializador(chave_secreta: str, sal: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=chave_secreta, salt=sal)


def gerar_token(dados, chave_secreta: str, sal: str = "sge-token") -> str:
    """Cria um token assinado e com carimbo de tempo.

    Nao ha estado no servidor: a validade e a integridade sao garantidas pela
    assinatura, o que mantem a recuperacao de senha funcional mesmo com
    multiplos processos Gunicorn.
    """
    return _serializador(chave_secreta, sal).dumps(dados)


def validar_token(
    token: str,
    chave_secreta: str,
    validade_segundos: int = 1800,
    sal: str = "sge-token",
):
    """Valida um token assinado.

    Retorna o conteudo original ou ``None`` se o token for invalido,
    adulterado ou expirado.
    """
    if not token:
        return None
    try:
        return _serializador(chave_secreta, sal).loads(
            token, max_age=validade_segundos
        )
    except (SignatureExpired, BadSignature, ValueError):
        return None


# ---------------------------------------------------------------------------
# Normalizacao e sanitizacao de entrada
# ---------------------------------------------------------------------------
def normalizar_email(email: str | None) -> str:
    """Padroniza o e-mail para comparacao e armazenamento."""
    return (email or "").strip().lower()


def normalizar_texto(texto: str | None) -> str:
    """Remove espacos redundantes preservando acentuacao."""
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def remover_acentos(texto: str | None) -> str:
    """Versao sem acentos e em minusculas, para buscas tolerantes.

    O SQLite nao possui ``unaccent``; normalizar na aplicacao permite que a
    busca por "jose" encontre "Jose" e "Jose" indiferentemente.
    """
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def apenas_digitos(valor: str | None) -> str:
    """Mantem somente digitos (CPF, CEP, telefone)."""
    return re.sub(r"\D", "", valor or "")


def comparar_seguro(a: str | None, b: str | None) -> bool:
    """Comparacao de strings em tempo constante (evita *timing attack*)."""
    return secrets.compare_digest((a or "").encode(), (b or "").encode())
