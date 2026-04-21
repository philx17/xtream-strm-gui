const state = {
  catalog: {
    livetv_categories: [],
    movie_categories: [],
    series_categories: []
  },
  items: {
    livetv: [],
    movies: [],
    series: []
  },
  itemLoadState: {
    livetv: "idle",
    movies: "idle",
    series: "idle"
  },
  itemLoadInfo: {
    livetv: "Noch nicht geladen",
    movies: "Noch nicht geladen",
    series: "Noch nicht geladen"
  },
  selected: {
    livetv_categories: new Set(),
    movie_categories: new Set(),
    series_categories: new Set(),

    livetv_exclude_ids: new Set(),
    movie_exclude_ids: new Set(),
    series_exclude_ids: new Set(),

    proxy_library_ids: new Set()
  },
  account: null,
  profiles: {},
  lastRunningState: false,
  proxy: {
    info: null,
    libraries: []
  }
};

let filterMode = "all";

async function api(url, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(url, opts);

  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }

  if (!res.ok) {
    const msg = data?.error || `HTTP ${res.status} bei ${url}`;
    throw new Error(msg);
  }

  return data;
}

function el(id) {
  return document.getElementById(id);
}

function toast(msg, type = "ok") {
  const box = document.getElementById("toastContainer");
  if (!box) return;

  const div = document.createElement("div");
  div.className = `toast ${type}`;
  div.textContent = msg;
  box.appendChild(div);

  setTimeout(() => {
    div.style.opacity = "0";
    div.style.transform = "translateY(-4px)";
    setTimeout(() => div.remove(), 220);
  }, 3500);
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function sortByName(items) {
  return [...items].sort((a, b) => (a.name || "").localeCompare(b.name || "", "de"));
}

function uniqueById(items) {
  const map = new Map();
  for (const item of items || []) {
    const id = String(item?.id || "").trim();
    if (!id) continue;
    if (!map.has(id)) map.set(id, item);
  }
  return [...map.values()];
}

function categoryNameMap(type) {
  const items = type === "livetv"
    ? state.catalog.livetv_categories
    : type === "movies"
      ? state.catalog.movie_categories
      : state.catalog.series_categories;

  const map = new Map();
  for (const x of items) {
    map.set(String(x.id), x.name || x.id);
  }
  return map;
}

function setFilter(mode) {
  filterMode = mode === "selected" ? "selected" : "all";
  renderAllLists();
}

function toggleSection(id) {
  const node = el(id);
  if (!node) return;
  const isHidden = node.style.display === "none";
  node.style.display = isHidden ? "block" : "none";
}

function clearLoadedItems(type) {
  state.items[type] = [];
  state.itemLoadState[type] = "idle";
  state.itemLoadInfo[type] = "Noch nicht geladen";

  if (type === "livetv") {
    state.selected.livetv_exclude_ids = new Set();
  } else if (type === "movies") {
    state.selected.movie_exclude_ids = new Set();
  } else {
    state.selected.series_exclude_ids = new Set();
  }
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
      series_categories: [...state.selected.series_categories],

      livetv_exclude_ids: [...state.selected.livetv_exclude_ids],
      movie_exclude_ids: [...state.selected.movie_exclude_ids],
      series_exclude_ids: [...state.selected.series_exclude_ids],

      livetv_include_ids: [],
      movie_include_ids: [],
      series_include_ids: [],

      proxy_library_ids: [...state.selected.proxy_library_ids]
    },
    sync: {
      delete_removed: el("deleteRemoved").checked
    },
    schedule: {
      enabled: el("scheduleEnabled")?.checked || false,
      mode: el("scheduleMode")?.value || "daily",
      time: el("scheduleTime")?.value || "03:30",
      weekday: el("scheduleWeekday")?.value || "monday",
      interval_days: Number(el("scheduleIntervalDays")?.value || 1),
      profile_name: el("scheduleProfile")?.value || ""
    },
    proxy: {
 	 jellyfin_base_url: el("proxyJellyfinUrl")?.value.trim() || "",
 	 jellyfin_external_base_url: el("proxyJellyfinExternalUrl")?.value.trim() || "",
 	 base_path: "/proxy",
 	 username: el("proxyUsername")?.value.trim() || "",
 	 password: el("proxyPassword")?.value || ""
	}
  };
}

