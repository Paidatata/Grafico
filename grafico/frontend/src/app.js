// ==========================================================================
// Config & Constant Definitions
// ==========================================================================
const SVG_NS = "http://www.w3.org/2000/svg";

// Dimensions
const CHART_WIDTH = 12000; // Represents 04:00 to 24:00 (20 hours * 600px/hour)
const CHART_HEIGHT = 800;

// Margins
const MARGIN_LEFT = 150; // For station names
const MARGIN_RIGHT = 100;
const MARGIN_TOP = 50;
const MARGIN_BOTTOM = 50;

const USABLE_WIDTH = CHART_WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
const USABLE_HEIGHT = CHART_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM;

// Scales
// The chart spans one full service day: 04:00 today through 04:00 the next day.
// END_HOUR = 28 means "28 hours past midnight" (i.e. 04:00 the next day), not a
// literal clock hour — it's what lets a stop at, say, 00:15 render as the tail of
// the day instead of wrapping back to the chart's left edge. Mirrors the
// SERVICE_DAY_START_HOUR convention in backend/src/timeutils.py.
const START_HOUR = 4;
const END_HOUR = 28;
const TOTAL_HOURS = END_HOUR - START_HOUR;

// Coordinate helpers
// Time mapping: X pixel to Minutes from midnight
// X coordinate in DXF had scale: 1 minute = 20 units.
// In our SVG viewport, we map X linearly between MARGIN_LEFT and CHART_WIDTH - MARGIN_RIGHT
//
// timeToX/xToTime work in *service-day* minutes (via timeStrToServiceMinutes below),
// not raw clock minutes, so 00:00-03:59 stops land after 23:59 rather than before
// 04:00. Grid-line positions use serviceOffsetMinutesToX instead (see drawGrid) —
// they need the START_HOUR..END_HOUR boundary to stay unwrapped, which the
// timeStrToServiceMinutes modulo would otherwise collapse onto the left edge.
function timeToX(timeStr) {
    const serviceMinutes = timeStrToServiceMinutes(timeStr);
    const pct = serviceMinutes / (TOTAL_HOURS * 60);
    return MARGIN_LEFT + pct * USABLE_WIDTH;
}

function xToTime(x) {
    const pct = Math.max(0, Math.min(1, (x - MARGIN_LEFT) / USABLE_WIDTH));
    const serviceMinutes = pct * TOTAL_HOURS * 60;
    const rawMinutes = (serviceMinutes + START_HOUR * 60) % (24 * 60);

    const h = Math.floor(rawMinutes / 60);
    const m = Math.floor(rawMinutes % 60);
    const s = Math.floor((rawMinutes * 60) % 60);

    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function xToTimeSnapped(x, snapMinutes = 5) {
    const timeStr = xToTime(x);
    let minutes = timeStrToMinutes(timeStr);
    minutes = Math.round(minutes / snapMinutes) * snapMinutes;
    const h = Math.floor(minutes / 60) % 24;
    const m = Math.floor(minutes % 60);
    const s = Math.round((minutes * 60) % 60); // Use round to avoid floating point issues
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// Unwrapped hour-offset-from-START_HOUR -> X, used only for grid-line placement.
// h in drawGrid legitimately runs past 24 (up to END_HOUR=28) to reach the chart's
// right edge; feeding that through timeToX's wrapping service-minutes formula would
// hit the modulo boundary exactly at h=28 and draw the last gridline on top of the
// first instead of at the right edge.
function serviceOffsetMinutesToX(offsetMinutes) {
    const pct = offsetMinutes / (TOTAL_HOURS * 60);
    return MARGIN_LEFT + pct * USABLE_WIDTH;
}

function timeStrToMinutes(timeStr) {
    if (!timeStr) return 0;
    const parts = timeStr.split(":").map(Number);
    const h = parts[0] || 0;
    const m = parts[1] || 0;
    const s = parts[2] || 0;
    return h * 60 + m + (s / 60);
}

// Minutes elapsed since the service day started at START_HOUR (04:00), wrapping at 24h.
// Mirrors backend/src/timeutils.py's time_str_to_service_minutes. Use this — never
// timeStrToMinutes — whenever two times are compared for ordering or elapsed distance,
// so trips that cross midnight stay monotonic (00:02 comes *after* 23:59, not before).
function timeStrToServiceMinutes(timeStr) {
    const raw = timeStrToMinutes(timeStr);
    return ((raw - START_HOUR * 60) % (24 * 60) + (24 * 60)) % (24 * 60);
}

function dateToServiceMinutes(date) {
    const raw = date.getHours() * 60 + date.getMinutes() + (date.getSeconds() / 60);
    return ((raw - START_HOUR * 60) % (24 * 60) + (24 * 60)) % (24 * 60);
}

// Reads whatever time is currently centered in the chart's visible viewport —
// the "reference time" the sidebar lists and the now-line represent. Falls
// back to the real clock if the chart hasn't rendered yet (e.g. before the
// first successful load).
function getReferenceTime() {
    const container = document.getElementById("chart-container");
    if (!container || container.clientWidth === 0) return currentClockTimeStr();
    const centerX = container.scrollLeft + container.clientWidth / 2;
    return xToTime(centerX);
}

function currentClockTimeStr() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
}

// ==========================================================================
// Generic Dialog (shared primitive — used by Grades, Edição de Viagem, etc.)
// ==========================================================================
function showDialog({ title, fields, onConfirm, confirmLabel = "Confirmar" }) {
    const overlay = document.getElementById("dialog-overlay");
    const box = document.getElementById("dialog-box");

    const fieldsHtml = fields.map(f => `
        <div class="dialog-field">
            <label for="dialog-field-${f.name}">${f.label}</label>
            <input
                id="dialog-field-${f.name}"
                type="${f.type || 'text'}"
                value="${f.value !== undefined ? f.value : ''}"
                ${f.required ? 'required' : ''}
            >
        </div>
    `).join("");

    box.innerHTML = `
        <h3>${title}</h3>
        ${fieldsHtml}
        <div class="dialog-actions">
            <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
            <button class="btn btn-primary btn-sm" id="dialog-confirm">${confirmLabel}</button>
        </div>
    `;

    overlay.classList.remove("hidden");

    const close = () => overlay.classList.add("hidden");

    document.getElementById("dialog-cancel").onclick = close;
    document.getElementById("dialog-confirm").onclick = () => {
        const values = {};
        for (const f of fields) {
            const input = document.getElementById(`dialog-field-${f.name}`);
            if (f.required && !input.value) {
                input.focus();
                return;
            }
            values[f.name] = input.value;
        }
        close();
        onConfirm(values);
    };
}

function showConfirmDialog({ title, message, confirmLabel = "Confirmar", onConfirm, onCancel }) {
    const overlay = document.getElementById("dialog-overlay");
    const box = document.getElementById("dialog-box");

    box.innerHTML = `
        <h3>${title}</h3>
        <p style="margin: 14px 0 20px 0; font-size: 14px; color: var(--text-primary); line-height: 1.4;">${message}</p>
        <div class="dialog-actions">
            <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
            <button class="btn btn-primary btn-sm" id="dialog-confirm">${confirmLabel}</button>
        </div>
    `;

    overlay.classList.remove("hidden");

    const close = () => overlay.classList.add("hidden");

    document.getElementById("dialog-cancel").onclick = () => {
        close();
        if (onCancel) onCancel();
    };
    document.getElementById("dialog-confirm").onclick = () => {
        close();
        if (onConfirm) onConfirm();
    };
}

// ==========================================================================
// Generic Context Menu (shared primitive)
// ==========================================================================
let _contextMenuOutsideClickHandler = null;

function showContextMenu(clientX, clientY, items) {
    const menu = document.getElementById("context-menu");
    menu.innerHTML = items.map((item, i) => `<li data-idx="${i}">${item.label}</li>`).join("");
    menu.style.left = `${clientX}px`;
    menu.style.top = `${clientY}px`;
    menu.classList.remove("hidden");

    menu.querySelectorAll("li").forEach((li, i) => {
        li.onclick = () => {
            hideContextMenu();
            items[i].onClick();
        };
    });

    if (_contextMenuOutsideClickHandler) {
        document.removeEventListener("click", _contextMenuOutsideClickHandler);
    }
    _contextMenuOutsideClickHandler = (e) => {
        if (!menu.contains(e.target)) hideContextMenu();
    };
    // Deferred so the same click that opened the menu (a `contextmenu` event,
    // separate from `click`) doesn't immediately trigger this outside-click check.
    setTimeout(() => document.addEventListener("click", _contextMenuOutsideClickHandler), 0);
}

function hideContextMenu() {
    document.getElementById("context-menu").classList.add("hidden");
    if (_contextMenuOutsideClickHandler) {
        document.removeEventListener("click", _contextMenuOutsideClickHandler);
        _contextMenuOutsideClickHandler = null;
    }
}

// ==========================================================================
// Mode Switching (Operacional / Grades)
// ==========================================================================
function switchMode(mode) {
    appState.mode = mode;

    document.getElementById("btn-mode-operational").classList.toggle("active", mode === "operational");
    document.getElementById("btn-mode-schedules").classList.toggle("active", mode === "schedules");
    document.getElementById("operational-view").classList.toggle("hidden", mode !== "operational");
    document.getElementById("schedules-view").classList.toggle("hidden", mode !== "schedules");

    if (mode === "schedules") renderSchedulesView();
}

// ==========================================================================
// Grades View
// ==========================================================================
function renderSchedulesView() {
    const container = document.getElementById("schedules-view");
    container.innerHTML = `
        <aside class="sidebar sidebar-left glass-panel" id="schedules-list-panel">
            <div class="panel-header"><h2>Grades</h2></div>
            <ul class="train-list" id="schedules-list"></ul>
            <div class="schedules-actions">
                <button class="btn btn-secondary btn-sm" onclick="promptCreateSchedule()">Nova Grade</button>
                <button class="btn btn-secondary btn-sm" onclick="promptCloneSchedule()">Salvar Como</button>
                <button class="btn btn-secondary btn-sm" onclick="promptRenameSchedule()">Renomear</button>
                <button class="btn btn-secondary btn-sm" onclick="promptDeleteSchedule()">Excluir</button>
                <button class="btn btn-primary btn-sm" onclick="promptLoadSchedule()">Carregar p/ Hoje</button>
            </div>
        </aside>
        <section class="graphic-area glass-panel">
            <div class="panel-header"><h2>Editor de Grade</h2></div>
            <div class="chart-scroll-container" id="schedule-editor-container"></div>
        </section>
    `;

    loadSchedulesList();
}

function loadSchedulesList() {
    fetch("/api/schedules")
        .then(r => r.json())
        .then(schedules => {
            appState.schedules = schedules;
            if (appState.editorScheduleId === undefined || appState.editorScheduleId === null) {
                appState.editorScheduleId = schedules[0] ? schedules[0].id : null;
            }
            renderSchedulesList(schedules);
            renderScheduleEditor();
        });
}

function renderSchedulesList(schedules) {
    const list = document.getElementById("schedules-list");
    list.innerHTML = schedules.map(s => `
        <li class="train-item ${appState.editorScheduleId === s.id ? 'selected' : ''}" onclick="selectEditorSchedule(${s.id})">
            <div class="train-info"><span class="train-code-label">${s.name}</span></div>
        </li>
    `).join("");
}

function selectEditorSchedule(scheduleId) {
    appState.editorScheduleId = scheduleId;
    loadSchedulesList();
}

function promptCreateSchedule() {
    showDialog({
        title: "Nova Grade",
        fields: [{ name: "name", label: "Nome", required: true }],
        onConfirm: (values) => {
            fetch("/api/schedules", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(created => { appState.editorScheduleId = created.id; loadSchedulesList(); })
                .catch(err => alert("Não foi possível criar a grade: " + err.message));
        },
    });
}

function promptCloneSchedule() {
    if (!appState.editorScheduleId) return;
    showDialog({
        title: "Salvar Como",
        fields: [{ name: "name", label: "Novo nome", required: true }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}/clone`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(created => { appState.editorScheduleId = created.id; loadSchedulesList(); })
                .catch(err => alert("Não foi possível salvar como: " + err.message));
        },
    });
}

function promptRenameSchedule() {
    if (!appState.editorScheduleId) return;
    const current = appState.schedules.find(s => s.id === appState.editorScheduleId);
    showDialog({
        title: "Renomear Grade",
        fields: [{ name: "name", label: "Nome", required: true, value: current ? current.name : "" }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}`, {
                method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: values.name }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(() => loadSchedulesList())
                .catch(err => alert("Não foi possível renomear: " + err.message));
        },
    });
}

function promptDeleteSchedule() {
    if (!appState.editorScheduleId) return;
    if (!confirm("Excluir esta grade? Esta ação não pode ser desfeita.")) return;
    fetch(`/api/schedules/${appState.editorScheduleId}`, { method: "DELETE" })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(() => { appState.editorScheduleId = null; loadSchedulesList(); })
        .catch(err => alert("Não foi possível excluir: " + err.message));
}

function promptLoadSchedule() {
    if (!appState.editorScheduleId) return;
    const current = appState.schedules.find(s => s.id === appState.editorScheduleId);
    if (!confirm(`Carregar "${current ? current.name : ''}" para operação hoje? As viagens em curso serão substituídas.`)) return;
    fetch(`/api/schedules/${appState.editorScheduleId}/load`, { method: "POST" })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(data => {
            initSchedule(data);
            switchMode("operational");
        })
        .catch(err => alert("Não foi possível carregar a grade: " + err.message));
}

function renderScheduleEditor() {
    const container = document.getElementById("schedule-editor-container");
    if (!appState.editorScheduleId) { container.innerHTML = ""; return; }

    fetch(`/api/schedules/${appState.editorScheduleId}/trips`)
        .then(r => r.json())
        .then(data => {
            appState.editorTrips = data.trips;
            drawScheduleEditorChart(container);
        });
}

function drawScheduleEditorChart(container) {
    container.innerHTML = "";
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", CHART_WIDTH);
    svg.setAttribute("height", CHART_HEIGHT);
    svg.setAttribute("id", "schedule-editor-svg");

    drawGrid(svg);

    appState.editorTrips.forEach(trip => {
        const points = trip.stops.map(stop =>
            `${timeToX(stop.time)},${dxfYToSvg(stop.y_coord, appState.selectedLine)}`
        ).join(" ");
        const polyline = document.createElementNS(SVG_NS, "polyline");
        polyline.setAttribute("points", points);
        polyline.className.baseVal = "train-path-planned";
        polyline.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            e.stopPropagation();
            showContextMenu(e.clientX, e.clientY, [
                { label: "Editar prefixo", onClick: () => promptEditPrefix(trip) },
            ]);
        });
        svg.appendChild(polyline);
    });

    svg.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY, [
            { label: "Nova Viagem", onClick: () => startTripCreationMode() },
        ]);
    });
    svg.addEventListener("click", onScheduleEditorClick);

    container.appendChild(svg);
}

