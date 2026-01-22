// ===============================
// app.js (FINAL) - ONE GLOBAL FILTER for EVERYTHING + Pending Marking
// ===============================

let cfg = null;
let catalog = null;

let currentTab = "livetv";
let selectedLiveCat = null;
let selectedMovieCat = null;
let selectedShow = null;

// ---------- GLOBAL: one filter for EVERYTHING ----------
let uiFilterMode = "all"; // default "Alle"

function setGlobalFilter(val){
  uiFilterMode = val || "all";
}

function getGlobalFilter(){
  return uiFilterMode || "all";
}

// ---------- Saved snapshot for "pending" ----------
let savedAllowSnapshot = null; // deep clone of cfg.allow after last save/load

function snapshotSavedAllow(){
  try{
    savedAllowSnapshot = JSON.parse(JSON.stringify(cfg.allow || {}));
  }catch(e){
    savedAllowSnapshot = null;
  }
}

function ensureSnapshot(){
  if(!savedAllowSnapshot) snapshotSavedAllow();
}

// pending helpers
function setHas(setLike, v){
  return new Set(setLike || []).has(v);
}

function pendingForTitle(kind, title){
  ensureSnapshot();
  const now = setHas(cfg?.allow?.[kind]?.titles, title);
  const saved = setHas(savedAllowSnapshot?.[kind]?.titles, title);
  return now !== saved;
}

function pendingForCategory(kind, category){
  ensureSnapshot();
  const nowFull = setHas(cfg?.allow?.[kind]?.full_categories, category);
  const savedFull = setHas(savedAllowSnapshot?.[kind]?.full_categories, category);
  if(nowFull !== savedFull) return true;

  const items = getCategoryItems(kind, category);
  for(const n of items){
    if(pendingForTitle(kind, n)) return true;
  }
  return false;
}

function pendingForShow(show){
  ensureSnapshot();
  const nowFull = setHas(cfg?.allow?.series?.full_shows, show);
  const savedFull = setHas(savedAllowSnapshot?.series?.full_shows, show);
  if(nowFull !== savedFull) return true;

  const nowShow = setHas(cfg?.allow?.series?.shows, show);
  const savedShow = setHas(savedAllowSnapshot?.series?.shows, show);
  if(nowShow !== savedShow) return true;

  const eps = getShowEpisodeNames(show);
  for(const n of eps){
    const now = setHas(cfg?.allow?.series?.titles, n);
    const saved = setHas(savedAllowSnapshot?.series?.titles, n);
    if(now !== saved) return true;
  }
  return false;
}

function pendingForEpisode(epTitle){
  ensureSnapshot();
  const now = setHas(cfg?.allow?.series?.titles, epTitle);
  const saved = setHas(savedAllowSnapshot?.series?.titles, epTitle);
  return now !== saved;
}

// ---------- DOM helpers ----------
function el(id){ return document.getElementById(id); }

function sortAlphaDE(arr){
  return (arr || []).sort((a,b)=> a.localeCompare(b, "de", {sensitivity:"base"}));
}

function getCategoryItems(kind, category){
  const cats = (catalog?.[kind]?.categories) || {};
  return (cats[category] || []).map(it => (it.tvg_name || it.title)).filter(Boolean);
}

function getShowEpisodeNames(show){
  const s = catalog?.series?.shows?.[show];
  if(!s) return [];
  const out = [];
  const seasons = s.seasons || {};
  Object.keys(seasons).forEach(sk=>{
    (seasons[sk] || []).forEach(ep=>{
      const n = ep.tvg_name || ep.title;
      if(n) out.push(n);
    });
  });
  return out;
}

function categoryIsFullSticky(kind, category){
  const fullSet = new Set(cfg.allow[kind].full_categories || []);
  return fullSet.has(category);
}

function showIsFullSticky(show){
  const set = new Set(cfg.allow.series.full_shows || []);
  return set.has(show);
}

function categorySelectionState(kind, category){
  // returns: "none" | "partial" | "all"
  const items = getCategoryItems(kind, category);
  if(items.length === 0) return "none";

  const titles = new Set(cfg.allow[kind].titles || []);
  let selectedCount = 0;
  for(const n of items){
    if(titles.has(n)) selectedCount++;
  }
  if(selectedCount === 0) return "none";
  if(selectedCount === items.length) return "all";
  return "partial";
}

function showSelectionState(show){
  // returns: "none" | "partial" | "all"
  const eps = getShowEpisodeNames(show);
  if(eps.length === 0) return "none";

  const titles = new Set(cfg.allow.series.titles || []);
  let selectedCount = 0;
  for(const n of eps){
    if(titles.has(n)) selectedCount++;
  }
  if(selectedCount === 0) return "none";
  if(selectedCount === eps.length) return "all";
  return "partial";
}

// ---------- API ----------
async function apiGet(path){
  const r = await fetch(path);
  const j = await r.json();
  if(!r.ok) throw new Error(j.error || j.detail || "API error");
  return j;
}

async function apiPost(path, body){
  const r = await fetch(path, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify(body||{})
  });
  const j = await r.json();
  if(!r.ok) throw new Error(j.error || j.detail || "API error");
  return j;
}

function setStatus(msg){ el("status").textContent = msg; }
function setStatusTop(msg){ el("statusTop").textContent = msg; }

// ---------- Tabs ----------
function setTab(tab){
  currentTab = tab;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab===tab));
  el("panel_livetv").style.display = tab==="livetv" ? "block":"none";
  el("panel_movies").style.display = tab==="movies" ? "block":"none";
  el("panel_series").style.display = tab==="series" ? "block":"none";
}

// ---------- Config shape ----------
function ensureAllow(){
  cfg.allow = cfg.allow || {};
  cfg.allow.livetv = cfg.allow.livetv || {categories:[], titles:[], full_categories:[]};
  cfg.allow.movies = cfg.allow.movies || {categories:[], titles:[], full_categories:[]};
  cfg.allow.series = cfg.allow.series || {shows:[], titles:[], full_shows:[]};

  cfg.allow.livetv.full_categories = cfg.allow.livetv.full_categories || [];
  cfg.allow.movies.full_categories = cfg.allow.movies.full_categories || [];
  cfg.allow.series.full_shows = cfg.allow.series.full_shows || [];
  cfg.allow.series.shows = cfg.allow.series.shows || [];
  cfg.allow.series.titles = cfg.allow.series.titles || [];
}

