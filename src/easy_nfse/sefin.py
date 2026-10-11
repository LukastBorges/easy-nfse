"""Cliente da API da Sefin Nacional (Emissor Público Nacional da NFS-e)."""

from __future__ import annotations

import base64
import gzip
import re
from dataclasses import dataclass, field

import httpx

from .certificado import Certificado

BASE_URL = {
    "1": "https://sefin.nfse.gov.br/SefinNacional",
    "2": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
}
CONSULTA_PUBLICA = "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave={chave}"


class SefinError(Exception):
    def __init__(self, mensagens: list[str], status: int | None = None, resposta: dict | None = None):
        super().__init__("; ".join(mensagens))
        self.mensagens = mensagens
        self.status = status
        self.resposta = resposta or {}

    @property
    def codigos(self) -> set[str]:
        return {m.split(" ", 1)[0] for m in self.mensagens}


@dataclass
class ResultadoEmissao:
    chave_acesso: str
    id_dps: str
    nfse_xml: bytes | None
    alertas: list[str] = field(default_factory=list)
    resposta: dict = field(default_factory=dict)


def gzip_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode()


def ungzip_b64(data: str) -> bytes:
    return gzip.decompress(base64.b64decode(data))


def _get(d: dict, *keys: str):
    """Busca chave ignorando maiúsculas/minúsculas (a API varia entre versões)."""
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def _mensagens(payload: dict, chave: str = "erros") -> list[str]:
    itens = _get(payload, chave, chave[:-1]) or []
    if isinstance(itens, dict):
        itens = [itens]
    msgs = []
    for e in itens:
        if not isinstance(e, dict):
            msgs.append(str(e))
            continue
        cod = _get(e, "codigo", "code") or ""
        desc = _get(e, "descricao", "mensagem", "message") or ""
        comp = _get(e, "complemento") or ""
        msgs.append(" ".join(x for x in (str(cod), desc, f"({comp})" if comp else "") if x).strip())
    return msgs


class SefinClient:
    def __init__(self, cert: Certificado, ambiente: str, verificar_tls: bool = True, timeout: float = 60):
        self.base = BASE_URL[ambiente]
        self._client = httpx.Client(
            verify=cert.ssl_context(verificar_tls),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def __enter__(self) -> "SefinClient":
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _json(self, resp: httpx.Response) -> dict:
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"dados": data}
        except ValueError:
            titulo = re.search(r"<title>(.*?)</title>", resp.text, re.S | re.I)
            texto = titulo.group(1).strip() if titulo else resp.text[:300].strip()
            if resp.status_code in (401, 403):
                texto += " O certificado não foi aceito: use o A1 ICP-Brasil válido do emitente."
            return {"texto": texto}

    def emitir(self, dps_assinada: bytes) -> ResultadoEmissao:
        resp = self._client.post(f"{self.base}/nfse", json={"dpsXmlGZipB64": gzip_b64(dps_assinada)})
        data = self._json(resp)
        if resp.status_code >= 400 or not _get(data, "chaveAcesso"):
            msgs = _mensagens(data) or [f"HTTP {resp.status_code}: {data.get('texto') or data}"]
            raise SefinError(msgs, resp.status_code, data)
        xml_b64 = _get(data, "nfseXmlGZipB64")
        return ResultadoEmissao(
            chave_acesso=_get(data, "chaveAcesso"),
            id_dps=_get(data, "idDps") or "",
            nfse_xml=ungzip_b64(xml_b64) if xml_b64 else None,
            alertas=_mensagens(data, "alertas"),
            resposta={k: v for k, v in data.items() if k.lower() != "nfsexmlgzipb64"},
        )

    def consultar_nfse(self, chave: str) -> bytes:
        resp = self._client.get(f"{self.base}/nfse/{chave}")
        data = self._json(resp)
        xml_b64 = _get(data, "nfseXmlGZipB64")
        if resp.status_code >= 400 or not xml_b64:
            raise SefinError(_mensagens(data) or [f"HTTP {resp.status_code}"], resp.status_code, data)
        return ungzip_b64(xml_b64)

    def consultar_dps(self, id_dps: str) -> str | None:
        """Chave de acesso da NFS-e gerada a partir da DPS, ou None se não existir."""
        resp = self._client.get(f"{self.base}/dps/{id_dps}")
        if resp.status_code == 404:
            return None
        data = self._json(resp)
        if resp.status_code >= 400:
            raise SefinError(_mensagens(data) or [f"HTTP {resp.status_code}"], resp.status_code, data)
        return _get(data, "chaveAcesso")

    def testar(self) -> int:
        """HEAD /dps/{id fictício}: qualquer certificado válido pode consultar (404 = conexão OK)."""
        fake = "DPS" + "0" * 42
        return self._client.head(f"{self.base}/dps/{fake}").status_code
