/* SMT Digital Solution dashboard — vanilla JavaScript loader.
 *
 * Two pages share this script:
 *   • /dashboard/             ← reads #dashboard-config
 *   • /dashboard/assets/.../  ← reads #asset-detail-config
 *
 * The script picks the right initialiser based on which JSON block is
 * present in the DOM. Shared helpers (DOM, formatting, badges, fetch)
 * live at module scope so both initialisers can reuse them.
 *
 * The dashboard is read-only and uses only the public Phase 6 REST API.
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

  // ── Refresh wiring (shared) ─────────────────────────────────────────

  function wireRefreshControls(loadAll, autoIntervalMs) {
    const refreshBtn = $("refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadAll());

    let handle = null;
    const autoToggle = $("auto-refresh-toggle");
    if (autoToggle && autoIntervalMs > 0) {
      autoToggle.addEventListener("change", (e) => {
        if (handle) {
          clearInterval(handle);
          handle = null;
        }
        if (e.target.checked) {
          handle = setInterval(loadAll, autoIntervalMs);
        }
      });
    }
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
        ["Pēdējais simulators", data.simulator.last_run_status || "—"],
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
            (data.runs.latest_status || "—") + " · "
              + formatTimestamp(data.runs.latest_started_at),
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
      { key: "simulator", url: ENDPOINTS.overviewSimulator,
        stateRoles: ["simulator-runs-state"], onSuccess: renderSimulator },
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

    wireRefreshControls(loadAll, AUTO_INTERVAL_MS);
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
          "Metrika", "Vērtība", "Vienība", "Laiks", "Kvalitāte",
        ].map((h) => el("th", { text: h }))),
      ]);
      const tbody = el("tbody");
      items.forEach((m) => {
        tbody.appendChild(
          el("tr", null, [
            el("td", { text: m.metric_key || "—" }),
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

    function buildChartCard(metricKey) {
      const card = el("div", { class: "chart-card", "data-metric": metricKey });
      const header = el("div", { class: "chart-card__header" }, [
        el("span", { class: "chart-card__metric", text: metricKey }),
        el("span", { class: "chart-card__latest",
                     "data-role": `chart-${metricKey}-latest`, text: "—" }),
      ]);
      const body = el("div", { class: "chart-card__body",
                               "data-role": `chart-${metricKey}-body` });
      // Initial loading state inside the body — replaced once data arrives.
      body.appendChild(el("div", {
        class: "state state--loading", text: "Ielādē…",
      }));
      const range = el("div", { class: "chart-card__range",
                                "data-role": `chart-${metricKey}-range`, text: "" });
      card.appendChild(header);
      card.appendChild(body);
      card.appendChild(range);
      return card;
    }

    function buildChartGrid() {
      const grid = $("charts-grid");
      if (!grid) return;
      clear(grid);
      if (!CHART_METRICS.length) {
        grid.appendChild(
          el("div", { class: "state state--empty",
                      text: "Diagrammu metrikas nav konfigurētas." }),
        );
        return;
      }
      CHART_METRICS.forEach((metric) => {
        grid.appendChild(buildChartCard(metric));
      });
    }

    function setChartState(metric, kind, message) {
      const body = $(`chart-${metric}-body`);
      if (!body) return;
      clear(body);
      body.appendChild(el("div", { class: `state state--${kind}`, text: message }));
    }

    function renderChart(metric, payload) {
      const body = $(`chart-${metric}-body`);
      const latestEl = $(`chart-${metric}-latest`);
      const rangeEl = $(`chart-${metric}-range`);
      if (!body) return;

      const items = Array.isArray(payload) ? payload : [];
      // API returns measurements newest-first; SVG wants oldest-first.
      const ordered = items.slice().reverse();
      const points = ordered
        .filter((m) => m && m.timestamp && m.value !== null && m.value !== undefined)
        .map((m) => [new Date(m.timestamp), Number(m.value)]);

      clear(body);
      if (points.length === 0) {
        body.appendChild(
          el("div", { class: "state state--empty", text: "Nav datu." }),
        );
        if (latestEl) latestEl.textContent = "—";
        if (rangeEl) rangeEl.textContent = "";
        return;
      }
      const svgEl = svg("svg", {
        class: "chart-card__svg",
        role: "img",
        "aria-label": `${metric} laika rinda`,
      });
      body.appendChild(svgEl);
      renderSparkline(svgEl, points);

      const lastMeasurement = items[0];
      if (latestEl) {
        latestEl.textContent =
          formatNumber(lastMeasurement.value) + " · "
          + formatTimestamp(lastMeasurement.timestamp);
      }
      const ys = points.map((p) => p[1]);
      const minY = Math.min.apply(null, ys);
      const maxY = Math.max.apply(null, ys);
      if (rangeEl) {
        rangeEl.textContent =
          `min ${formatNumber(minY)} · max ${formatNumber(maxY)} · n=${points.length}`;
      }
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
      setChartState(metric, "loading", "Ielādē…");
      try {
        const url = CHART_URL_TEMPLATE.replace(
          "__METRIC__", encodeURIComponent(metric),
        );
        const data = await fetchJson(url);
        renderChart(metric, data);
      } catch (err) {
        setChartState(
          metric, "error",
          "Kļūda: " + (err && err.message ? err.message : "nezināma"),
        );
        const latestEl = $(`chart-${metric}-latest`);
        if (latestEl) latestEl.textContent = "—";
        const rangeEl = $(`chart-${metric}-range`);
        if (rangeEl) rangeEl.textContent = "";
      }
    }

    async function loadCharts() {
      const grid = $("charts-grid");
      if (grid) clear(grid);
      buildChartGrid();
      await Promise.all(CHART_METRICS.map(loadChart));
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

    wireRefreshControls(loadAll, AUTO_INTERVAL_MS);
    loadAll();
  }

  // ── Page dispatch ───────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
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
})();
