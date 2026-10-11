<p align="center"><img src="src/easy_nfse/static/logo.svg" width="96" alt="easy-nfse"></p>

# easy-nfse

App local para emitir NFS-e do **padrão nacional** (Sefin Nacional / nfse.gov.br) a partir de uma nota já emitida.

1. Arraste o **PDF** (DANFSe ou impressão do Emissor Nacional) ou o **XML** de uma nota anterior.
2. O app cria um **template** com prestador, tomador, serviço e tributação. Revise e salve.
3. A cada nova nota, informe só a **data de competência** e o **valor**, revise e emita.

## Rodar

```bash
uv run easy-nfse          # abre http://127.0.0.1:8000
```

Os dados ficam em `./data` (ou em `$EASY_NFSE_DATA`): certificado, senha, templates, numeração e XMLs emitidos.
O servidor escuta só em `127.0.0.1`. Não exponha na rede, porque ele guarda o seu certificado.

## Configuração

- **Certificado A1** (.pfx ICP-Brasil do prestador): em *Configurações*. A senha fica em `data/config.json` (permissão 600)
  ou na variável `EASY_NFSE_CERT_SENHA`.
- **Ambiente**: o padrão é *Produção restrita* (testes, sem validade jurídica). Troque para *Produção* quando estiver tudo certo.
- **Série da DPS**: o padrão é `1`, dentro da faixa de aplicativo próprio (1–49999). O Emissor Web usa outra faixa, então a numeração não colide.

## Tomador do exterior / exportação

Escolha **Exterior (NIF)** no tipo de documento do tomador. O app pede o endereço estrangeiro, o código NBS
(obrigatório, E0318) e os dados de comércio exterior (moeda, modo de prestação etc.). Com tributação
**Exportação de serviço** e prestação no Brasil, o país do resultado é obrigatório (E0590). Por padrão ele é o país do tomador.
A cada emissão você informa o valor na moeda do contrato, e o botão **PTAX** sugere o valor em R$ pela cotação de venda
do Banco Central. Confira com seu contador qual taxa usar.

## Como funciona

| Etapa | Detalhes |
|---|---|
| Importação de PDF | Lê a chave de acesso e os campos do DANFSe (v1.0/v2.0) ou da impressão da Consulta Pública. Códigos IBGE vêm da chave e da API do IBGE. Se houver certificado, baixa o **XML oficial** pela chave (`GET /nfse/{chave}`), que é mais fiel. |
| Importação de XML | Copia exatamente a DPS original (`infDPS`). |
| DPS | Leiaute v1.01, validada contra o XSD oficial (`src/easy_nfse/xsd`). |
| Assinatura | XMLDSig enveloped, RSA-SHA256, C14N 1.0, sem prefixo `ds:`. |
| Envio | `POST /nfse` com mTLS e `{"dpsXmlGZipB64": ...}`. |
| PDF (DANFSe) | Gerado pelo app no layout **DANFSe v2.0** (NT 008/2026), porque a API oficial de DANFSe foi suspensa em 03/08/2026. Fica salvo em `data/emissoes/` e disponível no resultado e no histórico. O histórico também gera o PDF de qualquer XML de NFS-e. |
| Numeração | Só avança quando a Sefin aceita a nota. Reenviar com o mesmo nº é seguro: uma duplicata recebe E0014 e o app mostra a nota existente. |

## Limitações conhecidas

- Sem suporte a intermediário, deduções, tributação federal ou grupo IBS/CBS.
- A leitura de PDF é heurística. Revise sempre o template importado.
- Na cópia local do XSD foram removidos `^`/`$` dos padrões, porque em XSD eles são literais (bug do schema oficial).

## Testes

```bash
uv run pytest                                  # unitários (assinatura verificada com libxmlsec1)
EASY_NFSE_SAMPLES=pasta/com/pdfs uv run pytest # + leitura de PDFs reais
```

## Desenvolvimento

Instruções para agentes de código e convenções do projeto (incluindo **Conventional Commits**) estão em [AGENTS.md](AGENTS.md).
