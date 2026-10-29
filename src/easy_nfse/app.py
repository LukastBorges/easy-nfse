"""Aplicação web (FastAPI + Jinja + htmx)."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import ValidationError

from . import atualizacao, danfse, dominios, dps, ibge, importers, ptax, storage
from .certificado import Certificado, CertificadoError
from .models import CertificadoSalvo, Config, Emissao, Template
from .sefin import CONSULTA_PUBLICA, SefinClient, SefinError
from .util import digits, fmt_doc, fmt_money, parse_money, split_municipio_uf, strip_accents

BASE = Path(__file__).parent
@asynccontextmanager
async def _ciclo_de_vida(_app):
    atualizacao.iniciar_em_segundo_plano()
    yield


app = FastAPI(title="easy-nfse", docs_url=None, redoc_url=None, lifespan=_ciclo_de_vida)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
views = Jinja2Templates(directory=BASE / "templates")
views.env.filters["money"] = fmt_money
views.env.filters["doc"] = fmt_doc
views.env.filters["data"] = lambda d: d.strftime("%d/%m/%Y") if d else ""
views.env.filters["datahora"] = lambda d: d.strftime("%d/%m/%Y %H:%M") if d else ""
views.env.globals["consulta_publica"] = lambda chave: CONSULTA_PUBLICA.format(chave=chave)


@lru_cache
def _svg_icone(nome: str) -> str:
    return (BASE / "static" / "vendor" / "tabler-icons" / f"{nome}.svg").read_text(encoding="utf-8").strip()


def icone(nome: str, cls: str = "size-4 shrink-0") -> Markup:
    """Ícone Tabler embutido no HTML (herda a cor do texto). Novos: rode scripts/icones_tabler.py."""
    return Markup(_svg_icone(nome).replace("<svg ", f'<svg class="{cls}" aria-hidden="true" ', 1))


views.env.globals["icone"] = icone

OP_SIMP_NAC = {"1": "Não optante", "2": "MEI", "3": "ME/EPP (Simples Nacional)"}
REG_AP_TRIB_SN = {
    "1": "Tributos federais e municipal pelo SN",
    "2": "Federais pelo SN, ISSQN fora do SN",
    "3": "Federais e municipal fora do SN",
}
REG_ESP_TRIB = {
    "0": "Nenhum", "1": "Ato Cooperado", "2": "Estimativa", "3": "Microempresa Municipal",
    "4": "Notário ou Registrador", "5": "Profissional Autônomo", "6": "Sociedade de Profissionais", "9": "Outros",
}
TRIB_ISSQN = {"1": "Operação tributável", "2": "Imunidade", "3": "Exportação de serviço", "4": "Não incidência"}
TP_RET_ISSQN = {"1": "Não retido", "2": "Retido pelo tomador", "3": "Retido pelo intermediário"}
TP_IMUNIDADE = {
    "0": "Imunidade (tipo não informado)", "1": "Patrimônio, renda ou serviços (art. 150, VI, a)",
    "2": "Templos de qualquer culto (art. 150, VI, b)",
    "3": "Partidos, sindicatos, educação e assistência social (art. 150, VI, c)",
    "4": "Livros, jornais e periódicos (art. 150, VI, d)", "5": "Fonogramas e videofonogramas (art. 150, VI, e)",
}
views.env.globals.update(
    PAISES=dominios.paises(),
    PAISES_EXT={k: v for k, v in dominios.paises().items() if k != "BR"},
    MOEDAS={k: f"{iso} · {nome}" for k, (iso, nome) in dominios.MOEDAS.items()},
    MOEDA_ISO={k: iso for k, (iso, _) in dominios.MOEDAS.items()},
    MD_PRESTACAO=dominios.opcoes("TSModoPrestacao"),
    VINC_PREST=dominios.opcoes("TSVincPrest"),
    MEC_COMEX_P=dominios.opcoes("TSMecAFComExPrest"),
    MEC_COMEX_T=dominios.opcoes("TSMecAFComExToma"),
    MOV_TEMP_BENS=dominios.opcoes("TSMovTempBens"),
    MDIC=dominios.opcoes("TSEnvMDIC", sem_desconhecido=False),
    C_NAO_NIF={k: v for k, v in dominios.opcoes("TSCodNaoNIF").items() if k != "0"},
    OP_SIMP_NAC=OP_SIMP_NAC, REG_AP_TRIB_SN=REG_AP_TRIB_SN, REG_ESP_TRIB=REG_ESP_TRIB,
    TRIB_ISSQN=TRIB_ISSQN, TP_RET_ISSQN=TP_RET_ISSQN, TP_IMUNIDADE=TP_IMUNIDADE,
)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def _abrir_certificado(s: CertificadoSalvo) -> Certificado:
    data = storage.load_certificate(s.id)
    if not data:
        raise CertificadoError(f"O arquivo {s.arquivo or 'do certificado'} não está mais na pasta de dados. "
                               "Remova-o e envie de novo.")
    return Certificado.load(data, storage.cert_password(s))


DIAS_AVISO_VALIDADE = 30  # avisa que o certificado vai vencer com esta antecedência


def _guardar_dados(s: CertificadoSalvo, c: Certificado) -> None:
    s.titular, s.documento, s.validade, s.impressao = c.titular, c.documento, c.validade, c.impressao


def info_certificados(cfg: Config) -> list[dict]:
    """Certificados salvos, com os dados guardados no config.json (sem decifrar os .pfx).

    Certificado salvo antes de existirem esses dados (ou migrado da versão de um certificado só) é aberto uma vez
    e os dados ficam guardados; se não abrir, vem com `ok` falso e o motivo em `erro`.
    """
    infos, mudou = [], False
    for s in cfg.certificados:
        base = {"id": s.id, "arquivo": s.arquivo, "documento": s.documento, "vencido": False}
        try:
            if not s.validade:
                _guardar_dados(s, _abrir_certificado(s))
                mudou = True
            elif not storage.load_certificate(s.id):
                raise CertificadoError(f"O arquivo {s.arquivo or 'do certificado'} não está mais na pasta de dados. "
                                       "Remova-o e envie de novo.")
        except CertificadoError as exc:
            infos.append({**base, "ok": False, "erro": str(exc)})
            continue
        dias = (s.validade - datetime.now(timezone.utc)).days
        infos.append({**base, "ok": True, "titular": s.titular, "documento": s.documento, "validade": s.validade,
                      "vencido": dias < 0, "dias": dias, "vence_em_breve": 0 <= dias <= DIAS_AVISO_VALIDADE})
    if mudou:
        storage.save_config(cfg)
    return infos


def abrir_certificado(cfg: Config, cert_id: str) -> Certificado:
    """Abre o .pfx para assinar ou conectar à Sefin."""
    salvo = next((c for c in cfg.certificados if c.id == cert_id), None)
    if not salvo:
        raise CertificadoError("Certificado não encontrado.")
    return _abrir_certificado(salvo)


def certificado_do_template(certs: list[dict], t: Template) -> dict | None:
    """O certificado escolhido no template ou, no automático, o mais novo do CNPJ/CPF do prestador."""
    if t.certificado_id:
        escolhido = next((c for c in certs if c["id"] == t.certificado_id), None)
        if escolhido:
            return escolhido
    doc = digits(t.prestador.documento)
    candidatos = [c for c in certs if c["ok"] and doc and c["documento"] == doc]
    return max(candidatos, key=lambda c: (not c["vencido"], c["validade"]), default=None)


def problema_certificado(certs: list[dict], t: Template, cert: dict | None) -> str:
    """Por que o template não pode emitir com esse certificado ("" se pode)."""
    if not certs:
        return "Nenhum certificado digital configurado."
    if not cert:
        return (f"Nenhum certificado de {fmt_doc(t.prestador.documento) or 'prestador'} (prestador do template). "
                "Adicione o certificado A1 dele em Configurações.")
    if not cert["ok"]:
        return cert["erro"]
    if cert["vencido"]:
        return f"O certificado de {cert['titular']} está vencido."
    if cert["documento"] and digits(t.prestador.documento) != cert["documento"]:
        return (f"O certificado é de {fmt_doc(cert['documento'])}, mas o prestador do template é "
                f"{fmt_doc(t.prestador.documento)}. A Sefin exige o certificado do emitente (E0718).")
    return ""


def render(request: Request, nome: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    cfg = ctx.pop("cfg", None) or storage.load_config()
    return views.TemplateResponse(request, nome, {"cfg": cfg, "atualizacao": atualizacao.status(), **ctx},
                                  status_code=status_code)


_emitindo = 0  # emissões em andamento: a atualização não pode reiniciar o app no meio de uma
_emitindo_trava = threading.Lock()


@contextmanager
def _emissao_em_andamento():
    global _emitindo
    with _emitindo_trava:
        _emitindo += 1
    try:
        yield
    finally:
        with _emitindo_trava:
            _emitindo -= 1


def hx_redirect(url: str) -> Response:
    return Response(status_code=204, headers={"HX-Redirect": url})


def baixar_xml(cfg: Config):
    """Função que baixa o XML de uma NFS-e pela chave (produção; se falhar, produção restrita).

    Tenta cada certificado, primeiro os do emitente (o CNPJ/CPF dele faz parte da chave).
    """
    certs = [c for c in info_certificados(cfg) if c["ok"]]
    if not certs:
        return None

    def baixar(chave: str) -> bytes:
        ultimo: Exception | None = None
        for c in sorted(certs, key=lambda c: not (c["documento"] and c["documento"] in chave)):
            for amb in ("1", "2"):
                try:
                    with SefinClient(abrir_certificado(cfg, c["id"]), amb, cfg.verificar_tls, timeout=30) as cli:
                        return cli.consultar_nfse(chave)
                except (SefinError, CertificadoError, httpx.HTTPError) as exc:
                    ultimo = exc
        raise ultimo or RuntimeError("falha ao consultar")

    return baixar


def proximo_numero(cfg: Config, t: Template) -> int:
    return cfg.numeracao.get(Config.chave_numeracao(cfg.ambiente, digits(t.prestador.documento), cfg.serie), 0) + 1


def get_template_or_404(template_id: str) -> Template:
    try:
        return storage.get_template(template_id)
    except KeyError:
        raise HTTPException(404, "Template não encontrado")


def _unflatten(form) -> dict:
    out: dict = {}
    for chave, valor in form.multi_items():
        if not isinstance(valor, str):
            continue
        alvo = out
        partes = chave.split(".")
        for p in partes[:-1]:
            alvo = alvo.setdefault(p, {})
        alvo[partes[-1]] = valor.strip()
    return out


def _resolver_municipio(cod: str, texto: str) -> tuple[str, str]:
    """Se o código IBGE estiver vazio, tenta resolver pelo texto "Cidade/UF"."""
    cod = digits(cod)
    if len(cod) == 7:
        return cod, texto or ibge.nome(cod)
    nome, uf = split_municipio_uf(texto)
    return (ibge.codigo(nome, uf) or "", texto) if nome else ("", texto)


# --------------------------------------------------------------------------------------
# páginas
# --------------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Home: boas-vindas (sem templates) ou atalhos de emissão + últimas emissões."""
    cfg = storage.load_config()
    emissoes = storage.list_emissoes()
    ultimas: dict[str, Emissao] = {}
    for e in emissoes:  # mais recentes primeiro
        ultimas.setdefault(e.template_id, e)
    templates = storage.list_templates()
    # templates usados recentemente primeiro
    templates.sort(key=lambda t: ultimas[t.id].emitida_em if t.id in ultimas else t.atualizado_em, reverse=True)
    certs = info_certificados(cfg)
    cert_templates = {}  # id do template → (certificado, problema que impede emitir)
    for t in templates:
        c = certificado_do_template(certs, t)
        cert_templates[t.id] = (c, problema_certificado(certs, t, c))
    return render(request, "index.html", cfg=cfg, templates=templates, ultimas=ultimas, emissoes=emissoes[:5],
                  certs=certs, cert_templates=cert_templates)


