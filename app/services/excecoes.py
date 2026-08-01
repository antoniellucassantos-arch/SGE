"""Excecoes de dominio do SGE.

Por que excecoes proprias em vez de ``abort()`` direto?
------------------------------------------------------
Os services precisam poder ser chamados de qualquer lugar — rota web, CLI,
seed, testes e futura API mobile. Se lancassem ``abort(400)``, ficariam
acoplados ao ciclo de requisicao HTTP do Flask.

Com excecoes de dominio, cada camada decide como reagir: a rota web
transforma em ``flash`` + redirect, a API transformaria em JSON com o codigo
correto, e o teste simplesmente verifica a excecao.
"""

from __future__ import annotations


class ErroDominio(Exception):
    """Raiz da hierarquia. Toda excecao previsivel do SGE herda daqui."""

    mensagem_padrao = "Nao foi possivel concluir a operacao."
    codigo_http = 400

    def __init__(self, mensagem: str | None = None, **contexto) -> None:
        self.mensagem = mensagem or self.mensagem_padrao
        self.contexto = contexto
        super().__init__(self.mensagem)

    def __str__(self) -> str:
        return self.mensagem


class ErroValidacao(ErroDominio):
    """Dados de entrada invalidos segundo as regras de negocio.

    Distinto da validacao de formulario: cobre regras que dependem do estado
    do banco (ex.: "esta turma ja atingiu a capacidade maxima").
    """

    mensagem_padrao = "Os dados informados sao invalidos."
    codigo_http = 400

    def __init__(
        self,
        mensagem: str | None = None,
        erros_por_campo: dict[str, list[str]] | None = None,
        **contexto,
    ) -> None:
        super().__init__(mensagem, **contexto)
        self.erros_por_campo = erros_por_campo or {}


class ErroRegraNegocio(ErroDominio):
    """Operacao valida em forma, porem proibida pelas regras da escola."""

    mensagem_padrao = "Esta operacao nao e permitida pelas regras do sistema."
    codigo_http = 409


class RegistroNaoEncontrado(ErroDominio):
    """Entidade inexistente ou fora do escopo de acesso do usuario.

    Usada tambem quando o registro existe mas o usuario nao tem escopo sobre
    ele, para nao revelar a existencia do dado (evita enumeracao de ids).
    """

    mensagem_padrao = "Registro nao encontrado."
    codigo_http = 404


class ErroPermissao(ErroDominio):
    """Usuario autenticado sem autorizacao para a operacao."""

    mensagem_padrao = "Voce nao tem permissao para executar esta acao."
    codigo_http = 403


class ErroAutenticacao(ErroDominio):
    """Falha de credenciais ou conta indisponivel."""

    mensagem_padrao = "Nao foi possivel autenticar."
    codigo_http = 401


class ErroConflito(ErroDominio):
    """Violacao de unicidade (CPF, e-mail, codigo ja cadastrado)."""

    mensagem_padrao = "Ja existe um registro com estes dados."
    codigo_http = 409


class ErroArquivo(ErroDominio):
    """Falha ao processar upload: tipo, tamanho ou conteudo invalido."""

    mensagem_padrao = "Nao foi possivel processar o arquivo enviado."
    codigo_http = 400


class ErroOperacaoBanco(ErroDominio):
    """Falha inesperada de persistencia, ja com rollback aplicado."""

    mensagem_padrao = (
        "Ocorreu um erro ao gravar os dados. Nenhuma alteracao foi salva."
    )
    codigo_http = 500


__all__ = [
    "ErroDominio",
    "ErroValidacao",
    "ErroRegraNegocio",
    "RegistroNaoEncontrado",
    "ErroPermissao",
    "ErroAutenticacao",
    "ErroConflito",
    "ErroArquivo",
    "ErroOperacaoBanco",
]
