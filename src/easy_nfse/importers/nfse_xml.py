"""Importa um template a partir do XML de uma NFS-e (ou de uma DPS) do padrão nacional.

É a fonte mais fiel: copiamos exatamente o que foi declarado na DPS original.
"""

from __future__ import annotations

from lxml import etree

from ..models import ComercioExterior, Endereco, Origem, Prestador, Servico, Template, Tomador, Tributacao
from ..util import fmt_money, parse_money


class XMLImportError(Exception):
    pass


def _find(el: etree._Element | None, path: str) -> etree._Element | None:
    if el is None:
        return None
    xpath = "./" + "/".join(f"*[local-name()='{p}']" for p in path.split("/"))
    found = el.xpath(xpath)
    return found[0] if found else None


def _txt(el: etree._Element | None, path: str) -> str:
    found = _find(el, path)
    return (found.text or "").strip() if found is not None else ""


def parse(data: bytes, arquivo: str = "") -> dict:
    """Retorna kwargs para Template (sem id/nome)."""
    try:
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise XMLImportError(f"XML inválido: {exc}") from exc

    found = root.xpath("//*[local-name()='infDPS']")
    if not found:
        raise XMLImportError("Não encontrei uma DPS (infDPS) neste XML. É o XML da NFS-e do padrão nacional?")
    inf = found[0]
    inf_nfse = (root.xpath("//*[local-name()='infNFSe']") or [None])[0]

    prest_el = _find(inf, "prest")
    p = Prestador(
        tipo_doc="CPF" if _txt(prest_el, "CPF") else "CNPJ",
        documento=_txt(prest_el, "CNPJ") or _txt(prest_el, "CPF"),
        nome=_txt(inf_nfse, "emit/xNome") or _txt(prest_el, "xNome"),
        im=_txt(prest_el, "IM"),
        fone=_txt(prest_el, "fone"),
        email=_txt(prest_el, "email"),
        cod_municipio=_txt(inf, "cLocEmi"),
        municipio=_txt(inf_nfse, "xLocEmi"),
        op_simp_nac=_txt(prest_el, "regTrib/opSimpNac") or "1",
        reg_ap_trib_sn=_txt(prest_el, "regTrib/regApTribSN"),
        reg_esp_trib=_txt(prest_el, "regTrib/regEspTrib") or "0",
    )

    toma_el = _find(inf, "toma")
    tomador = None
    if toma_el is not None:
        exterior = bool(_txt(toma_el, "NIF") or _txt(toma_el, "cNaoNIF")) or _find(toma_el, "end/endExt") is not None
        if exterior:
            tipo_doc, documento = "NIF", _txt(toma_el, "NIF")
        else:
            tipo_doc = "CNPJ" if _txt(toma_el, "CNPJ") else "CPF"
            documento = _txt(toma_el, "CNPJ") or _txt(toma_el, "CPF")
        c_nao_nif = _txt(toma_el, "cNaoNIF")
        tomador = Tomador(
            tipo_doc=tipo_doc,
            documento=documento,
            c_nao_nif=c_nao_nif if c_nao_nif in ("1", "2") else "",
            nome=_txt(toma_el, "xNome"),
            im=_txt(toma_el, "IM"),
            fone=_txt(toma_el, "fone"),
            email=_txt(toma_el, "email"),
            endereco=Endereco(
                pais=_txt(toma_el, "end/endExt/cPais"),
                cod_postal=_txt(toma_el, "end/endExt/cEndPost"),
                cidade=_txt(toma_el, "end/endExt/xCidade"),
                estado_prov=_txt(toma_el, "end/endExt/xEstProvReg"),
                cep=_txt(toma_el, "end/endNac/CEP"),
                cod_municipio=_txt(toma_el, "end/endNac/cMun"),
                logradouro=_txt(toma_el, "end/xLgr"),
                numero=_txt(toma_el, "end/nro"),
                complemento=_txt(toma_el, "end/xCpl"),
                bairro=_txt(toma_el, "end/xBairro"),
            ),
        )

    serv_el = _find(inf, "serv")
    s = Servico(
        c_trib_nac=_txt(serv_el, "cServ/cTribNac"),
        c_trib_nac_desc=_txt(inf_nfse, "xTribNac"),
        c_trib_mun=_txt(serv_el, "cServ/cTribMun"),
        c_nbs=_txt(serv_el, "cServ/cNBS"),
        descricao=_txt(serv_el, "cServ/xDescServ"),
        cod_municipio_prestacao=_txt(serv_el, "locPrest/cLocPrestacao"),
        municipio_prestacao=_txt(inf_nfse, "xLocPrestacao") if _txt(serv_el, "locPrest/cLocPrestacao") else "",
        pais_prestacao=_txt(serv_el, "locPrest/cPaisPrestacao"),
    )
    ce = _find(serv_el, "comExt")
    com_ext = ComercioExterior()
    if ce is not None:
        com_ext = ComercioExterior(
            md_prestacao=_txt(ce, "mdPrestacao") or "1",
            vinc_prest=_txt(ce, "vincPrest") or "0",
            tp_moeda=_txt(ce, "tpMoeda") or "220",
            mec_af_comex_p=_txt(ce, "mecAFComexP") or "01",
            mec_af_comex_t=_txt(ce, "mecAFComexT") or "01",
            mov_temp_bens=_txt(ce, "movTempBens") or "1",
            n_di=_txt(ce, "nDI"),
            n_re=_txt(ce, "nRE"),
            mdic=_txt(ce, "mdic") or "0",
        )
    valor_moeda = parse_money(_txt(ce, "vServMoeda")) if ce is not None else None

    tm = _find(inf, "valores/trib/tribMun")
    tr = Tributacao(
        trib_issqn=_txt(tm, "tribISSQN") or "1",
        pais_resultado=_txt(tm, "cPaisResult"),
        tp_imunidade=_txt(tm, "tpImunidade"),
        tp_ret_issqn=_txt(tm, "tpRetISSQN") or "1",
        p_aliq=_txt(tm, "pAliq"),
        p_tot_trib_sn=_txt(inf, "valores/trib/totTrib/pTotTribSN"),
    )

    avisos = []
    if _find(inf, "interm") is not None:
        avisos.append("A nota original tem intermediário; ele não será repetido nas novas emissões.")
    ajuste_bc = _find(inf, "valores/vDedRed") is not None or _find(inf, "valores/vAjusteBC") is not None  # NT 009
    if _find(inf, "valores/trib/tribFed") is not None or ajuste_bc:
        avisos.append("A nota original tem tributação federal/deduções; esses grupos não são copiados.")
    if _find(inf, "IBSCBS") is not None:
        avisos.append("A nota original tem grupo IBS/CBS; ele não é copiado (opcional em 2026).")

    valor = parse_money(_txt(inf, "valores/vServPrest/vServ"))
    chave = (inf_nfse.get("Id", "") if inf_nfse is not None else "").removeprefix("NFS")
    return dict(
        prestador=p,
        tomador=tomador,
        servico=s,
        tributacao=tr,
        com_ext=com_ext,
        origem=Origem(
            tipo="xml",
            arquivo=arquivo,
            chave_acesso=chave,
            numero_nfse=_txt(inf_nfse, "nNFSe"),
            competencia=_txt(inf, "dCompet"),
            valor=fmt_money(valor) if valor else "",
            valor_moeda=str(valor_moeda) if valor_moeda else "",
            aliquota_original=_txt(tm, "pAliq"),
        ),
        ultimo_valor=str(valor) if valor else "",
        ultimo_valor_moeda=str(valor_moeda) if valor_moeda else "",
        avisos=avisos,
    )
