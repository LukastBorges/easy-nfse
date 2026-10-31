"""Gera o ícone do easyNFSe (opção A de docs/design: o ponto mostarda da marca com o "e" em verde-mata).

O "e" vem da Bricolage Grotesque (static/vendor/fonts) convertido em contorno, para o ícone não depender da fonte.
Gera, a partir de um único desenho:

- static/logo.svg (64 px, README e páginas), static/favicon.svg (32 px, aba do navegador)
- static/apple-touch-icon.png (180 px) e static/logo-512.png
- packaging/icons/easy-nfse.icns (macOS, com a margem do grid de ícones da Apple) e easy-nfse.ico (Windows)

    uv run --with fonttools --with brotli --with playwright --with pillow python scripts/icone.py

O .icns usa o `iconutil` do macOS; em outro sistema, ele é pulado.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
STATIC = RAIZ / "src" / "easy_nfse" / "static"
ICONES = RAIZ / "packaging" / "icons"
FONTE = STATIC / "vendor" / "fonts" / "bricolage-grotesque.woff2"

MOSTARDA_CLARA, MOSTARDA_ESCURA, MATA = "#EBC247", "#AE8210", "#10211A"


def contorno_do_e() -> tuple[str, tuple[float, float, float, float]]:
    """Caminho SVG do "e" (peso 800, tamanho óptico 48, como na prancha aprovada) e a caixa dele, em unidades da fonte (y para cima)."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    fonte = TTFont(FONTE)
    eixos = {a.axisTag for a in fonte["fvar"].axes}
    fonte = instantiateVariableFont(fonte, {k: v for k, v in {"wght": 800, "opsz": 48, "wdth": 100}.items() if k in eixos})
    glifos = fonte.getGlyphSet()
    nome = fonte.getBestCmap()[ord("e")]
    caneta, caixa = SVGPathPen(glifos), BoundsPen(glifos)
    glifos[nome].draw(caneta)
    glifos[nome].draw(caixa)
    return caneta.getCommands(), caixa.bounds


def svg(lado: int, altura_e: float, margem: float = 0, sombra: bool = False) -> str:
    """O ícone num quadrado de `lado`: quadrado mostarda arredondado com o "e" centrado (altura `altura_e` do lado)."""
    caminho, (x0, y0, x1, y1) = contorno_do_e()
    m = lado * margem
    q = lado - 2 * m  # lado do quadrado mostarda
    escala = q * altura_e / (y1 - y0)
    cx, cy = lado / 2 - (x0 + x1) / 2 * escala, lado / 2 + (y0 + y1) / 2 * escala  # centro óptico = centro da caixa
    raio = q * 0.225
    filtro = (f'<filter id="s" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="{lado * .012:.2f}" '
              f'stdDeviation="{lado * .018:.2f}" flood-color="#000" flood-opacity=".35"/></filter>') if sombra else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" role="img" aria-label="easyNFSe">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{MOSTARDA_CLARA}"/><stop offset="1" stop-color="{MOSTARDA_ESCURA}"/></linearGradient>{filtro}</defs>'
        f'<rect x="{m:g}" y="{m:g}" width="{q:g}" height="{q:g}" rx="{raio:.2f}" fill="url(#g)"{" filter=\"url(#s)\"" if sombra else ""}/>'
        f'<rect x="{m + lado * .006:.2f}" y="{m + lado * .006:.2f}" width="{q - lado * .012:.2f}" height="{q - lado * .012:.2f}" '
        f'rx="{raio:.2f}" fill="none" stroke="#FFF5C8" stroke-opacity=".35" stroke-width="{lado * .008:.2f}"/>'
        f'<path transform="translate({cx:.2f} {cy:.2f}) scale({escala:.5f} {-escala:.5f})" d="{caminho}" fill="{MATA}"/>'
        f"</svg>"
    )


def rasterizar(pedidos: list[tuple[str, int, Path]]) -> None:
    """Renderiza SVGs em PNG (fundo transparente) com o Chromium do Playwright."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        nav = p.chromium.launch()
        for codigo, tamanho, destino in pedidos:
            pg = nav.new_page(viewport={"width": tamanho, "height": tamanho})
            pg.set_content(f'<html><body style="margin:0;background:transparent">'
                           f'{codigo.replace("<svg ", f"<svg width=\"{tamanho}\" height=\"{tamanho}\" ", 1)}</body></html>')
            destino.parent.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(destino), omit_background=True)
            pg.close()
        nav.close()


def main() -> None:
    from PIL import Image

    plano = svg(64, 0.5)  # sem margem: README, páginas e Windows
    (STATIC / "logo.svg").write_text(plano + "\n", encoding="utf-8")
    (STATIC / "favicon.svg").write_text(svg(32, 0.56) + "\n", encoding="utf-8")  # "e" um pouco maior em 16 px
    mac = svg(1024, 0.5, margem=100 / 1024, sombra=True)  # grid da Apple: 824 px de 1024, com sombra

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        conjunto = tmp / "easy-nfse.iconset"
        pedidos = [(plano, 180, STATIC / "apple-touch-icon.png"), (plano, 512, STATIC / "logo-512.png")]
        pedidos += [(plano, t, tmp / f"ico-{t}.png") for t in (16, 24, 32, 48, 64, 128, 256)]
        for base in (16, 32, 128, 256, 512):
            pedidos += [(mac, base, conjunto / f"icon_{base}x{base}.png"), (mac, base * 2, conjunto / f"icon_{base}x{base}@2x.png")]
        rasterizar(pedidos)

        imagens = [Image.open(tmp / f"ico-{t}.png") for t in (16, 24, 32, 48, 64, 128, 256)]
        imagens[-1].save(ICONES / "easy-nfse.ico", sizes=[i.size for i in imagens], append_images=imagens[:-1])
        if shutil.which("iconutil"):
            subprocess.run(["iconutil", "-c", "icns", str(conjunto), "-o", str(ICONES / "easy-nfse.icns")], check=True)
        else:
            print("iconutil não encontrado (só no macOS): o .icns não foi atualizado")
    for arq in ("logo.svg", "favicon.svg", "apple-touch-icon.png", "logo-512.png"):
        print(STATIC / arq)
    print(ICONES / "easy-nfse.ico", ICONES / "easy-nfse.icns", sep="\n")


if __name__ == "__main__":
    main()