function startTripCreationMode() {
    appState.tripCreationMode = {};
    document.getElementById("schedule-editor-svg").style.cursor = "crosshair";
}

function onScheduleEditorClick(e) {
    if (!appState.tripCreationMode) return;

    const svg = document.getElementById("schedule-editor-svg");
    const rect = svg.getBoundingClientRect();
    const svgX = e.clientX - rect.left;
    const svgY = e.clientY - rect.top;
    const station = yToStation(svgY, appState.selectedLine);
    if (!station) return;  // click missed every station within tolerance — ignore
    const time = xToTimeSnapped(svgX, 5); // Snap to 5 minutes

    if (!appState.tripCreationMode.firstPoint) {
        appState.tripCreationMode.firstPoint = { station: station.id, time };
        return;
    }

    const secondPoint = { station: station.id, time };
    const firstPoint = appState.tripCreationMode.firstPoint;
    if (firstPoint.station === secondPoint.station) {
        return; // Ignora se clicou na mesma estação
    }
    appState.tripCreationMode = null;
    document.getElementById("schedule-editor-svg").style.cursor = "default";
    openTripCreationDialog(firstPoint, secondPoint);
}

function openTripCreationDialog(firstPoint, secondPoint) {
    const [origin, destination] = timeStrToMinutes(firstPoint.time) <= timeStrToMinutes(secondPoint.time)
        ? [firstPoint, secondPoint] : [secondPoint, firstPoint];
    const direction = `${origin.station}-${destination.station}`;

    const overlay = document.getElementById("dialog-overlay");
    const box = document.getElementById("dialog-box");
    box.innerHTML = `
        <h3>Nova Viagem</h3>
        <p>Origem: ${origin.station} às ${origin.time.substring(0, 5)}</p>
        <p>Destino: ${destination.station} às ${destination.time.substring(0, 5)}</p>
        <div class="dialog-field">
            <label for="tc-prefix">Prefixo</label>
            <input id="tc-prefix" required maxlength="3">
        </div>
        <div class="dialog-field">
            <label for="tc-count">Nº de viagens</label>
            <input id="tc-count" type="number" value="1" min="1">
        </div>
        <div class="dialog-field">
            <label for="tc-headway">Intervalo (MM:SS)</label>
            <input id="tc-headway" value="15:00">
        </div>
        <div class="dialog-actions">
            <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
            <button class="btn btn-primary btn-sm" id="dialog-confirm">Criar</button>
        </div>
    `;
    overlay.classList.remove("hidden");

    document.getElementById("dialog-cancel").onclick = () => overlay.classList.add("hidden");
    document.getElementById("dialog-confirm").onclick = () => {
        const prefix = document.getElementById("tc-prefix").value;
        if (!prefix) { document.getElementById("tc-prefix").focus(); return; }
        const count = parseInt(document.getElementById("tc-count").value, 10);
        const [mm, ss] = document.getElementById("tc-headway").value.split(":").map(Number);
        const headwaySeconds = mm * 60 + ss;

        overlay.classList.add("hidden");

        fetch(`/api/schedules/${appState.editorScheduleId}/trips/batch`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                direction, first_departure: origin.time, last_station: destination.station,
                count, headway_seconds: headwaySeconds, prefix,
                stop_offsets: [
                    { station: origin.station, offset_seconds: 0 },
                    { station: destination.station, offset_seconds: Math.round((timeStrToMinutes(destination.time) - timeStrToMinutes(origin.time)) * 60) },
                ],
            }),
        })
            .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
            .then(() => renderScheduleEditor())
            .catch(err => alert("Não foi possível criar a viagem: " + err.message));
    };
}

