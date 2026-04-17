const state = {
  catalog: {
    livetv_categories: [],
    movie_categories: [],
    series_categories: []
  },
  selected: {
    livetv_categories: new Set(),
    movie_categories: new Set(),
    series_categories: new Set()
  },
  account: null,
  profiles: {}
};

async function api(url, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function el(id) {
  return document.getElementById(id);
}

function getConfigFromUi() {
  return {
    connection: {
      base_url: el("baseUrl").value.trim(),
      username: el("username").value.trim(),
      password: el("password").value
    },
    output: {
      root_dir: el("rootDir").value.trim(),
      movies_dir: el("moviesDir").value.trim(),
      series_dir: el("seriesDir").value.trim(),
      livetv_file: el("livetvFile").value.trim()
    },
    selection: {
      livetv_categories: [...state.selected.livetv_categories],
      movie_categories: [...state.selected.movie_categories],
      series_categories: [...state.selected.series_categories]
    },
    sync: {
      delete_removed: el("deleteRemoved").checked
    }
  };
}

function applyConfigToUi(cfg) {
  cfg = cfg || {};
  const c = cfg.connection || {};
  const o = cfg.output || {};
  const s = cfg.selection || {};
  const sync = cfg.sync || {};

  el("baseUrl").value = c.base_url || "";
  el("username").value = c.username || "";
  el("password").value = c.password || "";

  el("rootDir").value = o.root_dir || "/output";
  el("moviesDir").value = o.movies_dir || "Movies";
  el("seriesDir").value = o.series_dir || "Series";
  el("livetvFile").value = o.livetv_file || "livetv.m3u";

  el("deleteRemoved").checked = sync.delete_removed !== false;

  state.selected.livetv_categories = new Set(s.livetv_categories || []);
  state.selected.movie_categories = new Set(s.movie_categories || []);
  state.selected.series_categories = new Set(s.series_categories || []);

  renderAllLists();
}

function renderAccountInfo(account) {
  state.account = account || null;
  const box = el("accountInfo");
  box.innerHTML = "";

  const entries = [
    ["Status", account?.status || "-"],
    ["Ablaufdatum", account?.exp_date || "-"],
    ["Erstellt am", account?.created_at || "-"],
    ["Max. Verbindungen", account?.max_connections ?? "-"],
    ["Aktive Verbindungen", account?.active_connections ?? "-"],
    ["Trial", account?.is_trial ? "Ja" : "Nein"],
    ["Server URL", account?.server_url || "-"],
    ["Server Zeitzone", account?.server_timezone || "-"],
    ["Server Zeit", account?.server_time_now || "-"],
    ["Ausgabeformate", Array.isArray(account?.allowed_output_formats) ? account.allowed_output_formats.join(", ") : "-"]
  ];

  for (const [k, v] of entries) {
    const div = document.createElement("div");
    div.className = "info-item";
    div.innerHTML = `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(String(v ?? "-"))}</div>`;
    box.appendChild(div);
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderList(listId, items, selectedSet, searchTerm) {
  const container = el(listId);
  container.innerHTML = "";

  const term = (searchTerm || "").toLowerCase().trim();
  const filtered = items.filter(item => (item.name || "").toLowerCase().includes(term));

  for (const item of filtered) {
    const row = document.createElement("label");
    row.className = "list-item";

    const checked = selectedSet.has(String(item.id));

    row.innerHTML = `
      <input type="checkbox" data-id="${escapeHtml(String(item.id))}" ${checked ? "checked" : ""} style="width:auto; margin-top:3px;">
      <div>
        <div>${escapeHtml(item.name || "Unbekannt")}</div>
        <div class="small">ID: ${escapeHtml(String(item.id || ""))}</div>
      </div>
    `;

    const checkbox = row.querySelector("input");
    checkbox.addEventListener("change", () => {
      const id = String(item.id);
      if (checkbox.checked) selectedSet.add(id);
      else selectedSet.delete(id);
      updateSelectedCounters();
    });

    container.appendChild(row);
  }
}

function renderAllLists() {
  renderList("liveList", state.catalog.livetv_categories, state.selected.livetv_categories, el("searchLive").value);
  renderList("movieList", state.catalog.movie_categories, state.selected.movie_categories, el("searchMovies").value);
  renderList("seriesList", state.catalog.series_categories, state.selected.series_categories, el("searchSeries").value);
  updateSelectedCounters();
}

function updateSelectedCounters() {
  el("liveSelectedCount").textContent = `${state.selected.livetv_categories.size} ausgewählt`;
  el("movieSelectedCount").textContent = `${state.selected.movie_categories.size} ausgewählt`;
  el("seriesSelectedCount").textContent = `${state.selected.series_categories.size} ausgewählt`;
}

function setAllSelection(type, value) {
  const items = state.catalog[type] || [];
  const selectedKey = type;
  const setRef = state.selected[selectedKey];
  setRef.clear();
  if (value) {
    for (const item of items) {
      setRef.add(String(item.id));
    }
  }
  renderAllLists();
}

async function loadProfiles() {
  const data = await api("/api/profiles");
  state.profiles = data.profiles || {};
  const select = el("profileSelect");
  select.innerHTML = "";
  const names = Object.keys(state.profiles).sort((a, b) => a.localeCompare(b, "de"));
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = "-- Profil wählen --";
  select.appendChild(opt0);

  for (const name of names) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  }
}

async function loadRuntimeConfig() {
  try {
    const cfg = await api("/api/runtime-config");
    applyConfigToUi(cfg);
  } catch (_) {}
}

async function saveRuntimeConfig() {
  try {
    await api("/api/runtime-config", "POST", getConfigFromUi());
  } catch (_) {}
}

async function doTestConnection() {
  const cfg = getConfigFromUi();
  const res = await api("/api/test-connection", "POST", cfg.connection);
  renderAccountInfo(res.account || {});
  await saveRuntimeConfig();
  alert("Verbindung erfolgreich.");
}

async function doLoadCatalog() {
  const cfg = getConfigFromUi();
  const res = await api("/api/load-catalog", "POST", cfg.connection);
  state.catalog = res.catalog || { livetv_categories: [], movie_categories: [], series_categories: [] };
  renderAccountInfo(res.account || {});
  renderAllLists();
  await saveRuntimeConfig();
  alert("Kategorien geladen.");
}

async function doSaveProfile() {
  const name = el("profileName").value.trim();
  if (!name) {
    alert("Bitte Profilnamen eingeben.");
    return;
  }

  const cfg = getConfigFromUi();
  await api("/api/profiles/save", "POST", { name, config: cfg });
  await loadProfiles();
  alert("Profil gespeichert.");
}

async function doLoadProfile() {
  const name = el("profileSelect").value;
  if (!name || !state.profiles[name]) {
    alert("Bitte ein Profil wählen.");
    return;
  }
  const cfg = state.profiles[name].config || {};
  el("profileName").value = name;
  applyConfigToUi(cfg);
  await saveRuntimeConfig();
}

async function doDeleteProfile() {
  const name = el("profileSelect").value;
  if (!name) {
    alert("Bitte ein Profil wählen.");
    return;
  }
  if (!confirm(`Profil "${name}" wirklich löschen?`)) return;
  await api("/api/profiles/delete", "POST", { name });
  await loadProfiles();
  alert("Profil gelöscht.");
}

async function doStartExport() {
  const cfg = getConfigFromUi();
  await api("/api/export/start", "POST", { config: cfg });
  await saveRuntimeConfig();
  alert("Export gestartet.");
}

async function doResetOutput() {
  const cfg = getConfigFromUi();
  if (!confirm("Alle von der App erzeugten Dateien löschen?")) return;
  const res = await api("/api/output/reset", "POST", {
    config: cfg,
    delete_runtime_state: false
  });
  alert(`Gelöschte Dateien: ${res.result?.deleted_files ?? 0}`);
  await loadReport();
}

async function pollStatus() {
  try {
    const status = await api("/api/status");
    const progress = Number(status.progress || 0);
    el("progressBar").style.width = `${Math.max(0, Math.min(100, progress))}%`;
    el("statusText").textContent = `${status.phase || "idle"} - ${status.message || ""}`;

    const logs = Array.isArray(status.logs) ? status.logs : [];
    el("logBox").textContent = logs.join("\n");
  } catch (_) {}
}

function renderSummary(report) {
  const summary = report?.summary || {};
  const stats = [
    ["LiveTV Kategorien", summary.selected_livetv_categories ?? 0],
    ["Movie Kategorien", summary.selected_movie_categories ?? 0],
    ["Serien Kategorien", summary.selected_series_categories ?? 0],
    ["LiveTV Sender", summary.livetv_channels ?? 0],
    ["Filme", summary.movies ?? 0],
    ["Serien", summary.series ?? 0],
    ["Episoden", summary.episodes ?? 0],
    ["Geschriebene Dateien", summary.written_files ?? 0],
    ["Gelöschte Dateien", summary.deleted_files ?? 0],
  ];

  const box = el("summaryStats");
  box.innerHTML = "";
  for (const [k, n] of stats) {
    const div = document.createElement("div");
    div.className = "stat";
    div.innerHTML = `<div>${escapeHtml(k)}</div><div class="n">${escapeHtml(String(n))}</div>`;
    box.appendChild(div);
  }
}

function formatChangeItem(item) {
  const type = item?.type || "item";
  const name = item?.name || item?.path || "Unbekannt";
  return `${type}: ${name}`;
}

function renderChanges(report) {
  const added = Array.isArray(report?.changelog?.added) ? report.changelog.added : [];
  const removed = Array.isArray(report?.changelog?.removed) ? report.changelog.removed : [];

  const addedList = el("addedList");
  const removedList = el("removedList");
  addedList.innerHTML = "";
  removedList.innerHTML = "";

  if (!added.length) {
    addedList.innerHTML = "<li>Keine Änderungen</li>";
  } else {
    for (const item of added) {
      const li = document.createElement("li");
      li.textContent = formatChangeItem(item);
      addedList.appendChild(li);
    }
  }

  if (!removed.length) {
    removedList.innerHTML = "<li>Keine Änderungen</li>";
  } else {
    for (const item of removed) {
      const li = document.createElement("li");
      li.textContent = formatChangeItem(item);
      removedList.appendChild(li);
    }
  }
}

async function loadReport() {
  try {
    const report = await api("/api/report");
    renderSummary(report || {});
    renderChanges(report || {});
    if (report?.account) renderAccountInfo(report.account);
  } catch (_) {}
}

async function clearReport() {
  await api("/api/report/clear", "POST", {});
  await loadReport();
}

function bindSearchInputs() {
  el("searchLive").addEventListener("input", renderAllLists);
  el("searchMovies").addEventListener("input", renderAllLists);
  el("searchSeries").addEventListener("input", renderAllLists);
}

function bindButtons() {
  el("btnTestConnection").addEventListener("click", () => doTestConnection().catch(err => alert(err.message)));
  el("btnLoadCatalog").addEventListener("click", () => doLoadCatalog().catch(err => alert(err.message)));
  el("btnSaveProfile").addEventListener("click", () => doSaveProfile().catch(err => alert(err.message)));
  el("btnLoadProfile").addEventListener("click", () => doLoadProfile().catch(err => alert(err.message)));
  el("btnDeleteProfile").addEventListener("click", () => doDeleteProfile().catch(err => alert(err.message)));
  el("btnStartExport").addEventListener("click", () => doStartExport().catch(err => alert(err.message)));
  el("btnResetOutput").addEventListener("click", () => doResetOutput().catch(err => alert(err.message)));
  el("btnClearReport").addEventListener("click", () => clearReport().catch(err => alert(err.message)));

  el("btnSelectAllLive").addEventListener("click", () => setAllSelection("livetv_categories", true));
  el("btnSelectNoneLive").addEventListener("click", () => setAllSelection("livetv_categories", false));
  el("btnSelectAllMovies").addEventListener("click", () => setAllSelection("movie_categories", true));
  el("btnSelectNoneMovies").addEventListener("click", () => setAllSelection("movie_categories", false));
  el("btnSelectAllSeries").addEventListener("click", () => setAllSelection("series_categories", true));
  el("btnSelectNoneSeries").addEventListener("click", () => setAllSelection("series_categories", false));
}

async function init() {
  bindButtons();
  bindSearchInputs();
  await loadProfiles();
  await loadRuntimeConfig();
  await loadReport();
  await pollStatus();
  setInterval(pollStatus, 2000);
}

window.addEventListener("load", init);