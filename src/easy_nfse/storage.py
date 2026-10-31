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

from pydantic import BaseModel

from .models import CertificadoSalvo, Config, Emissao, Prestador, Template, Tomador
from .util import digits, strip_accents


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
PRESTADORES_DIR = DATA_DIR / "prestadores"
TOMADORES_DIR = DATA_DIR / "tomadores"
BACKUP_DIR = DATA_DIR / "backup"
EMISSOES_DIR = DATA_DIR / "emissoes"
CACHE_DIR = DATA_DIR / "cache"
CONFIG_FILE = DATA_DIR / "config.json"
CERTS_DIR = DATA_DIR / "certificados"
CERT_FILE = DATA_DIR / "certificado.pfx"  # legado: certificado único das versões até 0.2
EMISSOES_LOG = DATA_DIR / "emissoes.jsonl"


def ensure_dirs() -> None:
    for d in (DATA_DIR, TEMPLATES_DIR, PRESTADORES_DIR, TOMADORES_DIR, EMISSOES_DIR, CACHE_DIR, CERTS_DIR):
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
    cfg = Config.model_validate_json(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else Config()
    if CERT_FILE.exists():
        _migrar_certificado_unico(cfg)
    return cfg


def save_config(cfg: Config) -> None:
    ensure_dirs()
    _write_private(CONFIG_FILE, cfg.model_dump_json(indent=2).encode())


# --- certificados -----------------------------------------------------------------

def _migrar_certificado_unico(cfg: Config) -> None:
    """Versões anteriores guardavam um só certificado em `certificado.pfx`: vira o primeiro da lista."""
    salvo = CertificadoSalvo(id=new_id(), arquivo=CERT_FILE.name, senha=cfg.certificado_senha)
    save_certificate(salvo.id, CERT_FILE.read_bytes())
    cfg.certificados.append(salvo)
    cfg.certificado_senha = ""
    save_config(cfg)
    CERT_FILE.unlink()


def cert_password(c: CertificadoSalvo) -> str:
    return c.senha or os.environ.get("EASY_NFSE_CERT_SENHA", "")


def _cert_path(cert_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8}", cert_id):
        raise KeyError(cert_id)
    return CERTS_DIR / f"{cert_id}.pfx"


def save_certificate(cert_id: str, data: bytes) -> None:
    ensure_dirs()
    _write_private(_cert_path(cert_id), data)


def load_certificate(cert_id: str) -> bytes | None:
    path = _cert_path(cert_id)
    return path.read_bytes() if path.exists() else None


def delete_certificate(cert_id: str) -> None:
    _cert_path(cert_id).unlink(missing_ok=True)


# --- templates --------------------------------------------------------------------

def new_id() -> str:
    return secrets.token_hex(4)


def _json_path(pasta: Path, ident: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{8}", ident):
        raise KeyError(ident)
    return pasta / f"{ident}.json"


def _template_path(template_id: str) -> Path:
    return _json_path(TEMPLATES_DIR, template_id)


def _legado(raw: dict) -> bool:
    """Template das versões até a 0.4, com a própria cópia do prestador e do tomador."""
    return "prestador_id" not in raw


def resolver(templates: list[Template]) -> list[Template]:
    """Preenche `prestador` e `tomador` a partir dos cadastros apontados pelo template."""
    prestadores = {p.id: p for p in list_prestadores()}
    tomadores = {t.id: t for t in list_tomadores()}
    for t in templates:
        t.prestador = prestadores.get(t.prestador_id) or Prestador()
        t.tomador = tomadores.get(t.tomador_id) if t.tomador_id else None
    return templates


def list_templates() -> list[Template]:
    if not TEMPLATES_DIR.exists():
        return []
    raws = [json.loads(p.read_text(encoding="utf-8")) for p in TEMPLATES_DIR.glob("*.json")]
    if any(_legado(r) for r in raws):
        migrar_cadastros()
        return list_templates()
    items = resolver([Template.model_validate(r) for r in raws])
    return sorted(items, key=lambda t: t.atualizado_em, reverse=True)


def get_template(template_id: str) -> Template:
    path = _template_path(template_id)
    if not path.exists():
        raise KeyError(template_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if _legado(raw):
        migrar_cadastros()
        return get_template(template_id)
    return resolver([Template.model_validate(raw)])[0]


def save_template(t: Template) -> None:
    """Grava o template (só os ids do prestador e do tomador: os cadastros são gravados à parte)."""
    ensure_dirs()
    _write_private(_template_path(t.id), t.model_dump_json(indent=2).encode())


def delete_template(template_id: str) -> None:
    _template_path(template_id).unlink(missing_ok=True)


# --- prestadores e tomadores --------------------------------------------------------

def _ordem(c: Prestador | Tomador) -> tuple:
    return strip_accents(c.nome).casefold(), c.documento


def list_prestadores() -> list[Prestador]:
    pastas = PRESTADORES_DIR.glob("*.json") if PRESTADORES_DIR.exists() else []
    return sorted((Prestador.model_validate_json(p.read_text(encoding="utf-8")) for p in pastas), key=_ordem)


def get_prestador(prestador_id: str) -> Prestador:
    path = _json_path(PRESTADORES_DIR, prestador_id)
    if not path.exists():
        raise KeyError(prestador_id)
    return Prestador.model_validate_json(path.read_text(encoding="utf-8"))


def save_prestador(p: Prestador) -> None:
    ensure_dirs()
    _write_private(_json_path(PRESTADORES_DIR, p.id), p.model_dump_json(indent=2).encode())


def delete_prestador(prestador_id: str) -> None:
    _json_path(PRESTADORES_DIR, prestador_id).unlink(missing_ok=True)


def list_tomadores() -> list[Tomador]:
    pastas = TOMADORES_DIR.glob("*.json") if TOMADORES_DIR.exists() else []
    return sorted((Tomador.model_validate_json(p.read_text(encoding="utf-8")) for p in pastas), key=_ordem)


def get_tomador(tomador_id: str) -> Tomador:
    path = _json_path(TOMADORES_DIR, tomador_id)
    if not path.exists():
        raise KeyError(tomador_id)
    return Tomador.model_validate_json(path.read_text(encoding="utf-8"))


def save_tomador(t: Tomador) -> None:
    ensure_dirs()
    _write_private(_json_path(TOMADORES_DIR, t.id), t.model_dump_json(indent=2).encode())


def delete_tomador(tomador_id: str) -> None:
    _json_path(TOMADORES_DIR, tomador_id).unlink(missing_ok=True)


def _sem_acento(texto: str) -> str:
    return " ".join(strip_accents(texto).casefold().split())


def chave_prestador(p: Prestador) -> str:
    """Identidade do prestador: tipo + CNPJ/CPF ("" se não houver documento)."""
    doc = digits(p.documento)
    return f"{p.tipo_doc}:{doc}" if doc else ""


def chave_tomador(t: Tomador) -> str:
    """Identidade do tomador: CPF/CNPJ, NIF ou, no exterior sem NIF (cNaoNIF), nome + país."""
    if t.tipo_doc == "NIF":
        if t.documento.strip():
            return f"NIF:{t.documento.strip().upper()}"
        nome = _sem_acento(t.nome)
        return f"NIF-sem:{t.endereco.pais}:{nome}" if nome else ""
    doc = digits(t.documento)
    return f"{t.tipo_doc}:{doc}" if doc else ""


_FORA_DA_COMPARACAO = {"id", "criado_em", "atualizado_em", "certificado_id", "municipio", "endereco.municipio"}
ROTULOS_CAMPOS = {
    "nome": "nome", "im": "inscrição municipal", "fone": "telefone", "email": "e-mail",
    "cod_municipio": "município", "op_simp_nac": "Simples Nacional", "reg_ap_trib_sn": "regime de apuração",
    "reg_esp_trib": "regime especial", "c_nao_nif": "motivo sem NIF", "tipo_doc": "tipo de documento",
}


def _achatar(d: dict, prefixo: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_achatar(v, f"{prefixo}{k}."))
        else:
            out[f"{prefixo}{k}"] = v
    return out


def diferencas(cadastro: BaseModel, outro: BaseModel) -> list[str]:
    """Campos preenchidos em `outro` que divergem do `cadastro` (rótulos para o usuário)."""
    a, b = _achatar(cadastro.model_dump(mode="json")), _achatar(outro.model_dump(mode="json"))
    rotulos = []
    for k, v in b.items():
        if k in _FORA_DA_COMPARACAO or v in ("", None):
            continue
        if _sem_acento(str(v)) != _sem_acento(str(a.get(k) or "")):
            rotulo = "endereço" if k.startswith("endereco.") else ROTULOS_CAMPOS.get(k, k)
            if rotulo not in rotulos:
                rotulos.append(rotulo)
    return rotulos


def vincular_prestador(p: Prestador) -> tuple[Prestador, bool, list[str]]:
    """O cadastro com o mesmo CNPJ/CPF ou, se não houver, `p` gravado como novo.

    Retorna (cadastro, se foi criado agora, campos em que `p` diverge do cadastro existente). O cadastro
    existente não é alterado: quem chama avisa o usuário das diferenças.
    """
    chave = chave_prestador(p)
    existente = next((x for x in list_prestadores() if chave and chave_prestador(x) == chave), None)
    if existente:
        return existente, False, diferencas(existente, p)
    p.id = new_id()
    save_prestador(p)
    return p, True, []


def vincular_tomador(t: Tomador) -> tuple[Tomador, bool, list[str]]:
    """Como `vincular_prestador`, pela chave do tomador (`chave_tomador`)."""
    chave = chave_tomador(t)
    existente = next((x for x in list_tomadores() if chave and chave_tomador(x) == chave), None)
    if existente:
        return existente, False, diferencas(existente, t)
    t.id = new_id()
    save_tomador(t)
    return t, True, []


def migrar_cadastros() -> None:
    """Até a 0.4, cada template guardava a sua cópia do prestador e do tomador (e o certificado escolhido).

    Passa a apontar para cadastros únicos (`prestadores/`, `tomadores/`), com o certificado no prestador.
    Os templates mais recentes vêm primeiro: havendo divergência, o cadastro fica com os dados deles e os
    outros templates recebem um aviso. Os JSON originais ficam em `backup/templates-0.4/`. Pode ser
    interrompida e rodada de novo.
    """
    legados = []
    for path in TEMPLATES_DIR.glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if _legado(raw):
            legados.append((path, raw))
    if not legados:
        return
    backup = BACKUP_DIR / "templates-0.4"
    backup.mkdir(parents=True, exist_ok=True)
    legados.sort(key=lambda item: str(item[1].get("atualizado_em", "")), reverse=True)
    for path, raw in legados:
        if not (backup / path.name).exists():
            _write_private(backup / path.name, path.read_bytes())
        avisos = raw.setdefault("avisos", [])

        p, _, dif = vincular_prestador(Prestador.model_validate(raw.get("prestador") or {}))
        if raw.get("certificado_id") and not p.certificado_id:
            p.certificado_id = raw["certificado_id"]
            save_prestador(p)
        if dif:
            avisos.append(f"O prestador {p.nome or p.documento} é usado por outros templates com dados diferentes "
                          f"({', '.join(dif)}). Ficou o cadastro mais recente: confira em Cadastros.")
        raw["prestador_id"] = p.id

        raw["tomador_id"] = ""
        tom = raw.get("tomador")
        if tom and (tom.get("documento") or tom.get("nome")):
            t, _, dif = vincular_tomador(Tomador.model_validate(tom))
            if dif:
                avisos.append(f"O tomador {t.nome} é usado por outros templates com dados diferentes "
                              f"({', '.join(dif)}). Ficou o cadastro mais recente: confira em Cadastros.")
            raw["tomador_id"] = t.id
        for campo in ("prestador", "tomador", "certificado_id"):
            raw.pop(campo, None)
        _write_private(path, json.dumps(raw, indent=2, ensure_ascii=False).encode())


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
