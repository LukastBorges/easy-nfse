"""Atualização automática do app empacotado (releases do GitHub).

Fluxo: `verificar` consulta a última release (no máximo 1x a cada `INTERVALO`); havendo versão nova
para esta plataforma, `baixar` grava o pacote em `<dados>/atualizacao/` e confere o SHA-256 informado
pelo GitHub. A instalação só acontece com um clique (`instalar`) ou ao abrir o app (`instalar_na_abertura`),
nunca durante uma emissão: o pacote é extraído ao lado da pasta do app (mesmo disco, troca atômica), um
script auxiliar espera o app fechar, troca as pastas (desfazendo se algo falhar) e reabre o app.

Rodando pelo código-fonte (`uv run`) não há o que trocar: só avisa que há versão nova.
Desliga com `Config.verificar_atualizacoes` ou `EASY_NFSE_SEM_ATUALIZACAO=1`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import __version__, storage

log = logging.getLogger(__name__)

URL_RELEASES = os.environ.get(
    "EASY_NFSE_UPDATE_URL", "https://api.github.com/repos/LukastBorges/easy-nfse/releases/latest"
)
INTERVALO = timedelta(hours=6)
_trava = threading.Lock()


class AtualizacaoError(Exception):
    pass


def plataforma() -> str | None:
    """Sufixo dos pacotes da release para este sistema (ver .github/workflows/release.yml)."""
    maquina = platform.machine().lower()
    if sys.platform == "darwin" and maquina == "arm64":
        return "macos-arm64"
    if sys.platform == "win32" and maquina in ("amd64", "x86_64"):
        return "windows-x64"
    return None


def versao(texto: str) -> tuple[int, ...]:
    """'easy-nfse-v0.3.1', 'v0.3.1' ou '0.3.1' → (0, 3, 1)."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", texto or "")
    return tuple(int(x) for x in m.groups()) if m else (0,)


def desativada() -> bool:
    return bool(os.environ.get("EASY_NFSE_SEM_ATUALIZACAO")) or not storage.load_config().verificar_atualizacoes


# --- onde o app está instalado -------------------------------------------------------

