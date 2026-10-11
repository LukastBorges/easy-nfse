"""Monitora a documentação técnica oficial da NFS-e e aponta mudanças que podem exigir revisão do código.

Compara o estado atual das páginas de gov.br/nfse (links de documentos, anúncios de atualização e o
conteúdo dos esquemas XSD) com o retrato salvo em `.github/nfse-monitor/estado.json`.

    uv run python scripts/monitor_nfse.py                       # verifica e mostra o relatório
    uv run python scripts/monitor_nfse.py --relatorio r.md      # grava o relatório em Markdown
    uv run python scripts/monitor_nfse.py --atualizar           # depois de revisar: atualiza o retrato

Saídas para o GitHub Actions (em $GITHUB_OUTPUT): `mudou` (true/false) e `assinatura` (hash das mudanças).
Código de saída 2 quando alguma fonte não pôde ser lida (para não confundir falha de rede com "sem mudanças").
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import httpx
from lxml import html

RAIZ = Path(__file__).resolve().parents[1]
ESTADO = RAIZ / ".github" / "nfse-monitor" / "estado.json"
XSD_LOCAL = RAIZ / "src" / "easy_nfse" / "xsd"
BASE = "https://www.gov.br/nfse/pt-br"

# fonte -> (url, tipo, o que revisar se mudar)
FONTES = {
    "documentacao-atual": (
        f"{BASE}/biblioteca/documentacao-tecnica/documentacao-atual", "links",
        "XSD e Anexo I → `src/easy_nfse/xsd/`, regras em `dps.py`, importadores; Anexo A → `paises.json`; "
        "manuais da API → `sefin.py`.",
    ),
    "reforma-tributaria-rtc": (
        f"{BASE}/biblioteca/documentacao-tecnica/rtc", "links",
        "Leiautes IBS/CBS: o grupo IBSCBS ainda não é enviado (`dps.py`); verifique se passou a ser obrigatório.",
    ),
    "notas-tecnicas": (
        f"{BASE}/nfs-e-via/documentacao-tecnica/notas-tecnicas", "links",
        "Leia a NT nova: DANFSe → `danfse.py`; leiaute/regras → `dps.py`.",
    ),
    "atualizacoes-e-implantacoes": (
        f"{BASE}/biblioteca/documentacao-tecnica/atualizacoes-e-implantacoes", "anuncios",
        "Mudanças anunciadas em produção/produção restrita: avalie impacto em `dps.py`, `sefin.py` e validações.",
    ),
    "apis": (
        f"{BASE}/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao", "links",
        "Endereços das APIs → `sefin.py` (BASE_URL, CONSULTA_PUBLICA).",
    ),
}
REVISAO_XSD = ("Conteúdo dos esquemas mudou → atualize `src/easy_nfse/xsd/` (reaplique o patch de `^`/`$`, ver "
               "AGENTS.md), rode os testes e revise `dps.montar` e `importers/nfse_xml.py`.")


class FonteIndisponivel(Exception):
    pass


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (easy-nfse monitor)"})


def _conteudo(cli: httpx.Client, url: str):
    resp = cli.get(url)
    if resp.status_code != 200:
        raise FonteIndisponivel(f"{url}: HTTP {resp.status_code}")
    doc = html.fromstring(resp.content)
    nucleo = doc.xpath("//*[@id='content-core']")
    if not nucleo:
        raise FonteIndisponivel(f"{url}: conteúdo principal (#content-core) não encontrado")
    return nucleo[0]


def _links(nucleo) -> list[str]:
    itens = set()
    for a in nucleo.xpath(".//a[@href]"):
        href = a.get("href").strip().split("?")[0].removesuffix("/view").removesuffix("/@@download/file")
        if href.startswith(("http", "/")) and not href.startswith("mailto:"):
            texto = re.sub(r"\s+", " ", a.text_content()).strip()
            itens.add(f"{texto} — {href}" if texto and texto not in href else href)
    return sorted(itens)


def _anuncios(nucleo) -> list[str]:
    """Quebra a página de atualizações em itens "dd/mm/aaaa texto"."""
    texto = re.sub(r"\s+", " ", nucleo.text_content()).strip()
    partes = re.split(r"(?=\b\d{2}/\d{2}/\d{4}\b)", texto)
    return sorted({p.strip() for p in partes if re.match(r"\d{2}/\d{2}/\d{4}", p.strip())})


def _normalizar_xsd(conteudo: bytes) -> bytes:
    # mesmo patch aplicado à cópia local (patterns com ^ e $ literais no esquema oficial)
    return re.sub(rb'pattern value="\^([^"]*)\$"', rb'pattern value="\1"', conteudo)


def _hash_xsd_oficial(cli: httpx.Client, links_atual: list[str]) -> dict[str, str]:
    urls = [l.rsplit(" — ", 1)[-1] for l in links_atual if re.search(r"esquemas_xsd.*\.zip$", l, re.I)]
    if not urls:
        raise FonteIndisponivel("link do pacote de esquemas XSD não encontrado na documentação atual")
    url = urls[0] if urls[0].startswith("http") else f"https://www.gov.br{urls[0]}"
    resp = cli.get(url)
    if resp.status_code != 200:
        url_alt = url + "/@@download/file"
        resp = cli.get(url_alt)
    if resp.status_code != 200:
        raise FonteIndisponivel(f"{url}: HTTP {resp.status_code}")
    hashes = {}
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        for nome in z.namelist():
            if nome.endswith(".xsd") and "/1.01/" in nome:
                hashes[Path(nome).name] = hashlib.sha256(_normalizar_xsd(z.read(nome))).hexdigest()
    if not hashes:
        raise FonteIndisponivel("pacote XSD sem a pasta 1.01")
    return dict(sorted(hashes.items()))


def _hash_xsd_local() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(XSD_LOCAL.glob("*.xsd"))}


def coletar() -> tuple[dict, list[str]]:
    estado: dict = {}
    falhas: list[str] = []
    with _cliente() as cli:
        for nome, (url, tipo, _) in FONTES.items():
            try:
                nucleo = _conteudo(cli, url)
                estado[nome] = _links(nucleo) if tipo == "links" else _anuncios(nucleo)
            except (httpx.HTTPError, FonteIndisponivel) as exc:
                falhas.append(f"{nome}: {exc}")
        if "documentacao-atual" in estado:
            try:
                estado["xsd-v1.01"] = _hash_xsd_oficial(cli, estado["documentacao-atual"])
            except (httpx.HTTPError, FonteIndisponivel, zipfile.BadZipFile) as exc:
                falhas.append(f"xsd-v1.01: {exc}")
    return estado, falhas


def comparar(antigo: dict, novo: dict) -> list[dict]:
    mudancas = []
    for nome, valor in novo.items():
        anterior = antigo.get(nome)
        if anterior == valor:
            continue
        if isinstance(valor, dict):  # hashes dos XSDs
            anterior = anterior or {}
            alterados = sorted(k for k in valor.keys() | anterior.keys() if valor.get(k) != anterior.get(k))
            mudancas.append({"fonte": nome, "novos": [], "removidos": [], "alterados": alterados})
        else:
            anterior = anterior or []
            mudancas.append({
                "fonte": nome,
                "novos": [x for x in valor if x not in anterior],
                "removidos": [x for x in anterior if x not in valor],
                "alterados": [],
            })
    return mudancas


def relatorio(mudancas: list[dict], assinatura: str) -> str:
    linhas = [
        "A documentação técnica oficial da NFS-e mudou desde o último retrato salvo. "
        "Revise se o easy-nfse precisa de ajustes.",
        "",
    ]
    for m in mudancas:
        fonte = m["fonte"]
        url, _, revisar = FONTES.get(fonte, ("", "", REVISAO_XSD))
        linhas.append(f"### {fonte}" + (f" ([página]({url}))" if url else ""))
        linhas.append(f"**O que revisar:** {revisar}")
        for titulo, chave in (("Novos", "novos"), ("Removidos", "removidos"), ("Arquivos alterados", "alterados")):
            if m[chave]:
                linhas.append(f"\n**{titulo}:**")
                linhas.extend(f"- {x[:400]}" for x in m[chave][:40])
                if len(m[chave]) > 40:
                    linhas.append(f"- … e mais {len(m[chave]) - 40}")
        linhas.append("")
    linhas += [
        "### Depois de revisar",
        "",
        "1. Ajuste o código (e o `AGENTS.md`, se for uma regra ou armadilha nova).",
        "2. Atualize o retrato: `uv run python scripts/monitor_nfse.py --atualizar`.",
        "3. Faça commit (ex.: `chore(monitor): atualizar retrato da documentação da NFS-e`) e feche esta issue.",
        "",
        f"<!-- nfse-monitor:{assinatura} -->",
    ]
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--atualizar", action="store_true", help="grava o estado atual como novo retrato")
    ap.add_argument("--relatorio", type=Path, help="arquivo Markdown para o relatório de mudanças")
    args = ap.parse_args()

    novo, falhas = coletar()
    for f in falhas:
        print(f"::warning::Fonte indisponível — {f}", file=sys.stderr)

    if args.atualizar:
        if falhas:
            print("Retrato NÃO atualizado: há fontes indisponíveis.", file=sys.stderr)
            return 2
        local = _hash_xsd_local()
        if novo.get("xsd-v1.01") and any(local.get(k) != v for k, v in novo["xsd-v1.01"].items()):
            print("Aviso: os XSDs oficiais diferem da cópia em src/easy_nfse/xsd/ — atualize-a.", file=sys.stderr)
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n")
        print(f"Retrato atualizado em {ESTADO.relative_to(RAIZ)}.")
        return 0

    antigo = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    # compara só as fontes lidas agora (fonte fora do ar não vira "mudança")
    mudancas = comparar({k: v for k, v in antigo.items() if k in novo}, novo)
    assinatura = hashlib.sha256(json.dumps(mudancas, sort_keys=True).encode()).hexdigest()[:16]
    texto = relatorio(mudancas, assinatura) if mudancas else "Nenhuma mudança na documentação oficial."
    if args.relatorio:
        args.relatorio.write_text(texto)
    print(texto)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"mudou={'true' if mudancas else 'false'}\nassinatura={assinatura}\n")
    return 2 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
