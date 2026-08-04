"""Corrige o arquivo Python recem-editado.

Chamado pelo hook ``PostToolUse`` (ver ``.claude/settings.json``). Recebe o
payload do hook em JSON pela entrada padrao e roda, no arquivo indicado::

    ruff check --fix <arquivo>

Sobre o ``ruff format``, que a auditoria previa aqui: ele **nao** entra.
Reformatar o projeto reescreveria 73 dos 142 arquivos, e em alguns o
resultado e pior. A matriz de permissoes agrupa por recurso::

    _P.TURMA_VISUALIZAR, _P.TURMA_CRIAR, _P.TURMA_EDITAR,

O formatador quebra isso em uma constante por linha, triplica o tamanho do
bloco e acaba com a leitura de relance — que e justamente o que torna a
matriz auditavel. O ``ruff check`` continua cuidando de import fora de
ordem, variavel nao usada e o resto do lint de verdade.

Por que um script, e nao um comando de uma linha no settings.json:

* a maquina de desenvolvimento e Windows e o servidor e Linux — o caminho
  do interpretador do venv muda, e aqui da para procurar os dois;
* o projeto nao depende de ``jq``, entao a extracao do caminho e feita com a
  biblioteca padrao;
* um script tem lugar para comentario. Um one-liner com pipe e ``read`` nao
  tem, e daqui a seis meses ninguem sabe por que ele existe.

Nunca falha o hook: formatacao que quebra a edicao atrapalha mais do que
ajuda. Erros vao para a saida de erro e o codigo de saida e sempre zero.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

#: Candidatos a interpretador do ambiente virtual, na ordem de preferencia.
CANDIDATOS_PYTHON = (
    RAIZ / "venv" / "Scripts" / "python.exe",  # Windows
    RAIZ / "venv" / "bin" / "python",  # Linux e macOS
    RAIZ / ".venv" / "Scripts" / "python.exe",
    RAIZ / ".venv" / "bin" / "python",
)


def _interpretador() -> str:
    for candidato in CANDIDATOS_PYTHON:
        if candidato.exists():
            return str(candidato)
    return sys.executable


def _caminho_editado(payload: dict) -> Path | None:
    """Extrai o arquivo alvo do payload do hook."""
    bruto = payload.get("tool_input", {}).get("file_path") or payload.get(
        "tool_response", {}
    ).get("filePath")
    if not bruto:
        return None

    caminho = Path(bruto)
    if caminho.suffix != ".py" or not caminho.exists():
        return None

    # Nao mexe em nada fora do projeto: o hook pode ser disparado por uma
    # edicao em arquivo temporario ou em outro repositorio aberto na sessao.
    try:
        caminho.resolve().relative_to(RAIZ)
    except ValueError:
        return None

    # Migrations sao geradas pelo Alembic e ficam de fora do ruff (ver o
    # `exclude` no pyproject.toml). Reformata-las so criaria ruido no diff.
    if "migrations" in caminho.resolve().parts:
        return None

    return caminho


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    alvo = _caminho_editado(payload)
    if alvo is None:
        return 0

    try:
        subprocess.run(  # noqa: S603 - argumentos controlados
            [
                _interpretador(),
                "-m",
                "ruff",
                "check",
                "--fix",
                # F401 (import nao usado) fica de fora do --fix aqui, e so
                # aqui. No meio de uma edicao um import quase sempre e
                # adicionado *antes* do codigo que o usa: apagado nesse
                # instante, o erro so aparece na proxima execucao dos testes,
                # como um NameError que parece nao ter causa. Aconteceu.
                # O pre-commit e o CI continuam limpando import morto.
                "--unfixable",
                "F401",
                "--quiet",
                str(alvo),
            ],
            cwd=RAIZ,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as erro:
        print(f"[hook formatar] {erro}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
