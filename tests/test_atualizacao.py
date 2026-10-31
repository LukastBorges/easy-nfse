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
    assert 'name="verificar_atualizacoes"' not in cli.get("/configuracoes").text  # saiu do formulário de Configurações
    assert 'hx-post="/atualizacao/instalar"' not in cli.get("/").text

    atualizacao.verificar_e_baixar()
    pagina = cli.get("/historico").text  # a faixa aparece em qualquer página
    assert "Versão <b>0.4.0</b>" in pagina and 'hx-post="/atualizacao/instalar"' in pagina

    monkeypatch.setattr(webapp, "_emitindo", 1)
    assert "emissão em andamento" in cli.post("/atualizacao/instalar").text
    monkeypatch.setattr(webapp, "_emitindo", 0)
    monkeypatch.setattr(atualizacao, "pasta_do_app", lambda: None)
    assert "git pull" in cli.post("/atualizacao/instalar").text



def test_aviso_acompanha_o_download(amb, monkeypatch):
    """Enquanto baixa, o aviso consulta /atualizacao/estado; ao terminar, mostra o botão de instalar."""
    monkeypatch.setattr(webapp.atualizacao, "status", atualizacao.status)
    cli = TestClient(webapp.app)
    atualizacao.verificar()
    with atualizacao._trava:  # download em andamento (thread de segundo plano)
        pagina = cli.get("/historico").text
        assert "Baixando em segundo plano" in pagina and 'hx-get="/atualizacao/estado"' in pagina
    estado = cli.get("/atualizacao/estado").text  # parou sem baixar: oferece baixar, sem consultar de novo
    assert 'hx-get="/atualizacao/estado"' not in estado and "Baixar" in estado

    amb["estado"]["pacote"] = b"adulterado"
    atualizacao.verificar_e_baixar()
    estado = cli.get("/atualizacao/estado").text
    assert "download falhou" in estado and "SHA-256" in estado and "Tentar de novo" in estado

    amb["estado"]["pacote"] = PACOTE
    atualizacao.verificar_e_baixar()
    estado = cli.get("/atualizacao/estado").text
    assert "baixada e verificada" in estado and 'hx-post="/atualizacao/instalar"' in estado
    assert 'hx-get="/atualizacao/estado"' not in estado

def test_opcao_de_checagem_automatica_no_sobre(amb, monkeypatch):
    chamadas = []
    monkeypatch.setattr(atualizacao, "verificar_e_baixar", lambda **kw: chamadas.append(kw))
    cli = TestClient(webapp.app)
    assert "Verificar e baixar atualizações automaticamente" in cli.get("/historico").text  # no Sobre, em toda página
    assert "Desligada" in cli.post("/atualizacao/automatica").text  # caixa desmarcada não envia o campo
    assert not storage.load_config().verificar_atualizacoes
    cli.post("/configuracoes", data={"ambiente": "2", "serie": "1"})  # salvar Configurações não mexe nela
    assert not storage.load_config().verificar_atualizacoes
    assert "Ligada" in cli.post("/atualizacao/automatica", data={"ativa": "1"}).text
    assert storage.load_config().verificar_atualizacoes
    assert len(chamadas) == 1  # ao ligar, já verifica (em segundo plano)


CHANGELOG = """# Changelog

## [0.4.0](https://github.com/x/compare/a...b) (2026-11-05)


### Funcionalidades

* **desktop:** atualizar o app automaticamente ([abc1234](https://github.com/x/commit/abc1234))
* **desktop:** atualizar o app automaticamente ([def5678](https://github.com/x/commit/def5678))
* menu com ajuda e sobre ([1111111](https://github.com/x/commit/1111111)), closes [#7](https://github.com/x/issues/7)


### Documentação

* **agents:** anotar algo interno ([2222222](https://github.com/x/commit/2222222))

## [0.3.0](https://github.com/x/compare/c...d) (2026-10-29)


### Build e dependências

* **deps:** atualizar algo ([3333333](https://github.com/x/commit/3333333))
"""


def test_notas_do_changelog():
    v4, v3 = atualizacao.notas(CHANGELOG)
    assert (v4["versao"], v4["data"]) == ("0.4.0", "2026-11-05")
    assert [s["titulo"] for s in v4["secoes"]] == ["Funcionalidades"]  # documentação fica de fora
    assert v4["secoes"][0]["itens"] == [  # sem hashes, sem "closes" e sem o item repetido
        {"escopo": "desktop", "texto": "atualizar o app automaticamente"},
        {"escopo": "", "texto": "menu com ajuda e sobre"},
    ]
    assert v3["secoes"] == []
    assert atualizacao.changelog()  # o CHANGELOG.md do repositório é encontrado


def test_rota_de_notas_mostra_a_versao_nova_e_a_instalada(amb, monkeypatch):
    amb["estado"]["release"] = release(body=CHANGELOG.split("## [0.3.0]")[0])
    atualizacao.verificar()
    monkeypatch.setattr(atualizacao, "changelog", lambda: atualizacao.notas(CHANGELOG)[1:])
    monkeypatch.setattr(webapp.atualizacao, "status", atualizacao.status)
    html = TestClient(webapp.app).get("/notas").text
    assert "Versão 0.4.0" in html and "disponível" in html and "Atualizar o app automaticamente" in html
    assert "Versão 0.3.0" in html and "instalada" in html and "Só ajustes internos" in html
    assert "abc1234" not in html


