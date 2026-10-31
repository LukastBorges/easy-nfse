"""Cadastros de prestadores e tomadores: migração, importação, rotas e troca na emissão."""

import json
from urllib.parse import unquote

from fastapi.testclient import TestClient
from lxml import etree

from easy_nfse import app as webapp
from easy_nfse import dps, importers, storage
from easy_nfse.models import Endereco, Prestador, Template, Tomador

from test_core import CNPJ, dados as dados_emissao, template as template_dps

CPF = "37040642034"
CPF_2 = "52998224725"
CPF_3 = "11144477735"


def legado(ident: str, atualizado: str, prestador: dict, tomador: dict | None, **extra) -> None:
    """Template no formato até a 0.4: cópias do prestador e do tomador dentro dele."""
    storage.ensure_dirs()
    raw = {"id": ident, "nome": f"t-{ident}", "atualizado_em": atualizado, "prestador": prestador,
           "tomador": tomador, "servico": {"c_trib_nac": "010301"}, **extra}
    (storage.TEMPLATES_DIR / f"{ident}.json").write_text(json.dumps(raw), encoding="utf-8")


def gravar(t: Template) -> Template:
    storage.save_prestador(t.prestador)
    if t.tomador:
        storage.save_tomador(t.tomador)
    storage.save_template(t)
    return storage.get_template(t.id)


def template_completo(**over) -> Template:
    """O template válido de test_core, com os cadastros gravados."""
    t = template_dps(**over)
    t.prestador.id, t.prestador.nome = "aaaa0001", "EMPRESA TESTE"
    t.prestador_id = t.prestador.id
    if t.tomador:
        t.tomador.id = t.tomador_id = "bbbb0001"
    return gravar(t)


def test_migra_templates_antigos(dados):
    pr = {"documento": CNPJ, "nome": "EMPRESA", "cod_municipio": "4314902", "email": "velho@x.com"}
    tom = {"tipo_doc": "CPF", "documento": CPF, "nome": "JOSE"}
    legado("aaaa0001", "2026-01-01T00:00:00", pr, tom, certificado_id="cccc0001")
    legado("aaaa0002", "2026-05-01T00:00:00", {**pr, "email": "novo@x.com"}, tom)
    legado("aaaa0003", "2026-03-01T00:00:00", pr, None, certificado_id="cccc0002")

    ts = {t.id: t for t in storage.list_templates()}
    assert len(storage.list_prestadores()) == 1 and len(storage.list_tomadores()) == 1
    p = storage.list_prestadores()[0]
    assert p.email == "novo@x.com"  # o template mais recente define o cadastro
    assert p.certificado_id == "cccc0002"  # certificado escolhido no template mais recente que tinha um
    assert all(t.prestador_id == p.id for t in ts.values())
    assert ts["aaaa0001"].tomador.nome == "JOSE" and ts["aaaa0003"].tomador is None
    assert any("e-mail" in a for a in ts["aaaa0001"].avisos) and not ts["aaaa0002"].avisos
    assert (storage.BACKUP_DIR / "templates-0.4" / "aaaa0001.json").exists()
    raw = json.loads((storage.TEMPLATES_DIR / "aaaa0001.json").read_text(encoding="utf-8"))
    assert "prestador" not in raw and "certificado_id" not in raw

    storage.list_templates()  # já migrado: nada muda
    assert len(storage.list_prestadores()) == 1 and len(storage.list_tomadores()) == 1


def test_migracao_tambem_ao_abrir_um_template(dados):
    legado("aaaa0001", "2026-01-01T00:00:00", {"documento": CNPJ}, {"tipo_doc": "NIF", "c_nao_nif": "1", "nome": "ACME"})
    t = storage.get_template("aaaa0001")
    assert t.prestador.documento == CNPJ and t.tomador.exterior and t.tomador.nome == "ACME"