@app.get("/templates", response_class=HTMLResponse)
def lista_templates(request: Request):
    """Importação de notas e gestão dos templates."""
    cfg = storage.load_config()
    return render(request, "templates.html", cfg=cfg, templates=storage.list_templates(), certs=info_certificados(cfg))


@app.post("/importar")
async def importar(request: Request, arquivo: UploadFile):
    cfg = storage.load_config()
    data = await arquivo.read()
    if not data:
        return render(request, "partials/erro.html", mensagens=["Selecione um arquivo PDF ou XML."])
    if len(data) > 15 * 1024 * 1024:
        return render(request, "partials/erro.html", mensagens=["Arquivo grande demais (máx. 15 MB)."])
    try:
        t = importers.de_arquivo(data, arquivo.filename or "nota", baixar_xml=baixar_xml(cfg))
    except importers.ImportacaoError as exc:
        return render(request, "partials/erro.html", mensagens=[str(exc)])
    return hx_redirect(f"/templates/{t.id}/editar?importado=1")


@app.post("/importar/chave")
def importar_chave(request: Request, chave: str = Form(...)):
    cfg = storage.load_config()
    try:
        baixar = baixar_xml(cfg)
        if not baixar:
            raise importers.ImportacaoError("Configure o certificado digital para importar pela chave.")
        t = importers.de_chave(chave, baixar)
    except (importers.ImportacaoError, SefinError, CertificadoError, httpx.HTTPError) as exc:
        return render(request, "partials/erro.html", mensagens=[f"Não foi possível importar: {exc}"])
    return hx_redirect(f"/templates/{t.id}/editar?importado=1")


