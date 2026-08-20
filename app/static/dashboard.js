// 연합컴퓨팅 플랫폼 대시보드 — /api/dashboard 단일 요청으로 5종 차트 렌더

const charts = { timeseries: null, histogram: null, bar: null };
const API_KEY_STORAGE_KEY = "fed-dashboard-api-key";
let opsCache = { models: [], groups: [], deployments: [], alerts: [], usage: [] };
let mockInterval = null; // 실시간 데모용 타이머
let mockState = {
    timeseries: null,
    silo_bar_resource: null,
    heatmap: null,
    topology: null,
    histogram: null
};

const $ = (id) => document.getElementById(id);

class AuthError extends Error {
    constructor(message, status) {
        super(message);
        this.name = "AuthError";
        this.status = status;
    }
}

function apiKey() {
    return $("api-key-input")?.value.trim() || "";
}

function saveApiKey() {
    const key = apiKey();
    if (key) {
        sessionStorage.setItem(API_KEY_STORAGE_KEY, key);
    } else {
        sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    }
}

function setAuthBanner(show) {
    const banner = $("auth-banner");
    if (banner) banner.hidden = !show;
}

function unwrapPaginated(data) {
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.items)) return data.items;
    return [];
}

async function fetchJSON(url) {
    const headers = {};
    const key = apiKey();
    if (key) headers["X-FED-API-Key"] = key;
    const res = await fetch(url, { headers });
    if (res.status === 401 || res.status === 403) {
        setAuthBanner(true);
        throw new AuthError(`인증 필요 (HTTP ${res.status})`, res.status);
    }
    setAuthBanner(false);
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return res.json();
}

async function loadModels() {
    // 만약 데모 모킹 모드가 켜져 있으면 가짜 모델 리스트 즉시 제공
    if ($("mock-toggle")?.checked) {
        const byName = { "demo-alpha": ["1.0.0", "1.1.0", "2.0.0"], "fed-bert": ["1.0.0"] };
        const modelSel = $("model-select");
        modelSel.innerHTML = "";
        for (const name of Object.keys(byName)) {
            const opt = document.createElement("option");
            opt.value = name;
            opt.textContent = name;
            modelSel.appendChild(opt);
        }
        modelSel.onchange = () => populateVersions(byName);
        populateVersions(byName);
        return byName;
    }

    const models = await fetchJSON("/api/models");
    const byName = {};
    for (const m of models) {
        (byName[m.name] ||= []).push(m.version);
    }
    const modelSel = $("model-select");
    modelSel.innerHTML = "";
    for (const name of Object.keys(byName)) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        modelSel.appendChild(opt);
    }
    modelSel.onchange = () => populateVersions(byName);
    if (Object.keys(byName).length) populateVersions(byName);
    return byName;
}

function populateVersions(byName) {
    const name = $("model-select").value;
    const versionSel = $("version-select");
    versionSel.innerHTML = "";
    for (const v of (byName[name] || [])) {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        versionSel.appendChild(opt);
    }
}

function selectIfPresent(selectId, value) {
    if (!value) return;
    const select = $(selectId);
    const exists = Array.from(select.options).some(opt => opt.value === value);
    if (exists) select.value = value;
}

function applyQueryDefaults(byName) {
    const params = new URLSearchParams(window.location.search);
    const model = params.get("model_name") || params.get("model");
    if (model && byName[model]) {
        $("model-select").value = model;
        populateVersions(byName);
    }
    selectIfPresent("version-select", params.get("version"));
    selectIfPresent("metric-select", params.get("metric"));
    selectIfPresent("resource-select", params.get("resource_metric"));
    const feature = params.get("feature");
    if (feature) $("feature-input").value = feature;
}

function setEmpty(id, shown) {
    $(id).hidden = !shown;
}

function chartPayload(envelope) {
    return envelope?.payload || envelope || null;
}