// ---------- Form ----------
function loadForm(){
  el("base_url").value = cfg.xtream.base_url || "";
  el("username").value = cfg.xtream.username || "";
  el("password").value = cfg.xtream.password || "";
  el("output").value = cfg.xtream.output || "ts";
  el("out_dir").value = cfg.paths.out_dir || "/output";

  el("sync_delete").checked = !!cfg.sync.sync_delete;
  el("prune_sidecars").checked = !!cfg.sync.prune_sidecars;

  el("sched_enabled").checked = !!cfg.schedule.enabled;
  el("sched_time").value = cfg.schedule.daily_time || "03:30";
}

function saveFormIntoCfg(){
  cfg.xtream.base_url = el("base_url").value.trim();
  cfg.xtream.username = el("username").value.trim();
  cfg.xtream.password = el("password").value;
  cfg.xtream.output = (el("output").value || "ts").trim();

  cfg.paths.out_dir = el("out_dir").value.trim() || "/output";

  cfg.sync.sync_delete = el("sync_delete").checked;
  cfg.sync.prune_sidecars = el("prune_sidecars").checked;

  cfg.schedule.enabled = el("sched_enabled").checked;
  cfg.schedule.daily_time = (el("sched_time").value || "03:30").trim();
}

function fmtRemaining(sec){
  if(sec === null || sec === undefined) return "–";
  if(sec <= 0) return "abgelaufen";
  const d = Math.floor(sec/86400);
  const h = Math.floor((sec%86400)/3600);
  const m = Math.floor((sec%3600)/60);
  if(d>0) return `${d}d ${h}h`;
  if(h>0) return `${h}h ${m}m`;
  return `${m}m`;
}

function renderConnStatus(test){
  const box = el("conn_box");
  box.innerHTML = "";

  const add = (k,v)=>{
    const d = document.createElement("div");
    d.className = "kv";
    d.innerHTML = `<b>${k}</b><span>${v}</span>`;
    box.appendChild(d);
  };

  add("Verbindung", test.ok ? `<span class='ok'>OK</span>` : `<span class='bad'>FEHLER</span>`);
  add("player_api.php", test.player_api ? "ja" : "nein");

  if(!test.ok){
    add("Fehler", (test.error||"–"));
    return;
  }

  if(test.user_info){
    add("Status", test.user_info.status || "–");
    add("Verbindungen", `${test.user_info.active_cons ?? "?"} / ${test.user_info.max_connections ?? "?"}`);
    add("Ablaufdatum", test.user_info.exp_iso ? new Date(test.user_info.exp_iso).toLocaleString() : "–");
    add("Restlaufzeit", fmtRemaining(test.user_info.remaining_seconds));
  }
}

// ---------- Layout tweaks ----------
function reorderItemsControls(kind){
  // Move .actions above search input inside items column
  const input = el(`search_${kind}_items`);
  if(!input) return;
  const parent = input.parentElement;
  if(!parent) return;
  const actions = parent.querySelector(".actions");
  if(!actions) return;
  parent.insertBefore(actions, input);
}

// ---------- GLOBAL filter UI injection ----------
function makeGlobalFilterSelect(onChange){
  const sel = document.createElement("select");
  sel.style.maxWidth = "260px";
  sel.style.padding = "6px";
  sel.innerHTML = `
    <option value="all">Alle</option>
    <option value="unselected_or_pending">Nur nicht ausgewählt + Pending</option>
    <option value="selected">Nur ausgewählt</option>
    <option value="unselected">Nur nicht ausgewählt</option>
    <option value="pending">Nur Pending (noch nicht gespeichert)</option>
  `;
  sel.value = getGlobalFilter();
  sel.addEventListener("change", ()=>{
    setGlobalFilter(sel.value);
    onChange && onChange(sel.value);
  });
  return sel;
}

function injectGlobalFilterAboveTabs(){
  const tab = document.querySelector(".tab");
  if(!tab) return;

  const tabsRow = tab.parentElement;
  if(!tabsRow) return;

  if(tabsRow.dataset.hasGlobalFilter === "1") return;
  tabsRow.dataset.hasGlobalFilter = "1";

  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.gap = "10px";
  wrap.style.alignItems = "center";
  wrap.style.flexWrap = "wrap";
  wrap.style.margin = "0 0 10px";

  const label = document.createElement("span");
  label.className = "small muted";
  label.textContent = "Globaler Filter:";
  wrap.appendChild(label);

  const sel = makeGlobalFilterSelect(()=>{
    if(!catalog) return;
    renderAll(); // apply everywhere
  });
  wrap.appendChild(sel);

  tabsRow.parentElement.insertBefore(wrap, tabsRow);
}

// ---------- Bulk helpers ----------
function setAllCategories(kind, enabled){
  const cats = catalog?.[kind]?.categories || {};
  const keys = Object.keys(cats);

  const fullSet = new Set(cfg.allow[kind].full_categories || []);
  let titles = new Set(cfg.allow[kind].titles || []);

  if(enabled){
    keys.forEach(k=>{
      fullSet.add(k);
      getCategoryItems(kind, k).forEach(n => titles.add(n));
    });
  } else {
    keys.forEach(k=>{
      fullSet.delete(k);
      getCategoryItems(kind, k).forEach(n => titles.delete(n));
    });
  }

  cfg.allow[kind].full_categories = Array.from(fullSet);
  cfg.allow[kind].titles = Array.from(titles);

  renderCats(kind);
  renderItems(kind);
}

