"""Persistência simples em arquivos JSON.

Pasta de dados: `$EASY_NFSE_DATA`, se definida; senão a pasta do usuário no app empacotado
(PyInstaller) ou `./data` ao rodar a partir do código-fonte (`uv run easy-nfse`).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from pathlib import Path

from .models import Config, Emissao, Template


def pasta_do_usuario() -> Path:
    """Pasta de dados do app instalado, conforme a convenção de cada sistema."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "easy-nfse"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "easy-nfse"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "easy-nfse"


def _pasta_de_dados() -> Path:
    if os.environ.get("EASY_NFSE_DATA"):
        return Path(os.environ["EASY_NFSE_DATA"])
    if getattr(sys, "frozen", False):  # executável gerado pelo PyInstaller
        return pasta_do_usuario()
    return Path.cwd() / "data"


DATA_DIR = _pasta_de_dados().resolve()
TEMPLATES_DIR = DATA_DIR / "templates"
EMISSOES_DIR = DATA_DIR / "emissoes"
CACHE_DIR = DATA_DIR / "cache"
CONFIG_FILE = DATA_DIR / "config.json"
CERT_FILE = DATA_DIR / "certificado.pfx"
EMISSOES_LOG = DATA_DIR / "emissoes.jsonl"


def ensure_dirs() -> None:
    for d in (DATA_DIR, TEMPLATES_DIR, EMISSOES_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:
        pass


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    tmp.replace(path)


# --- configuração -----------------------------------------------------------------

def load_config() -> Config:
    if CONFIG_FILE.exists():
        return Config.model_validate_json(CONFIG_FILE.read_text(encoding="utf-8"))
    return Config()


def save_config(cfg: Config) -> None:
    ensure_dirs()
    _write_private(CONFIG_FILE, cfg.model_dump_json(indent=2).encode())


def cert_password(cfg: Config) -> str:
    return os.environ.get("EASY_NFSE_CERT_SENHA") or cfg.certificado_senha


def save_certificate(data: bytes) -> None:
    ensure_dirs()
    _write_private(CERT_FILE, data)


def load_certificate() -> bytes | None:
    return CERT_FILE.read_bytes() if CERT_FILE.exists() else None


# --- templates --------------------------------------------------------------------

def new_id() -> str:
    return secrets.token_hex(4)


def _template_path(template_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8}", template_id):
        raise KeyError(template_id)
    return TEMPLATES_DIR / f"{template_id}.json"


def list_templates() -> list[Template]:
    if not TEMPLATES_DIR.exists():
        return []
    items = [Template.model_validate_json(p.read_text(encoding="utf-8")) for p in TEMPLATES_DIR.glob("*.json")]
    return sorted(items, key=lambda t: t.atualizado_em, reverse=True)


def get_template(template_id: str) -> Template:
    path = _template_path(template_id)
    if not path.exists():
        raise KeyError(template_id)
    return Template.model_validate_json(path.read_text(encoding="utf-8"))


def save_template(t: Template) -> None:
    ensure_dirs()
    _write_private(_template_path(t.id), t.model_dump_json(indent=2).encode())


def delete_template(template_id: str) -> None:
    _template_path(template_id).unlink(missing_ok=True)


# --- emissões ---------------------------------------------------------------------

def save_emissao(e: Emissao, dps_xml: bytes, nfse_xml: bytes | None, resposta: dict) -> Emissao:
    ensure_dirs()
    pasta = EMISSOES_DIR / f"{e.emitida_em:%Y-%m-%d}_{e.chave_acesso or e.id_dps}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "dps.xml").write_bytes(dps_xml)
    if nfse_xml:
        (pasta / "nfse.xml").write_bytes(nfse_xml)
    (pasta / "resposta.json").write_text(json.dumps(resposta, indent=2, ensure_ascii=False), encoding="utf-8")
    e.pasta = str(pasta.relative_to(DATA_DIR))
    with EMISSOES_LOG.open("a", encoding="utf-8") as f:
        f.write(e.model_dump_json() + "\n")
    return e


def list_emissoes() -> list[Emissao]:
    if not EMISSOES_LOG.exists():
        return []
    items = [Emissao.model_validate_json(line) for line in EMISSOES_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    return list(reversed(items))


def find_emissao(chave: str) -> Emissao | None:
    return next((e for e in list_emissoes() if e.chave_acesso == chave), None)
