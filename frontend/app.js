const state = { products: [], productId: "", action: "entry", query: "", toastTimer: null, editingProductId: "" };
const numberFormat = new Intl.NumberFormat("pt-BR");
const formatNumber = (value) => numberFormat.format(value ?? 0);
const ui = {
  headerActions: document.querySelector(".header-actions"),
  search: document.querySelector("#product-search"),
  productRows: document.querySelector("#product-rows"),
  productCount: document.querySelector("#product-count"),
  quantity: document.querySelector("#quantity-input"),
  reference: document.querySelector("#reference-input"),
  referenceField: document.querySelector("#reference-field"),
  form: document.querySelector("#movement-form"),
  list: document.querySelector("#commitment-list"),
  dialog: document.querySelector("#create-dialog"),
  createForm: document.querySelector("#create-form"),
  productId: document.querySelector("#product-id-input"),
  productName: document.querySelector("#product-name-input"),
  toast: document.querySelector("#toast"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail || `Erro ao acessar o estoque (${response.status}).`);
  return data;
}

function notify(message, isError = false) {
  clearTimeout(state.toastTimer);
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", isError);
  ui.toast.classList.add("visible");
  state.toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 3200);
}

function updateSummary() {
  const totals = state.products.reduce((sum, product) => ({
    total: sum.total + product.total,
    available: sum.available + product.available,
    reserved: sum.reserved + product.reserved,
    blocked: sum.blocked + product.blocked,
  }), { total: 0, available: 0, reserved: 0, blocked: 0 });
  animateMetric("metric-products", state.products.length);
  animateMetric("metric-total", totals.total);
  animateMetric("metric-available", totals.available);
  animateMetric("metric-reserved", totals.reserved);
  animateMetric("metric-blocked", totals.blocked);
}

function animateMetric(id, target) {
  const element = document.getElementById(id);
  const previousTarget = Number(element.dataset.value || 0);
  if (previousTarget === target) return;
  const run = Number(element.dataset.run || 0) + 1;
  element.dataset.run = String(run);
  element.dataset.value = String(target);
  const start = previousTarget;
  const duration = 520;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    element.textContent = formatNumber(target);
    return;
  }
  const startedAt = performance.now();
  function step(now) {
    if (Number(element.dataset.run) !== run) return;
    const progress = Math.min(1, (now - startedAt) / duration);
    const eased = 1 - (1 - progress) ** 3;
    element.textContent = formatNumber(Math.round(start + (target - start) * eased));
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function renderProducts() {
  ui.productRows.replaceChildren();
  ui.productCount.textContent = `${formatNumber(state.products.length)} ${state.products.length === 1 ? "produto" : "produtos"}`;
  updateSummary();

  const query = state.query.trim().toLocaleLowerCase("pt-BR");
  const visible = state.products.filter((product) =>
    `${product.name} ${product.product_id}`.toLocaleLowerCase("pt-BR").includes(query));
  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty-cell";
    cell.textContent = state.products.length ? "Nenhum produto encontrado." : "Nenhum produto cadastrado. Use “Novo produto” para começar.";
    row.append(cell);
    ui.productRows.append(row);
    return;
  }

  visible.forEach((product, index) => {
    const row = document.createElement("tr");
    row.className = "product-row";
    row.style.setProperty("--row-order", String(Math.min(index, 10)));
    row.classList.toggle("selected", product.product_id === state.productId);
    row.tabIndex = 0;
    row.setAttribute("aria-selected", String(product.product_id === state.productId));
    row.setAttribute("aria-label", `Selecionar ${product.name} para movimentação`);
    row.addEventListener("click", () => selectProduct(product.product_id));
    row.addEventListener("keydown", (event) => {
      if (event.target === row && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        selectProduct(product.product_id);
      }
    });
    const identity = document.createElement("td");
    identity.className = "product-identity";
    const name = document.createElement("strong");
    name.textContent = product.name;
    const code = document.createElement("small");
    code.textContent = product.product_id;
    identity.append(name, code);
    const total = document.createElement("td");
    total.textContent = formatNumber(product.total);
    const available = document.createElement("td");
    available.className = "available-cell";
    const availableNumber = document.createElement("strong");
    availableNumber.className = "available-number";
    availableNumber.textContent = formatNumber(product.available);
    const bar = document.createElement("span");
    bar.className = "availability-track";
    const fill = document.createElement("span");
    const ratio = product.total > 0 ? product.available / product.total : 0;
    fill.className = `availability-fill ${ratio === 0 ? "empty" : ratio < 0.25 ? "low" : ""}`.trim();
    fill.style.width = `${Math.max(0, Math.min(100, ratio * 100))}%`;
    bar.append(fill);
    available.append(availableNumber, bar);
    const reserved = document.createElement("td");
    reserved.textContent = formatNumber(product.reserved);
    const blocked = document.createElement("td");
    blocked.textContent = formatNumber(product.blocked);
    const action = document.createElement("td");
    action.className = "product-actions-cell";
    const actions = document.createElement("div");
    actions.className = "product-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "row-action edit-product";
    edit.title = "Editar produto";
    edit.setAttribute("aria-label", `Editar ${product.name}`);
    edit.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5 5 5M4 20l4.3-.9L19 8.4a2.1 2.1 0 0 0-3-3L5.3 16.1 4 20Z"/></svg>';
    edit.addEventListener("click", (event) => {
      event.stopPropagation();
      openProductDialog(product);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "row-action delete-product";
    remove.title = "Excluir produto";
    remove.setAttribute("aria-label", `Excluir ${product.name}`);
    remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg>';
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteProduct(product);
    });
    actions.append(edit, remove);
    action.append(actions);
    row.append(identity, total, available, reserved, blocked, action);
    ui.productRows.append(row);
  });
}

