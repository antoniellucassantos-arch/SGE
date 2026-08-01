"""Servico de autenticacao: login, bloqueio, troca e recuperacao de senha.

Toda a logica sensivel fica concentrada aqui para que a rota seja apenas uma
casca fina. Isso permite testar as regras de seguranca (bloqueio por
tentativas, expiracao de token, politica de senha) sem simular requisicoes
HTTP, e reutiliza-las na futura API mobile.
"""

from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.models.usuario import Usuario
from app.services import auditoria_service
from app.services.excecoes import (
    ErroAutenticacao,
    ErroOperacaoBanco,
    ErroValidacao,
)
from app.utils.seguranca import (
    avaliar_politica_senha,
    gerar_token,
    normalizar_email,
    validar_token,
)

#: Sal do token de recuperacao. Separado do sal de outros tokens para que um
#: token de finalidade diferente jamais seja aceito aqui.
SAL_RECUPERACAO = "sge-recuperacao-senha"

#: Mensagem unica para credenciais invalidas.
#: Nao diferenciar "e-mail inexistente" de "senha errada" impede que um
#: atacante descubra quais e-mails estao cadastrados na escola.
MENSAGEM_CREDENCIAL_INVALIDA = "E-mail ou senha incorretos."


def buscar_por_email(email: str) -> Usuario | None:
    """Localiza um usuario pelo e-mail normalizado."""
    email = normalizar_email(email)
    if not email:
        return None
    return db.session.query(Usuario).filter(Usuario.email == email).first()


def autenticar(email: str, senha: str, endereco_ip: str | None = None) -> Usuario:
    """Valida credenciais e devolve o usuario autenticado.

    Raises:
        ErroAutenticacao: credenciais invalidas, conta inativa ou bloqueada.
    """
    email = normalizar_email(email)
    usuario = buscar_por_email(email)

    # Usuario inexistente -----------------------------------------------------
    if usuario is None:
        auditoria_service.registrar_falha_login(email, "usuario inexistente")
        raise ErroAutenticacao(MENSAGEM_CREDENCIAL_INVALIDA)

    # Conta excluida ou desativada -------------------------------------------
    if usuario.esta_excluido or not usuario.ativo:
        auditoria_service.registrar_falha_login(
            email, "conta inativa", usuario_id=usuario.id
        )
        raise ErroAutenticacao(
            "Esta conta esta desativada. Procure a secretaria da escola."
        )

    # Bloqueio temporario ativo ----------------------------------------------
    if usuario.esta_bloqueado:
        auditoria_service.registrar_falha_login(
            email, "conta bloqueada", usuario_id=usuario.id
        )
        raise ErroAutenticacao(
            "Conta temporariamente bloqueada por excesso de tentativas. "
            f"Tente novamente em {usuario.minutos_restantes_bloqueio} minuto(s)."
        )

    # Senha incorreta ---------------------------------------------------------
    if not usuario.conferir_senha(senha):
        config = current_app.config
        bloqueou = usuario.registrar_falha_login(
            max_tentativas=config.get("LOGIN_MAX_TENTATIVAS", 5),
            minutos_bloqueio=config.get("LOGIN_BLOQUEIO_MINUTOS", 15),
        )
        _confirmar(
            "Falha ao registrar tentativa de login malsucedida",
            propagar_como=None,
        )

        auditoria_service.registrar_falha_login(
            email,
            "conta bloqueada apos tentativas" if bloqueou else "senha incorreta",
            usuario_id=usuario.id,
        )

        if bloqueou:
            raise ErroAutenticacao(
                "Muitas tentativas incorretas. Sua conta foi bloqueada por "
                f"{config.get('LOGIN_BLOQUEIO_MINUTOS', 15)} minutos."
            )
        raise ErroAutenticacao(MENSAGEM_CREDENCIAL_INVALIDA)

    # Sucesso -----------------------------------------------------------------
    usuario.registrar_login(endereco_ip)
    _confirmar("Falha ao registrar login bem-sucedido")
    auditoria_service.registrar_login(usuario)
    _confirmar("Falha ao gravar auditoria de login", propagar_como=None)

    return usuario


def alterar_senha(usuario: Usuario, senha_atual: str, nova_senha: str) -> None:
    """Troca a senha exigindo a confirmacao da senha vigente.

    Raises:
        ErroValidacao: senha atual incorreta, nova senha fraca ou repetida.
    """
    if not usuario.conferir_senha(senha_atual):
        auditoria_service.registrar_falha_login(
            usuario.email, "senha atual incorreta na troca", usuario_id=usuario.id
        )
        raise ErroValidacao(
            "A senha atual esta incorreta.",
            erros_por_campo={"senha_atual": ["Senha incorreta."]},
        )

    if senha_atual == nova_senha:
        raise ErroValidacao(
            "A nova senha deve ser diferente da atual.",
            erros_por_campo={"nova_senha": ["Escolha uma senha diferente."]},
        )

    _validar_politica(nova_senha)

    usuario.definir_senha(nova_senha, exigir_troca=False)
    auditoria_service.registrar_alteracao_senha(usuario)
    _confirmar("Falha ao alterar a senha")