function promptEditPrefix(trip) {
    const currentPrefix = trip.train_code.match(/^([A-Za-z]+)/)?.[1] || "";
    showDialog({
        title: `Editar prefixo — ${trip.train_code}`,
        fields: [{ name: "prefix", label: "Prefixo", required: true, value: currentPrefix }],
        onConfirm: (values) => {
            fetch(`/api/schedules/${appState.editorScheduleId}/trips/${encodeURIComponent(trip.trip_id)}`, {
                method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prefix: values.prefix }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                .then(() => renderScheduleEditor())
                .catch(err => alert("Não foi possível editar o prefixo: " + err.message));
        },
    });
}

// True if referenceTimeStr falls within [trip.start_time, trip.end_time], in
// service-day minutes so trips crossing midnight behave the same way the
// backend's chronology/lookback checks and the drag-lock check already do.
// Slack absorbs sub-pixel scrollLeft rounding: the chart is ~8.2 px/min, so a
// half-pixel snap shifts the derived reference time by a few seconds and would
// otherwise drop a trip from its own list at the exact instant it was centered
// (e.g. right after clicking it in the sidebar).
const IN_TRANSIT_SLACK_MINUTES = 0.5;

function isTripInTransitAt(trip, referenceTimeStr) {
    const ref = timeStrToServiceMinutes(referenceTimeStr);
    const start = timeStrToServiceMinutes(trip.start_time);
    const end = timeStrToServiceMinutes(trip.end_time);
    return ref >= start - IN_TRANSIT_SLACK_MINUTES && ref <= end + IN_TRANSIT_SLACK_MINUTES;
}

// "P15" -> 15. Used to sort each sidebar panel by departure order (parser.py
// assigns train_code numbers in departure order already, so sorting by number
// is equivalent to sorting by start_time).
function trainNumber(trainCode) {
    return parseInt(trainCode.slice(1), 10);
}

function minutesToTimeStr(totalMinutes) {
    const h = Math.floor(totalMinutes / 60) % 24;
    const m = Math.floor(totalMinutes % 60);
    const s = Math.floor((totalMinutes * 60) % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// Station metadata
const stations = {
    "Line 10": [
        {"id": "BFU", "name": "Barra Funda", "y_dxf": 5860.32},
        {"id": "LUZ", "name": "Luz", "y_dxf": 5380.32},
        {"id": "BAS", "name": "Brás", "y_dxf": 4980.32},
        {"id": "MOC", "name": "Juventus-Mooca", "y_dxf": 4740.32},
        {"id": "IPG", "name": "Ipiranga", "y_dxf": 4380.32},
        {"id": "TMD", "name": "Tamanduateí", "y_dxf": 4180.32},
        {"id": "SCS", "name": "São Caetano do Sul", "y_dxf": 3860.32},
        {"id": "UTG", "name": "Utinga", "y_dxf": 3420.32},
        {"id": "PSA", "name": "Prefeito Saladino", "y_dxf": 3220.32},
        {"id": "SAN", "name": "Santo André", "y_dxf": 2980.32},
        {"id": "CPV", "name": "Capuava", "y_dxf": 2500.32},
        {"id": "MAU", "name": "Mauá", "y_dxf": 2100.32},
        {"id": "GPT", "name": "Guapituba", "y_dxf": 1660.32},
        {"id": "RPI", "name": "Ribeirão Pires", "y_dxf": 1100.32},
        {"id": "RGS", "name": "Rio Grande da Serra", "y_dxf": 500.32}
    ],
    "Line 7": [
        {"id": "JUN", "name": "Jundiaí", "y_dxf": 11520.32},
        {"id": "VAU", "name": "Várzea Paulista", "y_dxf": 11220.32},
        {"id": "CLP", "name": "Campo Limpo Paulista", "y_dxf": 10900.32},
        {"id": "BTJ", "name": "Botujuru", "y_dxf": 10580.32},
        {"id": "FDR", "name": "Francisco Morato", "y_dxf": 10300.32},
        {"id": "BFI", "name": "Baltazar Fidélis", "y_dxf": 9940.32},
        {"id": "FMO", "name": "Franco da Rocha", "y_dxf": 9500.32},
        {"id": "CAI", "name": "Caieiras", "y_dxf": 9260.32},
        {"id": "PRT", "name": "Perus", "y_dxf": 8700.32},
        {"id": "VPL", "name": "Vila Aurora", "y_dxf": 8260.32},
        {"id": "JRG", "name": "Jaraguá", "y_dxf": 7900.32},
        {"id": "VCL", "name": "Vila Clarice", "y_dxf": 7500.32},
        {"id": "PRU", "name": "Pirituba", "y_dxf": 7300.32},
        {"id": "PQR", "name": "Piqueri", "y_dxf": 6980.32},
        {"id": "LPA", "name": "Lapa", "y_dxf": 6700.32},
        {"id": "ABR", "name": "Água Branca", "y_dxf": 6420.32},
        {"id": "LUZ_L7", "name": "Luz (L7)", "y_dxf": 6180.32}
    ]
};

// Unified Line 710 simply combines both
stations["Line 710"] = [...stations["Line 7"], ...stations["Line 10"]];

// Sort stations by Y dxf coordinate descending (so Jundiaí is top, Rio Grande da Serra is bottom)
stations["Line 710"].sort((a, b) => b.y_dxf - a.y_dxf);

// Y scaling: maps DXF Y coordinate to SVG Y pixel coordinate
function dxfYToSvg(y, lineType) {
    const lineStations = stations[lineType];
    const minY = lineStations[lineStations.length - 1].y_dxf;
    const maxY = lineStations[0].y_dxf;
    
    // Invert Y so high Y is at top of SVG (higher elevation in chart)
    const pct = (y - minY) / (maxY - minY);
    return MARGIN_TOP + (1.0 - pct) * USABLE_HEIGHT;
}

// Inverse of dxfYToSvg: nearest station to an SVG Y pixel, or null outside tolerance.
const STATION_SNAP_TOLERANCE_PX = 25;

function yToStation(svgY, lineType) {
    const lineStations = stations[lineType];
    let best = null;
    let bestDist = Infinity;
    for (const station of lineStations) {
        const stationY = dxfYToSvg(station.y_dxf, lineType);
        const dist = Math.abs(svgY - stationY);
        if (dist < bestDist) { bestDist = dist; best = station; }
    }
    return bestDist <= STATION_SNAP_TOLERANCE_PX ? best : null;
}

// Global Application State
let appState = {
    mode: "operational", // "operational" | "schedules"
    editorScheduleId: null,
    tripCreationMode: null, // { firstPoint: {station, time} }
    selectedLine: "Line 10",
    trips: [],          // Working trips data
    selectedTripId: null,
    showRealized: false,
    realizedTrips: [],  // Compare track data
    dragNode: null,     // Reference to node currently being dragged
    editLookbackMinutes: 15,  // Sane default before the server value loads
    // Set when a live update arrives mid-drag; drained once the gesture commits.
    pendingRerender: false,
    // True while a centerChartOnTime() scrollTo is in flight, so the scroll
    // events it generates aren't mistaken for user interaction.
    isProgrammaticScroll: false,
    // True while auto-scroll is paused because the operator is interacting
    // with the chart (dragging a node, or scrolling it manually); resumes
    // automatically AUTO_SCROLL_RESUME_IDLE_MS after the last interaction.
    autoScrollPaused: false,
    lastInteractionAt: 0,
    departFromMode: null,
    autoRegulationEnabled: false,
    interdictionCreationMode: null,
    interdictions: []
};

// ==========================================================================
// Interdictions
// ==========================================================================
// Right-click on empty chart space fixes the first corner (see the svg
// "contextmenu" listener in renderChart); dragging the mouse from there live-previews
// the rectangle, and a left-click fixes the second corner and opens the dialog.
let _interdictionPreviewRect = null;

function startInterdictionDrag(firstPoint) {
    appState.interdictionCreationMode = { firstPoint };
    const chartSvg = document.getElementById("train-chart-svg");
    if (chartSvg) chartSvg.style.cursor = "crosshair";
}

function onInterdictionDragPreview(e) {
    if (!appState.interdictionCreationMode) return;

    const svg = document.getElementById("train-chart-svg");
    const rect = svg.getBoundingClientRect();
    const svgX = e.clientX - rect.left;
    const svgY = e.clientY - rect.top;

    const firstPoint = appState.interdictionCreationMode.firstPoint;
    const x1 = timeToX(firstPoint.time);
    const y1 = dxfYToSvg(firstPoint.y, appState.selectedLine);

    if (!_interdictionPreviewRect) {
        _interdictionPreviewRect = document.createElementNS(SVG_NS, "rect");
        _interdictionPreviewRect.className.baseVal = "interdiction-rect interdiction-rect-preview";
        svg.appendChild(_interdictionPreviewRect);
    }
    _interdictionPreviewRect.setAttribute("x", Math.min(x1, svgX));
    _interdictionPreviewRect.setAttribute("y", Math.min(y1, svgY));
    _interdictionPreviewRect.setAttribute("width", Math.abs(svgX - x1));
    _interdictionPreviewRect.setAttribute("height", Math.abs(svgY - y1));
}

function clearInterdictionPreview() {
    if (_interdictionPreviewRect) {
        _interdictionPreviewRect.remove();
        _interdictionPreviewRect = null;
    }
}

function onChartClickForInterdiction(e) {
    if (!appState.interdictionCreationMode) return;

    const svg = document.getElementById("train-chart-svg");
    const rect = svg.getBoundingClientRect();
    const svgX = e.clientX - rect.left;
    const svgY = e.clientY - rect.top;
    const secondPoint = { time: xToTime(svgX), y: svgYToDxfY(svgY) };

    const firstPoint = appState.interdictionCreationMode.firstPoint;
    appState.interdictionCreationMode = null;
    if (svg) svg.style.cursor = "default";
    clearInterdictionPreview();
    openInterdictionDialog(firstPoint, secondPoint);
}

function svgYToDxfY(svgY) {
    const lineStations = stations[appState.selectedLine];
    const minY = lineStations[lineStations.length - 1].y_dxf;
    const maxY = lineStations[0].y_dxf;
    const pct = (svgY - MARGIN_TOP) / USABLE_HEIGHT;
    return maxY - pct * (maxY - minY);
}

function openInterdictionDialog(firstPoint, secondPoint, existing = null) {
    if (existing) {
        const overlay = document.getElementById("dialog-overlay");
        const box = document.getElementById("dialog-box");
        box.innerHTML = `
            <h3>Editar Interdição</h3>
            <div class="dialog-field"><label>Descrição</label><input id="id-description" value="${existing.description}"></div>
            <div class="dialog-field"><label>Hora inicial</label><input id="id-start" type="time" value="${existing.start_time.substring(0, 5)}"></div>
            <div class="dialog-field"><label>Hora final</label><input id="id-end" type="time" value="${existing.end_time.substring(0, 5)}"></div>
            <div class="dialog-actions">
                <button class="btn btn-secondary btn-sm" id="id-delete">Excluir</button>
                <button class="btn btn-secondary btn-sm" id="dialog-cancel">Cancelar</button>
                <button class="btn btn-primary btn-sm" id="dialog-confirm">Salvar</button>
            </div>
        `;
        overlay.classList.remove("hidden");
        const close = () => overlay.classList.add("hidden");
        document.getElementById("dialog-cancel").onclick = close;
        document.getElementById("id-delete").onclick = () => {
            if (!confirm("Excluir esta interdição?")) return;
            close();
            fetch(`/api/interdictions/${existing.id}`, { method: "DELETE" })
                .then(r => { if (!r.ok) throw new Error("Falha ao excluir"); return reloadScheduleFromServer(); })
                .catch(err => alert(err.message));
        };
        document.getElementById("dialog-confirm").onclick = () => {
            close();
            fetch(`/api/interdictions/${existing.id}`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    y_top: existing.y_top, y_bottom: existing.y_bottom,
                    start_time: document.getElementById("id-start").value + ":00",
                    end_time: document.getElementById("id-end").value + ":00",
                    description: document.getElementById("id-description").value,
                }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível salvar: " + err.message));
        };
        return;
    }

    showDialog({
        title: "Nova Interdição",
        fields: [
            { name: "description", label: "Descrição", value: "" },
            { name: "start_time", label: "Hora inicial", type: "time", value: firstPoint.time.substring(0, 5) },
            { name: "end_time", label: "Hora final", type: "time", value: secondPoint.time.substring(0, 5) },
        ],
        confirmLabel: "Criar",
        onConfirm: (values) => {
            fetch("/api/interdictions", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    y_top: Math.min(firstPoint.y, secondPoint.y),
                    y_bottom: Math.max(firstPoint.y, secondPoint.y),
                    start_time: values.start_time + ":00",
                    end_time: values.end_time + ":00",
                    description: values.description,
                }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível criar a interdição: " + err.message));
        },
    });
}

function drawInterdictions(svg) {
    (appState.interdictions || []).forEach(interdiction => {
        const x1 = timeToX(interdiction.start_time);
        const x2 = timeToX(interdiction.end_time);
        const y1 = dxfYToSvg(interdiction.y_top, appState.selectedLine);
        const y2 = dxfYToSvg(interdiction.y_bottom, appState.selectedLine);

        const rect = document.createElementNS(SVG_NS, "rect");
        rect.setAttribute("x", Math.min(x1, x2));
        rect.setAttribute("y", Math.min(y1, y2));
        rect.setAttribute("width", Math.abs(x2 - x1));
        rect.setAttribute("height", Math.abs(y2 - y1));
        rect.className.baseVal = "interdiction-rect";
        rect.addEventListener("click", (e) => {
            e.stopPropagation();
            openInterdictionDialog(null, null, interdiction);
        });
        svg.appendChild(rect);

        const label = document.createElementNS(SVG_NS, "text");
        label.setAttribute("x", Math.min(x1, x2) + 6);
        label.setAttribute("y", Math.min(y1, y2) + 16);
        label.className.baseVal = "interdiction-label";
        label.textContent = interdiction.description;
        svg.appendChild(label);
    });
}

function loadAutoRegulationSetting() {
    fetch("/api/settings/auto-regulation")
        .then(r => r.json())
        .then(data => {
            appState.autoRegulationEnabled = data.enabled;
            syncAutoRegulationIcon();
        });
}

function toggleAutoRegulation() {
    const newValue = !appState.autoRegulationEnabled;
    fetch("/api/settings/auto-regulation", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: newValue }),
    })
        .then(r => r.json())
        .then(data => {
            appState.autoRegulationEnabled = data.enabled;
            syncAutoRegulationIcon();
        });
}

