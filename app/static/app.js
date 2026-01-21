let cfg = null;
let catalog = null;

let currentTab = "livetv";
let selectedLiveCat = null;
let selectedMovieCat = null;
let selectedShow = null;

function el(id){ return document.getElementById(id); }

function sortAlphaDE(arr){
  return (arr || []).sort((a,b)=> a.localeCompare(b, "de", {sensitivity:"base"}));
}

function getCategoryItems(kind, category){
  const cats = (catalog?.[kind]?.categories) || {};
  return (cats[category] || []).map(it => (it.tvg_name || it.title)).filter(Boolean);
}

function categoryIsFullySelected(kind, category){
  const items = getCategoryItems(kind, category);
  if(items.length === 0) return false;
  const titles = new Set(cfg.allow[kind].titles || []);
  return items.every(n => titles.has(n));
}

function categoryIsFullSticky(kind, category){
  const fullSet = new Set(cfg.allow[kind].full_categories || []);
  return fullSet.has(category);
}

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

function setTab(tab){
  currentTab = tab;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab===tab));
  el("panel_livetv").style.display = tab==="livetv" ? "block":"none";
  el("panel_movies").style.display = tab==="movies" ? "block":"none";
  el("panel_series").style.display = tab==="series" ? "block":"none";
}

function ensureAllow(){
  cfg.allow = cfg.allow || {};
  cfg.allow.livetv = cfg.allow.livetv || {categories:[], titles:[], full_categories:[]};
  cfg.allow.movies = cfg.allow.movies || {categories:[], titles:[], full_categories:[]};
  cfg.allow.series = cfg.allow.series || {shows:[], titles:[]};

  cfg.allow.livetv.full_categories = cfg.allow.livetv.full_categories || [];
  cfg.allow.movies.full_categories = cfg.allow.movies.full_categories || [];
}

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

