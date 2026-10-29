import base64
import io
import datetime as dt
import os
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from easy_nfse import dps
from easy_nfse.certificado import Certificado
from easy_nfse.importers import _endereco, nfse_xml
from easy_nfse.models import Endereco, Prestador, Servico, Template, Tomador, Tributacao
from easy_nfse.util import cnpj_valido, cpf_valido, fmt_money, parse_money

CNPJ = "51925143000145"


@pytest.fixture(scope="module")
def cert() -> Certificado:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{CNPJ}")])
    san = x509.SubjectAlternativeName(
        [x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), b"\x04\x0e" + CNPJ.encode())]
    )
    now = dt.datetime.now(dt.timezone.utc)
    c = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=30))
        .add_extension(san, False).sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(b"t", key, c, None, BestAvailableEncryption(b"senha"))
    return Certificado.load(pfx, "senha")


def template(**over) -> Template:
    base = dict(
        id="abcd1234",
        nome="teste",
        prestador=Prestador(documento=CNPJ, cod_municipio="4314902", op_simp_nac="2"),
        tomador=Tomador(
            tipo_doc="CPF", documento="37040642034", nome="JOSÉ – TESTE",
            endereco=Endereco(cep="70160900", cod_municipio="5300108", logradouro="PC DOS TRES PODERES",
                              numero="S/N", bairro="ZONA CIVICO"),
        ),
        servico=Servico(c_trib_nac="010301", cod_municipio_prestacao="4314902", descricao="x"),
        tributacao=Tributacao(),
    )
    base.update(over)
    return Template(**base)


def dados(**over) -> dps.DadosEmissao:
    # Data de Brasília, e não a do sistema: a CI roda em UTC e, perto da meia-noite, a competência
    # ficaria depois do dhEmi (que ainda desconta 1 min de margem) → E0015.
    hoje = (dt.datetime.now(dps.TZ) - dt.timedelta(minutes=5)).date()
    base = dict(competencia=hoje, valor=Decimal("1500"), descricao="Serviço\nlinha 2",
                serie="1", n_dps=7, ambiente="2")
    base.update(over)
    return dps.DadosEmissao(**base)


def test_certificado_documento(cert):
    assert cert.documento == CNPJ
    assert cert.titular == "EMPRESA TESTE LTDA"


def test_id_dps():
    assert dps.id_dps(template(), "1", 7) == "DPS" + "4314902" + "2" + CNPJ + "00001" + "7".zfill(15)
    assert len(dps.id_dps(template(), "1", 7)) == 45


def test_montar_valida_xsd_e_regras():
    root, ident = dps.montar(template(), dados())
    ns = {"n": dps.NS}
    assert root.find("n:infDPS", ns).get("Id") == ident
    assert root.findtext(".//n:vServ", namespaces=ns) == "1500.00"
    assert root.find(".//n:prest/n:xNome", ns) is None  # E0121
    assert root.findtext(".//n:toma/n:xNome", namespaces=ns) == "JOSÉ - TESTE"
    assert root.findtext(".//n:indTotTrib", namespaces=ns) == "0"


def test_me_epp_usa_ptottribsn():
    t = template(prestador=Prestador(documento=CNPJ, cod_municipio="4314902", op_simp_nac="3", reg_ap_trib_sn="1"),
                 tributacao=Tributacao(p_tot_trib_sn="6", p_aliq="2.01"))
    root, _ = dps.montar(t, dados())
    ns = {"n": dps.NS}
    assert root.findtext(".//n:pTotTribSN", namespaces=ns) == "6.00"
    assert root.findtext(".//n:pAliq", namespaces=ns) == "2.01"
    assert root.find(".//n:indTotTrib", ns) is None


def test_competencia_futura_rejeitada():
    with pytest.raises(dps.DPSError):
        dps.montar(template(), dados(competencia=dt.date.today() + dt.timedelta(days=2)))


