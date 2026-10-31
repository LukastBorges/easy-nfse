"""Cria uma pasta de dados fictícia para conferir as telas e tirar capturas (README, docs/design).

Prestadores, tomadores, templates, certificados autoassinados (com o CNPJ na extensão ICP-Brasil) e algumas
emissões de teste. Nada aqui é real e nada é enviado à Sefin.

    EASY_NFSE_DATA=/tmp/easy-nfse-demo uv run python scripts/dados_demo.py
    EASY_NFSE_NO_BROWSER=1 EASY_NFSE_PORT=8765 EASY_NFSE_DATA=/tmp/easy-nfse-demo uv run easy-nfse

Recusa rodar sem EASY_NFSE_DATA ou numa pasta que já tenha dados, para nunca tocar na pasta de dados real.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path


def cnpj_com_digitos(base12: str) -> str:
    def digito(nums: str, pesos: list[int]) -> str:
        r = sum(int(n) * p for n, p in zip(nums, pesos)) % 11
        return "0" if r < 2 else str(11 - r)

    d1 = digito(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return base12 + d1 + digito(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])


def cpf_com_digitos(base9: str) -> str:
    def digito(nums: str) -> str:
        r = sum(int(n) * p for n, p in zip(nums, range(len(nums) + 1, 1, -1))) * 10 % 11
        return "0" if r == 10 else str(r)

    d1 = digito(base9)
    return base9 + d1 + digito(base9 + d1)


def gerar_pfx(documento: str, nome: str, dias: int, senha: str = "demo") -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    titular = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{documento}")])
    san = x509.SubjectAlternativeName(
        [x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), b"\x04\x0e" + documento.encode())])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(titular).issuer_name(titular).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora + dt.timedelta(days=dias - 365))
            .not_valid_after(agora + dt.timedelta(days=dias)).add_extension(san, False).sign(chave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"demo", chave, cert, None, BestAvailableEncryption(senha.encode()))


def main() -> None:
    pasta = os.environ.get("EASY_NFSE_DATA")
    if not pasta:
        sys.exit("Defina EASY_NFSE_DATA com uma pasta nova (ex.: /tmp/easy-nfse-demo).")
    if Path(pasta).exists() and any(Path(pasta).iterdir()):
        sys.exit(f"{pasta} já tem arquivos. Use uma pasta vazia: o script não sobrescreve dados.")

    from easy_nfse import storage
    from easy_nfse.models import (CertificadoSalvo, ComercioExterior, Emissao, Endereco, Origem, Prestador,
                                  Servico, Template, Tomador, Tributacao)

    # ids fixos no formato do app (8 hexadecimais), para as capturas terem sempre os mesmos endereços
    storage.ensure_dirs()
    jatoba = cnpj_com_digitos("123456780001")
    ipe = cnpj_com_digitos("456789010001")
    horta = cnpj_com_digitos("987654320001")
    marina = cpf_com_digitos("123456789")

    cfg = storage.load_config()
    for documento, nome, dias in [(jatoba, "JATOBA TECNOLOGIA ME", 135), (ipe, "ESTUDIO IPE LTDA", 21),
                                  (jatoba, "JATOBA TECNOLOGIA ME", -233)]:
        c = CertificadoSalvo(id=storage.new_id(), arquivo=f"{nome.split()[0].lower()}.pfx", senha="demo")
        storage.save_certificate(c.id, gerar_pfx(documento, nome, dias))
        cfg.certificados.append(c)
    cfg.numeracao = {cfg.chave_numeracao("2", jatoba, "1"): 41, cfg.chave_numeracao("2", ipe, "1"): 16}
    storage.save_config(cfg)

    bh = {"cod_municipio": "3106200", "municipio": "Belo Horizonte/MG"}
    prestadores = {
        "jatoba": Prestador(id="0a7b0a01", documento=jatoba, nome="Jatobá Tecnologia ME", email="contato@jatoba.dev",
                            op_simp_nac="3", reg_ap_trib_sn="1", **bh),
        "ipe": Prestador(id="0a7b0a02", documento=ipe, nome="Estúdio Ipê Ltda", email="ola@estudioipe.com.br",
                         op_simp_nac="3", reg_ap_trib_sn="1", **bh),
    }
    tomadores = {
        "acme": Tomador(id="ac3e0001", tipo_doc="NIF", documento="12-3456789", nome="Acme Corporation, Inc.",
                        endereco=Endereco(pais="US", cod_postal="19808", cidade="Wilmington", estado_prov="Delaware",
                                          logradouro="Centerville Rd", numero="2711", complemento="Suite 400")),
        "pixel": Tomador(id="b1c00002", tipo_doc="NIF", c_nao_nif="2", nome="Pixel Labs LLC",
                         endereco=Endereco(pais="US", cod_postal="78701", cidade="Austin", estado_prov="Texas",
                                           logradouro="Congress Ave", numero="500", complemento="Floor 3")),
        "horta": Tomador(id="40e00003", tipo_doc="CNPJ", documento=horta, nome="Horta Digital Ltda",
                         email="financeiro@hortadigital.com.br",
                         endereco=Endereco(cod_municipio="3106200", municipio="Belo Horizonte/MG",
                                           logradouro="Rua da Bahia", numero="1148", bairro="Centro")),
        "marina": Tomador(id="aa000004", tipo_doc="CPF", documento=marina, nome="Marina Duarte",
                          email="marina.duarte@email.com",
                          endereco=Endereco(cep="34000000", cod_municipio="3144805", municipio="Nova Lima/MG",
                                            logradouro="Alameda do Ipê", numero="80", bairro="Vale do Sereno")),
    }
    for p in prestadores.values():
        storage.save_prestador(p)
    for t in tomadores.values():
        storage.save_tomador(t)

    exportacao = dict(tributacao=Tributacao(trib_issqn="3", pais_resultado="US", p_tot_trib_sn="6.00"),
                      com_ext=ComercioExterior(tp_moeda="220"))
    templates = [
        Template(id="7e000001", nome="Consultoria em TI para a Acme", prestador_id="0a7b0a01", tomador_id="ac3e0001",
                 servico=Servico(c_trib_nac="010700", c_nbs="115011000", descricao="Consultoria em tecnologia da informação",
                                 cod_municipio_prestacao="3106200", municipio_prestacao="Belo Horizonte/MG"),
                 origem=Origem(tipo="xml", numero_nfse="1180"), ultimo_valor="38420.00", ultimo_valor_moeda="7000.00",
                 **exportacao),
        Template(id="7e000002", nome="Desenvolvimento sob demanda e manutenção evolutiva", prestador_id="0a7b0a02",
                 tomador_id="b1c00002",
                 servico=Servico(c_trib_nac="010101", c_nbs="115021000", descricao="Desenvolvimento de software sob encomenda",
                                 cod_municipio_prestacao="3106200", municipio_prestacao="Belo Horizonte/MG"),
                 origem=Origem(tipo="pdf", numero_nfse="2104"), ultimo_valor="12150.00", ultimo_valor_moeda="2200.00",
                 **exportacao),
        Template(id="7e000003", nome="Suporte mensal", prestador_id="0a7b0a01", tomador_id="40e00003",
                 servico=Servico(c_trib_nac="010700", descricao="Suporte técnico mensal",
                                 cod_municipio_prestacao="3106200", municipio_prestacao="Belo Horizonte/MG"),
                 tributacao=Tributacao(p_tot_trib_sn="6.00"), origem=Origem(tipo="xml", numero_nfse="812"),
                 ultimo_valor="4800.00"),
    ]
    for t in templates:
        storage.save_template(t)

    hoje = dt.datetime.now()
    for dias, t, tomador, valor, moeda, numero in [(12, templates[0], "Acme Corporation, Inc.", "38420.00", "7000.00", "2271"),
                                                   (15, templates[1], "Pixel Labs LLC", "12150.00", "2200.00", "2104"),
                                                   (29, templates[2], "Horta Digital Ltda", "4800.00", "", "812"),
                                                   (42, templates[0], "Acme Corporation, Inc.", "38420.00", "7000.00", "1180")]:
        quando = hoje - dt.timedelta(days=dias)
        chave = f"3106200210{t.prestador_id[:4]:0<4}{numero:0>9}{dias:0>4}".ljust(50, "0")[:50]
        e = Emissao(chave_acesso=chave, numero_nfse=numero, id_dps=f"DPS{chave[:42]}", serie="1", n_dps=int(numero) % 50,
                    ambiente="2", template_id=t.id, template_nome=t.nome, prestador_id=t.prestador_id,
                    tomador_id=t.tomador_id, tomador=tomador, valor=valor, valor_moeda=moeda, moeda="USD" if moeda else "",
                    competencia=f"{quando:%Y-%m-%d}", emitida_em=quando)
        storage.save_emissao(e, b"<DPS/>", None, {"demo": True})
    print(f"Dados fictícios criados em {pasta}")


if __name__ == "__main__":
    main()
