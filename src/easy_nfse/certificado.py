"""Certificado digital A1 (ICP-Brasil): leitura do .pfx, assinatura da DPS e contexto mTLS."""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

OID_CNPJ = "2.16.76.1.3.3"
OID_CPF = "2.16.76.1.3.1"
DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"


class CertificadoError(Exception):
    pass


def c14n(element: etree._Element) -> bytes:
    """C14N 1.0 inclusivo de um elemento como apex do subconjunto do documento.

    Não usamos etree.tostring(subelemento, method="c14n") diretamente: com o libxml2 2.14 ele
    emite xmlns="" espúrios nos filhos quando o namespace padrão vem de um ancestral. Canonicalizar
    uma cópia isolada produz o resultado correto, pois os namespaces em escopo são copiados.
    """
    return etree.tostring(copy.deepcopy(element), method="c14n")


@dataclass
class Certificado:
    key: object
    cert: x509.Certificate
    chain: list[x509.Certificate]

    @classmethod
    def load(cls, pfx: bytes, senha: str) -> "Certificado":
        try:
            key, cert, chain = pkcs12.load_key_and_certificates(pfx, senha.encode() if senha else None)
        except ValueError as exc:
            raise CertificadoError("Não foi possível abrir o certificado. Confira a senha.") from exc
        if key is None or cert is None:
            raise CertificadoError("O arquivo .pfx não contém chave privada e certificado.")
        return cls(key=key, cert=cert, chain=list(chain or []))

    # --- informações ------------------------------------------------------------

    @property
    def titular(self) -> str:
        cn = self.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return cn[0].value.split(":")[0] if cn else self.cert.subject.rfc4514_string()

    @property
    def documento(self) -> str:
        """CNPJ (e-CNPJ) ou CPF (e-CPF) do titular, lido das extensões ICP-Brasil."""
        try:
            san = self.cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            for other in san.get_values_for_type(x509.OtherName):
                raw = re.sub(rb"\D", b"", other.value).decode()
                if other.type_id.dotted_string == OID_CNPJ and len(raw) >= 14:
                    return raw[-14:]
                if other.type_id.dotted_string == OID_CPF and len(raw) >= 19:
                    return raw[8:19]
        except x509.ExtensionNotFound:
            pass
        cn = self.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        m = re.search(r":(\d{11}|\d{14})$", cn[0].value) if cn else None
        return m.group(1) if m else ""

    @property
    def validade(self) -> datetime:
        return self.cert.not_valid_after_utc

    @property
    def impressao(self) -> str:
        return self.cert.fingerprint(hashes.SHA256()).hex()

    @property
    def vencido(self) -> bool:
        return self.validade < datetime.now(timezone.utc)

    # --- uso ----------------------------------------------------------------------

    def assinar(self, root: etree._Element, reference_id: str) -> etree._Element:
        """Assina (XMLDSig enveloped, RSA-SHA256, C14N 1.0) o elemento com Id=reference_id.

        A assinatura fica como irmã de infDPS, dentro de <DPS>, sem prefixo "ds:".
        """
        target = root.find(f".//*[@Id='{reference_id}']")
        if target is None:
            raise CertificadoError(f"Elemento com Id {reference_id} não encontrado.")
        digest = hashlib.sha256(c14n(target)).digest()

        def ds(parent, tag, text=None, **attrib):
            el = etree.SubElement(parent, f"{{{DS}}}{tag}", attrib)
            if text is not None:
                el.text = text
            return el

        sig = etree.SubElement(root, f"{{{DS}}}Signature", nsmap={None: DS})
        info = ds(sig, "SignedInfo")
        ds(info, "CanonicalizationMethod", Algorithm=C14N)
        ds(info, "SignatureMethod", Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")
        ref = ds(info, "Reference", URI=f"#{reference_id}")
        transforms = ds(ref, "Transforms")
        ds(transforms, "Transform", Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
        ds(transforms, "Transform", Algorithm=C14N)
        ds(ref, "DigestMethod", Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
        ds(ref, "DigestValue", base64.b64encode(digest).decode())
        assinatura = self.key.sign(c14n(info), padding.PKCS1v15(), hashes.SHA256())
        ds(sig, "SignatureValue", base64.b64encode(assinatura).decode())
        x509_data = ds(ds(sig, "KeyInfo"), "X509Data")
        der = self.cert.public_bytes(serialization.Encoding.DER)
        ds(x509_data, "X509Certificate", base64.b64encode(der).decode())
        return root

    def ssl_context(self, verificar_tls: bool = True) -> ssl.SSLContext:
        """Contexto TLS com o certificado do cliente (mTLS exigido pela Sefin Nacional)."""
        if verificar_tls:
            ctx = ssl.create_default_context(cafile=certifi.where())
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        key_pem = self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        chain_pem = self.cert.public_bytes(serialization.Encoding.PEM) + b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in self.chain
        )
        # load_cert_chain só aceita caminhos: arquivos temporários privados, apagados logo em seguida.
        with tempfile.TemporaryDirectory(prefix="easy-nfse-") as tmp:
            cert_path, key_path = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
            for path, data in ((cert_path, chain_pem), (key_path, key_pem)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            ctx.load_cert_chain(cert_path, key_path)
        return ctx
