# AGENTS.md — easy-nfse

Instruções para agentes de código (Claude Code e outros) que trabalham neste repositório.
Leia tudo antes de alterar código. Atualize este arquivo quando aprender algo que o próximo agente precisa saber.

## O que é

App **local, de um único usuário**, para emitir **NFS-e do padrão nacional** (Sefin Nacional / nfse.gov.br)
a partir de uma nota anterior. O usuário importa o PDF (DANFSe) ou o XML de uma nota já emitida, o app cria um
**template**, e cada nova emissão pede só **data de competência + valor** (e o valor em moeda estrangeira, na exportação).

Caso de uso real do dono: ME/EPP de Belo Horizonte, que **exporta serviço** (TI) para tomador nos EUA,
com cNaoNIF = 1, NBS obrigatório, comExt em USD e conversão pela PTAX.

## Stack e comandos

- Python 3.13 com **uv**, FastAPI, Jinja2, **htmx**, **Tailwind v4 (browser build)**, lxml, cryptography, pdfplumber, reportlab, httpx.
- Front sem build: `static/vendor/` tem htmx, Tailwind e os ícones Tabler usados (`tabler-icons/`) versionados. Não adicione npm nem bundler.

```bash
uv run easy-nfse                     # sobe em http://127.0.0.1:8000 e abre o navegador
EASY_NFSE_NO_BROWSER=1 EASY_NFSE_PORT=8765 EASY_NFSE_DATA=/tmp/x uv run easy-nfse   # servidor de teste isolado
uv run pytest -q                     # testes (assinatura verificada com libxmlsec1 via pacote xmlsec)
EASY_NFSE_SAMPLES=pasta/com/pdfs uv run pytest -q   # inclui leitura de PDFs reais (não versionados)
```

Variáveis de ambiente: `EASY_NFSE_DATA` (pasta de dados), `EASY_NFSE_CERT_SENHA`, `EASY_NFSE_HOST`, `EASY_NFSE_PORT`, `EASY_NFSE_NO_BROWSER`,
`EASY_NFSE_SEM_ATUALIZACAO` (não consulta releases; os testes ligam no `conftest.py`), `EASY_NFSE_UPDATE_URL` (URL da "última release", para testar com um servidor falso).

## Mapa do código (`src/easy_nfse/`)

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Rotas FastAPI, fluxo importar → editar → revisar → emitir, histórico, configurações, `/cotacao`, `/danfse` |
| `models.py` | Pydantic: `Template` (prestador, tomador, serviço, tributação, `com_ext`, `certificado_id`), `Config` (com a lista `certificados`), `CertificadoSalvo`, `Emissao` |
| `dps.py` | `validar_template`, `montar` (DPS v1.01) e validação XSD. **Regras de negócio da Sefin ficam aqui** |
| `certificado.py` | Leitura do .pfx, CNPJ/CPF pelas OIDs ICP-Brasil, **XMLDSig feito à mão**, contexto mTLS |
| `sefin.py` | Cliente da API (`POST /nfse`, `GET /nfse/{chave}`, `GET/HEAD /dps/{id}`), parse de erros |
| `danfse.py` | Gera o PDF **DANFSe v2.0** (NT 008/2026) a partir do XML da NFS-e (reportlab) |
| `importers/` | `nfse_xml.py` (fiel), `danfse_pdf.py` (heurístico: grade v1/v2 + lista da Consulta Pública), `__init__.py` (campos → Template) |
| `dominios.py` | Países ISO2 (`paises.json`, do Anexo A oficial), moedas BACEN, enums lidos do XSD |
| `ibge.py`, `ptax.py` | Códigos IBGE (API do IBGE, cache em `data/cache`) e cotação PTAX (BCB) |
| `storage.py` | JSON em `data/`: `config.json`, `templates/*.json`, `emissoes/` + `emissoes.jsonl`, `certificados/<id>.pfx` |
| `xsd/` | XSDs oficiais **v1.01** (com um patch, ver abaixo) |
| `atualizacao.py` | Atualização do app empacotado: checa a release mais recente (6 h), baixa o pacote da plataforma, confere o SHA-256 (`digest` da API do GitHub) e instala por troca de pastas |
| `desktop.py` | Modo desktop: servidor em thread + janela pywebview, porta fixa 47318 (segunda instância só mostra a primeira), logs em `<dados>/logs/` |
| `packaging/` | `easy-nfse.spec` (PyInstaller), `launcher.py` e ícones `.icns`/`.ico` |
| `templates/`, `static/` | Jinja + htmx + Tailwind; `app.js` com comportamentos pequenos (dropzone, condicionais, PTAX, tema) |
| Páginas | `/` home (boas-vindas sem templates; com templates: aviso global do ambiente + busca/filtro + cards de emissão (até 3 linhas, depois rola), cada um com o estado do seu certificado + últimas emissões), `/templates` (importador + lista de templates), `/templates/{id}` (emissão), `/templates/{id}/editar`, `/historico`, `/configuracoes` (Emissão global no topo; abaixo, adicionar certificado + busca/filtro + lista com a numeração da DPS de cada CNPJ) |
| Blocos reutilizáveis | `templates/_importador.html`, `_checklist.html`, `_template_linha.html`, `_emissoes.html`, `_macros.html` |

