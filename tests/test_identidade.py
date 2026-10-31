"""Identidade visual (docs/design): fontes locais e o menu do cabeçalho."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from easy_nfse import app as webapp

PACOTE = Path(webapp.__file__).parent


def test_fontes_sao_locais_e_existem():
    """O app roda sem internet: as fontes vêm de static/vendor/fonts (scripts/fontes.py), não do Google Fonts."""
    base = (PACOTE / "templates" / "base.html").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in base and "fonts.gstatic" not in base
    arquivos = set(re.findall(r"/static/vendor/fonts/([\w.-]+\.woff2)", base))
    assert {"public-sans.woff2", "bricolage-grotesque.woff2"} <= arquivos
    assert all((PACOTE / "static" / "vendor" / "fonts" / a).exists() for a in arquivos)
    assert (PACOTE / "static" / "vendor" / "fonts" / "bricolage-grotesque-OFL.txt").exists()


@pytest.mark.parametrize("caminho, item", [
    ("/", "Início"),
    ("/templates", "Templates"),
    ("/cadastros/tomadores", "Cadastros"),
    ("/historico", "Histórico"),
    ("/configuracoes", "Configurações"),
])
def test_menu_marca_so_a_pagina_atual(dados, caminho, item):
    """O realce deslizante (app.js) parte do item com aria-current="page": precisa haver exatamente um."""
    html = TestClient(webapp.app).get(caminho).text
    marcados = re.findall(r'data-nav-item="([^"]+)"\s+aria-current=page', html)
    assert marcados == [item]
    assert 'class="nav-luz"' in html
