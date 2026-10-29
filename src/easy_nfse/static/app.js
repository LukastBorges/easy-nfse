// Pequenos comportamentos de UI (o resto é htmx).

// Dropzone: arrastar e soltar um PDF/XML envia o formulário de importação.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-dropzone]").forEach((zone) => {
    const form = zone.closest("form");
    const input = zone.querySelector("input[type=file]");
    const send = () => input.files.length && htmx.trigger(form, "submit");
    ["dragenter", "dragover"].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); zone.dataset.over = "1"; })
    );
    ["dragleave", "drop"].forEach((ev) =>
      zone.addEventListener(ev, (e) => { e.preventDefault(); delete zone.dataset.over; })
    );
    zone.addEventListener("drop", (e) => { input.files = e.dataTransfer.files; send(); });
    input.addEventListener("change", send);
  });
});

// Lista filtrável: [data-filtro] com [data-filtro-busca] (texto), [data-filtro-estado] (select) e itens
// <li data-busca="..." data-estado="a b">. Mostra [data-filtro-vazio] quando nada sobra.
function filtrarLista(box) {
  const sem = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const termos = sem(box.querySelector("[data-filtro-busca]")?.value || "").split(/\s+/).filter(Boolean);
  const estado = box.querySelector("[data-filtro-estado]")?.value || "";
  const itens = [...box.querySelectorAll("[data-busca]")];
  let visiveis = 0;
  itens.forEach((li) => {
    const texto = sem(li.dataset.busca);
    const ok = termos.every((t) => texto.includes(t)) && (!estado || li.dataset.estado.split(" ").includes(estado));
    li.classList.toggle("hidden", !ok);
    visiveis += ok;
  });
  box.querySelector("[data-filtro-vazio]")?.classList.toggle("hidden", visiveis > 0);
  box.querySelectorAll("[data-max-linhas]").forEach(limitarLinhas);
  const contagem = box.querySelector("[data-filtro-contagem]");
  if (contagem) contagem.textContent = visiveis === itens.length ? "" : `${visiveis} de ${itens.length}`;
}
document.addEventListener("input", (e) => {
  const box = e.target.closest && e.target.closest("[data-filtro]");
  if (box && e.target.matches("[data-filtro-busca], [data-filtro-estado]")) filtrarLista(box);
});

// Grade com no máximo N linhas visíveis (data-max-linhas="N"); o resto rola. A altura depende das colunas
// e do tamanho dos cards, então é medida: vai até o início da linha N+1, deixando uma ponta dela à mostra.
function limitarLinhas(grade) {
  grade.style.maxHeight = "";
  const max = Number(grade.dataset.maxLinhas);
  const topos = [...new Set([...grade.children].filter((el) => el.offsetParent).map((el) => el.offsetTop))].sort((a, b) => a - b);
  if (topos.length > max) grade.style.maxHeight = `${topos[max] - topos[0] + 40}px`;
  marcarMais(grade);
}
// Esmaece a borda de baixo enquanto houver cards abaixo para rolar.
const marcarMais = (g) => g.toggleAttribute("data-mais", g.scrollTop + g.clientHeight < g.scrollHeight - 2);
document.addEventListener("scroll", (e) => e.target.matches?.("[data-max-linhas]") && marcarMais(e.target), true);
const limitarTodas = () => document.querySelectorAll("[data-max-linhas]").forEach(limitarLinhas);
document.addEventListener("DOMContentLoaded", limitarTodas);
addEventListener("load", limitarTodas); // depois das fontes, que mudam a altura dos cards
addEventListener("resize", limitarTodas);

// Campo de dinheiro: formata "1500" -> "1.500,00" ao sair do campo.
document.addEventListener("focusout", (e) => {
  const el = e.target;
  if (!el.matches || !el.matches("[data-money]")) return;
  let v = el.value.replace(/[^\d,.-]/g, "");
  if (!v) return;
  if (v.includes(",")) v = v.replace(/\./g, "").replace(",", ".");
  else if ((v.match(/\./g) || []).length > 1 || /^\d{1,3}\.\d{3}$/.test(v)) v = v.replace(/\./g, "");
  const n = Number(v);
  if (!isNaN(n)) el.value = n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});

// Mostrar/ocultar blocos controlados por checkbox (ex.: tomador).
document.addEventListener("change", (e) => {
  const el = e.target;
  if (el.matches && el.matches("[data-toggle]")) {
    document.querySelectorAll(el.dataset.toggle).forEach((t) => t.classList.toggle("hidden", !el.checked));
  }
});

