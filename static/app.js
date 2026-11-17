"use strict";

const $ = id => document.getElementById(id);
const names = {catalogue: "Catalogue", orders: "Orders", support: "Support", staff: "Staff desk"};
const starters = ["track_order", "policy_question", "request_return"];
const state = {session: null, view: "catalogue", busy: false, stage: "menu", selected: new Set(), pending: null};

function element(tag, value, className) {
  const entry = document.createElement(tag);
  if (value !== undefined) entry.textContent = value;
  if (className) entry.className = className;
  return entry;
}

function button(label, onClick, cls = "outline") {
  const entry = element("button", label, cls);
  entry.type = "button";
  entry.addEventListener("click", onClick);
  return entry;
}

function error(id, message) {
  const target = $(id);
  target.textContent = message || "";
  target.hidden = !message;
}

async function api(url, payload) {
  const response = await fetch(url, payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const problem = new Error(data.error || "The local request failed.");
    problem.status = response.status;
    throw problem;
  }
  return data;
}

function dataRows(target, entries) {
  const list = element("dl", undefined, "response-data");
  for (const [key, value] of entries) {
    const row = element("div");
    row.append(element("dt", key), element("dd", String(value)));
    list.append(row);
  }
  target.append(list);
}

function selectedStore() {
  return state.session.stores.find(store => store.id === state.session.tenant);
}

function setIdentity() {
  const {role, user} = state.session;
  const labels = {guest: "Guest", customer: "Verified customer", agent: "Support agent", admin: "Tenant admin"};
  $("identity").textContent = labels[role];
  $("assistant-status").textContent = role === "customer" ? `Verified · ${user}` : selectedStore().name;
}

function updateButtons() {
  $("message").disabled = state.busy || !state.session;
  $("send").disabled = $("message").disabled;
  $("new-chat").disabled = state.busy;
  $("retry-chat").disabled = state.busy;
  $("choices").querySelectorAll("button").forEach(entry => { entry.disabled = state.busy; });
  $("stores").querySelectorAll("button").forEach(entry => { entry.disabled = state.busy; });
}

function focusAssistant() {
  $("assistant").focus({preventScroll: true});
  $("assistant").scrollIntoView({block: "nearest", behavior: "smooth"});
}

function productText(product) {
  const copy = element("div", undefined, "product-copy");
  copy.append(element("p", `${product.category} · ${product.sku}`), element("h3", product.title),
    element("p", product.description, "description"));
  const footer = element("div", undefined, "product-foot");
  footer.append(element("strong", product.price_label),
    element("span", product.availability, "stock" + (product.stock ? "" : " empty")));
  copy.append(footer);
  return copy;
}

function appendMessage(speaker, reply) {
  const message = element("article", undefined, "bubble" + (speaker === "You" ? " user" : ""));
  message.append(element("span", speaker, "byline"));
  if (reply.title) message.append(element("h3", reply.title));
  message.append(element("p", reply.message));
  if (reply.rows?.length) dataRows(message, reply.rows);
  if (reply.citation) {
    const {title, source, version, effective} = reply.citation;
    message.append(element("p", `${title} · ${source} · v${version} · Effective ${effective}`, "citation"));
  }
  reply.products?.forEach(product => message.append(productText(product)));
  $("conversation").append(message);
  while ($("conversation").children.length > 120) $("conversation").firstChild.remove();
  $("conversation").scrollTop = $("conversation").scrollHeight;
}

function options(reply = {stage: "menu", options: []}) {
  const target = $("choices");
  target.replaceChildren();
  const list = reply.options.length ? reply.options : reply.stage === "menu" ? starters.map(task => state.session.services[task]) : [];
  for (const label of list) {
    const shortcut = reply.stage === "menu" ? Object.keys(state.session.services).find(key => state.session.services[key] === label) : undefined;
    target.append(button(label, () => send(label, shortcut), "outline" + (label === "Confirm" ? " confirm" : "")));
  }
  if (reply.stage !== "menu" && !list.includes("Cancel draft")) target.append(button("Cancel draft", () => send("Cancel draft")));
  $("message").placeholder = reply.stage === "otp" ? "Enter the verification code" : "Ask about this store";
  $("message").inputMode = reply.stage === "otp" ? "numeric" : "text";
  updateButtons();
}