function opsItem(title, meta, badgeText = null, badgeKind = "", { onClick = null } = {}) {
    const item = document.createElement("div");
    item.className = onClick ? "ops-item clickable" : "ops-item";
    if (onClick) item.addEventListener("click", onClick);
    const titleEl = document.createElement("div");
    titleEl.className = "ops-title";
    titleEl.textContent = title;
    item.appendChild(titleEl);
    const metaEl = document.createElement("div");
    metaEl.className = "ops-meta";
    if (badgeText) {
        const badge = document.createElement("span");
        badge.className = `badge ${badgeKind}`.trim();
        badge.textContent = badgeText;
        metaEl.appendChild(badge);
        if (meta) metaEl.appendChild(document.createTextNode(` ${meta}`));
    } else {
        metaEl.textContent = meta || "";
    }
    item.appendChild(metaEl);
    return item;
}

function setOpsState(id, state) {
    const root = $(id);
    if (root) root.dataset.state = state;
}

function showOpsDetail(title, rows) {
    const panel = $("ops-detail");
    const body = $("ops-detail-body");
    $("ops-detail-title").textContent = title;
    body.innerHTML = "";
    for (const [label, value] of rows) {
        const row = document.createElement("dl");
        row.className = "ops-detail-row";
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value ?? "—";
        row.appendChild(dt);
        row.appendChild(dd);
        body.appendChild(row);
    }
    panel.hidden = false;
}

function hideOpsDetail() {
    $("ops-detail").hidden = true;
}

function renderList(id, items, emptyText = "데이터 없음") {
    const root = $(id);
    root.innerHTML = "";
    root.dataset.state = "ready";
    if (!items.length) {
        root.appendChild(opsItem(emptyText, ""));
        return;
    }
    items.forEach(item => root.appendChild(item));
}

// --- 실시간 모킹 데이터 제너레이터 (Wave/진동 연산 포함) ---
function generateMockDashboardData(model, ver, metric, resource, feature) {
    // 처음 모킹 상태를 주입
    if (!mockState.timeseries || mockState.model !== model || mockState.ver !== ver) {
        mockState.model = model;
        mockState.ver = ver;
        
        // 1. 시계열 메트릭
        const series = {};
        const timestamps = ["2026-05-26T10:00:00Z", "2026-05-26T10:10:00Z", "2026-05-26T10:20:00Z", "2026-05-26T10:30:00Z"];
        const silos = ["silo-1", "silo-2", "silo-3", "silo-4", "silo-5", "silo-6"];
        
        silos.forEach((silo, idx) => {
            let base = 0.75 + idx * 0.02;
            series[silo] = timestamps.map((ts, tIdx) => ({
                timestamp: ts,
                value: base + tIdx * 0.015 + (Math.random() - 0.5) * 0.005
            }));
        });
        mockState.timeseries = { series };

        // 2. 사일로별 리소스
        mockState.silo_bar_resource = {
            items: silos.map((silo, idx) => ({
                silo_id: silo,
                value: 30 + idx * 7 + Math.random() * 5
            }))
        };

        // 3. 히트맵 matrix
        mockState.heatmap = {
            row_labels: silos,
            col_labels: ["accuracy", "latency_ms", "throughput_rps"],
            matrix: silos.map((silo, idx) => [
                0.81 + idx * 0.015,
                127.2 - idx * 4,
                54.0 + idx * 3
            ])
        };

        // 4. 토폴로지
        mockState.topology = {
            nodes: [
                { id: "demo-six-silos", label: "demo-six-silos", role: "group" },
                ...silos.map(s => ({ id: s, label: `데모 사일로 ${s.slice(-1)}`, role: "silo", over_budget: s === "silo-6" })),
                { id: "deploy::demo-alp", label: "demo-alpha@1.0.0", role: "deployment" }
            ],
            edges: silos.map(s => ({ source: "demo-six-silos", target: s, kind: "group" }))
        };

        // 5. 히스토그램
        mockState.histogram = {
            bin_edges: [0, 20, 40, 60, 80, 100],
            bin_counts: [12, 28, 35, 20, 5]
        };
    } else {
        // 기존 모킹 데이터가 있으면 소폭 실시간 변동(Wave) 연산 추가
        // Timeseries 마지막 포인트 파동
        const silos = Object.keys(mockState.timeseries.series);
        silos.forEach(silo => {
            const arr = mockState.timeseries.series[silo];
            const last = arr[arr.length - 1];
            last.value = Math.max(0.1, Math.min(1.0, last.value + (Math.random() - 0.5) * 0.008));
        });

        // 리소스 바 차트 출렁거림
        mockState.silo_bar_resource.items.forEach(it => {
            it.value = Math.max(10, Math.min(100, it.value + (Math.random() - 0.5) * 4));
        });

        // 히트맵 수치 출렁거림
        mockState.heatmap.matrix.forEach((row) => {
            row[0] = Math.max(0.5, Math.min(1.0, row[0] + (Math.random() - 0.5) * 0.004));
            row[1] = Math.max(10, row[1] + (Math.random() - 0.5) * 1.5);
            row[2] = Math.max(5, row[2] + (Math.random() - 0.5) * 1.0);
        });

        // 6번 사일로의 자원 압박 상태 주기적 변동
        const s6 = mockState.topology.nodes.find(n => n.id === "silo-6");
        if (s6 && Math.random() < 0.2) {
            s6.over_budget = !s6.over_budget;
        }
    }
    return mockState;
}