function syncAutoRegulationIcon() {
    const btn = document.getElementById("btn-auto-regulation");
    if (!btn) return;
    btn.classList.toggle("active", !!appState.autoRegulationEnabled);
    btn.title = appState.autoRegulationEnabled
        ? "Regulação automática: ligada (clique para desligar)"
        : "Regulação automática: desligada (clique para ligar)";
}

function applyRegulation(arrivalTripId, stationId) {
    fetch("/api/regulation/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trip_id: arrivalTripId, station_id: stationId }),
    })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(updatedTrips => {
            updatedTrips.forEach(applyTripUpdate);
        })
        .catch(err => alert("Não foi possível regular: " + err.message));
}


function activeStopRange(trip) {
    const first = trip.active_first_seq != null ? trip.active_first_seq : 0;
    const last = trip.active_last_seq != null ? trip.active_last_seq : trip.stops.length - 1;
    return { first, last };
}

function startDepartFromMode(trip) {
    appState.departFromMode = { tripId: trip.trip_id };
    const chartSvg = document.getElementById("train-chart-svg");
    if (chartSvg) chartSvg.style.cursor = "crosshair";
}

function confirmSuppressFrom(trip, stop) {
    const activeFirst = trip.active_first_seq || 0;
    const isFirstStop = stop.station === trip.stops[activeFirst].station;
    const message = isFirstStop
        ? `Cancelar a viagem ${trip.train_code} inteira?`
        : `Suprimir ${trip.train_code} a partir de ${stop.station}?`;
    if (!confirm(message)) return;

    fetch(`/api/trips/${encodeURIComponent(trip.trip_id)}/suppress-from/${encodeURIComponent(stop.station)}`, {
        method: "POST",
    })
        .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
        .then(updatedTrip => applyTripUpdate(updatedTrip))
        .catch(err => alert("Não foi possível suprimir: " + err.message));
}

// ==========================================================================
// Turnaround (Tempo de Volta)
// ==========================================================================
function formatTurnaroundSeconds(seconds) {
    if (seconds == null) return "";
    const mm = Math.floor(seconds / 60);
    const ss = seconds % 60;
    return `${mm}:${String(ss).padStart(2, '0')}`;
}

function parseTurnaroundInput(value) {
    if (!value) return null;
    if (value.includes(":")) {
        const [mm, ss] = value.split(":").map(Number);
        return mm * 60 + ss;
    }
    return parseInt(value, 10);
}

const DEFAULT_TURNAROUND_SECONDS = 180; // 3 minutos padrão

function openTurnaroundDialog(station) {
    const current = (appState.stationTurnarounds || {})[station.id];
    const displayValue = (current !== undefined && current !== null) ? current : DEFAULT_TURNAROUND_SECONDS;
    showDialog({
        title: `Tempo mínimo de volta em ${station.name}`,
        fields: [{
            name: "turnaround",
            label: "Tempo mínimo (MM:SS ou segundos, padrão: 03:00 / 3 min)",
            value: formatTurnaroundSeconds(displayValue)
        }],
        confirmLabel: "Salvar",
        onConfirm: (values) => {
            const seconds = parseTurnaroundInput(values.turnaround);
            fetch(`/api/stations/${encodeURIComponent(station.id)}/turnaround`, {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ turnaround_seconds: seconds }),
            })
                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return reloadScheduleFromServer(); })
                .catch(err => alert("Não foi possível salvar tempo de volta: " + err.message));
        },
    });
}

function effectiveFirstStop(trip) {
    const idx = trip.active_first_seq != null ? trip.active_first_seq : 0;
    return trip.stops[idx];
}

function effectiveLastStop(trip) {
    const idx = trip.active_last_seq != null ? trip.active_last_seq : trip.stops.length - 1;
    return trip.stops[idx];
}

function computeTurnaroundPairs() {
    const stationTurnarounds = appState.stationTurnarounds || {};
    const pairs = [];

    // Only stations with an explicitly configured turnaround take part in pairing/validation
    // (NULL/unconfigured means "no pairing for that station" -- no fallback default here).
    const configuredStationIds = Object.keys(stationTurnarounds).filter(
        id => stationTurnarounds[id] !== undefined && stationTurnarounds[id] !== null
    );

    configuredStationIds.forEach(stationId => {
        const turnaroundSeconds = stationTurnarounds[stationId];

        const directions = [...new Set((appState.trips || []).map(t => t.direction))];

        directions.forEach(dIn => {
            const arrivals = appState.trips
                .filter(t => t.active_last_seq !== -1 && effectiveLastStop(t) && effectiveLastStop(t).station === stationId && t.direction === dIn)
                .sort((a, b) => timeStrToServiceMinutes(effectiveLastStop(a).time) - timeStrToServiceMinutes(effectiveLastStop(b).time));
            const departures = appState.trips
                .filter(t => t.active_first_seq !== -1 && effectiveFirstStop(t) && effectiveFirstStop(t).station === stationId && t.direction !== dIn)
                .sort((a, b) => timeStrToServiceMinutes(effectiveFirstStop(a).time) - timeStrToServiceMinutes(effectiveFirstStop(b).time));

            // Positional pairing: the i-th arrival with the i-th departure, in chronological
            // order (same physical train, same platform). Leftovers on either side are simply
            // unpaired -- not an error.
            const pairCount = Math.min(arrivals.length, departures.length);
            for (let i = 0; i < pairCount; i++) {
                const arrivalTrip = arrivals[i];
                const departureTrip = departures[i];
                const arrTimeStr = effectiveLastStop(arrivalTrip).time;
                const departureTime = effectiveFirstStop(departureTrip).time;
                const arrMin = timeStrToServiceMinutes(arrTimeStr);
                const depMin = timeStrToServiceMinutes(departureTime);
                const gapSeconds = (depMin - arrMin) * 60;

                pairs.push({
                    stationId,
                    arrivalTrip,
                    departureTrip,
                    arrivalTime: arrTimeStr,
                    departureTime,
                    gapSeconds,
                    turnaroundSeconds,
                    valid: gapSeconds >= turnaroundSeconds,
                });
            }
        });
    });

    return pairs;
}

function drawTurnaroundConnectors(svg) {
    const lineStations = stations[appState.selectedLine];
    const pairs = computeTurnaroundPairs();
    const stationPairCount = {};

    // Use current reference time from viewport (now-line position) or real clock
    const refTimeStr = getReferenceTime();
    const refServiceMinutes = timeStrToServiceMinutes(refTimeStr);

    pairs.forEach(pair => {
        const station = lineStations.find(s => s.id === pair.stationId);
        if (!station) return;

        const x1 = timeToX(pair.arrivalTime);
        const x2 = timeToX(pair.departureTime);
        const yStation = dxfYToSvg(station.y_dxf, appState.selectedLine);

        // Check if station is in lower half of USABLE_HEIGHT
        const isLowerHalf = yStation > (MARGIN_TOP + USABLE_HEIGHT / 2);

        // Assign 3 alternating levels (8px, 16px, 24px)
        const pairIndex = stationPairCount[pair.stationId] || 0;
        stationPairCount[pair.stationId] = pairIndex + 1;
        const level = pairIndex % 3;
        const offset = 8 + level * 8; // 8px, 16px, 24px

        // Lower stations (ex: Rio Grande da Serra / RGS) offset DOWNWARDS (borda inferior)
        // Upper stations (ex: Jundiaí / BFU) offset UPWARDS (borda superior)
        const yLevel = isLowerHalf ? (yStation + offset) : (yStation - offset);

        // Path bracket: M x1 yStation L x1 yLevel L x2 yLevel L x2 yStation
        const pathData = `M ${x1} ${yStation} L ${x1} ${yLevel} L ${x2} ${yLevel} L ${x2} ${yStation}`;

        const depServiceMin = timeStrToServiceMinutes(pair.departureTime);
        const isRealized = depServiceMin <= refServiceMinutes;

        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", pathData);
        path.setAttribute("fill", "none");

        let className = "turnaround-connector";
        if (!pair.valid) {
            className += " violation";
            path.setAttribute("stroke", "#dc2626");
            path.setAttribute("stroke-dasharray", "4 3");
            path.setAttribute("stroke-width", "3");
        } else if (isRealized) {
            className += " realized";
            path.setAttribute("stroke", "#ef4444");
            path.setAttribute("stroke-width", "3");
            path.removeAttribute("stroke-dasharray");
        } else {
            className += " future";
            path.setAttribute("stroke", "#0284c7");
            path.setAttribute("stroke-dasharray", "6 4");
            path.setAttribute("stroke-width", "3");
        }
        path.className.baseVal = className;

        path.addEventListener("mouseover", (e) => {
            const gapMin = (pair.gapSeconds / 60).toFixed(1);
            const reqMin = (pair.turnaroundSeconds / 60).toFixed(1);
            const statusHtml = !pair.valid
                ? `<span style="color: #dc2626; font-weight: 600;">⚠️ Violação: ${gapMin} min (Mínimo: ${reqMin} min)</span>`
                : (isRealized
                    ? `<span style="color: #ef4444; font-weight: 600;">Volta Realizada: ${gapMin} min (Mínimo: ${reqMin} min)</span>`
                    : `<span style="color: #0284c7; font-weight: 600;">Volta Futura: ${gapMin} min (Mínimo: ${reqMin} min)</span>`);

            updateTooltipPosition(e.clientX, e.clientY, `
                <strong>Volta em ${station.name} (Nível ${level + 1}):</strong><br>
                Chegada (${pair.arrivalTrip.train_code}): ${pair.arrivalTime.substring(0, 5)}<br>
                Partida (${pair.departureTrip.train_code}): ${pair.departureTime.substring(0, 5)}<br>
                ${statusHtml}
            `);
            highlightTurnaroundChain(pair.arrivalTrip.trip_id);
        });

        path.addEventListener("mouseout", () => {
            hideTooltip();
            clearTurnaroundChainHighlight();
        });

        path.addEventListener("click", (e) => {
            e.stopPropagation();
            openTurnaroundDialog(station);
        });

        svg.appendChild(path);

        // Indicator circles at endpoint nodes
        [x1, x2].forEach(x => {
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("cx", x);
            circle.setAttribute("cy", yStation);
            circle.setAttribute("r", 3);
            let nodeClass = "turnaround-node";
            if (!pair.valid) nodeClass += " violation";
            else if (isRealized) nodeClass += " realized";
            else nodeClass += " future";
            circle.className.baseVal = nodeClass;
            svg.appendChild(circle);
        });
    });
}

function computeTurnaroundNextTripMap() {
    const nextTripId = {};
    computeTurnaroundPairs().forEach(pair => {
        nextTripId[pair.arrivalTrip.trip_id] = pair.departureTrip.trip_id;
    });
    return nextTripId;
}

function highlightTurnaroundChain(startTripId) {
    const nextTripId = computeTurnaroundNextTripMap();
    let currentId = startTripId;
    let hop = 0;
    const maxHops = 20;

    while (currentId && hop <= maxHops) {
        const opacity = Math.max(0.15, 1 - hop * 0.25);
        [`line-${currentId}-past`, `line-${currentId}-future`].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.opacity = opacity;
        });
        currentId = nextTripId[currentId];
        hop++;
    }
}

