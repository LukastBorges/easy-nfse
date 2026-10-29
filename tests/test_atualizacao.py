"""Atualização automática: checagem das releases, download verificado, troca de pastas e interface."""

import hashlib
import io
import subprocess
import sys
import threading
import zipfile
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from easy_nfse import app as webapp
from easy_nfse import atualizacao, storage

PACOTE = b"conteudo do pacote da versao nova"


def release(tag="easy-nfse-v0.4.0", digest=hashlib.sha256(PACOTE).hexdigest(), **over):
    base = {
        "tag_name": tag, "html_url": f"https://github.com/LukastBorges/easy-nfse/releases/tag/{tag}",
        "draft": False, "prerelease": False,
        "assets": [
            {"name": f"{tag}-macos-arm64.dmg", "digest": f"sha256:{digest}", "browser_download_url": "https://x/mac.dmg"},
            {"name": f"{tag}-windows-x64.zip", "digest": f"sha256:{digest}", "browser_download_url": "https://x/win.zip"},
        ],
    }
    return {**base, **over}


@pytest.fixture
def amb(tmp_path, monkeypatch):
    """Dados isolados, app "empacotado" em tmp_path/app (gravável), versão atual 0.3.0 e GitHub falso."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "dados")
    monkeypatch.setattr(storage, "CONFIG_FILE", tmp_path / "dados" / "config.json")
    monkeypatch.setattr(atualizacao, "__version__", "0.3.0")
    monkeypatch.setattr(atualizacao, "plataforma", lambda: "macos-arm64")
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(atualizacao, "pasta_do_app", lambda: tmp_path / "app")
    monkeypatch.delenv("EASY_NFSE_SEM_ATUALIZACAO", raising=False)
    chamadas = {"get": 0}
    estado = {"release": release(), "pacote": PACOTE}

    def get(url, **kw):
        chamadas["get"] += 1
        return httpx.Response(200, json=estado["release"], request=httpx.Request("GET", url))

    @contextmanager
    def stream(metodo, url, **kw):
        r = httpx.Response(200, stream=httpx.ByteStream(estado["pacote"]), request=httpx.Request(metodo, url))
        yield r

    monkeypatch.setattr(atualizacao.httpx, "get", get)
    monkeypatch.setattr(atualizacao.httpx, "stream", stream)
    return {"chamadas": chamadas, "estado": estado, "tmp": tmp_path}


def test_versao():
    assert atualizacao.versao("easy-nfse-v0.10.2") == (0, 10, 2) > atualizacao.versao("0.9.9")
    assert atualizacao.versao("lixo") == (0,)


def test_verifica_baixa_e_confere_sha256(amb):
    atualizacao.verificar()
    assert atualizacao.status()["nova"] == "0.4.0" and not atualizacao.status()["pronta"]
    atualizacao.verificar()  # dentro do intervalo: não consulta de novo
    assert amb["chamadas"]["get"] == 1

    arquivo = atualizacao.baixar()
    assert arquivo.read_bytes() == PACOTE and arquivo.name.endswith("-macos-arm64.dmg")
    assert atualizacao.status()["pronta"]


def test_download_adulterado_e_descartado(amb):
    amb["estado"]["pacote"] = b"outro conteudo"
    atualizacao.verificar()
    with pytest.raises(atualizacao.AtualizacaoError, match="SHA-256"):
        atualizacao.baixar()
    assert not list((amb["tmp"] / "dados" / "atualizacao").glob("easy-nfse-*"))
    assert not atualizacao.status()["pronta"]


def test_sem_versao_nova_ou_sem_digest(amb):
    amb["estado"]["release"] = release(tag="easy-nfse-v0.3.0")
    atualizacao.verificar()
    assert atualizacao.status()["nova"] is None
    amb["estado"]["release"] = release(digest="")
    atualizacao.verificar(forcar=True)
    with pytest.raises(atualizacao.AtualizacaoError, match="verificável"):
        atualizacao.baixar()


def test_rotina_de_fundo_nao_levanta_e_respeita_desligado(amb, monkeypatch):
    amb["estado"]["release"] = {"draft": True}
    atualizacao.verificar_e_baixar()
    assert "não foi publicada" in atualizacao._ler()["erro"]

    cfg = storage.load_config()
    cfg.verificar_atualizacoes = False
    storage.save_config(cfg)
    amb["chamadas"]["get"] = 0
    atualizacao.verificar_e_baixar()
    assert amb["chamadas"]["get"] == 0


def test_codigo_fonte_so_avisa(amb, monkeypatch):
    monkeypatch.setattr(atualizacao, "pasta_do_app", lambda: None)
    atualizacao.verificar_e_baixar()
    st = atualizacao.status()
    assert st["nova"] and not st["instalavel"] and not st["pronta"] and "git pull" in st["motivo"]


def test_extrair_zip_recusa_caminho_fora_da_pasta(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../fora.txt", "x")
    (tmp_path / "p.zip").write_bytes(buf.getvalue())
    with pytest.raises(atualizacao.AtualizacaoError, match="inválido"):
        atualizacao._extrair(tmp_path / "p.zip", tmp_path / "novo")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("easy-nfse/easy-nfse.exe", "exe")
        z.writestr("easy-nfse/_internal/lib.dll", "dll")
    (tmp_path / "ok.zip").write_bytes(buf.getvalue())
    atualizacao._extrair(tmp_path / "ok.zip", tmp_path / "novo")
    assert (tmp_path / "novo" / "easy-nfse.exe").exists() and (tmp_path / "novo" / "_internal" / "lib.dll").exists()


def _rodar_troca(amb, criar_novo: bool) -> None:
    atual, novo = amb["tmp"] / "app", amb["tmp"] / "app.novo"
    (atual / "versao.txt").write_text("velha", encoding="utf-8")
    if criar_novo:
        novo.mkdir()
        (novo / "versao.txt").write_text("nova", encoding="utf-8")
    processo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])  # o "app" que vai fechar
    # recolhe o processo ao terminar: senão ele vira zumbi (o pai é o pytest) e o script esperaria pelo limite
    threading.Thread(target=processo.wait, daemon=True).start()
    _, comando = atualizacao.script_troca(processo.pid, atual, novo, reabrir=False)
    subprocess.run(comando, timeout=60, capture_output=True)


def test_script_troca_substitui_a_pasta(amb):
    _rodar_troca(amb, criar_novo=True)
    assert (amb["tmp"] / "app" / "versao.txt").read_text(encoding="utf-8") == "nova"
    assert not (amb["tmp"] / "app.novo").exists() and not (amb["tmp"] / "app.antigo").exists()


def test_script_troca_desfaz_se_falhar(amb):
    _rodar_troca(amb, criar_novo=False)  # sem a pasta nova: a troca falha e a versão atual volta
    assert (amb["tmp"] / "app" / "versao.txt").read_text(encoding="utf-8") == "velha"
    assert not (amb["tmp"] / "app.antigo").exists()


def test_ao_abrir_instala_uma_vez_e_depois_avisa(amb, monkeypatch):
    atualizacao.verificar_e_baixar()
    instalou = []

    def instalar():
        instalou.append(1)
        e = atualizacao._ler()
        e["tentou_instalar"] = e["versao"]
        atualizacao._gravar(e)

    monkeypatch.setattr(atualizacao, "instalar", instalar)
    assert atualizacao.ao_abrir() is True and instalou == [1]
    assert atualizacao.ao_abrir() is False and instalou == [1]  # falhou e reabriu na versão velha: não entra em laço

    monkeypatch.setattr(atualizacao, "__version__", "0.4.0")  # reabriu na versão nova
    assert atualizacao.ao_abrir() is False
    assert atualizacao.status()["atualizado_para"] == "0.4.0"
    atualizacao.dispensar_aviso()
    assert not atualizacao.status()["atualizado_para"]


def test_interface(amb, monkeypatch):
    monkeypatch.setattr(webapp.atualizacao, "status", atualizacao.status)
    cli = TestClient(webapp.app)
    assert "Verificar e baixar atualizações automaticamente" in cli.get("/configuracoes").text
    assert "Reiniciar e atualizar" not in cli.get("/").text

    atualizacao.verificar_e_baixar()
    pagina = cli.get("/historico").text  # a faixa aparece em qualquer página
    assert "Versão <b>0.4.0</b>" in pagina and "Reiniciar e atualizar" in pagina

    monkeypatch.setattr(webapp, "_emitindo", 1)
    assert "emissão em andamento" in cli.post("/atualizacao/instalar").text
    monkeypatch.setattr(webapp, "_emitindo", 0)
    monkeypatch.setattr(atualizacao, "pasta_do_app", lambda: None)
    assert "git pull" in cli.post("/atualizacao/instalar").text