def _form_template(request: Request, t: Template, status_code: int = 200, **ctx) -> HTMLResponse:
    cfg = storage.load_config()
    certs = info_certificados(cfg)
    automatico = certificado_do_template(certs, t.model_copy(update={"certificado_id": ""}))
    return render(request, "template_form.html", status_code, cfg=cfg, t=t, certs=certs, cert_automatico=automatico,
                  **ctx)


@app.get("/templates/{template_id}/editar", response_class=HTMLResponse)
def editar(request: Request, template_id: str, importado: int = 0):
    t = get_template_or_404(template_id)
    return _form_template(request, t, importado=bool(importado), erros=dps.validar_template(t))


@app.post("/templates/{template_id}")
async def salvar(request: Request, template_id: str):
    atual = get_template_or_404(template_id)
    dados = _unflatten(await request.form())
    tem_tomador = dados.pop("tem_tomador", "") == "1"
    base = atual.model_dump()
    certificado_id = dados.get("certificado_id", atual.certificado_id)
    if certificado_id not in {c.id for c in storage.load_config().certificados}:
        certificado_id = ""
    base.update(nome=dados.get("nome") or atual.nome, ultimo_valor=atual.ultimo_valor, certificado_id=certificado_id)
    for secao in ("prestador", "servico", "tributacao", "com_ext"):
        base[secao].update(dados.get(secao, {}))
    if dados.get("servico", {}).get("local_tipo") == "brasil":
        base["servico"]["pais_prestacao"] = ""
    base["servico"].pop("local_tipo", None)
    if tem_tomador:
        tom = dados.get("tomador", {})
        end = tom.pop("endereco", {})
        base["tomador"] = {**(base.get("tomador") or {}), **tom}
        base["tomador"]["endereco"] = {**((base.get("tomador") or {}).get("endereco") or {}), **end}
    else:
        base["tomador"] = None
    try:
        t = Template.model_validate(base)
    except ValidationError as exc:
        erros = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        return _form_template(request, atual, 422, erros=erros)

    p, s = t.prestador, t.servico
    p.cod_municipio, p.municipio = _resolver_municipio(p.cod_municipio, p.municipio)
    s.cod_municipio_prestacao, s.municipio_prestacao = _resolver_municipio(s.cod_municipio_prestacao, s.municipio_prestacao)
    if t.tomador:
        e = t.tomador.endereco
        if t.tomador.tipo_doc == "NIF":
            if e.pais == "BR":
                e.pais = ""
            e.cep = e.cod_municipio = e.municipio = ""
        else:
            e.pais = e.cod_postal = e.cidade = e.estado_prov = ""
            t.tomador.c_nao_nif = ""
            if e.preenchido() or e.municipio:
                e.cod_municipio, e.municipio = _resolver_municipio(e.cod_municipio, e.municipio)
    if s.pais_prestacao:
        s.cod_municipio_prestacao = s.municipio_prestacao = ""
    if t.tributacao.trib_issqn == "3":  # exportação: sem retenção nem alíquota (campos ficam ocultos)
        t.tributacao.tp_ret_issqn, t.tributacao.p_aliq = "1", ""
    else:
        t.tributacao.pais_resultado = ""
    if t.tributacao.trib_issqn == "3" and not t.tributacao.pais_resultado and t.tomador_exterior:
        t.tributacao.pais_resultado = t.tomador.endereco.pais
    for campo in ("documento", "fone"):
        setattr(p, campo, digits(getattr(p, campo)))
    s.c_trib_nac, s.c_trib_mun, s.c_nbs = digits(s.c_trib_nac), digits(s.c_trib_mun), digits(s.c_nbs)
    if t.tomador:
        to = t.tomador
        if to.tipo_doc != "NIF":
            to.documento = digits(to.documento)
        to.fone = digits(to.fone)
        to.endereco.cep = digits(to.endereco.cep)
        if not to.documento and not (to.tipo_doc == "NIF" and to.c_nao_nif):
            t.tomador = None
    t.atualizado_em = datetime.now()
    t.avisos = []
    storage.save_template(t)

    erros = dps.validar_template(t)
    if erros:
        return _form_template(request, t, erros=erros, salvo=True)
    return RedirectResponse(f"/templates/{t.id}", status_code=303)