function clearTurnaroundChainHighlight() {
    document.querySelectorAll(".train-path-planned, .train-path-past").forEach(el => {
        el.style.opacity = "";
    });
}



// Predefined mock realized (actual) data for comparison
const mockRealizedData = [
    {
        "trip_id": "TRIP_BFU-RGS_0500",
        "direction": "BFU-RGS",
        "stops": [
            {"station": "BFU", "time": "05:03:00", "y_coord": 5860.32},
            {"station": "LUZ", "time": "05:12:00", "y_coord": 5380.32},
            {"station": "BAS", "time": "05:17:00", "y_coord": 4980.32},
            {"station": "SCS", "time": "05:32:00", "y_coord": 3860.32},
            {"station": "SAN", "time": "05:44:00", "y_coord": 2980.32},
            {"station": "MAU", "time": "05:53:00", "y_coord": 2100.32},
            {"station": "RGS", "time": "06:04:00", "y_coord": 500.32}
        ]
    }
];

// ==========================================================================
// Initialization & Loading Logic
// ==========================================================================
window.onload = function() {
    syncThemeIcon();
    loadDefaultSchedule();
    document.getElementById("chart-container").addEventListener("scroll", onChartScroll);
    setupChartPanAndWheel();
};

function loadDefaultSchedule() {
    fetch("/api/schedule")
        .then(response => {
            if (!response.ok) throw new Error("Server returned " + response.status);
            return response.json();
        })
        .then(data => {
            initSchedule(data);
            connectLiveUpdates();
            loadLookbackSetting();
            loadAutoRegulationSetting();
            startAutoScrollClock();

        })
        .catch(err => {
            console.error("Could not reach the schedule server.", err);
            document.getElementById("chart-container").innerHTML =
                '<p style="padding: 40px; color: var(--text-secondary);">Não foi possível conectar ao servidor. Verifique se o backend está rodando.</p>';
        });
}

function initSchedule(data) {
    if (Array.isArray(data)) {
        appState.trips = JSON.parse(JSON.stringify(data));
        appState.stationTurnarounds = {};
        appState.interdictions = [];
    } else {
        appState.trips = data.trips || [];
        appState.stationTurnarounds = data.station_turnarounds || {};
        appState.interdictions = data.interdictions || [];
    }
    renderApp();
}

function applyTripUpdate(updatedTrip) {
    const idx = appState.trips.findIndex(t => t.trip_id === updatedTrip.trip_id);
    if (idx >= 0) {
        appState.trips[idx] = updatedTrip;
    } else {
        appState.trips.push(updatedTrip);
    }
    renderApp();
}

// Refetch the authoritative schedule and redraw. Shared by the schedule_reset handler,
// the drag-rejection recovery path, and the post-drag drain of deferred live updates.
function reloadScheduleFromServer() {
    return fetch("/api/schedule")
        .then(response => {
            if (!response.ok) throw new Error("Server returned " + response.status);
            return response.json();
        })
        .then(data => {
            appState.trips = data.trips;
            appState.stationTurnarounds = data.station_turnarounds || {};
            appState.interdictions = data.interdictions || [];
            renderApp();
        })
        .catch(err => {
            console.error("Could not refresh the schedule from the server.", err);
        });
}


function connectLiveUpdates() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        const knownTypes = ["trip_updated", "schedule_reset", "interdiction_changed", "interdiction_deleted"];
        if (!knownTypes.includes(message.type)) return;

        // Any re-render rebuilds the entire SVG, detaching the circle element the active
        // drag holds in dragNode.element along with the listeners bound to the old SVG —
        // the gesture then visually jumps out from under the dispatcher. So defer *every*
        // update while a drag is in flight, not just ones for the trip being dragged, and
        // reconcile with the server once the gesture's own round-trip completes.
        if (appState.dragNode) {
            appState.pendingRerender = true;
            return;
        }

        if (message.type === "trip_updated") {
            applyTripUpdate(message.trip);
        } else {
            reloadScheduleFromServer();
        }
    };

    socket.onclose = () => {
        setTimeout(connectLiveUpdates, 3000);
    };
}


function loadLookbackSetting() {
    fetch("/api/settings/edit-lookback-minutes")
        .then(response => response.json())
        .then(data => {
            appState.editLookbackMinutes = data.edit_lookback_minutes;
        });
}

function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        let data;
        try {
            data = JSON.parse(e.target.result);
        } catch (err) {
            alert("Erro ao ler JSON: Formato inválido.");
            return;
        }

        const tripsPayload = Array.isArray(data) ? data : (data.trips || []);
        if (!tripsPayload.length) {
            alert("O arquivo fornecido não contém viagens válidas.");
            return;
        }

        fetch("/api/template/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(tripsPayload),
        })
            .then(response => {
                if (!response.ok) return response.json().then(b => Promise.reject(new Error(b.detail || response.statusText)));
                return response.json();
            })
            .then(() => fetch("/api/schedule"))
            .then(response => response.json())
            .then(scheduleData => {
                initSchedule(scheduleData);
                alert(`Grade padrão importada com sucesso (${scheduleData.trips ? scheduleData.trips.length : 0} viagens).`);
            })
            .catch(err => {
                alert("Não foi possível importar a grade: " + err.message);
            });
    };
    reader.readAsText(file);
}

// ==========================================================================
// Render Application
// ==========================================================================
function renderApp() {
    renderTrainLists();
    renderChart();
}

function renderTrainListPanel(listElementId, badgeElementId, trips) {
    const listElement = document.getElementById(listElementId);
    listElement.innerHTML = "";

    document.getElementById(badgeElementId).textContent = `${trips.length} Trens`;

    trips.forEach(trip => {
        const li = document.createElement("li");
        li.className = `train-item ${appState.selectedTripId === trip.trip_id ? 'selected' : ''}`;
        li.onclick = () => selectTrip(trip.trip_id);

        const startStation = trip.stops[0].station;
        const endStation = trip.stops[trip.stops.length - 1].station;

        li.innerHTML = `
            <div class="train-info">
                <span class="train-code-label">${trip.train_code}</span>
                <span class="train-route-label">${startStation} ➔ ${endStation} (${trip.direction})</span>
            </div>
            <span class="train-time-label">${trip.start_time.substring(0, 5)}</span>
        `;
        listElement.appendChild(li);
    });
}

function renderTrainLists() {
    renderTrainListPanel("train-list-odd", "train-count-odd", getOddTrips());
    renderTrainListPanel("train-list-even", "train-count-even", getEvenTrips());
    filterTrainList("odd");
    filterTrainList("even");
}

function getFilteredTrips() {
    return appState.trips.filter(trip => {
        // If unified line 710, show all trips
        if (appState.selectedLine === "Line 710") return true;
        
        // Otherwise filter by direction/stops matching line stations
        const lineStations = stations[appState.selectedLine].map(s => s.id);
        const hasStart = lineStations.includes(trip.stops[0].station);
        const hasEnd = lineStations.includes(trip.stops[trip.stops.length - 1].station);
        return hasStart && hasEnd;
    });
}

function getOddTrips() {
    const referenceTime = getReferenceTime();
    return getFilteredTrips()
        .filter(trip => trip.train_code.startsWith("P"))
        .filter(trip => isTripInTransitAt(trip, referenceTime))
        .sort((a, b) => trainNumber(a.train_code) - trainNumber(b.train_code));
}

function getEvenTrips() {
    const referenceTime = getReferenceTime();
    return getFilteredTrips()
        .filter(trip => !trip.train_code.startsWith("P"))
        .filter(trip => isTripInTransitAt(trip, referenceTime))
        .sort((a, b) => trainNumber(a.train_code) - trainNumber(b.train_code));
}

function switchLine(lineType) {
    appState.selectedLine = lineType;
    appState.selectedTripId = null;
    
    // Toggle active tab class
    document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
    if (lineType === "Line 10") document.getElementById("btn-l10").classList.add("active");
    if (lineType === "Line 7") document.getElementById("btn-l7").classList.add("active");
    if (lineType === "Line 710") document.getElementById("btn-l710").classList.add("active");
    
    renderApp();
}

function selectTrip(tripId) {
    appState.selectedTripId = appState.selectedTripId === tripId ? null : tripId;
    renderApp();
}

// ==========================================================================
// Chart Rendering (SVG Generation)
// ==========================================================================
function renderChart() {
    const container = document.getElementById("chart-container");
    const oldScrollLeft = container.scrollLeft;
    container.innerHTML = ""; // Clear
    // The old preview <rect> (if any) was just discarded along with the container's
    // previous contents -- drop the stale reference so the next drag move recreates it.
    _interdictionPreviewRect = null;

    // Create SVG element
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", CHART_WIDTH);
    svg.setAttribute("height", CHART_HEIGHT);
    svg.setAttribute("id", "train-chart-svg");

    // Attach general mouse up/move listener to SVG for dragging
    svg.addEventListener("mousemove", onNodeDrag);
    svg.addEventListener("mousemove", onInterdictionDragPreview);
    svg.addEventListener("mouseup", onNodeDragEnd);
    svg.addEventListener("mouseleave", onNodeDragEnd);
    svg.addEventListener("click", onChartClickForInterdiction);
    svg.addEventListener("contextmenu", (e) => {
        if (appState.interdictionCreationMode) return;
        e.preventDefault();
        const rect = svg.getBoundingClientRect();
        const svgX = e.clientX - rect.left;
        const svgY = e.clientY - rect.top;
        const point = { time: xToTime(svgX), y: svgYToDxfY(svgY) };
        showContextMenu(e.clientX, e.clientY, [
            { label: "🚧 Interditar via", onClick: () => startInterdictionDrag(point) },
        ]);
    });

    drawGrid(svg);
    drawTrainPaths(svg);
    drawTurnaroundConnectors(svg);
    drawInterdictions(svg);

    
    container.appendChild(svg);
    container.scrollLeft = oldScrollLeft;
}