def test_assinatura_valida_com_xmlsec(cert):
    try:  # xmlsec falha no import se o libxml2 dele diferir do lxml (comum em alguns ambientes de CI)
        import xmlsec
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"xmlsec indisponível: {exc}")
    root, ident = dps.montar(template(), dados())
    assinado = etree.fromstring(dps.serializar(cert.assinar(root, ident)))
    dps.validar_xsd(assinado)
    sig = assinado.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
    assert sig.nsmap.get(None) == "http://www.w3.org/2000/09/xmldsig#"  # sem prefixo ds:
    xmlsec.tree.add_ids(assinado, ["Id"])
    ctx = xmlsec.SignatureContext()
    pub = cert.cert.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    ctx.key = xmlsec.Key.from_memory(pub, xmlsec.constants.KeyDataFormatPem)
    ctx.verify(sig)
    assinado.find(f".//{{{dps.NS}}}vServ").text = "1.00"
    with pytest.raises(xmlsec.Error):
        ctx.verify(sig)


def test_importa_xml_nfse_roundtrip():
    root, _ = dps.montar(template(), dados())
    nfse = etree.Element(f"{{{dps.NS}}}NFSe", nsmap={None: dps.NS}, versao="1.01")
    inf = etree.SubElement(nfse, f"{{{dps.NS}}}infNFSe", Id="NFS" + "4" * 50)
    etree.SubElement(inf, f"{{{dps.NS}}}nNFSe").text = "123"
    inf.append(root)
    kw = nfse_xml.parse(etree.tostring(nfse))
    assert kw["prestador"].documento == CNPJ
    assert kw["tomador"].endereco.cod_municipio == "5300108"
    assert kw["servico"].c_trib_nac == "010301"
    assert kw["origem"].chave_acesso == "4" * 50
    assert kw["origem"].numero_nfse == "123"
    assert kw["ultimo_valor"] == "1500.00"


@pytest.mark.parametrize("texto,esperado", [
    ("GOETHE , 37 , Bairro RIO BRANCO , CEP 90430100 , Porto Alegre/RS",
     dict(logradouro="GOETHE", numero="37", bairro="RIO BRANCO", cep="90430100", municipio="Porto Alegre/RS")),
    ("RIACHUELO, 843, CENTRO HISTORICO", dict(logradouro="RIACHUELO", numero="843", bairro="CENTRO HISTORICO")),
    ("PC DOS TRES PODERES S/N , Anexo 4 , Bairro ZONA CIVICO , CEP 70160900 , Brasília/DF",
     dict(logradouro="PC DOS TRES PODERES", numero="S/N", complemento="Anexo 4", bairro="ZONA CIVICO")),
])
def test_endereco(texto, esperado):
    r = _endereco(texto)
    for k, v in esperado.items():
        assert r.get(k) == v


def test_util():
    assert parse_money("1.500,00") == Decimal("1500.00")
    assert parse_money("1500.5") == Decimal("1500.50")
    assert parse_money("R$ 6.600") == Decimal("6600.00")
    assert fmt_money(Decimal("1234567.8")) == "R$ 1.234.567,80"
    assert cnpj_valido(CNPJ) and not cnpj_valido("51925143000146")
    assert cpf_valido("37040642034") and not cpf_valido("37040642035")


SAMPLES = Path(os.environ.get("EASY_NFSE_SAMPLES", "samples"))


@pytest.mark.skipif(not list(SAMPLES.glob("*.pdf")), reason="sem PDFs em samples/")
@pytest.mark.parametrize("pdf", sorted(SAMPLES.glob("*.pdf")), ids=lambda p: p.name)
def test_pdfs_de_exemplo(pdf, monkeypatch):
    from easy_nfse import importers
    from easy_nfse.importers import danfse_pdf

    campos, texto = danfse_pdf.extrair(pdf.read_bytes())
    kw = importers._de_campos(campos, texto)
    assert len(kw["origem"].chave_acesso) == 50
    assert len(kw["servico"].c_trib_nac) == 6
    assert kw["ultimo_valor"]


