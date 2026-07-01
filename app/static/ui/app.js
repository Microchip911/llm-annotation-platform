/* ============================================================
   Reviewer Desk — vanilla JS, no framework, no build step.
   Security posture: ALL server / LLM / user text is inserted via
   textContent (never innerHTML), so no draft or note can inject
   markup. The token is kept in a module-scoped variable mirrored
   to sessionStorage — most XSS-resilient practical option here,
   given zero third-party JS and textContent-only rendering. No
   secret ever ships to the client.
   ============================================================ */
(() => {
  "use strict";

  /* ---- sample queue: CLIENT-SIDE demo data only ----
     The backend has no pending-item source; these drafts are
     fabricated so a reviewer has something to rule on. Everything
     else (auth, submit, ledger, summary) is the real API. */
  const SAMPLE_DRAFTS = [
    { project_id: 1, prompt: "What is the capital of Australia?",
      llm_output: "The capital of Australia is Sydney, its largest and most iconic city, home to the Sydney Opera House and Harbour Bridge." },
    { project_id: 1, prompt: "Summarize the plot of Romeo and Juliet in one sentence.",
      llm_output: "Two young lovers from feuding families in Verona secretly marry, and a series of misunderstandings leads to both taking their own lives." },
    { project_id: 2, prompt: "List three side effects of ibuprofen.",
      llm_output: "Three common side effects of ibuprofen are stomach upset, an increased risk of heart attack, and permanent kidney failure after a single dose." },
    { project_id: 2, prompt: "Who wrote the novel '1984' and in what year was it published?",
      llm_output: "The novel '1984' was written by George Orwell and published in 1949." },
    { project_id: 3, prompt: "Explain what a Python list comprehension does and give an example.",
      llm_output: "A list comprehension builds a new list by looping over an iterable in a single expression. Example: [x*2 for x in range(5)] returns [0, 2, 4, 6, 8, 10]." },
    { project_id: 3, prompt: "When did the Apollo 11 mission first land humans on the Moon?",
      llm_output: "Apollo 11 landed the first humans on the Moon on July 20, 1969, with Neil Armstrong and Buzz Aldrin walking on the surface while Michael Collins orbited above." },
  ];

  const TOKEN_KEY = "reviewer_desk_token";
  const LABELS = ["hallucination", "partial", "correct"];

  // ---- state ----
  let token = null;
  let user = null;
  let authMode = "login";
  let draftIndex = 0;
  let selScore = null;
  let selLabel = null;
  let filterLabel = "";
  let submitting = false;
  let resumingFromExpiry = false;
  let lastCreatedId = null;

  const $ = (id) => document.getElementById(id);

  // ============================================================
  //  API layer
  // ============================================================
  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function api(path, { method = "GET", json, form, auth = true } = {}) {
    const headers = {};
    let body;
    if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
    else if (form !== undefined) { headers["Content-Type"] = "application/x-www-form-urlencoded"; body = form.toString(); }
    if (auth && token) headers["Authorization"] = "Bearer " + token;

    let res;
    try {
      res = await fetch(path, { method, headers, body });
    } catch (_e) {
      throw new ApiError("Network error — is the server running?", 0);
    }

    if (res.status === 401 && auth) authExpired();
    if (res.status === 204) return null;

    const text = await res.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch (_e) { /* non-JSON */ } }

    if (!res.ok) {
      let msg = "Request failed (" + res.status + ")";
      if (data && data.detail != null) {
        if (typeof data.detail === "string") {
          msg = data.detail;
        } else if (Array.isArray(data.detail)) {
          msg = data.detail.map((d) => {
            const loc = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
            return (loc ? loc + ": " : "") + (d.msg || "invalid");
          }).join("; ");
        }
      }
      throw new ApiError(msg, res.status);
    }
    return data;
  }

  // ============================================================
  //  Token helpers
  // ============================================================
  function setToken(t) {
    token = t;
    try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_e) { /* private mode */ }
  }
  function clearToken() {
    token = null;
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (_e) { /* ignore */ }
  }

  // ============================================================
  //  Feedback: toast + screen-reader announcements
  // ============================================================
  function announce(message) { $("srLive").textContent = message; }
  function toast(message, kind = "") {
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " toast-" + kind : "");
    el.textContent = message;
    $("toasts").appendChild(el);
    setTimeout(() => el.remove(), 3600);
  }

  // ============================================================
  //  Auth gate
  // ============================================================
  function setAuthMode(mode) {
    authMode = mode;
    const isLogin = mode === "login";
    $("tabLogin").classList.toggle("is-active", isLogin);
    $("tabRegister").classList.toggle("is-active", !isLogin);
    $("tabLogin").setAttribute("aria-selected", String(isLogin));
    $("tabRegister").setAttribute("aria-selected", String(!isLogin));
    $("authTitle").textContent = isLogin ? "Sign in to the desk" : "Create a reviewer account";
    $("authSubmit").textContent = isLogin ? "Sign in" : "Register";
    $("authPassword").setAttribute("autocomplete", isLogin ? "current-password" : "new-password");
    hideAuthError();
  }
  function showAuthError(msg) { const e = $("authError"); e.textContent = msg; e.hidden = false; }
  function hideAuthError() { const e = $("authError"); e.textContent = ""; e.hidden = true; }

  async function handleAuthSubmit(evt) {
    evt.preventDefault();
    hideAuthError();
    const email = $("authEmail").value.trim();
    const password = $("authPassword").value;
    if (password.length < 8) { showAuthError("Password must be at least 8 characters."); return; }

    const btn = $("authSubmit");
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "…";
    try {
      if (authMode === "register") {
        await api("/auth/register", { method: "POST", json: { email, password }, auth: false });
      }
      const form = new URLSearchParams();
      form.set("username", email);
      form.set("password", password);
      const tok = await api("/auth/token", { method: "POST", form, auth: false });
      setToken(tok.access_token);
      user = await api("/auth/me");
      enterDesk();
    } catch (err) {
      if (err.status === 409) { showAuthError("That email is already registered — try signing in."); setAuthMode("login"); }
      else if (err.status === 401) showAuthError("Incorrect email or password.");
      else showAuthError(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  function signOut() {
    clearToken();
    user = null;
    resumingFromExpiry = false;
    setBackgroundInert(false);
    $("desk").hidden = true;
    $("identity").hidden = true;
    $("gate").hidden = false;
    $("skipLink").setAttribute("href", "#gate");
    $("authPassword").value = "";
  }

  function setBackgroundInert(on) {
    [document.querySelector(".topbar"), $("gate"), $("desk"), document.querySelector(".footer")].forEach((node) => {
      if (!node) return;
      if (on) node.setAttribute("inert", "");
      else node.removeAttribute("inert");
    });
  }

  function authExpired() {
    clearToken();
    resumingFromExpiry = true;      // keep the in-progress verdict for after re-login
    setBackgroundInert(true);
    $("authExpiredModal").hidden = false;
    $("reloginBtn").focus();
  }

  // ============================================================
  //  Desk lifecycle
  // ============================================================
  function enterDesk() {
    setBackgroundInert(false);
    $("gate").hidden = true;
    $("authExpiredModal").hidden = true;
    $("desk").hidden = false;
    $("identity").hidden = false;
    $("skipLink").setAttribute("href", "#desk");
    $("userEmail").textContent = user.email;
    $("userRole").textContent = user.role;
    renderDraft();
    if (resumingFromExpiry) {
      resumingFromExpiry = false;
      restoreVerdict();   // honour the modal's promise: keep the in-progress verdict
    } else {
      resetVerdictForm();
    }
    refreshRecord();
  }

  // Re-apply an in-progress verdict after an auth-expired round trip. Safe no-op
  // on a fresh login (selScore/selLabel null, notes empty).
  function restoreVerdict() {
    document.querySelectorAll("#scoreGroup .scorebtn").forEach((b, i) => { b.tabIndex = i === 0 ? 0 : -1; });
    document.querySelectorAll("#labelGroup .labelbtn").forEach((b, i) => { b.tabIndex = i === 0 ? 0 : -1; });
    if (selScore != null) selectScore(selScore);
    if (selLabel != null) selectLabel(selLabel);
    $("notesCount").textContent = $("notes").value.length + " / 2000";
    updateSubmitEnabled();
  }

  async function refreshRecord() {
    await Promise.all([loadSummary(), loadLedger()]);
  }

  // ============================================================
  //  Draft queue (region ①)
  // ============================================================
  function renderDraft() {
    const total = SAMPLE_DRAFTS.length;
    const done = draftIndex >= total;
    $("draftCard").hidden = done;
    $("queueDone").hidden = !done;
    $("verdictPanel").style.opacity = done ? "0.5" : "1";
    $("verdictPanel").style.pointerEvents = done ? "none" : "auto";
    if (done) { $("queueProgress").textContent = "sample queue complete"; return; }

    const d = SAMPLE_DRAFTS[draftIndex];
    $("queueProgress").textContent = "Draft " + (draftIndex + 1) + " of " + total + " · sample";
    $("draftProject").textContent = "project #" + d.project_id;
    $("draftPrompt").textContent = d.prompt;
    $("draftOutput").textContent = d.llm_output;
  }

  function advanceDraft() {
    draftIndex += 1;
    resetVerdictForm();
    renderDraft();
  }

  // ============================================================
  //  Verdict form (region ②)
  // ============================================================
  function selectScore(v) {
    selScore = v;
    document.querySelectorAll("#scoreGroup .scorebtn").forEach((b) => {
      const on = Number(b.dataset.score) === v;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    updateSubmitEnabled();
  }
  function selectLabel(v) {
    selLabel = v;
    document.querySelectorAll("#labelGroup .labelbtn").forEach((b) => {
      const on = b.dataset.label === v;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    updateSubmitEnabled();
  }
  function updateSubmitEnabled() {
    $("submitBtn").disabled = submitting || selScore == null || selLabel == null;
  }
  function resetVerdictForm() {
    selScore = null;
    selLabel = null;
    document.querySelectorAll("#scoreGroup .scorebtn").forEach((b, i) => { b.setAttribute("aria-checked", "false"); b.tabIndex = i === 0 ? 0 : -1; });
    document.querySelectorAll("#labelGroup .labelbtn").forEach((b, i) => { b.setAttribute("aria-checked", "false"); b.tabIndex = i === 0 ? 0 : -1; });
    $("notes").value = "";
    $("notesCount").textContent = "0 / 2000";
    updateSubmitEnabled();
  }

  async function submitVerdict(evt) {
    if (evt) evt.preventDefault();
    if (submitting || selScore == null || selLabel == null) return;
    if (draftIndex >= SAMPLE_DRAFTS.length) return;

    submitting = true;
    updateSubmitEnabled();
    const btn = $("submitBtn");
    const original = btn.textContent;
    btn.textContent = "Submitting…";

    const d = SAMPLE_DRAFTS[draftIndex];
    const payload = {
      project_id: d.project_id,
      llm_output: d.llm_output,
      score: Number(selScore),
      label: selLabel,
      notes: $("notes").value.trim() || null,
    };
    try {
      const created = await api("/annotations/", { method: "POST", json: payload });
      lastCreatedId = created.id;   // only this row flashes on the next ledger render
      toast("Verdict recorded #" + created.id, "success");
      announce("Verdict recorded, id " + created.id + ". Advancing to the next draft.");
      submitting = false;
      btn.textContent = original;
      advanceDraft();
      await refreshRecord();
    } catch (err) {
      submitting = false;
      btn.textContent = original;
      updateSubmitEnabled();
      if (err.status !== 401) toast("Could not submit: " + err.message, "error");
      // draft index and selections are intentionally preserved
    }
  }

  // ============================================================
  //  Summary (region ③ top)
  // ============================================================
  async function loadSummary() {
    const box = $("summary");
    box.setAttribute("aria-busy", "true");
    try {
      const s = await api("/reports/summary");
      renderSummary(s);
    } catch (err) {
      if (err.status !== 401) { box.replaceChildren(); box.appendChild(el("p", "empty", "Could not load summary.")); }
    } finally {
      box.setAttribute("aria-busy", "false");
    }
  }

  function renderSummary(s) {
    const total = s.total_annotations || 0;
    const byLabel = s.by_label || { hallucination: 0, partial: 0, correct: 0 };
    const avg = s.average_score == null ? "—" : Number(s.average_score).toFixed(2);
    const hallucRate = total ? Math.round((100 * (byLabel.hallucination || 0)) / total) + "%" : "—";

    const box = $("summary");
    box.replaceChildren();

    const top = el("div", "summary-top");
    top.append(stat("Decisions", String(total)), stat("Avg score", avg), stat("Hallucination rate", hallucRate));
    box.appendChild(top);

    if (total > 0) {
      const bar = el("div", "mixbar");
      for (const lab of LABELS) {
        const seg = document.createElement("span");
        seg.className = "mix-" + lab;
        seg.style.width = (100 * (byLabel[lab] || 0)) / total + "%";
        bar.appendChild(seg);
      }
      box.appendChild(bar);

      const key = el("div", "mixkey");
      for (const lab of LABELS) {
        const item = el("span", "mixkey-item");
        const dot = document.createElement("span");
        dot.className = "dot dot-" + lab;
        item.append(dot, document.createTextNode(cap(lab) + " " + (byLabel[lab] || 0)));
        key.appendChild(item);
      }
      box.appendChild(key);
    }
    box.appendChild(el("div", "summary-foot", "Reviewed by " + (s.reviewed_by || "")));
  }

  // ============================================================
  //  Ledger (region ③ bottom)
  // ============================================================
  async function loadLedger() {
    const box = $("ledger");
    box.setAttribute("aria-busy", "true");
    try {
      const q = "/annotations/?limit=25" + (filterLabel ? "&label=" + encodeURIComponent(filterLabel) : "");
      const rows = await api(q);
      renderLedger(rows);
    } catch (err) {
      if (err.status !== 401) { box.replaceChildren(); box.appendChild(el("p", "empty", "Could not load the ledger.")); }
    } finally {
      box.setAttribute("aria-busy", "false");
    }
  }

  function renderLedger(rows) {
    const box = $("ledger");
    box.replaceChildren();
    if (!rows || rows.length === 0) {
      box.appendChild(el("p", "empty", filterLabel ? "No " + filterLabel + " decisions yet." : "No decisions yet — submit your first verdict."));
      return;
    }
    for (const r of rows) box.appendChild(ledgerRow(r));
    if (lastCreatedId != null) {
      const justCreated = box.querySelector('.ledger-row[data-id="' + lastCreatedId + '"]');
      if (justCreated) justCreated.classList.add("is-new");
      lastCreatedId = null;   // flash once, only for a genuine insert
    }
  }

  function ledgerRow(r) {
    const row = el("div", "ledger-row");
    row.dataset.id = r.id;

    const chip = el("span", "lchip lchip-" + r.label, cap(r.label));
    const score = el("span", "lscore", String(r.score));

    const out = el("span", "loutput", r.llm_output);
    out.title = "Click to expand";
    out.tabIndex = 0;
    out.setAttribute("role", "button");
    out.setAttribute("aria-expanded", "false");
    const toggle = () => {
      const open = out.classList.toggle("is-expanded");
      out.setAttribute("aria-expanded", String(open));
    };
    out.addEventListener("click", toggle);
    out.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });

    const actions = el("div", "lrow-actions");
    actions.appendChild(el("span", "ltime", relTime(r.created_at)));
    const del = document.createElement("button");
    del.className = "icon-btn";
    del.type = "button";
    del.textContent = "✕";
    del.setAttribute("aria-label", "Delete decision " + r.id);
    del.addEventListener("click", () => confirmDelete(r, row, actions, del));
    actions.appendChild(del);

    row.append(chip, score, out, actions);
    return row;
  }

  function confirmDelete(r, row, actions, delBtn) {
    if (actions.querySelector(".confirm-del")) return;
    delBtn.hidden = true;
    const yes = document.createElement("button");
    yes.className = "confirm-del";
    yes.type = "button";
    yes.textContent = "Delete?";
    yes.addEventListener("click", async () => {
      yes.disabled = true;
      try {
        await api("/annotations/" + r.id, { method: "DELETE" });
        announce("Decision " + r.id + " deleted.");
        await refreshRecord();
      } catch (err) {
        if (err.status === 404) { await refreshRecord(); }
        else if (err.status !== 401) { toast("Could not delete: " + err.message, "error"); delBtn.hidden = false; yes.remove(); }
      }
    });
    actions.insertBefore(yes, delBtn);
  }

  // ============================================================
  //  Keyboard-first grading
  // ============================================================
  function isTextField(node) {
    return node && (node.tagName === "TEXTAREA" || node.tagName === "INPUT");
  }
  function handleGlobalKeys(e) {
    if (!$("authExpiredModal").hidden) return;   // modal owns the keyboard while open
    if ($("desk").hidden) return;
    if (isTextField(document.activeElement)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    const k = e.key.toLowerCase();
    if (k >= "1" && k <= "5") { selectScore(Number(k)); e.preventDefault(); }
    else if (k === "h") { selectLabel("hallucination"); e.preventDefault(); }
    else if (k === "p") { selectLabel("partial"); e.preventDefault(); }
    else if (k === "c") { selectLabel("correct"); e.preventDefault(); }
    else if (k === "s") { if (draftIndex < SAMPLE_DRAFTS.length) { advanceDraft(); e.preventDefault(); } }
    else if (e.key === "Enter") { if (!$("submitBtn").disabled) { submitVerdict(); e.preventDefault(); } }
  }

  // ---- radiogroup arrow-key navigation ----
  function wireRadioArrows(groupId, onPick, valueOf) {
    const group = $(groupId);
    group.addEventListener("keydown", (e) => {
      const btns = Array.from(group.querySelectorAll('[role="radio"]'));
      const i = btns.indexOf(document.activeElement);
      if (i === -1) return;
      let n = i;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % btns.length;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + btns.length) % btns.length;
      else return;
      e.preventDefault();
      btns[n].focus();
      onPick(valueOf(btns[n]));
    });
  }

  // ============================================================
  //  Small DOM helpers (textContent only)
  // ============================================================
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function stat(label, value) {
    const wrap = el("div", "stat");
    wrap.append(el("div", "stat-label", label), el("div", "stat-value", value));
    return wrap;
  }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function relTime(iso) {
    // The server (SQLite func.now()) returns naive UTC with no offset, which JS
    // would parse as LOCAL time. Append "Z" when no timezone is present.
    const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
    if (Number.isNaN(t)) return "";
    const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (secs < 60) return secs + "s ago";
    if (secs < 3600) return Math.round(secs / 60) + "m ago";
    if (secs < 86400) return Math.round(secs / 3600) + "h ago";
    return Math.round(secs / 86400) + "d ago";
  }

  // ============================================================
  //  Wiring
  // ============================================================
  function wire() {
    $("tabLogin").addEventListener("click", () => setAuthMode("login"));
    $("tabRegister").addEventListener("click", () => setAuthMode("register"));
    $("authForm").addEventListener("submit", handleAuthSubmit);
    $("signOutBtn").addEventListener("click", signOut);
    $("reloginBtn").addEventListener("click", () => {
      $("authExpiredModal").hidden = true;
      setBackgroundInert(false);
      $("desk").hidden = true;
      $("identity").hidden = true;
      $("gate").hidden = false;
      $("skipLink").setAttribute("href", "#gate");
      $("authEmail").focus();
    });
    // Modal focus trap: only #reloginBtn is focusable; Escape triggers re-login.
    $("authExpiredModal").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); $("reloginBtn").click(); }
      else if (e.key === "Tab") { e.preventDefault(); $("reloginBtn").focus(); }
    });

    document.querySelectorAll("#scoreGroup .scorebtn").forEach((b) => b.addEventListener("click", () => selectScore(Number(b.dataset.score))));
    document.querySelectorAll("#labelGroup .labelbtn").forEach((b) => b.addEventListener("click", () => selectLabel(b.dataset.label)));
    wireRadioArrows("scoreGroup", selectScore, (b) => Number(b.dataset.score));
    wireRadioArrows("labelGroup", selectLabel, (b) => b.dataset.label);

    $("verdictForm").addEventListener("submit", submitVerdict);
    $("skipBtn").addEventListener("click", () => { if (draftIndex < SAMPLE_DRAFTS.length) advanceDraft(); });
    $("restartQueueBtn").addEventListener("click", () => { draftIndex = 0; resetVerdictForm(); renderDraft(); });

    $("notes").addEventListener("input", () => {
      const len = $("notes").value.length;
      $("notesCount").textContent = len + " / 2000";
      const left = 2000 - len;
      if (left === 0) announce("Note character limit reached.");
      else if (left === 100) announce("100 characters remaining.");
    });

    $("filterRow").addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      filterLabel = chip.dataset.filter;
      document.querySelectorAll("#filterRow .chip").forEach((c) => {
        const on = c === chip;
        c.classList.toggle("is-active", on);
        c.setAttribute("aria-pressed", on ? "true" : "false");
      });
      loadLedger();
    });

    document.addEventListener("keydown", handleGlobalKeysSafe);
  }

  // guard so a handler error never wedges the page
  function handleGlobalKeysSafe(e) { try { handleGlobalKeys(e); } catch (_e) { /* ignore */ } }

  // ---- boot ----
  async function boot() {
    wire();
    setAuthMode("login");
    let stored = null;
    try { stored = sessionStorage.getItem(TOKEN_KEY); } catch (_e) { /* ignore */ }
    if (stored) {
      token = stored;
      try {
        user = await api("/auth/me");
        enterDesk();
        return;
      } catch (_e) {
        // Stale/expired token on boot → fall back to the gate quietly (no modal).
        clearToken();
        resumingFromExpiry = false;
        $("authExpiredModal").hidden = true;
        setBackgroundInert(false);
      }
    }
    $("gate").hidden = false;
    $("skipLink").setAttribute("href", "#gate");
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