## Regras que NÃO podem ser quebradas

### Segurança e dados
- `data/` contém **certificado A1, senha, notas fiscais e dados de clientes**. Nunca versione, nunca imprima em logs,
  nunca envie a serviços externos. Testes e servidores de teste usam `EASY_NFSE_DATA` apontando para uma pasta temporária.
- O servidor escuta só em `127.0.0.1`. Não mude o padrão.
- **Nunca emita nota em Produção (`tpAmb=1`) em testes ou automações.** Ambiente padrão é Produção restrita (`2`).
  Emissão em produção é irreversível (só cancelamento/substituição).

### Certificados (vários, um por prestador)
- Biblioteca em Configurações: cada `.pfx` fica em `data/certificados/<id>.pfx` e a senha em `config.certificados[]`.
  Reenviar o mesmo certificado (mesma `impressao` SHA-256) substitui o registro em vez de duplicar.
- Titular, documento e validade são **guardados no `config.json` ao salvar**: as páginas usam esses dados e o `.pfx` só
  é decifrado para assinar/conectar (`app.abrir_certificado`). Decifrar todos a cada página custava ~36 ms por
  certificado. Registros sem esses dados (antigos/migrados) são abertos uma vez por `info_certificados` e completados.
- O template usa `certificado_id` se escolhido; senão (**automático**) o certificado do CNPJ/CPF do prestador,
  preferindo o não vencido de validade mais longa (renovar = adicionar o novo, sem mexer nos templates).
  Lógica em `app.certificado_do_template` / `app.problema_certificado`; a Sefin exige o certificado do emitente (E0718).
- Remover um certificado volta ao automático os templates que o tinham escolhido.
- `data/certificado.pfx` + `config.certificado_senha` (até a 0.2.x) são migrados sozinhos em `storage.load_config`.
- `EASY_NFSE_CERT_SENHA` agora é só **fallback** para certificado salvo sem senha (antes sobrepunha a senha salva).
- Importar pela chave tenta todos os certificados válidos, primeiro os cujo documento aparece na chave.

### Numeração da DPS
- O `nDPS` **só avança quando a Sefin aceita** a nota. Reenviar o mesmo número é seguro: duplicata → **E0014**, e o app
  consulta `GET /dps/{id}` e mostra a nota existente. Não "auto-incremente e tente de novo" (geraria nota duplicada).
- Série padrão `1`: faixa de aplicativo próprio é **1–49999** (Emissor Web usa 70000–79999; antigo usava 900).
- Id da DPS: `"DPS" + cMun(7) + tpInsc(1: CPF, 2: CNPJ) + inscrição(14) + série(5) + nDPS(15)` = 45 caracteres.

### Leiaute e regras da Sefin (Anexo I — ver `dps.py`)
- `tpEmit=1`: **não enviar** `prest/xNome` nem `prest/end` (E0121).
- ME/EPP (`opSimpNac=3`): exige `regApTribSN`; **não pode** `indTotTrib` (E0712) → enviar `pTotTribSN`.
- `pAliq`: só em cenários específicos (E0617/E0619/…); por padrão **vazio** (alíquota parametrizada pelo município).
- Exportação (`tribISSQN=3`): sem retenção e sem `pAliq`; `regEspTrib=0` (E0172); **NBS obrigatório** (E0318);
  **comExt obrigatório** (E0330), com `vServMoeda` informado **a cada emissão**; valores "0/00 – Desconhecido" são rejeitados.
- `cPaisResult`: obrigatório na exportação **prestada no Brasil** para tomador no exterior (E0590); **proibido** se a
  prestação for no exterior (E0591).