function generateMockOpsData() {
    return {
        models: [
            { name: "demo-alpha", version: "1.0.0", framework: "pytorch", weights_path: "/srv/weights/demo_alpha_v1.pth", created_at: "2026-05-26T08:24:02Z" },
            { name: "demo-alpha", version: "1.1.0", framework: "pytorch", weights_path: "/srv/weights/demo_alpha_v1_1.pth", created_at: "2026-05-26T09:12:00Z" },
            { name: "fed-bert", version: "1.0.0", framework: "tensorflow", weights_path: "/srv/weights/fed_bert.h5", created_at: "2026-05-26T05:44:00Z" }
        ],
        groups: [
            { group_id: "demo-six-silos", member_node_ids: ["silo-1", "silo-2", "silo-3", "silo-4", "silo-5", "silo-6"], description: "데모용 6개 사일로 그룹", updated_at: "2026-05-26T08:24:02Z" }
        ],
        deployments: [
            { deployment_id: "deploy::demo-alp", model_name: "demo-alpha", version: "1.0.0", strategy: "realtime", target_node_ids: ["silo-1", "silo-2", "silo-3", "silo-4", "silo-5", "silo-6"], status: "running", created_at: "2026-05-26T08:24:02Z" }
        ],
        usage: [
            { silo_id: "silo-1", cpu_pct: 31.0 + Math.random() * 3, mem_pct: 36.0, over_budget: false },
            { silo_id: "silo-2", cpu_pct: 37.0 + Math.random() * 3, mem_pct: 40.0, over_budget: false },
            { silo_id: "silo-3", cpu_pct: 43.0 + Math.random() * 3, mem_pct: 44.0, over_budget: false },
            { silo_id: "silo-4", cpu_pct: 49.0 + Math.random() * 3, mem_pct: 48.0, over_budget: false },
            { silo_id: "silo-5", cpu_pct: 55.0 + Math.random() * 3, mem_pct: 52.0, over_budget: false },
            { silo_id: "silo-6", cpu_pct: 61.0 + Math.random() * 3, mem_pct: 56.0, over_budget: mockState.topology?.nodes.find(n => n.id === "silo-6")?.over_budget || false }
        ],
        alerts: [
            { rule_id: "silo-6-cpu-pressure", model_name: "demo-alpha", version: "1.0.0", metric: "cpu_pct", message: "silo-6 CPU 자원 임계값 80% 초과 우려", status: "open", observed_value: 82.5, threshold: 80.0, triggered_at: "2026-05-26T10:28:44Z" }
        ]
    };
}

