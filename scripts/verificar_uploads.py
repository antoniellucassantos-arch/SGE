"""Impede que uploads voltem para dentro de ``app/static/``.

Tudo em ``static/`` e servido diretamente pelo servidor web, sem passar por
``@login_required`` nem por checagem de escopo. Foi assim que a foto de
aluno ficou acessivel por URL direta, sem login — item 1.5 da auditoria.

A regressao e facil: basta alguem achar mais pratico salvar o arquivo perto
do CSS. Este verificador roda no pre-commit e no CI.

Uso::

    python scripts/verificar_uploads.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
STATIC = RAIZ / "app" / "static"

#: Subpastas legitimas de ``static/``. Qualquer outra e suspeita.
PASTAS_ESPERADAS = frozenset({"css", "js", "img", "vendor", "favicon"})

#: Trechos que indicam upload sendo gravado dentro de ``static/``.
PADROES_PROIBIDOS = (
    'static" / "uploads',
    "static/uploads",
    'static", "uploads',
)


def _pastas_inesperadas() -> list[Path]:
    if not STATIC.exists():
        return []
    return [
        caminho
        for caminho in STATIC.iterdir()
        if caminho.is_dir() and caminho.name not in PASTAS_ESPERADAS
    ]


def _codigo_apontando_para_static() -> list[str]:
    ocorrencias: list[str] = []
    for arquivo in RAIZ.rglob("*.py"):
        partes = arquivo.relative_to(RAIZ).parts
        if partes[0] in {"venv", ".venv", "migrations", "scripts"}:
            continue

        try:
            texto = arquivo.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for numero, linha in enumerate(texto.splitlines(), start=1):
            if any(padrao in linha for padrao in PADROES_PROIBIDOS):
                relativo = arquivo.relative_to(RAIZ)
                ocorrencias.append(f"{relativo}:{numero}: {linha.strip()}")

    return ocorrencias


def main() -> int:
    problemas: list[str] = []

    for pasta in _pastas_inesperadas():
        problemas.append(
            f"pasta inesperada em app/static/: {pasta.name}/ "
            "(uploads vao para uploads/ na raiz, servidos por rota autenticada)"
        )

    problemas.extend(_codigo_apontando_para_static())

    if problemas:
        print("Upload dentro de app/static/ e servido sem autenticacao.")
        print("Sao dados pessoais de menores de idade. Ver CLAUDE.md.\n")
        for problema in problemas:
            print(f"  {problema}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