function setAllShows(enabled){
  const shows = catalog?.series?.shows || {};
  const keys = Object.keys(shows);

  let full = new Set(cfg.allow.series.full_shows || []);
  let titles = new Set(cfg.allow.series.titles || []);
  let allowedShows = new Set(cfg.allow.series.shows || []);

  if(enabled){
    keys.forEach(show=>{
      full.add(show);
      allowedShows.add(show);
      getShowEpisodeNames(show).forEach(n => titles.add(n));
    });
  } else {
    keys.forEach(show=>{
      full.delete(show);
      allowedShows.delete(show);
      getShowEpisodeNames(show).forEach(n => titles.delete(n));
    });
  }

  cfg.allow.series.full_shows = Array.from(full);
  cfg.allow.series.shows = Array.from(allowedShows);
  cfg.allow.series.titles = Array.from(titles);

  renderShows();
  renderEpisodes();
}

function setAllEpisodesForSelectedShow(enabled){
  if(!selectedShow) return;
  const eps = getShowEpisodeNames(selectedShow);

  let titles = new Set(cfg.allow.series.titles || []);
  let full = new Set(cfg.allow.series.full_shows || []);
  let allowedShows = new Set(cfg.allow.series.shows || []);

  if(enabled){
    eps.forEach(n => titles.add(n));
    full.add(selectedShow);
    allowedShows.add(selectedShow);
  } else {
    eps.forEach(n => titles.delete(n));
    full.delete(selectedShow);
    allowedShows.delete(selectedShow);
  }

  cfg.allow.series.titles = Array.from(titles);
  cfg.allow.series.full_shows = Array.from(full);
  cfg.allow.series.shows = Array.from(allowedShows);

  renderShows();
  renderEpisodes();
}

// ---------- filtering + pending marking ----------
function passFilter(mode, isSelected, isPending){
  if(mode === "selected") return !!isSelected;
  if(mode === "unselected") return !isSelected;
  if(mode === "pending") return !!isPending;
  if(mode === "unselected_or_pending") return (!isSelected) || (!!isPending);
  return true; // all
}

function markRowPending(row, isPending){
  if(!isPending) return;
  row.style.borderLeft = "4px solid #f2c94c";
  row.style.paddingLeft = "8px";
  row.title = "Pending: Auswahl noch nicht gespeichert";
}

// ---- LiveTV/Movies: Categories + Items ----
function renderCats(kind){
  const box = el(kind + "_cats");
  box.innerHTML = "";
  const search = el("search_" + kind + "_cat").value.trim().toLowerCase();
  const mode = getGlobalFilter(); // GLOBAL

  const cats = (catalog?.[kind]?.categories) || {};
  const keys = sortAlphaDE(Object.keys(cats));

  keys.forEach(k=>{
    if(search && !k.toLowerCase().includes(search)) return;

    const count = (cats[k] || []).length;

    const isFullSticky = categoryIsFullSticky(kind, k);
    const state = categorySelectionState(kind, k);
    const checked = isFullSticky || (state === "all");
    const indeterminate = (!checked && state === "partial");

    const isPending = pendingForCategory(kind, k);

    if(!passFilter(mode, checked || indeterminate, isPending)) return;

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.justifyContent="space-between";
    row.style.gap="10px";
    row.style.padding="6px 0";

    markRowPending(row, isPending);

    const left = document.createElement("div");
    left.style.display="flex";
    left.style.alignItems="center";
    left.style.gap="8px";

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;
    cb.indeterminate = indeterminate;

    cb.addEventListener("change", ()=>{
      const fullSet = new Set(cfg.allow[kind].full_categories || []);
      const items = getCategoryItems(kind, k);
      let titles = new Set(cfg.allow[kind].titles || []);

      if(cb.checked){
        fullSet.add(k);
        items.forEach(n => titles.add(n));
      } else {
        fullSet.delete(k);
        items.forEach(n => titles.delete(n));
      }

      cfg.allow[kind].full_categories = Array.from(fullSet);
      cfg.allow[kind].titles = Array.from(titles);

      renderCats(kind);
      renderItems(kind);
    });

    const name = document.createElement("span");
    name.textContent = k;

    const pill = document.createElement("span");
    pill.className="pill";
    pill.textContent = count;

    left.appendChild(cb);
    left.appendChild(name);

    row.appendChild(left);
    row.appendChild(pill);

    row.addEventListener("click", (e)=>{
      if(e.target.tagName.toLowerCase()==="input") return;
      if(kind==="livetv") selectedLiveCat = k;
      if(kind==="movies") selectedMovieCat = k;
      renderItems(kind);
    });

    box.appendChild(row);
  });
}

function renderItems(kind){
  const box = el(kind + "_items");
  box.innerHTML = "";
  const search = el("search_" + kind + "_items").value.trim().toLowerCase();
  const mode = getGlobalFilter(); // GLOBAL

  let catKey = null;
  if(kind==="livetv") catKey = selectedLiveCat;
  if(kind==="movies") catKey = selectedMovieCat;

  const cats = catalog?.[kind]?.categories || {};
  const items = catKey ? (cats[catKey] || []) : [];

  if(!catKey){
    box.innerHTML = `<div class="small muted">Wähle links eine Kategorie.</div>`;
    return;
  }

  const isFullSticky = categoryIsFullSticky(kind, catKey);

  items.sort((a,b)=>{
    const an = (a.tvg_name||a.title||"");
    const bn = (b.tvg_name||b.title||"");
    return an.localeCompare(bn, "de", {sensitivity:"base"});
  });

  items.forEach(it=>{
    const name = it.tvg_name || it.title;
    if(!name) return;
    if(search && !name.toLowerCase().includes(search)) return;

    const checked = isFullSticky || (cfg.allow[kind].titles || []).includes(name);
    const isPending = pendingForTitle(kind, name);

    if(!passFilter(mode, checked, isPending)) return;

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.gap="8px";
    row.style.padding="6px 0";

    markRowPending(row, isPending);

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;

    cb.addEventListener("change", ()=>{
      const itemsInCat = getCategoryItems(kind, catKey);
      let titles = new Set(cfg.allow[kind].titles || []);
      let fullSet = new Set(cfg.allow[kind].full_categories || []);

      if(isFullSticky && !cb.checked){
        fullSet.delete(catKey);
        itemsInCat.forEach(n => { if(n !== name) titles.add(n); });
        titles.delete(name);
      } else {
        if(cb.checked) titles.add(name); else titles.delete(name);
      }

      const selectedCount = itemsInCat.reduce((acc, n)=> acc + (titles.has(n) ? 1 : 0), 0);
      if(itemsInCat.length > 0 && selectedCount === itemsInCat.length){
        fullSet.add(catKey);
      } else {
        fullSet.delete(catKey);
      }

      cfg.allow[kind].titles = Array.from(titles);
      cfg.allow[kind].full_categories = Array.from(fullSet);

      renderCats(kind);
      renderItems(kind);
    });

    const label = document.createElement("span");
    label.textContent = name;

    row.appendChild(cb);
    row.appendChild(label);
    box.appendChild(row);
  });
}