- Tomador do exterior: `NIF` **ou** `cNaoNIF` (1/2; nunca 0), `end/endExt` (cPais ≠ BR, cEndPost, xCidade, xEstProvReg);
  `nro`/`xBairro` são obrigatórios no XSD → app envia `S/N` e `-` se vazios.
- `dCompet` ≤ data de `dhEmi` (E0015); `dhEmi` é enviado com 1 min de margem (E0008).
- No DANFSe, o NIF impresso como `1`/`2` significa **cNaoNIF**, não um NIF.

## Armadilhas técnicas já resolvidas (não "conserte" de volta)

- **XSD oficial com `^...$` nos patterns**: em XSD isso é literal. Removido na cópia local (`tiposSimples_v1.01.xsd`).
  Se atualizar os XSDs, reaplique: `sed -E 's/pattern value="\^([^"]*)\$"/pattern value="\1"/'`.
- **C14N do lxml em subárvore** (`etree.tostring(sub, method="c14n")`) emite `xmlns=""` espúrios com libxml2 2.14
  → assinatura inválida (E0714). Use `certificado.c14n()` (canonicaliza uma cópia isolada).
- **signxml** não serve: no modo sem prefixo cria elementos fora do namespace ds. A assinatura é feita à mão em
  `Certificado.assinar` (enveloped, RSA-SHA256, C14N 1.0, `Signature` sem prefixo, irmã de `infDPS`).
  Qualquer mudança na assinatura **precisa** passar no teste com `xmlsec` (`test_assinatura_valida_com_xmlsec`).
- **Tailwind v4**: classes reutilizáveis são `@utility` (não `@layer components` + `@apply` de classe custom — quebra
  todo o CSS). Modo escuro via `@custom-variant dark` + `data-theme` no `<html>`; **toda classe de cor nova precisa do par
  `dark:`**. Preflight remove `cursor: pointer` (regra global em `base.html`).
- **htmx**: formulários com `hx-*` recebem fragmentos (`templates/partials/`); formulários sem htmx precisam de página completa
  (ex.: erro em `/danfse` renderiza `historico.html`). Redirecionamento após htmx: header `HX-Redirect`.
- **Ícones**: só [Tabler](https://tabler.io/icons) (outline), via `{{ icone('nome', 'classes') }}` (helper em `app.py`, SVG
  embutido, herda a cor do texto). Não use SVG inline nem glifos (✓, !, ←, ↗, 🌐). Ao usar um ícone novo, rode
  `uv run python scripts/icones_tabler.py` (baixa os usados da versão fixada, apaga os sem uso). O script só enxerga nomes
  em linhas que contêm `icone`: ao escolher o ícone por variável/dicionário, nomeie-a `icone_*`/`icones_*`.
  `test_icones_dos_templates_existem` confere os nomes literais.
- **Aviso da home** é só para o que é global (ambiente). Estado de certificado vai no card do template (e na página de
  emissão), nunca numa lista no alerta.
- **Busca/filtro de listas** (home e Configurações): `[data-filtro]` com `[data-filtro-busca]`, `[data-filtro-estado]`,
  `[data-filtro-contagem]`, `[data-filtro-vazio]` e itens `data-busca`/`data-estado` (vários estados separados por espaço);
  a busca ignora acentos. Grade com `data-max-linhas="N"` mostra N linhas e rola: a altura é medida em `app.js`
  (depende das colunas e da altura dos cards), não fixe em CSS.
- **Confirmações**: nunca use `confirm()`/`onclick`. Use `hx-confirm="texto"` (htmx) ou `data-confirm="texto"` (botão
  de formulário comum), com `data-confirm-titulo`, `data-confirm-acao` e `data-confirm-perigo` opcionais. O diálogo
  `#confirmar` fica em `base.html` e a lógica em `app.js`.
- **PDF**: rótulos e valores do DANFSe usam a mesma fonte; o parser casa **rótulos conhecidos** e atribui valores pela
  coluna/posição (`danfse_pdf._ler_grade`). Use `extract_words(x_tolerance=1)`. Páginas da Consulta Pública são lidas
  como lista rótulo→valor. Ligaduras "fi/fl" somem em alguns PDFs: `util.norm()` remove "fi"/"fl" dos dois lados.
- **API de DANFSe oficial foi suspensa (03/08/2026)**: o app gera o PDF localmente (`danfse.py`), página única, A4,
  com "NFS-e SEM VALIDADE JURÍDICA" quando `tpAmb=2`.
