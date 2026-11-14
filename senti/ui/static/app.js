/* SENTI console client. Talks only to the loopback host that served it. */
(function () {
  "use strict";

  // ---- token: taken from the URL fragment once, then removed from the address bar ----
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
  let token = fragment.get("token") || sessionStorage.getItem("senti.token") || "";
  if (fragment.get("token")) {
    sessionStorage.setItem("senti.token", token);
    history.replaceState(null, "", location.pathname);
  }

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  const STATE_LABELS = {
    idle: "Idle", listening: "Listening", processing: "Processing", investigating: "Investigating",
    planning: "Planning", awaiting_authorization: "Awaiting authorization", executing: "Executing",
    verifying: "Verifying", completed: "Completed", failed: "Failed", requires_attention: "Requires attention",
  };
  const ACTIVE = new Set(["listening", "processing", "investigating", "planning",
    "awaiting_authorization", "executing", "verifying"]);

  const ui = {
    state: "idle", busy: false, requestId: null, startedAt: null, conversationId: null,
    pendingMsg: null, approvals: new Map(), estop: false, settleTimer: null,
  };

  // ---- API ----
  async function api(method, path, body) {
    const init = { method, headers: { "Authorization": "Bearer " + token, "X-SENTI-Token": token } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) {
      const err = new Error((data && data.error) || ("HTTP " + res.status));
      err.status = res.status;
      throw err;
    }
    return data;
  }

  let toastTimer = null;
  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
  }

  // ---- state / core ----
  function setState(state, detail) {
    if (!STATE_LABELS[state]) return;
    ui.state = state;
    document.body.dataset.state = state;
    $("state-chip").textContent = STATE_LABELS[state];
    $("core-state").textContent = STATE_LABELS[state];
    $("core-detail").textContent = detail || "";
    clearTimeout(ui.settleTimer);
    if (state === "completed") {
      ui.settleTimer = setTimeout(() => { if (!ui.busy) setState(ui.estop ? "requires_attention" : "idle"); }, 6000);
    }
    if (ui.pendingMsg) {
      ui.pendingMsg.querySelector(".pending-label").textContent = STATE_LABELS[state] + (detail ? " — " + detail : "") + "…";
    }
  }

  function setBusy(busy) {
    ui.busy = busy;
    $("send").disabled = busy;
    $("new-conv").disabled = busy;
    if (busy) { ui.startedAt = ui.startedAt || Date.now(); } else { ui.startedAt = null; }
    tickElapsed();
  }

  function tickElapsed() {
    const node = $("elapsed");
    if (!ui.busy || !ui.startedAt) { node.hidden = true; return; }
    const s = Math.floor((Date.now() - ui.startedAt) / 1000);
    node.hidden = false;
    node.textContent = (s >= 60 ? Math.floor(s / 60) + "m " : "") + (s % 60) + "s";
  }

  // ---- conversation ----
  function scrollMessages() {
    const box = $("messages");
    box.scrollTop = box.scrollHeight;
  }

  function addMessage(role, text, foot) {
    $("welcome").hidden = true;
    const wrap = el("div", "msg " + role);
    wrap.appendChild(el("div", "who", role === "user" ? "You" : role === "error" ? "System" : "SENTI"));
    const bubble = el("div", "bubble");
    if (role === "assistant") {
      bubble.classList.add("md");
      bubble.innerHTML = window.SentiMarkdown.render(text); // renderer escapes all input first
    } else {
      bubble.textContent = text;
    }
    wrap.appendChild(bubble);
    if (foot) wrap.appendChild(el("div", "foot", foot));
    $("messages").appendChild(wrap);
    scrollMessages();
    return wrap;
  }

  function showPending() {
    clearPending();
    const wrap = el("div", "msg assistant pending");
    wrap.appendChild(el("div", "who", "SENTI"));
    const bubble = el("div", "bubble");
    const dots = el("span", "typing");
    dots.append(el("i"), el("i"), el("i"));
    bubble.append(dots, el("span", "pending-label", "Listening…"));
    wrap.appendChild(bubble);
    $("messages").appendChild(wrap);
    ui.pendingMsg = wrap;
    scrollMessages();
  }

  function clearPending() {
    if (ui.pendingMsg) ui.pendingMsg.remove();
    ui.pendingMsg = null;
    ui.streamText = "";
  }

  async function send() {
    const input = $("input");
    const text = input.value.trim();
    if (!text || ui.busy) return;
    addMessage("user", text);
    input.value = "";
    autosize();
    setBusy(true);
    showPending();
    try {
      const res = await api("POST", "/api/chat", { text, conversation_id: ui.conversationId || undefined });
      ui.requestId = res.request_id;
    } catch (err) {
      if (err.status === 409) {
        toast("SENTI is still working on the previous request.");
        input.value = text;
        return;
      }
      clearPending();
      setBusy(false);
      addMessage("error", "Could not send: " + err.message);
    }
  }

  function autosize() {
    const input = $("input");
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  }

  // ---- timeline ----
  function timeOf(ts) {
    const d = ts ? new Date(ts) : new Date();
    return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function timeline(kind, titleNodes, sub, ts) {
    const li = el("li", "tl " + kind);
    const head = el("div", "tl-head");
    const title = el("div", "tl-title");
    (Array.isArray(titleNodes) ? titleNodes : [titleNodes]).forEach((n) =>
      title.appendChild(typeof n === "string" ? document.createTextNode(n) : n));
    head.append(title, el("span", "tl-time", timeOf(ts)));
    li.appendChild(head);
    if (sub) li.appendChild(el("div", "tl-sub", sub));
    const list = $("timeline");
    list.appendChild(li);
    while (list.children.length > 200) list.firstChild.remove();
    list.scrollTop = list.scrollHeight;
    $("ops-empty").hidden = true;
  }

  function statusKind(status) {
    const s = String(status || "").toLowerCase();
    if (["succeeded", "success", "ok", "approved", "verified", "completed", "simulated", "valid"].includes(s)) return "ok";
    if (["denied", "failed", "error", "interrupted", "expired", "invalid", "unavailable"].includes(s)) return "bad";
    if (["pending", "approval_required", "proposed"].includes(s)) return "warn";
    return "info";
  }

  // ---- authorization ----
  function previewValue(v) {
    if (v == null) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v); } catch (_) { return String(v); }
  }

  function pick(obj, keys) {
    for (const k of keys) if (obj && obj[k] != null && obj[k] !== "") return obj[k];
    return null;
  }

  function renderApproval(item) {
    const p = item.preview || {};
    const card = el("article", "auth-card");
    card.dataset.id = item.approval_id;
    const top = el("div", "auth-top");
    top.append(el("span", "auth-tool", item.tool), el("span", "risk " + String(item.risk || "").replace(/[^\w]/g, ""), item.risk || "unknown"));
    card.appendChild(top);
    const desc = pick(p, ["summary", "description"]);
    if (desc) card.appendChild(el("p", "auth-desc", previewValue(desc)));

    const current = pick(p, ["current_state", "current", "before"]);
    const intended = pick(p, ["intended_state", "intended", "after", "target_state"]);
    if (current != null || intended != null) {
      const sim = el("div", "sim");
      const a = el("div", "box"); a.append(el("b", null, "Current"), document.createTextNode(previewValue(current) || "unknown"));
      const b = el("div", "box"); b.append(el("b", null, "Intended"), document.createTextNode(previewValue(intended) || "unknown"));
      sim.append(a, el("span", "arrow", "→"), b);
      card.appendChild(sim);
    }
    const rows = el("dl", "sim-rows");
    const addRow = (label, value) => {
      if (value == null || value === "") return;
      const r = el("div"); r.append(el("dt", null, label), el("dd", null, previewValue(value))); rows.appendChild(r);
    };
    addRow("Effect", pick(p, ["effect", "effects", "impact"]));
    addRow("Recovery", pick(p, ["recovery", "rollback", "compensation"]));
    addRow("Simulation", p.simulation);
    if (p.available === false) addRow("Available", "no");
    if (p.simulation_error) addRow("Sim error", p.simulation_error);
    if (rows.children.length) card.appendChild(rows);

    const args = item.arguments || p.arguments;
    if (args && Object.keys(args).length) {
      const det = el("details", "auth-args");
      det.append(el("summary", null, "Arguments"), el("pre", null, JSON.stringify(args, null, 2)));
      card.appendChild(det);
    }

    const bar = el("div", "countdown-bar"); const fill = el("i"); bar.appendChild(fill);
    const actions = el("div", "auth-actions");
    const countdown = el("span", "countdown");
    const approve = el("button", "btn-approve", "Approve"); approve.type = "button";
    const deny = el("button", "btn-deny", "Deny"); deny.type = "button";
    approve.addEventListener("click", () => decide(item.approval_id, "approve"));
    deny.addEventListener("click", () => decide(item.approval_id, "deny"));
    actions.append(countdown, deny, approve);
    card.append(bar, actions);

    const total = Number(item.timeout_seconds) || 120;
    const deadline = Date.now() + (Number(item.expires_in) || total) * 1000;
    ui.approvals.set(item.approval_id, { card, countdown, fill, deadline, total, done: false });
    $("auth-list").prepend(card);
    updateCountdowns();
    refreshAuthCount();
  }

  function finishApproval(id, status) {
    const entry = ui.approvals.get(id);
    if (!entry || entry.done) return;
    entry.done = true;
    entry.card.classList.add("done");
    const actions = entry.card.querySelector(".auth-actions");
    actions.replaceChildren(el("span", "auth-status " + statusKind(status), status));
    setTimeout(() => { entry.card.remove(); ui.approvals.delete(id); refreshAuthCount(); }, 4000);
    refreshAuthCount();
  }

  function refreshAuthCount() {
    const pending = [...ui.approvals.values()].filter((e) => !e.done).length;
    const badge = $("auth-count");
    badge.textContent = String(pending);
    badge.classList.toggle("hot", pending > 0);
    $("auth-empty").hidden = ui.approvals.size > 0;
  }

  function updateCountdowns() {
    const now = Date.now();
    for (const e of ui.approvals.values()) {
      if (e.done) continue;
      const left = Math.max(0, Math.ceil((e.deadline - now) / 1000));
      e.countdown.textContent = left > 0 ? "Expires in " + left + "s" : "Expiring…";
      e.fill.style.width = Math.max(0, Math.min(100, (left / e.total) * 100)) + "%";
    }
  }

  async function decide(id, decision) {
    const entry = ui.approvals.get(id);
    if (entry) entry.card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const res = await api("POST", "/api/approvals/" + encodeURIComponent(id), { decision });
      finishApproval(id, res.status);
    } catch (err) {
      toast("Decision not recorded: " + err.message);
      if (err.status === 409 || err.status === 404) finishApproval(id, err.status === 404 ? "gone" : "closed");
      else if (entry) entry.card.querySelectorAll("button").forEach((b) => { b.disabled = false; });
    }
  }

  // ---- system / manifest ----
  function setKV(id, text, cls) {
    const dd = $(id);
    dd.textContent = text;
    dd.className = (dd.classList.contains("mono") ? "mono " : "") + (cls || "");
  }

  async function loadManifest() {
    try {
      const m = await api("GET", "/api/manifest");
      const c = m.console || {};
      setKV("m-model", m.resolved_model_tag || m.foundation_model_tag || "unknown", m.model_installed ? "ok" : "warn");
      const ollama = String(m.ollama_status || "unknown");
      setKV("m-ollama", ollama.split(":")[0], ollama === "connected" ? "ok" : "bad");
      setKV("m-tools", (c.available_tools ?? "?") + " available / " + (c.tool_count ?? "?"));
      const policy = m.policy || {};
      setKV("m-mutations", policy.mutations_enabled ? "enabled (approval required)" : "blocked",
        policy.mutations_enabled ? "" : "warn");
      setKV("m-db", m.database_status || "unknown", m.database_status === "available" ? "ok" : "bad");
      setEstop(Boolean(c.emergency_stop ?? policy.emergency_stop));
      if (c.conversation_id) setConversation(c.conversation_id);
    } catch (err) {
      setKV("m-ollama", "host unreachable", "bad");
    }
  }

  function setConversation(id) {
    ui.conversationId = id || null;
    $("m-conv").textContent = id ? String(id).slice(0, 12) : "—";
    $("m-conv").title = id || "";
  }

  function setEstop(on) {
    ui.estop = on;
    const btn = $("estop");
    btn.setAttribute("aria-checked", on ? "true" : "false");
    $("estop-sub").textContent = on ? "ENGAGED — actions blocked" : "Disengaged";
  }

  async function toggleEstop() {
    const next = !ui.estop;
    const btn = $("estop");
    btn.disabled = true;
    try {
      const res = await api("POST", "/api/emergency-stop", { enabled: next });
      setEstop(Boolean(res.emergency_stop ?? next));
      loadManifest();
    } catch (err) {
      toast("Emergency stop change failed: " + err.message);
    } finally {
      btn.disabled = false;
    }
  }

  // ---- memory ----
  function memoryText(payload) {
    if (payload == null) return "";
    if (typeof payload === "string") return payload;
    for (const k of ["text", "value", "content", "summary", "fact", "preference"]) {
      if (typeof payload[k] === "string") return payload[k];
    }
    try { return JSON.stringify(payload); } catch (_) { return String(payload); }
  }

  async function loadMemories() {
    const ns = $("mem-ns").value;
    try {
      const res = await api("GET", "/api/memories" + (ns ? "?namespace=" + encodeURIComponent(ns) : ""));
      const list = $("mem-list");
      list.replaceChildren();
      for (const m of res.memories || []) {
        const li = el("li", "mem-item");
        li.appendChild(el("span", "mem-meta", [m.namespace, m.memory_type].filter(Boolean).join(" · ")));
        const btn = el("button", "forget-btn", "Forget");
        btn.type = "button";
        btn.title = "Permanently forget this memory";
        btn.addEventListener("click", () => forgetMemory(m.memory_id, li, btn));
        li.appendChild(btn);
        li.appendChild(el("div", "mem-body", memoryText(m.payload)));
        list.appendChild(li);
      }
      $("mem-empty").hidden = list.children.length > 0;
    } catch (err) {
      $("mem-empty").hidden = false;
      $("mem-empty").textContent = "Memory unavailable: " + err.message;
    }
  }

  async function forgetMemory(id, li, btn) {
    if (btn.dataset.confirm !== "1") {
      btn.dataset.confirm = "1";
      btn.textContent = "Confirm";
      setTimeout(() => { btn.dataset.confirm = ""; btn.textContent = "Forget"; }, 3000);
      return;
    }
    btn.disabled = true;
    try {
      await api("DELETE", "/api/memories/" + encodeURIComponent(id));
      li.remove();
      $("mem-empty").hidden = $("mem-list").children.length > 0;
    } catch (err) {
      btn.disabled = false;
      toast("Could not forget memory: " + err.message);
    }
  }

  // ---- events ----
  function handleEvent(ev) {
    if (ev.conversation_id) setConversation(ev.conversation_id);
    switch (ev.type) {
      case "snapshot":
        setBusy(Boolean(ev.busy));
        if (ev.busy && ev.elapsed != null) ui.startedAt = Date.now() - ev.elapsed * 1000;
        if (ev.state) setState(ev.state);
        if (ev.busy && !ui.pendingMsg) showPending();
        if (!ev.busy) clearPending();
        for (const a of ev.approvals || []) if (!ui.approvals.has(a.approval_id)) renderApproval(a);
        break;
      case "state":
        setState(ev.state, ev.detail);
        if (ev.state === "completed" || ev.state === "failed") { setBusy(false); clearPending(); }
        else if (ACTIVE.has(ev.state) && ev.request_id) setBusy(true);
        if (ev.state !== "listening" && ev.state !== "completed") {
          timeline(ev.state === "failed" ? "bad" : "dim", STATE_LABELS[ev.state] || ev.state, ev.detail, ev.ts);
        }
        break;
      case "thinking":
        timeline("info", "Deliberate reasoning " + (ev.enabled ? "on" : "off"), ev.reason, ev.ts);
        break;
      case "delta": {
        // Live token stream: render the reply as it is generated.
        if (!ui.pendingMsg) showPending();
        ui.streamText = (ui.streamText || "") + (ev.text || "");
        const bubble = ui.pendingMsg.querySelector(".bubble");
        if (!bubble.classList.contains("md")) {
          bubble.classList.add("md");
          ui.pendingMsg.classList.add("streaming");
        }
        bubble.innerHTML = window.SentiMarkdown.render(ui.streamText); // renderer escapes all input first
        scrollMessages();
        break;
      }
      case "tool": {
        if (ev.phase === "proposed" && ui.streamText) {
          // Text before a tool call is a preamble; restart the stream for the next step.
          ui.streamText = "";
          showPending();
        }
        const phase = el("span", "phase", ev.phase || "tool");
        const name = el("span", "mono", ev.tool || "unknown");
        const status = ev.status ? " · " + ev.status : "";
        timeline(statusKind(ev.status || ev.phase), [phase, name, status], ev.summary, ev.ts);
        break;
      }
      case "approval":
        if (ev.status === "pending") {
          if (!ui.approvals.has(ev.approval_id)) renderApproval(ev);
          timeline("warn", [el("span", "phase", "authorization"), el("span", "mono", ev.tool), " requested"],
            "Risk: " + (ev.risk || "unknown"), ev.ts);
        } else {
          finishApproval(ev.approval_id, ev.status);
          timeline(statusKind(ev.status), [el("span", "phase", "authorization"), el("span", "mono", ev.tool), " " + ev.status],
            ev.reason && ev.reason !== "operator" ? "Reason: " + ev.reason : "", ev.ts);
        }
        break;
      case "memory":
        timeline("mem", "Memory " + (ev.action || "event") + (ev.count != null ? " (" + ev.count + ")" : ""), ev.summary, ev.ts);
        if (ev.action === "learned" || ev.action === "forgotten") loadMemories();
        break;
      case "reply": {
        clearPending();
        const usage = ev.usage || {};
        const bits = [ev.model, usage.elapsed_seconds != null ? Number(usage.elapsed_seconds).toFixed(1) + "s" : null,
          usage.completion_tokens != null ? usage.completion_tokens + " tokens" : null].filter(Boolean);
        addMessage("assistant", ev.text || "", bits.join(" · "));
        break;
      }
      case "error":
        clearPending();
        addMessage("error", ev.message || "Unknown error");
        timeline("bad", "Error", ev.message, ev.ts);
        break;
      case "policy":
        setEstop(Boolean(ev.emergency_stop));
        timeline(ev.emergency_stop ? "bad" : "ok", "Emergency stop " + (ev.emergency_stop ? "engaged" : "released"),
          ev.denied_approvals ? ev.denied_approvals + " pending action(s) denied" : "", ev.ts);
        loadManifest();
        break;
      default:
        break;
    }
  }

  let stream = null;
  let retry = 1000;
  function connect() {
    if (stream) stream.close();
    stream = new EventSource("/api/events?token=" + encodeURIComponent(token));
    stream.onopen = () => {
      retry = 1000;
      $("link-dot").className = "dot live";
      $("link-label").textContent = "Live";
    };
    stream.onmessage = (msg) => {
      try { handleEvent(JSON.parse(msg.data)); } catch (err) { console.error("bad event", err); }
    };
    stream.onerror = () => {
      $("link-dot").className = "dot down";
      $("link-label").textContent = "Reconnecting";
      stream.close();
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    };
  }

  // ---- wiring ----
  function init() {
    if (!token) {
      $("link-label").textContent = "No session token — relaunch SENTI";
      $("link-dot").className = "dot down";
    }
    const input = $("input");
    $("composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    input.addEventListener("input", autosize);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); input.focus(); }
    });
    $("estop").addEventListener("click", toggleEstop);
    $("refresh-manifest").addEventListener("click", loadManifest);
    $("mem-ns").addEventListener("change", loadMemories);
    $("ops-clear").addEventListener("click", () => { $("timeline").replaceChildren(); $("ops-empty").hidden = false; });
    $("new-conv").addEventListener("click", async () => {
      try {
        const res = await api("POST", "/api/new-conversation", {});
        setConversation(res.conversation_id);
        $("messages").querySelectorAll(".msg").forEach((n) => n.remove());
        $("welcome").hidden = false;
      } catch (err) { toast("Could not start a new conversation: " + err.message); }
    });
    setInterval(() => { tickElapsed(); updateCountdowns(); }, 1000);
    setInterval(loadManifest, 30000);
    connect();
    loadManifest();
    loadMemories();
    input.focus();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
