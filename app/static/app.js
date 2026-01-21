let cfg = null;
let catalog = null;

let currentTab = "livetv";
let selectedLiveCat = null;
let selectedMovieCat = null;
let selectedShow = null;

function el(id){ return document.getElementById(id); }

function sortDE(arr){
  return (arr||[]).sort((a,b)=>a.localeCompare(b,"de",{sensitivity:"base"}));
}

/* ---------- API ---------- */

async function apiGet(path){
  const r = await fetch(path);
  const j = await r.json();
  if(!r.ok) throw new Error(j.error || j.detail || "API error");
  return j;
}
async function apiPost(path, body){
  const r = await fetch(path,{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body||{})
  });
  const j = await r.json();
  if(!r.ok) throw new Error(j.error || j.detail || "API error");
  return j;
}

function setStatus(t){ el("status").textContent = t; }

/* ---------- HELPERS ---------- */

function ensureAllow(){
  cfg.allow = cfg.allow || {};
  cfg.allow.livetv = cfg.allow.livetv || {categories:[],titles:[],full_categories:[]};
  cfg.allow.movies = cfg.allow.movies || {categories:[],titles:[],full_categories:[]};
  cfg.allow.series = cfg.allow.series || {shows:[],titles:[]};
}

function getCategoryItems(kind, cat){
  const c = catalog?.[kind]?.categories || {};
  return (c[cat]||[]).map(i=>i.tvg_name||i.title).filter(Boolean);
}

function isFullCat(kind, cat){
  return (cfg.allow[kind].full_categories||[]).includes(cat);
}

/* ---------- TABS ---------- */

function setTab(t){
  currentTab=t;
  document.querySelectorAll(".tab")
    .forEach(b=>b.classList.toggle("active",b.dataset.tab===t));
  el("panel_livetv").style.display=t==="livetv"?"block":"none";
  el("panel_movies").style.display=t==="movies"?"block":"none";
  el("panel_series").style.display=t==="series"?"block":"none";
}

/* ---------- RENDER CATEGORIES ---------- */

function renderCats(kind){
  const box = el(kind+"_cats");
  box.innerHTML="";
  const cats = catalog?.[kind]?.categories||{};
  sortDE(Object.keys(cats)).forEach(cat=>{
    const row=document.createElement("div");
    row.className="list-row";

    const cb=document.createElement("input");
    cb.type="checkbox";
    cb.checked=isFullCat(kind,cat);

    cb.onchange=()=>{
      const full=new Set(cfg.allow[kind].full_categories||[]);
      const titles=new Set(cfg.allow[kind].titles||[]);
      const items=getCategoryItems(kind,cat);

      if(cb.checked){
        full.add(cat);
        items.forEach(t=>titles.add(t));
      }else{
        full.delete(cat);
        items.forEach(t=>titles.delete(t));
      }

      cfg.allow[kind].full_categories=[...full];
      cfg.allow[kind].titles=[...titles];
      renderCats(kind); renderItems(kind);
    };

    const name=document.createElement("span");
    name.className="list-name";
    name.textContent=cat;

    const pill=document.createElement("span");
    pill.className="pill";
    pill.textContent=cats[cat].length;

    row.append(cb,name,pill);

    row.onclick=e=>{
      if(e.target.tagName==="INPUT") return;
      if(kind==="livetv") selectedLiveCat=cat;
      if(kind==="movies") selectedMovieCat=cat;
      renderItems(kind);
    };

    box.appendChild(row);
  });
}

/* ---------- RENDER ITEMS ---------- */

function renderItems(kind){
  const box=el(kind+"_items");
  box.innerHTML="";
  const cat=(kind==="livetv")?selectedLiveCat:selectedMovieCat;
  if(!cat){
    box.innerHTML="<div class='small muted'>Kategorie wählen</div>";
    return;
  }

  const items=catalog[kind].categories[cat]||[];
  sortDE(items.map(i=>i)).forEach(it=>{
    const name=it.tvg_name||it.title;
    if(!name) return;

    const row=document.createElement("div");
    row.className="list-row item";

    const cb=document.createElement("input");
    cb.type="checkbox";
    cb.checked=(cfg.allow[kind].titles||[]).includes(name);
    cb.onchange=()=>{
      const set=new Set(cfg.allow[kind].titles||[]);
      cb.checked?set.add(name):set.delete(name);
      cfg.allow[kind].titles=[...set];
    };

    const label=document.createElement("span");
    label.className="list-name";
    label.textContent=name;

    row.append(cb,label);
    box.appendChild(row);
  });
}

/* ---------- INIT ---------- */

async function init(){
  cfg=await apiGet("/api/config");
  ensureAllow();

  document.querySelectorAll(".tab")
    .forEach(t=>t.onclick=()=>setTab(t.dataset.tab));

  el("btn_refresh").onclick=async()=>{
    setStatus("Lade Playlist...");
    const r=await apiPost("/api/refresh",{});
    catalog=r.catalog;
    selectedLiveCat=sortDE(Object.keys(catalog.livetv.categories||{}))[0]||null;
    selectedMovieCat=sortDE(Object.keys(catalog.movies.categories||{}))[0]||null;
    renderCats("livetv"); renderItems("livetv");
    renderCats("movies"); renderItems("movies");
    setStatus("Playlist geladen");
  };

  const st=await apiGet("/api/status");
  if(st.last_run){
    const d=new Date(st.last_run.time);
    const p=n=>String(n).padStart(2,"0");
    setStatus(`Letzter Run: ${p(d.getDate())}.${p(d.getMonth()+1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`);
  }
}

init();
