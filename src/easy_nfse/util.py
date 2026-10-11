"""Pequenos utilitários de texto, números e documentos."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def norm(value: str) -> str:
    """Normaliza um rótulo para comparação: sem acento, minúsculo, só [a-z0-9].

    Remove também "fi"/"fl" porque alguns PDFs perdem essas ligaduras
    ("Identificação" vira "Identi cação").
    """
    s = strip_accents(value).lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s.replace("fi", "").replace("fl", "")


def empty_if_dash(value: str | None) -> str:
    v = (value or "").strip()
    return "" if v in {"-", "--", "—", "–", "R$", "R$ -", "%"} else v


_XML_REPLACEMENTS = {
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", " ": " ", "•": "-",
}


def xml_text(value: str, multiline: bool = False) -> str:
    """Limpa texto para os tipos TSString do leiaute (Latin-1, sem espaços nas pontas)."""
    s = value or ""
    for src, dst in _XML_REPLACEMENTS.items():
        s = s.replace(src, dst)
    s = s.replace("\r\n", "\n")
    if not multiline:
        s = re.sub(r"\s+", " ", s)
    else:
        s = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n"))
    s = "".join(c if ord(c) < 256 else strip_accents(c) or "?" for c in s)
    return s.strip()


def parse_money(value: str | None) -> Decimal | None:
    """Aceita "1.500,00", "1500,00", "1500.00", "R$ 1.500" ..."""
    s = (value or "").replace("R$", "").replace(" ", "").strip()
    if not s or s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_percent(value: str | None) -> Decimal | None:
    return parse_money((value or "").replace("%", ""))


def fmt_money(value: Decimal | str | None) -> str:
    if value in (None, ""):
        return ""
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    inteiro, dec = f"{d:.2f}".split(".")
    neg = inteiro.startswith("-")
    inteiro = inteiro.lstrip("-")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return ("-" if neg else "") + "R$ " + ".".join(grupos) + "," + dec


def fmt_doc(value: str) -> str:
    d = digits(value)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return value


def cnpj_valido(value: str) -> bool:
    d = digits(value)
    if len(d) != 14 or d == d[0] * 14:
        return False
    def dv(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        r = sum(int(a) * b for a, b in zip(base, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    return d[12] == dv(d[:12]) and d[13] == dv(d[:13])


def cpf_valido(value: str) -> bool:
    d = digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for i in (9, 10):
        r = sum(int(d[j]) * (i + 1 - j) for j in range(i)) * 10 % 11
        if r % 10 != int(d[i]):
            return False
    return True


def split_municipio_uf(value: str) -> tuple[str, str]:
    """"Porto Alegre - RS", "Porto Alegre/RS", "Porto Alegre / RS / Brasil" -> ("Porto Alegre", "RS")."""
    v = empty_if_dash(value)
    if not v:
        return "", ""
    m = re.match(r"^(.*?)\s*[-/]\s*([A-Za-z]{2})\b", v)
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return v.strip(), ""