function drawGrid(svg) {
    const lineStations = stations[appState.selectedLine];
    
    // 1. Draw station horizontal lines
    const nowX = timeToX(getReferenceTime());
    lineStations.forEach(station => {
        const y = dxfYToSvg(station.y_dxf, appState.selectedLine);
        
        // Horizontal line
        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", MARGIN_LEFT);
        line.setAttribute("y1", y);
        line.setAttribute("x2", CHART_WIDTH - MARGIN_RIGHT);
        line.setAttribute("y2", y);
        line.className.baseVal = "station-grid-line";
        line.addEventListener("click", () => openTurnaroundDialog(station));
        svg.appendChild(line);

        // Floating station name label pinned to the vertical hour/now line
        const floatingLabel = document.createElementNS(SVG_NS, "text");
        floatingLabel.setAttribute("x", nowX);
        floatingLabel.setAttribute("y", y - 4);
        floatingLabel.setAttribute("text-anchor", "middle");
        floatingLabel.className.baseVal = "floating-station-label";
        floatingLabel.textContent = station.id;
        svg.appendChild(floatingLabel);
        
        // Station sigla — left margin
        const label = document.createElementNS(SVG_NS, "text");
        label.setAttribute("x", MARGIN_LEFT - 15);
        label.setAttribute("y", y + 4);
        label.setAttribute("text-anchor", "end");
        label.className.baseVal = "station-label";
        label.textContent = station.id;
        svg.appendChild(label);

        // Station sigla — right margin
        const labelRight = document.createElementNS(SVG_NS, "text");
        labelRight.setAttribute("x", CHART_WIDTH - MARGIN_RIGHT + 15);
        labelRight.setAttribute("y", y + 4);
        labelRight.setAttribute("text-anchor", "start");
        labelRight.className.baseVal = "station-label";
        labelRight.textContent = station.id;
        svg.appendChild(labelRight);
    });
    
    // 2. Draw vertical time grid lines (every hour and every 10 minutes)
    // h runs past 24 up to END_HOUR (28) to reach the service day's 04:00-next-day
    // right edge; displayHour wraps it back to a real clock hour for the label text,
    // while the X position uses the unwrapped offset (see serviceOffsetMinutesToX).
    for (let h = START_HOUR; h <= END_HOUR; h++) {
        const displayHour = h % 24;
        const x = serviceOffsetMinutesToX((h - START_HOUR) * 60);

        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", x);
        line.setAttribute("y1", MARGIN_TOP);
        line.setAttribute("x2", x);
        line.setAttribute("y2", CHART_HEIGHT - MARGIN_BOTTOM);
        line.className.baseVal = "grid-line-major";
        svg.appendChild(line);

        // Hour label text at top and bottom
        const topLabel = document.createElementNS(SVG_NS, "text");
        topLabel.setAttribute("x", x);
        topLabel.setAttribute("y", MARGIN_TOP - 15);
        topLabel.setAttribute("text-anchor", "middle");
        topLabel.className.baseVal = "time-label";
        topLabel.textContent = `${String(displayHour).padStart(2, '0')}:00`;
        svg.appendChild(topLabel);

        const bottomLabel = document.createElementNS(SVG_NS, "text");
        bottomLabel.setAttribute("x", x);
        bottomLabel.setAttribute("y", CHART_HEIGHT - MARGIN_BOTTOM + 25);
        bottomLabel.setAttribute("text-anchor", "middle");
        bottomLabel.className.baseVal = "time-label";
        bottomLabel.textContent = `${String(displayHour).padStart(2, '0')}:00`;
        svg.appendChild(bottomLabel);

        // Draw minute minor lines (every 10 minutes)
        if (h < END_HOUR) {
            for (let m = 10; m < 60; m += 10) {
                const xm = serviceOffsetMinutesToX((h - START_HOUR) * 60 + m);

                const minLine = document.createElementNS(SVG_NS, "line");
                minLine.setAttribute("x1", xm);
                minLine.setAttribute("y1", MARGIN_TOP);
                minLine.setAttribute("x2", xm);
                minLine.setAttribute("y2", CHART_HEIGHT - MARGIN_BOTTOM);
                minLine.className.baseVal = "grid-line-minor";
                svg.appendChild(minLine);
            }
        }
    }
}

function getStopY(stop, lineKey) {
    if (!stop) return 0;
    if (stop.y_coord != null) {
        return dxfYToSvg(stop.y_coord, lineKey);
    }
    const lineStations = stations[lineKey || appState.selectedLine];
    if (lineStations && stop.station) {
        const st = lineStations.find(s => s.id === stop.station);
        if (st) return dxfYToSvg(st.y_dxf, lineKey);
    }
    return 0;
}

function splitTripAtNow(trip, selectedLine) {
    const nowX = timeToX(getReferenceTime());
    const stopsWithCoords = (trip.stops || []).map(stop => ({
        x: timeToX(stop.time),
        y: getStopY(stop, selectedLine)
    }));

    const pastPoints = [];
    const futurePoints = [];

    for (let i = 0; i < stopsWithCoords.length; i++) {
        const p = stopsWithCoords[i];
        if (p.x <= nowX) {
            pastPoints.push(p);
        } else {
            if (pastPoints.length > 0 && futurePoints.length === 0) {
                const prev = stopsWithCoords[i - 1];
                const t = (nowX - prev.x) / (p.x - prev.x);
                const interpY = prev.y + t * (p.y - prev.y);
                const split = { x: nowX, y: interpY };
                pastPoints.push(split);
                futurePoints.push(split);
            }
            futurePoints.push(p);
        }
    }

    return { pastPoints, futurePoints };
}

function drawTrainPaths(svg) {
    const lineTrips = getFilteredTrips();
    
    // Draw planned train paths
    lineTrips.forEach(trip => {
        const isSelected = appState.selectedTripId === trip.trip_id;
        const { first, last } = activeStopRange(trip);

        if (first > 0 || last < trip.stops.length - 1) {
            const suppressedBefore = trip.stops.slice(0, Math.max(0, first + 1));
            const suppressedAfter = trip.stops.slice(Math.max(0, last), trip.stops.length);
            [suppressedBefore, suppressedAfter].forEach(segment => {
                if (segment.length < 2) return;
                const points = segment.map(s => `${timeToX(s.time)},${getStopY(s, appState.selectedLine)}`).join(" ");
                const dashed = document.createElementNS(SVG_NS, "polyline");
                dashed.setAttribute("points", points);
                dashed.className.baseVal = "train-path-suppressed";
                svg.appendChild(dashed);
            });
        }

        const activeStops = (first <= last && first >= 0) ? trip.stops.slice(first, last + 1) : [];
        // A held stop's arrival_time differs from its departure_time (the train waited on
        // the platform between them) -- insert that stop twice, once at arrival_time and
        // once at departure_time, so the polyline draws a flat wait on the station's own
        // grid line instead of jumping straight from arrival to the (later) departure.
        // Untouched stops always have arrival_time === time (this app never modeled dwell
        // before interdiction holds), so this is a no-op duplicate-free pass-through for them.
        const stopsWithWait = [];
        activeStops.forEach(stop => {
            if (stop.arrival_time && stop.arrival_time !== stop.time) {
                stopsWithWait.push({ ...stop, time: stop.arrival_time });
            }
            stopsWithWait.push(stop);
        });
        const activeTrip = { ...trip, stops: stopsWithWait };
        let { pastPoints, futurePoints } = splitTripAtNow(activeTrip, appState.selectedLine);

        function attachTripLineEvents(polyline) {
            polyline.addEventListener("mouseover", () => showHoverNodeLabels(trip));
            polyline.addEventListener("mousemove", (e) => showTripTooltipDynamic(e, trip));
            polyline.addEventListener("mouseout", () => { hideTooltip(); clearHoverNodeLabels(); });
            polyline.addEventListener("click", () => selectTrip(trip.trip_id));
            polyline.addEventListener("mouseenter", () => highlightTurnaroundChain(trip.trip_id));
            polyline.addEventListener("mouseleave", () => clearTurnaroundChainHighlight());
        }

        if (pastPoints.length >= 2) {
            const pastLine = document.createElementNS(SVG_NS, "polyline");
            pastLine.setAttribute("points", pastPoints.map(p => `${p.x},${p.y}`).join(" "));
            pastLine.setAttribute("id", `line-${trip.trip_id}-past`);
            pastLine.setAttribute("stroke", "#ef4444");
            pastLine.setAttribute("stroke-width", "2.5");
            pastLine.setAttribute("fill", "none");
            pastLine.className.baseVal = "train-path-past";
            attachTripLineEvents(pastLine);
            svg.appendChild(pastLine);
        }

        if (futurePoints.length >= 2) {
            const futureLine = document.createElementNS(SVG_NS, "polyline");
            futureLine.setAttribute("points", futurePoints.map(p => `${p.x},${p.y}`).join(" "));
            futureLine.setAttribute("id", `line-${trip.trip_id}-future`);
            futureLine.setAttribute("stroke", "#0284c7");
            futureLine.setAttribute("stroke-dasharray", "6 4");
            futureLine.setAttribute("stroke-width", "2");
            futureLine.setAttribute("fill", "none");
            futureLine.className.baseVal = `train-path-planned ${isSelected ? 'highlighted' : ''}`;
            attachTripLineEvents(futureLine);
            svg.appendChild(futureLine);
        }

        // Wide transparent hit area on top of visible polylines for easier mouse targeting
        const hitArea = document.createElementNS(SVG_NS, "polyline");
        hitArea.setAttribute("points", stopsWithWait.map(stop =>
            `${timeToX(stop.time)},${getStopY(stop, appState.selectedLine)}`
        ).join(" "));
        hitArea.className.baseVal = "train-hit-area";
        attachTripLineEvents(hitArea);
        svg.appendChild(hitArea);

        // If selected, draw interactive handles/circles
        if (isSelected) {
            trip.stops.forEach((stop, stopIdx) => {
                const isSuppressed = stopIdx < first || stopIdx > last;
                const px = timeToX(stop.time);
                const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
                
                const circle = document.createElementNS(SVG_NS, "circle");
                circle.setAttribute("cx", px);
                circle.setAttribute("cy", py);
                circle.setAttribute("r", 5);
                circle.setAttribute("id", `node-${trip.trip_id}-${stopIdx}`);

                const nowMinutes = dateToServiceMinutes(new Date());
                const stopMinutes = timeStrToServiceMinutes(stop.time);
                const isLocked = (nowMinutes - stopMinutes) > appState.editLookbackMinutes;

                circle.className.baseVal = isSuppressed ? "time-node suppressed" : (isLocked ? "time-node locked" : "time-node");
                if (!isLocked && !isSuppressed) {
                    circle.addEventListener("mousedown", (e) => onNodeDragStart(e, trip.trip_id, stopIdx));
                }
                circle.addEventListener("mouseover", (e) => showNodeTooltip(e, stop, trip));
                circle.addEventListener("mouseout", hideTooltip);
                
                const violatedPair = computeTurnaroundPairs().find(p =>
                    p.departureTrip.trip_id === trip.trip_id && !p.valid
                    && effectiveFirstStop(trip).station === stop.station
                );

                circle.addEventListener("contextmenu", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const menuItems = [
                        { label: "Suprimir a partir daqui", onClick: () => confirmSuppressFrom(trip, stop) },
                    ];
                    if (stopIdx === (trip.active_first_seq || 0)) {
                        menuItems.push({ label: "Alterar partida", onClick: () => startDepartFromMode(trip) });
                    }
                    if (violatedPair) {
                        menuItems.push({ label: "Regular", onClick: () => applyRegulation(violatedPair.arrivalTrip.trip_id, violatedPair.stationId) });
                    }
                    showContextMenu(e.clientX, e.clientY, menuItems);
                });


                circle.addEventListener("click", (e) => {
                    if (!appState.departFromMode || appState.departFromMode.tripId !== trip.trip_id) return;
                    e.stopPropagation();
                    const targetStationId = stop.station;
                    appState.departFromMode = null;
                    const chartSvg = document.getElementById("train-chart-svg");
                    if (chartSvg) chartSvg.style.cursor = "default";

                    const isLastStop = (stopIdx === trip.stops.length - 1);
                    const title = isLastStop ? "Cancelar Viagem" : "Alterar Partida da Viagem";
                    const message = isLastStop
                        ? `Deseja cancelar a viagem ${trip.train_code} inteira?`
                        : `Deseja alterar o início da viagem ${trip.train_code} para a estação ${targetStationId}, cancelando o trecho anterior?`;

                    showConfirmDialog({
                        title,
                        message,
                        onConfirm: () => {
                            const endpoint = isLastStop
                                ? `/api/trips/${encodeURIComponent(trip.trip_id)}/suppress-from/${encodeURIComponent(trip.stops[0].station)}`
                                : `/api/trips/${encodeURIComponent(trip.trip_id)}/depart-from/${encodeURIComponent(targetStationId)}`;

                            fetch(endpoint, { method: "POST" })
                                .then(r => { if (!r.ok) return r.json().then(b => Promise.reject(new Error(b.detail))); return r.json(); })
                                .then(updatedTrip => applyTripUpdate(updatedTrip))
                                .catch(err => alert("Não foi possível alterar a partida: " + err.message));
                        }
                    });
                });

                svg.appendChild(circle);
            });
        }
    });

    
    // Draw realized actual paths (if toggled)
    if (appState.showRealized) {
        mockRealizedData.forEach(actualTrip => {
            // Find corresponding planned trip to map coords
            const planned = appState.trips.find(t => t.trip_id === actualTrip.trip_id);
            if (!planned) return;
            
            let points = actualTrip.stops.map(stop => {
                const px = timeToX(stop.time);
                const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
                return `${px},${py}`;
            }).join(" ");
            
            const polyline = document.createElementNS(SVG_NS, "polyline");
            polyline.setAttribute("points", points);
            polyline.className.baseVal = "train-path-actual";
            svg.appendChild(polyline);
        });
    }
}