def test_chaves():
    assert storage.chave_prestador(Prestador(documento="51.925.143/0001-45")) == f"CNPJ:{CNPJ}"
    assert storage.chave_tomador(Tomador(tipo_doc="NIF", documento=" ab12 ")) == "NIF:AB12"
    sem_nif = Tomador(tipo_doc="NIF", nome="Acme  Ínc", endereco=Endereco(pais="US"))
    assert storage.chave_tomador(sem_nif) == "NIF-sem:US:acme inc"
    assert storage.chave_tomador(Tomador(tipo_doc="CPF")) == ""


def nfse_xml(t: Template) -> bytes:
    root, _ = dps.montar(t, dados_emissao())
    nfse = etree.Element(f"{{{dps.NS}}}NFSe", nsmap={None: dps.NS}, versao="1.01")
    inf = etree.SubElement(nfse, f"{{{dps.NS}}}infNFSe", Id="NFS" + "4" * 50)
    etree.SubElement(inf, f"{{{dps.NS}}}nNFSe").text = "1"
    inf.append(root)
    return etree.tostring(nfse)


def test_importar_reaproveita_cadastros(dados):
    t1 = importers.de_arquivo(nfse_xml(template_dps()), "a.xml")
    assert any("cadastrado a partir da nota" in a for a in t1.avisos)
    t2 = importers.de_arquivo(nfse_xml(template_dps()), "b.xml")
    assert t2.prestador_id == t1.prestador_id and t2.tomador_id == t1.tomador_id
    assert any("já estava cadastrado: o template usa" in a for a in t2.avisos)

    outro = template_dps()
    outro.tomador.email = "novo@x.com"
    t3 = importers.de_arquivo(nfse_xml(outro), "c.xml")
    assert t3.tomador_id == t1.tomador_id and storage.get_tomador(t1.tomador_id).email == ""
    assert any("dados diferentes (e-mail)" in a for a in t3.avisos)
    assert len(storage.list_prestadores()) == 1 and len(storage.list_tomadores()) == 1


def test_rotas_de_cadastro(dados):
    cli = TestClient(webapp.app)
    form = {"tomador.tipo_doc": "CPF", "tomador.documento": "111.444.777-35", "tomador.nome": "JOSE"}
    r = cli.post("/cadastros/tomadores", data=form, follow_redirects=False)
    assert r.status_code == 303 and "JOSE" in unquote(r.headers["location"])
    to = storage.list_tomadores()[0]
    assert to.documento == CPF_3

    assert "Já existe o cadastro" in cli.post("/cadastros/tomadores", data=form).text  # mesmo CPF
    assert "Informe o documento" in cli.post("/cadastros/tomadores", data={"tomador.tipo_doc": "CPF"}).text

    # no diálogo (template/emissão): 204 + evento para o app.js atualizar o select
    r = cli.post("/cadastros/tomadores", data={**form, "tomador.documento": CPF_2, "dialogo": "1"})
    assert r.status_code == 204
    evento = json.loads(r.headers["HX-Trigger"])["cadastro-salvo"]
    assert evento["papel"] == "tomador" and evento["tipo"] == "CPF" and CPF_2[:3] in evento["rotulo"]
    assert "Já existe" in cli.post("/cadastros/tomadores", data={**form, "dialogo": "1"}).text  # erro volta no diálogo

    t = template_completo()
    t.tomador_id = to.id
    storage.save_template(t)
    assert len(storage.list_tomadores()) == 3
    r = cli.post(f"/cadastros/tomadores/{to.id}/excluir", follow_redirects=False)
    assert "usado pelos templates" in unquote(r.headers["location"])
    assert cli.post(f"/cadastros/tomadores/{evento['id']}/excluir").status_code == 200
    assert len(storage.list_tomadores()) == 2

    # editar vale para os templates do cadastro; o que ficou inválido aparece
    r = cli.post(f"/cadastros/tomadores/{to.id}", data={**form, "tomador.nome": ""})
    assert "Estes templates ficaram com pendências" in r.text and t.nome in r.text
    assert storage.get_template(t.id).tomador.nome == ""

    for url in ("/cadastros", "/cadastros/tomadores", "/cadastros/prestadores", "/cadastros/tomadores/novo",
                f"/cadastros/tomadores/{to.id}?dialogo=1", f"/cadastros/tomadores/resumo?tomador_id={to.id}"):
        assert cli.get(url).status_code == 200, url
    assert cli.get("/cadastros/outros").status_code == 404


