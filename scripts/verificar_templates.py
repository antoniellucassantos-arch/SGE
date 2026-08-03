"""Impede ``<script>`` inline nos templates.

A Content-Security-Policy do sistema e ``script-src 'self'``: o navegador
recusa qualquer script inline. A falha e silenciosa do pior jeito — a pagina
carrega, o grafico simplesmente nao aparece, e nada vai para o log do
servidor. Quem for investigar so descobre abrindo o console do navegador.

Dado que o JavaScript precisa ler vai por atributo ``data-*`` (com
``|tojson``) ou por ``<script type="application/json">``, lido com
``JSON.parse``. Nunca gerado como codigo.

Uso::

    python scripts/verificar_templates.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES = RAIZ / "app" / "templates"

TAG_SCRIPT = re.compile(r"<script\b[^>]*>", re.IGNORECASE)

#: Um `<script>` e aceitavel quando carrega arquivo (`src=`) ou quando
#: carrega dado nao executavel (`type="application/json"`).
PERMITIDOS = ("src=", 'type="application/json"', "type='application/json'")


def main() -> int:
    if not TEMPLATES.exists():
        return 0

    problemas: list[str] = []

    for arquivo in sorted(TEMPLATES.rglob("*.html")):
        try:
            texto = arquivo.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for numero, linha in enumerate(texto.splitlines(), start=1):
            for tag in TAG_SCRIPT.findall(linha):
                if any(marca in tag for marca in PERMITIDOS):
                    continue
                relativo = arquivo.relative_to(RAIZ)
                problemas.append(f"{relativo}:{numero}: {tag}")

    if problemas:
        print("Script inline quebra em silencio sob a CSP script-src 'self'.")
        print("Passe o dado por data-* ou <script type=\"application/json\">.")
        print("Ver CLAUDE.md, secao Frontend.\n")
        for problema in problemas:
            print(f"  {problema}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