def pasta_do_app() -> Path | None:
    """O que é trocado na atualização: o easy-nfse.app (macOS) ou a pasta do .exe (Windows)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":  # .../easy-nfse.app/Contents/MacOS/easy-nfse
        return exe.parents[2] if exe.parents[2].suffix == ".app" else None
    return exe.parent


def instalavel() -> tuple[bool, str]:
    """Se este app consegue se atualizar sozinho; senão, o motivo (para mostrar ao usuário)."""
    pasta = pasta_do_app()
    if not pasta:
        return False, "Rodando pelo código-fonte: atualize com git pull."
    if not plataforma():
        return False, "Não há pacote de atualização para este sistema."
    if not (os.access(pasta, os.W_OK) and os.access(pasta.parent, os.W_OK)):
        return False, f"Sem permissão para gravar em {pasta.parent}. Baixe a nova versão pela página da release."
    return True, ""


# --- estado (atualizacao/estado.json) -----------------------------------------------

def _pasta() -> Path:
    return storage.DATA_DIR / "atualizacao"


def _ler() -> dict:
    try:
        return json.loads((_pasta() / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar(estado: dict) -> None:
    _pasta().mkdir(parents=True, exist_ok=True)
    (_pasta() / "estado.json").write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def status() -> dict:
    """O que a interface mostra: versão nova (e se já está baixada) ou que acabou de atualizar."""
    e = _ler()
    nova = versao(e.get("versao", "")) > versao(__version__)
    arquivo = Path(e["arquivo"]) if e.get("arquivo") else None
    pode, motivo = instalavel()
    return {
        "atual": __version__,
        "nova": ".".join(map(str, versao(e["versao"]))) if nova else None,  # "0.4.0" (a tag é easy-nfse-v0.4.0)
        "pagina": e.get("pagina", ""),
        "pronta": bool(nova and pode and arquivo and arquivo.exists()),
        "instalavel": pode,
        "motivo": motivo,
        "erro": e.get("erro", "") if nova else "",
        "baixando": _trava.locked(),  # verificar_e_baixar rodando em segundo plano
        "verificado_em": e.get("verificado_em", ""),
        "atualizado_para": e.get("atualizado_para", ""),
    }


# --- verificar e baixar ------------------------------------------------------------

def verificar(forcar: bool = False) -> dict:
    """Consulta a última release e guarda o que interessa. Respeita INTERVALO, salvo `forcar`."""
    e = _ler()
    if not forcar and e.get("verificado_em"):
        if datetime.now() - datetime.fromisoformat(e["verificado_em"]) < INTERVALO:
            return e
    r = httpx.get(URL_RELEASES, timeout=15, follow_redirects=True,
                  headers={"Accept": "application/vnd.github+json", "User-Agent": f"easy-nfse/{__version__}"})
    r.raise_for_status()
    rel = r.json()
    if rel.get("draft") or rel.get("prerelease"):
        raise AtualizacaoError("A última release ainda não foi publicada.")
    sufixo = plataforma()
    pacote = next((a for a in rel.get("assets", []) if sufixo and a["name"].rsplit(".", 1)[0].endswith(sufixo)), None)
    novo = {
        "verificado_em": datetime.now().isoformat(timespec="seconds"),
        "versao": rel.get("tag_name", ""),
        "pagina": rel.get("html_url", ""),
        "pacote_url": pacote["browser_download_url"] if pacote else "",
        "pacote_nome": pacote["name"] if pacote else "",
        "sha256": (pacote or {}).get("digest", "").removeprefix("sha256:"),
        "notas": (rel.get("body") or "")[:50_000],  # changelog da versão nova (mesmo formato do CHANGELOG.md)
    }
    # mantém o download já feito (e a tentativa de instalação) se a versão não mudou
    if e.get("versao") == novo["versao"]:
        novo.update({k: e[k] for k in ("arquivo", "tentou_instalar", "atualizado_para") if k in e})
    _gravar(novo)
    return novo


def baixar() -> Path:
    """Baixa o pacote da versão nova e confere o SHA-256. Idempotente."""
    e = _ler()
    if versao(e.get("versao", "")) <= versao(__version__):
        raise AtualizacaoError("Não há versão nova.")
    if not (e.get("pacote_url") and re.fullmatch(r"[0-9a-f]{64}", e.get("sha256", ""))):
        raise AtualizacaoError("A release não tem pacote verificável para este sistema; baixe pela página da release.")
    destino = _pasta() / e["pacote_nome"]
    if destino.exists() and _sha256(destino) == e["sha256"]:
        e["arquivo"] = str(destino)
        _gravar(e)
        return destino
    for velho in _pasta().glob("easy-nfse-*"):  # pacotes de versões anteriores
        velho.unlink(missing_ok=True)
    parcial = destino.with_name(destino.name + ".part")
    h = hashlib.sha256()
    with httpx.stream("GET", e["pacote_url"], timeout=60, follow_redirects=True,
                      headers={"User-Agent": f"easy-nfse/{__version__}"}) as r, parcial.open("wb") as f:
        r.raise_for_status()
        for bloco in r.iter_bytes(1 << 20):
            h.update(bloco)
            f.write(bloco)
    if h.hexdigest() != e["sha256"]:
        parcial.unlink(missing_ok=True)
        raise AtualizacaoError("O arquivo baixado não confere com o SHA-256 da release; o download foi descartado.")
    parcial.replace(destino)
    e["arquivo"] = str(destino)
    e.pop("erro", None)
    _gravar(e)
    log.info("Atualização %s baixada e verificada", e["versao"])
    return destino


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def verificar_e_baixar(forcar: bool = False) -> None:
    """Rotina de segundo plano: nunca levanta exceção (registra no estado e no log)."""
    if desativada() and not forcar:
        return
    with _trava:
        try:
            verificar(forcar)
            if status()["nova"] and instalavel()[0]:
                baixar()
        except (httpx.HTTPError, AtualizacaoError, OSError, ValueError, KeyError) as exc:
            log.warning("Verificação de atualização falhou: %s", exc)
            e = _ler()
            e["erro"] = str(exc)
            _gravar(e)


def iniciar_em_segundo_plano() -> None:
    """Verifica agora e a cada INTERVALO, enquanto o app estiver aberto."""
    if os.environ.get("EASY_NFSE_SEM_ATUALIZACAO"):
        return
    parar = threading.Event()

    def laco():
        while not parar.is_set():
            verificar_e_baixar()
            parar.wait(INTERVALO.total_seconds())

    threading.Thread(target=laco, name="atualizacao", daemon=True).start()


# --- notas de atualização (changelog) ---------------------------------------------

SECOES_VISIVEIS = ("Funcionalidades", "Correções", "Desempenho")  # o resto (docs, build, CI) não interessa a quem usa
_VERSAO_MD = re.compile(r"^##\s+\[?(\d+\.\d+\.\d+)\]?(?:\([^)]*\))?\s*(?:\((\d{4}-\d{2}-\d{2})\))?")
_ITEM_MD = re.compile(r"^\*\s+(?:\*\*([^*]+?):\*\*\s+)?(.+)$")
_REFS_MD = re.compile(r"\s*\(\[[0-9a-f]{7,40}\]\([^)]*\)\)(?:,\s*closes\s+.*)?$")


def notas(markdown: str) -> list[dict]:
    """Lê o changelog do release-please: [{versao, data, secoes: [{titulo, itens: [{escopo, texto}]}]}]."""
    versoes: list[dict] = []
    secao: dict | None = None
    for linha in markdown.splitlines():
        if m := _VERSAO_MD.match(linha):
            versoes.append({"versao": m.group(1), "data": m.group(2) or "", "secoes": []})
            secao = None
        elif linha.startswith("### ") and versoes:
            titulo = linha[4:].strip()
            secao = {"titulo": titulo, "itens": []} if titulo in SECOES_VISIVEIS else None
            if secao:
                versoes[-1]["secoes"].append(secao)
        elif secao is not None and (m := _ITEM_MD.match(linha.strip())):
            item = {"escopo": m.group(1) or "", "texto": _REFS_MD.sub("", m.group(2)).strip()}
            if item not in secao["itens"]:  # o release-please repete o commit e o merge do PR
                secao["itens"].append(item)
    return versoes


def changelog() -> list[dict]:
    """Notas das versões até a instalada (CHANGELOG.md vai junto no app empacotado)."""
    aqui = Path(__file__).resolve().parent
    for arq in (aqui / "CHANGELOG.md", aqui.parents[1] / "CHANGELOG.md"):
        if arq.exists():
            return notas(arq.read_text(encoding="utf-8"))
    return []


def notas_da_versao_nova() -> list[dict]:
    if not status()["nova"]:
        return []
    return [v for v in notas(_ler().get("notas", "")) if versao(v["versao"]) > versao(__version__)]


# --- instalar ------------------------------------------------------------------------

def _extrair(pacote: Path, novo: Path) -> None:
    """Coloca o app da versão nova em `novo` (ao lado da pasta atual)."""
    shutil.rmtree(novo, ignore_errors=True)
    if pacote.suffix == ".zip":  # Windows: o .zip contém a pasta easy-nfse/
        with tempfile.TemporaryDirectory(dir=novo.parent, prefix=".easy-nfse-") as tmp:
            with zipfile.ZipFile(pacote) as z:
                for nome in z.namelist():  # nada fora da pasta de destino
                    if Path(nome).is_absolute() or ".." in Path(nome).parts:
                        raise AtualizacaoError(f"Pacote inválido ({nome}).")
                z.extractall(tmp)
            raiz = next(Path(tmp).glob("*/easy-nfse.exe"), None)
            if not raiz:
                raise AtualizacaoError("Pacote sem easy-nfse.exe.")
            raiz.parent.replace(novo)
    elif pacote.suffix == ".dmg":  # macOS: monta só para leitura e copia o .app
        with tempfile.TemporaryDirectory(prefix="easy-nfse-dmg-") as ponto:
            subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", ponto, str(pacote)],
                           check=True, capture_output=True)
            try:
                subprocess.run(["ditto", str(Path(ponto) / "easy-nfse.app"), str(novo)], check=True, capture_output=True)
            finally:
                subprocess.run(["hdiutil", "detach", ponto, "-force"], capture_output=True)
    else:
        raise AtualizacaoError(f"Pacote desconhecido: {pacote.name}")


def script_troca(pid: int, atual: Path, novo: Path, reabrir: bool = True) -> tuple[Path, list[str]]:
    """Grava o script que espera o processo `pid` sair e troca `atual` por `novo` (com volta atrás)."""
    antigo = atual.with_name(atual.name + ".antigo")
    pasta = _pasta()
    pasta.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        exe = atual / "easy-nfse.exe"
        script = pasta / "trocar.ps1"
        script.write_text(f"""$ErrorActionPreference = 'Stop'
