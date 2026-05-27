// ios-activity-monitor frontend
// minimal dev-tool dashboard with hover-to-explain

const MAX_VISIBLE = 40;
const SPARK_LEN = 30;
const UI_RATE_DEFAULT = 5000;

const state = {
  sortKey: "cpu",
  sortDir: "desc",
  history: new Map(),
  initialized: false,
  uiIntervalMs:
    parseInt(localStorage.getItem("iam-ui-interval-ms") || "", 10) ||
    UI_RATE_DEFAULT,
  lastRenderAt: -Infinity,
};

const $$ = (sel) => document.querySelectorAll(sel);
const bind = (key) => document.querySelector(`[data-bind="${key}"]`);

// ─── sort header ─────────────────────────────────────────────────────
$$("th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (state.sortKey === key) {
      state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
    } else {
      state.sortKey = key;
      state.sortDir = key === "name" || key === "pid" ? "asc" : "desc";
    }
    renderHeaderSort();
    if (window.__lastPayload) render(window.__lastPayload);
  });
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const map = { c: "cpu", m: "rss_mb", n: "name", p: "pid", t: "threads" };
  const next = map[e.key.toLowerCase()];
  if (!next) return;
  if (state.sortKey === next) {
    state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
  } else {
    state.sortKey = next;
    state.sortDir = next === "name" || next === "pid" ? "asc" : "desc";
  }
  renderHeaderSort();
  if (window.__lastPayload) render(window.__lastPayload);
});

function renderHeaderSort() {
  $$("th[data-sort]").forEach((th) => {
    th.classList.remove("sorted", "asc", "desc");
    if (th.dataset.sort === state.sortKey) {
      th.classList.add("sorted", state.sortDir);
    }
  });
}
renderHeaderSort();

// ─── ui refresh rate ────────────────────────────────────────────────
const rateSelect = document.getElementById("ui-rate");
if (rateSelect) {
  rateSelect.value = String(state.uiIntervalMs);
  rateSelect.addEventListener("change", () => {
    const ms = parseInt(rateSelect.value, 10);
    if (Number.isFinite(ms) && ms > 0) {
      state.uiIntervalMs = ms;
      localStorage.setItem("iam-ui-interval-ms", String(ms));
      // force a render on the next tick
      state.lastRenderAt = -Infinity;
    }
  });
}

// ─── sample-rate control ────────────────────────────────────────────
let activeWS = null;
function sendSampleInterval(ms) {
  if (activeWS && activeWS.readyState === WebSocket.OPEN) {
    activeWS.send(JSON.stringify({ cmd: "set_sample_interval", ms }));
  }
}

const sampleSelect = document.getElementById("sample-rate");
if (sampleSelect) {
  const stored = parseInt(
    localStorage.getItem("iam-sample-interval-ms") || "",
    10,
  );
  if (Number.isFinite(stored) && stored > 0) {
    sampleSelect.value = String(stored);
  }
  sampleSelect.addEventListener("change", () => {
    const ms = parseInt(sampleSelect.value, 10);
    if (Number.isFinite(ms) && ms > 0) {
      localStorage.setItem("iam-sample-interval-ms", String(ms));
      sendSampleInterval(ms);
    }
  });
}

// ─── ws connection ───────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  activeWS = ws;
  setStatus("connecting", "connecting…");

  ws.addEventListener("open", () => {
    setStatus("live", "live");
    // push the persisted sample interval on (re)connect
    if (sampleSelect) {
      const ms = parseInt(sampleSelect.value, 10);
      if (Number.isFinite(ms) && ms > 0) sendSampleInterval(ms);
    }
  });
  ws.addEventListener("message", (ev) => {
    let payload;
    try {
      payload = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (payload.type === "error") {
      setStatus("error", payload.message || "stream error");
      return;
    }
    if (payload.type === "battery") {
      renderBattery(payload.battery);
      return;
    }
    if (payload.type !== "tick") return;
    window.__lastPayload = payload;
    accumulateHistory(payload);
    const now = performance.now();
    if (now - state.lastRenderAt >= state.uiIntervalMs) {
      state.lastRenderAt = now;
      render(payload);
    }
    setStatus("live", "live");
  });
  ws.addEventListener("close", () => {
    setStatus("connecting", "reconnecting…");
    setTimeout(connect, 1500);
  });
  ws.addEventListener("error", () => setStatus("error", "socket error"));
}
connect();

