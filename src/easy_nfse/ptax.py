"""Cotação PTAX (Banco Central) para converter valores em moeda estrangeira."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)


class PTAXError(Exception):
    pass


@dataclass
class Cotacao:
    data: date
    compra: Decimal
    venda: Decimal


def cotacao(moeda_iso: str, ate: date) -> Cotacao:
    """Boletim de fechamento mais recente com data <= `ate` (busca até 10 dias antes)."""
    params = {
        "@moeda": f"'{moeda_iso}'",
        "@dataInicial": f"'{(ate - timedelta(days=10)):%m-%d-%Y}'",
        "@dataFinalCotacao": f"'{ate:%m-%d-%Y}'",
        "$format": "json",
        "$select": "cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim",
    }
    resp = httpx.get(URL, params=params, timeout=15)
    resp.raise_for_status()
    fechamentos = [v for v in resp.json().get("value", []) if v.get("tipoBoletim") == "Fechamento"]
    if not fechamentos:
        raise PTAXError(f"sem cotação de fechamento para {moeda_iso} até {ate:%d/%m/%Y}")
    ultimo = max(fechamentos, key=lambda v: v["dataHoraCotacao"])
    return Cotacao(
        data=datetime.fromisoformat(ultimo["dataHoraCotacao"][:19]).date(),
        compra=Decimal(str(ultimo["cotacaoCompra"])),
        venda=Decimal(str(ultimo["cotacaoVenda"])),
    )