try {{ Wait-Process -Id {pid} -Timeout 120 }} catch {{ }}
Start-Sleep -Milliseconds 500
$atual = '{atual}'; $novo = '{novo}'; $antigo = '{antigo}'
if (Test-Path $antigo) {{ Remove-Item $antigo -Recurse -Force }}
Move-Item $atual $antigo
try {{
  Move-Item $novo $atual
  Get-ChildItem $atual -Recurse -File | Unblock-File
}} catch {{
  if (Test-Path $atual) {{ Remove-Item $atual -Recurse -Force }}
  Move-Item $antigo $atual
  throw
}}
Remove-Item $antigo -Recurse -Force -ErrorAction SilentlyContinue
{f"Start-Process '{exe}'" if reabrir else ""}
""", encoding="utf-8")
        return script, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                        "-File", str(script)]
    script = pasta / "trocar.sh"
    script.write_text(f"""#!/bin/sh
i=0; while kill -0 {pid} 2>/dev/null && [ $i -lt 400 ]; do sleep 0.3; i=$((i+1)); done  # até ~2 min
atual='{atual}'; novo='{novo}'; antigo='{antigo}'
rm -rf "$antigo"
mv "$atual" "$antigo" || exit 1
if mv "$novo" "$atual"; then
  rm -rf "$antigo"