// ==========================================================================
// Interactive Drag & Drop + Downstream Time Propagation
// ==========================================================================
function onNodeDragStart(e, tripId, stopIdx) {
    e.preventDefault();
    e.stopPropagation();

    markUserInteraction();

    const trip = appState.trips.find(t => t.trip_id === tripId);
    if (!trip) return;

    const activeFirst = trip.active_first_seq || 0;
    const isOriginNode = (stopIdx === activeFirst);

    appState.dragNode = {
        tripId: tripId,
        stopIdx: stopIdx,
        isOriginNode: isOriginNode,
        originalX: timeToX(trip.stops[stopIdx].time),
        originalTimeMinutes: timeStrToMinutes(trip.stops[stopIdx].time),
        // Snapshot of this trip's stop times before the drag began
        dragStartStops: JSON.parse(JSON.stringify(trip.stops)),
        element: e.target,
        targetOriginStop: null,
        targetSnapElement: null
    };

    e.target.classList.add("dragging");
}

function onNodeDrag(e) {
    if (!appState.dragNode) return;

    const svg = document.getElementById("train-chart-svg");
    const rect = svg.getBoundingClientRect();

    // Find relative mouse position on SVG
    const clientX = e.clientX - rect.left;
    const clientY = e.clientY - rect.top;

    // Clear previous snap highlights
    if (appState.dragNode.targetSnapElement) {
        appState.dragNode.targetSnapElement.classList.remove("snap-target");
        appState.dragNode.targetSnapElement = null;
    }
    appState.dragNode.targetOriginStop = null;

    const trip = appState.trips.find(t => t.trip_id === appState.dragNode.tripId);
    const stopIdx = appState.dragNode.stopIdx;
    const activeFirst = trip ? (trip.active_first_seq || 0) : 0;
    const activeLast = trip ? (trip.active_last_seq !== null && trip.active_last_seq !== undefined ? trip.active_last_seq : trip.stops.length - 1) : 0;

    // Check if dragging origin node vertically/towards downstream stations
    if (appState.dragNode.isOriginNode && trip) {
        for (let i = activeFirst + 1; i <= activeLast; i++) {
            const targetStop = trip.stops[i];
            const targetY = dxfYToSvg(targetStop.y_coord, appState.selectedLine);
            const targetX = timeToX(targetStop.time);
            const distY = Math.abs(clientY - targetY);
            const distX = Math.abs(clientX - targetX);

            if (distY < 30 && distX < 70) {
                appState.dragNode.targetOriginStop = targetStop;
                appState.dragNode.targetOriginIdx = i;
                const snapEl = document.getElementById(`node-${trip.trip_id}-${i}`);
                if (snapEl) {
                    snapEl.classList.add("snap-target");
                    appState.dragNode.targetSnapElement = snapEl;
                }
                break;
            }
        }
    }

    if (appState.dragNode.targetOriginStop) {
        const targetStop = appState.dragNode.targetOriginStop;
        const isLastStop = (appState.dragNode.targetOriginIdx === trip.stops.length - 1);
        const actionText = isLastStop
            ? "Solte para CANCELAR a viagem inteira"
            : `Solte para alterar início da viagem para ${targetStop.station}`;
        updateTooltipPosition(e.clientX, e.clientY, `
            <strong>Trem:</strong> ${trip.train_code}<br>
            <span style="color: #ec4899; font-weight: 600;">${actionText}</span>
        `);
        return;
    }

    // Bound movement within grid area for standard time shift
    const newX = Math.max(MARGIN_LEFT, Math.min(CHART_WIDTH - MARGIN_RIGHT, clientX));

    // Calculate time differences
    const newTimeStr = xToTime(newX);
    const newTimeMinutes = timeStrToMinutes(newTimeStr);
    const deltaMinutes = newTimeMinutes - appState.dragNode.originalTimeMinutes;

    // Update current stop time
    trip.stops[stopIdx].time = newTimeStr;
    trip.stops[stopIdx].x_coord = newX;

    // Propagate time delta (+D minutes) to all downstream stops
    for (let i = stopIdx + 1; i < trip.stops.length; i++) {
        const originalTime = timeStrToMinutes(appState.dragNode.dragStartStops[i].time);
        const updatedTimeMinutes = originalTime + deltaMinutes;
        const updatedTimeStr = minutesToTimeStr(updatedTimeMinutes);

        trip.stops[i].time = updatedTimeStr;
        trip.stops[i].x_coord = timeToX(updatedTimeStr);
    }

    // Recalculate trip start/end time
    trip.start_time = trip.stops[0].time;
    trip.end_time = trip.stops[trip.stops.length - 1].time;

    // Redraw SVG in-place for performance
    updateSvgVisuals(trip);

    // Update tooltip
    updateTooltipPosition(e.clientX, e.clientY, `
        <strong>Trem:</strong> ${trip.train_code}<br>
        <strong>Estação:</strong> ${trip.stops[stopIdx].station}<br>
        <strong>Novo Horário:</strong> ${newTimeStr.substring(0, 5)} (${deltaMinutes >= 0 ? '+' : ''}${Math.round(deltaMinutes)} min)
    `);
}

function onNodeDragEnd(e) {
    if (!appState.dragNode) return;

    if (appState.dragNode.targetSnapElement) {
        appState.dragNode.targetSnapElement.classList.remove("snap-target");
    }

    const { tripId, stopIdx, element, targetOriginStop, targetOriginIdx, dragStartStops } = appState.dragNode;
    element.classList.remove("dragging");

    const trip = appState.trips.find(t => t.trip_id === tripId);

    if (targetOriginStop && trip) {
        // Revert temporary drag displacement in memory & SVG before showing dialog
        trip.stops = dragStartStops;
        trip.start_time = trip.stops[0].time;
        trip.end_time = trip.stops[trip.stops.length - 1].time;
        updateSvgVisuals(trip);

        appState.dragNode = null;
        hideTooltip();

        const isLastStop = (targetOriginIdx === trip.stops.length - 1);
        const title = isLastStop ? "Cancelar Viagem" : "Alterar Partida da Viagem";
        const message = isLastStop
            ? `Deseja cancelar a viagem ${trip.train_code} inteira?`
            : `Deseja alterar o início da viagem ${trip.train_code} para a estação ${targetOriginStop.station}, cancelando o trecho anterior?`;

        showConfirmDialog({
            title,
            message,
            onConfirm: () => {
                const endpoint = isLastStop
                    ? `/api/trips/${encodeURIComponent(tripId)}/suppress-from/${encodeURIComponent(trip.stops[0].station)}`
                    : `/api/trips/${encodeURIComponent(tripId)}/depart-from/${encodeURIComponent(targetOriginStop.station)}`;

                fetch(endpoint, { method: "POST" })
                    .then(response => {
                        if (!response.ok) return response.json().then(body => Promise.reject(new Error(body.detail)));
                        return response.json();
                    })
                    .then(updatedTrip => applyTripUpdate(updatedTrip))
                    .catch(err => {
                        alert("Não foi possível alterar a partida: " + err.message);
                        reloadScheduleFromServer();
                    });
            },
            onCancel: () => {
                reloadScheduleFromServer();
            }
        });
        return;
    }

    const stationId = trip.stops[stopIdx].station;
    const newTime = trip.stops[stopIdx].time;

    fetch("/api/stops/shift", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trip_id: tripId, station_id: stationId, new_time: newTime }),
    })
        .then(response => {
            if (!response.ok) return response.json().then(body => Promise.reject(new Error(body.detail)));
            return response.json();
        })
        .then(updatedTrip => {
            applyTripUpdate(updatedTrip);
        })
        .catch(err => {
            alert("Edição rejeitada pelo servidor: " + err.message);
            appState.pendingRerender = false;
            return reloadScheduleFromServer();
        })
        .finally(() => {
            if (appState.pendingRerender) {
                appState.pendingRerender = false;
                reloadScheduleFromServer();
            }
        });

    appState.dragNode = null;
    hideTooltip();
}

function updateSvgVisuals(trip) {
    const { pastPoints, futurePoints } = splitTripAtNow(trip, appState.selectedLine);

    const pastPolyline = document.getElementById(`line-${trip.trip_id}-past`);
    if (pastPolyline) {
        pastPolyline.setAttribute("points", pastPoints.map(p => `${p.x},${p.y}`).join(" "));
    }

    const futurePolyline = document.getElementById(`line-${trip.trip_id}-future`);
    if (futurePolyline) {
        futurePolyline.setAttribute("points", futurePoints.map(p => `${p.x},${p.y}`).join(" "));
    }

    trip.stops.forEach((stop, stopIdx) => {
        const px = timeToX(stop.time);
        const circle = document.getElementById(`node-${trip.trip_id}-${stopIdx}`);
        if (circle) circle.setAttribute("cx", px);
    });
}

function showHoverNodeLabels(trip) {
    const svg = document.getElementById("train-chart-svg");
    if (!svg) return;

    let group = document.getElementById("hover-node-labels");
    if (!group) {
        group = document.createElementNS(SVG_NS, "g");
        group.setAttribute("id", "hover-node-labels");
        svg.appendChild(group);
    }
    group.innerHTML = "";

    trip.stops.forEach(stop => {
        const px = timeToX(stop.time);
        const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
        const labelText = `${trip.train_code} ${stop.time.substring(0, 5)}`;

        const text = document.createElementNS(SVG_NS, "text");
        text.setAttribute("x", px + 12);
        text.setAttribute("y", py - 8);
        text.className.baseVal = "hover-node-label";
        text.textContent = labelText;
        group.appendChild(text);

        // Measured after the text node is attached, so the background rect
        // fits the actual rendered width instead of a guessed character width.
        const bbox = text.getBBox();
        const bg = document.createElementNS(SVG_NS, "rect");
        bg.setAttribute("x", bbox.x - 4);
        bg.setAttribute("y", bbox.y - 2);
        bg.setAttribute("width", bbox.width + 8);
        bg.setAttribute("height", bbox.height + 4);
        bg.setAttribute("rx", 3);
        bg.className.baseVal = "hover-node-label-bg";
        group.insertBefore(bg, text);
    });
}