function setStatus(status, text) {
  document.querySelector(".dot").dataset.status = status;
  bind("status-text").textContent = text;
}

// ─── battery ────────────────────────────────────────────────────────
function renderBattery(b) {
  const wrap = document.querySelector(".battery");
  if (!wrap) return;
  wrap.classList.remove("warm", "hot");
  if (!b || b.temp_c == null) {
    bind("battery-temp").textContent = "—";
    bind("battery-state").textContent = "";
    bind("battery-charge").textContent = "";
    return;
  }
  const t = b.temp_c;
  let label;
  if (t >= 41) {
    wrap.classList.add("hot");
    label = "hot";
  } else if (t >= 37) {
    wrap.classList.add("warm");
    label = "warm";
  } else if (t >= 33) {
    label = "mild";
  } else {
    label = "cool";
  }
  bind("battery-temp").textContent = t.toFixed(1);
  bind("battery-state").textContent = label;
  const charge =
    b.level_pct != null
      ? `${b.level_pct}%${b.is_charging ? " charging" : ""}`
      : "";
  bind("battery-charge").textContent = charge;
}

// ─── history (accumulated every tick, even when not rendering) ─────
function accumulateHistory(payload) {
  const seenPids = new Set();
  for (const s of payload.samples) {
    seenPids.add(s.pid);
    const hist = state.history.get(s.pid) ?? [];
    hist.push(s.cpu);
    while (hist.length > SPARK_LEN) hist.shift();
    state.history.set(s.pid, hist);
  }
  for (const pid of [...state.history.keys()]) {
    if (!seenPids.has(pid)) state.history.delete(pid);
  }
}

// ─── render ──────────────────────────────────────────────────────────
function render(payload) {
  bind("device-name").textContent = payload.device.name;
  const productRaw = payload.device.product_type;
  const marketing =
    (window.lookupDevice && window.lookupDevice(productRaw)) || null;
  bind("device-product").textContent = marketing || productRaw;
  bind("device-ios").textContent = payload.device.product_version;

  const t = payload.totals;
  bind("aggregate-cpu").textContent = t.aggregate_cpu.toFixed(1);
  bind("process-count").textContent = t.process_count;
  bind("rss-total").textContent = formatNumber(t.rss_mb_total);
  bind("rate").textContent = payload.interval_ms;
  renderBattery(payload.battery);

  // sort
  const samples = payload.samples.slice();
  const dir = state.sortDir === "desc" ? -1 : 1;
  samples.sort((a, b) => {
    const av = a[state.sortKey];
    const bv = b[state.sortKey];
    if (typeof av === "string") return dir * av.localeCompare(bv);
    return dir * ((av ?? 0) - (bv ?? 0));
  });

  renderRows(samples.slice(0, MAX_VISIBLE));
  state.initialized = true;
}

function renderRows(samples) {
  const tbody = bind("rows");
  const existing = new Map();
  for (const tr of tbody.children) existing.set(Number(tr.dataset.pid), tr);

  const used = new Set();
  let prev = null;
  for (const s of samples) {
    const cls = cpuTier(s.cpu);
    let tr = existing.get(s.pid);
    if (!tr) {
      tr = document.createElement("tr");
      tr.dataset.pid = s.pid;
      tr.innerHTML = `
        <td class="col-pid"></td>
        <td class="col-name"></td>
        <td class="col-cpu"></td>
        <td class="col-spark"><svg class="spark" viewBox="0 0 96 18" preserveAspectRatio="none"><polyline points=""/></svg></td>
        <td class="col-mem"></td>
        <td class="col-th"></td>
      `;
      tr.classList.add("fade-in");
      attachTooltipHandlers(tr);
    }
    used.add(s.pid);

    tr.dataset.name = s.name;
    tr.querySelector(".col-pid").textContent = s.pid;
    tr.querySelector(".col-name").textContent = s.name;
    const cpuTd = tr.querySelector(".col-cpu");
    cpuTd.classList.remove("high", "critical");
    if (cls === "hot") cpuTd.classList.add("high");
    if (cls === "critical") cpuTd.classList.add("critical");
    cpuTd.textContent = s.cpu.toFixed(1);

    const hist = state.history.get(s.pid) ?? [s.cpu];
    const sparkSvg = tr.querySelector(".spark");
    sparkSvg.classList.remove("hot", "critical");
    if (cls === "hot") sparkSvg.classList.add("hot");
    if (cls === "critical") sparkSvg.classList.add("critical");
    sparkSvg
      .querySelector("polyline")
      .setAttribute("points", sparkPoints(hist, 96, 18));

    tr.querySelector(".col-mem").textContent = formatNumber(s.rss_mb);
    tr.querySelector(".col-th").textContent = s.threads;

    // reorder in place
    if (tr.parentNode !== tbody) tbody.appendChild(tr);
    else {
      const expectedNext = prev ? prev.nextSibling : tbody.firstChild;
      if (expectedNext !== tr) tbody.insertBefore(tr, expectedNext);
    }
    prev = tr;
  }
  for (const [pid, tr] of existing) {
    if (!used.has(pid)) tr.remove();
  }
}