function renderCommitments(records) {
  ui.list.replaceChildren();
  document.querySelector("#commitment-count").textContent = `${records.length} ${records.length === 1 ? "registro" : "registros"}`;
  const selectedProduct = state.products.find((product) => product.product_id === state.productId);
  document.querySelector("#commitment-product").textContent = selectedProduct
    ? `${selectedProduct.name} · ${selectedProduct.product_id}`
    : "Selecione um produto";
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = state.productId ? "Nenhuma reserva ou bloqueio para este produto." : "Selecione um produto na tabela para consultar os registros.";
    ui.list.append(empty);
    return;
  }

  for (const record of records) {
    const row = document.createElement("div");
    row.className = "commitment-row";
    const reference = document.createElement("span");
    reference.className = "commitment-reference";
    reference.textContent = record.reference;
    reference.title = record.reference;
    const type = document.createElement("span");
    type.className = "commitment-type";
    type.textContent = record.kind === "block" ? "Bloqueio" : "Reserva";
    const quantity = document.createElement("span");
    quantity.className = "commitment-quantity";
    quantity.textContent = `${formatNumber(record.quantity)} un.`;
    const actions = document.createElement("div");
    actions.className = "commitment-actions";

    const idButton = document.createElement("button");
    idButton.className = "mini-button";
    idButton.type = "button";
    idButton.textContent = "ID";
    idButton.title = `Copiar identificador: ${record.commitment_id}`;
    idButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(record.commitment_id);
        notify("Identificador copiado.");
      } catch {
        notify(`ID: ${record.commitment_id}`);
      }
    });
    actions.append(idButton);
    if (record.released) {
      const status = document.createElement("span");
      status.className = "commitment-state";
      status.textContent = "Liberado";
      actions.append(status);
    } else {
      const release = document.createElement("button");
      release.className = "mini-button release";
      release.type = "button";
      release.textContent = "Liberar";
      release.addEventListener("click", () => releaseRecord(record));
      actions.append(release);
    }
    row.append(reference, type, quantity, actions);
    ui.list.append(row);
  }
}