def definir_senha_sem_confirmacao(usuario: Usuario, nova_senha: str) -> None:
    """Define a senha em fluxos que ja autenticaram por outro meio.

    Usado na conclusao da recuperacao por token e no primeiro acesso, quando
    nao existe senha anterior conhecida pelo usuario.
    """
    _validar_politica(nova_senha)
    usuario.definir_senha(nova_senha, exigir_troca=False)
    auditoria_service.registrar_alteracao_senha(usuario, por_recuperacao=True)
    _confirmar("Falha ao redefinir a senha")


# ---------------------------------------------------------------------------
# Recuperacao de senha
# ---------------------------------------------------------------------------
def gerar_token_recuperacao(usuario: Usuario) -> str:
    """Cria um token assinado de uso unico para redefinicao de senha.

    O hash atual da senha entra no payload: assim que a senha muda, todos os
    tokens emitidos antes deixam de valer automaticamente, sem precisar de
    uma tabela de tokens usados.
    """
    return gerar_token(
        {
            "usuario_id": usuario.id,
            "email": usuario.email,
            "assinatura": (usuario.senha_hash or "")[-24:],
        },
        chave_secreta=current_app.config["SECRET_KEY"],
        sal=SAL_RECUPERACAO,
    )


def validar_token_recuperacao(token: str) -> Usuario | None:
    """Valida o token e devolve o usuario, ou ``None`` se invalido/expirado."""
    dados = validar_token(
        token,
        chave_secreta=current_app.config["SECRET_KEY"],
        validade_segundos=current_app.config.get("TOKEN_RECUPERACAO_VALIDADE", 1800),
        sal=SAL_RECUPERACAO,
    )
    if not isinstance(dados, dict):
        return None

    usuario = db.session.get(Usuario, dados.get("usuario_id"))
    if usuario is None or usuario.esta_excluido or not usuario.ativo:
        return None

    # E-mail alterado desde a emissao: token nao vale mais.
    if usuario.email != dados.get("email"):
        return None

    # Token de uso unico: a senha ja foi trocada depois da emissao.
    if (usuario.senha_hash or "")[-24:] != dados.get("assinatura"):
        return None

    return usuario


def solicitar_recuperacao(email: str) -> tuple[Usuario | None, str | None]:
    """Inicia o fluxo de recuperacao de senha.

    Retorna ``(usuario, token)`` quando o e-mail existe e a conta esta ativa,
    e ``(None, None)`` caso contrario.

    Importante: a **rota** deve exibir a mesma mensagem de sucesso nos dois
    casos. Revelar que o e-mail nao existe permitiria enumerar as contas da
    escola.
    """
    usuario = buscar_por_email(email)
    if usuario is None or usuario.esta_excluido or not usuario.ativo:
        return None, None

    return usuario, gerar_token_recuperacao(usuario)


def redefinir_senha_por_token(token: str, nova_senha: str) -> Usuario:
    """Conclui a recuperacao de senha.

    Raises:
        ErroAutenticacao: token invalido ou expirado.
        ErroValidacao: nova senha fora da politica.
    """
    usuario = validar_token_recuperacao(token)
    if usuario is None:
        raise ErroAutenticacao(
            "Link de recuperacao invalido ou expirado. Solicite um novo."
        )

    definir_senha_sem_confirmacao(usuario, nova_senha)
    usuario.desbloquear()
    _confirmar("Falha ao desbloquear a conta apos recuperacao", propagar_como=None)
    return usuario


# ---------------------------------------------------------------------------
# Apoio interno
# ---------------------------------------------------------------------------
def _validar_politica(senha: str) -> None:
    """Aplica a politica de senha configurada, agregando todos os problemas."""
    config = current_app.config
    problemas = avaliar_politica_senha(
        senha,
        tamanho_minimo=config.get("SENHA_TAMANHO_MINIMO", 8),
        exige_maiuscula=config.get("SENHA_EXIGE_MAIUSCULA", True),
        exige_minuscula=config.get("SENHA_EXIGE_MINUSCULA", True),
        exige_numero=config.get("SENHA_EXIGE_NUMERO", True),
        exige_simbolo=config.get("SENHA_EXIGE_SIMBOLO", False),
    )
    if problemas:
        raise ErroValidacao(
            " ".join(problemas), erros_por_campo={"nova_senha": problemas}
        )


def _confirmar(mensagem_erro: str, propagar_como=ErroOperacaoBanco) -> None:
    """Confirma a transacao, revertendo e registrando em caso de falha.

    ``propagar_como=None`` e usado em operacoes acessorias (auditoria,
    contadores) que nao devem derrubar o fluxo principal do usuario.
    """
    try:
        db.session.commit()
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem_erro, erro)
        if propagar_como is not None:
            raise propagar_como() from erro
