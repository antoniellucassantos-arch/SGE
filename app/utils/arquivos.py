"""Tratamento seguro de uploads (fotos de alunos, logo da escola, anexos).

Upload e uma das superficies de ataque mais exploradas em aplicacoes web.
As defesas aplicadas aqui, em camadas:

1. **Extensao na lista de permissao** — nunca lista de bloqueio.
2. **Validacao do conteudo real** — a imagem e aberta e verificada pelo
   Pillow. Um ``.php`` renomeado para ``.jpg`` falha nesta etapa.
3. **Nome gerado pelo servidor** — o nome enviado pelo usuario e descartado,
   o que elimina *path traversal* (``../../etc/passwd``) e colisoes.
4. **Reencodificacao da imagem** — a imagem e redimensionada e regravada,
   descartando metadados EXIF (que podem conter geolocalizacao de um aluno)
   e qualquer payload escondido no arquivo original.
5. **Limite de tamanho** — aplicado pelo Flask via ``MAX_CONTENT_LENGTH``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from app.services.excecoes import ErroArquivo

#: Assinaturas binarias aceitas (defesa adicional a extensao).
ASSINATURAS_IMAGEM: tuple[bytes, ...] = (
    b"\xff\xd8\xff",       # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"RIFF",               # WEBP (container RIFF)
)


def extensao_permitida(nome_arquivo: str, permitidas: set[str] | None = None) -> bool:
    """Verifica a extensao contra a lista de permissao configurada."""
    if not nome_arquivo or "." not in nome_arquivo:
        return False

    permitidas = permitidas or current_app.config.get(
        "EXTENSOES_IMAGEM_PERMITIDAS", {"png", "jpg", "jpeg", "webp"}
    )
    return nome_arquivo.rsplit(".", 1)[1].lower() in permitidas


def gerar_nome_arquivo(extensao: str) -> str:
    """Gera um nome de arquivo opaco, baseado em UUID.

    O nome nao carrega **nenhuma** informacao sobre o dono: nada de CPF,
    id ou carimbo de data. Assim, mesmo que uma URL vaze, ela nao revela de
    quem e o arquivo nem permite enumerar os demais.
    """
    return f"{uuid.uuid4().hex}.{extensao.lower().lstrip('.')}"


def _pasta_destino(subpasta: str) -> Path:
    """Resolve (e cria) a pasta de destino, fora de ``static/``.

    Servir uploads por ``static/`` significaria entregar foto de aluno a
    qualquer pessoa com a URL, sem autenticacao. Aqui os arquivos ficam em
    ``uploads/`` na raiz do projeto e so saem por rota autenticada.
    """
    base = Path(current_app.config["PASTA_UPLOADS"]) / subpasta
    base.mkdir(parents=True, exist_ok=True)
    return base


def _validar_assinatura(arquivo: FileStorage) -> None:
    """Confere os primeiros bytes contra as assinaturas conhecidas."""
    arquivo.stream.seek(0)
    cabecalho = arquivo.stream.read(12)
    arquivo.stream.seek(0)

    if not any(cabecalho.startswith(assinatura) for assinatura in ASSINATURAS_IMAGEM):
        raise ErroArquivo(
            "O arquivo enviado nao e uma imagem valida. "
            "Envie um arquivo PNG, JPG ou WEBP."
        )


def salvar_imagem(
    arquivo: FileStorage | None,
    subpasta: str,
    prefixo: str = "img",
    largura_maxima: int | None = None,
    quadrada: bool = False,
) -> str | None:
    """Valida, normaliza e grava uma imagem enviada pelo usuario.

    Args:
        arquivo: Campo de upload do formulario.
        subpasta: Pasta sob ``static/uploads`` (``alunos``, ``escola``...).
        prefixo: Prefixo legivel do nome final.
        largura_maxima: Redimensiona proporcionalmente se exceder.
        quadrada: Recorta ao centro em proporcao 1:1 (fotos de perfil).

    Returns:
        O nome do arquivo gravado, ou ``None`` se nada foi enviado.

    Raises:
        ErroArquivo: extensao, conteudo ou gravacao invalidos.
    """
    if not arquivo or not arquivo.filename:
        return None

    if not extensao_permitida(arquivo.filename):
        permitidas = ", ".join(
            sorted(current_app.config.get("EXTENSOES_IMAGEM_PERMITIDAS", []))
        )
        raise ErroArquivo(f"Formato nao permitido. Use: {permitidas}.")

    _validar_assinatura(arquivo)

    largura_maxima = largura_maxima or current_app.config.get(
        "FOTO_LARGURA_MAXIMA", 800
    )

    try:
        imagem = Image.open(arquivo.stream)
        # verify() invalida o objeto para leitura; reabrimos em seguida.
        imagem.verify()
        arquivo.stream.seek(0)
        imagem = Image.open(arquivo.stream)

        # Aplica a rotacao registrada no EXIF e descarta os metadados:
        # fotos de celular costumam carregar geolocalizacao, dado sensivel
        # que nao deve ir para o servidor da escola (LGPD).
        imagem = _corrigir_orientacao(imagem)

        if imagem.mode not in ("RGB", "L"):
            imagem = imagem.convert("RGB")

        if quadrada:
            imagem = _recortar_centro(imagem)

        if imagem.width > largura_maxima:
            proporcao = largura_maxima / imagem.width
            nova_altura = int(imagem.height * proporcao)
            imagem = imagem.resize(
                (largura_maxima, nova_altura), Image.Resampling.LANCZOS
            )

        nome = gerar_nome_arquivo("jpg")
        caminho = _pasta_destino(subpasta) / nome
        imagem.save(caminho, "JPEG", quality=85, optimize=True)

        return nome

    except UnidentifiedImageError as erro:
        raise ErroArquivo(
            "Nao foi possivel ler a imagem enviada. Tente outro arquivo."
        ) from erro
    except OSError as erro:
        current_app.logger.error("Falha ao gravar imagem: %s", erro)
        raise ErroArquivo(
            "Nao foi possivel salvar a imagem. Tente novamente."
        ) from erro


def _corrigir_orientacao(imagem: Image.Image) -> Image.Image:
    """Aplica a orientacao EXIF para que a foto nao apareca deitada."""
    try:
        exif = imagem.getexif()
        orientacao = exif.get(274)  # tag padrao "Orientation"
        if orientacao == 3:
            imagem = imagem.rotate(180, expand=True)
        elif orientacao == 6:
            imagem = imagem.rotate(270, expand=True)
        elif orientacao == 8:
            imagem = imagem.rotate(90, expand=True)
    except (AttributeError, KeyError, TypeError, ValueError):
        pass  # imagem sem EXIF: nada a corrigir
    return imagem


def _recortar_centro(imagem: Image.Image) -> Image.Image:
    """Recorta a imagem em proporcao 1:1 a partir do centro."""
    largura, altura = imagem.size
    if largura == altura:
        return imagem

    lado = min(largura, altura)
    esquerda = (largura - lado) // 2
    topo = (altura - lado) // 2
    return imagem.crop((esquerda, topo, esquerda + lado, topo + lado))


def remover_arquivo(nome: str | None, subpasta: str) -> bool:
    """Remove um arquivo de upload, ignorando ausencia.

    Valida que o caminho resolvido permanece dentro da pasta esperada: mesmo
    que um nome adulterado chegue ate aqui, ele nao consegue apagar arquivos
    fora do diretorio de uploads.
    """
    if not nome:
        return False

    try:
        pasta = _pasta_destino(subpasta).resolve()
        caminho = (pasta / nome).resolve()

        if not caminho.is_relative_to(pasta):
            current_app.logger.warning(
                "Tentativa de remocao fora da pasta de uploads: %s", nome
            )
            return False

        if caminho.exists():
            caminho.unlink()
            return True

    except OSError as erro:
        current_app.logger.warning("Falha ao remover arquivo %s: %s", nome, erro)

    return False


def responder_arquivo(subpasta: str, nome: str | None):
    """Entrega um upload ao navegador, validando o caminho resolvido.

    Usada pelas rotas autenticadas de foto. A validacao de **quem** pode ver
    o arquivo e responsabilidade do decorador de escopo na rota; aqui
    garantimos apenas que o caminho nao escapa da pasta de uploads.

    Raises:
        RegistroNaoEncontrado: arquivo ausente ou caminho fora da pasta.
    """
    from flask import send_from_directory

    from app.services.excecoes import RegistroNaoEncontrado

    if not nome:
        raise RegistroNaoEncontrado("Arquivo nao encontrado.")

    pasta = _pasta_destino(subpasta).resolve()
    caminho = (pasta / nome).resolve()

    # Mesmo com o nome vindo do banco, um valor adulterado nao pode servir
    # arquivos de fora da pasta (path traversal).
    if not caminho.is_relative_to(pasta) or not caminho.is_file():
        raise RegistroNaoEncontrado("Arquivo nao encontrado.")

    resposta = send_from_directory(pasta, caminho.name)

    # Foto de aluno e dado pessoal: nao pode ficar em cache compartilhado.
    resposta.headers["Cache-Control"] = "private, max-age=300"
    return resposta


def substituir_imagem(
    arquivo: FileStorage | None,
    nome_atual: str | None,
    subpasta: str,
    prefixo: str = "img",
    **opcoes,
) -> str | None:
    """Grava a nova imagem e remove a anterior somente apos o sucesso.

    A ordem importa: apagar antes de gravar deixaria o registro sem imagem
    caso a gravacao falhasse.
    """
    novo_nome = salvar_imagem(arquivo, subpasta, prefixo, **opcoes)
    if novo_nome and nome_atual:
        remover_arquivo(nome_atual, subpasta)
    return novo_nome or nome_atual