async function renderOperations() {
    ["ops-models", "ops-groups", "ops-deployments", "ops-alerts"].forEach(id => {
        setOpsState(id, "loading");
    });
    try {
        let models, groups, deployments, usage, alerts;

        if ($("mock-toggle")?.checked) {
            // 데모 모킹 데이터를 즉각 생성하여 주입
            const mData = generateMockOpsData();
            models = mData.models;
            groups = mData.groups;
            deployments = mData.deployments;
            usage = mData.usage;
            alerts = mData.alerts;
            setAuthBanner(false);
        } else {
            const [modelsRaw, groupsRaw, deploymentsRaw, usageRaw, alertsRaw] = await Promise.all([
                fetchJSON("/api/models"),
                fetchJSON("/api/silo-groups"),
                fetchJSON("/api/deployments"),
                fetchJSON("/api/resources/usage"),
                fetchJSON("/api/monitoring/alerts?limit=20"),
            ]);
            models = modelsRaw;
            groups = groupsRaw;
            deployments = deploymentsRaw;
            usage = usageRaw;
            alerts = unwrapPaginated(alertsRaw);
        }
        
        opsCache = { models, groups, deployments, alerts, usage };

        renderList("ops-models", models.slice(0, 8).map(m =>
            opsItem(`${m.name}@${m.version}`, `${m.framework} · ${m.created_at || ""}`, null, "", {
                onClick: () => showOpsDetail(`모델 ${m.name}@${m.version}`, [
                    ["프레임워크", m.framework],
                    ["가중치", m.weights_path],
                    ["등록", m.created_at],
                ]),
            })
        ));
        renderList("ops-groups", groups.slice(0, 8).map(g =>
            opsItem(g.group_id, `${g.member_node_ids.length} silos · ${g.description || "-"}`, null, "", {
                onClick: () => showOpsDetail(`그룹 ${g.group_id}`, [
                    ["멤버", g.member_node_ids.join(", ")],
                    ["설명", g.description || "-"],
                    ["태그", (g.tags || []).join(", ") || "-"],
                    ["갱신", g.updated_at],
                ]),
            })
        ));
        renderList("ops-deployments", deployments.slice(0, 8).map(d =>
            opsItem(
                `${d.model_name}@${d.version}`,
                `${d.strategy} · ${d.target_node_ids.length} nodes`,
                d.status,
                d.status === "running" ? "ok" : "warn",
                {
                    onClick: () => showOpsDetail(`배포 ${d.deployment_id.slice(0, 8)}`, [
                        ["모델", `${d.model_name}@${d.version}`],
                        ["전략", d.strategy],
                        ["상태", d.status],
                        ["노드", d.target_node_ids.join(", ")],
                        ["생성", d.created_at],
                    ]),
                },
            )
        ));

        const pressure = usage.filter(u => u.over_budget).length;
        const usageItems = usage.slice(0, 6).map(u =>
            opsItem(
                u.silo_id,
                `CPU ${Number(u.cpu_pct).toFixed(1)} · MEM ${Number(u.mem_pct).toFixed(1)}`,
                u.over_budget ? "over" : "ok",
                u.over_budget ? "warn" : "ok",
            )
        );
        const alertItems = alerts.slice(0, 5).map(a =>
            opsItem(`${a.metric || a.rule_id}`, `${a.model_name || ""} · ${a.message || ""}`.trim(), a.status || "open", "warn", {
                onClick: () => showOpsDetail(`알림 ${a.alert_id?.slice(0, 8) || ""}`, [
                    ["규칙", a.rule_id],
                    ["모델", a.model_name ? `${a.model_name}@${a.version || ""}` : "-"],
                    ["관측값", a.observed_value != null ? String(a.observed_value) : "-"],
                    ["임계값", a.threshold != null ? String(a.threshold) : "-"],
                    ["발화", a.triggered_at],
                ]),
            })
        );
        renderList("ops-alerts", [
            opsItem("리소스 압박", `${pressure}/${usage.length} silos`, pressure ? "warn" : "ok", pressure ? "warn" : "ok"),
            ...usageItems,
            ...alertItems,
        ]);
    } catch (e) {
        const msg = e instanceof AuthError ? "API Key 확인 필요" : e.message;
        ["ops-models", "ops-groups", "ops-deployments", "ops-alerts"].forEach(id => {
            setOpsState(id, "error");
            renderList(id, [opsItem("로드 실패", msg, "error", "warn")]);
        });
    }
}

