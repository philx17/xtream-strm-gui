window.AppApi = (() => {
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
      const msg = data?.error || data?.detail || `HTTP ${res.status} bei ${url}`;
      throw new Error(msg);
    }

    return data;
  }

  return { api };
})();