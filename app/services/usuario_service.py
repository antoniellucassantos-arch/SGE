"""Regras de negocio da gestao de contas de acesso."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import PapelUsuario
from app.models.usuario import Usuario
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)
from app.utils.seguranca import (
    apenas_digitos,
    avaliar_politica_senha,
    gerar_senha_temporaria,
    normalizar_email,
    remover_acentos,
)
from app.utils.validadores import cpf_valido


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def consulta_base():
    return db.session.query(Usuario).filter(Usuario.excluido_em.is_(None))


def buscar(usuario_id: int | str | None) -> Usuario:
    usuario = Usuario.buscar_por_id(usuario_id)
    if usuario is None or usuario.esta_excluido:
        raise RegistroNaoEncontrado("Usuario nao encontrado.")
    return usuario


def listar(
    termo: str | None = None,
    papel: str | None = None,
    situacao: str | None = None,
):
    """Consulta de listagem de contas de acesso."""
    consulta = consulta_base()

    if termo:
        alvo = f"%{remover_acentos(termo)}%"
        condicoes = [
            Usuario.nome_normalizado.like(alvo),
            db.func.lower(Usuario.email).like(f"%{termo.lower()}%"),
        ]
        digitos = apenas_digitos(termo)
        if digitos:
            condicoes.append(Usuario.cpf.like(f"%{digitos}%"))
        consulta = consulta.filter(or_(*condicoes))

    if papel:
        consulta = consulta.filter(Usuario.papel == papel)

    if situacao == "ativo":
        consulta = consulta.filter(Usuario.ativo.is_(True))
    elif situacao == "inativo":
        consulta = consulta.filter(Usuario.ativo.is_(False))
    elif situacao == "bloqueado":
        from app.models.base import agora_utc

        consulta = consulta.filter(Usuario.bloqueado_ate > agora_utc())

    return consulta


def estatisticas() -> dict[str, int]:
    """Contagem de contas por papel, para os cartoes da listagem."""
    linhas = (
        db.session.query(Usuario.papel, db.func.count(Usuario.id))
        .filter(Usuario.excluido_em.is_(None), Usuario.ativo.is_(True))
        .group_by(Usuario.papel)
        .all()
    )

    resultado = {papel.value: 0 for papel in PapelUsuario}
    for papel, total in linhas:
        chave = papel.value if hasattr(papel, "value") else str(papel)
        resultado[chave] = total

    resultado["total"] = sum(resultado.values())
    return resultado


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------
def _validar_email_unico(email: str, usuario_id: int | None = None) -> str:
    email = normalizar_email(email)
    if not email:
        raise ErroValidacao(
            "Informe um e-mail.",
            erros_por_campo={"email": ["Campo obrigatorio."]},
        )

    consulta = db.session.query(Usuario).filter(Usuario.email == email)
    if usuario_id:
        consulta = consulta.filter(Usuario.id != usuario_id)

    if consulta.first():
        raise ErroConflito(f"Ja existe uma conta com o e-mail {email}.")

    return email


def _validar_cpf(cpf: str | None, usuario_id: int | None = None) -> str | None:
    digitos = apenas_digitos(cpf)
    if not digitos:
        return None

    if not cpf_valido(digitos):
        raise ErroValidacao(
            "CPF invalido.",
            erros_por_campo={"cpf": ["Confira os digitos informados."]},
        )

    consulta = db.session.query(Usuario).filter(Usuario.cpf == digitos)
    if usuario_id:
        consulta = consulta.filter(Usuario.id != usuario_id)

    if consulta.first():
        raise ErroConflito("Ja existe uma conta com este CPF.")

    return digitos


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def criar(dados: dict[str, Any], senha: str | None = None) -> tuple[Usuario, str]:
    """Cria uma conta de acesso.

    Returns:
        ``(usuario, senha_temporaria)``. A senha e exibida uma unica vez
        para a secretaria repassar ao usuario; ela nunca fica armazenada em
        texto puro.
    """
    dados["email"] = _validar_email_unico(dados.get("email", ""))
    dados["cpf"] = _validar_cpf(dados.get("cpf"))

    senha_final = senha or gerar_senha_temporaria()
    if senha:
        problemas = avaliar_politica_senha(senha)
        if problemas:
            raise ErroValidacao(
                " ".join(problemas), erros_por_campo={"senha": problemas}
            )

    usuario = Usuario()
    usuario.atualizar_campos(**dados)
    usuario.definir_senha(senha_final, exigir_troca=True)

    db.session.add(usuario)
    _confirmar("Falha ao criar usuario")

    auditoria_service.registrar_criacao(
        "Usuario",
        usuario.id,
        f"Conta criada: {usuario.email} ({usuario.papel.rotulo})",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return usuario, senha_final


def atualizar(usuario: Usuario, dados: dict[str, Any], autor) -> Usuario:
    """Atualiza uma conta de acesso."""
    if "email" in dados:
        dados["email"] = _validar_email_unico(dados["email"], usuario_id=usuario.id)
    if "cpf" in dados:
        dados["cpf"] = _validar_cpf(dados.get("cpf"), usuario_id=usuario.id)

    # Um administrador nao pode rebaixar ou desativar a propria conta: sem
    # essa trava e possivel ficar sem nenhum administrador no sistema.
    if autor is not None and autor.id == usuario.id:
        novo_papel = dados.get("papel")
        if novo_papel and novo_papel != usuario.papel.value:
            raise ErroRegraNegocio(
                "Voce nao pode alterar o proprio perfil de acesso. "
                "Peca a outro administrador."
            )
        if dados.get("ativo") is False:
            raise ErroRegraNegocio("Voce nao pode desativar a propria conta.")

    if dados.get("papel") and usuario.e_administrador:
        _garantir_outro_administrador(usuario, dados["papel"])

    antes = usuario.para_dicionario(excluir={"senha_hash"})
    usuario.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, usuario.para_dicionario(excluir={"senha_hash"})
    )
    if not alteracoes:
        return usuario

    _confirmar("Falha ao atualizar usuario")
    auditoria_service.registrar_atualizacao(
        "Usuario", usuario.id, f"Conta atualizada: {usuario.email}", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return usuario


def _garantir_outro_administrador(usuario: Usuario, novo_papel: str) -> None:
    """Impede que o sistema fique sem nenhum administrador ativo."""
    if novo_papel == PapelUsuario.ADMINISTRADOR.value:
        return

    restantes = (
        consulta_base()
        .filter(
            Usuario.papel == PapelUsuario.ADMINISTRADOR,
            Usuario.ativo.is_(True),
            Usuario.id != usuario.id,
        )
        .count()
    )
    if restantes == 0:
        raise ErroRegraNegocio(
            "Este e o unico administrador ativo do sistema. Promova outro "
            "usuario a administrador antes de alterar este perfil."
        )


def redefinir_senha(usuario: Usuario) -> str:
    """Gera uma senha temporaria e exige a troca no proximo acesso."""
    senha = gerar_senha_temporaria()
    usuario.definir_senha(senha, exigir_troca=True)
    usuario.desbloquear()

    _confirmar("Falha ao redefinir senha")

    auditoria_service.registrar_atualizacao(
        "Usuario",
        usuario.id,
        f"Senha redefinida administrativamente: {usuario.email}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return senha


def alternar_ativacao(usuario: Usuario, autor) -> Usuario:
    """Ativa ou desativa uma conta."""
    if autor is not None and autor.id == usuario.id:
        raise ErroRegraNegocio("Voce nao pode desativar a propria conta.")

    if usuario.ativo and usuario.e_administrador:
        _garantir_outro_administrador(usuario, PapelUsuario.SECRETARIA.value)

    usuario.ativo = not usuario.ativo
    _confirmar("Falha ao alterar situacao da conta")

    auditoria_service.registrar_atualizacao(
        "Usuario",
        usuario.id,
        f"Conta {'ativada' if usuario.ativo else 'desativada'}: {usuario.email}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return usuario


def desbloquear(usuario: Usuario) -> Usuario:
    """Remove o bloqueio temporario por tentativas de login."""
    usuario.desbloquear()
    _confirmar("Falha ao desbloquear conta")

    auditoria_service.registrar_atualizacao(
        "Usuario", usuario.id, f"Conta desbloqueada: {usuario.email}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return usuario


def excluir(usuario: Usuario, autor) -> None:
    """Exclui logicamente uma conta de acesso."""
    if autor is not None and autor.id == usuario.id:
        raise ErroRegraNegocio("Voce nao pode excluir a propria conta.")

    if usuario.e_administrador:
        _garantir_outro_administrador(usuario, PapelUsuario.SECRETARIA.value)

    usuario.excluir(autor.id if autor else None)
    usuario.ativo = False
    _confirmar("Falha ao excluir usuario")

    auditoria_service.registrar_exclusao(
        "Usuario", usuario.id, f"Conta excluida: {usuario.email}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def atualizar_perfil(usuario: Usuario, dados: dict[str, Any]) -> Usuario:
    """Atualiza os dados que o proprio usuario pode editar.

    Papel e situacao **nao** entram aqui: sao atribuicoes administrativas.
    """
    permitidos = {"nome_completo", "telefone", "foto"}
    filtrados = {k: v for k, v in dados.items() if k in permitidos}

    antes = usuario.para_dicionario(excluir={"senha_hash"})
    usuario.atualizar_campos(**filtrados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, usuario.para_dicionario(excluir={"senha_hash"})
    )
    if not alteracoes:
        return usuario

    _confirmar("Falha ao atualizar perfil")
    auditoria_service.registrar_atualizacao(
        "Usuario", usuario.id, "Perfil atualizado pelo proprio usuario", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return usuario


# ---------------------------------------------------------------------------
def _confirmar(mensagem: str, propagar: bool = True) -> None:
    from flask import current_app

    try:
        db.session.commit()
    except IntegrityError as erro:
        db.session.rollback()
        current_app.logger.warning("%s (integridade): %s", mensagem, erro)
        if propagar:
            raise ErroConflito(
                "Ja existe uma conta com este e-mail ou CPF."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
