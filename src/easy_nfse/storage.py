"""Persistência simples em arquivos JSON dentro de ./data (ou $EASY_NFSE_DATA)."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

from .models import Config, Emissao, Template

DATA_DIR = Path(os.environ.get("EASY_NFSE_DATA", Path.cwd() / "data")).resolve()
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
        return Config.model_validate_json(CONFIG_FILE.read_text())
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
    items = [Template.model_validate_json(p.read_text()) for p in TEMPLATES_DIR.glob("*.json")]
    return sorted(items, key=lambda t: t.atualizado_em, reverse=True)


def get_template(template_id: str) -> Template:
    path = _template_path(template_id)
    if not path.exists():
        raise KeyError(template_id)
    return Template.model_validate_json(path.read_text())


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
    (pasta / "resposta.json").write_text(json.dumps(resposta, indent=2, ensure_ascii=False))
    e.pasta = str(pasta.relative_to(DATA_DIR))
    with EMISSOES_LOG.open("a") as f:
        f.write(e.model_dump_json() + "\n")
    return e


def list_emissoes() -> list[Emissao]:
    if not EMISSOES_LOG.exists():
        return []
    items = [Emissao.model_validate_json(line) for line in EMISSOES_LOG.read_text().splitlines() if line.strip()]
    return list(reversed(items))


def find_emissao(chave: str) -> Emissao | None:
    return next((e for e in list_emissoes() if e.chave_acesso == chave), None)
