"""Importação de notas anteriores (XML ou PDF) para templates."""

from __future__ import annotations

import re

from .. import ibge, storage
from ..models import Endereco, Origem, Prestador, Servico, Template, Tomador, Tributacao
from ..util import digits, empty_if_dash, fmt_money, norm, parse_money, parse_percent, split_municipio_uf
from .. import dominios
from . import danfse_pdf, nfse_xml


class ImportacaoError(Exception):
    pass


# --------------------------------------------------------------------------------------
# Mapeamento de textos impressos -> códigos do leiaute
# --------------------------------------------------------------------------------------

def _op_simp_nac(texto: str) -> str | None:
    n = norm(texto)
    if "mei" in n or "microempreendedor" in n:
        return "2"
    if "epp" in n or "microempresa" in n or "pequenoporte" in n:
        return "3"
    if "naooptante" in n:
        return "1"
    return None


def _reg_ap_trib_sn(texto: str) -> str:
    n = norm(texto)
    if not n:
        return ""
    if "issqn" in n:
        return "2"
    if "nfse" in n or "legislacoes" in n or "fora" in n:
        return "3"
    return "1" if "sn" in n or "simples" in n else ""


def _reg_esp_trib(texto: str) -> str:
    n = norm(texto)
    for chave, cod in (("cooperado", "1"), ("estimativa", "2"), ("microempresamunicipal", "3"),
                       ("notario", "4"), ("autonomo", "5"), ("sociedade", "6"), ("outros", "9")):
        if chave in n:
            return cod
    return "0"


def _trib_issqn(texto: str) -> str:
    n = norm(texto)
    for chave, cod in (("imunidade", "2"), ("exportacao", "3"), ("naoincidencia", "4")):
        if chave in n:
            return cod
    return "1"


def _tp_ret_issqn(texto: str) -> str:
    n = norm(texto)
    if "intermediario" in n:
        return "3"
    if "tomador" in n:
        return "2"
    return "1"


def _endereco(texto: str) -> dict[str, str]:
    """Quebra um endereço impresso em partes.

    "GOETHE , 37 , Bairro RIO BRANCO , CEP 90430100 , Porto Alegre/RS"  (Consulta Pública)
    "RIACHUELO, 843, CENTRO HISTORICO"                                  (DANFSe)
    """
    t = re.sub(r"\s+", " ", empty_if_dash(texto))
    if not t:
        return {}
    res: dict[str, str] = {}
    resto: list[str] = []
    rotulado = False
    for parte in (p.strip() for p in t.split(",")):
        if not parte:
            continue
        if re.match(r"(?i)^bairro\b", parte):
            res["bairro"] = parte[6:].strip()
            rotulado = True
        elif re.match(r"(?i)^cep\b", parte) and len(digits(parte)) == 8:
            res["cep"] = digits(parte)
            rotulado = True
        elif rotulado and re.search(r"/[A-Za-z]{2}$", parte):
            res["municipio"] = parte
        else:
            resto.append(parte)
    if "bairro" not in res and not rotulado and len(resto) >= 3:
        res["bairro"] = resto.pop()
    if resto:
        res["logradouro"] = resto.pop(0)
    if resto:
        res["numero"] = resto.pop(0)
    if resto:
        res["complemento"] = ", ".join(resto)
    # "PC DOS TRES PODERES S/N , Anexo 4" -> número embutido no logradouro
    m = re.match(r"^(.*\S)\s+(S/?N|\d+[A-Za-z]?)$", res.get("logradouro", ""))
    if m and (not res.get("numero") or not re.fullmatch(r"(?i)(S/?N|\d+\w?)", res["numero"])):
        compl = [x for x in (res.get("numero"), res.get("complemento")) if x]
        res["logradouro"], res["numero"] = m.group(1), m.group(2).upper()
        res["complemento"] = ", ".join(compl)
    return res


def _municipio(texto: str, avisos: list[str], contexto: str) -> tuple[str, str]:
    """"Porto Alegre - RS" -> ("4314902", "Porto Alegre/RS")."""
    nome, uf = split_municipio_uf(texto)
    if not nome:
        return "", ""
    exibicao = f"{nome}/{uf}" if uf else nome
    cod = ibge.codigo(nome, uf) or ""
    if not cod:
        avisos.append(f"Não encontrei o código IBGE de \"{exibicao}\" ({contexto}). Informe manualmente.")
    return cod, exibicao