function clearHoverNodeLabels() {
    const group = document.getElementById("hover-node-labels");
    if (group) group.innerHTML = "";
}

// ==========================================================================
// Tooltip & Helper Logic
// ==========================================================================
function showTripTooltip(e, trip) {
    const text = `
        <strong>Trem:</strong> ${trip.train_code}<br>
        <strong>Partida:</strong> ${trip.start_time.substring(0, 5)} (${trip.stops[0].station})<br>
        <strong>Chegada:</strong> ${trip.end_time.substring(0, 5)} (${trip.stops[trip.stops.length-1].station})
    `;
    updateTooltipPosition(e.clientX, e.clientY, text);
}

function showTripTooltipDynamic(e, trip) {
    const container = document.getElementById("chart-container");
    const rect = container.getBoundingClientRect();
    const svgX = e.clientX - rect.left + container.scrollLeft;
    const svgY = e.clientY - rect.top + container.scrollTop;

    const timeAtMouse = xToTime(svgX).substring(0, 5);

    const nearestStop = trip.stops.reduce((best, stop) => {
        const stopY = dxfYToSvg(stop.y_coord, appState.selectedLine);
        const bestY = dxfYToSvg(best.y_coord, appState.selectedLine);
        return Math.abs(svgY - stopY) < Math.abs(svgY - bestY) ? stop : best;
    }, trip.stops[0]);

    const text = `
        <strong>Trem:</strong> ${trip.train_code}<br>
        <strong>Horário:</strong> ${timeAtMouse}<br>
        <strong>Estação:</strong> ${nearestStop.station}
    `;
    updateTooltipPosition(e.clientX, e.clientY, text);
}

function showNodeTooltip(e, stop, trip) {
    const text = `
        <strong>Trem:</strong> ${trip.train_code}<br>
        <strong>Estação:</strong> ${stop.station}<br>
        <strong>Horário:</strong> ${stop.time.substring(0, 5)}
    `;
    updateTooltipPosition(e.clientX, e.clientY, text);
}

function updateTooltipPosition(clientX, clientY, innerHTML) {
    const tooltip = document.getElementById("tooltip");
    tooltip.innerHTML = innerHTML;
    tooltip.classList.remove("hidden");
    
    tooltip.style.left = `${clientX + 15}px`;
    tooltip.style.top = `${clientY + 15}px`;
}

function hideTooltip() {
    document.getElementById("tooltip").classList.add("hidden");
}

// ==========================================================================
// Sidebar Controllers (Search, Toggle Realized, Reset, Export)
// ==========================================================================
function filterTrainList(side) {
    const inputId = side === "odd" ? "search-train-odd" : "search-train-even";
    const listId = side === "odd" ? "train-list-odd" : "train-list-even";

    const query = document.getElementById(inputId).value.toLowerCase();
    const items = document.querySelectorAll(`#${listId} .train-item`);

    items.forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(query) ? "flex" : "none";
    });
}

let trainListRefreshScheduled = false;

// Re-renders both sidebar panels on the next animation frame at most once,
// even if `scroll` fires dozens of times in that frame — scroll fires very
// frequently and a full list re-render on every pixel would jank the scroll.
function scheduleTrainListRefresh() {
    if (trainListRefreshScheduled) return;
    trainListRefreshScheduled = true;
    requestAnimationFrame(() => {
        trainListRefreshScheduled = false;
        renderTrainLists();
    });
}

function onChartScroll() {
    if (!appState.isProgrammaticScroll) {
        markUserInteraction();
    }
    updateNowLineLabel();
    scheduleTrainListRefresh();
}

function loadMockRealizedData() {
    appState.showRealized = !appState.showRealized;
    
    const btn = document.getElementById("btn-mock-real");
    if (appState.showRealized) {
        btn.textContent = "📈 Ocultar Realizado";
        btn.classList.add("btn-primary");
    } else {
        btn.textContent = "📈 Mostrar Realizado";
        btn.classList.remove("btn-primary");
    }
    
    renderChart();
}

function resetToOriginal() {
    if (!appState.selectedTripId) {
        alert("Selecione um trem para resetar.");
        return;
    }
    if (!confirm("Deseja reverter este trem para a grade padrão?")) return;

    fetch(`/api/trips/${encodeURIComponent(appState.selectedTripId)}/reset`, { method: "POST" })
        .then(response => {
            if (!response.ok) throw new Error("Reset failed: " + response.status);
            return response.json();
        })
        .then(updatedTrip => {
            applyTripUpdate(updatedTrip);
        })
        .catch(err => {
            alert("Não foi possível resetar o trem: " + err.message);
        });
}

function exportData() {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(appState.trips, null, 2));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `grade_ferroviaria_L10.json`);
    dlAnchorElem.click();
}

// ==========================================================================
// Auto-Scroll Clock ("now" line stays centered; the chart moves beneath it)
// ==========================================================================
const AUTO_SCROLL_TICK_MS = 15000;
const AUTO_SCROLL_RESUME_IDLE_MS = 30000;
const AUTO_SCROLL_RESUME_CHECK_MS = 1000;

// Incremented on every centerChartOnTime() call; lets each call's cleanup
// recognize whether it's still the most recent call before clearing
// isProgrammaticScroll (see centerChartOnTime).
let centerChartCallId = 0;

// Scrolls the chart so timeStr's X position lands at the horizontal center of
// the visible viewport. Shared by "select a train" and the auto-scroll clock,
// so both always land through the same math.
function centerChartOnTime(timeStr, { smooth = true } = {}) {
    const container = document.getElementById("chart-container");
    if (!container) return;

    const x = timeToX(timeStr);
    const targetLeft = Math.max(0, x - container.clientWidth / 2);

    // Tag this call so its cleanup only clears the flag if no later call has
    // superseded it (see clearFlag below) — two centerChartOnTime calls can
    // legitimately overlap (e.g. an autoScrollTick firing while a selectTrip
    // scroll is still settling), and without this guard the earlier call's
    // fallback timeout could clear isProgrammaticScroll out from under the
    // later call's still-in-flight scroll, briefly exposing its native scroll
    // events to onChartScroll as if they were user interaction.
    const callId = ++centerChartCallId;

    appState.isProgrammaticScroll = true;
    container.scrollTo({ left: targetLeft, behavior: smooth ? "smooth" : "auto" });

    // scrollend fires once a smooth-scroll animation actually settles; without
    // it the flag would clear after the animation's first frame and every
    // remaining frame's scroll event would be misread as user interaction,
    // permanently pausing the auto-scroll clock.
    const clearFlag = () => {
        if (callId !== centerChartCallId) return; // a newer call is still in flight
        appState.isProgrammaticScroll = false;
    };
    container.addEventListener("scrollend", clearFlag, { once: true });
    // Fallback for browsers without scrollend: this container's smooth
    // scrolls never take anywhere near this long to settle. Also removes the
    // scrollend listener itself so it doesn't leak a closure per call in
    // browsers that never fire scrollend.
    setTimeout(() => {
        container.removeEventListener("scrollend", clearFlag);
        clearFlag();
    }, 1000);
}

function markUserInteraction() {
    appState.lastInteractionAt = Date.now();
    appState.autoScrollPaused = true;
}

function updateNowLineLabel() {
    const label = document.getElementById("now-line-label");
    if (label) label.textContent = getReferenceTime().substring(0, 5);
    updateFloatingStationLabels();
}

function updateFloatingStationLabels() {
    const nowX = timeToX(getReferenceTime());
    const labels = document.querySelectorAll(".floating-station-label");
    labels.forEach(lbl => {
        lbl.setAttribute("x", nowX);
    });
}

function autoScrollTick() {
    if (appState.dragNode) return;
    updateNowLineLabel();
    if (!appState.autoScrollPaused) {
        renderChart();
        centerChartOnTime(currentClockTimeStr(), { smooth: true });
    }
}

function autoScrollResumeCheck() {
    if (!appState.autoScrollPaused) return;
    if (Date.now() - appState.lastInteractionAt >= AUTO_SCROLL_RESUME_IDLE_MS) {
        appState.autoScrollPaused = false;
        if (appState.selectedTripId !== null) {
            appState.selectedTripId = null;
            renderApp();
        }
    }
}

function startAutoScrollClock() {
    centerChartOnTime(currentClockTimeStr(), { smooth: false });
    updateNowLineLabel();
    setInterval(autoScrollTick, AUTO_SCROLL_TICK_MS);
    setInterval(autoScrollResumeCheck, AUTO_SCROLL_RESUME_CHECK_MS);
}

// ==========================================================================
// Theme Management
// ==========================================================================
function toggleTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    applyTheme(isDark ? 'light' : 'dark');
}

function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('grafico-theme', theme);
    syncThemeIcon();
}

function syncThemeIcon() {
    const btn = document.getElementById('btn-theme-toggle');
    if (!btn) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    btn.textContent = isDark ? '☀️' : '🌙';
    btn.title = isDark ? 'Mudar para modo claro' : 'Mudar para modo escuro';
}

// ==========================================================================
// Chart Mouse Pan & Wheel Navigation
// ==========================================================================
let isPanning = false;
let panStartX = 0;
let panStartScrollLeft = 0;

function setupChartPanAndWheel() {
    const container = document.getElementById("chart-container");
    if (!container) return;

    container.addEventListener("scroll", () => {
        updateNowLineLabel();
    });

    container.addEventListener("mousedown", (e) => {
        // If clicking on draggable node circle or context menu, do not start canvas pan
        if (e.target.tagName.toLowerCase() === "circle" || e.target.classList.contains("time-node")) return;
        if (e.button !== 0) return; // Only left-click drag

        isPanning = true;
        panStartX = e.clientX;
        panStartScrollLeft = container.scrollLeft;
        container.classList.add("is-panning");
        markUserInteraction();
    });

    window.addEventListener("mousemove", (e) => {
        if (!isPanning) return;
        const container = document.getElementById("chart-container");
        if (!container) return;
        const dx = e.clientX - panStartX;
        container.scrollLeft = panStartScrollLeft - dx;
        markUserInteraction();
    });

    window.addEventListener("mouseup", () => {
        if (isPanning) {
            isPanning = false;
            const container = document.getElementById("chart-container");
            if (container) container.classList.remove("is-panning");
        }
    });

    container.addEventListener("wheel", (e) => {
        if (Math.abs(e.deltaY) > 0 || Math.abs(e.deltaX) > 0) {
            const scrollDelta = e.deltaX !== 0 ? e.deltaX : e.deltaY;
            container.scrollLeft += scrollDelta;
            e.preventDefault();
            markUserInteraction();
        }
    }, { passive: false });
}
