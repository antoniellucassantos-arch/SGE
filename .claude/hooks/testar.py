"""Roda a suite de testes ao fim do turno.

Chamado pelo hook ``Stop`` (ver ``.claude/settings.json``).

Por que no fim do turno, e nao a cada edicao: a suite leva cerca de um
minuto. Rodando a cada `Edit`, uma sequencia de dez ajustes custaria dez
minutos parados — e o resultado do meio da sequencia nem interessa, porque o
codigo esta incompleto por construcao. No fim do turno o codigo esta no
estado que se pretendia entregar, que e quando "passou ou nao passou" tem
significado.

Falha nao bloqueia o turno: devolve o resumo para o modelo pela saida
padrao, em JSON, para que a proxima acao ja saiba o que quebrou.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

CANDIDATOS_PYTHON = (
    RAIZ / "venv" / "Scripts" / "python.exe",  # Windows
    RAIZ / "venv" / "bin" / "python",  # Linux e macOS
    RAIZ / ".venv" / "Scripts" / "python.exe",
    RAIZ / ".venv" / "bin" / "python",
)

#: Limite generoso: a suite completa leva cerca de um minuto.
TEMPO_LIMITE = 300


def _interpretador() -> str | None:
    for candidato in CANDIDATOS_PYTHON:
        if candidato.exists():
            return str(candidato)
    return None


def _ultima_linha_util(saida: str) -> str:
    """Devolve o resumo do pytest (`N passed`, `N failed`, ...)."""
    for linha in reversed(saida.strip().splitlines()):
        if linha.strip():
            return linha.strip()
    return "sem saida"


def main() -> int:
    python = _interpretador()
    if python is None:
        # Sem venv nao ha o que rodar, e reclamar disso a cada turno seria
        # ruido — quem clonou o projeto ainda nao instalou nada.
        return 0

    try:
        processo = subprocess.run(  # noqa: S603 - argumentos controlados
            [python, "-m", "pytest", "-q", "--no-header", "-x"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            check=False,
            timeout=TEMPO_LIMITE,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as erro:
        print(json.dumps({"systemMessage": f"Testes nao rodaram: {erro}"}))
        return 0

    resumo = _ultima_linha_util(processo.stdout or processo.stderr or "")

    if processo.returncode == 0:
        print(json.dumps({"suppressOutput": True}))
        return 0

    # `-x` para no primeiro erro: o objetivo e avisar que quebrou, nao
    # produzir o relatorio completo. O detalhe sai quando alguem rodar a
    # suite de proposito.
    detalhe = (processo.stdout or "")[-2000:]
    print(
        json.dumps(
            {
                "systemMessage": f"Suite de testes falhando: {resumo}",
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "additionalContext": (
                        "A suite de testes falhou apos as alteracoes deste "
                        f"turno.\n\n{detalhe}"
                    ),
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