def _de_campos(campos: dict[str, str], texto: str) -> dict:
    """Converte os campos lidos do PDF em kwargs de Template."""
    g = lambda k: empty_if_dash(campos.get(k, ""))  # noqa: E731
    avisos: list[str] = []

    chave = digits(g("ident.chave"))
    if len(chave) != 50:
        m = re.search(r"(?<!\d)\d{50}(?!\d)", texto.replace(" ", ""))
        chave = m.group(0) if m else ""

    # --- prestador ---------------------------------------------------------------
    doc = digits(g("prest.doc"))
    if not doc and chave:
        doc = chave[9:23] if chave[8] == "2" else chave[12:23]
    simples = g("prest.simples")
    op = _op_simp_nac(simples)
    if not op:
        op = "1"
        avisos.append("Não identifiquei a situação no Simples Nacional; confira o regime do prestador.")
    end_prest = _endereco(g("prest.endereco_lista") or g("prest.endereco"))
    mun_prest_txt = g("prest.municipio") or g("prest.municipio_uf") or end_prest.get("municipio", "")
    cod_prest = chave[:7] if chave else ""
    ibge_cep = g("prest.ibge_cep")
    if not cod_prest and ibge_cep:
        cod_prest = digits(ibge_cep.split("/")[0])[:7]
    if not cod_prest:
        cod_prest, _ = _municipio(mun_prest_txt, avisos, "prestador")
    nome_mun, uf_mun = split_municipio_uf(mun_prest_txt)
    prestador = Prestador(
        tipo_doc="CPF" if len(doc) == 11 else "CNPJ",
        documento=doc,
        nome=re.sub(r"^[\d.]+\s+", "", g("prest.nome")) if op == "2" else g("prest.nome"),
        im=g("prest.im"),
        fone=digits(g("prest.fone").split("(tel:")[0]),
        email=g("prest.email"),
        cod_municipio=cod_prest,
        municipio=f"{nome_mun}/{uf_mun}" if uf_mun else nome_mun,
        op_simp_nac=op,
        reg_ap_trib_sn=_reg_ap_trib_sn(g("prest.regime_sn")) if op == "3" else "",
        reg_esp_trib=_reg_esp_trib(g("trib.reg_esp") or g("prest.reg_esp")),
    )
    if op == "3" and not prestador.reg_ap_trib_sn:
        prestador.reg_ap_trib_sn = "1"
        avisos.append("ME/EPP: assumi apuração do ISSQN pelo Simples Nacional (regApTribSN = 1). Confira.")

    # --- tomador -------------------------------------------------------------------
    tomador = None
    doc_txt = g("toma.doc")
    doc_t = digits(doc_txt)
    end = _endereco(g("toma.endereco_lista") or g("toma.endereco"))
    mun_txt = g("toma.municipio") or g("toma.municipio_uf") or end.get("municipio", "")
    if len(doc_t) in (11, 14) and not re.search(r"[A-Za-z]", doc_txt):
        ibge_cep_t = g("toma.ibge_cep")
        cep = digits(g("toma.cep")) or end.get("cep", "")
        cod_mun_t = ""
        if ibge_cep_t:
            partes = [digits(p) for p in ibge_cep_t.split("/")]
            cod_mun_t = next((p for p in partes if len(p) == 7), "")
            cep = cep or next((p for p in partes if len(p) == 8), "")
        if end and not cod_mun_t and mun_txt:
            cod_mun_t, mun_exib = _municipio(mun_txt, avisos, "endereço do tomador")
        else:
            n, u = split_municipio_uf(mun_txt)
            mun_exib = f"{n}/{u}" if u else n
        endereco = Endereco(
            cep=cep, cod_municipio=cod_mun_t, municipio=mun_exib,
            logradouro=end.get("logradouro", ""), numero=end.get("numero", ""),
            complemento=end.get("complemento", ""), bairro=end.get("bairro", ""),
        )
        if endereco.preenchido() and not endereco.completo():
            avisos.append("Endereço do tomador incompleto ou ambíguo no PDF; revise antes de emitir.")
        tomador = Tomador(
            tipo_doc="CPF" if len(doc_t) == 11 else "CNPJ",
            documento=doc_t,
            nome=g("toma.nome"),
            im=g("toma.im"),
            fone=digits(g("toma.fone")),
            email=g("toma.email"),
            endereco=endereco,
        )
    elif doc_txt or g("toma.nome"):
        # Tomador do exterior: o DANFSe não detalha o endereço estrangeiro de forma estruturada.
        textos = [mun_txt, g("toma.endereco_lista"), g("toma.endereco"), g("trib.pais_result")]
        pais = next((c for t in textos for parte in re.split(r"[,/\n-]", t or "")
                     if (c := dominios.pais_por_nome(parte)) and c != "BR"), "")
        # O DANFSe imprime o código do motivo (cNaoNIF) no lugar do NIF quando ele não existe.
        sem_nif = not doc_txt or doc_txt in ("0", "1", "2")
        tomador = Tomador(
            tipo_doc="NIF",
            documento="" if sem_nif else doc_txt,
            c_nao_nif=(doc_txt if doc_txt in ("1", "2") else "1") if sem_nif else "",
            nome=g("toma.nome"),
            fone=digits(g("toma.fone")),
            email=g("toma.email"),
            endereco=Endereco(
                pais=pais,
                cod_postal=re.sub(r"\s*\(ext\)\s*$", "", g("toma.cep") or g("toma.ibge_cep"), flags=re.I),
                cidade=split_municipio_uf(mun_txt)[0],
                logradouro=end.get("logradouro", ""), numero=end.get("numero", ""),
                complemento=end.get("complemento", ""), bairro=end.get("bairro", ""),
            ),
        )
        avisos.append("Tomador do exterior: confira NIF, país e endereço (código postal, cidade, estado/província).")

    # --- serviço -------------------------------------------------------------------
    ctrib_txt = g("serv.ctribnac") or g("serv.ctrib_nac_mun")
    m = re.match(r"\s*(\d{2})\.?(\d{2})\.?(\d{2})\s*(?:[-/]\s*)?(.*)", ctrib_txt, re.S)
    c_trib_nac = "".join(m.groups()[:3]) if m else ""
    c_trib_desc = re.sub(r"\s+", " ", m.group(4)).strip(" -") if m else ""
    if g("serv.ctrib_nac_mun") or re.fullmatch(r"\d{3}", c_trib_desc):
        # DANFSe v2: "01.07.01 / 001" e a descrição numa linha própria, sem rótulo
        c_trib_desc = re.sub(r"\s+", " ", g("serv.titulo"))
    if not c_trib_nac:
        avisos.append("Não encontrei o código de tributação nacional; informe manualmente.")
    c_trib_mun = digits(g("serv.ctribmun"))
    if not c_trib_mun and "/" in g("serv.ctrib_nac_mun"):
        c_trib_mun = digits(g("serv.ctrib_nac_mun").split("/", 1)[1])[:3]
    nbs = digits(g("serv.nbs"))[:9]
    if len(nbs) != 9:
        m_nbs = re.search(r"NBS:?\s*(\d{9})", g("info.titulo") + " " + g("info.info"))
        nbs = m_nbs.group(1) if m_nbs else ""
    local_txt = g("serv.local") or g("serv.local_uf_pais")
    if local_txt and norm(split_municipio_uf(local_txt)[0]) == norm(nome_mun) and cod_prest:
        cod_local, local_exib = cod_prest, prestador.municipio
    else:
        cod_local, local_exib = _municipio(local_txt, avisos, "local da prestação")
    descricao = g("serv.descricao")
    servico = Servico(
        c_trib_nac=c_trib_nac,
        c_trib_nac_desc=c_trib_desc,
        c_trib_mun=c_trib_mun if len(c_trib_mun) == 3 else "",
        c_nbs=nbs,
        descricao=descricao,
        cod_municipio_prestacao=cod_local,
        municipio_prestacao=local_exib,
    )

    # --- tributação ----------------------------------------------------------------
    aliq = parse_percent(g("trib.aliquota"))
    tributacao = Tributacao(
        trib_issqn=_trib_issqn(g("trib.trib_issqn")),
        pais_resultado=dominios.pais_por_nome(g("trib.pais_result")),
        tp_ret_issqn=_tp_ret_issqn(g("trib.retencao")),
        # Só ME/EPP (apurando ISSQN pelo SN) costuma precisar informar a alíquota.
        p_aliq=f"{aliq:.2f}" if aliq and op == "3" and prestador.reg_ap_trib_sn == "1" else "",
    )
    if tributacao.trib_issqn == "3":
        if tomador and tomador.tipo_doc == "NIF" and not tributacao.pais_resultado:
            tributacao.pais_resultado = tomador.endereco.pais
        avisos.append("Exportação de serviço: confira os dados de comércio exterior (moeda, modo de prestação etc.); "
                      "eles não aparecem no PDF.")
    elif tributacao.trib_issqn != "1":
        avisos.append("A nota original não é 'operação tributável'; revise a tributação do ISSQN.")

    valor = parse_money(g("trib.valor_serv") or g("total.valor_serv") or g("total.valor_operacao"))
    return dict(
        prestador=prestador,
        tomador=tomador,
        servico=servico,
        tributacao=tributacao,
        origem=Origem(
            tipo="pdf",
            chave_acesso=chave,
            numero_nfse=digits(g("ident.numero_nfse")),
            competencia=g("ident.competencia"),
            valor=fmt_money(valor) if valor else "",
            aliquota_original=f"{aliq:.2f}" if aliq else "",
        ),
        ultimo_valor=str(valor) if valor else "",
        avisos=avisos,
    )


