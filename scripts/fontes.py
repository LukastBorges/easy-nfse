"""Baixa as fontes da identidade visual para `static/vendor/fonts/` (o app funciona sem internet).

Bricolage Grotesque (títulos, valores e marca; eixos de peso e tamanho óptico) e Public Sans (interface), ambas
variáveis, subconjunto latino (cobre o português), dos pacotes do Fontsource numa versão fixada. As licenças
(SIL Open Font License 1.1) vão junto.

    uv run python scripts/fontes.py
"""

from __future__ import annotations

from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "src" / "easy_nfse" / "static" / "vendor" / "fonts"

# pacote do Fontsource -> (versão, {arquivo no pacote: nome local})
FONTES = {
    "@fontsource-variable/bricolage-grotesque": ("5.2.10", {
        "files/bricolage-grotesque-latin-standard-normal.woff2": "bricolage-grotesque.woff2",
        "LICENSE": "bricolage-grotesque-OFL.txt",
    }),
    "@fontsource-variable/public-sans": ("5.2.7", {
        "files/public-sans-latin-wght-normal.woff2": "public-sans.woff2",
        "files/public-sans-latin-wght-italic.woff2": "public-sans-italic.woff2",
        "LICENSE": "public-sans-OFL.txt",
    }),
}


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as cliente:
        for pacote, (versao, arquivos) in FONTES.items():
            for origem, local in arquivos.items():
                resposta = cliente.get(f"https://cdn.jsdelivr.net/npm/{pacote}@{versao}/{origem}")
                resposta.raise_for_status()
                (DESTINO / local).write_bytes(resposta.content)
                print(f"{local}: {len(resposta.content) // 1024} KB")
    (DESTINO / "VERSAO").write_text(
        "".join(f"{p}@{v}\n" for p, (v, _) in FONTES.items()), encoding="utf-8")


if __name__ == "__main__":
    main()