- Endpoints da Sefin: produção `https://sefin.nfse.gov.br/SefinNacional`, restrita
  `https://sefin.producaorestrita.nfse.gov.br/SefinNacional`. Corpo: `{"dpsXmlGZipB64": ...}` com **mTLS**.

## Empacotamento e releases

- Pasta de dados (`storage._pasta_de_dados`): `$EASY_NFSE_DATA` > pasta do usuário se `sys.frozen` (app do PyInstaller)
  > `./data`. Não mude o padrão do código-fonte (`./data`): o dono usa assim no dia a dia.
- O `.spec` precisa de `collect_submodules("reportlab.graphics.barcode")`: o reportlab importa os módulos de código de
  barras via `exec()` e, sem isso, o app empacotado não inicia. Ao adicionar dependências com import dinâmico, rode o
  executável (`EASY_NFSE_NO_BROWSER=1 EASY_NFSE_PORT=47399 dist/easy-nfse.app/Contents/MacOS/easy-nfse`) e teste as
  páginas com `curl`; o workflow de release faz essa verificação nos dois sistemas.
- No Windows, o pywebview (WinForms) carrega o `Python.Runtime.dll` do pythonnet via .NET Framework, que **recusa DLLs
  com a marca "baixado da internet"** (Zone.Identifier, herdada ao extrair o .zip pelo Explorer) → "Failed to resolve
  Python.Runtime.Loader.Initialize". `desktop._desbloquear_dlls` remove a marca ao iniciar e, se a janela nativa falhar
  mesmo assim, o app abre no navegador (não deixe exceção do `webview.start()` escapar).
- **Atualização automática** (`atualizacao.py`): só o app empacotado se atualiza (código-fonte só avisa). Baixa sozinho,
  mas **instala só com clique** ("Reiniciar e atualizar") **ou ao abrir o app** (`desktop.main` → `ao_abrir`), nunca no
  meio de uma emissão (`app._emissao_em_andamento` bloqueia). Instalação: extrai ao lado da pasta do app (`.novo`, mesmo
  disco), um script (sh/PowerShell, saída em `<dados>/atualizacao/trocar.log`) espera o processo sair, troca com volta
  atrás (`.antigo`) e reabre. Tenta instalar na abertura **uma vez por versão** (evita laço se falhar). Depende dos nomes
  `easy-nfse-vX.Y.Z-<plataforma>.(dmg|zip)` e do `.zip` do Windows conter a pasta `easy-nfse/`: se mudar o empacotamento,
  ajuste `atualizacao.plataforma`/`_extrair`. O script sh limita a espera (~2 min): `kill -0` responde para processo zumbi.
- **Menu ⋮ do cabeçalho** (`base.html`): Ajuda (README), Notas de atualização, Reportar um problema (issues) e, por último,
  Sobre (versão, "Verificar agora" e link do código-fonte; o item mostra a versão nova quando houver). As notas vêm de `atualizacao.notas()`, um leitor do formato do
  release-please que mostra só Funcionalidades/Correções/Desempenho: o `CHANGELOG.md` (versões até a instalada; vai no
  app pelo `.spec`) e o corpo da release nova (guardado em `estado.json`). Se mudar as seções do release-please
  (`release-please-config.json`), ajuste `SECOES_VISIVEIS`.
- `tzdata` é dependência só no Windows (não há base de fusos no sistema para `zoneinfo`).
- O repositório usa **releases imutáveis**: publicada, a release não aceita arquivos novos (HTTP 422). Por isso o
  release-please cria a release como **rascunho** (`draft` + `force-tag-creation`), os builds anexam os executáveis
  ao rascunho e o job `publicar` só publica depois que os dois terminaram. Tags no formato `easy-nfse-vX.Y.Z`
  (não mude: o release-please usa o formato para achar a release anterior); arquivos `easy-nfse-vX.Y.Z-<plataforma>`.
- O release-please atualiza a versão também no `uv.lock` (`extra-files`); a CI usa `uv sync --frozen`.
- Versão: única fonte é o `pyproject.toml` (`__version__` vem de `importlib.metadata`). O release-please atualiza o
  `pyproject.toml`, o `CHANGELOG.md` e o `.release-please-manifest.json`; não edite a versão à mão.
- Assinatura de código (Apple/Microsoft) está pendente por decisão do dono; não adicione passos que exijam secrets.

## Monitor da documentação oficial

- `monitor-nfse.yml` roda toda segunda-feira e compara gov.br/nfse (documentação atual, RTC, notas técnicas, anúncios
  de implantação, APIs e o conteúdo dos XSDs v1.01) com `.github/nfse-monitor/estado.json`. Mudou → abre/atualiza uma
  issue com o rótulo `nfse-monitor`, contendo o relatório e o que revisar.
