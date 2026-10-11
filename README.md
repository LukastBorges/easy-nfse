<p align="center"><img src="src/easy_nfse/static/logo.svg" width="96" alt="easy-nfse"></p>

# easy-nfse

Aplicativo local para emitir NFS-e do **padrão nacional** (Sefin Nacional / [nfse.gov.br](https://www.nfse.gov.br/))
a partir de uma nota já emitida.

1. Arraste o **PDF** (DANFSe ou impressão do Emissor Nacional) ou o **XML** de uma nota anterior.
2. O app cria um **template** com prestador, tomador, serviço e tributação. Revise e salve.
3. A cada nova nota, informe apenas a **data de competência** e o **valor**, revise e emita.

## Funcionalidades

- Emissão direta pela **API oficial da Sefin Nacional**, com assinatura digital e autenticação feitas com o seu
  certificado A1, sem intermediários.
- Importação de notas anteriores em PDF ou XML (ou pela chave de acesso, se houver certificado configurado).
- **Tomador do exterior e exportação de serviço**, com conversão do valor em moeda estrangeira pela PTAX.
- Geração do **PDF da nota (DANFSe v2.0)** e histórico das emissões, com download do PDF e do XML.
- Numeração da DPS automática e protegida contra notas duplicadas.
- Tema claro e escuro.

## Requisitos

- macOS, Linux ou Windows com o [uv](https://docs.astral.sh/uv/) instalado (ele baixa o Python 3.13, se necessário).
- **Certificado digital A1** (arquivo `.pfx`/`.p12` ICP-Brasil) do prestador. Certificados A3 (token ou cartão)
  ainda não são suportados.
- Município do prestador aderente à NFS-e de padrão nacional.
- Conexão com a internet para emitir notas.

## Instalação e execução

```bash
git clone https://github.com/LukastBorges/easy-nfse.git
cd easy-nfse
uv run easy-nfse          # instala as dependências na primeira vez e abre http://127.0.0.1:8000
```

## Primeiros passos

1. Em **Configurações**, envie o certificado A1 e a senha dele. Use **Testar conexão com a Sefin** para conferir.
2. Mantenha o ambiente em **Produção restrita** enquanto testa: as notas emitidas nele não têm validade jurídica.
3. Em **Templates**, importe uma nota anterior e revise os dados.
4. No **Início**, escolha o template, informe a data e o valor, revise e emita.
5. Quando estiver tudo certo, mude o ambiente para **Produção** em *Configurações*.

## Dados e segurança

- Tudo fica no seu computador, na pasta `./data` (ou na indicada por `$EASY_NFSE_DATA`): certificado, senha,
  templates, numeração e XMLs das notas emitidas. No macOS e no Linux, os arquivos podem ser lidos apenas pelo seu
  usuário.
- A pasta `data/` está no `.gitignore` e **nunca deve ser versionada nem compartilhada**.
- O servidor escuta apenas em `127.0.0.1`. Não o exponha na rede, pois ele guarda o seu certificado.
- Se preferir não gravar a senha do certificado em disco, defina a variável de ambiente `EASY_NFSE_CERT_SENHA`.

## Configuração

- **Certificado A1**: em *Configurações*. O card fica verde quando o certificado é válido e âmbar quando está expirado.
- **Ambiente**: o padrão é *Produção restrita* (testes, sem validade jurídica). Troque para *Produção* quando estiver
  tudo certo.
- **Série da DPS**: o padrão é `1`, dentro da faixa reservada a aplicativos próprios (1 a 49999). O Emissor Web usa
  outra faixa, então as numerações não colidem.
- **Numeração da DPS**: avança automaticamente a cada nota aceita pela Sefin. Só é preciso ajustá-la se o mesmo CNPJ
  já tiver usado a mesma série em outro sistema.

| Variável de ambiente | Uso |
|---|---|
| `EASY_NFSE_DATA` | Pasta de dados (padrão: `./data`) |
| `EASY_NFSE_CERT_SENHA` | Senha do certificado, em vez de gravá-la em disco |
| `EASY_NFSE_HOST` / `EASY_NFSE_PORT` | Endereço e porta do servidor (padrão: `127.0.0.1:8000`) |
| `EASY_NFSE_NO_BROWSER` | Não abre o navegador ao iniciar |

## Tomador do exterior e exportação

Escolha **Exterior (NIF)** no tipo de documento do tomador. O app pede o endereço no exterior, o código NBS
(obrigatório, E0318) e os dados de comércio exterior (moeda, modo de prestação etc.). Com a tributação
**Exportação de serviço** e a prestação no Brasil, o país do resultado é obrigatório (E0590); por padrão, ele é o
país do tomador.

A cada emissão, você informa o valor na moeda do contrato, e o botão **PTAX** sugere o valor em reais pela cotação de
venda do Banco Central. Confirme com o seu contador qual taxa usar.

## Como funciona

| Etapa | Detalhes |
|---|---|
| Importação de PDF | Lê a chave de acesso e os campos do DANFSe (v1.0/v2.0) ou da impressão da Consulta Pública. Os códigos IBGE vêm da chave e da API do IBGE. Se houver certificado, baixa o **XML oficial** pela chave (`GET /nfse/{chave}`), que é mais fiel. |
| Importação de XML | Copia exatamente a DPS original (`infDPS`). |
| DPS | Leiaute v1.01, validada contra o XSD oficial (`src/easy_nfse/xsd`). |
| Assinatura | XMLDSig *enveloped*, RSA-SHA256, C14N 1.0, sem o prefixo `ds:`. |
| Envio | `POST /nfse` com mTLS e o corpo `{"dpsXmlGZipB64": ...}`. |
| PDF (DANFSe) | Gerado pelo app no layout **DANFSe v2.0** (NT 008/2026), porque a API oficial de DANFSe foi suspensa em 03/08/2026. Fica salvo em `data/emissoes/` e disponível no resultado da emissão e no histórico. O histórico também gera o PDF de qualquer XML de NFS-e. |
| Numeração | Só avança quando a Sefin aceita a nota. Reenviar com o mesmo número é seguro: a Sefin recusa a duplicata (E0014), e o app mostra a nota existente. |

## Limitações conhecidas

- Não há suporte a intermediário, deduções/reduções, tributação federal nem ao grupo IBS/CBS.
- Apenas certificado A1 (arquivo); certificados A3 ainda não são suportados.
- A leitura de PDF é heurística: revise sempre o template importado. Notas dos sistemas municipais antigos
  (anteriores ao padrão nacional) não são reconhecidas.
- Na cópia local do XSD, os caracteres `^` e `$` foram removidos dos padrões (*patterns*), porque em XSD eles são
  literais (falha do esquema oficial).

## Testes

```bash
uv run pytest                                   # testes unitários (assinatura verificada com libxmlsec1)
EASY_NFSE_SAMPLES=pasta/com/pdfs uv run pytest  # inclui a leitura de PDFs reais (não versionados)
```

## Desenvolvimento

As instruções para agentes de código e as convenções do projeto, incluindo o padrão **Conventional Commits**,
estão em [AGENTS.md](AGENTS.md).

## Aviso

Este projeto não tem vínculo com a Receita Federal, a Sefin Nacional nem com prefeituras. A responsabilidade pelas
notas emitidas e pelas informações fiscais é de quem as emite; em caso de dúvida, consulte o seu contador.
