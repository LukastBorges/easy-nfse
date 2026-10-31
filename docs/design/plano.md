# Plano de implantação da identidade visual

Como levar a [especificação](README.md) para o app em etapas pequenas, cada uma entregável e testável sozinha.
A ordem põe primeiro o que muda o app inteiro com pouca marcação (tokens e `@utility`) e deixa para depois o que
exige redesenhar cada tela.

## Decisões a tomar antes de começar

1. **Tema claro.** Os conceitos são só escuros, mas o app tem tema claro, escuro e "igual ao sistema". Proposta:
   manter os três, com o escuro como padrão, e criar um tema claro "papel" (fundo `papel`, texto `tinta`, vidro em
   verde translúcido, mesma mostarda). Na etapa 1 o tema claro recebe valores provisórios; o desenho dele é a etapa 7.
   A alternativa é remover o tema claro e o botão de tema, o que simplifica tudo mas muda um comportamento existente.
2. **Ícone de app e favicon.** A marca escolhida é só lettering e não cabe em 16 px. Proposta: o ponto quadrado
   mostarda com um "e" em `mata-0` dentro. Precisa de aprovação antes da etapa 8.
3. **Funcionalidades novas que aparecem nos conceitos** (fora do redesenho, cada uma no seu `feat`):
   resumo "Emitidas em outubro" na Início, resumo do mês e barras dos últimos 12 meses no Histórico, histórico
   agrupado por mês, e o valor em moeda estrangeira na lista do histórico. Podem entrar depois da etapa 6 ou ficar de fora.

## Andamento

| Etapa | Estado |
|---|---|
| 0, 1, 2 | Feitas no branch `feat/identidade-visual` |
| 3, 4 | Feitas (Início com boas-vindas e cards iguais; emissão na folha de papel) |
| 5 | Feita (Templates com a bandeja de importação; Cadastros com abas, chips e fichas; formulários e diálogo) |
| 6 | Feita (Histórico como livro-razão agrupado por mês; Configurações com cartões de ambiente, chave de TLS e régua de validade) |
| 7, 8 | A fazer |

## Etapa 0 — Fontes locais

O app roda sem internet (desktop empacotado) e hoje carrega a Inter do Google Fonts.

- `scripts/fontes.py`, no molde de `scripts/icones_tabler.py`: baixa Bricolage Grotesque e Public Sans variáveis
  (woff2, subconjunto latino) de uma versão fixada e grava em `static/vendor/fonts/` com as licenças OFL.
- `@font-face` em `base.html` apontando para `/static/vendor/fonts/`; remove o `<link>` do Google Fonts.
- Teste: as fontes referenciadas existem (no estilo de `test_icones_dos_templates_existem`).
- Conferir que o `.spec` já inclui (`collect_data_files("easy_nfse")` pega `static/`).

Commit: `build(ui): empacotar Bricolage Grotesque e Public Sans`.

## Etapa 1 — Tokens e utilitários

**Estratégia adotada:** em vez de trocar as classes de cor de todas as telas de uma vez, o `@theme` de `base.html`
**remapeia as paletas do Tailwind que as telas já usam** (`slate` vai do papel à mata, `indigo`/`violet`/`amber`
viram mostarda, `emerald` vira folha, `rose` vira barro, `sky` vira água). O app inteiro muda de cor sem editar
marcação; cada tela troca para as cores e variáveis definitivas na sua etapa. Os materiais que mudam com o tema
(vidro, campos, textos) são variáveis CSS (`--texto`, `--rotulo`, `--vidro-1`…) redefinidas em `[data-theme=dark]`.

O que estava previsto:

O maior salto visual com a menor mudança de marcação: as telas já usam `btn-primary`, `btn-ghost`, `card`, `input`,
`label`, `hint`, `menu-item`, `kv`, `section-title`.

