/* SMT Digital Solution dashboard — vanilla JavaScript loader.
 *
 * Reads endpoint URLs from the JSON script block #dashboard-config that
 * the Django view emits, then fetches every overview endpoint in
 * parallel and renders the results into the page shell. The shell shows
 * loading, error, and empty states without exposing stack traces.
 *
 * The dashboard is intentionally read-only and uses only the public
 * Phase 6 REST API.
 */

(function () {
  "use strict";

  function readConfig() {
    const node = document.getElementById("dashboard-config");
    if (!node) {
      return null;
    }
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return null;
    }
  }

  const config = readConfig();
  if (!config) {
    document.body.appendChild(
      Object.assign(document.createElement("div"), {
        className: "state state--error",
        textContent:
          "Dashboard konfigurācija nav pieejama. Atjaunojiet lapu.",
      }),
    );
    return;
  }

  const ENDPOINTS = config.endpoints;
  const ASSET_SUMMARY_URL_TEMPLATE = config.assetSummaryUrlTemplate || "";
  const AUTO_REFRESH_INTERVAL_MS =
    Math.max(0, (config.autoRefreshIntervalSeconds || 0) * 1000);

  // ── DOM helpers ─────────────────────────────────────────────────────

  function $(role) {
    return document.querySelector(`[data-role="${role}"]`);
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.entries(attrs).forEach(([key, value]) => {
        if (value === null || value === undefined) {
          return;
        }
        if (key === "class") {
          node.className = value;
        } else if (key === "text") {
          node.textContent = value;
        } else if (key === "html") {
          node.innerHTML = value;
        } else {
          node.setAttribute(key, value);
        }
      });
    }
    (children || []).forEach((child) => {
      if (child === null || child === undefined) {
        return;
      }
      node.appendChild(
        typeof child === "string" ? document.createTextNode(child) : child,
      );
    });
    return node;
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function setState(node, kind, message) {
    if (!node) return;
    clear(node);
    node.appendChild(
      el("div", {
        class: `state state--${kind}`,
        text: message,
      }),
    );
  }

  // ── Formatting helpers ──────────────────────────────────────────────

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

  function formatBool(value) {
    if (value === true) return "jā";
    if (value === false) return "nē";
    return "—";
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

  function assetSummaryHref(code) {
    if (!code || !ASSET_SUMMARY_URL_TEMPLATE) return null;
    return ASSET_SUMMARY_URL_TEMPLATE.replace(
      "__CODE__", encodeURIComponent(code),
    );
  }

  function countPill(label, value) {
    return el("span", { class: "count-pill" }, [
      el("strong", { text: String(value) }),
      " " + label,
    ]);
  }

  // ── Generic fetch with timeout ──────────────────────────────────────

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
        throw new Error(`HTTP ${resp.status}`);
      }
      return await resp.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  // ── Renderers ───────────────────────────────────────────────────────

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
      [
        "Pēdējais mērījums",
        formatTimestamp(data.telemetry.latest_measurement_at),
      ],
      [
        "Pēdējais simulators",
        data.simulator.last_run_status || "—",
      ],
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
    if (generatedAt) {
      generatedAt.textContent = "Atjaunots: " + formatTimestamp(data.generated_at);
    }
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
      counts.appendChild(countPill("ar anomāliju", data.counts.with_active_anomaly));
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
      el(
        "tr", null,
        headers.map((h) => el("th", { text: h })),
      ),
    ]);
    const tbody = el("tbody");
    data.items.forEach((row) => {
      const href = assetSummaryHref(row.asset_code);
      const link = href
        ? el("a", { href: href, rel: "noopener", text: "JSON" })
        : el("span", { class: "card__hint", text: "—" });
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
          el("td", null, [link]),
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

    // Per-metric latest table
    const metricsWrapper = $("telemetry-metrics-wrapper");
    if (metricsWrapper) {
      // Re-create the wrapper contents but keep the subsection title node.
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

    // Recent measurements
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

  function renderSimulator(data) {
    const counts = $("simulator-counts");
    if (counts) {
      clear(counts);
      counts.appendChild(countPill("scenāriji", data.scenarios.total));
      counts.appendChild(countPill("aktīvi", data.scenarios.active));
      counts.appendChild(countPill("palaidieni", data.runs.total));
      counts.appendChild(countPill("completed", data.runs.completed));
      counts.appendChild(countPill("failed", data.runs.failed));
      counts.appendChild(countPill("running", data.runs.running));
      counts.appendChild(
        countPill(
          "pēdējais",
          (data.runs.latest_status || "—") +
            " · " + formatTimestamp(data.runs.latest_started_at),
        ),
      );
    }

    const wrapper = $("simulator-runs-wrapper");
    if (!wrapper) return;
    const title = wrapper.querySelector(".subsection-title");
    clear(wrapper);
    if (title) wrapper.appendChild(title);

    const items = data.recent_runs || [];
    if (items.length === 0) {
      wrapper.appendChild(
        el("div", { class: "state state--empty", text: "Nav simulatora palaidienu." }),
      );
      return;
    }
    const thead = el("thead", null, [
      el("tr", null, [
        "Scenārijs", "Statuss", "Sākts", "Beidzies",
        "Ziņojumi", "Kļūda",
      ].map((h) => el("th", { text: h }))),
    ]);
    const tbody = el("tbody");
    items.forEach((r) => {
      tbody.appendChild(
        el("tr", null, [
          el("td", { text: r.scenario_code || "—" }),
          el("td", null, [statusBadge(r.status)]),
          el("td", { class: "numeric", text: formatTimestamp(r.started_at) }),
          el("td", { class: "numeric", text: formatTimestamp(r.finished_at) }),
          el("td", { class: "numeric", text: formatNumber(r.messages_published) }),
          el("td", { text: r.error_message || "" }),
        ]),
      );
    });
    wrapper.appendChild(el("table", { class: "data-table" }, [thead, tbody]));
  }

  // ── Section orchestration ───────────────────────────────────────────

  const SECTIONS = [
    {
      key: "overview",
      url: ENDPOINTS.overview,
      stateRoles: ["overview-state"],
      onSuccess: renderOverviewCards,
    },
    {
      key: "assets",
      url: ENDPOINTS.overviewAssets,
      stateRoles: ["assets-state"],
      onSuccess: renderAssets,
    },
    {
      key: "events",
      url: ENDPOINTS.overviewEvents,
      stateRoles: ["events-state"],
      onSuccess: renderEvents,
    },
    {
      key: "telemetry",
      url: ENDPOINTS.overviewTelemetry,
      stateRoles: ["telemetry-metrics-state", "telemetry-recent-state"],
      onSuccess: renderTelemetry,
    },
    {
      key: "simulator",
      url: ENDPOINTS.overviewSimulator,
      stateRoles: ["simulator-runs-state"],
      onSuccess: renderSimulator,
    },
  ];

  function setSectionLoading(section) {
    section.stateRoles.forEach((role) => {
      setState($(role), "loading", "Ielādē…");
    });
  }

  function setSectionError(section, message) {
    section.stateRoles.forEach((role) => {
      setState($(role), "error", message);
    });
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

  // ── Refresh wiring ──────────────────────────────────────────────────

  let autoRefreshHandle = null;

  function setAutoRefresh(enabled) {
    if (autoRefreshHandle) {
      clearInterval(autoRefreshHandle);
      autoRefreshHandle = null;
    }
    if (enabled && AUTO_REFRESH_INTERVAL_MS > 0) {
      autoRefreshHandle = setInterval(loadAll, AUTO_REFRESH_INTERVAL_MS);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const refreshBtn = $("refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => loadAll());
    }
    const autoToggle = $("auto-refresh-toggle");
    if (autoToggle) {
      autoToggle.addEventListener("change", (e) => {
        setAutoRefresh(e.target.checked);
      });
    }
    loadAll();
  });
})();