# --------------------------------------------------------------------------------------

def _nome_padrao(kwargs: dict) -> str:
    tomador = kwargs.get("tomador")
    serv: Servico = kwargs["servico"]
    quem = tomador.nome.title() if tomador and tomador.nome else "Sem tomador"
    oque = serv.c_trib_nac_desc or serv.descricao
    oque = re.sub(r"\s+", " ", oque)
    if len(oque) > 40:
        oque = oque[:40].rsplit(" ", 1)[0] + "…"
    return f"{quem} · {oque}" if oque else quem


def _completar_nomes_municipios(kwargs: dict) -> None:
    p: Prestador = kwargs["prestador"]
    s: Servico = kwargs["servico"]
    if p.cod_municipio and not p.municipio:
        p.municipio = ibge.nome(p.cod_municipio)
    if s.cod_municipio_prestacao and not s.municipio_prestacao:
        s.municipio_prestacao = ibge.nome(s.cod_municipio_prestacao)
    t: Tomador | None = kwargs.get("tomador")
    if t and t.endereco.cod_municipio and not t.endereco.municipio:
        t.endereco.municipio = ibge.nome(t.endereco.cod_municipio)


def criar_template(kwargs: dict, arquivo: str) -> Template:
    _completar_nomes_municipios(kwargs)
    kwargs["origem"].arquivo = arquivo
    t = Template(id=storage.new_id(), nome=_nome_padrao(kwargs), **kwargs)
    storage.save_template(t)
    return t