- Em `base.html`, tokens semânticos como variáveis CSS que mudam com `data-theme` (`--cor-fundo`, `--cor-texto`,
  `--cor-texto-2`, `--cor-rotulo`, `--cor-acao`, `--cor-vidro`, `--cor-borda`, `--cor-sucesso`, `--cor-alerta`,
  `--cor-perigo`…), expostos ao Tailwind em `@theme` como cores (`bg-fundo`, `text-rotulo`, `border-borda`…).
  Assim uma classe serve aos dois temas e a regra "toda cor nova precisa do par `dark:`" deixa de valer para as
  cores semânticas. **Atualizar essa regra no `AGENTS.md` no mesmo commit.**
- Fundo da mesa (luz, vinheta, grão, fibras) em `body::before`/`::after` e um elemento fixo, com as texturas em
  `data:` URI.
- Redefinir os `@utility` existentes: `btn-primary` vira mostarda, `btn-ghost` vira vidro, `btn-success` some
  (mesclar com `btn-primary`), `card` vira vidro fosco, `input` com sombra interna e foco mostarda; novos
  `@utility`: `vidro`, `pill` (com variantes de estado), `papel`.
- `@supports not (backdrop-filter: blur(1px))`: vidro vira `mata-2` a 92 %, sem desfoque.
- Selects: a seta (`--chevron`) e `option` com as cores novas.

Riscos: classes de cor do Tailwind espalhadas nas telas (`text-slate-500`, `bg-indigo-50`…) continuam com as cores
antigas até as etapas 3 a 6; o app fica misto por um tempo. Fazer a etapa 1 e a 2 juntas no mesmo PR, se possível.

Commit: `feat(ui): adotar tokens e utilitários da identidade mata, mostarda e papel`.

## Etapa 2 — Moldura do app

`base.html` e o que aparece em todas as páginas.

- Cabeçalho: marca em lettering, selo de ambiente (mostarda em produção restrita; `barro` em produção), botão de
  tema e menu ⋮ em vidro.
- Transições entre páginas com View Transitions entre documentos (CSS em `base.html`, sem JavaScript): cabeçalho
  parado, conteúdo (`main`) saindo e entrando, e o realce do menu (`<span class="realce">` no item ativo, com
  `view-transition-name: realce`) deslizando de um item ao outro. Os itens do menu têm nomes próprios
  (`nav-1`…`nav-5`, classe `item-nav`) numa camada acima do realce, para ele passar por trás dos nomes.
  Itens de rotas aninhadas (emissão marca Início; `/templates/{id}/editar` marca Templates) seguem a regra de `base.html`.
- Diálogos `#confirmar`, `#cadastro`, notas de atualização e sobre: vidro mais opaco, `backdrop` com desfoque.
  Manter a altura definida do diálogo de Notas (armadilha do WKWebView no `AGENTS.md`).
- `_aviso_atualizacao.html`, `partials/atualizacao.html`, foco visível global, cursor.
- Celular: navegação só com ícones, como nos conceitos (390 px sem rolagem horizontal).

Commit: `feat(ui): redesenhar cabeçalho, menu e diálogos`.

## Etapa 3 — Início

`index.html`, `_checklist.html`, `_emissoes.html`.

- Boas-vindas (sem templates): o título com o texto atual, a nota anterior em papel com marca-texto nos campos que
  viram template e a ficha "Próximas notas" só com data e valor; os três passos (sequência real, numerada), o
  checklist "Antes de emitir" e as três garantias. Referência: `telas/08-boas-vindas-1440.jpg`.
- Cards de emissão em vidro, todos do mesmo tamanho (grade com `minmax(0, 1fr)` e `grid-auto-rows: 1fr`, botão com
  `margin-top: auto`), textos de uma linha com reticências e `title`, hover pela borda, valor em Bricolage e o estado
  do certificado no card. Atenção: a grade rola depois de 3 linhas (`data-max-linhas`); a medição de altura em
  `app.js` precisa continuar certa com linhas iguais.
- Busca e filtros (`data-filtro`) com o novo `input`; a mecânica de `data-max-linhas` não muda.
- Animação de entrada (`pousar`) só na carga da página.

Commit: `feat(ui): redesenhar a página inicial`.

## Etapa 4 — Emissão