function destroyChart(key) {
    if (charts[key]) {
        charts[key].destroy();
        charts[key] = null;
    }
}

// Chart.js 공통 옵션 사전 정의 (Inter 서체 연동)
const defaultChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            labels: {
                color: "#e2e8f0",
                font: { family: "Inter", size: 11, weight: "600" }
            }
        }
    },
    scales: {
        x: {
            grid: { color: "rgba(255, 255, 255, 0.03)" },
            ticks: { color: "#94a3b8", font: { family: "Inter", size: 10, weight: "500" } }
        },
        y: {
            grid: { color: "rgba(255, 255, 255, 0.03)" },
            ticks: { color: "#94a3b8", font: { family: "Inter", size: 10, weight: "500" } }
        }
    }
};

function renderTimeseries(payload) {
    destroyChart("timeseries");
    const series = payload?.series || {};
    const siloIds = Object.keys(series);
    if (siloIds.length === 0) { setEmpty("empty-timeseries", true); return; }
    setEmpty("empty-timeseries", false);

    const colors = ["#38bdf8", "#34d399", "#fb923c", "#f87171", "#a78bfa", "#f472b6"];
    const datasets = siloIds.map((silo, i) => ({
        label: silo,
        data: series[silo].map(p => ({ x: p.timestamp, y: p.value })),
        borderColor: colors[i % colors.length],
        backgroundColor: colors[i % colors.length] + "0d",
        tension: 0.3,
        fill: true,
        borderWidth: 2.5,
        pointBackgroundColor: colors[i % colors.length],
        pointHoverRadius: 7,
        pointRadius: 2,
    }));

    charts.timeseries = new Chart($("chart-timeseries"), {
        type: "line",
        data: { datasets },
        options: {
            ...defaultChartOptions,
            scales: {
                ...defaultChartOptions.scales,
                x: {
                    ...defaultChartOptions.scales.x,
                    type: "category",
                    ticks: { ...defaultChartOptions.scales.x.ticks, maxRotation: 0 }
                }
            }
        }
    });
}

function renderHistogram(payload) {
    destroyChart("histogram");
    if (!payload || !payload.bin_edges) { setEmpty("empty-histogram", true); return; }
    setEmpty("empty-histogram", false);

    const labels = payload.bin_edges.slice(0, -1).map((e, idx) =>
        `${e.toFixed(1)}~${payload.bin_edges[idx + 1].toFixed(1)}`
    );
    charts.histogram = new Chart($("chart-histogram"), {
        type: "bar",
        data: {
            labels,
            datasets: [{ 
                label: "count", 
                data: payload.bin_counts, 
                backgroundColor: "#38bdf8",
                borderRadius: 10,
                hoverBackgroundColor: "#0ea5e9"
            }],
        },
        options: {
            ...defaultChartOptions,
            scales: {
                ...defaultChartOptions.scales,
                y: { ...defaultChartOptions.scales.y, beginAtZero: true }
            }
        }
    });
}

function renderBar(payload) {
    destroyChart("bar");
    const items = payload?.items || [];
    if (items.length === 0) { setEmpty("empty-bar", true); return; }
    setEmpty("empty-bar", false);

    charts.bar = new Chart($("chart-bar"), {
        type: "bar",
        data: {
            labels: items.map(it => it.silo_id),
            datasets: [{
                label: "value",
                data: items.map(it => it.value),
                backgroundColor: items.map(it => it.value > 80 ? "#f87171" : "#34d399"),
                borderRadius: 10,
            }],
        },
        options: {
            ...defaultChartOptions,
            scales: {
                ...defaultChartOptions.scales,
                y: { ...defaultChartOptions.scales.y, beginAtZero: true }
            }
        }
    });
}