@app.post("/templates/{template_id}/excluir")
def excluir(request: Request, template_id: str):
    storage.delete_template(template_id)
    if request.headers.get("HX-Request"):  # exclusão pela lista: remove só a linha
        return Response("", headers={"HX-Refresh": "true"} if not storage.list_templates() else {})
    return RedirectResponse("/templates", status_code=303)


@app.post("/templates/{template_id}/duplicar")
def duplicar(template_id: str):
    t = get_template_or_404(template_id)
    novo = t.model_copy(update={"id": storage.new_id(), "nome": f"{t.nome} (cópia)",
                                "criado_em": datetime.now(), "atualizado_em": datetime.now()}, deep=True)
    storage.save_template(novo)
    return RedirectResponse(f"/templates/{novo.id}/editar", status_code=303)


# --------------------------------------------------------------------------------------
# emissão
# --------------------------------------------------------------------------------------

@app.get("/templates/{template_id}", response_class=HTMLResponse)
def pagina_emissao(request: Request, template_id: str):
    cfg = storage.load_config()
    t = get_template_or_404(template_id)
    certs = info_certificados(cfg)
    cert = certificado_do_template(certs, t)
    return render(request, "emitir.html", cfg=cfg, t=t, n_dps=proximo_numero(cfg, t), hoje=date.today(),
                  erros=dps.validar_template(t), cert=cert, problema_cert=problema_certificado(certs, t, cert),
                  emissoes=[e for e in storage.list_emissoes() if e.template_id == t.id][:5])


