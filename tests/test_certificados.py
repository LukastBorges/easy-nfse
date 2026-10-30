"""Vários certificados A1: biblioteca em Configurações e escolha por prestador."""

import datetime as dt

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from easy_nfse import app as webapp
from easy_nfse import storage
from easy_nfse.models import CertificadoSalvo, Config, Prestador, Template

CNPJ_A = "51925143000145"
CNPJ_B = "11222333000181"


def gerar_pfx(cnpj: str, dias: int = 30, nome: str = "EMPRESA TESTE LTDA", senha: str = "senha") -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{cnpj}")])
    san = x509.SubjectAlternativeName(
        [x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), b"\x04\x0e" + cnpj.encode())]
    )
    now = dt.datetime.now(dt.timezone.utc)
    c = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=400))
        .not_valid_after(now + dt.timedelta(days=dias)).add_extension(san, False).sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"t", key, c, None, BestAvailableEncryption(senha.encode()))


def adicionar(pfx: bytes, senha: str = "senha") -> str:
    cfg = storage.load_config()
    s = CertificadoSalvo(id=storage.new_id(), arquivo="x.pfx", senha=senha)
    storage.save_certificate(s.id, pfx)
    cfg.certificados.append(s)
    storage.save_config(cfg)
    return s.id


def prestador(cnpj: str, certificado_id: str = "") -> Prestador:
    return Prestador(id=cnpj[:8], documento=cnpj, certificado_id=certificado_id)


def template(cnpj: str, certificado_id: str = "", **over) -> Template:
    """Template gravado (com o cadastro do prestador) para as páginas."""
    p = prestador(cnpj, certificado_id)
    storage.save_prestador(p)
    t = Template(id=over.pop("id", "abcd1234"), nome="t", prestador_id=p.id, prestador=p, **over)
    storage.save_template(t)
    return t


def test_migra_certificado_unico(dados):
    storage.ensure_dirs()
    storage.CERT_FILE.write_bytes(gerar_pfx(CNPJ_A))
    storage.save_config(Config(certificado_senha="senha"))

    cfg = storage.load_config()
    assert len(cfg.certificados) == 1 and cfg.certificados[0].senha == "senha"
    assert cfg.certificado_senha == ""
    assert not storage.CERT_FILE.exists()
    assert storage.load_certificate(cfg.certificados[0].id)
    assert len(storage.load_config().certificados) == 1  # não migra de novo
    info = webapp.info_certificados(cfg)
    assert info[0]["ok"] and info[0]["documento"] == CNPJ_A


def test_senha_da_variavel_de_ambiente(dados, monkeypatch):
    adicionar(gerar_pfx(CNPJ_A), senha="")
    assert not webapp.info_certificados(storage.load_config())[0]["ok"]
    monkeypatch.setenv("EASY_NFSE_CERT_SENHA", "senha")
    assert webapp.info_certificados(storage.load_config())[0]["ok"]


def test_escolha_automatica_pelo_prestador(dados):
    vencido = adicionar(gerar_pfx(CNPJ_A, dias=-1))
    renovado = adicionar(gerar_pfx(CNPJ_A, dias=365))
    outro = adicionar(gerar_pfx(CNPJ_B, nome="OUTRA LTDA"))
    certs = webapp.info_certificados(storage.load_config())

    assert webapp.certificado_do_prestador(certs, prestador(CNPJ_A))["id"] == renovado
    assert webapp.certificado_do_prestador(certs, prestador(CNPJ_B))["id"] == outro
    assert webapp.certificado_do_prestador(certs, prestador("37040642034")) is None
    # escolha explícita vence o automático; id que sumiu volta ao automático
    assert webapp.certificado_do_prestador(certs, prestador(CNPJ_A, certificado_id=vencido))["id"] == vencido
    assert webapp.certificado_do_prestador(certs, prestador(CNPJ_A, certificado_id="ffffffff"))["id"] == renovado


def test_problema_certificado(dados):
    p = prestador(CNPJ_A)
    assert "Nenhum certificado digital" in webapp.problema_certificado([], p, None)

    adicionar(gerar_pfx(CNPJ_A, dias=-1))
    certs = webapp.info_certificados(storage.load_config())
    assert "vencido" in webapp.problema_certificado(certs, p, webapp.certificado_do_prestador(certs, p))
    assert "Nenhum certificado de 11.222.333/0001-81" in webapp.problema_certificado(certs, prestador(CNPJ_B), None)

    outro = adicionar(gerar_pfx(CNPJ_B))
    certs = webapp.info_certificados(storage.load_config())
    p = prestador(CNPJ_A, certificado_id=outro)
    assert "E0718" in webapp.problema_certificado(certs, p, webapp.certificado_do_prestador(certs, p))