- Ao resolver uma issue dessas: ajuste o código, rode `uv run python scripts/monitor_nfse.py --atualizar` e commite o
  retrato (`chore(monitor): ...`). Não atualize o retrato sem revisar: ele é o registro do que o código já cobre.
- **NT 009** (leiaute RTC, Anexo VI v1.04): em Produção restrita desde 20/10/2026, ainda não em Produção.
  O app não emite os grupos afetados (`IBSCBS`, `vDedRed`/`gReeRepRes` → `vAjusteBC`, códigos 99.02–99.04);
  só **lê** notas de outros emissores, aceitando os dois nomes (`vDedRed`/`vAjusteBC`, `vCalcDR`/`vCalcAjusteBCISSQN`).
  Quando o novo leiaute chegar à Produção com XSD de versão nova, a DPS (`dps.montar`, `xsd/`) precisará ser revista.
- Mudança anunciada a acompanhar: **CNPJ alfanumérico**. O XSD v1.01 ainda exige `[0-9]{14}` e o app trata CNPJ como
  dígitos (`util.digits`, `cnpj_valido`); quando o esquema mudar, isso precisará ser revisto.

## Convenções de código

- Português para UI, mensagens, docstrings e nomes de domínio (`prestador`, `tomador`, `competencia`); siga o estilo existente.
- Mensagens de erro ao usuário devem dizer **o que fazer** e citar o código da Sefin quando houver (ex.: "(E0590)").
- Regra de negócio nova → `dps.validar_template` + teste em `tests/test_core.py`.
- Campo novo no template → `models.py`, `template_form.html`, `app.salvar`, `dps.montar`, `importers/nfse_xml.py`
  (e `danfse_pdf`/`importers/__init__.py` se aparecer no PDF), `danfse.py` se for impresso, e teste.
- Não adicione dependências sem necessidade; prefira a biblioteca padrão. Use `uv add` (nunca pip).
- **Sempre** passe `encoding="utf-8"` ao ler/gravar texto (`read_text`, `write_text`, `open`, `logging.basicConfig`):
  no Windows o padrão é cp1252 e acentos quebram (foi o que derrubou o primeiro build de Windows). A CI roda com
  `PYTHONWARNDEFAULTENCODING=1` e o pytest transforma `EncodingWarning` do pacote em erro.
- Antes de concluir: `uv run pytest -q` verde. Para mudanças de UI, suba um servidor isolado e confira (Playwright via
  `uv run --with playwright ...` funciona) nos temas claro e escuro e em 390 px de largura (sem scroll horizontal).

## Commits: Conventional Commits (obrigatório)

Todas as mensagens de commit seguem [Conventional Commits 1.0](https://www.conventionalcommits.org/pt-br/v1.0.0/):

```
<tipo>(<escopo opcional>): <descrição no imperativo, minúscula, sem ponto final>

[corpo opcional: o porquê da mudança, quebrado em ~72 colunas]

[rodapé opcional: BREAKING CHANGE: ..., Refs: #123]
```

**Tipos:** `feat` (funcionalidade), `fix` (correção), `docs`, `style` (formatação, sem mudar lógica), `refactor`,
`perf`, `test`, `build` (dependências/uv), `ci`, `chore`, `revert`.

**Escopos sugeridos:** `dps`, `assinatura`, `sefin`, `importador`, `danfse`, `ui`, `tema`, `exportacao`, `ptax`,
`config`, `storage`, `xsd`, `deps`, `agents`.

Exemplos:
```
feat(exportacao): suportar tomador do exterior com NIF e endExt
fix(assinatura): canonicalizar cópia isolada para evitar xmlns="" (E0714)
feat(danfse): gerar PDF DANFSe v2.0 conforme NT 008/2026
docs: adicionar instruções para agentes em AGENTS.md
build(deps): adicionar reportlab
feat(dps)!: enviar leiaute v1.01

BREAKING CHANGE: templates antigos precisam do campo com_ext
```

Regras:
- Um commit por mudança lógica; não misture refatoração com funcionalidade.
- `!` após o tipo/escopo ou rodapé `BREAKING CHANGE:` quando quebrar compatibilidade (ex.: formato dos JSON em `data/`).
- Só faça commit/push quando o usuário pedir. Nunca inclua `data/`, `samples/`, certificados ou PDFs/XMLs de notas reais.