def _fingir_popen(monkeypatch):
    class Popen:
        def __init__(self, *a, **k):
            pass
    monkeypatch.setattr(atualizacao.subprocess, "Popen", Popen)


def test_instalar_uma_de_cada_vez(amb, monkeypatch):
    """Duas instalações juntas: a segunda apagaria o .novo da primeira e seria morta no meio da cópia (bug da 0.4.2)."""
    atualizacao.verificar_e_baixar()
    _fingir_popen(monkeypatch)
    copiando, liberar = threading.Event(), threading.Event()

    def extrair(pacote, novo):
        copiando.set()
        liberar.wait(5)
        novo.mkdir()

    monkeypatch.setattr(atualizacao, "_extrair", extrair)
    primeira = threading.Thread(target=atualizacao.instalar)
    primeira.start()
    assert copiando.wait(5)
    with pytest.raises(atualizacao.AtualizacaoError, match="já está sendo instalada"):
        atualizacao.instalar()
    liberar.set()
    primeira.join(5)
    assert atualizacao._ler()["tentou_instalar"] == "easy-nfse-v0.4.0"
    atualizacao._instalando.release()  # no app, a trava fica presa até o processo sair


def test_instalar_que_falha_solta_a_trava(amb, monkeypatch):
    atualizacao.verificar_e_baixar()
    _fingir_popen(monkeypatch)

    def extrair(pacote, novo):
        raise atualizacao.AtualizacaoError("pacote quebrado")

    monkeypatch.setattr(atualizacao, "_extrair", extrair)
    for _ in range(2):  # a segunda tentativa não pode dar "já está sendo instalada"
        with pytest.raises(atualizacao.AtualizacaoError, match="pacote quebrado"):
            atualizacao.instalar()
    assert not atualizacao._instalando.locked()


def test_extrair_dmg_desmonta_o_que_sobrou(tmp_path, monkeypatch):
    """Uma instalação interrompida deixa o .dmg montado; montar de novo dava "Resource busy"."""
    import plistlib

    pacote = tmp_path / "easy-nfse-v0.4.2-macos-arm64.dmg"
    pacote.write_bytes(b"dmg")
    chamadas = []

    def run(cmd, **kw):
        chamadas.append(cmd[:2])
        if cmd[:2] == ["hdiutil", "info"]:
            info = {"images": [{"image-path": str(pacote), "system-entities": [{"mount-point": "/ponto/velho"}]},
                               {"image-path": "/outro.dmg", "system-entities": [{"mount-point": "/ponto/outro"}]}]}
            return subprocess.CompletedProcess(cmd, 0, plistlib.dumps(info), b"")
        if cmd[0] == "ditto":
            (tmp_path / "novo").mkdir()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(atualizacao.subprocess, "run", run)
    atualizacao._extrair(pacote, tmp_path / "novo")
    desmontados = [c for c in chamadas if c == ["hdiutil", "detach"]]
    assert chamadas.index(["hdiutil", "detach"]) < chamadas.index(["hdiutil", "attach"])  # o que sobrou sai antes
    assert len(desmontados) == 2  # o que sobrou (só deste pacote) e o desta instalação


def test_extrair_dmg_explica_quando_nao_monta(tmp_path, monkeypatch):
    pacote = tmp_path / "x.dmg"
    pacote.write_bytes(b"dmg")

    def run(cmd, **kw):
        if cmd[:2] == ["hdiutil", "attach"]:
            return subprocess.CompletedProcess(cmd, 1, "", "hdiutil: attach failed - Resource busy\n")
        return subprocess.CompletedProcess(cmd, 0, b"<plist><dict/></plist>" if "-plist" in cmd else "", "")

    monkeypatch.setattr(atualizacao.subprocess, "run", run)
    with pytest.raises(atualizacao.AtualizacaoError, match="Resource busy"):
        atualizacao._extrair(pacote, tmp_path / "novo")


def test_ao_abrir_avisa_quando_a_troca_falhou(amb, monkeypatch):
    """O script de troca desfez a instalação: em vez de só mostrar "versão nova", explica e oferece tentar de novo."""
    monkeypatch.setattr(webapp.atualizacao, "status", atualizacao.status)
    atualizacao.verificar_e_baixar()
    e = atualizacao._ler()
    e["tentou_instalar"] = e["versao"]
    atualizacao._gravar(e)
    (atualizacao._pasta() / "trocar.log").write_text(
        "mv: rename /x/easy-nfse.app.novo to /x/easy-nfse.app: No such file or directory\n", encoding="utf-8")

    assert atualizacao.ao_abrir() is False  # não tenta sozinho de novo (sem laço)
    st = atualizacao.status()
    assert "A instalação da versão 0.4.0 não terminou" in st["erro"] and "No such file" in st["erro"]
    assert st["pronta"]
    pagina = TestClient(webapp.app).get("/historico").text
    assert "não terminou" in pagina and "Tente de novo" in pagina and 'hx-post="/atualizacao/instalar"' in pagina
