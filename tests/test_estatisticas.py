from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from easy_nfse import estatisticas
from easy_nfse.models import Emissao

HOJE = date(2026, 10, 31)


def emissao(competencia: str, valor: str, ambiente: str = "1", **over) -> Emissao:
    return Emissao(chave_acesso=f"{competencia}{valor}{ambiente}", id_dps="x", serie="1", n_dps=1, ambiente=ambiente,
                   template_id="t", template_nome="T", valor=valor, competencia=competencia, **over)


NOTAS = [
    emissao("2026-10-18", "38420.00", valor_moeda="7000.00", moeda="USD"),
    emissao("2026-10-01", "4800.00", ambiente="2"),
    emissao("2026-09-30", "38420.00", valor_moeda="7000.00", moeda="USD"),
    emissao("2026-04-10", "1000.00"),
    emissao("2025-10-15", "500.00"),
    emissao("2025-11-15", "900.00"),
]


def test_padrao_e_o_ano_ate_hoje_e_compara_com_o_ano_anterior():
    r = estatisticas.resumir(NOTAS, "", hoje=HOJE)
    assert (r.periodo, r.inicio, r.fim) == ("ano", date(2026, 1, 1), HOJE)
    assert r.total == Decimal("77840.00") and r.notas == 3 and r.testes == 1  # teste não soma
    assert r.moedas == {"USD": Decimal("14000.00")}
    assert r.anterior == Decimal("500.00")  # só até 31/10/2025
    assert len(r.barras) == 10 and not r.por_dia
    assert r.maior.nome == "outubro" and r.maior.altura == 100
    assert r.barras[3].valor == Decimal("1000.00") and r.barras[3].altura == 8  # baixa, mas visível


def test_ultimo_mes_tem_barra_por_dia():
    r = estatisticas.resumir(NOTAS, "mes", hoje=HOJE)
    assert (r.inicio, r.fim, r.por_dia, len(r.barras)) == (date(2026, 10, 2), HOJE, True, 30)
    assert r.total == Decimal("38420.00") and r.testes == 0
    assert r.anterior == Decimal("38420.00") and r.anterior_nome == "nos 30 dias anteriores"
    assert r.maior.nome == "18/10"


def test_seis_meses_sao_meses_inteiros():
    r = estatisticas.resumir(NOTAS, "6meses", hoje=HOJE)
    assert r.inicio == date(2026, 5, 1) and len(r.barras) == 6
    assert r.total == Decimal("76840.00")
    assert r.anterior == Decimal("1900.00")  # nov/2025 a abr/2026


def test_personalizado_aceita_datas_invertidas_e_volta_ao_padrao_sem_datas():
    r = estatisticas.resumir(NOTAS, "personalizado", hoje=HOJE, de=date(2026, 12, 31), ate=date(2025, 1, 1))
    assert (r.inicio, r.fim) == (date(2025, 1, 1), date(2026, 12, 31))
    assert len(r.barras) == 24 and r.maior.nome == "outubro de 2026"
    assert r.titulo == "Emitido de 01/01/2025 a 31/12/2026"
    assert estatisticas.resumir(NOTAS, "personalizado", hoje=HOJE).periodo == "ano"


def test_pagina_do_historico_com_periodo(dados):
    from easy_nfse import app as webapp

    cli = TestClient(webapp.app)
    pagina = cli.get("/historico").text
    assert "Emitido em" in pagina and "Próximo número da DPS" in pagina
    pagina = cli.get("/historico?periodo=personalizado&de=2026-01-01&ate=lixo").text
    assert 'value="personalizado" selected' in pagina