async function inbox() {
  const panel = $("inbox");
  panel.hidden = state.stage !== "otp";
  if (panel.hidden) return;
  const origin = state.session;
  try {
    const data = await api("/api/inbox");
    if (origin !== state.session || state.stage !== "otp") return;
    const use = $("use-code");
    use.hidden = !data.code;
    use.textContent = data.code || "";
    use.disabled = state.busy;
    $("inbox-note").textContent = data.code ? `${data.seconds}s remaining` : "Waiting for a matching demo profile";
  } catch (problem) {
    $("inbox-note").textContent = problem.message;
  }
}

async function send(text, shortcut, retry = false) {
  if (!text.trim() || !state.session || state.busy) return;
  state.busy = true;
  updateButtons();
  error("chat-error");
  $("retry-chat").hidden = true;
  if (!retry) state.pending = {text, shortcut, request_id: crypto.randomUUID()};
  try {
    const reply = await api("/api/chat", state.pending);
    state.pending = null;
    $("message").value = "";
    appendMessage("You", {message: reply.echo});
    appendMessage("Assistant", reply);
    state.stage = reply.stage;
    options(reply);
    if (reply.verified && state.session.role !== "customer" || !reply.verified && state.session.role === "customer") {
      state.session = await api("/api/session");
      setIdentity();
    }
    if (state.view === "orders" && (reply.verified || reply.event === "verification_expired")) await orders();
  } catch (problem) {
    error("chat-error", problem.message);
    if (state.pending && (!problem.status || problem.status >= 500)) $("retry-chat").hidden = false;
    else state.pending = null;
  } finally {
    state.busy = false;
    updateButtons();
    inbox();
  }
}

function startTask(task) {
  focusAssistant();
  return send(state.session.services[task], task);
}

function updateComparison() {
  $("compare-tools").hidden = state.selected.size === 0;
  $("compare-count").textContent = `${state.selected.size} of 2 selected`;
  $("compare").disabled = state.selected.size !== 2;
  $("products").querySelectorAll("input[type=checkbox]").forEach(input => {
    input.disabled = state.selected.size === 2 && !input.checked;
  });
}