function renderCats(kind){
  const box = el(kind + "_cats");
  box.innerHTML = "";
  const search = el("search_" + kind + "_cat").value.trim().toLowerCase();

  const cats = (catalog?.[kind]?.categories) || {};
  const keys = sortAlphaDE(Object.keys(cats));

  keys.forEach(k=>{
    if(search && !k.toLowerCase().includes(search)) return;

    const count = (cats[k] || []).length;
    const isFullSticky = categoryIsFullSticky(kind, k);
    const checked = isFullSticky || categoryIsFullySelected(kind, k);

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.justifyContent="space-between";
    row.style.gap="10px";
    row.style.padding="6px 0";

    const left = document.createElement("div");
    left.style.display="flex";
    left.style.alignItems="center";
    left.style.gap="8px";

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;

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
  if(isFullSticky){
    const allNames = getCategoryItems(kind, catKey);
    const set = new Set(cfg.allow[kind].titles || []);
    allNames.forEach(n => set.add(n));
    cfg.allow[kind].titles = Array.from(set);
  }

  items.sort((a,b)=>{
    const an = (a.tvg_name||a.title||"");
    const bn = (b.tvg_name||b.title||"");
    return an.localeCompare(bn, "de", {sensitivity:"base"});
  });

  items.forEach(it=>{
    const name = it.tvg_name || it.title;
    if(!name) return;
    if(search && !name.toLowerCase().includes(search)) return;

    const checked = (cfg.allow[kind].titles || []).includes(name);

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.gap="8px";
    row.style.padding="6px 0";

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;

    cb.addEventListener("change", ()=>{
      if(categoryIsFullSticky(kind, catKey) && !cb.checked){
        const fullSet = new Set(cfg.allow[kind].full_categories || []);
        fullSet.delete(catKey);
        cfg.allow[kind].full_categories = Array.from(fullSet);
      }

      const arr = new Set(cfg.allow[kind].titles || []);
      if(cb.checked) arr.add(name); else arr.delete(name);
      cfg.allow[kind].titles = Array.from(arr);

      renderCats(kind);
    });

    const label = document.createElement("span");
    label.textContent = name;

    row.appendChild(cb);
    row.appendChild(label);
    box.appendChild(row);
  });
}

function renderShows(){
  const box = el("series_shows");
  box.innerHTML = "";
  const search = el("search_series_show").value.trim().toLowerCase();

  const shows = catalog?.series?.shows || {};
  const keys = sortAlphaDE(Object.keys(shows));

  keys.forEach(show=>{
    if(search && !show.toLowerCase().includes(search)) return;
    const checked = (cfg.allow.series.shows || []).includes(show);

    const row = document.createElement("div");
    row.style.display="flex";
    row.style.alignItems="center";
    row.style.justifyContent="space-between";
    row.style.gap="10px";
    row.style.padding="6px 0";

    const left = document.createElement("div");
    left.style.display="flex";
    left.style.alignItems="center";
    left.style.gap="8px";

    const cb = document.createElement("input");
    cb.type="checkbox";
    cb.checked = checked;
    cb.addEventListener("change", ()=>{
      const arr = new Set(cfg.allow.series.shows || []);
      if(cb.checked) arr.add(show); else arr.delete(show);
      cfg.allow.series.shows = Array.from(arr);
    });

    const name = document.createElement("span");
    name.textContent = show;

    const pill = document.createElement("span");
    pill.className="pill";
    pill.textContent = shows[show].total;

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

  if(!selectedShow){
    box.innerHTML = `<div class="small muted">Wähle links eine Show.</div>`;
    return;
  }

  const show = catalog?.series?.shows?.[selectedShow];
  if(!show){
    box.innerHTML = `<div class="small muted">Show nicht gefunden.</div>`;
    return;
  }

  const seasons = show.seasons || {};
  const seasonKeys = Object.keys(seasons).sort();

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

      const checked = (cfg.allow.series.titles || []).includes(name);

      const row = document.createElement("div");
      row.style.display="flex";
      row.style.alignItems="center";
      row.style.gap="8px";
      row.style.padding="4px 0";

      const cb = document.createElement("input");
      cb.type="checkbox";
      cb.checked = checked;
      cb.addEventListener("change", ()=>{
        const arr = new Set(cfg.allow.series.titles || []);
        if(cb.checked) arr.add(name); else arr.delete(name);
        cfg.allow.series.titles = Array.from(arr);
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

async function init(){
  cfg = await apiGet("/api/config");
  ensureAllow();
  loadForm();

  document.querySelectorAll(".tab").forEach(t=>{
    t.addEventListener("click", ()=> setTab(t.dataset.tab));
  });

  el("btn_save").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    setStatus("Gespeichert.");
  });

  el("btn_test").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    setStatus("Teste Verbindung...");
    const res = await apiGet("/api/test");
    renderConnStatus(res);
    setStatus(res.ok ? "Verbindung OK." : "Verbindung FEHLER.");
  });

  el("btn_refresh").addEventListener("click", async ()=>{
    saveFormIntoCfg();
    await apiPost("/api/config", cfg);
    setStatus("Lade Playlist...");
    const res = await apiPost("/api/refresh", {});
    catalog = res.catalog;

    selectedLiveCat = sortAlphaDE(Object.keys(catalog.livetv.categories||{}))[0] || null;
    selectedMovieCat = sortAlphaDE(Object.keys(catalog.movies.categories||{}))[0] || null;
    selectedShow = sortAlphaDE(Object.keys(catalog.series.shows||{}))[0] || null;

    renderAll();
    setStatus(`Playlist geladen. LiveTV: ${catalog.livetv.total}, Movies: ${catalog.movies.total}, Series: ${catalog.series.total}`);
  });

  el("btn_run").addEventListener("click", async ()=>{
    setStatus("Sync läuft...");
    const res = await apiPost("/api/run", {});
    setStatus(`Fertig: +${res.run.result.created} neu, ${res.run.result.updated} updated, ${res.run.result.deleted} gelöscht, ${res.run.result.skipped_not_allowed} nicht erlaubt.`);
  });

  ["search_livetv_cat","search_livetv_items","search_movies_cat","search_movies_items","search_series_show","search_series_eps"].forEach(id=>{
    el(id).addEventListener("input", ()=>{
      if(!catalog) return;
      if(id.includes("livetv")) { renderCats("livetv"); renderItems("livetv"); }
      if(id.includes("movies")) { renderCats("movies"); renderItems("movies"); }
      if(id.includes("series_show")) renderShows();
      if(id.includes("series_eps")) renderEpisodes();
    });
  });

  el("livetv_select_cat").addEventListener("click", ()=>{
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

  el("livetv_clear_cat").addEventListener("click", ()=>{
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

  el("movies_select_cat").addEventListener("click", ()=>{
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

  el("movies_clear_cat").addEventListener("click", ()=>{
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

  el("series_select_show").addEventListener("click", ()=>{
    if(!selectedShow) return;
    const set = new Set(cfg.allow.series.shows||[]);
    set.add(selectedShow);
    cfg.allow.series.shows = Array.from(set);
    renderShows();
  });

  el("series_clear_show").addEventListener("click", ()=>{
    if(!selectedShow) return;
    const set = new Set(cfg.allow.series.shows||[]);
    set.delete(selectedShow);
    cfg.allow.series.shows = Array.from(set);
    renderShows();
  });

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
    box.className = "cleanup-box";

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
      if(el("cl_movies").checked) targets.push("movies");
      if(el("cl_series").checked) targets.push("series");
      if(el("cl_livetv").checked) targets.push("livetv");
      const include_state = el("cl_state").checked;

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

  try{
    const res = await apiGet("/api/test");
    renderConnStatus(res);
  }catch(e){}

  try{
    const cached = await apiGet("/api/catalog_cached");
    catalog = cached.catalog;

    selectedLiveCat = sortAlphaDE(Object.keys(catalog.livetv.categories||{}))[0] || null;
    selectedMovieCat = sortAlphaDE(Object.keys(catalog.movies.categories||{}))[0] || null;
    selectedShow = sortAlphaDE(Object.keys(catalog.series.shows||{}))[0] || null;

    renderAll();
  }catch(e){}

  const st = await apiGet("/api/status");
  if(st.last_run){
    function fmtDE(ts){
        const d = new Date(ts);
        const pad = n => String(n).padStart(2,"0");
        return `${pad(d.getDate())}.${pad(d.getMonth()+1)}.${d.getFullYear()} `
             + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
      }
      
      setStatus(`Letzter Run: ${fmtDE(st.last_run.time)} (${st.last_run.reason})`);
  } else if(st.has_catalog){
    setStatus("Catalog geladen (cached). Du kannst Auswahl ändern, ohne Playlist neu zu laden.");
  } else {
    setStatus("Noch kein Run. Erst Playlist laden, auswählen, speichern.");
  }
}

init().catch(err=>{ setStatus("Fehler: " + err.message); });