def template_exportacao(**over) -> Template:
    from easy_nfse.models import ComercioExterior

    base = dict(
        tomador=Tomador(
            tipo_doc="NIF", documento="98-7654321", nome="ACME Inc.",
            endereco=Endereco(pais="US", cod_postal="94105", cidade="San Francisco", estado_prov="CA",
                              logradouro="Market St", numero="500"),
        ),
        servico=Servico(c_trib_nac="010101", c_nbs="115021000", cod_municipio_prestacao="4314902", descricao="x"),
        tributacao=Tributacao(trib_issqn="3", pais_resultado="US"),
        com_ext=ComercioExterior(tp_moeda="220"),
    )
    base.update(over)
    return template(**base)


def test_exportacao_tomador_exterior():
    t = template_exportacao()
    assert t.exige_com_ext
    root, _ = dps.montar(t, dados(valor_moeda=Decimal("1000")))  # valida XSD
    ns = {"n": dps.NS}
    assert root.findtext(".//n:toma/n:NIF", namespaces=ns) == "98-7654321"
    assert root.findtext(".//n:toma/n:end/n:endExt/n:cPais", namespaces=ns) == "US"
    assert root.findtext(".//n:toma/n:end/n:xBairro", namespaces=ns) == "-"
    assert root.findtext(".//n:serv/n:comExt/n:vServMoeda", namespaces=ns) == "1000.00"
    assert root.findtext(".//n:serv/n:comExt/n:tpMoeda", namespaces=ns) == "220"
    assert root.findtext(".//n:tribMun/n:cPaisResult", namespaces=ns) == "US"
    assert root.findtext(".//n:locPrest/n:cLocPrestacao", namespaces=ns) == "4314902"


def test_exportacao_regras():
    with pytest.raises(dps.DPSError, match="moeda estrangeira"):
        dps.montar(template_exportacao(), dados())
    with pytest.raises(dps.DPSError, match="NBS"):
        dps.montar(template_exportacao(servico=Servico(c_trib_nac="010101", cod_municipio_prestacao="4314902")),
                   dados(valor_moeda=Decimal("1")))
    with pytest.raises(dps.DPSError, match="resultado"):
        dps.montar(template_exportacao(tributacao=Tributacao(trib_issqn="3")), dados(valor_moeda=Decimal("1")))


def test_exportacao_prestada_no_exterior_sem_pais_resultado():
    s = Servico(c_trib_nac="010101", c_nbs="115021000", pais_prestacao="DE", descricao="x")
    root, _ = dps.montar(template_exportacao(servico=s), dados(valor_moeda=Decimal("10")))
    ns = {"n": dps.NS}
    assert root.findtext(".//n:locPrest/n:cPaisPrestacao", namespaces=ns) == "DE"
    assert root.find(".//n:tribMun/n:cPaisResult", ns) is None  # E0591


def test_importa_xml_exportacao():
    root, _ = dps.montar(template_exportacao(), dados(valor_moeda=Decimal("1000")))
    kw = nfse_xml.parse(etree.tostring(root))
    to = kw["tomador"]
    assert to.tipo_doc == "NIF" and to.documento == "98-7654321"
    assert to.endereco.pais == "US" and to.endereco.cidade == "San Francisco"
    assert kw["tributacao"].trib_issqn == "3" and kw["tributacao"].pais_resultado == "US"
    assert kw["com_ext"].tp_moeda == "220"
    assert kw["ultimo_valor_moeda"] == "1000.00"