def test_documento_do_prestador_nao_muda(dados):
    t = template_completo()
    cli = TestClient(webapp.app)
    cli.post(f"/cadastros/prestadores/{t.prestador_id}",
             data={"prestador.tipo_doc": "CPF", "prestador.documento": CPF, "prestador.nome": "NOVO NOME"})
    p = storage.get_prestador(t.prestador_id)
    assert p.documento == CNPJ and p.tipo_doc == "CNPJ" and p.nome == "NOVO NOME"


def test_salvar_template_com_cadastros(dados):
    t = template_completo()
    cli = TestClient(webapp.app)
    r = cli.post(f"/templates/{t.id}", data={"prestador_id": t.prestador_id, "tomador_id": "",
                                             "servico.local_tipo": "brasil"}, follow_redirects=False)
    assert r.status_code == 303
    salvo = storage.get_template(t.id)
    assert salvo.tomador is None and salvo.prestador.documento == CNPJ
    r = cli.post(f"/templates/{t.id}", data={"prestador_id": "", "servico.local_tipo": "brasil"})
    assert "Escolha o prestador" in r.text
    assert 'name="prestador_id"' in cli.get(f"/templates/{t.id}/editar").text


def test_trocar_tomador_na_emissao(dados):
    t = template_completo()
    outro = Tomador(id="bbbb0002", tipo_doc="CPF", documento=CPF_2, nome="MARIA OUTRA")
    storage.save_tomador(outro)
    cli = TestClient(webapp.app)

    pagina = cli.get(f"/templates/{t.id}?tomador_id={outro.id}&valor=1.234,00").text
    assert "MARIA OUTRA" in pagina and "Só nesta nota" in pagina and 'value="1.234,00"' in pagina

    hoje = dados_emissao().competencia.isoformat()
    r = cli.post(f"/templates/{t.id}/revisar", data={"competencia": hoje, "valor": "100", "descricao": "x",
                                                     "tomador_id": outro.id})
    assert "MARIA OUTRA" in r.text and CPF_2 in r.text and f'name="tomador_id" value="{outro.id}"' in r.text
    assert storage.get_template(t.id).tomador_id == "bbbb0001"  # o template não muda

    r = cli.post(f"/templates/{t.id}/revisar", data={"competencia": hoje, "valor": "100", "descricao": "x",
                                                     "tomador_id": "sem"})
    assert "<toma>" not in r.text and "&lt;toma&gt;" not in r.text  # sem tomador nesta nota
    assert cli.get(f"/templates/{t.id}?tomador_id=ffffffff").status_code == 404


def test_home_filtra_e_emite_por_cadastro(dados):
    t = template_completo()
    outro = Tomador(id="bbbb0002", tipo_doc="CPF", documento=CPF_2, nome="MARIA OUTRA")
    storage.save_tomador(outro)
    gravar(t.model_copy(update={"id": "abcd0002", "nome": "segundo", "tomador_id": outro.id, "tomador": outro}))
    cli = TestClient(webapp.app)

    home = cli.get("/").text
    assert 'data-filtro-por="tomador"' in home and f'data-tomador="{outro.id}"' in home
    assert 'data-filtro-por="prestador"' not in home  # um prestador só: sem filtro
    home = cli.get(f"/?tomador_id={outro.id}").text
    assert "Emitindo para" in home and f'href="/templates/{t.id}?tomador_id={outro.id}"' in home
    assert f'<option value="{outro.id}" selected>' in home
    lista = cli.get("/templates").text
    assert 'data-filtro-por="tomador"' in lista and f'data-prestador="{t.prestador_id}"' in lista