def _dados_emissao(cfg: Config, t: Template, competencia: str, valor: str, descricao: str,
                   n_dps: int | None = None, valor_moeda: str = "") -> dps.DadosEmissao:
    erros = []
    try:
        comp = date.fromisoformat(competencia)
    except ValueError:
        comp = None
        erros.append("Informe a data de competência.")
    v = parse_money(valor)
    if v is None:
        erros.append("Informe o valor do serviço.")
    if erros:
        raise dps.DPSError(erros)
    return dps.DadosEmissao(competencia=comp, valor=v, descricao=descricao, serie=cfg.serie,
                            n_dps=n_dps or proximo_numero(cfg, t), ambiente=cfg.ambiente,
                            valor_moeda=parse_money(valor_moeda) if t.exige_com_ext else None)


@app.post("/templates/{template_id}/revisar", response_class=HTMLResponse)
def revisar(request: Request, template_id: str, competencia: str = Form(""), valor: str = Form(""),
            descricao: str = Form(""), valor_moeda: str = Form("")):
    cfg = storage.load_config()
    t = get_template_or_404(template_id)
    try:
        d = _dados_emissao(cfg, t, competencia, valor, descricao, valor_moeda=valor_moeda)
        root, ident = dps.montar(t, d)
    except dps.DPSError as exc:
        return render(request, "partials/erro.html", t=t, mensagens=exc.erros)
    certs = info_certificados(cfg)
    cert = certificado_do_template(certs, t)
    alertas = [p] if (p := problema_certificado(certs, t, cert)) else []
    xml = dps.serializar(root).decode()
    return render(request, "partials/revisao.html", cfg=cfg, t=t, d=d, id_dps=ident, xml=xml, alertas=alertas,
                  cert=cert, pode_emitir=not alertas)