def _nfse(dps_root, chave="3" * 50) -> bytes:
    nfse = etree.Element(f"{{{dps.NS}}}NFSe", nsmap={None: dps.NS}, versao="1.01")
    inf = etree.SubElement(nfse, f"{{{dps.NS}}}infNFSe", Id="NFS" + chave)
    for tag, val in [("xLocEmi", "Porto Alegre"), ("xLocPrestacao", "Porto Alegre"), ("nNFSe", "42"),
                     ("xTribNac", "Processamento de dados"), ("verAplic", "x"), ("ambGer", "2"), ("tpEmis", "1"),
                     ("cStat", "100"), ("dhProc", "2026-10-11T10:00:00-03:00"), ("nDFSe", "1")]:
        etree.SubElement(inf, f"{{{dps.NS}}}{tag}").text = val
    emit = etree.SubElement(inf, f"{{{dps.NS}}}emit")
    etree.SubElement(emit, f"{{{dps.NS}}}CNPJ").text = CNPJ
    etree.SubElement(emit, f"{{{dps.NS}}}xNome").text = "EMPRESA TESTE LTDA"
    end = etree.SubElement(emit, f"{{{dps.NS}}}enderNac")
    for tag, val in [("xLgr", "RUA A"), ("nro", "1"), ("xBairro", "CENTRO"), ("cMun", "4314902"), ("UF", "RS"), ("CEP", "90000000")]:
        etree.SubElement(end, f"{{{dps.NS}}}{tag}").text = val
    etree.SubElement(etree.SubElement(inf, f"{{{dps.NS}}}valores"), f"{{{dps.NS}}}vLiq").text = "1000.00"
    inf.append(dps_root)
    return etree.tostring(nfse)


@pytest.mark.parametrize("tpl", ["nacional", "exportacao"])
def test_danfse_pdf(tpl):
    import pdfplumber
    from easy_nfse import danfse

    t = template() if tpl == "nacional" else template_exportacao()
    root, _ = dps.montar(t, dados(valor_moeda=Decimal("200") if t.exige_com_ext else None))
    pdf = danfse.gerar(_nfse(root))
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        assert len(p.pages) == 1  # NT 008: página única
        texto = p.pages[0].extract_text()
    assert "DANFSe v2.0" in texto and "3" * 50 in texto
    assert "NFS-e SEM VALIDADE JURÍDICA" in texto  # tpAmb = 2
    assert "R$ 1.500,00" in texto
    if tpl == "exportacao":
        assert "Exportação de Serviço" in texto and "USD 200,00" in texto and "San Francisco" in texto


@pytest.mark.parametrize("grupo,calc", [("vDedRed", "vCalcDR"), ("vAjusteBC", "vCalcAjusteBCISSQN")])
def test_le_ajuste_bc_nos_dois_leiautes(grupo, calc):
    """NT 009 (2.3): vDedRed/vCalcDR viraram vAjusteBC/vCalcAjusteBCISSQN; o app só lê esses grupos."""
    import pdfplumber
    from easy_nfse import danfse

    root, _ = dps.montar(template(), dados())
    ns = {"n": dps.NS}
    root.find(".//n:valores", ns).append(etree.Element(f"{{{dps.NS}}}{grupo}"))
    nfse = etree.fromstring(_nfse(root))
    etree.SubElement(nfse.find("n:infNFSe/n:valores", ns), f"{{{dps.NS}}}{calc}").text = "123.45"

    kw = nfse_xml.parse(etree.tostring(nfse))
    assert any("deduções" in a for a in kw["avisos"])
    with pdfplumber.open(io.BytesIO(danfse.gerar(etree.tostring(nfse)))) as p:
        assert "R$ 123,45" in p.pages[0].extract_text()


def test_ibge_bloqueado_nao_quebra_o_pdf(monkeypatch):
    """O firewall do IBGE às vezes responde uma página HTML no lugar do JSON (derrubou um build)."""
    import pdfplumber
    from easy_nfse import danfse, ibge

    def bloqueado(url, *a, **k):
        return httpx.Response(200, text="<html><title>Request Rejected</title></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(ibge.httpx, "get", bloqueado)
    assert ibge.nome("5300108") == ""
    assert ibge.codigo("Brasília", "DF") is None
    assert not list(ibge.storage.CACHE_DIR.glob("ibge_*.json")) if ibge.storage.CACHE_DIR.exists() else True

    root, _ = dps.montar(template(), dados())
    with pdfplumber.open(io.BytesIO(danfse.gerar(_nfse(root)))) as p:
        assert "5300108 / DF" in p.pages[0].extract_text()  # sem o nome, mostra o código


def test_ibge_resolve_nome_e_codigo():
    from easy_nfse import ibge

    assert ibge.nome("4314902") == "Porto Alegre/RS"
    assert ibge.codigo("porto alegre", "rs") == "4314902"
