"""Configuração dos testes: sem rede e sem tocar na pasta de dados real."""

import os
import tempfile

# Precisa vir antes de importar easy_nfse: storage.DATA_DIR é calculado no import.
os.environ.setdefault("EASY_NFSE_DATA", tempfile.mkdtemp(prefix="easy-nfse-testes-"))
os.environ["EASY_NFSE_SEM_ATUALIZACAO"] = "1"  # nada de consultar o GitHub nos testes

import httpx  # noqa: E402
import pytest  # noqa: E402

MUNICIPIOS_FALSOS = {
    "RS": [{"id": 4314902, "nome": "Porto Alegre"}],
    "DF": [{"id": 5300108, "nome": "Brasília"}],
    "MG": [{"id": 3106200, "nome": "Belo Horizonte"}],
    "SP": [{"id": 3550308, "nome": "São Paulo"}],
}


def resposta_ibge(url: str, *args, **kwargs) -> httpx.Response:
    """Simula a API de municípios do IBGE para as UFs acima."""
    uf = url.rstrip("/").split("/")[-2].upper()
    req = httpx.Request("GET", url)
    if uf in MUNICIPIOS_FALSOS:
        return httpx.Response(200, json=MUNICIPIOS_FALSOS[uf], request=req)
    return httpx.Response(404, request=req)


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch, tmp_path):
    from easy_nfse import ibge, storage

    monkeypatch.setattr(storage, "CACHE_DIR", tmp_path / "cache")  # cache do IBGE isolado por teste
    monkeypatch.setattr(ibge.httpx, "get", resposta_ibge)


@pytest.fixture
def dados(tmp_path, monkeypatch):
    """Pasta de dados vazia e isolada por teste."""
    from easy_nfse import storage

    for nome, rel in [("DATA_DIR", "."), ("TEMPLATES_DIR", "templates"), ("EMISSOES_DIR", "emissoes"),
                      ("PRESTADORES_DIR", "prestadores"), ("TOMADORES_DIR", "tomadores"), ("BACKUP_DIR", "backup"),
                      ("CERTS_DIR", "certificados"), ("CONFIG_FILE", "config.json"),
                      ("CERT_FILE", "certificado.pfx"), ("EMISSOES_LOG", "emissoes.jsonl")]:
        monkeypatch.setattr(storage, nome, (tmp_path / rel).resolve())
    monkeypatch.delenv("EASY_NFSE_CERT_SENHA", raising=False)
    return tmp_path
