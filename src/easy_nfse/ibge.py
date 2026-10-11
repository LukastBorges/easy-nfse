"""Resolução de códigos IBGE de municípios (API pública do IBGE, com cache local)."""

from __future__ import annotations

import json

import httpx

from . import storage
from .util import UF_POR_CODIGO, norm

API = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"


def _municipios(uf: str) -> list[dict]:
    uf = uf.upper()
    cache = storage.CACHE_DIR / f"ibge_{uf}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    resp = httpx.get(API.format(uf=uf), timeout=15)
    resp.raise_for_status()
    data = [{"id": str(m["id"]), "nome": m["nome"]} for m in resp.json()]
    storage.ensure_dirs()
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def codigo(nome: str, uf: str) -> str | None:
    """Retorna o código IBGE (7 dígitos) para nome + UF, ou None."""
    if not nome or not uf or uf.upper() not in UF_POR_CODIGO.values():
        return None
    try:
        alvo = norm(nome)
        for m in _municipios(uf):
            if norm(m["nome"]) == alvo:
                return m["id"]
    except httpx.HTTPError:
        return None
    return None


def nome(cod: str) -> str:
    """"4314902" -> "Porto Alegre/RS" (ou "" se não encontrado)."""
    uf = UF_POR_CODIGO.get((cod or "")[:2])
    if not uf:
        return ""
    try:
        for m in _municipios(uf):
            if m["id"] == cod:
                return f"{m['nome']}/{uf}"
    except httpx.HTTPError:
        pass
    return ""