function cpuTier(cpu) {
  if (cpu >= 50) return "critical";
  if (cpu >= 15) return "hot";
  return "normal";
}

function formatNumber(n) {
  if (n == null) return "—";
  if (n >= 10000) return (n / 1000).toFixed(1) + "k";
  if (n >= 1000) return n.toFixed(0);
  if (n >= 100) return n.toFixed(0);
  return n.toFixed(1);
}

function sparkPoints(data, width, height) {
  if (!data.length) return "";
  const padY = 1;
  // a one-point polyline doesn't render; duplicate it so we draw a flat line
  const series = data.length === 1 ? [data[0], data[0]] : data;
  const max = Math.max(8, ...series);
  const range = Math.max(0.5, max);
  const n = series.length;
  return series
    .map((v, i) => {
      const x = (i / (n - 1)) * width;
      const y = height - padY - (v / range) * (height - 2 * padY);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

// ─── tooltip ─────────────────────────────────────────────────────────
const tooltipEl = document.getElementById("tooltip");

function attachTooltipHandlers(tr) {
  tr.addEventListener("mouseenter", () => showTooltip(tr));
  tr.addEventListener("mousemove", (e) => positionTooltip(e));
  tr.addEventListener("mouseleave", () => hideTooltip());
}

function showTooltip(tr) {
  const name = tr.dataset.name;
  if (!name) return;
  const info = window.lookupProcess(name);
  const cpuCell = tr.querySelector(".col-cpu");
  const cpu = parseFloat(cpuCell.textContent);
  const isHigh = cpu >= 15;

  const desc = info.desc ?? defaultDescription(name, info.kind);
  const hot =
    info.hot && isHigh
      ? `<div class="tt-hot">${escapeHtml(info.hot)}</div>`
      : "";

  tooltipEl.innerHTML = `
    <h4>${escapeHtml(name)}<span class="tt-kind">${escapeHtml(info.kind)}</span></h4>
    <p>${escapeHtml(desc)}</p>
    ${hot}
  `;
  tooltipEl.classList.add("show");
  tooltipEl.setAttribute("aria-hidden", "false");
}

function hideTooltip() {
  tooltipEl.classList.remove("show");
  tooltipEl.setAttribute("aria-hidden", "true");
}

function positionTooltip(e) {
  const pad = 14;
  const rect = tooltipEl.getBoundingClientRect();
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  if (x + rect.width > window.innerWidth - 8) x = e.clientX - pad - rect.width;
  if (y + rect.height > window.innerHeight - 8)
    y = e.clientY - pad - rect.height;
  tooltipEl.style.left = `${x}px`;
  tooltipEl.style.top = `${y}px`;
}

function defaultDescription(name, kind) {
  if (kind === "system daemon") {
    return "iOS background service. Not documented here yet — search the name for details, or it may be specific to your installed apps.";
  }
  if (kind === "app or framework") {
    return "App or framework process. May be a foreground app, an Apple framework worker, or a third-party app extension.";
  }
  return "iOS process. Not documented here yet.";
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
