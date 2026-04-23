window.AppRender = (() => {
  const { el, escapeHtml, sortByName, categoryNameMap } = window.AppUtils;
  const AppState = window.AppState;

  function renderAccountInfo(account) {
    const state = AppState.state;
    state.account = account || null;

    const box = el("accountInfo");
    if (!box) return;
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
    if (!container) return;
    container.innerHTML = "";

    const term = (searchTerm || "").toLowerCase().trim();

    const filtered = sortByName(items).filter(item => {
      const matchesSearch = (item.name || "").toLowerCase().includes(term);
      const matchesFilter = AppState.filterMode === "selected"
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

        window.AppActions.clearLoadedItems(type);
        renderAllLists();
        renderAllItemLists();
        await window.AppActions.saveRuntimeConfig();
      });

      container.appendChild(row);
    }
  }

  function getFilteredItemsBySelectedCategories(type) {
    const state = AppState.state;

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
    const state = AppState.state;
    const container = el(listId);
    if (!container) return;
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
          await window.AppActions.saveRuntimeConfig();
        });

        container.appendChild(row);
      }
    }
  }

  function renderItemLoadInfos() {
    const state = AppState.state;
    if (el("liveItemsLoadInfo")) el("liveItemsLoadInfo").textContent = state.itemLoadInfo.livetv;
    if (el("movieItemsLoadInfo")) el("movieItemsLoadInfo").textContent = state.itemLoadInfo.movies;
    if (el("seriesItemsLoadInfo")) el("seriesItemsLoadInfo").textContent = state.itemLoadInfo.series;
  }

  function renderAllLists() {
    const state = AppState.state;

    renderCategoryList("liveList", state.catalog.livetv_categories, state.selected.livetv_categories, el("searchLive")?.value || "", "livetv");
    renderCategoryList("movieList", state.catalog.movie_categories, state.selected.movie_categories, el("searchMovies")?.value || "", "movies");
    renderCategoryList("seriesList", state.catalog.series_categories, state.selected.series_categories, el("searchSeries")?.value || "", "series");

    if (el("liveSelectedCount")) el("liveSelectedCount").textContent = `${state.selected.livetv_categories.size} ausgewählt`;
    if (el("movieSelectedCount")) el("movieSelectedCount").textContent = `${state.selected.movie_categories.size} ausgewählt`;
    if (el("seriesSelectedCount")) el("seriesSelectedCount").textContent = `${state.selected.series_categories.size} ausgewählt`;

    renderItemLoadInfos();
  }

  function renderAllItemLists() {
    const state = AppState.state;

    const liveItems = getFilteredItemsBySelectedCategories("livetv");
    const movieItems = getFilteredItemsBySelectedCategories("movies");
    const seriesItems = getFilteredItemsBySelectedCategories("series");

    renderGroupedItemSelector(
      "liveItemsList",
      liveItems,
      state.selected.livetv_exclude_ids,
      el("searchLiveItems")?.value || "",
      "livetv"
    );

    renderGroupedItemSelector(
      "movieItemsList",
      movieItems,
      state.selected.movie_exclude_ids,
      el("searchMovieItems")?.value || "",
      "movies"
    );

    renderGroupedItemSelector(
      "seriesItemsList",
      seriesItems,
      state.selected.series_exclude_ids,
      el("searchSeriesItems")?.value || "",
      "series"
    );

    if (el("liveExcludedCount")) el("liveExcludedCount").textContent = `${state.selected.livetv_exclude_ids.size} ausgeschlossen`;
    if (el("movieExcludedCount")) el("movieExcludedCount").textContent = `${state.selected.movie_exclude_ids.size} ausgeschlossen`;
    if (el("seriesExcludedCount")) el("seriesExcludedCount").textContent = `${state.selected.series_exclude_ids.size} ausgeschlossen`;

    renderItemLoadInfos();
  }

  function renderProxyInfo(info) {
    const state = AppState.state;
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
    const state = AppState.state;
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
        await window.AppActions.saveRuntimeConfig();
      });

      container.appendChild(row);
    }

    renderProxySelectionInfo();
  }

  function renderProxySelectionInfo() {
    const info = el("proxyLibrariesSelectedCount");
    if (!info) return;
    info.textContent = `${AppState.state.selected.proxy_library_ids.size} Bibliotheken ausgewählt`;
  }

  function renderProxyEndpointInfo() {
    const box = el("proxyEndpointInfo");
    if (!box) return;

    const user = el("proxyUsername")?.value.trim() || "-";
    const pass = el("proxyPassword")?.value || "-";
    const proxyUrl = `${window.location.origin}/proxy/player_api.php`;
    const localJf = el("proxyJellyfinUrl")?.value.trim() || "-";
    const extJf = el("proxyJellyfinExternalUrl")?.value.trim() || "-";
    const epgUrl = `${window.location.origin}/xmltv.php`;

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
        <div class="k">XMLTV / EPG</div>
        <div class="v">${escapeHtml(epgUrl)}</div>
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
    if (!box) return;
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
    if (!addedList || !removedList) return;

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

  function renderHealth(health) {
    const state = AppState.state;
    state.health = health || null;

    const box = el("healthInfo");
    if (!box) return;

    if (!health) {
      box.innerHTML = `<div class="small">Noch keine Health-Daten geladen.</div>`;
      return;
    }

    const checks = health.checks || {};
    const xmltv = checks.xmltv || {};
    const jellyfin = checks.jellyfin || {};
    const exportStatus = health.export_status || {};

    box.innerHTML = `
      <div class="info-item">
        <div class="k">Gesamtstatus</div>
        <div class="v">${escapeHtml(health.ok ? "OK" : "Fehler")}</div>
      </div>
      <div class="info-item">
        <div class="k">Zeit</div>
        <div class="v">${escapeHtml(health.time || "-")}</div>
      </div>
      <div class="info-item">
        <div class="k">Scheduler</div>
        <div class="v">${escapeHtml(health.scheduler_running ? "Läuft" : "Aus")}</div>
      </div>
      <div class="info-item">
        <div class="k">Exportphase</div>
        <div class="v">${escapeHtml(exportStatus.phase || "-")}</div>
      </div>
      <div class="info-item">
        <div class="k">XMLTV</div>
        <div class="v">${escapeHtml(xmltv.ok ? `OK (${xmltv.status_code || "-"})` : (xmltv.error || "Fehler"))}</div>
      </div>
      <div class="info-item">
        <div class="k">Jellyfin</div>
        <div class="v">${escapeHtml(jellyfin.ok ? `${jellyfin.server_name || "OK"} ${jellyfin.version || ""}` : (jellyfin.error || "Fehler"))}</div>
      </div>
    `;
  }

  return {
    renderAccountInfo,
    renderCategoryList,
    getFilteredItemsBySelectedCategories,
    renderGroupedItemSelector,
    renderItemLoadInfos,
    renderAllLists,
    renderAllItemLists,
    renderProxyInfo,
    renderProxyLibraries,
    renderProxySelectionInfo,
    renderProxyEndpointInfo,
    renderSummary,
    renderChanges,
    renderHealth
  };
})();