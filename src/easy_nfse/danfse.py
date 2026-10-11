"""Geração do DANFSe v2.0 (PDF) a partir do XML da NFS-e, conforme a NT 008/2026 (SE/CGNFS-e).

Desde 03/08/2026 a API oficial de DANFSe foi suspensa: cada sistema emissor gera o seu.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from . import dominios, ibge
from .sefin import CONSULTA_PUBLICA
from .util import UF_POR_CODIGO, digits, fmt_doc, fmt_money

LOGO = Path(__file__).parent / "static" / "nfse-logo.png"
CINZA = Color(0.95, 0.95, 0.95)
VERMELHO = Color(0.85, 0, 0)

L, R = 0.30 * cm, 20.70 * cm  # margens do corpo (NT 008, item 2.4.5)
COL = (R - L) / 4
FONTE, NEGRITO = "Helvetica", "Helvetica-Bold"

OP_SIMP_NAC = {"1": "Não Optante", "2": "Optante - Microempreendedor Individual (MEI)",
               "3": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)"}
REG_AP_TRIB_SN = {
    "1": "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
    "2": "Regime de apuração dos tributos federais pelo SN e o ISSQN pela NFS-e conforme respectiva legislação municipal do tributo",
    "3": "Regime de apuração dos tributos federais e municipal pela NFS-e conforme respectivas legislações federal e municipal de cada tributo",
}
REG_ESP = {"0": "Nenhum", "1": "Ato Cooperado (Cooperativa)", "2": "Estimativa", "3": "Microempresa Municipal",
           "4": "Notário ou Registrador", "5": "Profissional Autônomo", "6": "Sociedade de Profissionais", "9": "Outros"}
TRIB_ISSQN = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação de Serviço", "4": "Não Incidência"}
RET_ISSQN = {"1": "Não Retido", "2": "Retido pelo Tomador", "3": "Retido pelo Intermediário"}
EMITENTE = {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}
SITUACAO = {"100": "NFS-e Gerada", "101": "NFS-e de Substituição Gerada",
            "102": "NFS-e de Decisão Judicial", "103": "NFS-e Avulsa"}


# --------------------------------------------------------------------------------------
# leitura do XML
# --------------------------------------------------------------------------------------

class _X:
    """Acesso a elementos do XML ignorando namespace: x("DPS/infDPS/prest/CNPJ")."""

    def __init__(self, el):
        self.el = el

    def find(self, path: str):
        if self.el is None:
            return None
        found = self.el.xpath("./" + "/".join(f"*[local-name()='{p}']" for p in path.split("/")))
        return found[0] if found else None

    def __call__(self, path: str) -> str:
        f = self.find(path)
        return (f.text or "").strip() if f is not None else ""

    def sub(self, path: str) -> "_X":
        return _X(self.find(path))


def _d(v: str) -> str:
    return v or "-"


def _money(v: str) -> str:
    return fmt_money(Decimal(v)) if v else "-"


def _pct(v: str) -> str:
    return f"{Decimal(v):.2f}".replace(".", ",") + "%" if v else "-"


def _data(v: str) -> str:
    return datetime.fromisoformat(v).strftime("%d/%m/%Y") if v else "-"


def _datahora(v: str) -> str:
    return datetime.fromisoformat(v).strftime("%d/%m/%Y %H:%M:%S") if v else "-"


def _fone(v: str) -> str:
    d = digits(v)
    if len(d) in (10, 11):
        return f"({d[:2]}) {d[2:-4]}-{d[-4:]}"
    return d or "-"


def _cep(v: str) -> str:
    d = digits(v)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else _d(v)


def _nbs(v: str) -> str:
    d = digits(v)
    return f"{d[0]}.{d[1:5]}.{d[5:7]}.{d[7:]}" if len(d) == 9 else "-"


def _ctrib(v: str) -> str:
    d = digits(v)
    return f"{d[:2]}.{d[2:4]}.{d[4:]}" if len(d) == 6 else _d(v)


def _municipio(cod: str, nome: str = "") -> str:
    uf = UF_POR_CODIGO.get((cod or "")[:2], "")
    if not nome and cod:
        nome = ibge.nome(cod).split("/")[0] or cod  # sem acesso ao IBGE, mostra o código
    return f"{nome} / {uf}" if nome and uf else _d(nome)


def _endereco(e: _X) -> str:
    partes = [e("xLgr"), e("nro"), e("xCpl"), e("xBairro")]
    return ", ".join(p for p in partes if p) or "-"


def _pessoa(p: _X) -> dict:
    """Bloco de prestador/tomador do DPS (para o emitente usamos infNFSe/emit)."""
    doc = p("CNPJ") or p("CPF")
    nif = p("NIF") or p("cNaoNIF")
    end = p.sub("end")
    if end.find("endExt") is not None:
        ext = end.sub("endExt")
        pais = dominios.paises().get(ext("cPais"), ext("cPais"))
        mun = " / ".join(x for x in (ext("xCidade"), ext("xEstProvReg"), pais) if x)
        ibge_cep = f"{ext('cEndPost')} (ext)" if ext("cEndPost") else "-"
    elif end.find("endNac") is not None:
        cmun = end("endNac/cMun")
        mun = _municipio(cmun)
        ibge_cep = f"{cmun} / {_cep(end('endNac/CEP'))}"
    else:
        mun, ibge_cep = "-", "-"
    return {
        "doc": fmt_doc(doc) if doc else _d(nif),
        "im": _d(p("IM")),
        "fone": _fone(p("fone")),
        "nome": _d(p("xNome")),
        "mun": mun,
        "ibge_cep": ibge_cep,
        "end": _endereco(end) if end.el is not None else "-",
        "email": _d(p("email")),
    }


# --------------------------------------------------------------------------------------
# desenho
# --------------------------------------------------------------------------------------

class _Pagina:
    def __init__(self, c: Canvas):
        self.c = c
        self.y = A4[1] - 0.30 * cm  # cursor (de cima para baixo)

    # -- primitivas --------------------------------------------------------------------
    def linha(self, espessura: float = 0.5) -> None:
        self.c.setLineWidth(espessura)
        self.c.line(L, self.y, R, self.y)

    def _wrap(self, texto: str, largura: float, fonte: str, tam: float) -> list[str]:
        linhas: list[str] = []
        for paragrafo in (texto or "-").split("\n"):
            linhas.extend(simpleSplit(paragrafo, fonte, tam, largura) or [""])
        return linhas

    def _altura(self, celulas) -> float:
        alt = 0.0
        for rotulo, valor, span, opts in celulas:
            larg = COL * span - 0.2 * cm
            n = len(self._wrap(valor, larg, opts.get("fonte_valor", FONTE), opts.get("tam_valor", 7)))
            alt = max(alt, (8 if rotulo else 0) + n * 8.2 + 3)
        return alt

    def linha_celulas(self, celulas, sombra: set[int] | None = None) -> None:
        """celulas: lista de (rótulo, valor, colunas, opções). Desenha uma linha de até 4 colunas."""
        celulas = [(c + ({},))[:4] if len(c) == 3 else c for c in celulas]
        alt = self._altura(celulas)
        x = L
        for i, (rotulo, valor, span, opts) in enumerate(celulas):
            larg = COL * span
            if sombra and i in sombra:
                self.c.setFillColor(CINZA)
                self.c.rect(x, self.y - alt, larg, alt, stroke=0, fill=1)
                self.c.setFillColor(black)
            ty = self.y - 7.5
            if rotulo:
                self.c.setFont(NEGRITO, opts.get("tam_rotulo", 6))
                self.c.drawString(x + 0.12 * cm, ty, rotulo)
                ty -= 8
            fonte_v, tam_v = opts.get("fonte_valor", FONTE), opts.get("tam_valor", 7)
            self.c.setFont(fonte_v, tam_v)
            for ln in self._wrap(valor, larg - 0.2 * cm, fonte_v, tam_v):
                self.c.drawString(x + 0.12 * cm, ty, ln)
                ty -= 8.2
            x += larg
        self.y -= alt

    def titulo_bloco(self, titulo: str, celulas) -> None:
        """Primeira linha de um bloco: título (coluna 1, sombreado) + campos."""
        self.linha()
        cel = [("", "", 1, {})] + list(celulas)
        alt = self._altura([(c + ({},))[:4] if len(c) == 3 else c for c in cel])
        self.c.setFillColor(CINZA)
        self.c.rect(L, self.y - alt, COL, alt, stroke=0, fill=1)
        self.c.setFillColor(black)
        tam = 7.0  # NT 008: títulos de bloco em 7 pt; reduz se não couber na coluna
        while tam > 5 and stringWidth(titulo, NEGRITO, tam) > COL - 0.25 * cm:
            tam -= 0.25
        self.c.setFont(NEGRITO, tam)
        self.c.drawString(L + 0.12 * cm, self.y - 9, titulo)
        self.linha_celulas(cel)

    def faixa(self, texto: str) -> None:
        """Bloco suprimido (ex.: "INTERMEDIÁRIO ... NÃO IDENTIFICADO NA NFS-e")."""
        self.linha()
        self.c.setFont(FONTE, 7)
        self.c.drawCentredString((L + R) / 2, self.y - 8, texto)
        self.y -= 11

    def texto_largo(self, rotulo: str, valor: str, tam: float = 7) -> None:
        self.linha_celulas([(rotulo, valor, 4, {"tam_valor": tam})])


def gerar(nfse_xml: bytes) -> bytes:
    """Gera o PDF do DANFSe v2.0 para o XML de uma NFS-e do padrão nacional."""
    root = etree.fromstring(nfse_xml, etree.XMLParser(resolve_entities=False, no_network=True))
    inf_el = root.xpath("//*[local-name()='infNFSe']")
    if not inf_el:
        raise ValueError("XML sem infNFSe: não é uma NFS-e.")
    n = _X(inf_el[0])
    d = n.sub("DPS/infDPS")
    chave = (inf_el[0].get("Id") or "").removeprefix("NFS")
    homologacao = d("tpAmb") == "2"

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    c.setTitle(f"DANFSe {n('nNFSe')} - {chave}")
    c.setAuthor("easy-nfse")
    pg = _Pagina(c)

    # --- cabeçalho -------------------------------------------------------------------
    topo = pg.y
    alt_cab = 1.16 * cm
    c.setFillColor(CINZA)
    c.rect(L, topo - alt_cab, R - L, alt_cab, stroke=0, fill=1)
    c.setFillColor(black)
    if LOGO.exists():
        c.drawImage(ImageReader(str(LOGO)), 0.49 * cm, topo - 0.14 * cm - 0.85 * cm, width=4.0 * cm,
                    height=0.85 * cm, preserveAspectRatio=True, anchor="w", mask="auto")
    c.setFont(NEGRITO, 9)
    c.drawCentredString(10.5 * cm, topo - 0.42 * cm, "DANFSe v2.0")
    c.drawCentredString(10.5 * cm, topo - 0.78 * cm, "Documento Auxiliar da NFS-e")
    if homologacao:
        c.setFillColor(VERMELHO)
        c.drawCentredString(10.5 * cm, topo - 1.10 * cm, "NFS-e SEM VALIDADE JURÍDICA")
        c.setFillColor(black)
    uf_emi = n("emit/enderNac/UF")
    c.setFont(FONTE, 8)
    c.drawString(15.62 * cm, topo - 0.40 * cm, f"Município: {n('xLocEmi')}{' - ' + uf_emi if uf_emi else ''}")
    c.setFont(FONTE, 6)
    c.drawString(15.62 * cm, topo - 0.70 * cm, f"Ambiente Gerador: {n('ambGer')}")
    c.drawString(15.62 * cm, topo - 0.95 * cm, f"Tipo de Ambiente: {d('tpAmb')}")
    pg.y = topo - alt_cab

    # --- identificação ---------------------------------------------------------------
    pg.linha()
    ident_topo = pg.y
    rot = {"tam_rotulo": 7}
    pg.linha_celulas([("CHAVE DE ACESSO DA NFS-e", chave, 3, {**rot, "tam_valor": 8})])
    pg.linha_celulas([
        ("NÚMERO DA NFS-e", n("nNFSe"), 1, rot),
        ("COMPETÊNCIA DA NFS-e", _data(d("dCompet")), 1, rot),
        ("DATA E HORA DA EMISSÃO DA NFS-e", _datahora(n("dhProc")), 1, rot),
    ])
    pg.linha_celulas([
        ("NÚMERO DA DPS", d("nDPS"), 1, rot),
        ("SÉRIE DA DPS", d("serie"), 1, rot),
        ("DATA E HORA DA EMISSÃO DA DPS", _datahora(d("dhEmi")), 1, rot),
    ])
    pg.linha_celulas([
        ("EMITENTE DA NFS-e", EMITENTE.get(d("tpEmit"), "-"), 1, rot),
        ("SITUAÇÃO DA NFS-e", SITUACAO.get(n("cStat"), _d(n("cStat"))), 1, rot),
        ("FINALIDADE", "NFS-e regular" if n.find("IBSCBS") is not None else "-", 1, rot),
    ], sombra={0})
    # QR Code (x = 17,48 cm; y = 1,67 cm; mín. 1,52 cm)
    qr = QrCodeWidget(CONSULTA_PUBLICA.format(chave=chave))
    b = qr.getBounds()
    lado = 1.6 * cm
    dr = Drawing(lado, lado, transform=[lado / (b[2] - b[0]), 0, 0, lado / (b[3] - b[1]), 0, 0])
    dr.add(qr)
    renderPDF.draw(dr, c, 17.48 * cm, ident_topo - 0.12 * cm - lado)
    c.setFont(FONTE, 6)
    for i, t in enumerate(("A autenticidade desta NFS-e pode ser verificada",
                           "pela leitura deste código QR ou pela consulta da",
                           "chave de acesso no portal nacional da NFS-e")):
        c.drawString(15.62 * cm, ident_topo - 0.12 * cm - lado - 0.30 * cm - i * 7, t)
    pg.y = min(pg.y, ident_topo - 0.12 * cm - lado - 0.30 * cm - 2 * 7 - 4)

    # --- prestador (emitente) ----------------------------------------------------------
    e = n.sub("emit")
    prest = d.sub("prest")
    end_e = e.sub("enderNac")
    pg.titulo_bloco("PRESTADOR / FORNECEDOR", [
        ("CNPJ / CPF / NIF", fmt_doc(e("CNPJ") or e("CPF")), 1),
        ("Indicador Municipal (Inscrição)", _d(e("IM") or prest("IM")), 1),
        ("Telefone", _fone(e("fone") or prest("fone")), 1),
    ])
    pg.linha_celulas([
        ("Nome / Nome Empresarial", _d(e("xNome")), 2),
        ("Município / Sigla UF", _municipio(end_e("cMun"), n("xLocEmi")), 1),
        ("Código IBGE / CEP", f"{end_e('cMun')} / {_cep(end_e('CEP'))}", 1),
    ])
    pg.linha_celulas([
        ("Endereço", _endereco(end_e), 2),
        ("E-mail", _d(e("email") or prest("email")), 2),
    ])
    pg.linha_celulas([
        ("Simples Nacional na Data de Competência", OP_SIMP_NAC.get(prest("regTrib/opSimpNac"), "-"), 1),
        ("Regime de Apuração Tributária pelo SN", REG_AP_TRIB_SN.get(prest("regTrib/regApTribSN"), "-"), 3),
    ])

    # --- tomador / destinatário / intermediário ----------------------------------------
    if d.find("toma") is not None:
        t = _pessoa(d.sub("toma"))
        pg.titulo_bloco("TOMADOR / ADQUIRENTE", [
            ("CNPJ / CPF / NIF", t["doc"], 1), ("Indicador Municipal (Inscrição)", t["im"], 1),
            ("Telefone", t["fone"], 1),
        ])
        pg.linha_celulas([("Nome / Nome Empresarial", t["nome"], 2), ("Município / Sigla UF", t["mun"], 1),
                          ("Código IBGE / CEP", t["ibge_cep"], 1)])
        pg.linha_celulas([("Endereço", t["end"], 2), ("E-mail", t["email"], 2)])
    else:
        pg.faixa("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
    pg.faixa("DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
    if d.find("interm") is not None:
        i = _pessoa(d.sub("interm"))
        pg.titulo_bloco("INTERMEDIÁRIO DA OPERAÇÃO", [
            ("CNPJ / CPF / NIF", i["doc"], 1), ("Indicador Municipal (Inscrição)", i["im"], 1), ("Telefone", i["fone"], 1),
        ])
        pg.linha_celulas([("Nome / Nome Empresarial", i["nome"], 2), ("Município / Sigla UF", i["mun"], 1),
                          ("Código IBGE / CEP", i["ibge_cep"], 1)])
    else:
        pg.faixa("INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")

    # --- serviço -------------------------------------------------------------------------
    s = d.sub("serv")
    cod_mun = s("cServ/cTribMun")
    pais_prest = s("locPrest/cPaisPrestacao")
    if pais_prest:
        local = f"- / - / {dominios.paises().get(pais_prest, pais_prest)}"
    else:
        local = f"{_municipio(s('locPrest/cLocPrestacao'), n('xLocPrestacao'))} / -"
    pg.titulo_bloco("SERVIÇO PRESTADO", [
        ("Código de Tributação Nacional/Municipal", f"{_ctrib(s('cServ/cTribNac'))}{' / ' + cod_mun if cod_mun else ''}", 1),
        ("Código da NBS", _nbs(s("cServ/cNBS")), 1),
        ("Local da Prestação / Sigla UF / País", local, 1),
    ])
    pg.texto_largo("", n("xTribMun") or n("xTribNac"))
    pg.texto_largo("Descrição do Serviço", s("cServ/xDescServ"))

    # --- tributação municipal -------------------------------------------------------------
    v = d.sub("valores")
    tm = v.sub("trib/tribMun")
    vn = n.sub("valores")
    incid = _municipio(n("cLocIncid"), n("xLocIncid")) if n("cLocIncid") else "-"
    pg.titulo_bloco("TRIBUTAÇÃO MUNICIPAL (ISSQN)", [
        ("Tipo de Tributação do ISSQN", TRIB_ISSQN.get(tm("tribISSQN"), "-"), 1),
        ("Município / Sigla UF / País de Incidência do ISSQN", incid, 2),
    ])
    reg_esp = prest("regTrib/regEspTrib")
    if (reg_esp and reg_esp != "0") or tm("tpImunidade") or tm.find("exigSusp") is not None:
        pg.linha_celulas([
            ("Regime Especial de Tributação do ISSQN", REG_ESP.get(reg_esp, "-"), 1),
            ("Tipo de Imunidade do ISSQN", _d(tm("tpImunidade")), 1),
            ("Suspensão da Exigibilidade do ISSQN", "Sim" if tm.find("exigSusp") is not None else "Não", 1),
            ("Número Processo Suspensão", _d(tm("exigSusp/nProcesso")), 1),
        ])
    if tm.find("BM") is not None or v.find("vDedRed") is not None or v("vDescCondIncond/vDescIncond"):
        pg.linha_celulas([
            ("Benefício Municipal", _d(tm("BM/nBM")), 1),
            ("Cálculo do BM", _money(vn("vCalcBM")), 1),
            ("Total Deduções/Reduções", _money(vn("vCalcDR")), 1),
            ("Desconto Incondicionado", _money(v("vDescCondIncond/vDescIncond")), 1),
        ])
    pg.linha_celulas([
        ("BC ISSQN", _money(vn("vBC")), 1),
        ("Alíquota Aplicada", _pct(vn("pAliqAplic")), 1),
        ("Retenção do ISSQN", RET_ISSQN.get(tm("tpRetISSQN"), "-"), 1),
        ("ISSQN Apurado", _money(vn("vISSQN")), 1),
    ])

    # --- tributação federal ---------------------------------------------------------------
    tf = v.sub("trib/tribFed")
    pg.titulo_bloco("TRIBUTAÇÃO FEDERAL (EXCETO CBS)", [
        ("IRRF", _money(tf("vRetIRRF")), 1),
        ("Contribuição Previdenciária - Retida", _money(tf("vRetCP")), 1),
        ("Contribuições Sociais - Retidas", _money(tf("vRetCSLL")), 1),
    ])
    pg.linha_celulas([
        ("PIS - Débito Apuração Própria", _money(tf("piscofins/vPis")), 1),
        ("COFINS - Débito Apuração Própria", _money(tf("piscofins/vCofins")), 1),
        ("Descrição Contrib. Sociais - Retidas", "-", 2),
    ])

    # --- IBS / CBS (não informado por este emissor) ------------------------------------------
    pg.titulo_bloco("TRIBUTAÇÃO IBS / CBS", [
        ("CST / cClassTrib", "- / -", 1),
        ("Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF", "- / - / - / -", 2),
    ])

    # --- valor total ------------------------------------------------------------------------
    total_ret = vn("vTotalRet")
    pg.titulo_bloco("VALOR TOTAL DA NFS-e", [
        ("VALOR DA OPERAÇÃO / SERVIÇO", _money(v("vServPrest/vServ")), 1, {"tam_rotulo": 7}),
        ("Desconto Incondicionado", _money(v("vDescCondIncond/vDescIncond")), 1),
        ("Desconto Condicionado", _money(v("vDescCondIncond/vDescCond")), 1),
    ])
    pg.linha_celulas([
        ("Total das Retenções (ISSQN / Federais)", _money(total_ret), 1),
        ("VALOR LÍQUIDO DA NFS-e", _money(vn("vLiq")), 1, {"tam_rotulo": 7, "fonte_valor": NEGRITO}),
        ("Total do IBS/CBS", "-", 1),
        ("VALOR LÍQUIDO DA NFS-e + IBS/CBS", _money(vn("vLiq")), 1, {"tam_rotulo": 7, "fonte_valor": NEGRITO}),
    ], sombra={3})

    # --- informações complementares --------------------------------------------------------
    info: list[str] = []
    if s("infoCompl/xInfComp"):
        info.append(s("infoCompl/xInfComp"))
    if n("xOutInf"):
        info.append(n("xOutInf"))
    ce = s.sub("comExt")
    if ce.el is not None and ce("vServMoeda"):
        moeda = dominios.MOEDAS.get(ce("tpMoeda"), (f"moeda {ce('tpMoeda')}",))[0]
        info.append(f"Comércio exterior: valor do serviço em moeda estrangeira {moeda} "
                    f"{fmt_money(Decimal(ce('vServMoeda')))[3:]}.")
    tot = v.sub("trib/totTrib")
    if tot("pTotTribSN"):
        info.append(f"Totais aproximados dos Tributos cfe. Lei nº 12.741/2012: Simples Nacional: {_pct(tot('pTotTribSN'))}")
    elif tot.find("vTotTrib") is not None:
        info.append("Totais aproximados dos Tributos cfe. Lei nº 12.741/2012: "
                    f"Federais: {_money(tot('vTotTrib/vTotTribFed'))}; Estaduais: {_money(tot('vTotTrib/vTotTribEst'))}; "
                    f"Municipais: {_money(tot('vTotTrib/vTotTribMun'))};")
    elif tot.find("pTotTrib") is not None:
        info.append("Totais aproximados dos Tributos cfe. Lei nº 12.741/2012: "
                    f"Federais: {_pct(tot('pTotTrib/pTotTribFed'))}; Estaduais: {_pct(tot('pTotTrib/pTotTribEst'))}; "
                    f"Municipais: {_pct(tot('pTotTrib/pTotTribMun'))};")
    else:
        info.append("Totais aproximados dos Tributos cfe. Lei nº 12.741/2012: Federais: -; Estaduais: -; Municipais: -;")
    pg.linha()
    c.setFont(NEGRITO, 7)
    c.drawString(L + 0.12 * cm, pg.y - 9, "INFORMAÇÕES COMPLEMENTARES")
    pg.y -= 12
    pg.texto_largo("", "\n".join(info))

    # --- borda da página ----------------------------------------------------------------------
    c.setLineWidth(1)
    c.rect(L, 0.30 * cm, R - L, A4[1] - 0.60 * cm, stroke=1, fill=0)
    c.showPage()
    c.save()
    return buf.getvalue()
