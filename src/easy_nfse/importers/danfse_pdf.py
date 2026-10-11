"""Extrai dados de um PDF de NFS-e do padrão nacional.

Suporta:
  * DANFSe v1.0 e v2.0 (NT 008/2026) - layout em grade: rótulo em cima, valor embaixo, em colunas;
  * impressão da página da Consulta Pública / Emissor Nacional - layout em lista: rótulo e valor
    em linhas consecutivas.

O resultado é um dicionário "seção.campo" -> texto, que depois vira um Template.
Leitura de PDF é heurística: o usuário sempre revisa o template importado.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber

from ..util import norm

# --------------------------------------------------------------------------------------
# Dicionário de rótulos
# --------------------------------------------------------------------------------------

SECOES_GRADE = {
    "prest": ["PRESTADOR / FORNECEDOR"],
    "toma": ["TOMADOR DO SERVIÇO", "TOMADOR / ADQUIRENTE", "TOMADOR/ADQUIRENTE DA OPERAÇÃO"],
    "dest": ["DESTINATÁRIO DA OPERAÇÃO", "O DESTINATÁRIO É O PRÓPRIO TOMADOR/ADQUIRENTE DA OPERAÇÃO"],
    "interm": ["INTERMEDIÁRIO DO SERVIÇO", "INTERMEDIÁRIO DA OPERAÇÃO"],
    "serv": ["SERVIÇO PRESTADO"],
    "trib": ["TRIBUTAÇÃO MUNICIPAL", "TRIBUTAÇÃO MUNICIPAL (ISSQN)"],
    "fed": ["TRIBUTAÇÃO FEDERAL", "TRIBUTAÇÃO FEDERAL (EXCETO CBS)"],
    "ibs": ["TRIBUTAÇÃO IBS / CBS"],
    "total": ["VALOR TOTAL DA NFS-E"],
    "aprox": ["TOTAIS APROXIMADOS DOS TRIBUTOS"],
    "info": ["INFORMAÇÕES COMPLEMENTARES"],
}

ROTULOS_GRADE = {
    # identificação
    "chave": ["Chave de Acesso da NFS-e"],
    "numero_nfse": ["Número da NFS-e"],
    "competencia": ["Competência da NFS-e"],
    "numero_dps": ["Número da DPS"],
    "serie_dps": ["Série da DPS"],
    "emitente": ["Emitente da NFS-e"],
    "x": [
        "Data e Hora da emissão da NFS-e", "Data e Hora da emissão da DPS", "Situação da NFS-e",
        "Finalidade",
        # tributação municipal (não usados, mas delimitam colunas)
        "Suspensão da Exigibilidade do ISSQN",
        "Suspenção da Exigibilidade do ISSQN", "Número Processo Suspensão", "Benefício Municipal",
        "Desconto Incondicionado", "Total Deduções/Reduções", "Cálculo do BM", "BC ISSQN", "ISSQN Apurado",
        # federal / totais / IBS-CBS
        "IRRF", "CP", "CSLL", "PIS", "COFINS", "Retenção do PIS/COFINS", "TOTAL TRIBUTAÇÃO FEDERAL",
        "Contribuição Previdenciária - Retida", "Contribuições Sociais - Retidas",
        "PIS - Débito Apuração Própria", "COFINS - Débito Apuração Própria",
        "Descrição Contrib. Sociais - Retidas", "CST / cClassTrib",
        "Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF",
        "Exclusões e Reduções da Base de Cálculo", "Base de Cálculo Após Exclusões e Reduções",
        "Red. Alíquota IBS / Red. Alíquota CBS", "Alíquota - IBS UF / IBS Mun",
        "Aliq. Efetiva Municipal - IBS", "Valor Apurado Municipal - IBS", "Aliq. Efetiva Estadual - IBS",
        "Valor Apurado Estadual - IBS", "Valor Total Apurado - IBS", "Alíquota - CBS",
        "Alíquota Efetiva - CBS", "Valor Total Apurado - CBS", "Desconto Condicionado", "ISSQN Retido",
        "IRRF, CP, CSLL - Retidos", "PIS/COFINS Retidos", "Valor Líquido da NFS-e",
        "Total das Retenções (ISSQN / Federais)", "Total do IBS/CBS", "VALOR LÍQUIDO DA NFS-e + IBS/CBS",
        "Federais", "Estaduais", "Municipais",
        "Data Cientificação", "Identificação e Assinatura", "Nº NFS-e / Chave NFS-e",
    ],
    # pessoas
    "doc": ["CNPJ / CPF / NIF"],
    "im": ["Inscrição Municipal", "Indicador Municipal (Inscrição)", "Indicador Municipal"],
    "fone": ["Telefone"],
    "nome": ["Nome / Nome Empresarial"],
    "email": ["E-mail"],
    "endereco": ["Endereço"],
    "municipio": ["Município"],
    "cep": ["CEP"],
    "municipio_uf": ["Município / Sigla UF"],
    "ibge_cep": ["Código IBGE / CEP"],
    "simples": ["Simples Nacional na Data de Competência"],
    "regime_sn": ["Regime de Apuração Tributária pelo SN"],
    # serviço
    "ctribnac": ["Código de Tributação Nacional"],
    "ctribmun": ["Código de Tributação Municipal"],
    "ctrib_nac_mun": ["Código de Tributação Nacional / Municipal"],
    "local": ["Local da Prestação"],
    "pais": ["País da Prestação"],
    "local_uf_pais": ["Local da Prestação / Sigla UF / País"],
    "nbs": ["Código da NBS"],
    "descricao": ["Descrição do Serviço"],
    # tributação municipal
    "trib_issqn": ["Tributação do ISSQN", "Tipo de Tributação do ISSQN"],
    "pais_result": ["País Resultado da Prestação do Serviço"],
    "mun_incid": ["Município de Incidência do ISSQN", "Município / Sigla UF / País de Incidência do ISSQN"],
    "reg_esp": ["Regime Especial de Tributação", "Regime Especial de Tributação do ISSQN"],
    "imunidade": ["Tipo de Imunidade", "Tipo de Imunidade do ISSQN"],
    "valor_serv": ["Valor do Serviço"],
    "valor_operacao": ["VALOR DA OPERAÇÃO / SERVIÇO"],
    "aliquota": ["Alíquota Aplicada"],
    "retencao": ["Retenção do ISSQN"],
}

SECOES_LISTA = {
    "Identificação da NFS-e": "ident", "Identificação do DPS": "dps", "Emitente": "prest",
    "Tomador": "toma", "Intermediário": "interm", "Serviço Prestado": "serv",
    "Tributação Municipal": "trib", "Tributação Federal": "fed", "Outras Informações": "outras",
    "Informações Complementares": "info", "Total dos tributos": "aprox",
}

ROTULOS_LISTA = {
    "chave": ["Chave de acesso"],
    "numero": ["Número"],
    "serie": ["Série"],
    "nome": ["Razão Social", "Nome/Razão Social", "Nome / Nome Empresarial"],
    "doc": ["CNPJ", "CPF", "NIF"],
    "im": ["Inscrição Municipal"],
    "simples": ["Situação Perante o Simples Nacional"],
    "regime_sn": ["Regime de Apuração Tributária pelo SN"],
    "reg_esp": ["Regime Especial de Tributação"],
    "endereco_lista": ["Endereço do Estabelecimento/Domicílio"],
    "fone": ["Telefone"],
    "email": ["Email", "E-mail"],
    "trib_issqn": ["Tributação do ISSQN"],
    "pais_result": ["País Resultado da Prestação de Serviço"],
    "mun_incid": ["Município de Incidência"],
    "imunidade": ["Tipo de Imunidade"],
    "valor_serv": ["Valor do Serviço"],
    "aliquota": ["Alíquota"],
    "retencao": ["Retenção"],
    "pais": ["País"],
    "local": ["Município"],
    "ctribnac": ["Código de Tributação Nacional"],
    "ctribmun": ["Código de Tributação Municipal"],
    "nbs": ["Item da NBS correspondente ao serviço prestado"],
    "descricao": ["Descrição do serviço"],
    "info": ["Informações complementares"],
    "x": [
        "Data de geração", "Versão", "Data de emissão",
        "Suspensão do ISSQN", "Número processo suspensão", "Benefício Municipal - BM",
        "Desconto incondicionado", "Total Deduções/Reduções", "Total Benefício Municipal",
        "Base de Cálculo", "Valor do ISSQN", "Versão da Aplicação", "Ambiente Gerador",
        "Situação da NFS-e", "Número de documento de responsabilidade técnica", "Documento de referência",
        "Situação tributária do PIS/COFINS", "Base de cálculo PIS/COFINS", "PIS - Alíquota",
        "PIS - Valor do imposto", "COFINS - Alíquota", "COFINS - Valor do imposto",
        "Tipo de Retenção do PIS/Cofins", "Valor Retido IRRF", "Valor Retido CSLL", "Valor Retido CP",
        "Opção", "Federal", "Estadual", "Municipal",
    ],
}


def _indice(rotulos: dict[str, list[str]]) -> dict[str, str]:
    return {norm(texto): chave for chave, textos in rotulos.items() for texto in textos}


_GRADE = _indice(ROTULOS_GRADE)
_GRADE_SECOES = {norm(t): s for s, ts in SECOES_GRADE.items() for t in ts}
_LISTA = _indice(ROTULOS_LISTA)
_LISTA_SECOES = {norm(t): s for t, s in SECOES_LISTA.items()}
_MAX_PALAVRAS_ROTULO = 16


# --------------------------------------------------------------------------------------
# Layout em grade (DANFSe)
# --------------------------------------------------------------------------------------

@dataclass
class _Palavra:
    texto: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class _Rotulo:
    chave: str  # "sec:toma" para títulos de bloco
    x0: float
    top: float
    bottom: float
    fim_coluna: float = 0
    valores: list[tuple[float, float, str]] = field(default_factory=list)


def _linhas(palavras: list[_Palavra]) -> list[list[_Palavra]]:
    linhas: list[list[_Palavra]] = []
    for p in sorted(palavras, key=lambda p: (p.top, p.x0)):
        if linhas and abs(linhas[-1][0].top - p.top) <= 2:
            linhas[-1].append(p)
        else:
            linhas.append([p])
    return [sorted(linha, key=lambda p: p.x0) for linha in linhas]


def _grupos(linha: list[_Palavra], gap: float = 5) -> list[list[_Palavra]]:
    grupos: list[list[_Palavra]] = []
    for p in linha:
        if grupos and p.x0 - grupos[-1][-1].x1 <= gap:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return grupos


def _casar_rotulo(palavras: list[_Palavra]) -> tuple[str, int] | None:
    """Maior prefixo de `palavras` que é um rótulo conhecido -> (chave, nº de palavras)."""
    for n in range(min(len(palavras), _MAX_PALAVRAS_ROTULO), 0, -1):
        alvo = norm("".join(p.texto for p in palavras[:n]))
        if alvo in _GRADE_SECOES:
            return "sec:" + _GRADE_SECOES[alvo], n
        if alvo in _GRADE:
            # rótulos curtos ("CP", "CEP") só valem se ocupam o grupo inteiro
            if len(alvo) <= 6 and n != len(palavras):
                continue
            return _GRADE[alvo], n
    return None


def _ler_grade(page) -> dict[str, str]:
    palavras = [
        _Palavra(w["text"], w["x0"], w["x1"], w["top"], w["bottom"])
        for w in page.extract_words(x_tolerance=1, y_tolerance=2)
    ]
    separadores = sorted(
        e["top"] for e in page.horizontal_edges if (e["x1"] - e["x0"]) > page.width * 0.3
    )
    rotulos: list[_Rotulo] = []
    valores: list[tuple[float, float, str]] = []  # (top, x0, texto)

    for linha in _linhas(palavras):
        rotulos_linha: list[_Rotulo] = []
        for grupo in _grupos(linha):
            i = 0
            while i < len(grupo):
                casado = _casar_rotulo(grupo[i:])
                if not casado:
                    if i == 0 or not rotulos_linha:
                        valores.append((grupo[i].top, grupo[i].x0, " ".join(p.texto for p in grupo[i:])))
                    else:  # texto colado ao rótulo ("INTERMEDIÁRIO ... NÃO IDENTIFICADO")
                        rotulos_linha[-1].valores.append(
                            (grupo[i].top, grupo[i].x0, " ".join(p.texto for p in grupo[i:]))
                        )
                    break
                chave, n = casado
                rotulos_linha.append(_Rotulo(chave, grupo[i].x0, grupo[i].top, grupo[i + n - 1].bottom))
                i += n
        rotulos_linha.sort(key=lambda r: r.x0)
        for r, prox in zip(rotulos_linha, rotulos_linha[1:] + [None]):
            r.fim_coluna = prox.x0 if prox else page.width + 1
        rotulos.extend(rotulos_linha)

    for top, x0, texto in valores:
        candidatos = [r for r in rotulos if r.top < top - 1 and r.x0 - 4 <= x0 < r.fim_coluna]
        if not candidatos:
            continue
        # o rótulo mais próximo acima; na mesma linha de rótulos, o de coluna mais à direita
        topo = max(r.top for r in candidatos)
        dono = max((r for r in candidatos if r.top >= topo - 2), key=lambda r: r.x0)
        if any(dono.bottom + 0.5 < s < top - 0.5 for s in separadores):
            continue
        dono.valores.append((top, x0, texto))

    # Seções: no DANFSe v1 o bloco do prestador começa em "EMITENTE DA NFS-e".
    v2 = any(r.chave == "sec:prest" for r in rotulos)
    secoes = sorted(
        (r.top, r.chave[4:] if r.chave.startswith("sec:") else "prest")
        for r in rotulos
        if r.chave.startswith("sec:") or (r.chave == "emitente" and not v2)
    )

    campos: dict[str, str] = {}
    for r in rotulos:
        secao = "ident"
        for top, nome in secoes:
            if top <= r.top + 2:
                secao = nome
        chave = r.chave[4:] + ".titulo" if r.chave.startswith("sec:") else f"{secao}.{r.chave}"
        if r.chave == "emitente" and not v2:
            chave = "ident.emitente"
        linhas_valor: list[str] = []
        ultimo_top = None
        for top, _x0, texto in sorted(r.valores):
            if ultimo_top is not None and abs(top - ultimo_top) <= 2:
                linhas_valor[-1] += " " + texto
            else:
                linhas_valor.append(texto)
            ultimo_top = top
        valor = "\n".join(linhas_valor).strip()
        if valor and not campos.get(chave):
            campos[chave] = valor
    return campos


# --------------------------------------------------------------------------------------
# Layout em lista (impressão da Consulta Pública / Emissor Nacional)
# --------------------------------------------------------------------------------------

_LIXO = [
    re.compile(r"^https?://"),
    re.compile(r"^\d{2}/\d{2}/\d{4},? \d{2}:\d{2}"),
    re.compile(r"^Página \d+ de \d+$"),
]


def _ler_lista(texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    secao = "ident"
    atual: str | None = None
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or any(p.search(linha) for p in _LIXO):
            continue
        n = norm(linha)
        if n in _LISTA_SECOES and not (_LISTA_SECOES[n] == secao and n in _LISTA):
            secao = _LISTA_SECOES[n]
            atual = None
            continue
        if n in _LISTA:
            chave = _LISTA[n]
            atual = None if chave == "x" else f"{secao}.{chave}"
            if atual and atual in campos:
                atual = None  # mantém a primeira ocorrência
            continue
        if atual:
            campos[atual] = (campos.get(atual, "") + "\n" + linha).strip()
    # normaliza nomes de campos da identificação da DPS
    if "dps.numero" in campos:
        campos["ident.numero_dps"] = campos.pop("dps.numero")
    if "dps.serie" in campos:
        campos["ident.serie_dps"] = campos.pop("dps.serie")
    return campos


# --------------------------------------------------------------------------------------

def extrair(data: bytes) -> tuple[dict[str, str], str]:
    """Retorna (campos, texto completo)."""
    campos_grade: dict[str, str] = {}
    texto_lista: list[str] = []
    texto_total: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            texto = page.extract_text(x_tolerance=1) or ""
            texto_total.append(texto)
            cabecalho = norm(texto[:600])
            if "danfsev" in cabecalho or "documentoauxiliar" in cabecalho:
                for k, v in _ler_grade(page).items():
                    campos_grade.setdefault(k, v)
            else:
                texto_lista.append(page.extract_text() or "")
    campos = _ler_lista("\n".join(texto_lista)) if texto_lista else {}
    campos.update(campos_grade)  # a grade (DANFSe) tem prioridade
    return campos, "\n".join(texto_total)