// ---- SERIES ----
function renderShows(){
  const box = el("series_shows");
  box.innerHTML = "";
  const search = el("search_series_show").value.trim().toLowerCase();
  const mode = getGlobalFilter(); // GLOBAL

  const shows = catalog?.series?.shows || {};
  const keys = sortAlphaDE(Object.keys(shows));

  keys.forEach(show=>{
    if(search && !show.toLowerCase().includes(search)) return;

    const total = shows[show]?.total ?? 0;

    const sticky = showIsFullSticky(show);
    const state = showSelectionState(show);

    const checked = sticky || (state === "all");
    const indeterminate = (!checked && state === "partial");

    const isPending = pendingForShow(show);

    if(!passFilter(mode, checked || indeterminate, isPending)) return;

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.justifyContent="space-between";
    row.style.gap="10px";
    row.style.padding="6px 0";

    markRowPending(row, isPending);

    const left = document.createElement("div");
    left.style.display="flex";
    left.style.alignItems="center";
    left.style.gap="8px";

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;
    cb.indeterminate = indeterminate;

    cb.addEventListener("change", ()=>{
      let full = new Set(cfg.allow.series.full_shows || []);
      let titles = new Set(cfg.allow.series.titles || []);
      let allowedShows = new Set(cfg.allow.series.shows || []);

      const eps = getShowEpisodeNames(show);

      if(cb.checked){
        full.add(show);
        allowedShows.add(show);
        eps.forEach(n => titles.add(n));
      } else {
        full.delete(show);
        allowedShows.delete(show);
        eps.forEach(n => titles.delete(n));
      }

      cfg.allow.series.full_shows = Array.from(full);
      cfg.allow.series.shows = Array.from(allowedShows);
      cfg.allow.series.titles = Array.from(titles);

      renderShows();
      renderEpisodes();
    });

    const name = document.createElement("span");
    name.textContent = show;

    const pill = document.createElement("span");
    pill.className="pill";
    pill.textContent = total;

    left.appendChild(cb);
    left.appendChild(name);

    row.appendChild(left);
    row.appendChild(pill);

    row.addEventListener("click", (e)=>{
      if(e.target.tagName.toLowerCase()==="input") return;
      selectedShow = show;
      renderEpisodes();
    });

    box.appendChild(row);
  });
}

function renderEpisodes(){
  const box = el("series_eps");
  box.innerHTML = "";
  const search = el("search_series_eps").value.trim().toLowerCase();
  const mode = getGlobalFilter(); // GLOBAL

  if(!selectedShow){
    box.innerHTML = `<div class="small muted">Wähle links eine Show.</div>`;
    return;
  }

  const showObj = catalog?.series?.shows?.[selectedShow];
  if(!showObj){
    box.innerHTML = `<div class="small muted">Show nicht gefunden.</div>`;
    return;
  }

  const seasons = showObj.seasons || {};
  const seasonKeys = Object.keys(seasons).sort();

  const sticky = showIsFullSticky(selectedShow);

  seasonKeys.forEach(sk=>{
    const h = document.createElement("div");
    h.style.margin="10px 0 6px";
    h.innerHTML = `<strong>Season ${sk}</strong>`;
    box.appendChild(h);

    const eps = seasons[sk] || [];
    eps.sort((a,b)=> ((a.episode ?? 0) - (b.episode ?? 0)));

    eps.forEach(ep=>{
      const name = ep.tvg_name || ep.title;
      if(!name) return;
      if(search && !name.toLowerCase().includes(search)) return;

      const checked = sticky || (cfg.allow.series.titles || []).includes(name);
      const isPending = pendingForEpisode(name);

      if(!passFilter(mode, checked, isPending)) return;

      const row = document.createElement("div");
      row.style.display="flex";
      row.style.alignItems="center";
      row.style.gap="8px";
      row.style.padding="4px 0";

      markRowPending(row, isPending);

      const cb = document.createElement("input");
      cb.type="checkbox";
      cb.checked = checked;

      cb.addEventListener("change", ()=>{
        const allEps = getShowEpisodeNames(selectedShow);
        let titles = new Set(cfg.allow.series.titles || []);
        let full = new Set(cfg.allow.series.full_shows || []);
        let allowedShows = new Set(cfg.allow.series.shows || []);

        if(sticky && !cb.checked){
          full.delete(selectedShow);
          allEps.forEach(n => { if(n !== name) titles.add(n); });
          titles.delete(name);
        } else {
          if(cb.checked) titles.add(name); else titles.delete(name);
        }

        const selectedCount = allEps.reduce((acc, n)=> acc + (titles.has(n) ? 1 : 0), 0);
        if(allEps.length > 0 && selectedCount === allEps.length){
          full.add(selectedShow);
          allowedShows.add(selectedShow);
        } else {
          full.delete(selectedShow);
          if(selectedCount === 0){
            allowedShows.delete(selectedShow);
          } else {
            allowedShows.add(selectedShow);
          }
        }

        cfg.allow.series.titles = Array.from(titles);
        cfg.allow.series.full_shows = Array.from(full);
        cfg.allow.series.shows = Array.from(allowedShows);

        renderShows();
        renderEpisodes();
      });

      const label = document.createElement("span");
      label.textContent = name;

      row.appendChild(cb);
      row.appendChild(label);
      box.appendChild(row);
    });
  });
}

function renderAll(){
  if(!catalog) return;
  ensureAllow();
  renderCats("livetv");
  renderItems("livetv");
  renderCats("movies");
  renderItems("movies");
  renderShows();
  renderEpisodes();
}