function applyConfigToUi(cfg) {
  cfg = cfg || {};
  const c = cfg.connection || {};
  const o = cfg.output || {};
  const s = cfg.selection || {};
  const sync = cfg.sync || {};
  const schedule = cfg.schedule || {};
  const proxy = cfg.proxy || {};

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

  state.selected.livetv_exclude_ids = new Set(s.livetv_exclude_ids || []);
  state.selected.movie_exclude_ids = new Set(s.movie_exclude_ids || []);
  state.selected.series_exclude_ids = new Set(s.series_exclude_ids || []);
  state.selected.proxy_library_ids = new Set(s.proxy_library_ids || []);

  if (el("scheduleEnabled")) el("scheduleEnabled").checked = !!schedule.enabled;
  if (el("scheduleMode")) el("scheduleMode").value = schedule.mode || "daily";
  if (el("scheduleTime")) el("scheduleTime").value = schedule.time || "03:30";
  if (el("scheduleWeekday")) el("scheduleWeekday").value = schedule.weekday || "monday";
  if (el("scheduleIntervalDays")) el("scheduleIntervalDays").value = schedule.interval_days || 1;

	if (el("proxyJellyfinUrl")) el("proxyJellyfinUrl").value = proxy.jellyfin_base_url || "";
	if (el("proxyJellyfinExternalUrl")) el("proxyJellyfinExternalUrl").value = proxy.jellyfin_external_base_url || "";
	if (el("proxyUsername")) el("proxyUsername").value = proxy.username || "";
	if (el("proxyPassword")) el("proxyPassword").value = proxy.password || "";

  renderAllLists();
  renderAllItemLists();
  renderProxyLibraries();
  renderProxyEndpointInfo();
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

function renderCategoryList(listId, items, selectedSet, searchTerm, type) {
  const container = el(listId);
  container.innerHTML = "";

  const term = (searchTerm || "").toLowerCase().trim();

  const filtered = sortByName(items).filter(item => {
    const matchesSearch = (item.name || "").toLowerCase().includes(term);
    const matchesFilter = filterMode === "selected"
      ? selectedSet.has(String(item.id))
      : true;
    return matchesSearch && matchesFilter;
  });

  for (const item of filtered) {
    const row = document.createElement("label");
    row.className = "list-item";
    const checked = selectedSet.has(String(item.id));

    row.innerHTML = `
      <input type="checkbox" ${checked ? "checked" : ""} style="width:auto; margin-top:3px;">
      <div>
        <div>${escapeHtml(item.name || "Unbekannt")}</div>
        <div class="small">ID: ${escapeHtml(String(item.id || ""))}</div>
      </div>
    `;

    const checkbox = row.querySelector("input");
    checkbox.addEventListener("change", async () => {
      const id = String(item.id);
      if (checkbox.checked) selectedSet.add(id);
      else selectedSet.delete(id);

      clearLoadedItems(type);
      renderAllLists();
      renderAllItemLists();
      await saveRuntimeConfig();
    });

    container.appendChild(row);
  }
}

function getFilteredItemsBySelectedCategories(type) {
  if (type === "livetv") {
    return state.items.livetv.filter(x =>
      state.selected.livetv_categories.has(String(x.category_id || ""))
    );
  }
  if (type === "movies") {
    return state.items.movies.filter(x =>
      state.selected.movie_categories.has(String(x.category_id || ""))
    );
  }
  return state.items.series.filter(x =>
    state.selected.series_categories.has(String(x.category_id || ""))
  );
}

function renderGroupedItemSelector(listId, items, excludeSet, searchTerm, type) {
  const container = el(listId);
  container.innerHTML = "";

  const loadState = state.itemLoadState[type];
  const loadInfo = state.itemLoadInfo[type];

  if (loadState === "loading") {
    container.innerHTML = `<div class="small">Lade Inhalte ...</div>`;
    return;
  }

  if (loadState === "idle") {
    container.innerHTML = `<div class="small">${escapeHtml(loadInfo)}</div>`;
    return;
  }

  const catMap = categoryNameMap(type);
  const term = (searchTerm || "").toLowerCase().trim();
  const filtered = sortByName(items).filter(item =>
    (item.name || "").toLowerCase().includes(term)
  );

  const groups = new Map();
  for (const item of filtered) {
    const cid = String(item.category_id || "unknown");
    if (!groups.has(cid)) groups.set(cid, []);
    groups.get(cid).push(item);
  }

  if (groups.size === 0) {
    container.innerHTML = `<div class="small">Keine Einträge</div>`;
    return;
  }

  for (const [cid, groupItems] of groups.entries()) {
    const head = document.createElement("div");
    head.className = "small";
    head.style.margin = "8px 0 6px 0";
    head.innerHTML = `<strong>${escapeHtml(catMap.get(cid) || `Kategorie ${cid}`)}</strong> (${groupItems.length})`;
    container.appendChild(head);

    for (const item of groupItems.slice(0, 1000)) {
      const itemId = String(item.id);
      const excluded = excludeSet.has(itemId);

      const row = document.createElement("div");
      row.className = "list-item";
      row.innerHTML = `
        <input type="checkbox" ${excluded ? "checked" : ""} style="width:auto; margin-top:3px;">
        <div style="flex:1;">
          <div>${escapeHtml(item.name || "Unbekannt")}</div>
          <div class="small">ID: ${escapeHtml(itemId)}</div>
        </div>
      `;

      const checkbox = row.querySelector("input");

      checkbox.addEventListener("change", async () => {
        if (checkbox.checked) excludeSet.add(itemId);
        else excludeSet.delete(itemId);
        renderAllItemLists();
        await saveRuntimeConfig();
      });

      container.appendChild(row);
    }
  }
}

function cleanupSelectionSetsForCurrentItems() {
  const liveIds = new Set(state.items.livetv.map(x => String(x.id)));
  const movieIds = new Set(state.items.movies.map(x => String(x.id)));
  const seriesIds = new Set(state.items.series.map(x => String(x.id)));

  state.selected.livetv_exclude_ids = new Set(
    [...state.selected.livetv_exclude_ids].filter(id => liveIds.has(id))
  );
  state.selected.movie_exclude_ids = new Set(
    [...state.selected.movie_exclude_ids].filter(id => movieIds.has(id))
  );
  state.selected.series_exclude_ids = new Set(
    [...state.selected.series_exclude_ids].filter(id => seriesIds.has(id))
  );
}

function renderItemLoadInfos() {
  if (el("liveItemsLoadInfo")) el("liveItemsLoadInfo").textContent = state.itemLoadInfo.livetv;
  if (el("movieItemsLoadInfo")) el("movieItemsLoadInfo").textContent = state.itemLoadInfo.movies;
  if (el("seriesItemsLoadInfo")) el("seriesItemsLoadInfo").textContent = state.itemLoadInfo.series;
}

function renderAllLists() {
  renderCategoryList("liveList", state.catalog.livetv_categories, state.selected.livetv_categories, el("searchLive").value, "livetv");
  renderCategoryList("movieList", state.catalog.movie_categories, state.selected.movie_categories, el("searchMovies").value, "movies");
  renderCategoryList("seriesList", state.catalog.series_categories, state.selected.series_categories, el("searchSeries").value, "series");

  el("liveSelectedCount").textContent = `${state.selected.livetv_categories.size} ausgewählt`;
  el("movieSelectedCount").textContent = `${state.selected.movie_categories.size} ausgewählt`;
  el("seriesSelectedCount").textContent = `${state.selected.series_categories.size} ausgewählt`;

  renderItemLoadInfos();
}

function renderAllItemLists() {
  const liveItems = getFilteredItemsBySelectedCategories("livetv");
  const movieItems = getFilteredItemsBySelectedCategories("movies");
  const seriesItems = getFilteredItemsBySelectedCategories("series");

  renderGroupedItemSelector(
    "liveItemsList",
    liveItems,
    state.selected.livetv_exclude_ids,
    el("searchLiveItems").value,
    "livetv"
  );

  renderGroupedItemSelector(
    "movieItemsList",
    movieItems,
    state.selected.movie_exclude_ids,
    el("searchMovieItems").value,
    "movies"
  );

  renderGroupedItemSelector(
    "seriesItemsList",
    seriesItems,
    state.selected.series_exclude_ids,
    el("searchSeriesItems").value,
    "series"
  );

  el("liveExcludedCount").textContent = `${state.selected.livetv_exclude_ids.size} ausgeschlossen`;
  el("movieExcludedCount").textContent = `${state.selected.movie_exclude_ids.size} ausgeschlossen`;
  el("seriesExcludedCount").textContent = `${state.selected.series_exclude_ids.size} ausgeschlossen`;

  renderItemLoadInfos();
}

function setAllSelection(type, value) {
  const items = state.catalog[type] || [];
  const setRef = state.selected[type];
  setRef.clear();

  if (value) {
    for (const item of items) setRef.add(String(item.id));
  }

  if (type === "livetv_categories") clearLoadedItems("livetv");
  if (type === "movie_categories") clearLoadedItems("movies");
  if (type === "series_categories") clearLoadedItems("series");

  renderAllLists();
  renderAllItemLists();
  saveRuntimeConfig();
}

function renderProxyInfo(info) {
  state.proxy.info = info || null;
  const box = el("proxyInfo");
  if (!box) return;

  if (!info) {
    box.innerHTML = `<div class="small">Noch keine Verbindung getestet.</div>`;
    return;
  }

  const entries = [
    ["Servername", info.ServerName || info.Name || "-"],
    ["Version", info.Version || "-"],
    ["Produkt", info.ProductName || "Jellyfin"],
    ["Lokale Adresse", info.LocalAddress || "-"],
    ["WAN Adresse", info.WanAddress || "-"]
  ];

  box.innerHTML = "";
  for (const [k, v] of entries) {
    const div = document.createElement("div");
    div.className = "info-item";
    div.innerHTML = `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(String(v ?? "-"))}</div>`;
    box.appendChild(div);
  }
}

function renderProxyLibraries() {
  const container = el("proxyLibrariesList");
  if (!container) return;
  container.innerHTML = "";

  const libs = sortByName(state.proxy.libraries || []);
  if (!libs.length) {
    container.innerHTML = `<div class="small">Noch keine Bibliotheken geladen.</div>`;
    return;
  }

  for (const lib of libs) {
    const id = String(lib.id);
    const checked = state.selected.proxy_library_ids.has(id);
    const locations = Array.isArray(lib.locations) ? lib.locations.join(", ") : "";

    const row = document.createElement("label");
    row.className = "list-item";
    row.innerHTML = `
      <input type="checkbox" ${checked ? "checked" : ""} style="width:auto; margin-top:3px;">
      <div>
        <div>${escapeHtml(lib.name || "Unbekannt")}</div>
        <div class="small">Typ: ${escapeHtml(lib.collection_type || "-")}</div>
        <div class="small">${escapeHtml(locations || "")}</div>
      </div>
    `;

    const checkbox = row.querySelector("input");
    checkbox.addEventListener("change", async () => {
      if (checkbox.checked) state.selected.proxy_library_ids.add(id);
      else state.selected.proxy_library_ids.delete(id);

      renderProxySelectionInfo();
      renderProxyEndpointInfo();
      await saveRuntimeConfig();
    });

    container.appendChild(row);
  }

  renderProxySelectionInfo();
}

function renderProxySelectionInfo() {
  const info = el("proxyLibrariesSelectedCount");
  if (!info) return;
  info.textContent = `${state.selected.proxy_library_ids.size} Bibliotheken ausgewählt`;
}

function renderProxyEndpointInfo() {
  const box = el("proxyEndpointInfo");
  if (!box) return;

  const user = el("proxyUsername")?.value.trim() || "-";
  const pass = el("proxyPassword")?.value || "-";
  const proxyUrl = `${window.location.origin}/proxy/player_api.php`;
  const localJf = el("proxyJellyfinUrl")?.value.trim() || "-";
  const extJf = el("proxyJellyfinExternalUrl")?.value.trim() || "-";

  box.innerHTML = `
    <div class="info-item">
      <div class="k">Xtream Server URL</div>
      <div class="v">${escapeHtml(proxyUrl)}</div>
    </div>
    <div class="info-item">
      <div class="k">Xtream Username</div>
      <div class="v">${escapeHtml(user)}</div>
    </div>
    <div class="info-item">
      <div class="k">Xtream Passwort</div>
      <div class="v">${escapeHtml(pass)}</div>
    </div>
    <div class="info-item">
      <div class="k">Jellyfin lokal</div>
      <div class="v">${escapeHtml(localJf)}</div>
    </div>
    <div class="info-item">
      <div class="k">Jellyfin extern</div>
      <div class="v">${escapeHtml(extJf)}</div>
    </div>
    <div class="info-item">
      <div class="k">Stream-Verhalten</div>
      <div class="v">Direkte Jellyfin-URLs, automatisch lokal/extern</div>
    </div>
  `;
}

async function loadProfiles() {
  const data = await api("/api/profiles");
  state.profiles = data.profiles || {};
  const select = el("profileSelect");
  select.innerHTML = "";

  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = "-- Profil wählen --";
  select.appendChild(opt0);

  for (const name of Object.keys(state.profiles).sort((a, b) => a.localeCompare(b, "de"))) {
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

async function loadSchedule() {
  try {
    const data = await api("/api/schedule");
    const s = data.schedule || {};

    if (el("scheduleProfile")) {
      const profiles = state.profiles || {};
      const select = el("scheduleProfile");
      select.innerHTML = "";

      const opt0 = document.createElement("option");
      opt0.value = "";
      opt0.textContent = "-- Profil wählen --";
      select.appendChild(opt0);

      for (const name of Object.keys(profiles).sort((a, b) => a.localeCompare(b, "de"))) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
      }

      select.value = s.profile_name || "";
    }

    if (el("scheduleEnabled")) el("scheduleEnabled").checked = !!s.enabled;
    if (el("scheduleMode")) el("scheduleMode").value = s.mode || "daily";
    if (el("scheduleTime")) el("scheduleTime").value = s.time || "03:30";
    if (el("scheduleWeekday")) el("scheduleWeekday").value = s.weekday || "monday";
    if (el("scheduleIntervalDays")) el("scheduleIntervalDays").value = s.interval_days || 1;
    if (el("scheduleNextRun")) el("scheduleNextRun").textContent = `Nächster Lauf: ${data.next_run || "-"}`;
    if (el("scheduleProfileInfo")) el("scheduleProfileInfo").textContent = `Automatik nutzt Profil: ${s.profile_name || "-"}`;
  } catch (_) {}
}

async function saveSchedule() {
  const schedule = {
    enabled: el("scheduleEnabled").checked,
    mode: el("scheduleMode").value,
    time: el("scheduleTime").value,
    weekday: el("scheduleWeekday").value,
    interval_days: Number(el("scheduleIntervalDays").value || 1)
  };

  const profile_name = el("scheduleProfile")?.value || "";

  const res = await api("/api/schedule/save", "POST", {
    schedule,
    profile_name
  });

  if (el("scheduleNextRun")) {
    el("scheduleNextRun").textContent = `Nächster Lauf: ${res.next_run || "-"}`;
  }
  if (el("scheduleProfileInfo")) {
    el("scheduleProfileInfo").textContent = `Automatik nutzt Profil: ${profile_name || "-"}`;
  }

  await saveRuntimeConfig();
  toast("Zeitplan gespeichert.", "ok");
}

async function runNow() {
  await api("/api/schedule/run-now", "POST", {});
  toast("Export gestartet.", "ok");
}

async function cancelExport() {
  await api("/api/export/cancel", "POST", {});
  toast("Abbruch angefordert.", "warn");
  await pollStatus();
}

async function doTestConnection() {
  const cfg = getConfigFromUi();
  const res = await api("/api/test-connection", "POST", cfg.connection);
  renderAccountInfo(res.account || {});
  await saveRuntimeConfig();
  toast("Verbindung erfolgreich.", "ok");
}

async function doLoadCatalog() {
  const cfg = getConfigFromUi();
  const res = await api("/api/load-catalog", "POST", cfg.connection);
  state.catalog = res.catalog || { livetv_categories: [], movie_categories: [], series_categories: [] };
  renderAccountInfo(res.account || {});
  clearLoadedItems("livetv");
  clearLoadedItems("movies");
  clearLoadedItems("series");
  renderAllLists();
  renderAllItemLists();
  await saveRuntimeConfig();
  toast("Kategorien geladen.", "ok");
}

async function loadItemsForType(type) {
  const cfg = getConfigFromUi();
  const connection = cfg.connection;

  let categoryIds = [];
  if (type === "livetv") categoryIds = [...state.selected.livetv_categories];
  if (type === "movies") categoryIds = [...state.selected.movie_categories];
  if (type === "series") categoryIds = [...state.selected.series_categories];

  if (!connection.base_url || !connection.username || !connection.password) {
    toast("Bitte zuerst Verbindungsdaten eintragen.", "err");
    return;
  }

  if (!categoryIds.length) {
    state.items[type] = [];
    state.itemLoadState[type] = "idle";
    state.itemLoadInfo[type] = "Keine Kategorie ausgewählt";
    renderAllItemLists();
    return;
  }

  state.itemLoadState[type] = "loading";
  state.itemLoadInfo[type] = "Lade Inhalte ...";
  renderAllItemLists();

  try {
    const res = await api("/api/load-items", "POST", {
      connection,
      item_type: type,
      category_ids: categoryIds
    });

    state.items[type] = uniqueById(res.items || []);
    state.itemLoadState[type] = "loaded";
    state.itemLoadInfo[type] = res.cached
      ? `Geladen aus Cache (${state.items[type].length})`
      : `Frisch geladen (${state.items[type].length})`;

    cleanupSelectionSetsForCurrentItems();
    renderAllItemLists();
    await saveRuntimeConfig();
  } catch (err) {
    console.error(err);
    state.items[type] = [];
    state.itemLoadState[type] = "idle";
    state.itemLoadInfo[type] = `Fehler: ${err.message}`;
    renderAllItemLists();
    toast(`Inhalte konnten nicht geladen werden: ${err.message}`, "err");
  }
}

async function doProxyTestJellyfin() {
  const payload = {
    base_url: el("proxyJellyfinUrl").value.trim(),
    api_key: el("proxyJellyfinApiKey").value.trim()
  };

  const res = await api("/api/proxy/test-jellyfin", "POST", payload);
  renderProxyInfo(res.info || {});
  renderProxyEndpointInfo();
  await saveRuntimeConfig();
  toast("Jellyfin Verbindung erfolgreich.", "ok");
}

async function doProxyLoadLibraries() {
  const payload = {
    base_url: el("proxyJellyfinUrl").value.trim(),
    api_key: el("proxyJellyfinApiKey").value.trim()
  };

  const res = await api("/api/proxy/libraries", "POST", payload);
  state.proxy.libraries = res.libraries || [];
  renderProxyLibraries();
  renderProxyEndpointInfo();
  await saveRuntimeConfig();
  toast("Jellyfin Bibliotheken geladen.", "ok");
}

async function doSaveProfile() {
  const name = el("profileName").value.trim();
  if (!name) {
    toast("Bitte Profilnamen eingeben.", "err");
    return;
  }

  const cfg = getConfigFromUi();
  await api("/api/profiles/save", "POST", { name, config: cfg });
  await loadProfiles();
  await loadSchedule();
  toast("Profil gespeichert.", "ok");
}

async function doLoadProfile() {
  const name = el("profileSelect").value;
  if (!name || !state.profiles[name]) {
    toast("Bitte ein Profil wählen.", "err");
    return;
  }

  const cfg = state.profiles[name].config || {};
  el("profileName").value = name;
  applyConfigToUi(cfg);

  clearLoadedItems("livetv");
  clearLoadedItems("movies");
  clearLoadedItems("series");
  renderAllItemLists();

  await loadSchedule();
  await saveRuntimeConfig();
  toast(`Profil geladen: ${name}`, "ok");
}

async function doDeleteProfile() {
  const name = el("profileSelect").value;
  if (!name) {
    toast("Bitte ein Profil wählen.", "err");
    return;
  }

  if (!confirm(`Profil "${name}" wirklich löschen?`)) return;

  await api("/api/profiles/delete", "POST", { name });
  await loadProfiles();
  await loadSchedule();
  toast("Profil gelöscht.", "ok");
}

async function doStartExport() {
  const cfg = getConfigFromUi();
  const catSection = document.getElementById("catSection");
  if (catSection) catSection.style.display = "none";

  try {
    const res = await api("/api/export/start", "POST", { config: cfg });
    await saveRuntimeConfig();
    await pollStatus();
    toast("Export gestartet.", "ok");
    return res;
  } catch (err) {
    console.error("Export start failed:", err);
    toast(`Export konnte nicht gestartet werden: ${err.message}`, "err");
    throw err;
  }
}

async function doResetOutput() {
  const cfg = getConfigFromUi();
  if (!confirm("Alle von der App erzeugten Dateien löschen?")) return;

  const res = await api("/api/output/reset", "POST", {
    config: cfg,
    delete_runtime_state: false
  });

  toast(`Gelöschte Dateien: ${res.result?.deleted_files ?? 0}`, "ok");
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

    const btnCancel = el("btnCancelExport");
    if (btnCancel) {
      btnCancel.disabled = !status.running;
    }

    const isRunning = !!status.running;
    if (state.lastRunningState && !isRunning) {
      await loadReport();
      await loadSchedule();

      if (status.phase === "cancelled") {
        toast("Export abgebrochen.", "warn");
      } else if (status.phase === "done") {
        toast("Export abgeschlossen.", "ok");
      } else if (status.phase === "failed") {
        toast("Export fehlgeschlagen.", "err");
      }
    }
    state.lastRunningState = isRunning;
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
    ["Ausgeschl. LiveTV", summary.excluded_livetv ?? 0],
    ["Ausgeschl. Filme", summary.excluded_movies ?? 0],
    ["Ausgeschl. Serien", summary.excluded_series ?? 0],
    ["Series Worker", summary.series_info_workers ?? 0],
    ["Geschriebene Dateien", summary.written_files ?? 0],
    ["Gelöschte Dateien", summary.deleted_files ?? 0]
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
  toast("Report geleert.", "ok");
}

function bindSearchInputs() {
  [
    "searchLive", "searchMovies", "searchSeries",
    "searchLiveItems", "searchMovieItems", "searchSeriesItems"
  ].forEach(id => {
    const node = el(id);
    if (!node) return;
    node.addEventListener("input", () => {
      renderAllLists();
      renderAllItemLists();
    });
  });

[
  "proxyJellyfinUrl",
  "proxyJellyfinExternalUrl",
  "proxyJellyfinApiKey",
  "proxyUsername",
  "proxyPassword"
].forEach(id => {
  const node = el(id);
  if (!node) return;
  node.addEventListener("input", () => {
    renderProxyEndpointInfo();
  });
});
}

function bindButtons() {
  el("btnTestConnection").addEventListener("click", () => doTestConnection().catch(err => toast(err.message, "err")));
  el("btnLoadCatalog").addEventListener("click", () => doLoadCatalog().catch(err => toast(err.message, "err")));
  el("btnSaveProfile").addEventListener("click", () => doSaveProfile().catch(err => toast(err.message, "err")));
  el("btnLoadProfile").addEventListener("click", () => doLoadProfile().catch(err => toast(err.message, "err")));
  el("btnDeleteProfile").addEventListener("click", () => doDeleteProfile().catch(err => toast(err.message, "err")));
  el("btnStartExport").addEventListener("click", () => doStartExport().catch(err => toast(err.message, "err")));
  if (el("btnCancelExport")) el("btnCancelExport").addEventListener("click", () => cancelExport().catch(err => toast(err.message, "err")));
  el("btnResetOutput").addEventListener("click", () => doResetOutput().catch(err => toast(err.message, "err")));
  el("btnClearReport").addEventListener("click", () => clearReport().catch(err => toast(err.message, "err")));

  el("btnSelectAllLive").addEventListener("click", () => setAllSelection("livetv_categories", true));
  el("btnSelectNoneLive").addEventListener("click", () => setAllSelection("livetv_categories", false));
  el("btnSelectAllMovies").addEventListener("click", () => setAllSelection("movie_categories", true));
  el("btnSelectNoneMovies").addEventListener("click", () => setAllSelection("movie_categories", false));
  el("btnSelectAllSeries").addEventListener("click", () => setAllSelection("series_categories", true));
  el("btnSelectNoneSeries").addEventListener("click", () => setAllSelection("series_categories", false));

  if (el("btnSaveSchedule")) el("btnSaveSchedule").addEventListener("click", () => saveSchedule().catch(err => toast(err.message, "err")));
  if (el("btnRunNow")) el("btnRunNow").addEventListener("click", () => runNow().catch(err => toast(err.message, "err")));

  if (el("btnFilterAllCats")) el("btnFilterAllCats").addEventListener("click", () => setFilter("all"));
  if (el("btnFilterSelectedCats")) el("btnFilterSelectedCats").addEventListener("click", () => setFilter("selected"));

  if (el("btnLoadLiveItems")) el("btnLoadLiveItems").addEventListener("click", () => loadItemsForType("livetv").catch(err => toast(err.message, "err")));
  if (el("btnLoadMovieItems")) el("btnLoadMovieItems").addEventListener("click", () => loadItemsForType("movies").catch(err => toast(err.message, "err")));
  if (el("btnLoadSeriesItems")) el("btnLoadSeriesItems").addEventListener("click", () => loadItemsForType("series").catch(err => toast(err.message, "err")));

  if (el("btnProxyTestJellyfin")) el("btnProxyTestJellyfin").addEventListener("click", () => doProxyTestJellyfin().catch(err => toast(err.message, "err")));
  if (el("btnProxyLoadLibraries")) el("btnProxyLoadLibraries").addEventListener("click", () => doProxyLoadLibraries().catch(err => toast(err.message, "err")));
}

async function init() {
  bindButtons();
  bindSearchInputs();
  await loadProfiles();
  await loadRuntimeConfig();
  await loadReport();
  await loadSchedule();
  renderAllItemLists();
  renderProxyLibraries();
  renderProxyInfo(null);
  renderProxyEndpointInfo();
  await pollStatus();
  setInterval(pollStatus, 2000);
}

window.addEventListener("load", init);