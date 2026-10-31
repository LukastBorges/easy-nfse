"""Monta os conceitos visuais (HTML autônomos) e, opcionalmente, renderiza PNGs com Playwright.

Os arquivos `0*.html` desta pasta são fragmentos: `{{header:Nome}}` vira o cabeçalho com o item ativo e
`{{icon:nome}}` / `{{icon:nome:classe}}` vira o SVG Tabler de `static/vendor/tabler-icons`. O primeiro
`<style>` de cada fragmento é a folha da tela; `base.css` é a base comum (as regras de celular, a partir do
comentário "celular", entram por último para ganhar das regras da tela).

    uv run python docs/design/conceitos/renderizar.py                 # só monta os HTML em build/conceitos
    uv run --with playwright python docs/design/conceitos/renderizar.py --png [tela ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAIDA = RAIZ / "build" / "conceitos"
ICONES = RAIZ / "src" / "easy_nfse" / "static" / "vendor" / "tabler-icons"

NAV = [("home", "Início", "01-inicio.html"), ("template", "Templates", "05-templates.html"),
       ("address-book", "Cadastros", "06-cadastros.html"), ("history", "Histórico", "03-historico.html"),
       ("settings", "Configurações", "07-configuracoes.html")]
MARCA = '<a class="marca" href="#"><b>easy<span>NFSe</span><i></i></b></a>'
MARCA_MOVEL = "/* ---------- celular"

# Indicador do menu: um único realce que desliza até o item clicado. Ao clicar, ele corre até o destino e só
# então a página troca; ao abrir uma página por outro caminho, ele sai do item da página anterior (sessionStorage).
SCRIPT = """
(() => {
  const ler = k => { try { return sessionStorage.getItem(k); } catch { return null; } };
  const gravar = (k, v) => { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch {} };
  const nav = document.querySelector('.nav');
  if (nav) document.fonts.ready.then(() => {
    const luz = nav.querySelector('.nav-luz');
    const links = [...nav.querySelectorAll('a[data-nav]')];
    const ativo = links.find(a => a.classList.contains('ativo'));
    const calmo = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const por = (a, animar) => {
      luz.classList.toggle('sem-transicao', !animar || calmo);
      luz.style.width = a.offsetWidth + 'px';
      luz.style.transform = 'translateX(' + a.offsetLeft + 'px)';
      void luz.offsetWidth;
    };
    nav.classList.add('com-luz');
    const anterior = links.find(a => a.dataset.nav === ler('nav-anterior'));
    const jaMovido = ler('nav-movido') === (ativo && ativo.dataset.nav);
    gravar('nav-movido', null);
    if (ativo) {
      luz.style.opacity = 1;
      if (anterior && anterior !== ativo && !jaMovido && !calmo) {
        por(anterior, false);
        requestAnimationFrame(() => por(ativo, true));
      } else por(ativo, false);
      gravar('nav-anterior', ativo.dataset.nav);
    }
    links.forEach(a => a.addEventListener('click', e => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button || a === ativo) return;
      e.preventDefault();
      links.forEach(l => { l.classList.toggle('ativo', l === a); l.toggleAttribute('aria-current', l === a); });
      if (!ativo) { por(a, false); luz.style.opacity = 1; }
      por(a, true);
      gravar('nav-anterior', a.dataset.nav);
      gravar('nav-movido', a.dataset.nav);
      setTimeout(() => { location.href = a.href; }, calmo ? 0 : 420);
    }));
    addEventListener('resize', () => { const a = nav.querySelector('a.ativo'); if (a) por(a, false); });
  });
  // dentro da página de conceitos (iframe), avisa qual tela está aberta para as abas de fora acompanharem
  try { if (parent !== window) parent.postMessage({ tela: location.pathname.split('/').pop() }, '*'); } catch {}
})();
"""

# (tela, largura, altura, página inteira)
TELAS = [
    ("08-boas-vindas", 1440, 900, True), ("01-inicio", 1440, 900, False), ("02-emissao", 1440, 900, False), ("03-historico", 1440, 900, False),
    ("05-templates", 1440, 900, True), ("06-cadastros", 1440, 900, True), ("07-configuracoes", 1440, 900, True),
    ("00-identidade", 1440, 1000, True), ("04-logos", 1440, 1000, True),
    ("08-boas-vindas", 390, 844, True), ("01-inicio", 390, 844, False), ("05-templates", 390, 844, True), ("06-cadastros", 390, 844, True),
    ("07-configuracoes", 390, 844, True),
]


def icone(nome: str, classes: str = "ico") -> str:
    svg = (ICONES / f"{nome}.svg").read_text(encoding="utf-8").strip()
    return svg.replace("<svg ", f'<svg class="{classes}" ', 1)


def cabecalho(ativo: str) -> str:
    links = "".join(
        f'<a href="{h}" data-nav="{n}" class="{"ativo" if n == ativo else ""}"'
        f'{' aria-current="page"' if n == ativo else ""}>{icone(i)}<span>{n}</span></a>' for i, n, h in NAV)
    return (f'<header class="topo"><div class="faixa">{MARCA.replace("#", "01-inicio.html")}'
            f'<nav class="nav"><span class="nav-luz" aria-hidden="true"></span>{links}</nav>'
            f'<div class="direita"><span class="ambiente">{icone("flask")}<b>Produção restrita</b></span>'
            f'<button class="icone-btn" aria-label="Tema">{icone("moon")}</button>'
            f'<button class="icone-btn" aria-label="Mais opções">{icone("dots-vertical")}</button></div></div></header>')


def montar(nome: str) -> Path:
    frag = (AQUI / f"{nome}.html").read_text(encoding="utf-8")
    frag = re.sub(r"\{\{header:(\w+)\}\}", lambda m: cabecalho(m.group(1)), frag)
    frag = re.sub(r"\{\{icon:([\w-]+)(?::([\w -]+))?\}\}", lambda m: icone(m.group(1), m.group(2) or "ico"), frag)
    css_base, _, resto = (AQUI / "base.css").read_text(encoding="utf-8").partition(MARCA_MOVEL)
    css_movel = MARCA_MOVEL + resto if resto else ""
    estilo = ""
    m = re.search(r"<style>(.*?)</style>", frag, re.S)
    if m:
        estilo, frag = m.group(1), frag[: m.start()] + frag[m.end():]
    titulo = re.search(r"<!--\s*titulo:(.*?)-->", frag)
    html = (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{titulo.group(1).strip() if titulo else nome}</title>'
            f"<style>{css_base}{estilo}{css_movel}</style></head>"
            f'<body><div class="fibras"></div>{frag}<script>{SCRIPT}</script></body></html>')
    SAIDA.mkdir(parents=True, exist_ok=True)
    arq = SAIDA / f"{nome}.html"
    arq.write_text(html, encoding="utf-8")
    return arq


def renderizar(telas: list[tuple[str, int, int, bool]]) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for nome, largura, altura, inteira in telas:
            arq = montar(nome)
            ctx = navegador.new_context(viewport={"width": largura, "height": altura}, device_scale_factor=2)
            pagina = ctx.new_page()
            pagina.goto(arq.as_uri())
            pagina.evaluate("document.fonts.ready")
            pagina.wait_for_timeout(1800)  # deixa a animação de entrada terminar
            if inteira:  # cresce a janela até o fim: os fundos fixos (luz e grão) cobrem a página toda
                total = pagina.evaluate("document.documentElement.scrollHeight")
                pagina.set_viewport_size({"width": largura, "height": total})
                pagina.wait_for_timeout(300)
            png = SAIDA / f"{nome}-{largura}.png"
            pagina.screenshot(path=str(png))
            print(png)
            ctx.close()
        navegador.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--png" in args:
        args.remove("--png")
        renderizar([t for t in TELAS if not args or t[0] in args])
    else:
        for nome in sorted({t[0] for t in TELAS}):
            print(montar(nome))
