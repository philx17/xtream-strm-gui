window.AppInit = (() => {
  const { el, toast } = window.AppUtils;
  const { api } = window.AppApi;
  const Actions = window.AppActions;
  const Render = window.AppRender;

async function loadHealthGUI() {
  const { el } = window.AppUtils;

  function setPill(id, text, cls = "") {
    const node = el(id);
    if (!node) return;
    node.textContent = text;
    node.className = cls ? `status-pill ${cls}` : "status-pill";
  }

  function setMeta(id, text) {
    const node = el(id);
    if (!node) return;
    node.textContent = text;
    node.className = "meta-pill";
  }

  try {
    const data = await api("/healthz");

    const service = data?.service || {};
    const proxy = data?.proxy || {};
    const scheduler = data?.scheduler || {};
    const exportInfo = data?.export || {};

    // Proxy
    if (service.alive && proxy.configured) {
      setPill("statusProxy", "Proxy: Online", "status-ok");
    } else if (service.alive && !proxy.configured) {
      setPill("statusProxy", "Proxy: Incomplete", "status-warn");
    } else {
      setPill("statusProxy", "Proxy: Offline", "status-off");
    }

    // Export
    if (exportInfo.running) {
      setPill("statusExport", `Export: ${exportInfo.phase || "running"}`, "status-warn");
    } else if (exportInfo.last_error) {
      setPill("statusExport", "Export: Error", "status-off");
    } else {
      setPill("statusExport", `Export: ${exportInfo.phase || "idle"}`, "status-ok");
    }

    // Scheduler
    if (scheduler.available && scheduler.enabled) {
      setPill("statusScheduler", "Scheduler: Active", "status-ok");
    } else if (scheduler.available && !scheduler.enabled) {
      setPill("statusScheduler", "Scheduler: Off", "status-off");
    } else {
      setPill("statusScheduler", "Scheduler: Unavailable", "status-off");
    }

    // Meta
    setMeta("metaUptime", `Uptime: ${service.uptime_human || "-"}`);
    setMeta("metaLastExport", `Last export: ${exportInfo.finished_at || "-"}`);
    setMeta("metaNextExport", `Next export: ${scheduler.next_run || "-"}`);

    // optional in state ablegen
    if (window.AppState?.state) {
      window.AppState.state.health = data || null;
    }

  } catch (err) {
    setPill("statusProxy", "Proxy: Offline", "status-off");
    setPill("statusExport", "Export: Unknown", "status-off");
    setPill("statusScheduler", "Scheduler: Unknown", "status-off");

    setMeta("metaUptime", "Uptime: -");
    setMeta("metaLastExport", "Last export: -");
    setMeta("metaNextExport", "Next export: -");

    if (window.AppState?.state) {
      window.AppState.state.health = {
        ok: false,
        error: err.message
      };
    }
  }
}

  function updateScheduleModeVisibility() {
    const mode = el("scheduleMode")?.value || "daily";
    const weekdayWrap = el("scheduleWeekdayWrap");
    const intervalWrap = el("scheduleIntervalWrap");
    if (weekdayWrap) {
      weekdayWrap.style.display = mode === "weekly" ? "block" : "none";
    }
    if (intervalWrap) {
      intervalWrap.style.display = mode === "interval" ? "block" : "none";
    }
  }

  function bindSearchInputs() {
    [
      "searchLive", "searchMovies", "searchSeries",
      "searchLiveItems", "searchMovieItems", "searchSeriesItems"
    ].forEach(id => {
      const node = el(id);
      if (!node) return;
      node.addEventListener("input", () => {
        Render.renderAllLists();
        Render.renderAllItemLists();
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
        Render.renderProxyEndpointInfo();
      });
    });

    el("scheduleMode")?.addEventListener("change", updateScheduleModeVisibility);
  }

  function bindButtons() {
    el("btnTestConnection")?.addEventListener("click", () => Actions.doTestConnection().catch(err => toast(err.message, "err")));
    el("btnLoadCatalog")?.addEventListener("click", () => Actions.doLoadCatalog().catch(err => toast(err.message, "err")));
    el("btnSaveProfile")?.addEventListener("click", () => Actions.doSaveProfile().catch(err => toast(err.message, "err")));
    el("btnLoadProfile")?.addEventListener("click", () => Actions.doLoadProfile().catch(err => toast(err.message, "err")));
    el("btnDeleteProfile")?.addEventListener("click", () => Actions.doDeleteProfile().catch(err => toast(err.message, "err")));
    el("btnStartExport")?.addEventListener("click", () => Actions.doStartExport().catch(err => toast(err.message, "err")));
    el("btnCancelExport")?.addEventListener("click", () => Actions.cancelExport().catch(err => toast(err.message, "err")));
    el("btnResetOutput")?.addEventListener("click", () => Actions.doResetOutput().catch(err => toast(err.message, "err")));
    el("btnClearReport")?.addEventListener("click", () => Actions.clearReport().catch(err => toast(err.message, "err")));

    el("btnSelectAllLive")?.addEventListener("click", () => Actions.setAllSelection("livetv_categories", true));
    el("btnSelectNoneLive")?.addEventListener("click", () => Actions.setAllSelection("livetv_categories", false));
    el("btnSelectAllMovies")?.addEventListener("click", () => Actions.setAllSelection("movie_categories", true));
    el("btnSelectNoneMovies")?.addEventListener("click", () => Actions.setAllSelection("movie_categories", false));
    el("btnSelectAllSeries")?.addEventListener("click", () => Actions.setAllSelection("series_categories", true));
    el("btnSelectNoneSeries")?.addEventListener("click", () => Actions.setAllSelection("series_categories", false));

    el("btnSaveSchedule")?.addEventListener("click", () => Actions.saveSchedule().catch(err => toast(err.message, "err")));
    el("btnRunNow")?.addEventListener("click", () => Actions.runNow().catch(err => toast(err.message, "err")));

    el("btnFilterAllCats")?.addEventListener("click", () => Actions.setFilter("all"));
    el("btnFilterSelectedCats")?.addEventListener("click", () => Actions.setFilter("selected"));

    el("btnLoadLiveItems")?.addEventListener("click", () => Actions.loadItemsForType("livetv").catch(err => toast(err.message, "err")));
    el("btnLoadMovieItems")?.addEventListener("click", () => Actions.loadItemsForType("movies").catch(err => toast(err.message, "err")));
    el("btnLoadSeriesItems")?.addEventListener("click", () => Actions.loadItemsForType("series").catch(err => toast(err.message, "err")));

    el("btnProxyTestJellyfin")?.addEventListener("click", () => Actions.doProxyTestJellyfin().catch(err => toast(err.message, "err")));
    el("btnProxyLoadLibraries")?.addEventListener("click", () => Actions.doProxyLoadLibraries().catch(err => toast(err.message, "err")));
  }

  async function init() {
    window.toggleSection = Actions.toggleSection;

    bindButtons();
    bindSearchInputs();

    await Actions.loadProfiles();
    await Actions.loadRuntimeConfig();
    await Actions.loadReport();
    await Actions.loadSchedule();
    await Actions.loadHealth();
    Render.renderAllItemLists();
    Render.renderProxyLibraries();
    Render.renderProxyInfo(null);
    Render.renderProxyEndpointInfo();
    updateScheduleModeVisibility();
    await Actions.pollStatus();
    await loadHealthGUI();
    // alle 5 Sekunden aktualisieren

    setInterval(loadHealthGUI, 20000);
    }

  window.addEventListener("load", init);

  return { init };
})();