@app.post("/templates/{template_id}/emitir", response_class=HTMLResponse)
def emitir(request: Request, template_id: str, competencia: str = Form(""), valor: str = Form(""),
           descricao: str = Form(""), n_dps: int = Form(...), ambiente: str = Form(...),
           valor_moeda: str = Form("")):
    cfg = storage.load_config()
    t = get_template_or_404(template_id)
    if ambiente != cfg.ambiente:
        return render(request, "partials/erro.html",
                      mensagens=["O ambiente mudou desde a revisão. Revise a emissão novamente."])
    try:
        certs = info_certificados(cfg)
        info = certificado_do_template(certs, t)
        if not (info and info["ok"]):
            raise CertificadoError(problema_certificado(certs, t, info))
        cert = abrir_certificado(cfg, info["id"])
        d = _dados_emissao(cfg, t, competencia, valor, descricao, n_dps=n_dps, valor_moeda=valor_moeda)
        root, ident = dps.montar(t, d)
        assinado = cert.assinar(root, ident)
        dps.validar_xsd(assinado)
        xml = dps.serializar(assinado)
    except (dps.DPSError, CertificadoError) as exc:
        return render(request, "partials/erro.html", t=t, mensagens=getattr(exc, "erros", [str(exc)]))

    chave_num = Config.chave_numeracao(cfg.ambiente, digits(t.prestador.documento), cfg.serie)
    try:
        with _emissao_em_andamento(), SefinClient(cert, cfg.ambiente, cfg.verificar_tls) as cli:
            try:
                res = cli.emitir(xml)
            except SefinError as exc:
                if "E0014" in exc.codigos:  # DPS já usada: talvez uma emissão anterior sem resposta
                    cfg.numeracao[chave_num] = max(cfg.numeracao.get(chave_num, 0), n_dps)
                    storage.save_config(cfg)
                    existente = None
                    try:
                        existente = cli.consultar_dps(ident)
                    except (SefinError, httpx.HTTPError):
                        pass
                    return render(request, "partials/duplicada.html", t=t, n_dps=n_dps, chave=existente,
                                  mensagens=exc.mensagens)
                raise
    except SefinError as exc:
        return render(request, "partials/erro.html", t=t, titulo="A Sefin rejeitou a DPS", mensagens=exc.mensagens)
    except httpx.TimeoutException:
        return render(request, "partials/erro.html", t=t, titulo="Sem resposta da Sefin", mensagens=[
            "A requisição expirou e não sabemos se a nota foi gerada.",
            f"Tente emitir de novo: a mesma numeração (DPS nº {n_dps}) será usada, então a Sefin "
            "recusará uma duplicata (E0014) e mostraremos a nota existente.",
        ])
    except httpx.HTTPError as exc:
        dica = " Se for erro de certificado TLS do servidor, veja Configurações." if "CERTIFICATE" in str(exc).upper() else ""
        return render(request, "partials/erro.html", t=t, titulo="Falha de conexão com a Sefin",
                      mensagens=[f"{type(exc).__name__}: {exc}.{dica}"])

    cfg.numeracao[chave_num] = max(cfg.numeracao.get(chave_num, 0), n_dps)
    storage.save_config(cfg)
    numero_nfse = ""
    if res.nfse_xml:
        from lxml import etree
        found = etree.fromstring(res.nfse_xml).xpath("//*[local-name()='nNFSe']/text()")
        numero_nfse = found[0] if found else ""
    emissao = storage.save_emissao(
        Emissao(chave_acesso=res.chave_acesso, numero_nfse=numero_nfse, id_dps=ident, serie=cfg.serie,
                n_dps=n_dps, ambiente=cfg.ambiente, template_id=t.id, template_nome=t.nome,
                tomador=t.tomador.nome if t.tomador else "", valor=str(d.valor),
                valor_moeda=str(d.valor_moeda) if d.valor_moeda else "",
                moeda=dominios.MOEDAS.get(t.com_ext.tp_moeda, (t.com_ext.tp_moeda,))[0] if d.valor_moeda else "",
                competencia=d.competencia.isoformat()),
        xml, res.nfse_xml, res.resposta,
    )
    if res.nfse_xml:
        try:  # o PDF é um extra: falha aqui não pode esconder que a nota foi emitida
            (storage.DATA_DIR / emissao.pasta / "danfse.pdf").write_bytes(danfse.gerar(res.nfse_xml))
        except Exception:  # noqa: BLE001
            pass
    t.ultimo_valor = str(d.valor)
    if d.valor_moeda:
        t.ultimo_valor_moeda = str(d.valor_moeda)
    t.atualizado_em = datetime.now()
    storage.save_template(t)
    return render(request, "partials/sucesso.html", cfg=cfg, t=t, e=emissao, alertas=res.alertas)


@app.get("/cotacao")
def cotacao(moeda: str, data: str):
    """PTAX de venda (fechamento) do último dia útil até `data`, para converter o valor em R$."""
    iso = dominios.MOEDAS.get(moeda, (None,))[0]
    if not iso:
        return {"erro": "Moeda sem cotação PTAX disponível; informe o valor em R$ manualmente."}
    try:
        c = ptax.cotacao(iso, date.fromisoformat(data))
    except ValueError:
        return {"erro": "Data inválida."}
    except (httpx.HTTPError, ptax.PTAXError) as exc:
        return {"erro": f"Não consegui consultar a PTAX: {exc}"}
    return {"moeda": iso, "taxa": str(c.venda), "data": c.data.isoformat(), "data_br": c.data.strftime("%d/%m/%Y")}


# --------------------------------------------------------------------------------------
# histórico e arquivos
# --------------------------------------------------------------------------------------

@app.get("/historico", response_class=HTMLResponse)
def historico(request: Request):
    return render(request, "historico.html", emissoes=storage.list_emissoes())


@app.get("/emissoes/{chave}/{arquivo}")
def baixar_arquivo(chave: str, arquivo: str, download: int = 0):
    e = storage.find_emissao(chave)
    if not e or arquivo not in ("nfse.xml", "dps.xml", "danfse.pdf"):
        raise HTTPException(404)
    pasta = (storage.DATA_DIR / e.pasta).resolve()
    if storage.DATA_DIR not in pasta.parents:
        raise HTTPException(404)
    path = pasta / arquivo
    if arquivo == "danfse.pdf":
        xml = pasta / "nfse.xml"
        if not path.exists() and xml.exists():
            path.write_bytes(danfse.gerar(xml.read_bytes()))
        nome = f"NFS-e {e.numero_nfse or chave} - {e.tomador or e.template_nome}.pdf".replace("/", "-")
        if not path.exists():
            raise HTTPException(404, "XML da NFS-e não disponível para gerar o PDF.")
        return FileResponse(path, media_type="application/pdf", filename=nome,
                            content_disposition_type="attachment" if download else "inline")
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/xml", filename=f"{arquivo[:-4]}-{chave}.xml")