def de_arquivo(data: bytes, nome_arquivo: str, baixar_xml=None) -> Template:
    """Cria (e salva) um template a partir de um XML ou PDF de NFS-e.

    `baixar_xml(chave) -> bytes` é usado, se informado, para trocar a leitura do PDF pelo
    XML oficial (mais fiel) quando há certificado configurado.
    """
    nome = nome_arquivo.lower()
    if nome.endswith(".xml") or data.lstrip()[:1] == b"<":
        try:
            return criar_template(nfse_xml.parse(data), nome_arquivo)
        except nfse_xml.XMLImportError as exc:
            raise ImportacaoError(str(exc)) from exc
    if not (nome.endswith(".pdf") or data[:5] == b"%PDF-"):
        raise ImportacaoError("Envie o PDF (DANFSe) ou o XML da NFS-e.")

    try:
        campos, texto = danfse_pdf.extrair(data)
    except Exception as exc:  # pdfplumber pode lançar vários tipos
        raise ImportacaoError(f"Não consegui ler o PDF: {exc}") from exc
    kwargs = _de_campos(campos, texto)
    chave = kwargs["origem"].chave_acesso
    if not chave and not kwargs["servico"].c_trib_nac:
        raise ImportacaoError(
            "Não reconheci este PDF como uma NFS-e do padrão nacional (sem chave de acesso). "
            "Se tiver o XML da nota, envie-o."
        )

    if chave and baixar_xml:
        try:
            xml_kwargs = nfse_xml.parse(baixar_xml(chave))
            xml_kwargs["origem"].tipo = "chave"
            xml_kwargs["avisos"].insert(0, "Dados obtidos do XML oficial da nota (via chave de acesso do PDF).")
            return criar_template(xml_kwargs, nome_arquivo)
        except Exception as exc:  # cai para a leitura do PDF
            kwargs["avisos"].insert(0, f"Não consegui baixar o XML oficial pela chave ({exc}); usei a leitura do PDF.")
    return criar_template(kwargs, nome_arquivo)


def de_chave(chave: str, baixar_xml) -> Template:
    chave = digits(chave)
    if len(chave) != 50:
        raise ImportacaoError("A chave de acesso deve ter 50 dígitos.")
    try:
        kwargs = nfse_xml.parse(baixar_xml(chave))
    except nfse_xml.XMLImportError as exc:
        raise ImportacaoError(str(exc)) from exc
    kwargs["origem"].tipo = "chave"
    return criar_template(kwargs, f"chave {chave}")
