"""Montagem e validação da DPS (Declaração de Prestação de Serviço), leiaute v1.01."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from lxml import etree

from . import __version__
from .models import Template
from .util import cnpj_valido, cpf_valido, digits, xml_text

NS = "http://www.sped.fazenda.gov.br/nfse"
VERSAO = "1.01"
XSD_DIR = Path(__file__).parent / "xsd"
TZ = ZoneInfo("America/Sao_Paulo")


class DPSError(Exception):
    def __init__(self, erros: list[str]):
        super().__init__("; ".join(erros))
        self.erros = erros


@dataclass
class DadosEmissao:
    competencia: date
    valor: Decimal
    descricao: str
    serie: str
    n_dps: int
    ambiente: str
    valor_moeda: Decimal | None = None  # valor na moeda estrangeira (exportação)
    dh_emi: datetime | None = None


def id_dps(t: Template, serie: str, n_dps: int) -> str:
    p = t.prestador
    tipo = "2" if p.tipo_doc == "CNPJ" else "1"
    return f"DPS{p.cod_municipio}{tipo}{digits(p.documento).zfill(14)}{int(serie):05d}{n_dps:015d}"


def validar_template(t: Template) -> list[str]:
    """Regras que conseguimos checar antes de enviar (evita rejeições óbvias)."""
    erros: list[str] = []
    p, s, tr = t.prestador, t.servico, t.tributacao
    doc = digits(p.documento)
    if p.tipo_doc == "CNPJ" and not cnpj_valido(doc):
        erros.append("CNPJ do prestador inválido.")
    if p.tipo_doc == "CPF" and not cpf_valido(doc):
        erros.append("CPF do prestador inválido.")
    if len(digits(p.cod_municipio)) != 7:
        erros.append("Código IBGE do município do prestador (emissor) não informado.")
    if p.op_simp_nac == "3" and not p.reg_ap_trib_sn:
        erros.append("Informe o regime de apuração do Simples Nacional (ME/EPP).")
    if p.op_simp_nac == "3" and not tr.p_tot_trib_sn:
        erros.append("ME/EPP: informe o percentual aproximado de tributos do Simples Nacional.")
    if len(digits(s.c_trib_nac)) != 6:
        erros.append("Código de tributação nacional deve ter 6 dígitos (ex.: 010101).")
    if s.c_trib_mun and len(digits(s.c_trib_mun)) != 3:
        erros.append("Código de tributação municipal deve ter 3 dígitos.")
    if s.c_nbs and len(digits(s.c_nbs)) != 9:
        erros.append("Código NBS deve ter 9 dígitos.")
    if s.pais_prestacao:
        if s.pais_prestacao == "BR":
            erros.append("Para prestação no Brasil, informe o município (não o país).")
    elif len(digits(s.cod_municipio_prestacao)) != 7:
        erros.append("Código IBGE do local da prestação não informado.")
    if tr.trib_issqn == "2" and not tr.tp_imunidade:
        erros.append("Informe o tipo de imunidade.")
    if tr.trib_issqn in ("2", "3", "4"):
        if p.reg_esp_trib not in ("", "0"):
            erros.append("Com imunidade, exportação ou não incidência, o regime especial deve ser 'Nenhum' (E0172).")
        if tr.tp_ret_issqn != "1":
            erros.append("Com imunidade, exportação ou não incidência, o ISSQN não pode ser retido.")
    if tr.trib_issqn == "3" and tr.p_aliq:
        erros.append("Não informe alíquota de ISSQN para exportação de serviço.")
    if t.tomador_exterior and tr.trib_issqn == "3" and not s.pais_prestacao and not tr.pais_resultado:
        erros.append("Exportação com prestação no Brasil: informe o país onde ocorre o resultado do serviço (E0590).")
    if tr.pais_resultado == "BR":
        erros.append("O país do resultado da exportação não pode ser o Brasil.")
    if t.tomador and t.tomador.tipo_doc:
        to = t.tomador
        dt = digits(to.documento)
        if to.tipo_doc == "CNPJ" and not cnpj_valido(dt):
            erros.append("CNPJ do tomador inválido.")
        if to.tipo_doc == "CPF" and not cpf_valido(dt):
            erros.append("CPF do tomador inválido.")
        if to.tipo_doc == "NIF" and not to.documento.strip() and to.c_nao_nif not in ("1", "2"):
            erros.append("Tomador do exterior: informe o NIF ou o motivo para não informá-lo.")
        if not to.nome.strip():
            erros.append("Nome do tomador é obrigatório.")
        e = to.endereco
        if to.tipo_doc == "NIF":
            if not e.exterior:
                erros.append("Tomador do exterior: informe o país do endereço (diferente de Brasil).")
            elif not e.completo():
                erros.append("Endereço do tomador no exterior incompleto (código postal, cidade, estado/província e logradouro).")
        elif e.exterior:
            erros.append("Tomador com CPF/CNPJ deve ter endereço no Brasil; para exterior, use NIF.")
        elif e.preenchido() and not e.completo():
            erros.append("Endereço do tomador incompleto (CEP, município, logradouro, número e bairro).")
    if t.exige_com_ext:
        if len(digits(s.c_nbs)) != 9:
            erros.append("Exportação/tomador do exterior: o código NBS é obrigatório (E0318).")
        c = t.com_ext
        if len(digits(c.tp_moeda)) != 3:
            erros.append("Comércio exterior: informe a moeda (código BACEN de 3 dígitos).")
        if c.mov_temp_bens == "2" and not c.n_di:
            erros.append("Comércio exterior: informe o número da DI (E0352).")
    return erros


def _sub(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _opt(parent: etree._Element, tag: str, text: str | None) -> None:
    if text:
        _sub(parent, tag, text)


def _dec(value: str | Decimal) -> str:
    return f"{Decimal(str(value).replace(',', '.')):.2f}"


def montar(t: Template, d: DadosEmissao) -> tuple[etree._Element, str]:
    """Monta o XML (sem assinatura). Retorna (raiz <DPS>, Id do infDPS)."""
    erros = validar_template(t)
    if d.valor <= 0:
        erros.append("O valor do serviço deve ser maior que zero.")
    dh_emi = d.dh_emi or (datetime.now(TZ) - timedelta(minutes=1))  # margem p/ relógio (E0008)
    if d.competencia > dh_emi.date():
        erros.append("A data de competência não pode ser posterior à data de emissão (hoje).")
    if not d.descricao.strip():
        erros.append("A descrição do serviço é obrigatória.")
    if t.exige_com_ext and (d.valor_moeda is None or d.valor_moeda <= 0):
        erros.append("Informe o valor do serviço na moeda estrangeira.")
    if erros:
        raise DPSError(erros)

    p, s, tr = t.prestador, t.servico, t.tributacao
    ident = id_dps(t, d.serie, d.n_dps)

    root = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS}, versao=VERSAO)
    inf = _sub(root, "infDPS")
    inf.set("Id", ident)
    _sub(inf, "tpAmb", d.ambiente)
    _sub(inf, "dhEmi", dh_emi.isoformat(timespec="seconds"))
    _sub(inf, "verAplic", f"easy-nfse-{__version__}")
    _sub(inf, "serie", str(int(d.serie)))
    _sub(inf, "nDPS", str(d.n_dps))
    _sub(inf, "dCompet", d.competencia.isoformat())
    _sub(inf, "tpEmit", "1")
    _sub(inf, "cLocEmi", p.cod_municipio)

    prest = _sub(inf, "prest")
    _sub(prest, p.tipo_doc, digits(p.documento))
    _opt(prest, "IM", xml_text(p.im))
    _opt(prest, "fone", digits(p.fone))
    _opt(prest, "email", xml_text(p.email))
    reg = _sub(prest, "regTrib")
    _sub(reg, "opSimpNac", p.op_simp_nac)
    if p.op_simp_nac == "3":
        _sub(reg, "regApTribSN", p.reg_ap_trib_sn)
    _sub(reg, "regEspTrib", p.reg_esp_trib or "0")

    if t.tomador and t.tomador.tipo_doc:
        to = t.tomador
        toma = _sub(inf, "toma")
        if to.tipo_doc == "NIF":
            if to.documento.strip():
                _sub(toma, "NIF", xml_text(to.documento)[:40])
            else:
                _sub(toma, "cNaoNIF", to.c_nao_nif)
        else:
            _sub(toma, to.tipo_doc, digits(to.documento))
        _opt(toma, "IM", xml_text(to.im))
        _sub(toma, "xNome", xml_text(to.nome))
        e = to.endereco
        if e.completo():
            end = _sub(toma, "end")
            if e.exterior:
                ext = _sub(end, "endExt")
                _sub(ext, "cPais", e.pais)
                _sub(ext, "cEndPost", xml_text(e.cod_postal)[:11])
                _sub(ext, "xCidade", xml_text(e.cidade)[:60])
                _sub(ext, "xEstProvReg", xml_text(e.estado_prov)[:60])
            else:
                nac = _sub(end, "endNac")
                _sub(nac, "cMun", digits(e.cod_municipio))
                _sub(nac, "CEP", digits(e.cep))
            _sub(end, "xLgr", xml_text(e.logradouro))
            # no exterior nem sempre há número/bairro, mas o leiaute exige os campos
            _sub(end, "nro", xml_text(e.numero) or "S/N")
            _opt(end, "xCpl", xml_text(e.complemento))
            _sub(end, "xBairro", xml_text(e.bairro) or "-")
        _opt(toma, "fone", digits(to.fone))
        _opt(toma, "email", xml_text(to.email))

    serv = _sub(inf, "serv")
    loc = _sub(serv, "locPrest")
    if s.pais_prestacao:
        _sub(loc, "cPaisPrestacao", s.pais_prestacao)
    else:
        _sub(loc, "cLocPrestacao", digits(s.cod_municipio_prestacao))
    cserv = _sub(serv, "cServ")
    _sub(cserv, "cTribNac", digits(s.c_trib_nac))
    _opt(cserv, "cTribMun", digits(s.c_trib_mun))
    _sub(cserv, "xDescServ", xml_text(d.descricao, multiline=True)[:2000])
    _opt(cserv, "cNBS", digits(s.c_nbs))
    if t.exige_com_ext:
        c = t.com_ext
        com = _sub(serv, "comExt")
        _sub(com, "mdPrestacao", c.md_prestacao)
        _sub(com, "vincPrest", c.vinc_prest)
        _sub(com, "tpMoeda", digits(c.tp_moeda))
        _sub(com, "vServMoeda", _dec(d.valor_moeda))
        _sub(com, "mecAFComexP", c.mec_af_comex_p)
        _sub(com, "mecAFComexT", c.mec_af_comex_t)
        _sub(com, "movTempBens", c.mov_temp_bens)
        _opt(com, "nDI", xml_text(c.n_di)[:12])
        _opt(com, "nRE", xml_text(c.n_re)[:12])
        _sub(com, "mdic", c.mdic)

    valores = _sub(inf, "valores")
    vsp = _sub(valores, "vServPrest")
    _sub(vsp, "vServ", _dec(d.valor))
    trib = _sub(valores, "trib")
    tmun = _sub(trib, "tribMun")
    _sub(tmun, "tribISSQN", tr.trib_issqn)
    # cPaisResult: só na exportação com prestação no Brasil (E0590/E0591)
    if tr.trib_issqn == "3" and tr.pais_resultado and not s.pais_prestacao:
        _sub(tmun, "cPaisResult", tr.pais_resultado)
    if tr.trib_issqn == "2":
        _sub(tmun, "tpImunidade", tr.tp_imunidade)
    _sub(tmun, "tpRetISSQN", tr.tp_ret_issqn)
    if tr.p_aliq:
        _sub(tmun, "pAliq", _dec(tr.p_aliq))
    tot = _sub(trib, "totTrib")
    if p.op_simp_nac == "3":
        _sub(tot, "pTotTribSN", _dec(tr.p_tot_trib_sn))
    else:
        _sub(tot, "indTotTrib", "0")

    validar_xsd(root)
    return root, ident


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=False)
    return etree.XMLSchema(etree.parse(str(XSD_DIR / "DPS_v1.01.xsd"), parser))


def validar_xsd(root: etree._Element) -> None:
    schema = _schema()
    if not schema.validate(root):
        raise DPSError([f"XSD: {e.message}" for e in schema.error_log])


def serializar(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
