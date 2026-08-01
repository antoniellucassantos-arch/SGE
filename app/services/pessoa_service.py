"""Servico generico de cadastros de pessoas (professor, funcionario, responsavel).

Os tres cadastros compartilham exatamente o mesmo ciclo de vida: buscar,
listar com busca textual, criar, atualizar, excluir logicamente e vincular
uma conta de acesso. Escrever tres arquivos quase identicos seria triplicar
a superficie de manutencao — e a chance de uma correcao ser aplicada em
apenas dois deles.

O aluno tem service proprio (``aluno_service``) porque carrega regras que os
demais nao tem: geracao de RA, vinculo com responsaveis e bloqueio de
exclusao com matricula ativa.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import PapelUsuario, SituacaoCadastro
from app.models.pessoas import Funcionario, Professor, Responsavel
from app.models.usuario import Usuario
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)
from app.utils.seguranca import apenas_digitos, normalizar_email, remover_acentos
from app.utils.validadores import cpf_valido


class CadastroPessoa:
    """Operacoes de CRUD para um model de pessoa especifico.

    Instanciado uma vez por tipo (ver as constantes no fim do modulo) e
    usado pelas rotas como se fosse um service dedicado.
    """

    def __init__(
        self,
        modelo: type,
        rotulo: str,
        rotulo_plural: str,
        campo_identificador: str | None = None,
        gerador_identificador=None,
        papel_padrao: PapelUsuario | None = None,
    ) -> None:
        self.modelo = modelo
        self.rotulo = rotulo
        self.rotulo_plural = rotulo_plural
        self.campo_identificador = campo_identificador
        self.gerador_identificador = gerador_identificador
        self.papel_padrao = papel_padrao

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def consulta_base(self):
        return db.session.query(self.modelo).filter(
            self.modelo.excluido_em.is_(None)
        )

    def buscar(self, registro_id: int | str | None):
        """Recupera um registro ativo pelo id."""
        registro = self.modelo.buscar_por_id(registro_id)
        if registro is None or registro.esta_excluido:
            raise RegistroNaoEncontrado(f"{self.rotulo} nao encontrado.")
        return registro

    def listar(
        self,
        termo: str | None = None,
        situacao: str | None = None,
        **filtros_extras: Any,
    ):
        """Consulta de listagem com busca textual e filtros simples."""
        consulta = self.consulta_base()

        if termo:
            alvo = f"%{remover_acentos(termo)}%"
            digitos = apenas_digitos(termo)

            condicoes = [self.modelo.nome_normalizado.like(alvo)]
            if digitos:
                condicoes.append(self.modelo.cpf.like(f"%{digitos}%"))
            if self.campo_identificador:
                coluna = getattr(self.modelo, self.campo_identificador)
                condicoes.append(coluna.like(f"%{termo}%"))

            consulta = consulta.filter(or_(*condicoes))

        if situacao:
            consulta = consulta.filter(self.modelo.situacao == situacao)

        # Filtros especificos (cargo/setor do funcionario, por exemplo).
        for campo, valor in filtros_extras.items():
            if valor and hasattr(self.modelo, campo):
                consulta = consulta.filter(getattr(self.modelo, campo) == valor)

        return consulta

    # ------------------------------------------------------------------
    # Validacao
    # ------------------------------------------------------------------
    def _validar_cpf(self, cpf: str | None, registro_id: int | None = None) -> None:
        """Valida os digitos verificadores e a unicidade do CPF."""
        digitos = apenas_digitos(cpf)
        if not digitos:
            return

        if not cpf_valido(digitos):
            raise ErroValidacao(
                "CPF invalido.",
                erros_por_campo={"cpf": ["Confira os digitos informados."]},
            )

        consulta = self.consulta_base().filter(self.modelo.cpf == digitos)
        if registro_id:
            consulta = consulta.filter(self.modelo.id != registro_id)

        existente = consulta.first()
        if existente:
            raise ErroConflito(
                f"O CPF informado ja pertence a {existente.nome_completo}."
            )

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------
    def criar(self, dados: dict[str, Any]):
        """Cadastra um novo registro, gerando o identificador funcional."""
        self._validar_cpf(dados.get("cpf"))

        registro = self.modelo()
        registro.atualizar_campos(**dados)

        if self.campo_identificador and self.gerador_identificador:
            if not getattr(registro, self.campo_identificador, None):
                setattr(
                    registro, self.campo_identificador, self.gerador_identificador()
                )

        db.session.add(registro)
        self._confirmar(f"Falha ao cadastrar {self.rotulo.lower()}")

        auditoria_service.registrar_criacao(
            self.modelo.__name__,
            registro.id,
            f"{self.rotulo} cadastrado: {registro.nome_completo}",
        )
        self._confirmar("Falha ao registrar auditoria", propagar=False)

        return registro

    def atualizar(self, registro, dados: dict[str, Any]):
        """Atualiza um registro existente, gravando o delta na auditoria."""
        self._validar_cpf(dados.get("cpf"), registro_id=registro.id)

        antes = registro.para_dicionario()
        registro.atualizar_campos(**dados)
        depois = registro.para_dicionario()

        alteracoes = auditoria_service.calcular_alteracoes(antes, depois)
        if not alteracoes:
            return registro

        self._confirmar(f"Falha ao atualizar {self.rotulo.lower()}")

        auditoria_service.registrar_atualizacao(
            self.modelo.__name__,
            registro.id,
            f"{self.rotulo} atualizado: {registro.nome_completo}",
            alteracoes,
        )
        self._confirmar("Falha ao registrar auditoria", propagar=False)

        return registro

    def excluir(self, registro, usuario_id: int | None = None) -> None:
        """Exclui logicamente o registro apos verificar dependencias."""
        self._validar_exclusao(registro)

        registro.excluir(usuario_id)
        registro.situacao = SituacaoCadastro.INATIVO

        # Corta o acesso ao sistema junto com o desligamento: manter a conta
        # ativa apos a exclusao do cadastro seria uma falha de seguranca.
        if registro.usuario_id and registro.usuario:
            registro.usuario.ativo = False

        self._confirmar(f"Falha ao excluir {self.rotulo.lower()}")

        auditoria_service.registrar_exclusao(
            self.modelo.__name__,
            registro.id,
            f"{self.rotulo} excluido: {registro.nome_completo}",
        )
        self._confirmar("Falha ao registrar auditoria", propagar=False)

    def _validar_exclusao(self, registro) -> None:
        """Impede a exclusao quando ha vinculos ativos que a impediriam."""
        if isinstance(registro, Professor):
            vinculos = [v for v in registro.turmas_disciplinas if v.ativa]
            if vinculos:
                raise ErroRegraNegocio(
                    f"Este professor leciona em {len(vinculos)} turma(s). "
                    "Reatribua as disciplinas antes de excluir o cadastro."
                )
            if registro.turmas_regidas:
                raise ErroRegraNegocio(
                    "Este professor e regente de uma ou mais turmas. "
                    "Designe outro regente antes de excluir o cadastro."
                )

        if isinstance(registro, Responsavel) and registro.vinculos_alunos:
            nomes = ", ".join(a.nome_exibicao for a in registro.alunos[:3])
            raise ErroRegraNegocio(
                f"Este responsavel esta vinculado a alunos ({nomes}). "
                "Remova os vinculos antes de excluir o cadastro."
            )

    def restaurar(self, registro):
        """Desfaz a exclusao logica."""
        registro.restaurar()
        registro.situacao = SituacaoCadastro.ATIVO
        self._confirmar(f"Falha ao restaurar {self.rotulo.lower()}")

        auditoria_service.registrar_atualizacao(
            self.modelo.__name__,
            registro.id,
            f"{self.rotulo} restaurado: {registro.nome_completo}",
        )
        self._confirmar("Falha ao registrar auditoria", propagar=False)
        return registro

    # ------------------------------------------------------------------
    # Conta de acesso
    # ------------------------------------------------------------------
    def criar_acesso(self, registro, senha_temporaria: str) -> Usuario:
        """Cria a conta de acesso do cadastro a partir do e-mail informado.

        A senha e temporaria e a troca no primeiro acesso e obrigatoria: a
        secretaria entrega a senha ao usuario, e a partir dai somente ele
        conhece a senha definitiva.
        """
        if registro.usuario_id:
            raise ErroConflito(
                f"Este {self.rotulo.lower()} ja possui conta de acesso."
            )

        email = normalizar_email(registro.email)
        if not email:
            raise ErroValidacao(
                "Informe um e-mail no cadastro antes de criar a conta de acesso.",
                erros_por_campo={"email": ["E-mail obrigatorio para o acesso."]},
            )

        if db.session.query(Usuario).filter(Usuario.email == email).first():
            raise ErroConflito(
                f"Ja existe uma conta de acesso com o e-mail {email}."
            )

        usuario = Usuario(
            nome_completo=registro.nome_completo,
            email=email,
            cpf=registro.cpf,
            telefone=registro.celular or registro.telefone,
            papel=self.papel_padrao or PapelUsuario.SECRETARIA,
            ativo=True,
        )
        usuario.definir_senha(senha_temporaria, exigir_troca=True)

        db.session.add(usuario)
        db.session.flush()  # garante o id antes do vinculo

        registro.usuario_id = usuario.id
        self._confirmar("Falha ao criar conta de acesso")

        auditoria_service.registrar_criacao(
            "Usuario",
            usuario.id,
            f"Conta de acesso criada para {registro.nome_completo} ({email})",
        )
        self._confirmar("Falha ao registrar auditoria", propagar=False)

        return usuario

    # ------------------------------------------------------------------
    def _confirmar(self, mensagem: str, propagar: bool = True) -> None:
        from flask import current_app

        try:
            db.session.commit()
        except IntegrityError as erro:
            db.session.rollback()
            current_app.logger.warning("%s (integridade): %s", mensagem, erro)
            if propagar:
                raise ErroConflito(
                    "Ja existe um registro com estes dados. Verifique CPF, "
                    "e-mail e matricula."
                ) from erro
        except Exception as erro:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.error("%s: %s", mensagem, erro)
            if propagar:
                raise ErroOperacaoBanco() from erro


# ---------------------------------------------------------------------------
# Instancias prontas (uma por tipo de cadastro)
# ---------------------------------------------------------------------------
professores = CadastroPessoa(
    modelo=Professor,
    rotulo="Professor",
    rotulo_plural="Professores",
    campo_identificador="registro_funcional",
    gerador_identificador=Professor.gerar_registro_funcional,
    papel_padrao=PapelUsuario.PROFESSOR,
)

funcionarios = CadastroPessoa(
    modelo=Funcionario,
    rotulo="Funcionario",
    rotulo_plural="Funcionarios",
    campo_identificador="matricula_funcional",
    gerador_identificador=Funcionario.gerar_matricula_funcional,
    papel_padrao=PapelUsuario.SECRETARIA,
)

responsaveis = CadastroPessoa(
    modelo=Responsavel,
    rotulo="Responsavel",
    rotulo_plural="Responsaveis",
    papel_padrao=PapelUsuario.RESPONSAVEL,
)


def cargos_cadastrados() -> list[str]:
    """Cargos ja utilizados, para alimentar o filtro da listagem."""
    linhas = (
        db.session.query(Funcionario.cargo)
        .filter(Funcionario.excluido_em.is_(None), Funcionario.cargo.isnot(None))
        .distinct()
        .order_by(Funcionario.cargo)
        .all()
    )
    return [linha[0] for linha in linhas if linha[0]]