// ---------- Changes ----------
function fmtDE(ts){
  const d = new Date(ts);
  if(Number.isNaN(d.getTime())) return String(ts || "");
  const pad = n => String(n).padStart(2,"0");
  return `${pad(d.getDate())}.${pad(d.getMonth()+1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

async function loadChangesBox(){
  const box = document.getElementById("changes_box");
  if(!box) return;

  try{
    const res = await apiGet("/api/changes_latest");
    if(!res.has_changes || !res.data){
      box.innerHTML = `<div class="small muted">Noch keine Changes-Datei vorhanden.</div>`;
      return;
    }

    const data = res.data || {};
    const counts = data.counts || {};
    const added = Array.isArray(data.added) ? data.added : [];
    const time = data.time || "";

    const cTotal = counts.total ?? 0;
    const cLive  = counts.livetv ?? 0;
    const cMov   = counts.movies ?? 0;
    const cSer   = counts.series ?? 0;

    let html = "";
    html += `<div class="kv"><b>Neu</b><span>Total: ${cTotal} | LiveTV: ${cLive} | Movies: ${cMov} | Series: ${cSer}</span></div>`;
    html += `<div class="small muted">Zeit: ${fmtDE(time)}</div>`;
    html += `<div class="hr"></div>`;

    if(cTotal === 0 || added.length === 0){
      html += `<div class="small muted">Keine neuen Inhalte.</div>`;
      box.innerHTML = html;
      return;
    }

    const sorted = added.slice().sort((a,b)=>{
      const ak = (a.kind||"").localeCompare(b.kind||"");
      if(ak) return ak;
      const ag = ((a.group||a.show)||"").localeCompare(((b.group||b.show)||""), "de", {sensitivity:"base"});
      if(ag) return ag;
      return (a.title||"").localeCompare((b.title||""), "de", {sensitivity:"base"});
    });

    const top = sorted.slice(0, 20);
    top.forEach(it=>{
      const kind = (it.kind || "").toUpperCase();
      const grp = (it.group || it.show || "");
      const title = it.title || "";
      html += `<div class="small"><b>${kind}</b> ${grp ? `[${grp}] ` : ""}${title}</div>`;
    });

    if(sorted.length > 20){
      html += `<div class="small muted" style="margin-top:6px;">… und ${sorted.length-20} weitere</div>`;
    }

    box.innerHTML = html;
  }catch(e){
    box.innerHTML = `<div class="small muted">Changes laden fehlgeschlagen: ${e.message}</div>`;
  }
}

function injectChangesUI(){
  const card = document.querySelector(".card");
  if(!card) return;

  const hr = document.createElement("div");
  hr.className = "hr";
  card.appendChild(hr);

  const h = document.createElement("h4");
  h.textContent = "Neu hinzugefügt";
  card.appendChild(h);

  const box = document.createElement("div");
  box.id = "changes_box";
  box.className = "small";
  box.innerHTML = `<div class="small muted">Lade…</div>`;
  card.appendChild(box);

  const btnRow = document.createElement("div");
  btnRow.style.display = "flex";
  btnRow.style.gap = "8px";
  btnRow.style.marginTop = "8px";
  btnRow.style.flexWrap = "wrap";

  const btn = document.createElement("button");
  btn.textContent = "Neu hinzugefügt neu laden";
  btn.addEventListener("click", loadChangesBox);
  btnRow.appendChild(btn);

  card.appendChild(btnRow);
}

async function init(){
  cfg = await apiGet("/api/config");
  ensureAllow();
  loadForm();

  // snapshot for pending comparison (loaded config is "saved")
  snapshotSavedAllow();

  // default global filter
  setGlobalFilter("all");

  // Layout: actions above search in items columns
  reorderItemsControls("livetv");
  reorderItemsControls("movies");

  // Tabs
  document.querySelectorAll(".tab").forEach(t=>{
    t.addEventListener("click", ()=> setTab(t.dataset.tab));
  });

  // NEW: global filter above the LiveTV/Movies/Series tabs
  injectGlobalFilterAboveTabs();

  // Rename per-category buttons (LiveTV/Movies)
  (function renamePerCategoryButtons(){
    const a = el("livetv_select_cat"); if(a) a.textContent = "Alle Sender auswählen";
    const b = el("livetv_clear_cat");  if(b) b.textContent = "Alle Sender abwählen";
    const c = el("movies_select_cat"); if(c) c.textContent = "Alle Filme auswählen";
    const d = el("movies_clear_cat");  if(d) d.textContent = "Alle Filme abwählen";
  })();

  // Inject SERIES actions (All shows + all episodes) without HTML change
  (function injectSeriesBulkUI(){
    // Above show search: all series select/clear
    const showSearch = el("search_series_show");
    if(showSearch && showSearch.dataset.hasSeriesTop !== "1"){
      showSearch.dataset.hasSeriesTop = "1";

      const wrap = document.createElement("div");
      wrap.style.display="flex";
      wrap.style.gap="8px";
      wrap.style.margin="0 0 8px";
      wrap.style.flexWrap="wrap";

      const b1 = document.createElement("button");
      b1.textContent = "Alle Serien auswählen";
      b1.addEventListener("click", ()=>{ if(!catalog) return; setAllShows(true); });

      const b2 = document.createElement("button");
      b2.textContent = "Alle Serien abwählen";
      b2.addEventListener("click", ()=>{ if(!catalog) return; setAllShows(false); });

      wrap.appendChild(b1);
      wrap.appendChild(b2);

      showSearch.parentElement.insertBefore(wrap, showSearch);
    }

    // Above episode search: all episodes select/clear for selected show
    const epSearch = el("search_series_eps");
    if(epSearch && epSearch.dataset.hasSeriesEps !== "1"){
      epSearch.dataset.hasSeriesEps = "1";

      const wrap = document.createElement("div");
      wrap.style.display="flex";
      wrap.style.gap="8px";
      wrap.style.margin="0 0 8px";
      wrap.style.flexWrap="wrap";

      const b1 = document.createElement("button");
      b1.textContent = "Alle Episoden auswählen";
      b1.addEventListener("click", ()=>{ if(!catalog) return; setAllEpisodesForSelectedShow(true); });

      const b2 = document.createElement("button");
      b2.textContent = "Alle Episoden abwählen";
      b2.addEventListener("click", ()=>{ if(!catalog) return; setAllEpisodesForSelectedShow(false); });

      wrap.appendChild(b1);
      wrap.appendChild(b2);

      epSearch.parentElement.insertBefore(wrap, epSearch);
    }
  })();

  // Save config
  el("btn_save").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    snapshotSavedAllow(); // pending clears
    setStatus("Gespeichert.");
    if(catalog) renderAll();
  });

  // Test connection
  el("btn_test").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    snapshotSavedAllow();
    setStatus("Teste Verbindung...");
    const res = await apiGet("/api/test");
    renderConnStatus(res);
    setStatus(res.ok ? "Verbindung OK." : "Verbindung FEHLER.");
  });

  // Refresh playlist + catalog
  el("btn_refresh").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    snapshotSavedAllow();
    setStatus("Lade Playlist...");
    const res = await apiPost("/api/refresh", {});
    catalog = res.catalog;

    selectedLiveCat = sortAlphaDE(Object.keys(catalog.livetv.categories||{}))[0] || null;
    selectedMovieCat = sortAlphaDE(Object.keys(catalog.movies.categories||{}))[0] || null;
    selectedShow = sortAlphaDE(Object.keys(catalog.series.shows||{}))[0] || null;

    renderAll();
    setStatus(`Playlist geladen. LiveTV: ${catalog.livetv.total}, Movies: ${catalog.movies.total}, Series: ${catalog.series.total}`);
  });

// Run sync
el("btn_run").addEventListener("click", async () => {
  await runWithOverlay(async () => {
    // erst UI -> cfg speichern + server config updaten
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);

    // IMPORTANT:
    // Snapshot hier ist okay (als "saved before run"),
    // aber nach dem Run MUSS er nochmal neu gesetzt werden.
    snapshotSavedAllow();

    setStatus("Sync läuft...");
    const res = await apiPost("/api/run", {});
    setStatus(
      `Fertig: +${res.run.result.created} neu, ${res.run.result.updated} updated, ${res.run.result.deleted} gelöscht, ${res.run.result.skipped_not_allowed} nicht erlaubt.`
    );

    // >>> Pending sofort korrekt + Liste neu rendern (OHNE Filter-Toggle)
    await refreshUiAfterRun();

    // changes box aktualisieren
    await loadChangesBox();
  }, "Sync startet…");
});

  // Search inputs
  ["search_livetv_cat","search_livetv_items","search_movies_cat","search_movies_items","search_series_show","search_series_eps"].forEach(id=>{
    el(id).addEventListener("input", ()=>{
      if(!catalog) return;
      if(id.includes("livetv")) { renderCats("livetv"); renderItems("livetv"); }
      if(id.includes("movies")) { renderCats("movies"); renderItems("movies"); }
      if(id.includes("series_show")) renderShows();
      if(id.includes("series_eps")) renderEpisodes();
    });
  });

  // Per-category bulk actions (LiveTV/Movies)
  const lsc = el("livetv_select_cat");
  if(lsc) lsc.addEventListener("click", ()=>{
    if(!selectedLiveCat) return;
    const fullSet = new Set(cfg.allow.livetv.full_categories || []);
    fullSet.add(selectedLiveCat);
    cfg.allow.livetv.full_categories = Array.from(fullSet);

    const items = getCategoryItems("livetv", selectedLiveCat);
    const tset = new Set(cfg.allow.livetv.titles||[]);
    items.forEach(n => tset.add(n));
    cfg.allow.livetv.titles = Array.from(tset);

    renderCats("livetv"); renderItems("livetv");
  });

  const lcc = el("livetv_clear_cat");
  if(lcc) lcc.addEventListener("click", ()=>{
    if(!selectedLiveCat) return;
    const fullSet = new Set(cfg.allow.livetv.full_categories || []);
    fullSet.delete(selectedLiveCat);
    cfg.allow.livetv.full_categories = Array.from(fullSet);

    const items = getCategoryItems("livetv", selectedLiveCat);
    const tset = new Set(cfg.allow.livetv.titles||[]);
    items.forEach(n => tset.delete(n));
    cfg.allow.livetv.titles = Array.from(tset);

    renderCats("livetv"); renderItems("livetv");
  });

  const msc = el("movies_select_cat");
  if(msc) msc.addEventListener("click", ()=>{
    if(!selectedMovieCat) return;
    const fullSet = new Set(cfg.allow.movies.full_categories || []);
    fullSet.add(selectedMovieCat);
    cfg.allow.movies.full_categories = Array.from(fullSet);

    const items = getCategoryItems("movies", selectedMovieCat);
    const tset = new Set(cfg.allow.movies.titles||[]);
    items.forEach(n => tset.add(n));
    cfg.allow.movies.titles = Array.from(tset);

    renderCats("movies"); renderItems("movies");
  });

  const mcc = el("movies_clear_cat");
  if(mcc) mcc.addEventListener("click", ()=>{
    if(!selectedMovieCat) return;
    const fullSet = new Set(cfg.allow.movies.full_categories || []);
    fullSet.delete(selectedMovieCat);
    cfg.allow.movies.full_categories = Array.from(fullSet);

    const items = getCategoryItems("movies", selectedMovieCat);
    const tset = new Set(cfg.allow.movies.titles||[]);
    items.forEach(n => tset.delete(n));
    cfg.allow.movies.titles = Array.from(tset);

    renderCats("movies"); renderItems("movies");
  });

  // Inject "Alle Kategorien auswählen/abwählen" ABOVE the category list (LiveTV/Movies)
  (function injectAllCatsButtonsAboveCats(){
    const inject = (kind)=>{
      const searchBox = el("search_" + kind + "_cat");
      if(!searchBox) return;
      if(searchBox.dataset.hasAllCatsButtons === "1") return;
      searchBox.dataset.hasAllCatsButtons = "1";

      const wrap = document.createElement("div");
      wrap.style.display = "flex";
      wrap.style.gap = "8px";
      wrap.style.margin = "0 0 8px";
      wrap.style.flexWrap = "wrap";

      const b1 = document.createElement("button");
      b1.textContent = "Alle auswählen";
      b1.addEventListener("click", ()=>{ if(!catalog) return; setAllCategories(kind, true); });

      const b2 = document.createElement("button");
      b2.textContent = "Alle abwählen";
      b2.addEventListener("click", ()=>{ if(!catalog) return; setAllCategories(kind, false); });

      wrap.appendChild(b1);
      wrap.appendChild(b2);

      searchBox.parentElement.insertBefore(wrap, searchBox);
    };

    inject("livetv");
    inject("movies");
  })();

  // Cleanup UI injection (unchanged)
  (function injectCleanupUI(){
    const card = document.querySelector(".card");
    if(!card) return;

    const hr = document.createElement("div");
    hr.className = "hr";
    card.appendChild(hr);

    const h = document.createElement("h4");
    h.textContent = "Cleanup";
    card.appendChild(h);

    const wrap = document.createElement("div");
    wrap.className = "small muted";
    wrap.style.marginBottom = "8px";
    wrap.textContent = "Löscht Ordner im Output-Verzeichnis. Vorsicht!";
    card.appendChild(wrap);

    const box = document.createElement("div");
    box.style.display = "grid";
    box.style.gridTemplateColumns = "1fr 1fr";
    box.style.gap = "8px 12px";
    box.style.marginBottom = "8px";

    const mkcb = (id, label) => {
      const d = document.createElement("label");
      d.style.display = "flex";
      d.style.alignItems = "center";
      d.style.gap = "8px";
      d.style.margin = "0";
      d.innerHTML = `<input id="${id}" type="checkbox"/> ${label}`;
      return d;
    };

    box.appendChild(mkcb("cl_movies", "Movies löschen"));
    box.appendChild(mkcb("cl_series", "Series löschen"));
    box.appendChild(mkcb("cl_livetv", "LiveTV löschen"));

    const d2 = document.createElement("label");
    d2.style.display="flex";
    d2.style.alignItems="center";
    d2.style.gap="8px";
    d2.style.margin="0";
    d2.innerHTML = `<input id="cl_state" type="checkbox"/> State/Manifest löschen (.xtream_state)`;
    box.appendChild(d2);

    card.appendChild(box);

    const btn = document.createElement("button");
    btn.textContent = "Cleanup ausführen";
    btn.addEventListener("click", async ()=>{
      const targets = [];
      if(el("cl_movies")?.checked) targets.push("movies");
      if(el("cl_series")?.checked) targets.push("series");
      if(el("cl_livetv")?.checked) targets.push("livetv");
      const include_state = !!el("cl_state")?.checked;

      if(targets.length === 0 && !include_state){
        setStatus("Cleanup: nichts ausgewählt.");
        return;
      }

      if(!confirm("Wirklich löschen? Das kann nicht rückgängig gemacht werden.")) return;

      try{
        setStatus("Cleanup läuft...");
        const res = await apiPost("/api/cleanup", {targets, include_state});
        setStatus("Cleanup fertig: " + (res.deleted || []).join(", "));
      }catch(e){
        setStatus("Cleanup Fehler: " + e.message);
      }
    });
    card.appendChild(btn);
  })();

  // Changes UI
  injectChangesUI();
  await loadChangesBox();

  // initial connection box
  try{
    const res = await apiGet("/api/test");
    renderConnStatus(res);
  }catch(e){
    // ignore
  }

  // Try load cached catalog automatically
  try{
    const cached = await apiGet("/api/catalog_cached");
    catalog = cached.catalog;

    selectedLiveCat = sortAlphaDE(Object.keys(catalog.livetv.categories||{}))[0] || null;
    selectedMovieCat = sortAlphaDE(Object.keys(catalog.movies.categories||{}))[0] || null;
    selectedShow = sortAlphaDE(Object.keys(catalog.series.shows||{}))[0] || null;

    renderAll();
  }catch(e){
    // no cached catalog yet
  }

  const st = await apiGet("/api/status");
  if(st.last_run){
    setStatus(`...`);
    setStatusTop(`Letzter Run: ${fmtDE(st.last_run.time)} (${st.last_run.reason})`);
  } else if(st.has_catalog){
    setStatus("Catalog geladen (cached). Du kannst Auswahl ändern, ohne Playlist neu zu laden.");
  } else {
    setStatus("Noch kein Run. Erst Playlist laden, auswählen, speichern.");
    setStatusTop(`Noch kein Run.`);
  }
}

// ===============================
// RUN UI (Overlay + Lock) + Refresh
// ===============================
let __runOverlay = null;
let __runOverlayTimer = null;

function ensureRunOverlay() {
  if (__runOverlay) return __runOverlay;

  // inject minimal CSS once
  const style = document.createElement("style");
  style.textContent = `
    .run-overlay {
      position: fixed; inset: 0;
      background: rgba(0,0,0,0.45);
      display: flex; align-items: center; justify-content: center;
      z-index: 9999;
    }
    .run-card {
      width: min(520px, calc(100vw - 40px));
      background: #111;
      color: #fff;
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.4);
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }
    .run-title { font-weight: 700; font-size: 16px; margin-bottom: 8px; }
    .run-msg { font-size: 13px; opacity: 0.9; margin-bottom: 12px; white-space: pre-wrap; }
    .run-bar {
      height: 10px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.12);
    }
    .run-bar > div {
      height: 100%;
      width: 35%;
      background: rgba(255,255,255,0.85);
      border-radius: 999px;
      transform: translateX(-120%);
      animation: runbar 1.15s infinite linear;
    }
    @keyframes runbar {
      0%   { transform: translateX(-120%); }
      100% { transform: translateX(320%); }
    }
    .run-hint { margin-top: 10px; font-size: 12px; opacity: 0.75; }
  `;
  document.head.appendChild(style);

  // build overlay DOM
  const ov = document.createElement("div");
  ov.className = "run-overlay";
  ov.style.display = "none";
  ov.innerHTML = `
    <div class="run-card">
      <div class="run-title">Sync läuft…</div>
      <div class="run-msg" id="run_overlay_msg">Bitte warten. Währenddessen sind alle Eingaben gesperrt.</div>
      <div class="run-bar"><div></div></div>
      <div class="run-hint" id="run_overlay_hint">Du kannst das Fenster offen lassen – es aktualisiert sich automatisch.</div>
    </div>
  `;
  document.body.appendChild(ov);
  __runOverlay = ov;
  return ov;
}

function setUiDisabled(disabled) {
  // disable all buttons/inputs/selects except inside overlay
  const els = document.querySelectorAll("button, input, select, textarea");
  for (const el of els) {
    if (__runOverlay && __runOverlay.contains(el)) continue;
    // do not disable password/login basic auth prompts etc. (not relevant here)
    el.disabled = !!disabled;
  }
}

function showRunOverlay(message) {
  const ov = ensureRunOverlay();
  const msg = ov.querySelector("#run_overlay_msg");
  if (msg && message) msg.textContent = message;
  ov.style.display = "flex";

  // optional: rotate status messages while running
  const steps = [
    "Sync läuft… Playlist wird verarbeitet…",
    "Sync läuft… STRM Dateien werden geschrieben…",
    "Sync läuft… Aufräumen & Löschen…",
    "Sync läuft… Abschlussarbeiten…",
  ];
  let i = 0;
  clearInterval(__runOverlayTimer);
  __runOverlayTimer = setInterval(() => {
    const m = ov.querySelector("#run_overlay_msg");
    if (m) m.textContent = steps[i++ % steps.length];
  }, 1200);

  setUiDisabled(true);
}

function hideRunOverlay() {
  if (!__runOverlay) return;
  clearInterval(__runOverlayTimer);
  __runOverlayTimer = null;
  __runOverlay.style.display = "none";
  setUiDisabled(false);
}

/**
 * IMPORTANT:
 * After a run, reload config + catalog (cached) and re-render lists using the CURRENT filter/search
 * so "Pending" immediately disappears without touching the global filter.
 *
 * You must adapt the 3 hook-functions below to YOUR app.js names.
 * If you already have these functions, just map them accordingly.
 */
async function afterRunRefreshUi() {
  // 1) reload server config so pending flags can resolve
  try {
    if (typeof loadConfigFromServer === "function") {
      await loadConfigFromServer();
    } else if (typeof loadConfig === "function") {
      // common fallback name
      await loadConfig();
    } else {
      // last-resort: fetch and store globally if your code uses a global config var
      // const cfg = await apiGet("/api/config");
      // window.APP_CONFIG = cfg;
    }
  } catch (e) {
    console.warn("afterRunRefreshUi: config reload failed", e);
  }

  // 2) reload catalog cache (so selections reflect latest data)
  try {
    if (typeof loadCatalogCached === "function") {
      await loadCatalogCached();
    } else if (typeof refreshCatalogCached === "function") {
      await refreshCatalogCached();
    } else {
      // optional:
      // await apiGet("/api/catalog_cached");
    }
  } catch (e) {
    console.warn("afterRunRefreshUi: catalog reload failed", e);
  }

  // 3) re-render lists while KEEPING current filter/search state
  // (this is the key point: no manual filter toggle needed)
  try {
    if (typeof renderAllLists === "function") {
      renderAllLists(); // ideally uses current filter/search already in your state
    } else if (typeof applyCurrentFilters === "function") {
      applyCurrentFilters();
    } else if (typeof refreshAllViews === "function") {
      refreshAllViews();
    }
  } catch (e) {
    console.warn("afterRunRefreshUi: render failed", e);
  }
}

/**
 * Wrap an async action so UI is locked + overlay shown until it finishes.
 */
async function runWithOverlay(fn, startMsg) {
  showRunOverlay(startMsg || "Sync läuft…");
  try {
    return await fn();
  } finally {
    hideRunOverlay();
  }
}

init().catch(err=>{ setStatus("Fehler: " + err.message); });

/**
 * Nach dem Run:
 * - cfg vom Server neu holen
 * - snapshotSavedAllow() neu setzen (damit Pending sofort weg ist)
 * - catalog_cached neu holen (optional aber sinnvoll)
 * - renderAll() aufrufen (damit Listboxen ohne Filter-Toggle neu aufgebaut werden)
 */
async function refreshUiAfterRun() {
  // current UI state merken
  const prevLiveCat = selectedLiveCat;
  const prevMovieCat = selectedMovieCat;
  const prevShow = selectedShow;

  try {
    // 1) Config neu laden (Source of truth)
    const newCfg = await apiGet("/api/config");
    cfg = newCfg;
    ensureAllow();
    loadForm();

    // 2) Snapshot NEU setzen -> Pending verschwindet sofort
    snapshotSavedAllow();

    // 3) Catalog cached neu laden (damit du denselben Datenstand hast wie Server)
    //    (Wenn es noch keinen cached catalog gibt, ignorieren)
    try {
      const cached = await apiGet("/api/catalog_cached");
      if (cached && cached.catalog) {
        catalog = cached.catalog;
      }
    } catch (e) {
      // ok
    }

    // 4) Selections wiederherstellen, falls möglich
    if (catalog) {
      const liveKeys = Object.keys(catalog?.livetv?.categories || {});
      const movieKeys = Object.keys(catalog?.movies?.categories || {});
      const showKeys = Object.keys(catalog?.series?.shows || {});

      selectedLiveCat = (prevLiveCat && liveKeys.includes(prevLiveCat)) ? prevLiveCat : (sortAlphaDE(liveKeys)[0] || null);
      selectedMovieCat = (prevMovieCat && movieKeys.includes(prevMovieCat)) ? prevMovieCat : (sortAlphaDE(movieKeys)[0] || null);
      selectedShow = (prevShow && showKeys.includes(prevShow)) ? prevShow : (sortAlphaDE(showKeys)[0] || null);

      // 5) renderAll nutzt deinen global filter/search state automatisch
      renderAll();
    }
  } catch (e) {
    console.warn("refreshUiAfterRun failed", e);
    // fallback: zumindest Snapshot + rerender versuchen
    try {
      snapshotSavedAllow();
      if (catalog) renderAll();
    } catch (e2) {}
  }
}