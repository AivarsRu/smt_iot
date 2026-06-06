/* SMT Digital Solution dashboard — vanilla JavaScript loader.
 *
 * Four pages share this script:
 *   • /dashboard/                       ← reads #dashboard-config
 *   • /dashboard/assets/.../            ← reads #asset-detail-config
 *   • /dashboard/events/                ← reads #events-list-config
 *   • /dashboard/events/<id>/           ← reads #event-detail-config
 *
 * The script picks the right initialiser based on which JSON block is
 * present in the DOM. Shared helpers (DOM, formatting, badges, fetch)
 * live at module scope so all initialisers can reuse them.
 *
 * The dashboard is read-only and uses only the public Phase 6/7 REST API.
 */

(function () {
  "use strict";

  // ── Generic helpers ──────────────────────────────────────────────────

  function readJsonScript(elementId) {
    const node = document.getElementById(elementId);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return null;
    }
  }

  function $(role, root) {
    return (root || document).querySelector(`[data-role="${role}"]`);
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.entries(attrs).forEach(([key, value]) => {
        if (value === null || value === undefined) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "html") node.innerHTML = value;
        else node.setAttribute(key, value);
      });
    }
    (children || []).forEach((child) => {
      if (child === null || child === undefined) return;
      node.appendChild(
        typeof child === "string" ? document.createTextNode(child) : child,
      );
    });
    return node;
  }

  function svg(tag, attrs, children) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (attrs) {
      Object.entries(attrs).forEach(([k, v]) => {
        if (v === null || v === undefined) return;
        node.setAttribute(k, v);
      });
    }
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(c);
    });
    return node;
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setState(node, kind, message) {
    if (!node) return;
    clear(node);
    node.appendChild(
      el("div", { class: `state state--${kind}`, text: message }),
    );
  }

  function formatTimestamp(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  function formatNumber(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "number") {
      return Number.isInteger(value) ? String(value) : value.toFixed(2);
    }
    return String(value);
  }

  function badge(text, modifierClass) {
    return el("span", {
      class: `badge ${modifierClass || ""}`.trim(),
      text: text,
    });
  }

  function statusBadge(status) {
    return badge(status || "—", `badge--status-${status || "unknown"}`);
  }

  function severityBadge(severity) {
    return badge(severity || "info", `badge--severity-${severity || "info"}`);
  }

  function eventStatusBadge(status) {
    return badge(status || "—", `badge--status-${status || "unknown"}`);
  }

  function countPill(label, value) {
    return el("span", { class: "count-pill" }, [
      el("strong", { text: String(value) }),
      " " + label,
    ]);
  }

  function fillTemplate(template, placeholder, value) {
    if (!template) return null;
    if (value === null || value === undefined) return null;
    return template.replace(placeholder, encodeURIComponent(value));
  }

  async function fetchJson(url) {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 15000);
    try {
      const resp = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: ctrl.signal,
        credentials: "same-origin",
      });
      if (!resp.ok) {
        const err = new Error(`HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
      }
      return await resp.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  // Phase 7, Task 3B — read Django's csrftoken cookie as a fallback for
  // when the dashboard config doesn't carry a server-rendered token
  // (e.g. anonymous reads). Returns null if absent.
  function getCookie(name) {
    if (!document.cookie) return null;
    const needle = name + "=";
    const parts = document.cookie.split(";");
    for (let i = 0; i < parts.length; i += 1) {
      const part = parts[i].trim();
      if (part.indexOf(needle) === 0) {
        return decodeURIComponent(part.slice(needle.length));
      }
    }
    return null;
  }

  // ── Refresh wiring (shared) ─────────────────────────────────────────

  function wireRefreshControls(loadAll, autoIntervalMs) {
    // Returns a small controller so caller code (typically the live-update
    // adapter) can swap the polling cadence at runtime — e.g. lengthen
    // the interval when WebSocket is healthy and shorten it back when
    // the connection drops.
    const refreshBtn = $("refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadAll());

    const autoToggle = $("auto-refresh-toggle");
    let handle = null;
    let currentIntervalMs = autoIntervalMs > 0 ? autoIntervalMs : 0;

    function applyHandle() {
      if (handle) { clearInterval(handle); handle = null; }
      if (autoToggle && autoToggle.checked && currentIntervalMs > 0) {
        handle = setInterval(loadAll, currentIntervalMs);
      }
    }

    if (autoToggle) {
      autoToggle.addEventListener("change", applyHandle);
    }

    return {
      setInterval(ms) {
        currentIntervalMs = Math.max(0, ms || 0);
        applyHandle();
      },
      stop() {
        if (handle) { clearInterval(handle); handle = null; }
      },
    };
  }

  // ── Live updates / WebSocket helper ────────────────────────────────

  // Fixed-string Latvian labels for the live-status pill so the UI stays
  // consistent across pages and tests.
  const LIVE_STATUS_LABELS = {
    connecting: "Mēģina pieslēgties",
    open:       "Tiešraide pieslēgta",
    closed:     "Tiešraide atvienota",
    polling:    "Izmanto periodisku atjaunošanu",
    disabled:   "Tiešraide atspējota",
  };

  function setLiveStatus(state) {
    const pill = $("live-status-pill");
    if (!pill) return;
    pill.classList.remove(
      "status-pill--ok", "status-pill--degraded", "status-pill--warning",
    );
    if (state === "open") pill.classList.add("status-pill--ok");
    else if (state === "polling") pill.classList.add("status-pill--warning");
    else if (state === "closed" || state === "disabled") {
      pill.classList.add("status-pill--degraded");
    }
    pill.textContent = LIVE_STATUS_LABELS[state] || "—";
    pill.dataset.state = state;
  }

  function buildWebsocketUrl(path) {
    if (!path) return null;
    if (/^wss?:\/\//i.test(path)) return path;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${path}`;
  }

  function connectLiveUpdates(path, handlers) {
    // ``handlers`` may have ``onEvent(payload)``, ``onOpen()``, ``onClose()``,
    // ``onConnecting()``. Returns ``{close()}`` for teardown. Reconnects
    // with conservative exponential backoff (capped at 30 s) so a long
    // outage does not flood the browser console.
    if (!path || typeof window.WebSocket !== "function") {
      setLiveStatus("disabled");
      return { close() {} };
    }

    let ws = null;
    let manualClose = false;
    let backoff = 1000;
    const MAX_BACKOFF = 30000;
    let reconnectTimer = null;

    function open() {
      setLiveStatus("connecting");
      if (handlers.onConnecting) handlers.onConnecting();
      let url;
      try {
        url = buildWebsocketUrl(path);
      } catch (err) {
        setLiveStatus("disabled");
        return;
      }
      try {
        ws = new WebSocket(url);
      } catch (err) {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        backoff = 1000;
        setLiveStatus("open");
        if (handlers.onOpen) handlers.onOpen();
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (handlers.onEvent) handlers.onEvent(data);
        } catch (err) {
          // Ignore malformed frames — handler-side rendering must stay
          // robust against partial/garbled messages.
        }
      };
      ws.onerror = () => { /* Falls through to onclose for backoff. */ };
      ws.onclose = () => {
        ws = null;
        if (manualClose) return;
        setLiveStatus("closed");
        if (handlers.onClose) handlers.onClose();
        scheduleReconnect();
      };
    }

    function scheduleReconnect() {
      if (manualClose) return;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF);
    }

    open();

    return {
      close() {
        manualClose = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        if (ws) {
          try { ws.close(); } catch (e) { /* noop */ }
        }
      },
    };
  }

  // ────────────────────────────────────────────────────────────────────
  // Overview page (existing /dashboard/)
  // ────────────────────────────────────────────────────────────────────

  function initOverview(config) {
    const ENDPOINTS = config.endpoints;
    const ASSET_SUMMARY_TPL = config.assetSummaryUrlTemplate || "";
    const ASSET_DETAIL_TPL = config.assetDetailUrlTemplate || "";
    const AUTO_INTERVAL_MS =
      Math.max(0, (config.autoRefreshIntervalSeconds || 0) * 1000);
    const LIVE_AUTO_INTERVAL_MS =
      Math.max(0, (config.liveAutoRefreshIntervalSeconds || 0) * 1000);
    const WEBSOCKET_PATH = config.websocketPath || "";

    function renderOverviewCards(data) {
      const root = $("overview-cards");
      if (!root) return;
      clear(root);
      const cards = [
        ["Aktīvi (kopā)", data.assets.total],
        ["Aktīvi aktīvā statusā", data.assets.active],
        ["Aktīvi offline", data.assets.offline],
        ["Atvērti notikumi", data.events.open_total],
        ["Sliekšņa anomālijas", data.events.open_threshold_anomaly],
        ["Komunikācijas pārtraukumi", data.events.open_communication_timeout],
        ["Pēdējais mērījums", formatTimestamp(data.telemetry.latest_measurement_at)],
      ];
      cards.forEach(([label, value]) => {
        root.appendChild(
          el("div", { class: "card" }, [
            el("p", { class: "card__label", text: label }),
            el("p", { class: "card__value", text: formatNumber(value) }),
          ]),
        );
      });
      const generatedAt = $("generated-at");
      if (generatedAt) generatedAt.textContent =
        "Atjaunots: " + formatTimestamp(data.generated_at);
      const healthPill = $("health-pill");
      if (healthPill) {
        healthPill.classList.remove("status-pill--degraded");
        healthPill.classList.add("status-pill--ok");
        healthPill.textContent = "OK";
      }
    }

    function renderAssets(data) {
      const counts = $("assets-counts");
      if (counts) {
        clear(counts);
        counts.appendChild(countPill("kopā", data.counts.total));
        counts.appendChild(countPill("aktīvi", data.counts.active));
        counts.appendChild(countPill("offline", data.counts.offline));
        counts.appendChild(
          countPill("ar anomāliju", data.counts.with_active_anomaly),
        );
        (data.by_type || []).forEach((row) => {
          counts.appendChild(countPill(row.asset_type || "—", row.count));
        });
      }

      const wrapper = $("assets-table-wrapper");
      if (!wrapper) return;
      clear(wrapper);
      if (!data.items || data.items.length === 0) {
        setState($("assets-state") || wrapper, "empty", "Nav aktīvu.");
        return;
      }

      const headers = [
        "Kods", "Nosaukums", "Vieta", "Tips", "Statuss",
        "Pēdējoreiz redzēts", "Pēdējais mērījums",
        "T (°C)", "U (V)", "SoC (%)",
        "Anomālijas", "Detaļas",
      ];
      const thead = el("thead", null, [
        el("tr", null, headers.map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      data.items.forEach((row) => {
        const detailHref = fillTemplate(ASSET_DETAIL_TPL, "__CODE__", row.asset_code);
        const summaryHref = fillTemplate(ASSET_SUMMARY_TPL, "__CODE__", row.asset_code);
        const detailLink = detailHref
          ? el("a", { href: detailHref, rel: "noopener", text: "Atvērt" })
          : el("span", { class: "card__hint", text: "—" });
        const jsonLink = summaryHref
          ? el("a", {
              href: summaryHref,
              rel: "noopener",
              class: "card__hint",
              text: "JSON",
              "aria-label": "JSON kopsavilkums",
            })
          : null;
        tbody.appendChild(
          el("tr", null, [
            el("td", { text: row.asset_code || "—" }),
            el("td", { text: row.asset_name || "—" }),
            el("td", { text: row.site_code || "—" }),
            el("td", { text: row.asset_type || "—" }),
            el("td", null, [statusBadge(row.status)]),
            el("td", { class: "numeric", text: formatTimestamp(row.last_seen_at) }),
            el("td", { class: "numeric", text: formatTimestamp(row.last_measurement_at) }),
            el("td", { class: "numeric", text: formatNumber(row.last_temperature_c) }),
            el("td", { class: "numeric", text: formatNumber(row.last_voltage_v) }),
            el("td", { class: "numeric", text: formatNumber(row.last_battery_soc_pct) }),
            el("td", { class: "numeric", text: formatNumber(row.active_anomaly_count) }),
            el(
              "td", { class: "row-actions" },
              jsonLink ? [detailLink, " · ", jsonLink] : [detailLink],
            ),
          ]),
        );
      });
      wrapper.appendChild(el("table", { class: "data-table" }, [thead, tbody]));
    }

    function renderEvents(data) {
      const counts = $("events-counts");
      if (counts) {
        clear(counts);
        counts.appendChild(countPill("atvērti", data.counts.open_total));
        counts.appendChild(countPill("aizvērti", data.counts.closed_total));
        counts.appendChild(countPill("warning", data.counts.warning_open));
        counts.appendChild(countPill("error", data.counts.error_open));
        counts.appendChild(countPill("critical", data.counts.critical_open));
      }
      const wrapper = $("events-list-wrapper");
      if (!wrapper) return;
      clear(wrapper);
      if (!data.recent || data.recent.length === 0) {
        setState($("events-state") || wrapper, "empty", "Nav neseno notikumu.");
        return;
      }
      const thead = el("thead", null, [
        el("tr", null, [
          "Tips", "Smagums", "Statuss", "Virsraksts",
          "Aktīvs", "Ierīce", "Atklāts",
        ].map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      data.recent.forEach((row) => {
        tbody.appendChild(
          el("tr", null, [
            el("td", { text: row.event_type || "—" }),
            el("td", null, [severityBadge(row.severity)]),
            el("td", null, [eventStatusBadge(row.status)]),
            el("td", { text: row.title || "—" }),
            el("td", { text: row.asset_code || "—" }),
            el("td", { text: row.device_uid || "—" }),
            el("td", { class: "numeric", text: formatTimestamp(row.detected_at) }),
          ]),
        );
      });
      wrapper.appendChild(el("table", { class: "data-table" }, [thead, tbody]));
    }

    function renderTelemetry(data) {
      const counts = $("telemetry-counts");
      if (counts) {
        clear(counts);
        counts.appendChild(countPill("RawMessage kopā", data.raw_messages.total));
        counts.appendChild(countPill("parsed", data.raw_messages.parsed));
        counts.appendChild(countPill("failed", data.raw_messages.failed));
        counts.appendChild(countPill("Mērījumi kopā", data.measurements.total));
        counts.appendChild(
          countPill(
            "pēdējais",
            formatTimestamp(data.measurements.latest_timestamp),
          ),
        );
      }

      const metricsWrapper = $("telemetry-metrics-wrapper");
      if (metricsWrapper) {
        const title = metricsWrapper.querySelector(".subsection-title");
        clear(metricsWrapper);
        if (title) metricsWrapper.appendChild(title);
        const metrics = data.measurements.metrics || [];
        if (metrics.length === 0) {
          metricsWrapper.appendChild(
            el("div", { class: "state state--empty", text: "Nav mērījumu." }),
          );
        } else {
          const thead = el("thead", null, [
            el("tr", null, [
              "Metrika", "Vienība", "Pēdējā vērtība",
              "Pēdējais laiks", "Skaits",
            ].map((h) => el("th", { text: h }))),
          ]);
          const tbody = el("tbody");
          metrics.forEach((m) => {
            tbody.appendChild(
              el("tr", null, [
                el("td", { text: m.metric_key || "—" }),
                el("td", { text: m.unit || "" }),
                el("td", { class: "numeric", text: formatNumber(m.latest_value) }),
                el("td", { class: "numeric", text: formatTimestamp(m.latest_timestamp) }),
                el("td", { class: "numeric", text: formatNumber(m.count) }),
              ]),
            );
          });
          metricsWrapper.appendChild(
            el("table", { class: "data-table" }, [thead, tbody]),
          );
        }
      }

      const recentWrapper = $("telemetry-recent-wrapper");
      if (recentWrapper) {
        const title = recentWrapper.querySelector(".subsection-title");
        clear(recentWrapper);
        if (title) recentWrapper.appendChild(title);
        const items = data.recent_measurements || [];
        if (items.length === 0) {
          recentWrapper.appendChild(
            el("div", { class: "state state--empty", text: "Nav neseno mērījumu." }),
          );
          return;
        }
        const thead = el("thead", null, [
          el("tr", null, [
            "Aktīvs", "Ierīce", "Metrika",
            "Vērtība", "Vienība", "Laiks",
          ].map((h) => el("th", { text: h }))),
        ]);
        const tbody = el("tbody");
        items.forEach((m) => {
          tbody.appendChild(
            el("tr", null, [
              el("td", { text: m.asset_code || "—" }),
              el("td", { text: m.device_uid || "—" }),
              el("td", { text: m.metric_key || "—" }),
              el("td", { class: "numeric", text: formatNumber(m.value) }),
              el("td", { text: m.unit || "" }),
              el("td", { class: "numeric", text: formatTimestamp(m.timestamp) }),
            ]),
          );
        });
        recentWrapper.appendChild(
          el("table", { class: "data-table" }, [thead, tbody]),
        );
      }
    }

    // Phase 7, Task 4 — simulator panel + run-history rendering moved
    // to ``initSimulatorWorkspace`` (the dedicated /dashboard/simulator/
    // page). The overview no longer queries /api/overview/simulator/.

    const SECTIONS = [
      { key: "overview",  url: ENDPOINTS.overview,
        stateRoles: ["overview-state"], onSuccess: renderOverviewCards },
      { key: "assets",    url: ENDPOINTS.overviewAssets,
        stateRoles: ["assets-state"], onSuccess: renderAssets },
      { key: "events",    url: ENDPOINTS.overviewEvents,
        stateRoles: ["events-state"], onSuccess: renderEvents },
      { key: "telemetry", url: ENDPOINTS.overviewTelemetry,
        stateRoles: ["telemetry-metrics-state", "telemetry-recent-state"],
        onSuccess: renderTelemetry },
    ];

    function setSectionLoading(section) {
      section.stateRoles.forEach((role) => setState($(role), "loading", "Ielādē…"));
    }
    function setSectionError(section, message) {
      section.stateRoles.forEach((role) => setState($(role), "error", message));
      if (section.key === "overview") {
        const pill = $("health-pill");
        if (pill) {
          pill.classList.remove("status-pill--ok");
          pill.classList.add("status-pill--degraded");
          pill.textContent = "API kļūda";
        }
      }
    }
    async function loadSection(section) {
      setSectionLoading(section);
      try {
        const data = await fetchJson(section.url);
        section.onSuccess(data);
      } catch (err) {
        setSectionError(
          section,
          "Kļūda ielādējot: " + (err && err.message ? err.message : "nezināma"),
        );
      }
    }
    async function loadAll() {
      await Promise.all(SECTIONS.map(loadSection));
    }

    // ── Live update wiring ──────────────────────────────────────────

    setLiveStatus(WEBSOCKET_PATH ? "connecting" : "disabled");
    const refreshController = wireRefreshControls(loadAll, AUTO_INTERVAL_MS);

    function handleLiveEvent(payload) {
      if (!payload || typeof payload !== "object") return;
      const evt = payload.event_type;
      if (!evt || evt === "connection_ack" || evt === "pong") return;
      // Map event types to the cheapest reload that still keeps the
      // matching panel honest. Phase 7, Task 4 — simulator-only events
      // are intentionally ignored here because the simulator now lives
      // on its own page; we still react to telemetry / anomaly events
      // because those represent real operational changes.
      if (
        evt === "telemetry_received"
        || evt === "asset_state_updated"
        || evt === "raw_message_received"
        || evt === "simulator_mqtt_message_sent"
      ) {
        loadSection(SECTIONS[0]); // overview cards
        loadSection(SECTIONS[1]); // assets
        loadSection(SECTIONS[3]); // telemetry
      } else if (evt === "anomaly_created") {
        loadSection(SECTIONS[0]);
        loadSection(SECTIONS[2]); // events
      }
    }

    let liveConnection = null;
    if (WEBSOCKET_PATH) {
      liveConnection = connectLiveUpdates(WEBSOCKET_PATH, {
        onOpen() {
          if (LIVE_AUTO_INTERVAL_MS > 0) {
            refreshController.setInterval(LIVE_AUTO_INTERVAL_MS);
          }
        },
        onClose() {
          // Drop back to the aggressive polling cadence when the
          // socket is unavailable, so the page is still self-healing.
          refreshController.setInterval(AUTO_INTERVAL_MS);
        },
        onEvent: handleLiveEvent,
      });
      window.addEventListener("beforeunload", () => liveConnection.close());
    } else {
      setLiveStatus("disabled");
    }

    loadAll();
  }

  // ────────────────────────────────────────────────────────────────────
  // Asset detail page (/dashboard/assets/<id-or-code>/)
  // ────────────────────────────────────────────────────────────────────

  function renderSparkline(svgEl, points) {
    // ``points`` is an array of [Date, number]. Draws a minimal line chart
    // inside the supplied <svg> with viewBox 0 0 300 80. Pads 6 px on
    // each side. Returns true if a line was drawn, false on empty input.
    clear(svgEl);
    svgEl.setAttribute("viewBox", "0 0 300 80");
    svgEl.setAttribute("preserveAspectRatio", "none");
    const validPoints = (points || []).filter(
      (p) => p && p[1] !== null && p[1] !== undefined && !Number.isNaN(p[1]),
    );
    if (validPoints.length === 0) return false;

    const xs = validPoints.map((p) => p[0].getTime());
    const ys = validPoints.map((p) => p[1]);
    const minX = Math.min.apply(null, xs);
    const maxX = Math.max.apply(null, xs);
    const minY = Math.min.apply(null, ys);
    const maxY = Math.max.apply(null, ys);

    const padX = 6, padY = 6;
    const w = 300 - padX * 2, h = 80 - padY * 2;
    const sx = (x) => (
      maxX === minX ? padX + w / 2 : padX + ((x - minX) / (maxX - minX)) * w
    );
    const sy = (y) => (
      maxY === minY ? padY + h / 2 : padY + h - ((y - minY) / (maxY - minY)) * h
    );

    const polyline = svg("polyline", {
      points: validPoints.map((p) => `${sx(p[0].getTime())},${sy(p[1])}`).join(" "),
      fill: "none",
      stroke: "var(--color-primary)",
      "stroke-width": 1.5,
      "stroke-linejoin": "round",
      "stroke-linecap": "round",
    });
    svgEl.appendChild(polyline);

    // End-point marker for "latest value" affordance.
    const last = validPoints[validPoints.length - 1];
    svgEl.appendChild(
      svg("circle", {
        cx: sx(last[0].getTime()), cy: sy(last[1]),
        r: 2.5, fill: "var(--color-primary)",
      }),
    );
    return true;
  }

  function initAssetDetail(config) {
    const ASSET = config.assetIdentifier;
    const SUMMARY_URL = config.summaryUrl;
    const MEASUREMENTS_URL = config.measurementsUrl;
    const EVENTS_URL = config.eventsUrl;
    const CHART_URL_TEMPLATE = config.chartUrlTemplate;
    const CHART_METRICS = config.chartMetrics || [];
    const OVERVIEW_URL = config.dashboardOverviewUrl;
    const AUTO_INTERVAL_MS =
      Math.max(0, (config.autoRefreshIntervalSeconds || 0) * 1000);
    const LIVE_AUTO_INTERVAL_MS =
      Math.max(0, (config.liveAutoRefreshIntervalSeconds || 0) * 1000);
    const WEBSOCKET_PATH = config.websocketPath || "";

    function showPageError(message) {
      const banner = $("page-error");
      if (banner) {
        banner.hidden = false;
        clear(banner);
        banner.appendChild(
          el("div", { class: "state state--error" }, [
            el("strong", { text: message }),
            " ",
            el("a", {
              href: OVERVIEW_URL || "/dashboard/",
              text: "Atgriezties uz pārskatu",
            }),
          ]),
        );
      }
      // Also clear all section loading messages.
      [
        "identity-state", "state-cards-state", "charts-state",
        "measurements-state", "events-state", "raw-state",
      ].forEach((role) => setState($(role), "empty", "—"));
    }

    function renderIdentity(summary) {
      const wrapper = $("asset-identity");
      if (!wrapper) return;
      clear(wrapper);
      const a = summary.asset || {};
      const s = summary.state || {};

      const titleNode = $("asset-title");
      if (titleNode && a.code) {
        titleNode.textContent = `Aktīvs: ${a.code}`;
      }

      const items = [
        ["Kods", a.code || "—"],
        ["Nosaukums", a.name || "—"],
        ["Vieta", a.site_code || "—"],
        ["Tips", a.asset_type || "—"],
        ["Statuss", null, statusBadge(a.status)],
        ["Pēdējoreiz redzēts", formatTimestamp(s.last_seen_at)],
        ["Pēdējais mērījums", formatTimestamp(s.last_measurement_at)],
        ["Aktīvas anomālijas", formatNumber(s.active_anomaly_count)],
      ];
      items.forEach(([label, value, badgeNode]) => {
        wrapper.appendChild(
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: label }),
            badgeNode
              ? el("span", { class: "identity-item__value" }, [badgeNode])
              : el("span", { class: "identity-item__value", text: value }),
          ]),
        );
      });
    }

    function renderStateCards(summary) {
      const root = $("state-cards");
      if (!root) return;
      clear(root);
      const s = summary.state || {};
      const cards = [
        ["Temperatūra (°C)", s.last_temperature_c],
        ["Spriegums (V)",    s.last_voltage_v],
        ["Strāva (A)",       s.last_current_a],
        ["Jauda (W)",        s.last_power_w],
        ["Baterija (SoC %)", s.last_battery_soc_pct],
        ["Anomālijas",       s.active_anomaly_count],
        [
          "Anomālijas aktīvas",
          s.has_active_anomaly === true ? "jā"
            : s.has_active_anomaly === false ? "nē" : "—",
        ],
      ];
      cards.forEach(([label, value]) => {
        const text = typeof value === "string" ? value : formatNumber(value);
        root.appendChild(
          el("div", { class: "card" }, [
            el("p", { class: "card__label", text: label }),
            el("p", { class: "card__value", text: text }),
          ]),
        );
      });
    }

    function renderRawPanel(summary) {
      const wrapper = $("raw-panel");
      if (!wrapper) return;
      clear(wrapper);
      const raw = summary.latest_raw_message;
      if (!raw) {
        wrapper.appendChild(
          el("div", { class: "state state--empty",
                      text: "Nav saņemts neviens MQTT ziņojums šim aktīvam." }),
        );
        return;
      }
      const items = [
        ["message_id", raw.message_id || "—"],
        ["processing_status", raw.processing_status || "—"],
        ["received_at", formatTimestamp(raw.received_at)],
        ["topic", raw.topic || "—"],
      ];
      const dl = el("dl", { class: "diagnostic-panel__list" });
      items.forEach(([k, v]) => {
        dl.appendChild(el("dt", { text: k }));
        dl.appendChild(el("dd", { text: v }));
      });
      wrapper.appendChild(dl);
    }

    function renderMeasurementsTable(payload) {
      const wrapper = $("measurements-wrapper");
      if (!wrapper) return;
      clear(wrapper);
      const items = Array.isArray(payload) ? payload : [];
      if (items.length === 0) {
        wrapper.appendChild(
          el("div", { class: "state state--empty",
                      text: "Nav mērījumu šim aktīvam." }),
        );
        return;
      }
      const thead = el("thead", null, [
        el("tr", null, [
          "Metrika", "Sensors", "Vērtība", "Vienība", "Laiks", "Kvalitāte",
        ].map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      items.forEach((m) => {
        tbody.appendChild(
          el("tr", null, [
            el("td", { text: m.metric_key || "—" }),
            el("td", { text: m.sensor_code || "—" }),
            el("td", { class: "numeric", text: formatNumber(m.value) }),
            el("td", { text: m.unit || (m.metric_unit || "") }),
            el("td", { class: "numeric", text: formatTimestamp(m.timestamp) }),
            el("td", { text: m.quality || "—" }),
          ]),
        );
      });
      wrapper.appendChild(el("table", { class: "data-table" }, [thead, tbody]));
    }

    function renderEventsTable(payload) {
      const wrapper = $("events-wrapper");
      if (!wrapper) return;
      clear(wrapper);
      const items = Array.isArray(payload) ? payload : [];
      if (items.length === 0) {
        wrapper.appendChild(
          el("div", { class: "state state--empty",
                      text: "Nav notikumu šim aktīvam." }),
        );
        return;
      }
      const thead = el("thead", null, [
        el("tr", null, [
          "Tips", "Smagums", "Statuss", "Virsraksts",
          "Atklāts", "Aizvērts",
        ].map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      items.forEach((e) => {
        tbody.appendChild(
          el("tr", null, [
            el("td", { text: e.event_type || "—" }),
            el("td", null, [severityBadge(e.severity)]),
            el("td", null, [eventStatusBadge(e.status)]),
            el("td", { text: e.title || "—" }),
            el("td", { class: "numeric", text: formatTimestamp(e.detected_at) }),
            el("td", { class: "numeric", text: formatTimestamp(e.closed_at) }),
          ]),
        );
      });
      wrapper.appendChild(el("table", { class: "data-table" }, [thead, tbody]));
    }

    // Phase 7 Task 4 follow-up: the asset detail page reuses the
    // simulator workspace ``createSimulatorChart`` helper so the two
    // pages render the same interactive (drag-to-zoom, tooltip,
    // labelled axes, Latvian title + unit) chart. ``charts`` maps
    // metric_key → chart instance (each instance owns its DOM card).
    const charts = Object.create(null);
    const CHART_MAX_POINTS = config.chartMaxPoints || 200;

    // Backward-compatible normaliser: tolerate the legacy "list of
    // strings" shape in case a stale config is served from cache, but
    // prefer the {key, label, unit} dict shape.
    function chartMetricMeta(entry) {
      if (entry && typeof entry === "object") {
        return {
          key: entry.key,
          label: entry.label || entry.key,
          unit: entry.unit || "",
        };
      }
      return { key: entry, label: entry, unit: "" };
    }
    const CHART_METRIC_METAS = CHART_METRICS.map(chartMetricMeta);

    function buildChartGrid() {
      const grid = $("charts-grid");
      if (!grid) return;
      // Tear down previous charts (e.g. on a soft reset) so we don't
      // leak DOM nodes when ``loadAll`` is called repeatedly.
      Object.keys(charts).forEach((k) => {
        try { charts[k].destroy(); } catch (e) { /* noop */ }
        delete charts[k];
      });
      clear(grid);
      if (!CHART_METRIC_METAS.length) {
        grid.appendChild(
          el("div", { class: "state state--empty",
                      text: "Diagrammu metrikas nav konfigurētas." }),
        );
        return;
      }
      CHART_METRIC_METAS.forEach((meta) => {
        if (!meta.key) return;
        charts[meta.key] = createSimulatorChart(grid, {
          title: meta.label,
          unit: meta.unit,
          maxPoints: CHART_MAX_POINTS,
        });
      });
    }

    function setChartEmptyState(metric, message) {
      // ``createSimulatorChart`` already shows an empty-state when its
      // points buffer is empty. For load-error states we re-render the
      // empty pill with a descriptive message.
      const chart = charts[metric];
      if (!chart) return;
      const empty = chart.node.querySelector(".chart-card__empty");
      if (empty) {
        empty.textContent = message;
        empty.hidden = false;
      }
    }

    function renderChart(metric, payload) {
      const chart = charts[metric];
      if (!chart) return;
      const items = Array.isArray(payload) ? payload : [];
      // API returns measurements newest-first; the chart wants
      // chronological order so zoom + tooltip lookups stay coherent.
      const ordered = items.slice().reverse();
      const rows = ordered
        .filter((m) => m && m.timestamp && m.value !== null && m.value !== undefined)
        .map((m) => ({ t: new Date(m.timestamp), v: Number(m.value) }))
        .filter((r) => !Number.isNaN(r.t.getTime()) && !Number.isNaN(r.v));
      chart.setData(rows);
    }

    async function loadSummary() {
      setState($("identity-state"), "loading", "Ielādē…");
      setState($("state-cards-state"), "loading", "Ielādē…");
      setState($("raw-state"), "loading", "Ielādē…");
      try {
        const data = await fetchJson(SUMMARY_URL);
        renderIdentity(data);
        renderStateCards(data);
        renderRawPanel(data);
        return data;
      } catch (err) {
        if (err && err.status === 404) {
          showPageError(`Aktīvs "${ASSET}" netika atrasts.`);
          return null;
        }
        const msg =
          "Kļūda ielādējot kopsavilkumu: "
          + (err && err.message ? err.message : "nezināma");
        setState($("identity-state"), "error", msg);
        setState($("state-cards-state"), "error", msg);
        setState($("raw-state"), "error", msg);
        return null;
      }
    }

    async function loadMeasurements() {
      setState($("measurements-state"), "loading", "Ielādē…");
      try {
        const data = await fetchJson(MEASUREMENTS_URL);
        renderMeasurementsTable(data);
      } catch (err) {
        setState(
          $("measurements-state"),
          "error",
          "Kļūda ielādējot mērījumus: "
            + (err && err.message ? err.message : "nezināma"),
        );
      }
    }

    async function loadEvents() {
      setState($("events-state"), "loading", "Ielādē…");
      try {
        const data = await fetchJson(EVENTS_URL);
        renderEventsTable(data);
      } catch (err) {
        setState(
          $("events-state"),
          "error",
          "Kļūda ielādējot notikumus: "
            + (err && err.message ? err.message : "nezināma"),
        );
      }
    }

    async function loadChart(metric) {
      try {
        const url = CHART_URL_TEMPLATE.replace(
          "__METRIC__", encodeURIComponent(metric),
        );
        const data = await fetchJson(url);
        renderChart(metric, data);
      } catch (err) {
        setChartEmptyState(
          metric,
          "Kļūda: " + (err && err.message ? err.message : "nezināma"),
        );
      }
    }

    async function loadCharts() {
      // Build the grid lazily on first call so the chart factories are
      // attached only once. Subsequent refreshes only refetch + setData,
      // which preserves the user's current zoom on each chart.
      if (Object.keys(charts).length === 0) buildChartGrid();
      await Promise.all(CHART_METRIC_METAS.map((m) => loadChart(m.key)));
    }

    async function loadAll() {
      const summary = await loadSummary();
      if (summary === null) return;
      await Promise.all([loadMeasurements(), loadEvents(), loadCharts()]);
      // Update the global "Atjaunots" timestamp using summary metadata.
      const generatedAt = $("generated-at");
      if (generatedAt) {
        generatedAt.textContent =
          "Atjaunots: " + formatTimestamp(new Date().toISOString());
      }
      const healthPill = $("health-pill");
      if (healthPill) {
        healthPill.classList.remove("status-pill--degraded");
        healthPill.classList.add("status-pill--ok");
        healthPill.textContent = "OK";
      }
    }

    setLiveStatus(WEBSOCKET_PATH ? "connecting" : "disabled");
    const refreshController = wireRefreshControls(loadAll, AUTO_INTERVAL_MS);

    function eventTouchesThisAsset(payload) {
      if (!payload) return false;
      // Global events that should always refresh: simulator status only
      // affects this page indirectly (no UI on detail page) so we ignore
      // it. Other events must reference this asset.
      if (payload.asset_code && payload.asset_code === ASSET) return true;
      if (payload.asset_id && payload.asset_id === ASSET) return true;
      return false;
    }

    function handleLiveEventAsset(payload) {
      if (!payload || typeof payload !== "object") return;
      const evt = payload.event_type;
      if (!evt || evt === "connection_ack" || evt === "pong") return;
      // Asset-specific channels are joined per-identifier, so messages
      // arrive only for relevant assets — but we still cross-check the
      // payload because the consumer also subscribes to the global
      // overview group.
      if (
        evt === "telemetry_received" ||
        evt === "asset_state_updated" ||
        evt === "raw_message_received" ||
        evt === "anomaly_created"
      ) {
        if (!eventTouchesThisAsset(payload)) return;
        // Cheap incremental refresh: summary + charts pick up new data
        // points; events table catches new anomalies.
        loadSummary();
        if (evt === "anomaly_created") loadEvents();
        if (evt === "telemetry_received" || evt === "raw_message_received") {
          loadMeasurements();
          // Refresh just the affected metric chart when known, to avoid
          // re-fetching all four when one new value lands. The chart
          // helper preserves the user's zoom state on ``setData``, so
          // a per-metric refresh is non-destructive.
          if (
            payload.metric_key
            && CHART_METRIC_METAS.some((m) => m.key === payload.metric_key)
          ) {
            loadChart(payload.metric_key);
          } else {
            loadCharts();
          }
        }
      }
    }

    let liveConnection = null;
    if (WEBSOCKET_PATH) {
      liveConnection = connectLiveUpdates(WEBSOCKET_PATH, {
        onOpen() {
          if (LIVE_AUTO_INTERVAL_MS > 0) {
            refreshController.setInterval(LIVE_AUTO_INTERVAL_MS);
          }
        },
        onClose() {
          refreshController.setInterval(AUTO_INTERVAL_MS);
        },
        onEvent: handleLiveEventAsset,
      });
      window.addEventListener("beforeunload", () => liveConnection.close());
    } else {
      setLiveStatus("disabled");
    }

    loadAll();
  }

  // ────────────────────────────────────────────────────────────────────
  // Events list page (/dashboard/events/)
  // ────────────────────────────────────────────────────────────────────

  function buildQueryString(params) {
    const parts = [];
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value === null || value === undefined) return;
      const str = String(value).trim();
      if (str === "") return;
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(str)}`);
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function readFilterForm(form) {
    // Plain helper that maps form controls keyed by ``name`` to their
    // current value. Empty strings are returned as ``""`` so callers
    // can decide whether to skip them — buildQueryString skips empties.
    const out = {};
    Array.from(form.elements).forEach((node) => {
      if (!node.name) return;
      if (node.type === "checkbox") {
        out[node.name] = node.checked ? "true" : "";
      } else {
        out[node.name] = node.value;
      }
    });
    return out;
  }

  function initEventsList(config) {
    const ENDPOINT = (config.endpoints && config.endpoints.events) || "/api/events/";
    const DETAIL_TPL = config.eventDetailUrlTemplate || "";
    const ASSET_TPL = config.assetDetailUrlTemplate || "";

    const form = $("events-filter");
    const wrapper = $("events-table-wrapper");
    const meta = $("events-meta");
    const errBox = $("events-error");
    const emptyBox = $("events-empty");
    const loadingBox = $("events-loading");

    function setLoading(active) {
      if (loadingBox) loadingBox.hidden = !active;
    }

    function showError(message) {
      if (!errBox) return;
      errBox.hidden = false;
      errBox.textContent = message;
    }

    function clearStates() {
      if (errBox) {
        errBox.hidden = true;
        errBox.textContent = "";
      }
      if (emptyBox) emptyBox.hidden = true;
      if (meta) meta.textContent = "";
    }

    function renderTable(items) {
      if (!wrapper) return;
      clear(wrapper);
      if (!items || items.length === 0) {
        if (emptyBox) emptyBox.hidden = false;
        return;
      }

      const headers = [
        "Tips", "Smagums", "Statuss", "Virsraksts",
        "Aktīvs", "Ierīce", "Sensors", "Metrika",
        "Atklāts", "Slēgts", "Avots", "Detaļas",
      ];
      const thead = el("thead", null, [
        el("tr", null, headers.map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      items.forEach((row) => {
        const detailUrl = fillTemplate(DETAIL_TPL, "__ID__", row.id);
        const assetUrl = fillTemplate(ASSET_TPL, "__CODE__", row.asset_code);
        tbody.appendChild(
          el("tr", { "data-role": "event-row", "data-event-id": row.id }, [
            el("td", { class: "monospace", text: row.event_type || "—" }),
            el("td", null, [severityBadge(row.severity)]),
            el("td", null, [eventStatusBadge(row.status)]),
            el("td", { text: row.title || "—" }),
            el("td", null, [
              assetUrl && row.asset_code
                ? el("a", { href: assetUrl, text: row.asset_code })
                : document.createTextNode(row.asset_code || "—"),
            ]),
            el("td", { class: "monospace",
                       text: row.device_uid || "—" }),
            el("td", { class: "monospace",
                       text: row.sensor_code || "—" }),
            el("td", { class: "monospace",
                       text: row.metric_key || "—" }),
            el("td", { text: formatTimestamp(row.detected_at) }),
            el("td", { text: formatTimestamp(row.closed_at) }),
            el("td", { class: "monospace", text: row.source || "—" }),
            el("td", { class: "row-actions" }, [
              detailUrl
                ? el("a", {
                    href: detailUrl,
                    "data-role": "event-detail-link",
                    text: "Atvērt",
                  })
                : document.createTextNode("—"),
            ]),
          ]),
        );
      });
      const table = el("table", { class: "data-table",
                                  "data-role": "events-table" },
                      [thead, tbody]);
      wrapper.appendChild(table);
    }

    async function loadEvents() {
      clearStates();
      setLoading(true);
      const filters = readFilterForm(form);
      const url = ENDPOINT + buildQueryString(filters);
      try {
        const data = await fetchJson(url);
        // DRF list responses are bare arrays (no pagination wrapper).
        const items = Array.isArray(data) ? data : (data.results || []);
        renderTable(items);
        if (meta) {
          meta.textContent = `Parādīti ${items.length} notikumi (${url}).`;
        }
      } catch (err) {
        renderTable([]);
        showError(
          `Kļūda ielādējot notikumus: ${err.status || ""} ${err.message || err}`,
        );
      } finally {
        setLoading(false);
      }
    }

    // Initial population — read URL query string so deep links survive.
    const url = new URL(window.location.href);
    Array.from(form.elements).forEach((node) => {
      if (!node.name) return;
      const fromUrl = url.searchParams.get(node.name);
      if (fromUrl !== null) node.value = fromUrl;
    });

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      loadEvents();
    });
    const resetBtn = $("events-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        form.reset();
        loadEvents();
      });
    }
    const refreshBtn = $("events-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadEvents());

    loadEvents();
  }

  // ────────────────────────────────────────────────────────────────────
  // Event detail page (/dashboard/events/<id>/)
  // ────────────────────────────────────────────────────────────────────

  function renderJsonPayload(obj) {
    // Pretty-print as JSON with stable spacing so the snapshot is
    // grep-friendly for operators. Returns a string.
    try {
      return JSON.stringify(obj, null, 2);
    } catch (err) {
      return String(obj);
    }
  }

  function initEventDetail(config) {
    const EVENT_URL = config.eventDetailUrl;
    const MEAS_URL = config.measurementsUrl;
    const EVENTS_LIST_URL = config.eventsListUrl;
    const ASSET_TPL = config.assetDetailUrlTemplate || "";
    const PERIODS = Array.isArray(config.periods) ? config.periods : [];
    const DEFAULT_PERIOD = config.defaultPeriod || "24h";
    const TIMELINE_LIMIT = config.timelineLimit || 1000;

    let currentEvent = null;       // last successful event payload
    let currentPeriodId = DEFAULT_PERIOD;

    function showPageError(message) {
      const banner = $("page-error");
      if (banner) {
        banner.hidden = false;
        clear(banner);
        banner.appendChild(
          el("div", { class: "state state--error" }, [
            el("strong", { text: message }),
            " ",
            el("a", { href: EVENTS_LIST_URL,
                      text: "Atgriezties uz notikumu sarakstu" }),
          ]),
        );
      }
      [
        "event-identity-state", "event-context-state",
        "event-measurement-state", "timeline-state",
      ].forEach((role) => setState($(role), "empty", "—"));
    }

    function renderIdentity(event) {
      const wrapper = $("event-identity");
      if (!wrapper) return;
      clear(wrapper);

      const title = $("event-title");
      if (title) title.textContent = event.title || `Notikums ${event.id}`;

      wrapper.appendChild(
        el("div", { class: "identity-grid" }, [
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Tips" }),
            el("span", { class: "identity-item__value monospace",
                          text: event.event_type || "—" }),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Smagums" }),
            el("span", { class: "identity-item__value" },
                [severityBadge(event.severity)]),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Statuss" }),
            el("span", { class: "identity-item__value" },
                [eventStatusBadge(event.status)]),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Avots" }),
            el("span", { class: "identity-item__value monospace",
                          text: event.source || "—" }),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Atklāts" }),
            el("span", { class: "identity-item__value",
                          text: formatTimestamp(event.detected_at) }),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label",
                          text: "Apstiprināts" }),
            el("span", { class: "identity-item__value",
                          text: formatTimestamp(event.acknowledged_at) }),
          ]),
          el("div", { class: "identity-item" }, [
            el("span", { class: "identity-item__label", text: "Slēgts" }),
            el("span", { class: "identity-item__value",
                          text: formatTimestamp(event.closed_at) }),
          ]),
        ]),
      );
      if (event.description) {
        wrapper.appendChild(
          el("p", { class: "event-detail__description",
                    text: event.description }),
        );
      }
    }

    function renderContext(event) {
      const wrapper = $("event-context");
      if (!wrapper) return;
      clear(wrapper);

      const assetUrl = fillTemplate(ASSET_TPL, "__CODE__", event.asset_code);

      const rows = [
        ["Site", event.site_code],
        ["Aktīvs", event.asset_code, assetUrl],
        ["Ierīce", event.device_uid],
        ["Sensors", event.sensor_code],
        ["Metrika", event.metric_key],
        ["Mērījuma ID", event.measurement],
        ["Raw message ID", event.raw_message],
      ];
      rows.forEach(([label, value, href]) => {
        const valueNode = href && value
          ? el("a", { href: href, text: String(value),
                      "data-role": "context-asset-link" })
          : document.createTextNode(value ? String(value) : "—");
        wrapper.appendChild(
          el("div", { class: "context-grid__row" }, [
            el("span", { class: "context-grid__label", text: label }),
            el("span", { class: "context-grid__value monospace" },
                [valueNode]),
          ]),
        );
      });
    }

    async function renderMeasurementBlock(event) {
      const root = $("event-measurement");
      if (!root) return;
      clear(root);
      if (!event.measurement) {
        root.appendChild(
          el("div", { class: "state state--empty",
                       text: "Šim notikumam nav saistīta mērījuma." }),
        );
        return;
      }
      // ``event.measurement`` is the FK id. Fetch via the list endpoint
      // for the measurement detail; if not available there, fall back
      // to inline summary from sensor/metric of the event itself.
      try {
        // /api/measurements/{id}/ exists via DRF DefaultRouter retrieve.
        const url = MEAS_URL.replace(/\/$/, "") + "/" + encodeURIComponent(event.measurement) + "/";
        const m = await fetchJson(url);
        root.appendChild(
          el("dl", { class: "measurement-list" }, [
            el("dt", { text: "Laiks" }),
            el("dd", { text: formatTimestamp(m.timestamp) }),
            el("dt", { text: "Vērtība" }),
            el("dd", { text: `${formatNumber(m.value)} ${m.unit || ""}`.trim() }),
            el("dt", { text: "Sensors" }),
            el("dd", { class: "monospace", text: m.sensor_code || "—" }),
            el("dt", { text: "Metrika" }),
            el("dd", { class: "monospace", text: m.metric_key || "—" }),
            el("dt", { text: "Kvalitāte" }),
            el("dd", { text: m.quality || "—" }),
            el("dt", { text: "Raw message" }),
            el("dd", { class: "monospace", text: m.raw_message || "—" }),
          ]),
        );
      } catch (err) {
        root.appendChild(
          el("div", { class: "state state--error",
                       text: `Mērījumu nevarēja ielādēt: ${err.message || err}` }),
        );
      }
    }

    function renderPayload(event) {
      const node = $("event-payload");
      if (!node) return;
      node.textContent = renderJsonPayload(event.payload || {});
    }

    function renderPeriodButtons() {
      const root = $("period-buttons");
      if (!root) return;
      clear(root);
      PERIODS.forEach((p) => {
        const btn = el("button", {
          type: "button",
          class: "period-btn",
          "data-role": "period-btn",
          "data-period-id": p.id,
          text: p.label,
        });
        btn.addEventListener("click", () => {
          currentPeriodId = p.id;
          updatePeriodButtonsState();
          loadTimeline();
        });
        root.appendChild(btn);
      });
      updatePeriodButtonsState();
    }

    function updatePeriodButtonsState() {
      document.querySelectorAll('[data-role="period-btn"]').forEach((btn) => {
        const active = btn.dataset.periodId === currentPeriodId;
        btn.classList.toggle("period-btn--active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function computePeriodRange(periodId, anchor) {
      // Anchor: event.detected_at converted to a Date. ``periodId='all'``
      // returns no range (timeline shows all available data).
      const period = PERIODS.find((p) => p.id === periodId);
      if (!period || period.hours === null) {
        return { from: null, to: null };
      }
      const anchorMs = anchor.getTime();
      const halfWindow = (period.hours * 3600 * 1000) / 2;
      // Centre the window on detected_at but clip the "to" side so the
      // chart does not project into the future beyond now.
      const nowMs = Date.now();
      let toMs = anchorMs + halfWindow;
      if (toMs > nowMs) toMs = nowMs;
      const fromMs = toMs - period.hours * 3600 * 1000;
      return {
        from: new Date(fromMs).toISOString(),
        to: new Date(toMs).toISOString(),
      };
    }

    function readCustomRange() {
      const f = $("timeline-from");
      const t = $("timeline-to");
      const fromValue = f && f.value ? new Date(f.value).toISOString() : null;
      const toValue = t && t.value ? new Date(t.value).toISOString() : null;
      return { from: fromValue, to: toValue };
    }

    async function loadTimeline() {
      const section = $("event-timeline-section");
      const stateNode = $("timeline-state");
      const summary = $("timeline-summary");
      const chart = $("timeline-chart");

      if (!currentEvent || !section) return;
      const sensorCode = currentEvent.sensor_code;
      const metricKey = currentEvent.metric_key;
      if (!sensorCode || !metricKey) {
        section.hidden = true;
        return;
      }
      section.hidden = false;

      let range;
      if (currentPeriodId === "custom") {
        range = readCustomRange();
      } else {
        range = computePeriodRange(
          currentPeriodId, new Date(currentEvent.detected_at),
        );
      }

      const params = {
        sensor: sensorCode,
        metric: metricKey,
        limit: TIMELINE_LIMIT,
      };
      if (range.from) params.from = range.from;
      if (range.to) params.to = range.to;

      const url = MEAS_URL + buildQueryString(params);
      setState(stateNode, "loading", "Ielādē…");
      if (summary) summary.textContent = "";
      clear(chart);

      try {
        const measurements = await fetchJson(url);
        const items = Array.isArray(measurements) ? measurements : [];
        if (items.length === 0) {
          setState(stateNode, "empty",
            "Nav mērījumu izvēlētajā periodā.");
          return;
        }
        // Measurements arrive newest-first; sort oldest-first for the chart.
        const points = items
          .map((m) => [new Date(m.timestamp), m.value])
          .filter((p) => !Number.isNaN(p[0].getTime())
                        && p[1] !== null && p[1] !== undefined)
          .sort((a, b) => a[0] - b[0]);
        const drawn = renderSparkline(chart, points);
        if (!drawn) {
          setState(stateNode, "empty", "Mērījumi neizdevās attēlot.");
          return;
        }
        setState(stateNode, "ok", "");
        stateNode.hidden = true;

        if (summary) {
          const values = points.map((p) => p[1]);
          const min = Math.min.apply(null, values);
          const max = Math.max.apply(null, values);
          const last = points[points.length - 1];
          clear(summary);
          summary.appendChild(el("span", null, [
            el("strong", { text: "Pēdējais: " }),
            document.createTextNode(`${formatNumber(last[1])} (${formatTimestamp(last[0])})`),
          ]));
          summary.appendChild(el("span", { class: "timeline-summary__pill",
                                           text: `min ${formatNumber(min)}` }));
          summary.appendChild(el("span", { class: "timeline-summary__pill",
                                           text: `max ${formatNumber(max)}` }));
          summary.appendChild(el("span", { class: "timeline-summary__pill",
                                           text: `${points.length} punkti` }));
        }

        const ctx = $("event-timeline-context");
        if (ctx) {
          ctx.textContent = `Sensors ${sensorCode}, metrika ${metricKey}.`;
        }
      } catch (err) {
        setState(stateNode, "error",
          `Kļūda ielādējot timeline: ${err.message || err}`);
      }
    }

    function bindCustomRangeForm() {
      const form = $("timeline-custom");
      if (!form) return;
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        currentPeriodId = "custom";
        updatePeriodButtonsState();
        loadTimeline();
      });
    }

    async function loadEvent() {
      try {
        const event = await fetchJson(EVENT_URL);
        currentEvent = event;
        renderIdentity(event);
        renderContext(event);
        renderPayload(event);
        renderMeasurementBlock(event);
        renderPeriodButtons();
        loadTimeline();
      } catch (err) {
        if (err.status === 404) {
          showPageError("Notikums netika atrasts (404).");
        } else {
          showPageError(`Neizdevās ielādēt notikumu: ${err.message || err}`);
        }
      }
    }

    bindCustomRangeForm();
    loadEvent();
  }

  // ── Page dispatch ───────────────────────────────────────────────────
  // simulator workspace init lives below the dispatcher to keep the
  // existing pages above untouched.

  document.addEventListener("DOMContentLoaded", () => {
    const simulatorConfig = readJsonScript("simulator-config");
    if (simulatorConfig) {
      initSimulatorWorkspace(simulatorConfig);
      return;
    }
    const eventDetailConfig = readJsonScript("event-detail-config");
    if (eventDetailConfig) {
      initEventDetail(eventDetailConfig);
      return;
    }
    const eventsListConfig = readJsonScript("events-list-config");
    if (eventsListConfig) {
      initEventsList(eventsListConfig);
      return;
    }
    const detailConfig = readJsonScript("asset-detail-config");
    if (detailConfig) {
      initAssetDetail(detailConfig);
      return;
    }
    const overviewConfig = readJsonScript("dashboard-config");
    if (overviewConfig) {
      initOverview(overviewConfig);
      return;
    }
    document.body.appendChild(
      el("div", {
        class: "state state--error",
        text: "Dashboard konfigurācija nav pieejama. Atjaunojiet lapu.",
      }),
    );
  });

  // ────────────────────────────────────────────────────────────────────
  // Phase 7, Task 4 — Simulator workspace (/dashboard/simulator/)
  // ────────────────────────────────────────────────────────────────────

  // Lightweight time-series chart used by the simulator workspace.
  // Designed for the project's "vanilla JS, no frameworks" rule:
  //   * one chart per metric;
  //   * X axis = timestamp, Y axis = numeric value with unit;
  //   * tooltip on hover, drag-to-zoom on the X axis, reset-zoom button;
  //   * append-only data buffer (rolling FIFO at ``maxPoints``);
  //   * full re-render on data change is cheap because each chart holds
  //     at most a few hundred points and there are only ~5 charts.
  function createSimulatorChart(host, options) {
    const opts = options || {};
    const title = opts.title || "Metrika";
    const unit = opts.unit || "";
    const maxPoints = opts.maxPoints || 200;
    const W = opts.width || 520;
    const H = opts.height || 220;
    const PAD = { top: 12, right: 16, bottom: 36, left: 56 };
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;

    const points = []; // [{t: Date, v: number}]
    let zoom = null;   // {fromMs, toMs} or null

    const titleNode = el("h3", {
      class: "chart-card__title",
      text: title + (unit ? " (" + unit + ")" : ""),
    });
    const resetBtn = el("button", {
      type: "button",
      class: "btn chart-card__reset",
      text: "Atiestatīt skatu",
    });
    resetBtn.addEventListener("click", () => { zoom = null; render(); });

    const header = el("div", { class: "chart-card__header" }, [
      titleNode, resetBtn,
    ]);

    const svgNode = svg("svg", {
      class: "chart-card__svg",
      viewBox: "0 0 " + W + " " + H,
      preserveAspectRatio: "none",
      role: "img",
      "aria-label": title,
    });

    const tooltip = el("div", { class: "chart-card__tooltip", hidden: true });
    const empty = el("div", {
      class: "state state--empty chart-card__empty",
      text: "Nav datu šai metrikai.",
    });

    const card = el("div", { class: "chart-card" }, [
      header, svgNode, tooltip, empty,
    ]);
    if (host) host.appendChild(card);

    // ── helpers ──
    function clearSvg() {
      while (svgNode.firstChild) svgNode.removeChild(svgNode.firstChild);
    }

    function visiblePoints() {
      if (!zoom) return points.slice();
      return points.filter((p) => {
        const ms = p.t.getTime();
        return ms >= zoom.fromMs && ms <= zoom.toMs;
      });
    }

    function niceStep(range, targetTicks) {
      if (range <= 0) return 1;
      const raw = range / Math.max(1, targetTicks);
      const mag = Math.pow(10, Math.floor(Math.log10(raw)));
      const norm = raw / mag;
      let step;
      if (norm < 1.5) step = 1;
      else if (norm < 3) step = 2;
      else if (norm < 7) step = 5;
      else step = 10;
      return step * mag;
    }

    function render() {
      clearSvg();
      const data = visiblePoints();
      empty.hidden = data.length > 0;
      if (data.length === 0) return;

      const xs = data.map((p) => p.t.getTime());
      const ys = data.map((p) => p.v);
      let minX = Math.min.apply(null, xs);
      let maxX = Math.max.apply(null, xs);
      let minY = Math.min.apply(null, ys);
      let maxY = Math.max.apply(null, ys);
      if (maxX === minX) { maxX = minX + 1; }
      if (maxY === minY) {
        const pad = Math.abs(minY) * 0.1 || 1;
        maxY = minY + pad;
        minY = minY - pad;
      } else {
        // breathing room on Y range
        const padY = (maxY - minY) * 0.08;
        minY -= padY; maxY += padY;
      }

      function xScale(ms) {
        return PAD.left + ((ms - minX) / (maxX - minX)) * innerW;
      }
      function yScale(v) {
        return PAD.top + innerH - ((v - minY) / (maxY - minY)) * innerH;
      }

      // Plot background + frame
      svgNode.appendChild(svg("rect", {
        x: PAD.left, y: PAD.top, width: innerW, height: innerH,
        fill: "#fff", stroke: "var(--color-border)",
      }));

      // Y gridlines + tick labels
      const yStep = niceStep(maxY - minY, 4);
      const yStart = Math.ceil(minY / yStep) * yStep;
      for (let v = yStart; v <= maxY; v += yStep) {
        const y = yScale(v);
        svgNode.appendChild(svg("line", {
          x1: PAD.left, x2: PAD.left + innerW, y1: y, y2: y,
          stroke: "var(--color-border)", "stroke-dasharray": "3,3",
        }));
        svgNode.appendChild(svg("text", {
          x: PAD.left - 6, y: y + 3,
          "text-anchor": "end", "font-size": "10",
          fill: "var(--color-muted)",
          text: formatTickValue(v) + (unit ? " " + unit : ""),
        }));
      }

      // X tick labels (3 ticks: start, middle, end)
      const xLabelMs = [minX, (minX + maxX) / 2, maxX];
      xLabelMs.forEach((ms) => {
        svgNode.appendChild(svg("text", {
          x: xScale(ms), y: PAD.top + innerH + 14,
          "text-anchor": "middle", "font-size": "10",
          fill: "var(--color-muted)", text: formatTimeShort(new Date(ms)),
        }));
      });

      // Axis titles
      svgNode.appendChild(svg("text", {
        x: PAD.left + innerW / 2, y: H - 6,
        "text-anchor": "middle", "font-size": "11",
        fill: "var(--color-muted)", text: "Laiks",
      }));
      const yTitle = title + (unit ? " (" + unit + ")" : "");
      const yLabel = svg("text", {
        x: 12, y: PAD.top + innerH / 2,
        "text-anchor": "middle", "font-size": "11",
        fill: "var(--color-muted)", text: yTitle,
        transform: "rotate(-90, 12, " + (PAD.top + innerH / 2) + ")",
      });
      svgNode.appendChild(yLabel);

      // Polyline
      const ptsAttr = data.map(
        (p) => xScale(p.t.getTime()) + "," + yScale(p.v),
      ).join(" ");
      svgNode.appendChild(svg("polyline", {
        points: ptsAttr, fill: "none",
        stroke: "var(--color-primary)", "stroke-width": 1.6,
        "stroke-linejoin": "round", "stroke-linecap": "round",
      }));

      // Last-point marker
      const last = data[data.length - 1];
      svgNode.appendChild(svg("circle", {
        cx: xScale(last.t.getTime()), cy: yScale(last.v),
        r: 3, fill: "var(--color-primary)",
      }));

      // Drag-to-zoom rectangle (transparent overlay catches events).
      const overlay = svg("rect", {
        x: PAD.left, y: PAD.top, width: innerW, height: innerH,
        fill: "transparent", style: "cursor: crosshair;",
      });
      svgNode.appendChild(overlay);

      const dragRect = svg("rect", {
        x: 0, y: PAD.top, width: 0, height: innerH,
        fill: "var(--color-primary)", "fill-opacity": "0.15",
        stroke: "var(--color-primary)", "stroke-dasharray": "3,3",
        visibility: "hidden",
      });
      svgNode.appendChild(dragRect);

      const cursor = svg("line", {
        x1: 0, x2: 0, y1: PAD.top, y2: PAD.top + innerH,
        stroke: "var(--color-muted)", "stroke-dasharray": "2,2",
        visibility: "hidden",
      });
      svgNode.appendChild(cursor);
      const cursorDot = svg("circle", {
        cx: 0, cy: 0, r: 4, fill: "var(--color-primary)",
        visibility: "hidden",
      });
      svgNode.appendChild(cursorDot);

      function svgPoint(evt) {
        const r = svgNode.getBoundingClientRect();
        const xRatio = (evt.clientX - r.left) / r.width;
        const yRatio = (evt.clientY - r.top) / r.height;
        return { x: xRatio * W, y: yRatio * H };
      }

      function nearestPoint(xPx) {
        if (data.length === 0) return null;
        let best = data[0];
        let bestDx = Math.abs(xScale(best.t.getTime()) - xPx);
        for (let i = 1; i < data.length; i += 1) {
          const dx = Math.abs(xScale(data[i].t.getTime()) - xPx);
          if (dx < bestDx) { best = data[i]; bestDx = dx; }
        }
        return best;
      }

      function showTooltip(p, xPx, yPx) {
        cursor.setAttribute("x1", xPx);
        cursor.setAttribute("x2", xPx);
        cursor.setAttribute("visibility", "visible");
        cursorDot.setAttribute("cx", xPx);
        cursorDot.setAttribute("cy", yPx);
        cursorDot.setAttribute("visibility", "visible");
        tooltip.hidden = false;
        tooltip.textContent = (
          formatTimestamp(p.t) + " — "
          + formatNumber(p.v) + (unit ? " " + unit : "")
        );
      }
      function hideTooltip() {
        tooltip.hidden = true;
        cursor.setAttribute("visibility", "hidden");
        cursorDot.setAttribute("visibility", "hidden");
      }

      let dragStartX = null;
      overlay.addEventListener("pointermove", (evt) => {
        const pt = svgPoint(evt);
        if (dragStartX !== null) {
          const x = Math.min(dragStartX, pt.x);
          const w = Math.abs(pt.x - dragStartX);
          dragRect.setAttribute("x", x);
          dragRect.setAttribute("width", w);
          dragRect.setAttribute("visibility", "visible");
        } else {
          const np = nearestPoint(pt.x);
          if (np) showTooltip(np, xScale(np.t.getTime()), yScale(np.v));
        }
      });
      overlay.addEventListener("pointerleave", () => {
        dragStartX = null;
        dragRect.setAttribute("visibility", "hidden");
        hideTooltip();
      });
      overlay.addEventListener("pointerdown", (evt) => {
        const pt = svgPoint(evt);
        dragStartX = pt.x;
        try { overlay.setPointerCapture(evt.pointerId); } catch (e) { /* noop */ }
      });
      overlay.addEventListener("pointerup", (evt) => {
        const pt = svgPoint(evt);
        if (dragStartX !== null) {
          const dx = Math.abs(pt.x - dragStartX);
          if (dx > 6) {
            const x1 = Math.min(dragStartX, pt.x);
            const x2 = Math.max(dragStartX, pt.x);
            // Convert SVG x back to ms
            const ratio1 = Math.max(0, Math.min(1, (x1 - PAD.left) / innerW));
            const ratio2 = Math.max(0, Math.min(1, (x2 - PAD.left) / innerW));
            const fromMs = minX + ratio1 * (maxX - minX);
            const toMs = minX + ratio2 * (maxX - minX);
            zoom = { fromMs, toMs };
            render();
          }
        }
        dragStartX = null;
        dragRect.setAttribute("visibility", "hidden");
      });
      svgNode.addEventListener("dblclick", () => {
        zoom = null; render();
      });
    }

    function addPoint(t, v) {
      const date = (t instanceof Date) ? t : new Date(t);
      if (Number.isNaN(date.getTime())) return;
      const num = Number(v);
      if (Number.isNaN(num)) return;
      points.push({ t: date, v: num });
      while (points.length > maxPoints) points.shift();
      render();
    }

    function setData(rows) {
      points.length = 0;
      (rows || []).forEach((r) => points.push(r));
      while (points.length > maxPoints) points.shift();
      zoom = null;
      render();
    }

    function destroy() {
      if (card.parentNode) card.parentNode.removeChild(card);
    }

    function formatTickValue(v) {
      if (Math.abs(v) >= 1000 || Math.abs(v) < 0.01) {
        return Number(v).toPrecision(3);
      }
      return Number(v).toFixed(2);
    }
    function formatTimeShort(d) {
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      const ss = String(d.getSeconds()).padStart(2, "0");
      return hh + ":" + mm + ":" + ss;
    }

    render();

    return { addPoint, setData, destroy, render, node: card };
  }

  // ── Simulator workspace init ─────────────────────────────────────────

  function initSimulatorWorkspace(config) {
    const ENDPOINTS = config.endpoints || {};
    const AUTO_INTERVAL_MS =
      Math.max(0, (config.autoRefreshIntervalSeconds || 0) * 1000);
    const LIVE_AUTO_INTERVAL_MS =
      Math.max(0, (config.liveAutoRefreshIntervalSeconds || 0) * 1000);
    const WEBSOCKET_PATH = config.websocketPath || "";
    const CHART_METRICS = (config.chartMetrics || []).slice();
    const CHART_MAX_POINTS = config.chartMaxPoints || 200;
    const STREAM_MAX_ROWS = config.mqttStreamMaxRows || 100;

    const AUTH = {
      canControl: config.canControlSimulator === true,
      isAuthenticated: config.isAuthenticated === true,
      csrfToken: config.csrfToken || "",
    };

    // ── State ──────────────────────────────────────────────────────────
    let profiles = [];           // server-side profile list
    let activeProfileCode = "";  // currently selected
    let editorState = null;      // working copy of the active profile
    const charts = {};           // metric_key → chart instance
    let creating = false;        // true when creating a fresh profile

    // ── Permission application ────────────────────────────────────────
    function applyPermission() {
      const allowed = AUTH.canControl;
      const buttonRoles = [
        "simulator-start-btn", "simulator-stop-btn",
        "simulator-run-once-btn", "profile-save-btn", "profile-new-btn",
        "profile-reset-btn",
      ];
      buttonRoles.forEach((role) => {
        const btn = $(role);
        if (!btn) return;
        btn.disabled = !allowed;
        btn.setAttribute("aria-disabled", String(!allowed));
        if (!allowed) {
          btn.title = AUTH.isAuthenticated
            ? "Jums nav tiesību vadīt simulatoru."
            : "Lai vadītu simulatoru, lietotājam jābūt pierakstītam sistēmā.";
        } else {
          btn.removeAttribute("title");
        }
      });
      // Editor inputs
      [
        "profile-name", "profile-code", "profile-site-code",
        "profile-interval",
      ].forEach((role) => {
        const input = $(role);
        if (input) input.readOnly = !allowed;
      });
      const tableBody = $("profile-metrics-body");
      if (tableBody) {
        tableBody.querySelectorAll("input").forEach((inp) => {
          inp.disabled = !allowed;
        });
      }
      const notice = $("simulator-permission-notice");
      if (notice) {
        if (allowed) {
          notice.hidden = true;
          notice.textContent = "";
        } else {
          notice.hidden = false;
          notice.textContent = AUTH.isAuthenticated
            ? "Jums nav tiesību vadīt vai konfigurēt simulatoru."
            : "Lai vadītu simulatoru, lietotājam jābūt pierakstītam sistēmā.";
        }
      }
    }

    // ── Status panel ──────────────────────────────────────────────────
    function showSimulatorFeedback(kind, message) {
      const node = $("simulator-feedback");
      if (!node) return;
      node.hidden = false;
      clear(node);
      node.appendChild(
        el("div", { class: "state state--" + kind, text: message }),
      );
    }
    function clearSimulatorFeedback() {
      const node = $("simulator-feedback");
      if (!node) return;
      node.hidden = true;
      clear(node);
    }
    function renderSimulatorStatus(data) {
      if (data && typeof data.can_control === "boolean") {
        AUTH.canControl = data.can_control;
      }
      if (data && typeof data.is_authenticated === "boolean") {
        AUTH.isAuthenticated = data.is_authenticated;
      }
      applyPermission();

      const message = $("simulator-message");
      const code = $("simulator-scenario-code");
      const lastRun = $("simulator-last-run");
      const generated = $("simulator-generated");
      const statePill = $("simulator-state-pill");

      if (message) message.textContent = data.message || "—";
      const scenarioCode = (data.scenario && data.scenario.code) || "—";
      if (code) code.textContent = scenarioCode;
      if (lastRun) lastRun.textContent = formatTimestamp(data.last_run_at);
      if (generated) generated.textContent = formatNumber(data.generated_messages);
      if (statePill) {
        statePill.classList.remove(
          "status-pill--ok", "status-pill--degraded", "status-pill--warning",
        );
        if (data.is_active === true) {
          statePill.textContent = "Aktīvs";
          statePill.classList.add("status-pill--ok");
        } else if (data.is_active === false) {
          statePill.textContent = "Apturēts";
          statePill.classList.add("status-pill--degraded");
        } else if (data.ok === false) {
          statePill.textContent = "Nav scenārija";
          statePill.classList.add("status-pill--warning");
        } else {
          statePill.textContent = "—";
        }
      }
    }
    async function refreshSimulatorStatus() {
      const url = ENDPOINTS.simulatorStatus;
      if (!url) return;
      try {
        const data = await fetchJson(url);
        renderSimulatorStatus(data);
      } catch (err) {
        showSimulatorFeedback(
          "error",
          "Nevar ielādēt simulatora statusu: " + (err.message || "kļūda"),
        );
      }
    }

    // ── Action calls (Start / Stop / Run once) ────────────────────────
    function buildHeaders() {
      const csrf = AUTH.csrfToken || getCookie("csrftoken") || "";
      const h = { Accept: "application/json", "Content-Type": "application/json" };
      if (csrf) h["X-CSRFToken"] = csrf;
      return h;
    }
    async function callSimulatorAction(action) {
      if (!AUTH.canControl) {
        showSimulatorFeedback(
          "error",
          AUTH.isAuthenticated
            ? "Jums nav tiesību vadīt simulatoru."
            : "Lai vadītu simulatoru, lietotājam jābūt pierakstītam sistēmā.",
        );
        return;
      }
      const map = {
        "start":     ENDPOINTS.simulatorStart,
        "stop":      ENDPOINTS.simulatorStop,
        "run-once":  ENDPOINTS.simulatorRunOnce,
      };
      const url = map[action];
      if (!url) return;
      clearSimulatorFeedback();
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: buildHeaders(),
          credentials: "same-origin",
          body: JSON.stringify({}),
        });
        const text = await resp.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { /* noop */ }
        if (!resp.ok && !data) throw new Error("HTTP " + resp.status);
        if (data) {
          renderSimulatorStatus(data);
          showSimulatorFeedback(
            data.ok === false ? "error" : "info",
            data.message || "Izpildīts.",
          );
        }
      } catch (err) {
        showSimulatorFeedback(
          "error",
          "Kļūda: " + (err && err.message ? err.message : "nezināma kļūda"),
        );
      }
    }
    function wireControlButtons() {
      const root = $("simulator-actions");
      if (!root) return;
      root.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-action]");
        if (!btn) return;
        callSimulatorAction(btn.dataset.action);
      });
    }

    // ── Profile editor ────────────────────────────────────────────────

    function renderProfileSelect() {
      const select = $("profile-select");
      if (!select) return;
      clear(select);
      if (profiles.length === 0) {
        const opt = el("option", { value: "", text: "(nav profilu)" });
        select.appendChild(opt);
        return;
      }
      profiles.forEach((p) => {
        const opt = el("option", {
          value: p.code,
          text: p.code + " — " + (p.name || ""),
        });
        if (p.code === activeProfileCode) opt.selected = true;
        select.appendChild(opt);
      });
    }

    function loadIntoEditor(profile) {
      creating = false;
      editorState = profile ? deepCopy(profile) : null;
      const nameI = $("profile-name");
      const codeI = $("profile-code");
      const siteI = $("profile-site-code");
      const intI = $("profile-interval");
      if (nameI) nameI.value = profile ? (profile.name || "") : "";
      if (codeI) codeI.value = profile ? (profile.code || "") : "";
      if (siteI) siteI.value = profile ? (profile.site_code || "") : "";
      if (intI) intI.value = profile ? String(profile.interval_seconds || 60) : "60";

      // Disable code editing on existing profiles to keep references
      // stable; allow editing only when the user explicitly creates one.
      if (codeI) codeI.readOnly = profile != null;

      renderMetricsTable(profile);
      const fb = $("profile-feedback");
      if (fb) { fb.hidden = true; clear(fb); }
    }

    function deepCopy(v) {
      try { return JSON.parse(JSON.stringify(v)); }
      catch (e) { return v; }
    }

    function renderMetricsTable(profile) {
      const tbody = $("profile-metrics-body");
      if (!tbody) return;
      clear(tbody);
      const metrics = collectMetricRows(profile);
      if (metrics.length === 0) {
        const tr = el("tr");
        const td = el("td", {
          colspan: "8", class: "state state--empty",
          text: profile
            ? "Profilam nav konfigurētu metriku."
            : "Izvēlieties profilu, lai redzētu metrikas.",
        });
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }
      metrics.forEach((m) => {
        tbody.appendChild(buildMetricRow(m));
      });
      // Keep editor permission state honest.
      applyPermission();
    }

    function collectMetricRows(profile) {
      if (!profile) return [];
      const out = [];
      (profile.devices || []).forEach((dev) => {
        (dev.metrics || []).forEach((m) => out.push(Object.assign({}, m, {
          _device_uid: dev.device_uid,
        })));
      });
      out.sort((a, b) => {
        const sa = a.sort_order || 0, sb = b.sort_order || 0;
        if (sa !== sb) return sa - sb;
        return (a.metric_key || "").localeCompare(b.metric_key || "");
      });
      return out;
    }

    function buildMetricRow(m) {
      const tr = el("tr", { "data-metric-key": m.metric_key || "" });
      function cellInput(role, type, value, opts) {
        const i = el("input", Object.assign({
          type: type, value: value === undefined || value === null ? "" : String(value),
          "data-role": role, "data-metric-key": m.metric_key || "",
          "aria-label": role,
        }, opts || {}));
        const td = el("td"); td.appendChild(i); return td;
      }
      // Enabled checkbox
      const cb = el("input", {
        type: "checkbox",
        "data-role": "metric-enabled",
        "data-metric-key": m.metric_key || "",
        "aria-label": "iespējots",
      });
      if (m.is_enabled) cb.checked = true;
      const cbTd = el("td"); cbTd.appendChild(cb);
      tr.appendChild(cbTd);
      tr.appendChild(el("td", { class: "monospace", text: m.metric_key || "—" }));
      tr.appendChild(el("td", { text: m.metric_label || "—" }));
      tr.appendChild(el("td", { text: m.unit || "" }));
      tr.appendChild(cellInput("metric-min", "number", m.min_value, { step: "any" }));
      tr.appendChild(cellInput("metric-base", "number", m.base_value, { step: "any" }));
      tr.appendChild(cellInput("metric-max", "number", m.max_value, { step: "any" }));
      tr.appendChild(cellInput("metric-noise", "number", m.noise_amplitude, {
        step: "any", min: "0",
      }));
      return tr;
    }

    function readEditorValues() {
      const name = ($("profile-name") || {}).value || "";
      const code = ($("profile-code") || {}).value || "";
      const siteCode = ($("profile-site-code") || {}).value || "";
      const interval = Number(($("profile-interval") || {}).value || 0);
      const tbody = $("profile-metrics-body");
      const metrics = [];
      if (tbody) {
        tbody.querySelectorAll("tr[data-metric-key]").forEach((tr) => {
          const key = tr.getAttribute("data-metric-key") || "";
          if (!key) return;
          const cb = tr.querySelector('input[data-role="metric-enabled"]');
          const minI = tr.querySelector('input[data-role="metric-min"]');
          const baseI = tr.querySelector('input[data-role="metric-base"]');
          const maxI = tr.querySelector('input[data-role="metric-max"]');
          const noiseI = tr.querySelector('input[data-role="metric-noise"]');
          metrics.push({
            metric_key: key,
            is_enabled: cb ? cb.checked : false,
            min_value: minI && minI.value !== "" ? Number(minI.value) : null,
            base_value: baseI && baseI.value !== "" ? Number(baseI.value) : null,
            max_value: maxI && maxI.value !== "" ? Number(maxI.value) : null,
            noise_amplitude: noiseI && noiseI.value !== "" ? Number(noiseI.value) : 0,
          });
        });
      }
      return {
        name: name.trim(), code: code.trim(),
        site_code: siteCode.trim(),
        interval_seconds: interval,
        metrics: metrics,
      };
    }

    function renderProfileFeedback(kind, message, fieldErrors) {
      const fb = $("profile-feedback");
      if (!fb) return;
      fb.hidden = false;
      clear(fb);
      fb.appendChild(el("div", { class: "state state--" + kind, text: message }));
      if (fieldErrors && Object.keys(fieldErrors).length > 0) {
        const ul = el("ul", { class: "profile-editor__errors" });
        Object.keys(fieldErrors).forEach((key) => {
          const value = fieldErrors[key];
          if (Array.isArray(value)) {
            value.forEach((entry) => {
              ul.appendChild(el("li", {
                text: key + ": " + describeFieldError(entry),
              }));
            });
          } else if (typeof value === "string") {
            ul.appendChild(el("li", { text: key + ": " + value }));
          } else {
            ul.appendChild(el("li", { text: key + ": " + JSON.stringify(value) }));
          }
        });
        fb.appendChild(ul);
      }
    }
    function describeFieldError(entry) {
      if (entry == null) return "";
      if (typeof entry === "string") return entry;
      if (typeof entry === "object") {
        return Object.keys(entry).map((k) => k + "=" + entry[k]).join(", ");
      }
      return String(entry);
    }

    async function saveProfile() {
      if (!AUTH.canControl) return;
      const values = readEditorValues();
      const isCreate = creating || !activeProfileCode;
      const url = isCreate
        ? ENDPOINTS.profileList
        : (ENDPOINTS.profileDetailTemplate || "").replace(
            "__CODE__", encodeURIComponent(activeProfileCode),
          );
      if (!url) return;
      const method = isCreate ? "POST" : "PATCH";
      try {
        const resp = await fetch(url, {
          method: method,
          headers: buildHeaders(),
          credentials: "same-origin",
          body: JSON.stringify(values),
        });
        const data = await resp.json().catch(() => null);
        if (!resp.ok || !data || data.ok === false) {
          renderProfileFeedback(
            "error",
            (data && data.message) || ("Saglabāšana neizdevās (HTTP " + resp.status + ")."),
            data ? data.field_errors : null,
          );
          return;
        }
        renderProfileFeedback("info", data.message || "Saglabāts.", null);
        await loadProfiles();
        if (isCreate && data.profile && data.profile.code) {
          activeProfileCode = data.profile.code;
        }
        const refreshed = profiles.find((p) => p.code === activeProfileCode);
        renderProfileSelect();
        loadIntoEditor(refreshed || null);
      } catch (err) {
        renderProfileFeedback(
          "error",
          "Kļūda: " + (err && err.message ? err.message : "nezināma"),
          null,
        );
      }
    }

    async function loadProfiles() {
      try {
        const data = await fetchJson(ENDPOINTS.profileList);
        profiles = (data && data.profiles) || [];
        if (data && typeof data.can_control === "boolean") {
          AUTH.canControl = data.can_control;
        }
        if (!activeProfileCode && profiles.length > 0) {
          activeProfileCode = profiles[0].code;
        }
        renderProfileSelect();
        const active = profiles.find((p) => p.code === activeProfileCode);
        loadIntoEditor(active || null);
        rebuildCharts(active);
      } catch (err) {
        renderProfileFeedback(
          "error",
          "Nevar ielādēt profilus: " + (err.message || ""),
          null,
        );
      }
    }

    function startNewProfile() {
      if (!AUTH.canControl) return;
      creating = true;
      activeProfileCode = "";
      const select = $("profile-select");
      if (select) select.value = "";
      [
        ["profile-name", ""],
        ["profile-code", ""],
        ["profile-site-code", ""],
        ["profile-interval", "60"],
      ].forEach(([role, val]) => {
        const i = $(role);
        if (i) { i.value = val; i.readOnly = false; }
      });
      const tbody = $("profile-metrics-body");
      if (tbody) {
        clear(tbody);
        const tr = el("tr"); tr.appendChild(el("td", {
          colspan: "8", class: "state state--empty",
          text: "Pēc saglabāšanas pievienojiet ierīces un sensorus, lai šeit parādītos metrikas.",
        }));
        tbody.appendChild(tr);
      }
      const fb = $("profile-feedback");
      if (fb) { fb.hidden = true; clear(fb); }
    }

    function wireProfileEditor() {
      const select = $("profile-select");
      if (select) {
        select.addEventListener("change", () => {
          activeProfileCode = select.value || "";
          const p = profiles.find((x) => x.code === activeProfileCode);
          loadIntoEditor(p || null);
          rebuildCharts(p);
        });
      }
      const newBtn = $("profile-new-btn");
      if (newBtn) newBtn.addEventListener("click", startNewProfile);
      const saveBtn = $("profile-save-btn");
      if (saveBtn) saveBtn.addEventListener("click", saveProfile);
      const resetBtn = $("profile-reset-btn");
      if (resetBtn) resetBtn.addEventListener("click", () => {
        const p = profiles.find((x) => x.code === activeProfileCode);
        creating = false;
        loadIntoEditor(p || null);
      });
    }

    // ── Charts ────────────────────────────────────────────────────────
    function rebuildCharts(profile) {
      const host = $("simulator-charts");
      if (!host) return;
      // Tear down all existing charts.
      Object.keys(charts).forEach((k) => { try { charts[k].destroy(); } catch (e) { /* noop */ } });
      Object.keys(charts).forEach((k) => { delete charts[k]; });

      clear(host);

      // Determine which metrics to draw: union of profile-enabled keys
      // and the configured chart metric defaults so the UI always shows
      // something useful even before the first event arrives.
      const enabledKeys = new Set();
      if (profile) {
        (profile.devices || []).forEach((d) => {
          (d.metrics || []).forEach((m) => {
            if (m.is_enabled && m.metric_key) enabledKeys.add(m.metric_key);
          });
        });
      }
      const metaByKey = {};
      CHART_METRICS.forEach((m) => { metaByKey[m.key] = m; });
      const labelMap = {};
      const unitMap = {};
      (profile && profile.devices || []).forEach((d) => {
        (d.metrics || []).forEach((m) => {
          if (m.metric_key) {
            labelMap[m.metric_key] = labelMap[m.metric_key] || m.metric_label || m.metric_key;
            unitMap[m.metric_key] = unitMap[m.metric_key] || m.unit || "";
          }
        });
      });

      const keys = enabledKeys.size > 0
        ? Array.from(enabledKeys)
        : CHART_METRICS.map((m) => m.key);
      if (keys.length === 0) {
        host.appendChild(el("div", {
          class: "state state--empty",
          "data-role": "simulator-charts-state",
          text: "Vēl nav datu. Palaidiet simulatoru, lai sāktu rādīt grafikus.",
        }));
        return;
      }

      keys.forEach((key) => {
        const meta = metaByKey[key] || {};
        const label = labelMap[key] || meta.label || key;
        const unit = unitMap[key] || meta.unit || "";
        charts[key] = createSimulatorChart(host, {
          title: label,
          unit: unit,
          maxPoints: CHART_MAX_POINTS,
        });
      });
    }

    function appendMetricsToCharts(timestamp, metrics) {
      if (!metrics || typeof metrics !== "object") return;
      Object.keys(metrics).forEach((key) => {
        const value = metrics[key];
        const chart = charts[key];
        if (chart && (typeof value === "number")) {
          chart.addPoint(timestamp || new Date(), value);
        }
      });
    }

    // ── MQTT stream table ────────────────────────────────────────────
    function appendMqttRow(payload) {
      const tbody = $("mqtt-stream-body");
      if (!tbody) return;
      const empty = tbody.querySelector('[data-role="mqtt-stream-empty"]');
      if (empty) empty.remove();
      const tr = el("tr");
      const status = payload.publish_status || "—";
      const statusClass = status === "ok"
        ? "status-pill--ok"
        : status === "failed"
        ? "status-pill--degraded"
        : "status-pill--warning";
      const statusPill = el("span", {
        class: "status-pill " + statusClass, text: status,
      });
      tr.appendChild(el("td", { class: "numeric", text: formatTimestamp(new Date(payload.ts || Date.now())) }));
      tr.appendChild(el("td", { text: payload.scenario_code || "—" }));
      tr.appendChild(el("td", {
        text: (payload.device_uid || "—") + (payload.asset_code ? " / " + payload.asset_code : ""),
      }));
      tr.appendChild(el("td", { class: "monospace", text: payload.topic || "—" }));
      tr.appendChild(el("td", { text: payload.metric_summary || "—" }));
      const previewTd = el("td", { class: "monospace mqtt-stream-table__preview" });
      previewTd.textContent = payload.payload_preview || "";
      tr.appendChild(previewTd);
      const statusTd = el("td"); statusTd.appendChild(statusPill);
      tr.appendChild(statusTd);
      tr.appendChild(el("td", { text: payload.error || "" }));
      tbody.insertBefore(tr, tbody.firstChild);
      // FIFO trim
      while (tbody.children.length > STREAM_MAX_ROWS) {
        tbody.removeChild(tbody.lastChild);
      }
    }

    // ── Live update wiring ───────────────────────────────────────────
    setLiveStatus(WEBSOCKET_PATH ? "connecting" : "disabled");
    const refreshController = wireRefreshControls(
      () => Promise.all([refreshSimulatorStatus(), loadProfiles()]),
      AUTO_INTERVAL_MS,
    );

    function handleLiveEvent(payload) {
      if (!payload || typeof payload !== "object") return;
      const evt = payload.event_type;
      if (!evt || evt === "connection_ack" || evt === "pong") return;
      if (evt === "simulator_status_changed"
          || evt === "simulator_run_completed") {
        refreshSimulatorStatus();
      }
      if (evt === "simulator_mqtt_message_sent") {
        appendMqttRow(payload);
        appendMetricsToCharts(
          payload.ts ? new Date(payload.ts) : new Date(),
          payload.metrics || {},
        );
      }
      if (evt === "telemetry_received" || evt === "raw_message_received") {
        // Best-effort heartbeat — keep status fresh on unrelated traffic.
      }
    }

    if (WEBSOCKET_PATH) {
      const liveConnection = connectLiveUpdates(WEBSOCKET_PATH, {
        onOpen() {
          if (LIVE_AUTO_INTERVAL_MS > 0) {
            refreshController.setInterval(LIVE_AUTO_INTERVAL_MS);
          }
        },
        onClose() { refreshController.setInterval(AUTO_INTERVAL_MS); },
        onEvent: handleLiveEvent,
      });
      window.addEventListener("beforeunload", () => liveConnection.close());
    } else {
      setLiveStatus("disabled");
    }

    wireControlButtons();
    wireProfileEditor();
    applyPermission();
    refreshSimulatorStatus();
    loadProfiles();
  }

})();