@app.post("/danfse")
async def danfse_de_xml(request: Request, arquivo: UploadFile):
    """Gera o DANFSe (PDF) de qualquer XML de NFS-e do padrão nacional."""
    data = await arquivo.read()
    try:
        pdf = danfse.gerar(data)
    except Exception:  # noqa: BLE001
        return render(request, "historico.html", emissoes=storage.list_emissoes(), status_code=422,
                      erro="Não consegui gerar o PDF: o arquivo não parece ser o XML de uma NFS-e do padrão nacional.")
    nome = (arquivo.filename or "nfse").rsplit(".", 1)[0] + ".pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# --------------------------------------------------------------------------------------
# configurações
# --------------------------------------------------------------------------------------

def _numeracao(cfg: Config, doc: str) -> dict:
    chave = Config.chave_numeracao(cfg.ambiente, doc, cfg.serie)
    ultimo = cfg.numeracao.get(chave, 0)
    return {"chave": chave, "doc": doc, "ultimo": ultimo, "proximo": ultimo + 1}


def _estado_certificado(c: dict) -> str:
    if not c["ok"]:
        return "erro"
    return "vencido" if c["vencido"] else ("vencendo" if c["vence_em_breve"] else "valido")


def _pagina_config(request: Request, cfg: Config | None = None, **ctx):
    cfg = cfg or storage.load_config()
    certs = info_certificados(cfg)
    templates = storage.list_templates()
    usos: dict[str, list[str]] = {}  # id do certificado → templates que o usam
    for t in templates:
        if c := certificado_do_template(certs, t):
            usos.setdefault(c["id"], []).append(t.nome)
    ordem = {"erro": 0, "vencido": 1, "vencendo": 2, "valido": 3}
    linhas = []  # um certificado por linha, com a numeração da DPS do CNPJ/CPF dele
    for c in certs:
        estado = _estado_certificado(c)
        linhas.append({**c, "estado": estado, "usos": usos.get(c["id"], []),
                       "numeracao": _numeracao(cfg, c["documento"]) if c["documento"] else None})
    linhas.sort(key=lambda c: (ordem[c["estado"]], strip_accents(c.get("titular") or c["arquivo"]).casefold()))
    # prestadores de templates sem certificado também têm numeração (ajustável antes de adicionar o certificado)
    docs_cert = {c["documento"] for c in certs if c["documento"]}
    sem_cert = []
    for t in templates:
        d = digits(t.prestador.documento)
        if d and d not in docs_cert and d not in {n["doc"] for n in sem_cert}:
            sem_cert.append(_numeracao(cfg, d))
    chaves = {c["numeracao"]["chave"] for c in linhas if c["numeracao"]} | {n["chave"] for n in sem_cert}
    outros = sorted((k, v) for k, v in cfg.numeracao.items() if k not in chaves)
    return render(request, "config.html", cfg=cfg, linhas=linhas, sem_cert=sem_cert, numeracao_outros=outros,
                  data_dir=storage.DATA_DIR, **ctx)


@app.get("/configuracoes", response_class=HTMLResponse)
def configuracoes(request: Request):
    return _pagina_config(request)


@app.post("/configuracoes", response_class=HTMLResponse)
def salvar_configuracoes(request: Request, ambiente: str = Form(...), serie: str = Form("1"),
                         verificar_tls: str = Form(""), verificar_atualizacoes: str = Form("")):
    cfg = storage.load_config()
    serie_d = digits(serie)
    if not serie_d or not 1 <= int(serie_d) <= 49999:
        return _pagina_config(request, cfg, erro="A série deve estar entre 1 e 49999 (faixa de aplicativo próprio).")
    if ambiente not in ("1", "2"):
        return _pagina_config(request, cfg, erro="Ambiente inválido.")
    cfg.ambiente, cfg.serie, cfg.verificar_tls = ambiente, str(int(serie_d)), verificar_tls == "1"
    cfg.verificar_atualizacoes = verificar_atualizacoes == "1"
    storage.save_config(cfg)
    return _pagina_config(request, cfg, ok="Configurações salvas.")