else
  rm -rf "$atual"; mv "$antigo" "$atual"; exit 1
fi
{'open "$atual"' if reabrir else ""}
""", encoding="utf-8")
    script.chmod(0o700)
    return script, ["/bin/sh", str(script)]


def instalar() -> None:
    """Prepara a versão baixada, dispara o script de troca e encerra o app (ele reabre na versão nova)."""
    pode, motivo = instalavel()
    if not pode:
        raise AtualizacaoError(motivo)
    st, e = status(), _ler()
    if not st["pronta"]:
        raise AtualizacaoError("A atualização ainda não foi baixada.")
    atual = pasta_do_app()
    novo = atual.with_name(atual.name + ".novo")
    _extrair(Path(e["arquivo"]), novo)
    _, comando = script_troca(os.getpid(), atual, novo)
    e["tentou_instalar"] = e["versao"]
    _gravar(e)
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    with (_pasta() / "trocar.log").open("w", encoding="utf-8") as saida:  # o script roda escondido: erros ficam aqui
        subprocess.Popen(comando, creationflags=flags, start_new_session=sys.platform != "win32", close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=saida, stderr=subprocess.STDOUT)
    log.info("Instalando a atualização %s; o app vai reabrir.", e["versao"])


def ao_abrir() -> bool:
    """Chamado ao abrir o app (antes do servidor). True = há atualização instalando: o app deve sair já.

    Também registra quando a última instalação deu certo, para avisar "atualizado para X".
    """
    e = _ler()
    if e.get("tentou_instalar") and versao(e["tentou_instalar"]) <= versao(__version__):
        e["atualizado_para"] = __version__
        for k in ("tentou_instalar", "arquivo"):
            e.pop(k, None)
        for velho in _pasta().glob("easy-nfse-*"):
            velho.unlink(missing_ok=True)
        _gravar(e)
        return False
    # instala o que ficou baixado, mas só uma vez por versão (se falhou, não entra em laço)
    if desativada() or not status()["pronta"] or e.get("tentou_instalar") == e.get("versao"):
        return False
    try:
        instalar()
    except (AtualizacaoError, OSError, subprocess.SubprocessError) as exc:
        log.warning("Não foi possível instalar a atualização ao abrir: %s", exc)
        e = _ler()
        e["erro"], e["tentou_instalar"] = str(exc), e.get("versao")
        _gravar(e)
        return False
    return True


def dispensar_aviso() -> None:
    e = _ler()
    e.pop("atualizado_para", None)
    _gravar(e)