// Copiar para a área de transferência.
document.addEventListener("click", (e) => {
  const btn = e.target.closest && e.target.closest("[data-copy]");
  if (!btn) return;
  navigator.clipboard.writeText(btn.dataset.copy);
  const old = btn.innerHTML;
  btn.textContent = "Copiado!";
  setTimeout(() => (btn.innerHTML = old), 1200);
});

// Campos condicionais: data-show-if="campo:v1|v2;outro:v3" (mostra se QUALQUER condição valer).
function atualizarCondicionais(root = document) {
  root.querySelectorAll("[data-show-if]").forEach((el) => {
    const form = el.closest("form") || document;
    const visivel = el.dataset.showIf.split(";").some((cond) => {
      const [nome, valores] = cond.split(":");
      const campo = form.querySelector(`[name="${nome}"]`);
      return campo && valores.split("|").includes(campo.value);
    });
    el.classList.toggle("hidden", !visivel);
  });
}
document.addEventListener("DOMContentLoaded", () => atualizarCondicionais());
document.addEventListener("change", () => atualizarCondicionais());
document.addEventListener("htmx:afterSwap", (e) => atualizarCondicionais(e.target));

// Exportação: converte o valor em moeda estrangeira para R$ pela PTAX.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest && e.target.closest("[data-ptax]");
  if (!btn) return;
  const form = btn.closest("form");
  const moeda = form.querySelector("[name=valor_moeda]");
  const brl = form.querySelector("[name=valor]");
  const data = form.querySelector("[name=competencia]").value;
  const info = form.querySelector("[data-ptax-info]");
  const toNum = (v) => Number(v.includes(",") ? v.replace(/\./g, "").replace(",", ".") : v);
  const valor = toNum(moeda.value.replace(/[^\d,.]/g, ""));
  if (!valor) { info.textContent = "Informe primeiro o valor na moeda."; return; }
  info.textContent = "Consultando PTAX…";
  const r = await fetch(`/cotacao?moeda=${btn.dataset.ptax}&data=${data}`).then((r) => r.json());
  if (r.erro) { info.textContent = r.erro; return; }
  const total = Math.round(valor * Number(r.taxa) * 100) / 100;
  brl.value = total.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  info.textContent = `PTAX venda ${r.moeda} de ${r.data_br}: ${Number(r.taxa).toLocaleString("pt-BR", { minimumFractionDigits: 4 })}. Confira com seu contador qual taxa usar.`;
});

// Tema: sistema -> claro -> escuro (preferência guardada só neste navegador).
(() => {
  const html = document.documentElement;
  const media = matchMedia("(prefers-color-scheme: dark)");
  const nomes = { sistema: "Tema: igual ao sistema", claro: "Tema: claro", escuro: "Tema: escuro" };
  const aplicar = (pref) => {
    html.dataset.tema = pref;
    html.dataset.theme = pref === "escuro" || (pref === "sistema" && media.matches) ? "dark" : "light";
    const btn = document.getElementById("tema-btn");
    if (btn) btn.title = nomes[pref] + " (clique para alternar)";
  };
  media.addEventListener("change", () => html.dataset.tema === "sistema" && aplicar("sistema"));
  document.addEventListener("DOMContentLoaded", () => aplicar(html.dataset.tema || "sistema"));
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#tema-btn")) return;
    const ordem = ["sistema", "claro", "escuro"];
    const prox = ordem[(ordem.indexOf(html.dataset.tema) + 1) % ordem.length];
    try { localStorage.setItem("tema", prox); } catch {}
    aplicar(prox);
  });
})();

