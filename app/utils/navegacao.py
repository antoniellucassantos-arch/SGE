"""Validacao de destinos de redirecionamento.

Todo redirecionamento cujo destino venha do cliente — parametro ``next``,
cabecalho ``Referer`` — precisa passar por aqui.

Por que isso importa
--------------------
Um *open redirect* permite que um link aparentemente legitimo
(``https://sge.escola.com.br/auth/login?next=https://sge-falso.example``)
jogue o usuario recem-autenticado para fora do dominio, tipicamente numa
copia da tela de login. A vitima ja confia no endereco que clicou, e a URL
de partida e mesmo a da escola — por isso o golpe funciona.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from flask import request, url_for


def destino_seguro(url: str | None, padrao: str | None = None) -> str:
    """Devolve ``url`` apenas se ela apontar para o proprio host.

    Args:
        url: Destino pretendido, vindo do cliente (``next``, ``Referer``).
        padrao: Para onde ir quando o destino for recusado. Sem valor,
            usa o painel principal.

    Returns:
        A URL original, quando interna; caso contrario, o padrao.

    O tratamento cobre tres formas de escapar do host:

    - **absoluta** — ``https://externo.example/x``
    - **relativa ao protocolo** — ``//externo.example/x``, que o navegador
      resolve como externa mesmo sem esquema explicito;
    - **com credenciais embutidas** — ``https://escola.com.br@externo.example``,
      que engana a leitura humana mas nao o ``urlparse``.
    """
    padrao = padrao or url_for("painel.index")

    if not url:
        return padrao

    url = url.strip()
    if not url:
        return padrao

    # `//host/x` nao tem esquema, porem e absoluta para o navegador.
    # `urljoin` a resolve contra o host atual, revelando o destino real.
    partes = urlparse(urljoin(request.host_url, url))

    if partes.scheme and partes.scheme not in ("http", "https"):
        # Bloqueia javascript:, data:, file: e afins.
        return padrao

    if partes.netloc and partes.netloc != urlparse(request.host_url).netloc:
        return padrao

    caminho = partes.path or "/"
    if partes.query:
        caminho = f"{caminho}?{partes.query}"

    return caminho


def destino_pos_login(url: str | None) -> str:
    """Destino apos autenticar, evitando devolver o usuario ao proprio login."""
    destino = destino_seguro(url)

    if destino.startswith(url_for("auth.login")):
        return url_for("painel.index")

    return destino
