window.AppActions = (() => {
  const { api } = window.AppApi;
  const { el, toast, uniqueById } = window.AppUtils;
  const AppState = window.AppState;
  const Render = window.AppRender;

  function clearLoadedItems(type) {
    const state = AppState.state;

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

  function toggleSection(id) {
    const node = el(id);
    if (!node) return;
    const isHidden = node.style.display === "none";
    node.style.display = isHidden ? "block" : "none";
  }

  function startStatusPolling() {
    if (AppState.statusPollTimer) return;

    AppState.statusPollTimer = setInterval(async () => {
      if (document.hidden) return;
      await pollStatus();
    }, AppState.STATUS_POLL_INTERVAL_MS);
  }

  function stopStatusPolling() {
    if (!AppState.statusPollTimer) return;
    clearInterval(AppState.statusPollTimer);
    AppState.statusPollTimer = null;
  }

  function getConfigFromUi() {
    const state = AppState.state;

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
        jellyfin_api_key: el("proxyJellyfinApiKey")?.value.trim() || "",
        base_path: "/proxy",
        username: el("proxyUsername")?.value.trim() || "",
        password: el("proxyPassword")?.value || ""
      },
      active_profile_name: AppState.state.activeProfile || ""
    };
  }

  function applyConfigToUi(cfg) {
    const state = AppState.state;

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
    if (el("proxyJellyfinApiKey")) el("proxyJellyfinApiKey").value = proxy.jellyfin_api_key || "";
    if (el("proxyUsername")) el("proxyUsername").value = proxy.username || "";
    if (el("proxyPassword")) el("proxyPassword").value = proxy.password || "";

    Render.renderAllLists();
    Render.renderAllItemLists();
    Render.renderProxyLibraries();
    Render.renderProxyEndpointInfo();
  }

  function cleanupSelectionSetsForCurrentItems() {
    const state = AppState.state;

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

  function setFilter(mode) {
    AppState.filterMode = mode === "selected" ? "selected" : "all";
    Render.renderAllLists();
  }

  function setAllSelection(type, value) {
    const state = AppState.state;
    const items = state.catalog[type] || [];
    const setRef = state.selected[type];
    setRef.clear();

    if (value) {
      for (const item of items) setRef.add(String(item.id));
    }

    if (type === "livetv_categories") clearLoadedItems("livetv");
    if (type === "movie_categories") clearLoadedItems("movies");
    if (type === "series_categories") clearLoadedItems("series");

    Render.renderAllLists();
    Render.renderAllItemLists();
    saveRuntimeConfig();
  }

  async function loadProfiles() {
    const state = AppState.state;
    const data = await api("/api/profiles");
    state.profiles = data.profiles || {};

    console.log("[profiles] loaded:", Object.keys(state.profiles || {}));

    const select = el("profileSelect");
    if (!select) return;

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

  function detectActiveProfileFromConfig(cfg) {
    const state = AppState.state;

    if (!cfg || !state.profiles) {
      console.log("[profiles] detect skipped: no cfg or profiles");
      return null;
    }

    for (const [name, profile] of Object.entries(state.profiles)) {
      try {
        const same = JSON.stringify(profile.config) === JSON.stringify(cfg);
        console.log(`[profiles] compare "${name}":`, same);
        if (same) {
          console.log("[profiles] detected active profile:", name);
          return name;
        }
      } catch (err) {
        console.log(`[profiles] compare failed for "${name}":`, err);
      }
    }

    console.log("[profiles] no active profile detected");
    return null;
  }

async function loadRuntimeConfig() {
  try {
    const state = AppState.state;
    const cfg = await api("/api/runtime-config");

    console.log("[runtime-config] loaded:", cfg);

    applyConfigToUi(cfg);

    const activeName = String(cfg.active_profile_name || "").trim();
    if (activeName && state.profiles[activeName]) {
      if (el("profileSelect")) el("profileSelect").value = activeName;
      if (el("profileName")) el("profileName").value = activeName;
      state.activeProfile = activeName;
      console.log("[profiles] active profile from runtime-config:", activeName);
      return;
    }

    const detected = detectActiveProfileFromConfig(cfg);
    if (detected) {
      if (el("profileSelect")) el("profileSelect").value = detected;
      if (el("profileName")) el("profileName").value = detected;
      state.activeProfile = detected;
      console.log("[profiles] detected active profile:", detected);
    } else {
      console.log("[profiles] no active profile detected");
    }
  } catch (err) {
    console.log("[runtime-config] load failed:", err);
  }
}

  async function saveRuntimeConfig() {
    try {
      await api("/api/runtime-config", "POST", getConfigFromUi());
    } catch (_) {}
  }

  async function loadSchedule() {
    try {
      const state = AppState.state;
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
    AppState.state.lastRunningState = true;
    startStatusPolling();
    await pollStatus();
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
    Render.renderAccountInfo(res.account || {});
    await saveRuntimeConfig();
    toast("Verbindung erfolgreich.", "ok");
  }

  async function doLoadCatalog() {
    const state = AppState.state;
    document.getElementById("catSection").style.display = "block";
    const cfg = getConfigFromUi();
    const res = await api("/api/load-catalog", "POST", cfg.connection);
    state.catalog = res.catalog || { livetv_categories: [], movie_categories: [], series_categories: [] };
    Render.renderAccountInfo(res.account || {});
    clearLoadedItems("livetv");
    clearLoadedItems("movies");
    clearLoadedItems("series");
    Render.renderAllLists();
    Render.renderAllItemLists();
    await saveRuntimeConfig();
    toast("Kategorien geladen.", "ok");
  }

  async function loadItemsForType(type) {
    const state = AppState.state;
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
      Render.renderAllItemLists();
      return;
    }

    state.itemLoadState[type] = "loading";
    state.itemLoadInfo[type] = "Lade Inhalte ...";
    Render.renderAllItemLists();

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
      Render.renderAllItemLists();
      await saveRuntimeConfig();
    } catch (err) {
      console.error(err);
      state.items[type] = [];
      state.itemLoadState[type] = "idle";
      state.itemLoadInfo[type] = `Fehler: ${err.message}`;
      Render.renderAllItemLists();
      toast(`Inhalte konnten nicht geladen werden: ${err.message}`, "err");
    }
  }

  async function doProxyTestJellyfin() {
    const payload = {
      base_url: el("proxyJellyfinUrl").value.trim(),
      api_key: el("proxyJellyfinApiKey").value.trim()
    };

    const res = await api("/api/proxy/test-jellyfin", "POST", payload);
    Render.renderProxyInfo(res.info || {});
    Render.renderProxyEndpointInfo();
    await saveRuntimeConfig();
    toast("Jellyfin Verbindung erfolgreich.", "ok");
  }

  async function doProxyLoadLibraries() {
    const state = AppState.state;
    const payload = {
      base_url: el("proxyJellyfinUrl").value.trim(),
      api_key: el("proxyJellyfinApiKey").value.trim()
    };

    const res = await api("/api/proxy/libraries", "POST", payload);
    state.proxy.libraries = res.libraries || [];
    Render.renderProxyLibraries();
    Render.renderProxyEndpointInfo();
    await saveRuntimeConfig();
    toast("Jellyfin Bibliotheken geladen.", "ok");
  }

async function doSaveProfile() {
  const state = AppState.state;
  const name = el("profileName").value.trim();
  if (!name) {
    toast("Bitte Profilnamen eingeben.", "err");
    return;
  }

  const cfg = getConfigFromUi();
  await api("/api/profiles/save", "POST", { name, config: cfg });
  await loadProfiles();

  if (el("profileSelect")) el("profileSelect").value = name;
  if (el("profileName")) el("profileName").value = name;
  state.activeProfile = name;

  await saveRuntimeConfig();

  console.log("[profiles] saved and set active:", name);

  await loadSchedule();
  toast("Profil gespeichert.", "ok");
}

  async function doLoadProfile() {
  const state = AppState.state;
  const name = el("profileSelect").value;

  console.log("[profiles] requested load:", name);

  if (!name || !state.profiles[name]) {
    toast("Bitte ein Profil wählen.", "err");
    return;
  }

  const cfg = state.profiles[name].config || {};

  if (el("profileName")) el("profileName").value = name;
  if (el("profileSelect")) el("profileSelect").value = name;
  state.activeProfile = name;

  applyConfigToUi(cfg);

  clearLoadedItems("livetv");
  clearLoadedItems("movies");
  clearLoadedItems("series");
  Render.renderAllItemLists();

  await loadSchedule();
  await saveRuntimeConfig();

  console.log("[profiles] loaded and set active:", name);

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
      AppState.state.lastRunningState = true;
      startStatusPolling();
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
      const state = AppState.state;
      const status = await api("/api/status");
      const progress = Number(status.progress || 0);

      if (el("progressBar")) {
        el("progressBar").style.width = `${Math.max(0, Math.min(100, progress))}%`;
      }
      if (el("statusText")) {
        el("statusText").textContent = `${status.phase || "idle"} - ${status.message || ""}`;
      }

      const logs = Array.isArray(status.logs) ? status.logs : [];
      if (el("logBox")) {
        el("logBox").textContent = logs.join("\n");
      }

      const btnCancel = el("btnCancelExport");
      if (btnCancel) {
        btnCancel.disabled = !status.running;
      }

      const isRunning = !!status.running;

      if (state.lastRunningState && !isRunning) {
        await loadReport();
        await loadSchedule();
        await loadHealth();
        stopStatusPolling();

        if (status.phase === "cancelled") {
          toast("Export abgebrochen.", "warn");
        } else if (status.phase === "done") {
          toast("Export abgeschlossen.", "ok");
        } else if (status.phase === "failed") {
          toast("Export fehlgeschlagen.", "err");
        }
      }

      if (isRunning && !state.lastRunningState) {
        startStatusPolling();
      }

      state.lastRunningState = isRunning;
    } catch (_) {}
  }

  async function loadReport() {
    try {
      const report = await api("/api/report");
      Render.renderSummary(report || {});
      Render.renderChanges(report || {});
      if (report?.account) Render.renderAccountInfo(report.account);
    } catch (_) {}
  }

  async function clearReport() {
    await api("/api/report/clear", "POST", {});
    await loadReport();
    toast("Report geleert.", "ok");
  }

  async function loadHealth() {
    try {
      const health = await api("/api/health");
      Render.renderHealth(health || {});
    } catch (err) {
      Render.renderHealth({
        ok: false,
        time: "",
        scheduler_running: false,
        export_status: {},
        checks: {
          xmltv: { ok: false, error: err.message },
          jellyfin: { ok: false, error: err.message }
        }
      });
    }
  }

  return {
    clearLoadedItems,
    startStatusPolling,
    stopStatusPolling,
    getConfigFromUi,
    applyConfigToUi,
    cleanupSelectionSetsForCurrentItems,
    setFilter,
    toggleSection,
    setAllSelection,
    loadProfiles,
    loadRuntimeConfig,
    saveRuntimeConfig,
    loadSchedule,
    saveSchedule,
    runNow,
    cancelExport,
    doTestConnection,
    doLoadCatalog,
    loadItemsForType,
    doProxyTestJellyfin,
    doProxyLoadLibraries,
    doSaveProfile,
    doLoadProfile,
    doDeleteProfile,
    doStartExport,
    doResetOutput,
    pollStatus,
    loadReport,
    clearReport,
    loadHealth
  };
})();