async function catalogue(resetFacets = false) {
  if (!state.session) return;
  const from = state.session.tenant;
  const query = new URLSearchParams({q: $("query").value, category: $("category").value, brand: $("brand").value,
    max: $("maximum").value, available: $("available").checked ? "1" : "0"});
  error("catalogue-error");
  try {
    const data = await api(`/api/catalogue?${query}`);
    if (state.session.tenant !== from) return;
    const target = $("products");
    target.replaceChildren();
    if (resetFacets) {
      for (const [id, prop] of [["category", "category"], ["brand", "brand"]]) {
        for (const name of [...new Set(data.products.map(product => product[prop]))].sort()) {
          const option = element("option", name);
          option.value = name;
          $(id).append(option);
        }
      }
    }
    $("product-count").textContent = `${data.products.length} ${data.products.length === 1 ? "product" : "products"}`;
    for (const product of data.products) {
      const card = element("article", undefined, "product-card");
      const visual = element("div", undefined, `product-visual ${product.illustration}`);
      visual.setAttribute("aria-hidden", "true");
      const copy = productText(product);
      const pick = element("label", undefined, "product-check");
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selected.has(product.sku);
      checkbox.setAttribute("aria-label", `Compare ${product.title}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selected.add(product.sku);
        else state.selected.delete(product.sku);
        updateComparison();
      });
      pick.append(checkbox, element("span", "Compare"));
      copy.append(pick);
      card.append(visual, copy);
      target.append(card);
    }
    if (!data.products.length) target.append(element("p", "Try a different search or update the filters.", "guidance"));
    updateComparison();
  } catch (problem) {
    error("catalogue-error", problem.message);
  }
}

async function orders() {
  const target = $("orders");
  target.replaceChildren();
  $("order-help").textContent = "Verify a demo profile in the assistant to see its orders.";
  if (state.session.role !== "customer") return;
  try {
    const data = await api("/api/orders");
    $("order-help").textContent = "Choose an order to open its latest record in the assistant.";
    for (const order of data.orders) {
      const item = element("div", undefined, "record");
      item.append(element("strong", order.ref), element("p", `${order.state} · ${order.total_label}`),
        button("View", async () => {
          await startTask("track_order");
          if (state.stage === "order") send(order.ref);
        }));
      target.append(item);
    }
  } catch (problem) {
    $("order-help").textContent = problem.message;
  }
}

async function staffAction(action, reference, message) {
  error("staff-error");
  try {
    await api("/api/staff/action", {action, reference, message, request_id: crypto.randomUUID()});
    await staff();
    await ticket(reference);
  } catch (problem) {
    error("staff-error", problem.message);
  }
}

async function ticket(reference) {
  error("staff-error");
  try {
    const data = await api(`/api/staff/ticket?ref=${encodeURIComponent(reference)}`);
    const detail = $("ticket-detail");
    detail.hidden = false;
    detail.replaceChildren(element("h3", data.ref), element("p", `${data.category} · ${data.status}`),
      element("p", data.summary));
    if (data.order_ref) detail.append(element("p", `Related order ${data.order_ref}`));
    if (data.messages.length) dataRows(detail, data.messages.map(note => [note.actor, note.body]));
    if (data.status !== "Resolved") {
      const form = element("form", undefined, "staff-reply");
      const input = element("input");
      input.placeholder = "Write a reply";
      input.setAttribute("aria-label", "Staff reply");
      input.maxLength = 240;
      input.required = true;
      const submit = element("button", "Send reply", "ink-button");
      form.append(input, submit);
      form.addEventListener("submit", event => { event.preventDefault(); staffAction("reply", reference, input.value); });
      detail.append(form, button("Resolve ticket", () => staffAction("resolve", reference)));
    }
  } catch (problem) {
    error("staff-error", problem.message);
  }
}

async function staff() {
  const role = state.session.role;
  const valid = role === "agent" || role === "admin";
  $("staff-login").hidden = valid;
  $("staff-controls").hidden = !valid;
  $("staff-hint").textContent = `Agent ${state.session.tenant}.agent · PIN 2411. Admin ${state.session.tenant}.admin · PIN 2419.`;
  $("metrics").hidden = role !== "admin";
  if (!valid) return;
  try {
    const {tickets} = await api("/api/staff/queue");
    const queue = $("queue");
    queue.replaceChildren();
    if (!tickets.length) queue.append(element("p", "No tickets in this store’s queue.", "guidance"));
    for (const entry of tickets) {
      const record = element("div", undefined, "record");
      record.append(element("strong", entry.ref), element("p", `${entry.category} · ${entry.status}`));
      const actions = element("div");
      if (!entry.assigned && entry.status !== "Resolved") actions.append(button("Claim", () => staffAction("claim", entry.ref)));
      if (entry.assigned === state.session.user || role === "admin") actions.append(button("Open", () => ticket(entry.ref)));
      record.append(actions);
      queue.append(record);
    }
    if (role === "admin") {
      const m = await api("/api/staff/metrics");
      const metrics = $("metric-values");
      metrics.replaceChildren();
      dataRows(metrics, [["Conversations", m.conversations], ["Chat turns", m.chat_turns],
        ["Workflows completed / started", `${m.workflow_completions} / ${m.workflow_starts}`],
        ["Fallback turns / all turns", `${m.fallback_turns} / ${m.chat_turns}`],
        ["New handoffs", m.handoff_created], ["Provider errors", m.provider_errors],
        ["Turn p95", m.p95_ms === null ? "No turns yet" : `${m.p95_ms} ms`],
        ["Ticket states", Object.entries(m.ticket_statuses).map(([key, count]) => `${key} ${count}`).join(" · ") || "No tickets"]]);
    }
  } catch (problem) {
    error("staff-error", problem.message);
  }
}

async function show(view, focus = false) {
  state.view = view;
  for (const key of Object.keys(names)) $(`${key}-view`).hidden = key !== view;
  $("view-name").textContent = names[view];
  $("navigation").querySelectorAll("button").forEach(entry => {
    const selected = entry.dataset.view === view;
    entry.classList.toggle("selected", selected);
    if (selected) entry.setAttribute("aria-current", "page");
    else entry.removeAttribute("aria-current");
  });
  if (focus) $("main").focus({preventScroll: true});
  if (view === "orders") await orders();
  if (view === "staff") await staff();
}

async function loadSession(tenant) {
  if (state.busy) return;
  state.busy = true;
  updateButtons();
  error("chat-error");
  try {
    state.session = await api("/api/session", tenant ? {tenant} : undefined);
    const store = selectedStore();
    state.stage = state.session.stage;
    state.selected.clear();
    state.pending = null;
    $("retry-chat").hidden = true;
    $("ticket-detail").hidden = true;
    $("stores").replaceChildren();
    for (const shop of state.session.stores) {
      const choose = button("", () => { if (shop.id !== state.session.tenant) loadSession(shop.id); },
        `store-button${shop.id === store.id ? " active" : ""}`);
      choose.setAttribute("aria-pressed", String(shop.id === store.id));
      choose.append(element("span", shop.name[0], `swatch ${shop.id}`), element("span", shop.name, "store-name"));
      $("stores").append(choose);
    }
    $("store-title").textContent = store.name;
    $("store-specialty").textContent = store.specialty;
    $("store-title").closest(".store-header").classList.toggle("trail", store.id === "trail");
    $("catalogue-form").reset();
    $("category").selectedIndex = 0;
    $("brand").selectedIndex = 0;
    for (const select of [$("category"), $("brand")]) while (select.options.length > 1) select.remove(1);
    $("conversation").replaceChildren();
    appendMessage("Assistant", {message: `Welcome to ${store.name}. I can find products, check orders, or answer store policy questions.`});
    if (state.session.reply) appendMessage("Assistant", state.session.reply);
    options(state.session.reply || {stage: state.stage, options: []});
    setIdentity();
    await catalogue(true);
    await show(state.view);
  } catch (problem) {
    error("chat-error", problem.message);
  } finally {
    state.busy = false;
    updateButtons();
    inbox();
  }
}

$("catalogue-form").addEventListener("submit", event => { event.preventDefault(); event.currentTarget.querySelector("details").open = false; catalogue(); });
$("compare").addEventListener("click", async () => {
  if (state.selected.size === 2) {
    await startTask("compare_products");
    if (state.stage === "compare") send([...state.selected].join(", "));
  }
});
$("navigation").querySelectorAll("button").forEach(entry => entry.addEventListener("click", () => show(entry.dataset.view, true)));
document.querySelectorAll("[data-task]").forEach(entry => entry.addEventListener("click", () => startTask(entry.dataset.task)));
$("composer").addEventListener("submit", event => { event.preventDefault(); send($("message").value); });
$("jump-chat").addEventListener("click", () => { focusAssistant(); $("message").focus({preventScroll: true}); });
$("new-chat").addEventListener("click", () => { if (state.session) loadSession(state.session.tenant); });
$("retry-chat").addEventListener("click", () => {
  if (state.pending) send(state.pending.text, state.pending.shortcut, true);
});
$("use-code").addEventListener("click", () => send($("use-code").textContent));
$("staff-logout").addEventListener("click", () => loadSession(state.session.tenant));
$("staff-login").addEventListener("submit", async event => {
  event.preventDefault();
  error("staff-error");
  try {
    state.session = await api("/api/staff/login", {user: $("staff-user").value, pin: $("staff-pin").value});
    $("staff-pin").value = "";
    state.stage = "menu";
    $("conversation").replaceChildren();
    appendMessage("Assistant", {message: "The staff desk is open. Use New chat to start a customer session."});
    options();
    setIdentity();
    await staff();
  } catch (problem) {
    error("staff-error", problem.message);
  }
});
loadSession();
setInterval(inbox, 1000);
