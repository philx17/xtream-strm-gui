window.AppUtils = (() => {
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
    const state = window.AppState.state;
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

  return {
    el,
    toast,
    escapeHtml,
    sortByName,
    uniqueById,
    categoryNameMap
  };
})();