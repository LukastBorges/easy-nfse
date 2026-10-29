"""Sincroniza os ícones Tabler (https://tabler.io/icons, MIT) usados pelo app.

Procura, nas linhas dos templates e do código que contêm "icone", strings entre aspas que sejam nomes
de ícones outline do Tabler (pega `icone('nome')`, `icone('a' if x else 'b')` e dicionários como
`{% set icones = {...} %}`), baixa só esses SVGs da versão fixada abaixo e grava em `static/vendor/tabler-icons/`, já sem atributos de tamanho/classe (o helper
`icone` de `app.py` põe a classe). Ícones que deixaram de ser usados são apagados.

    uv run python scripts/icones_tabler.py
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

VERSAO = "3.49.0"
URL = f"https://cdn.jsdelivr.net/npm/@tabler/icons@{VERSAO}"
RAIZ = Path(__file__).resolve().parents[1]
PACOTE = RAIZ / "src" / "easy_nfse"
DESTINO = PACOTE / "static" / "vendor" / "tabler-icons"
CANDIDATO = re.compile(r"""["']([a-z0-9]+(?:-[a-z0-9]+)*)["']""")


def usados(existentes: set[str]) -> set[str]:
    nomes: set[str] = set()
    for arq in [*PACOTE.rglob("*.html"), *PACOTE.rglob("*.py")]:
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if "icone" in linha:
                nomes.update(CANDIDATO.findall(linha))
    return nomes & existentes


def minificar(svg: str) -> str:
    svg = re.sub(r'<path stroke="none" d="M0 0h24v24H0z" fill="none"\s*/>', "", svg)
    svg = re.sub(r'\s(?:width|height|class)="[^"]*"', "", svg)
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", svg)).strip() + "\n"


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as cli:
        nomes = usados(set(cli.get(f"{URL}/tabler-nodes-outline.json").raise_for_status().json()))
        (DESTINO / "LICENSE").write_text(cli.get(f"{URL}/LICENSE").raise_for_status().text, encoding="utf-8")
        for nome in sorted(nomes):
            arq = DESTINO / f"{nome}.svg"
            if not arq.exists():
                arq.write_text(minificar(cli.get(f"{URL}/icons/outline/{nome}.svg").raise_for_status().text),
                               encoding="utf-8")
                print("+", nome)
    for arq in DESTINO.glob("*.svg"):
        if arq.stem not in nomes:
            arq.unlink()
            print("-", arq.stem)
    (DESTINO / "VERSION").write_text(VERSAO + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