// Diálogo de confirmação próprio (substitui o confirm() do navegador).
// Uso: hx-confirm="texto" (htmx) ou data-confirm="texto" (botões de formulário comuns);
// opcionais: data-confirm-titulo, data-confirm-acao, data-confirm-perigo.
function confirmar(texto, opcoes = {}) {
  const dlg = document.getElementById("confirmar");
  if (!dlg || !dlg.showModal) return Promise.resolve(window.confirm(texto));
  dlg.querySelector("#confirmar-titulo").textContent = opcoes.titulo || "Confirmar";
  dlg.querySelector("#confirmar-texto").textContent = texto;
  const ok = dlg.querySelector("#confirmar-ok");
  ok.textContent = opcoes.acao || "Confirmar";
  ok.className = opcoes.perigo ? "btn bg-rose-600 text-white shadow-sm hover:bg-rose-500" : "btn-primary";
  dlg.querySelector("[data-icone-perigo]").classList.toggle("hidden", !opcoes.perigo);
  dlg.returnValue = "";
  dlg.showModal();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true }));
}
const opcoesDe = (el) => ({
  titulo: el.dataset.confirmTitulo, acao: el.dataset.confirmAcao, perigo: "confirmPerigo" in el.dataset,
});
document.addEventListener("htmx:confirm", (e) => {
  if (!e.detail.question) return;
  e.preventDefault();
  confirmar(e.detail.question, opcoesDe(e.detail.elt)).then((sim) => sim && e.detail.issueRequest(true));
});
document.addEventListener("click", (e) => {
  const btn = e.target.closest && e.target.closest("[data-confirm]");
  if (!btn || btn.dataset.confirmado) return;
  e.preventDefault();
  confirmar(btn.dataset.confirm, opcoesDe(btn)).then((sim) => {
    if (!sim) return;
    btn.dataset.confirmado = "1";
    btn.click();
    delete btn.dataset.confirmado;
  });
});

// Menu do cabeçalho (⋮): abre/fecha no botão; fecha com clique fora, Esc ou ao escolher um item.
function fecharMenus(exceto) {
  document.querySelectorAll("[data-menu]").forEach((m) => {
    if (m === exceto) return;
    m.querySelector("[role=menu]").hidden = true;
    m.querySelector("[data-menu-botao]").setAttribute("aria-expanded", "false");
  });
}
document.addEventListener("click", (e) => {
  const botao = e.target.closest && e.target.closest("[data-menu-botao]");
  if (!botao) return fecharMenus();
  const menu = botao.closest("[data-menu]");
  const lista = menu.querySelector("[role=menu]");
  fecharMenus(menu);
  lista.hidden = !lista.hidden;
  botao.setAttribute("aria-expanded", String(!lista.hidden));
  if (!lista.hidden) lista.querySelector("[role=menuitem]").focus();
});
document.addEventListener("keydown", (e) => {
  const lista = document.activeElement && document.activeElement.closest("[role=menu]");
  if (e.key === "Escape" && lista) {
    fecharMenus();
    lista.closest("[data-menu]").querySelector("[data-menu-botao]").focus();
  } else if (lista && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    const itens = [...lista.querySelectorAll("[role=menuitem]")];
    const i = itens.indexOf(document.activeElement) + (e.key === "ArrowDown" ? 1 : -1);
    itens[(i + itens.length) % itens.length].focus();
  }
});

// Diálogo "Sobre" (versão e atualizações).
document.addEventListener("click", (e) => {
  const item = e.target.closest && e.target.closest("[data-abrir-sobre]");
  if (!item) return;
  const dlg = document.getElementById("sobre");
  dlg.showModal();
});
document.getElementById("sobre")?.addEventListener("click", (e) => {
  if (e.target.id === "sobre") e.target.close(); // clique no fundo fecha
});

// Notas de atualização: abre o diálogo e carrega o changelog (só quando pedido).
document.addEventListener("click", (e) => {
  const item = e.target.closest && e.target.closest("[data-abrir-notas]");
  if (!item) return;
  document.getElementById("sobre")?.close();
  const dlg = document.getElementById("notas");
  dlg.querySelector("#notas-conteudo").innerHTML = '<p class="py-6 text-center text-sm text-slate-500 dark:text-slate-400">Carregando…</p>';
  dlg.showModal();
  htmx.ajax("GET", "/notas", "#notas-conteudo");
});

// Campos que salvam sozinhos (data-salva-sozinho + hx-post): se a gravação falhar, desfaz a mudança e avisa,
// em vez de deixar parecer que salvou.
function falhaAoSalvar(e) {
  const el = e.detail.elt;
  if (!el.matches || !el.matches("[data-salva-sozinho]")) return;
  if (el.type === "checkbox") el.checked = !el.checked;
  const alvo = document.querySelector(el.getAttribute("hx-target"));
  if (alvo) alvo.innerHTML = '<span class="text-rose-700 dark:text-rose-300">Não foi possível salvar. Feche e abra o easy-nfse e tente de novo.</span>';
}
document.addEventListener("htmx:responseError", falhaAoSalvar);
document.addEventListener("htmx:sendError", falhaAoSalvar);