async function loadProducts(preferredId = state.productId) {
  state.products = await request("/products");
  state.productId = state.products.some((product) => product.product_id === preferredId)
    ? preferredId
    : state.products[0]?.product_id || "";
  renderProducts();
  const selected = state.products.find((product) => product.product_id === state.productId);
  document.querySelector("#selected-product").textContent = selected ? `Produto: ${selected.name} · ${selected.product_id}` : "Selecione um produto na lista";
  document.querySelector(".submit-button").disabled = !state.productId;
  await loadCommitments();
}

async function loadCommitments() {
  if (!state.productId) return renderCommitments([]);
  renderCommitments(await request(`/products/${encodeURIComponent(state.productId)}/commitments`));
}

async function selectProduct(productId) {
  state.productId = productId;
  renderProducts();
  const selected = state.products.find((product) => product.product_id === productId);
  document.querySelector("#selected-product").textContent = selected
    ? `Produto: ${selected.name} · ${selected.product_id}`
    : "Selecione um produto na lista";
  document.querySelector(".submit-button").disabled = false;
  try {
    await loadCommitments();
    document.querySelector("#movement-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    notify(error.message, true);
  }
}

function changeAction(action) {
  state.action = action;
  const needsReference = action === "reservation" || action === "block";
  ui.referenceField.hidden = !needsReference;
  ui.reference.required = needsReference;
  document.querySelector("#reference-label").textContent = action === "block" ? "Motivo / referência" : "Pedido / referência";
  ui.reference.placeholder = action === "block" ? "Ex.: avaria-01" : "Ex.: pedido-123";
}

async function submitMovement(event) {
  event.preventDefault();
  if (!state.productId) return notify("Selecione um produto na tabela.", true);
  const quantity = Number(ui.quantity.value);
  if (!Number.isInteger(quantity) || quantity < 1) return notify("Informe uma quantidade inteira positiva.", true);
  const button = document.querySelector(".submit-button");
  button.disabled = true;
  try {
    const route = { entry: "entries", withdrawal: "withdrawals", reservation: "reservations", block: "blocks" }[state.action];
    const body = { quantity };
    if (state.action === "reservation" || state.action === "block") body.reference = ui.reference.value.trim();
    await request(`/products/${encodeURIComponent(state.productId)}/${route}`, { method: "POST", body: JSON.stringify(body) });
    notify("Movimentação registrada.");
    ui.quantity.value = "1";
    ui.reference.value = "";
    await loadProducts(state.productId);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = !state.productId;
  }
}

async function releaseRecord(record) {
  const confirmed = await showConfirmation({
    title: "Liberar este registro?",
    message: `As ${formatNumber(record.quantity)} unidades de “${record.reference}” voltarão ao saldo disponível.`,
    confirmLabel: "Liberar unidades",
  });
  if (!confirmed) return;
  try {
    await request(`/commitments/${encodeURIComponent(record.commitment_id)}/release`, { method: "POST" });
    notify("Registro liberado.");
    await loadProducts(state.productId);
  } catch (error) {
    notify(error.message, true);
  }
}

async function createProduct(event) {
  event.preventDefault();
  const id = ui.productId.value.trim();
  const name = ui.productName.value.trim();
  if (!id || !name) return;
  const button = ui.createForm.querySelector("[type=submit]");
  button.disabled = true;
  try {
    const body = JSON.stringify({ product_id: id, name });
    const editing = Boolean(state.editingProductId);
    if (editing) {
      await request(`/products/${encodeURIComponent(state.editingProductId)}`, { method: "PATCH", body });
    } else {
      await request("/products", { method: "POST", body });
    }
    ui.dialog.close();
    ui.createForm.reset();
    state.editingProductId = "";
    await loadProducts(id);
    notify(editing ? "Produto atualizado." : "Produto cadastrado. Registre uma entrada para adicionar unidades.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function openProductDialog(product = null) {
  state.editingProductId = product?.product_id || "";
  ui.createForm.reset();
  document.querySelector("#create-title").textContent = product ? "Editar produto" : "Adicionar produto";
  document.querySelector("#create-description").textContent = product
    ? "Atualize o nome ou a identificação do item."
    : "Cadastre o produto para acompanhar seus saldos.";
  document.querySelector("#product-submit").firstChild.textContent = product ? "Salvar alterações " : "Cadastrar ";
  const dialogNote = document.querySelector("#product-dialog-note");
  dialogNote.parentElement.hidden = !product;
  dialogNote.textContent = "Se alterar o código, as reservas e os bloqueios continuarão vinculados ao produto.";
  ui.productId.value = product?.product_id || "";
  ui.productName.value = product?.name || "";
  ui.dialog.showModal();
  ui.productId.focus();
}

async function deleteProduct(product) {
  const message = product.total > 0
    ? `“${product.name}” tem ${formatNumber(product.total)} ${product.total === 1 ? "unidade" : "unidades"}. Ao continuar, o produto, o saldo e todas as reservas e bloqueios associados serão excluídos. Essa ação não pode ser desfeita.`
    : `“${product.name}” (${product.product_id}) e todos os registros associados serão excluídos. Essa ação não pode ser desfeita.`;
  const confirmed = await showConfirmation({
    title: "Deseja excluir mesmo assim?",
    message,
    confirmLabel: "SIM",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await request(`/products/${encodeURIComponent(product.product_id)}`, { method: "DELETE" });
    if (state.productId === product.product_id) state.productId = "";
    await loadProducts();
    notify("Produto excluído.");
  } catch (error) {
    notify(error.message, true);
  }
}

function showConfirmation({ title, message, confirmLabel = "Confirmar", danger = false }) {
  const dialog = document.querySelector("#confirm-dialog");
  dialog.classList.toggle("danger", danger);
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-message").textContent = message;
  document.querySelector("#confirm-accept").textContent = confirmLabel;
  dialog.showModal();
  document.querySelector("#confirm-cancel").focus();
  return new Promise((resolve) => { state.confirmResolve = resolve; });
}

function showTab(tab) {
  const isCase = tab === "case";
  document.querySelector("#stock-view").hidden = isCase;
  document.querySelector("#case-view").hidden = !isCase;
  ui.headerActions.hidden = isCase;
  document.querySelector("#tab-stock").classList.toggle("active", !isCase);
  document.querySelector("#tab-stock").setAttribute("aria-selected", String(!isCase));
  document.querySelector("#tab-case").classList.toggle("active", isCase);
  document.querySelector("#tab-case").setAttribute("aria-selected", String(isCase));
}

function initialize() {
  ui.search.addEventListener("input", () => {
    state.query = ui.search.value;
    renderProducts();
  });
  ui.form.addEventListener("submit", submitMovement);
  document.querySelector("#action-picker").addEventListener("change", (event) => changeAction(event.target.value));
  document.querySelector("#open-create").addEventListener("click", () => openProductDialog());
  document.querySelector("#close-create").addEventListener("click", () => ui.dialog.close());
  document.querySelector("#cancel-create").addEventListener("click", () => ui.dialog.close());
  ui.createForm.addEventListener("submit", createProduct);
  document.querySelector("#tab-stock").addEventListener("click", () => showTab("stock"));
  document.querySelector("#tab-case").addEventListener("click", () => showTab("case"));
  ui.dialog.addEventListener("click", (event) => { if (event.target === ui.dialog) ui.dialog.close(); });
  const confirmDialog = document.querySelector("#confirm-dialog");
  document.querySelector("#confirm-accept").addEventListener("click", () => confirmDialog.close("confirm"));
  document.querySelector("#confirm-cancel").addEventListener("click", () => confirmDialog.close("cancel"));
  document.querySelector("#confirm-close").addEventListener("click", () => confirmDialog.close("cancel"));
  confirmDialog.addEventListener("click", (event) => { if (event.target === confirmDialog) confirmDialog.close("cancel"); });
  confirmDialog.addEventListener("close", () => {
    const resolve = state.confirmResolve;
    state.confirmResolve = null;
    resolve?.(confirmDialog.returnValue === "confirm");
  });
  changeAction("entry");
  loadProducts().catch((error) => notify(`Falha ao carregar estoque: ${error.message}`, true));
}

initialize();