function renderHeatmap(payload) {
    const root = $("chart-heatmap");
    root.innerHTML = "";
    if (!payload || !payload.row_labels || !payload.row_labels.length) {
        setEmpty("empty-heatmap", true); return;
    }
    setEmpty("empty-heatmap", false);

    const tbl = document.createElement("table");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.appendChild(document.createElement("th"));
    for (const c of payload.col_labels) {
        const th = document.createElement("th");
        th.textContent = c;
        headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    tbl.appendChild(thead);

    let maxVal = -Infinity;
    let minVal = Infinity;
    let hasValidData = false;

    payload.matrix.forEach(row => {
        row.forEach(val => {
            if (val !== null && val !== undefined) {
                hasValidData = true;
                if (val > maxVal) maxVal = val;
                if (val < minVal) minVal = val;
            }
        });
    });

    const range = maxVal - minVal;

    const tbody = document.createElement("tbody");
    payload.row_labels.forEach((row, i) => {
        const tr = document.createElement("tr");
        const rh = document.createElement("th");
        rh.textContent = row;
        tr.appendChild(rh);
        payload.matrix[i].forEach((val) => {
            const td = document.createElement("td");
            if (val === null || val === undefined) {
                td.textContent = "—";
                td.style.color = "rgba(148, 163, 184, 0.25)";
                td.style.background = "transparent";
            } else {
                td.textContent = Number(val).toFixed(3);
                
                let ratio = 0.5;
                if (hasValidData && range > 0) {
                    ratio = (val - minVal) / range;
                } else if (hasValidData) {
                    ratio = val > 0 ? 0.8 : 0.2;
                }

                td.style.background = `rgba(56, 189, 248, ${0.08 + ratio * 0.45})`;
                td.style.border = "1px solid rgba(255, 255, 255, 0.04)";
                
                if (ratio > 0.75) {
                    td.style.fontWeight = "700";
                    td.style.color = "#ffffff";
                } else {
                    td.style.color = "#e2e8f0";
                }
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    root.appendChild(tbl);
}

function renderTopology(payload) {
    const root = $("chart-topology");
    root.innerHTML = "";
    if (!payload || !payload.nodes || payload.nodes.length === 0) {
        setEmpty("empty-topology", true); return;
    }
    setEmpty("empty-topology", false);

    const groupNodes = payload.nodes.filter(n => n.role === "group");
    const silos = payload.nodes.filter(n => n.role !== "group" && n.role !== "deployment");
    const deployments = payload.nodes.filter(n => n.role === "deployment");

    const groupedSilos = {};
    payload.edges.filter(e => e.kind === "group").forEach(e => {
        (groupedSilos[e.source] ||= []).push(e.target);
    });

    groupNodes.forEach(g => {
        const block = document.createElement("div");
        block.className = "group-block";
        const label = document.createElement("div");
        label.className = "group-label";
        label.innerHTML = `<span style="font-size:16px;">📂</span> 그룹: ${g.label}`;
        block.appendChild(label);
        for (const siloId of (groupedSilos[g.id] || [])) {
            const silo = silos.find(s => s.id === siloId);
            if (!silo) continue;
            const row = document.createElement("div");
            row.className = "silo-row";
            const left = document.createElement("span");
            left.className = "silo-info";
            left.innerHTML = `<span class="silo-id">${silo.id}</span> <span class="silo-meta">(${silo.label})</span>`;
            
            const right = document.createElement("span");
            if (silo.over_budget) {
                right.className = "status-indicator status-over";
                right.textContent = "자원 압박";
            } else {
                right.className = "status-indicator status-ok";
                right.textContent = "정상";
            }
            row.appendChild(left);
            row.appendChild(right);
            block.appendChild(row);
        }
        root.appendChild(block);
    });

    if (deployments.length) {
        const dblock = document.createElement("div");
        dblock.className = "group-block";
        const dlabel = document.createElement("div");
        dlabel.className = "group-label";
        dlabel.innerHTML = `🚀 운영 중 배포: ${deployments.length}건`;
        dblock.appendChild(dlabel);
        deployments.forEach(d => {
            const row = document.createElement("div");
            row.className = "silo-row";
            const left = document.createElement("span");
            left.innerHTML = `<span class="silo-id" style="color: #38bdf8;">${d.id}</span>`;
            const right = document.createElement("span");
            right.textContent = d.label;
            right.style.color = "#94a3b8";
            right.style.fontSize = "12px";
            row.appendChild(left);
            row.appendChild(right);
            dblock.appendChild(row);
        });
        root.appendChild(dblock);
    }
}

async function refresh() {
    const model_name = $("model-select").value;
    const version = $("version-select").value;
    const metric = $("metric-select").value;
    const resource_metric = $("resource-select").value;
    const featureRaw = $("feature-input").value.trim();
    if (!model_name || !version) return;

    // 만약 데모 모킹 시뮬레이션이 활성화되어 있다면 백엔드 통신 없이 동적 생성 투사
    if ($("mock-toggle")?.checked) {
        const data = generateMockDashboardData(model_name, version, metric, resource_metric, featureRaw);
        renderTimeseries(chartPayload(data.timeseries));
        renderHistogram(featureRaw ? chartPayload(data.histogram) : null);
        renderBar(chartPayload(data.silo_bar_resource));
        renderHeatmap(chartPayload(data.heatmap));
        renderTopology(chartPayload(data.topology));
        await renderOperations();
        return;
    }

    const params = new URLSearchParams({ model_name, version, metric, resource_metric });
    if (featureRaw) params.set("feature", featureRaw);

    try {
        const data = await fetchJSON(`/api/dashboard?${params}`);
        renderTimeseries(chartPayload(data.timeseries));
        renderHistogram(featureRaw ? chartPayload(data.histogram) : null);
        renderBar(chartPayload(data.silo_bar_resource));
        renderHeatmap(chartPayload(data.heatmap));
        renderTopology(chartPayload(data.topology));
        await renderOperations();
    } catch (e) {
        console.error(e);
        if (e instanceof AuthError) {
            setAuthBanner(true);
        } else {
            alert("대시보드 데이터 로드 실패: " + e.message);
        }
    }
}

$("ops-detail-close")?.addEventListener("click", hideOpsDetail);
$("auth-retry-btn")?.addEventListener("click", async () => {
    saveApiKey();
    setAuthBanner(false);
    if (!$("model-select").value) {
        try {
            const byName = await loadModels();
            applyQueryDefaults(byName || {});
        } catch (e) {
            await renderOperations();
            return;
        }
    }
    await refresh();
});

$("refresh-btn").addEventListener("click", async () => {
    saveApiKey();
    if (!$("model-select").value) {
        const byName = await loadModels();
        applyQueryDefaults(byName || {});
    }
    await refresh();
});

// 데모 시뮬레이션 토글 핸들러 (켜지면 2초 실시간 진동 루프 ON)
$("mock-toggle")?.addEventListener("change", async (e) => {
    const active = e.target.checked;
    
    // 타이머 청소
    if (mockInterval) {
        clearInterval(mockInterval);
        mockInterval = null;
    }

    if (active) {
        // 모킹 시 즉시 로딩 후 2초마다 refresh()로 난수 진동 재갱신
        await loadModels();
        await refresh();
        mockInterval = setInterval(async () => {
            await refresh();
        }, 2000);
    } else {
        // 비활성화 시 모킹 상태 리셋 후 백엔드 재호출
        mockState = { timeseries: null, silo_bar_resource: null, heatmap: null, topology: null, histogram: null };
        try {
            const byName = await loadModels();
            applyQueryDefaults(byName || {});
            await refresh();
        } catch(err) {
            await renderOperations();
        }
    }
});

["model-select", "version-select", "metric-select", "resource-select"].forEach(id => {
    $(id).addEventListener("change", refresh);
});
$("api-key-input").addEventListener("change", saveApiKey);

(async () => {
    try {
        $("api-key-input").value = sessionStorage.getItem(API_KEY_STORAGE_KEY) || "";
        const byName = await loadModels();
        applyQueryDefaults(byName || {});
        if ($("model-select").value) await refresh();
        else await renderOperations();
    } catch (e) {
        console.error(e);
        if (e instanceof AuthError) setAuthBanner(true);
        await renderOperations();
    }
})();
