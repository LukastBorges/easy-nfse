"""Resumo das notas emitidas num período (cards do Histórico).

Os valores somam só as notas de Produção (as de Produção restrita não valem como faturamento) e
contam pela **competência**, a data que vale para o faturamento (Simples Nacional, PGDAS).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .models import Emissao

PERIODOS = {"ano": "Este ano", "mes": "Último mês", "6meses": "Últimos 6 meses", "personalizado": "Personalizado"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
MESES_CURTOS = [m[:3] for m in MESES]


@dataclass
class Barra:
    rotulo: str  # dica da barra ("out/2026", "18/10")
    nome: str  # como aparece na frase ("outubro", "18/10")
    valor: Decimal = Decimal(0)
    altura: int = 0  # % da maior barra


@dataclass
class Resumo:
    periodo: str
    inicio: date
    fim: date
    titulo: str  # "Emitido em 2026", "Emitido de 01/05 a 31/10"…
    total: Decimal = Decimal(0)
    notas: int = 0
    testes: int = 0
    moedas: dict[str, Decimal] = field(default_factory=dict)  # exportação: total na moeda estrangeira
    anterior: Decimal = Decimal(0)
    anterior_nome: str = ""  # "no mesmo período de 2025", "nos 30 dias anteriores"…
    barras: list[Barra] = field(default_factory=list)
    por_dia: bool = False

    @property
    def maior(self) -> Barra | None:
        com_valor = [b for b in reversed(self.barras) if b.valor]  # no empate, a mais recente
        return max(com_valor, key=lambda b: b.valor) if com_valor else None


def _meses_antes(d: date, n: int) -> date:
    """Primeiro dia do mês `n` meses antes do mês de `d`."""
    m = d.year * 12 + d.month - 1 - n
    return date(m // 12, m % 12 + 1, 1)


def _br(d: date, ano: bool = False) -> str:
    return d.strftime("%d/%m/%Y" if ano else "%d/%m")


def intervalo(periodo: str, hoje: date, de: date | None = None, ate: date | None = None) -> tuple[str, date, date]:
    """Período escolhido → (período válido, início, fim), datas inclusivas. Padrão: do início do ano até hoje."""
    if periodo == "mes":
        return periodo, hoje - timedelta(days=29), hoje
    if periodo == "6meses":
        return periodo, _meses_antes(hoje, 5), hoje
    if periodo == "personalizado" and (de or ate):
        inicio, fim = de or date(hoje.year, 1, 1), ate or hoje
        return periodo, min(inicio, fim), max(inicio, fim)
    return "ano", date(hoje.year, 1, 1), hoje


def _anterior(periodo: str, inicio: date, fim: date) -> tuple[date, date, str]:
    """Período de comparação: o mesmo do ano anterior (este ano) ou o de mesma duração logo antes."""
    if periodo == "ano":
        try:
            fim_ant = fim.replace(year=fim.year - 1)
        except ValueError:  # 29/02
            fim_ant = fim.replace(year=fim.year - 1, day=28)
        return inicio.replace(year=inicio.year - 1), fim_ant, f"no mesmo período de {inicio.year - 1}"
    if periodo == "6meses":
        return _meses_antes(inicio, 6), inicio - timedelta(days=1), "nos 6 meses anteriores"
    dias = (fim - inicio).days + 1
    return inicio - timedelta(days=dias), inicio - timedelta(days=1), f"nos {dias} dias anteriores"


def _titulo(periodo: str, inicio: date, fim: date, hoje: date) -> str:
    if periodo == "ano":
        return f"Emitido em {inicio.year}"
    if periodo == "mes":
        return "Emitido nos últimos 30 dias"
    if periodo == "6meses":
        return f"Emitido desde {MESES[inicio.month - 1]}"
    if inicio == fim:
        return f"Emitido em {_br(inicio, ano=inicio.year != hoje.year)}"
    ano = inicio.year != fim.year or fim.year != hoje.year
    return f"Emitido de {_br(inicio, ano)} a {_br(fim, ano)}"


def _barras(inicio: date, fim: date) -> tuple[list[tuple[date, Barra]], bool]:
    """Uma barra por dia em períodos de até 62 dias; senão, uma por mês."""
    if (fim - inicio).days < 62:
        dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
        return [(d, Barra(_br(d), _br(d))) for d in dias], True
    barras, m = [], date(inicio.year, inicio.month, 1)
    varios_anos = inicio.year != fim.year
    while m <= fim:
        nome = MESES[m.month - 1] + (f" de {m.year}" if varios_anos else "")
        barras.append((m, Barra(f"{MESES_CURTOS[m.month - 1]}/{m.year}", nome)))
        m = _meses_antes(m, -1)
    return barras, False


def resumir(emissoes: list[Emissao], periodo: str = "ano", hoje: date | None = None,
            de: date | None = None, ate: date | None = None) -> Resumo:
    hoje = hoje or date.today()
    periodo, inicio, fim = intervalo(periodo, hoje, de, ate)
    ini_ant, fim_ant, anterior_nome = _anterior(periodo, inicio, fim)
    barras, por_dia = _barras(inicio, fim)
    indice = {d: b for d, b in barras}
    r = Resumo(periodo, inicio, fim, _titulo(periodo, inicio, fim, hoje), anterior_nome=anterior_nome,
               barras=[b for _, b in barras], por_dia=por_dia)
    for e in emissoes:
        try:
            comp = date.fromisoformat(e.competencia[:10])
        except ValueError:
            continue
        if ini_ant <= comp <= fim_ant and e.ambiente == "1":
            r.anterior += Decimal(e.valor or 0)
        if not inicio <= comp <= fim:
            continue
        if e.ambiente != "1":
            r.testes += 1
            continue
        valor = Decimal(e.valor or 0)
        r.notas += 1
        r.total += valor
        if e.valor_moeda and e.moeda:
            r.moedas[e.moeda] = r.moedas.get(e.moeda, Decimal(0)) + Decimal(e.valor_moeda)
        indice[comp if por_dia else comp.replace(day=1)].valor += valor
    topo = max((b.valor for b in r.barras), default=Decimal(0))
    for b in r.barras:
        # barra vazia ainda aparece (trilho); com valor, nunca some de tão baixa
        b.altura = max(8, round(b.valor / topo * 100)) if topo and b.valor else 0
    return r
