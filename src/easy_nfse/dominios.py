"""Tabelas de domínio: países (Anexo A), moedas e listas de comércio exterior (do XSD oficial)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from lxml import etree

from .util import norm

_BASE = Path(__file__).parent

# Código BACEN da moeda (tpMoeda) -> (ISO 4217, nome). Todas têm cotação PTAX.
MOEDAS = {
    "220": ("USD", "Dólar americano"),
    "978": ("EUR", "Euro"),
    "540": ("GBP", "Libra esterlina"),
    "165": ("CAD", "Dólar canadense"),
    "150": ("AUD", "Dólar australiano"),
    "425": ("CHF", "Franco suíço"),
    "470": ("JPY", "Iene"),
}


@lru_cache(maxsize=1)
def paises() -> dict[str, str]:
    """ISO2 -> nome, conforme a tabela oficial (ANEXO_A-...-PAISES_ISO2)."""
    return json.loads((_BASE / "paises.json").read_text())


def pais_por_nome(nome: str) -> str:
    """Nome impresso ("Estados Unidos", "ESTADOS UNIDOS - US") -> ISO2, ou ""."""
    texto = (nome or "").strip()
    m = re.search(r"\b([A-Z]{2})\b\s*$", texto)
    if m and m.group(1) in paises():
        return m.group(1)
    alvo = norm(texto)
    if not alvo:
        return ""
    for cod, n in paises().items():
        if norm(n) == alvo or norm(n.split(",")[0]) == alvo:
            return cod
    return ""


@lru_cache(maxsize=None)
def _enum_xsd(tipo: str) -> dict[str, str]:
    """Lê os valores e descrições de um tipo enumerado do XSD (tiposSimples)."""
    xs = "{http://www.w3.org/2001/XMLSchema}"
    tree = etree.parse(str(_BASE / "xsd" / "tiposSimples_v1.01.xsd"))
    st = tree.find(f".//{xs}simpleType[@name='{tipo}']")
    valores = [e.get("value") for e in st.iter(f"{xs}enumeration")]
    doc = " ".join("".join(st.find(f".//{xs}documentation").itertext()).split())
    descr = {m.group(1): m.group(2).strip(" ;") for m in re.finditer(r"\b(\d{1,2}) - ([^;]+?)(?=;|\s\d{1,2} - |$)", doc)}
    return {v: descr.get(v, v) for v in valores}


def opcoes(tipo: str, sem_desconhecido: bool = True) -> dict[str, str]:
    """Opções de um enum do XSD; remove "0/00 - Desconhecido", que a Sefin Nacional rejeita."""
    itens = _enum_xsd(tipo)
    if sem_desconhecido:
        itens = {k: v for k, v in itens.items() if "desconhecido" not in v.lower()}
    return itens