def test_rotas_de_certificados(dados):
    cli = TestClient(webapp.app)
    pfx_a = gerar_pfx(CNPJ_A)

    def enviar(pfx, senha="senha"):
        return cli.post("/configuracoes/certificados", files={"arquivo": ("a.pfx", pfx)}, data={"senha": senha})

    assert "Confira a senha" in enviar(pfx_a, "errada").text
    assert enviar(pfx_a).status_code == 200
    assert enviar(pfx_a).status_code == 200  # o mesmo de novo não duplica
    assert enviar(gerar_pfx(CNPJ_B, nome="OUTRA LTDA")).status_code == 200
    cfg = storage.load_config()
    assert len(cfg.certificados) == 2
    id_b = next(i["id"] for i in webapp.info_certificados(cfg) if i["documento"] == CNPJ_B)

    t = template(CNPJ_A, certificado_id=id_b)
    pagina = cli.get("/configuracoes").text
    linha_b = pagina[pagina.index(f'id="ultimo-{id_b}"') - 3000:pagina.index(f'id="ultimo-{id_b}"')]
    assert "OUTRA LTDA" in linha_b and '<span class="truncate">51.925.143/0001-45</span>' in linha_b  # usado pelo prestador
    assert pagina.count('name="ultimo"') == 2  # numeração da DPS em cada certificado
    home = cli.get("/").text
    assert "Certificado de outro CNPJ (11.222.333/0001-81)" in home
    assert 'data-estado="problema"' in home and "data-max-linhas" in home  # filtro e grade limitada da home
    assert "E0718" in cli.get(f"/templates/{t.id}").text
    form = cli.get(f"/cadastros/prestadores/{t.prestador_id}").text
    assert f'value="{id_b}" selected' in form and "Automático" in form

    assert cli.post(f"/configuracoes/certificados/{id_b}/excluir").status_code == 200
    assert len(storage.load_config().certificados) == 1
    assert storage.get_prestador(t.prestador_id).certificado_id == ""
    home = cli.get("/").text
    assert "outro CNPJ" not in home and "Certificado vence em" in home  # o de teste vale 30 dias
    assert cli.post("/configuracoes/certificados/../excluir").status_code == 404


def test_icones_dos_templates_existem():
    """Todo icone('nome') literal precisa do SVG em static/vendor/tabler-icons (scripts/icones_tabler.py)."""
    import re
    from pathlib import Path

    pasta = Path(webapp.__file__).parent
    nomes = {n for f in (pasta / "templates").rglob("*.html")
             for n in re.findall(r"icone\('([a-z0-9-]+)'", f.read_text(encoding="utf-8"))}
    assert nomes and all((pasta / "static" / "vendor" / "tabler-icons" / f"{n}.svg").exists() for n in nomes)
    assert 'aria-hidden="true"' in webapp.icone("check")


def test_paginas_nao_abrem_os_pfx(dados, monkeypatch):
    """Titular, documento e validade ficam no config.json: listar não decifra os .pfx (lento com muitos)."""
    adicionar(gerar_pfx(CNPJ_A))
    webapp.info_certificados(storage.load_config())  # certificado antigo, sem os dados: abre uma vez e guarda
    salvo = storage.load_config().certificados[0]
    assert salvo.documento == CNPJ_A and salvo.validade and len(salvo.impressao) == 64

    def proibido(*a, **k):
        raise AssertionError("abriu o .pfx")

    monkeypatch.setattr(webapp.Certificado, "load", proibido)
    template(CNPJ_A)
    cli = TestClient(webapp.app)
    for url in ("/", "/templates", "/configuracoes", "/templates/abcd1234", "/templates/abcd1234/editar",
                "/cadastros/prestadores", f"/cadastros/prestadores/{CNPJ_A[:8]}"):
        assert cli.get(url).status_code == 200, url
    storage.delete_certificate(salvo.id)
    assert "não está mais na pasta" in webapp.info_certificados(storage.load_config())[0]["erro"]