`emitir.html` e as partials do fluxo (`revisao.html`, `sucesso.html`, `duplicada.html`, `erro.html`, `teste.html`).

- O formulário vira a folha de papel com o carimbo do ambiente; tomador, serviço e prestador em painéis de vidro ao
  lado; "Assinar e emitir" é o único botão mostarda.
- Revisão e sucesso: a nota emitida aparece como papel; erro da Sefin em aviso `barro` com o código (E0590 etc.).
- Conferir a troca de prestador/tomador só para a nota (`hx-vals`) e o botão da PTAX.

Commit: `feat(ui): redesenhar a emissão como folha de papel`.

## Etapa 5 — Templates e Cadastros

`templates.html`, `_importador.html`, `_template_linha.html`, `template_form.html`, `cadastros.html`,
`cadastro.html`, `_prestador_campos.html`, `_tomador_campos.html`, `partials/resumo_cadastro.html`,
`partials/cadastro_dialogo.html`.

- Importador como bandeja (borda tracejada, folha que se ergue); lista de templates em linhas dentro de um vidro.
- Cadastros com abas de ficha, chips de filtro com contagem, fichas em vidro com aviso de pendência.
- Formulários longos (template, cadastro) em seções de vidro com rótulos em `erva`.
- `test_certificados.py` confere trechos de marcação (`<span class="truncate">`); ajustar junto, se mudar.

Commits: `feat(ui): redesenhar templates e importador`, `feat(ui): redesenhar cadastros`.

## Etapa 6 — Histórico e Configurações

`historico.html`, `config.html`.

- Histórico como livro-razão: tabela dentro de um vidro, ações de PDF/XML/copiar à direita, selos de estado.
- Configurações: ambiente em cartões de rádio, chave de TLS, área de adicionar certificado tracejada, cada
  certificado com a régua de validade e a próxima DPS em destaque.

Commits: `feat(ui): redesenhar o histórico`, `feat(ui): redesenhar configurações e certificados`.

## Etapa 7 — Tema claro "papel"

Se a decisão 1 mantiver o tema claro: definir os valores claros dos tokens, desenhar o vidro sobre papel (verde
translúcido, sombra de tinta), conferir contraste AA de rótulos e selos, gerar referências claras em
`docs/design/telas/`.

Commit: `feat(tema): tema claro papel`.

## Etapa 8 — Marca fora do navegador

- `static/logo.svg`, `favicon.svg`, `apple-touch-icon.png`, `logo-512.png` e os ícones de `packaging/icons/`
  (`.icns`, `.ico`) com o símbolo aprovado.
- Novas capturas do README em `docs/screenshots/` (dados fictícios).
- O DANFSe (`danfse.py`) **não muda**: o leiaute segue a NT 008/2026.

Commit: `feat(ui): nova marca easyNFSe no ícone do app`.

## Como conferir cada etapa

- `uv run pytest -q` verde.
- Servidor isolado (`EASY_NFSE_NO_BROWSER=1 EASY_NFSE_PORT=8765 EASY_NFSE_DATA=/tmp/x uv run easy-nfse`) e
  capturas com Playwright em 1440 e 390 px, nos temas que existirem, comparando com `docs/design/telas/`.
- Janela nativa (`uv run --group desktop`): `backdrop-filter` e as texturas no WKWebView (macOS) e no WebView2
  (Windows), incluindo desempenho ao rolar listas longas. Se pesar, reduzir o desfoque ou tirar o grão do vidro.
- `prefers-reduced-motion` desliga as animações.
- Ícones novos: `uv run python scripts/icones_tabler.py`.

## Ordem sugerida de PRs

| PR | Etapas | Resultado |
|---|---|---|
| 1 | 0, 1, 2 | App inteiro com fundo, fontes, botões, cards e cabeçalho novos |
| 2 | 3, 4 | As duas telas mais usadas no visual final |
| 3 | 5 | Templates e cadastros |
| 4 | 6 | Histórico e configurações |
| 5 | 7, 8 | Tema claro e marca |