@app.post("/configuracoes/certificados", response_class=HTMLResponse)
async def adicionar_certificado(request: Request, arquivo: UploadFile, senha: str = Form("")):
    cfg = storage.load_config()
    data = await arquivo.read()
    try:
        c = Certificado.load(data, storage.cert_password(CertificadoSalvo(id="", senha=senha)))
    except CertificadoError as exc:
        return _pagina_config(request, cfg, erro=str(exc))
    # o mesmo certificado enviado de novo (ex.: senha trocada) substitui o anterior em vez de duplicar
    info_certificados(cfg)  # garante a impressão digital dos certificados antigos
    salvo = next((s for s in cfg.certificados if s.impressao == c.impressao), None)
    if not salvo:
        salvo = CertificadoSalvo(id=storage.new_id())
        cfg.certificados.append(salvo)
    salvo.arquivo, salvo.senha = arquivo.filename or "certificado.pfx", senha
    _guardar_dados(salvo, c)
    storage.save_certificate(salvo.id, data)
    storage.save_config(cfg)
    aviso = " Atenção: este certificado está vencido." if c.vencido else ""
    return _pagina_config(request, cfg, ok=f"Certificado de {c.titular} salvo.{aviso}")


@app.post("/configuracoes/certificados/{cert_id}/excluir", response_class=HTMLResponse)
def excluir_certificado(request: Request, cert_id: str):
    try:
        storage.delete_certificate(cert_id)
    except KeyError:
        raise HTTPException(404)
    cfg = storage.load_config()
    cfg.certificados = [c for c in cfg.certificados if c.id != cert_id]
    storage.save_config(cfg)
    for t in storage.list_templates():  # templates que o escolheram voltam ao automático
        if t.certificado_id == cert_id:
            t.certificado_id = ""
            storage.save_template(t)
    return _pagina_config(request, cfg, ok="Certificado removido.")


@app.post("/configuracoes/numeracao", response_class=HTMLResponse)
def salvar_numeracao(request: Request, chave: str = Form(...), ultimo: int = Form(...)):
    cfg = storage.load_config()
    if not re.fullmatch(r"[12]\|\d{11,14}\|\d{1,5}", chave) or ultimo < 0:
        return _pagina_config(request, cfg, erro="Numeração inválida.")
    cfg.numeracao[chave] = ultimo
    storage.save_config(cfg)
    return _pagina_config(request, cfg, ok=f"Numeração atualizada: a próxima DPS será a nº {ultimo + 1}.")


@app.post("/configuracoes/certificados/{cert_id}/testar", response_class=HTMLResponse)
def testar_conexao(request: Request, cert_id: str):
    cfg = storage.load_config()
    try:
        with SefinClient(abrir_certificado(cfg, cert_id), cfg.ambiente, cfg.verificar_tls, timeout=20) as cli:
            status = cli.testar()
    except (CertificadoError, httpx.HTTPError) as exc:
        return render(request, "partials/teste.html", ok=False, msg=f"{type(exc).__name__}: {exc}")
    if status in (200, 404):
        return render(request, "partials/teste.html", ok=True, msg=f"Conexão mTLS OK (HTTP {status}).")
    return render(request, "partials/teste.html", ok=False,
                  msg=f"A Sefin respondeu HTTP {status}. Verifique se o certificado é ICP-Brasil válido.")


# --------------------------------------------------------------------------------------
# atualização do app
# --------------------------------------------------------------------------------------

@app.post("/atualizacao/verificar", response_class=HTMLResponse)
def verificar_atualizacao(request: Request):
    try:
        atualizacao.verificar(forcar=True)
    except (httpx.HTTPError, atualizacao.AtualizacaoError, ValueError) as exc:
        return render(request, "partials/atualizacao.html", erro=f"Não consegui consultar as versões: {exc}")
    st = atualizacao.status()
    if st["nova"] and st["instalavel"] and not st["pronta"]:  # baixa em segundo plano (~50 MB)
        threading.Thread(target=atualizacao.verificar_e_baixar, kwargs={"forcar": True}, daemon=True).start()
    return render(request, "partials/atualizacao.html")


@app.post("/atualizacao/instalar", response_class=HTMLResponse)
def instalar_atualizacao(request: Request):
    if _emitindo:
        return render(request, "partials/atualizacao.html", erro="Há uma emissão em andamento. Tente de novo quando terminar.")
    try:
        atualizacao.instalar()
    except (atualizacao.AtualizacaoError, OSError, subprocess.SubprocessError) as exc:
        return render(request, "partials/atualizacao.html", erro=f"Não foi possível instalar: {exc}")
    threading.Timer(1.5, os._exit, [0]).start()  # dá tempo de a resposta chegar; o script reabre o app
    return render(request, "partials/atualizacao.html", instalando=True)


@app.post("/atualizacao/dispensar")
def dispensar_aviso_atualizacao():
    atualizacao.dispensar_aviso()
    return Response("")
