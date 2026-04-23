window.AppState = {
  state: {
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
    },
    health: null
  },

  filterMode: "all",
  statusPollTimer: null,
  STATUS_POLL_INTERVAL_MS: 3000
};