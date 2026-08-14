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
    const [h, m, s] = timeStr.split(":").map(Number);
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

// Global Application State
let appState = {
    selectedLine: "Line 10",
    trips: [],          // Working trips data
    selectedTripId: null,
    showRealized: false,
    realizedTrips: [],  // Compare track data
    dragNode: null,     // Reference to node currently being dragged
    editLookbackMinutes: 15,  // Sane default before the server value loads
    // Set when a live update arrives mid-drag; drained once the gesture commits.
    pendingRerender: false
};

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
    loadDefaultSchedule();
};

function loadDefaultSchedule() {
    fetch("/api/schedule")
        .then(response => {
            if (!response.ok) throw new Error("Server returned " + response.status);
            return response.json();
        })
        .then(data => {
            initSchedule(data.trips);
            connectLiveUpdates();
            loadLookbackSetting();
        })
        .catch(err => {
            console.error("Could not reach the schedule server.", err);
            document.getElementById("chart-container").innerHTML =
                '<p style="padding: 40px; color: var(--text-secondary);">Não foi possível conectar ao servidor. Verifique se o backend está rodando.</p>';
        });
}

function initSchedule(data) {
    appState.trips = JSON.parse(JSON.stringify(data)); // Deep clone

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
        if (message.type !== "trip_updated" && message.type !== "schedule_reset") return;

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

        fetch("/api/template/import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        })
            .then(response => {
                if (!response.ok) throw new Error("Import failed: " + response.status);
                return response.json();
            })
            .then(() => fetch("/api/schedule"))
            .then(response => response.json())
            .then(scheduleData => {
                initSchedule(scheduleData.trips);
                alert(`Grade padrão importada com sucesso.`);
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
    renderTrainList();
    renderChart();
}

function renderTrainList() {
    const listElement = document.getElementById("train-list");
    listElement.innerHTML = "";
    
    const lineTrips = getFilteredTrips();
    document.getElementById("train-count").textContent = `${lineTrips.length} Trens`;
    
    lineTrips.forEach(trip => {
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
    
    // Scroll chart horizontally to show selected train
    if (appState.selectedTripId) {
        const trip = appState.trips.find(t => t.trip_id === tripId);
        if (trip) {
            const startX = timeToX(trip.start_time);
            const container = document.getElementById("chart-container");
            container.scrollTo({
                left: startX - container.clientWidth / 2,
                behavior: 'smooth'
            });
        }
    }
}

// ==========================================================================
// Chart Rendering (SVG Generation)
// ==========================================================================
function renderChart() {
    const container = document.getElementById("chart-container");
    container.innerHTML = ""; // Clear
    
    // Create SVG element
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", CHART_WIDTH);
    svg.setAttribute("height", CHART_HEIGHT);
    svg.setAttribute("id", "train-chart-svg");
    
    // Attach general mouse up/move listener to SVG for dragging
    svg.addEventListener("mousemove", onNodeDrag);
    svg.addEventListener("mouseup", onNodeDragEnd);
    svg.addEventListener("mouseleave", onNodeDragEnd);
    
    drawGrid(svg);
    drawTrainPaths(svg);
    
    container.appendChild(svg);
}

function drawGrid(svg) {
    const lineStations = stations[appState.selectedLine];
    
    // 1. Draw station horizontal lines
    lineStations.forEach(station => {
        const y = dxfYToSvg(station.y_dxf, appState.selectedLine);
        
        // Horizontal line
        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", MARGIN_LEFT);
        line.setAttribute("y1", y);
        line.setAttribute("x2", CHART_WIDTH - MARGIN_RIGHT);
        line.setAttribute("y2", y);
        line.className.baseVal = "station-grid-line";
        svg.appendChild(line);
        
        // Station name label (fixed on left)
        const label = document.createElementNS(SVG_NS, "text");
        label.setAttribute("x", MARGIN_LEFT - 15);
        label.setAttribute("y", y + 4);
        label.setAttribute("text-anchor", "end");
        label.className.baseVal = "station-label";
        label.textContent = station.name;
        svg.appendChild(label);
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

function drawTrainPaths(svg) {
    const lineTrips = getFilteredTrips();
    
    // Draw planned train paths
    lineTrips.forEach(trip => {
        const isSelected = appState.selectedTripId === trip.trip_id;
        
        // Compute path string
        let points = trip.stops.map(stop => {
            const px = timeToX(stop.time);
            const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
            return `${px},${py}`;
        }).join(" ");
        
        const polyline = document.createElementNS(SVG_NS, "polyline");
        polyline.setAttribute("points", points);
        polyline.setAttribute("id", `line-${trip.trip_id}`);
        polyline.className.baseVal = `train-path-planned ${isSelected ? 'highlighted' : ''}`;
        
        // Show tooltip on hover
        polyline.addEventListener("mouseover", (e) => showTripTooltip(e, trip));
        polyline.addEventListener("mouseout", hideTooltip);
        polyline.addEventListener("click", () => selectTrip(trip.trip_id));
        
        svg.appendChild(polyline);
        
        // If selected, draw interactive handles/circles
        if (isSelected) {
            trip.stops.forEach((stop, stopIdx) => {
                const px = timeToX(stop.time);
                const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
                
                const circle = document.createElementNS(SVG_NS, "circle");
                circle.setAttribute("cx", px);
                circle.setAttribute("cy", py);
                circle.setAttribute("r", 5);
                // Stable id so updateSvgVisuals can look circles up by (trip, stop)
                // instead of assuming SVG document order matches trip.stops order.
                circle.setAttribute("id", `node-${trip.trip_id}-${stopIdx}`);

                // Service-day minutes on both sides so a stop just after midnight isn't
                // mistaken for one ~24h in the past (or the check silently bypassed).
                // Matches the server-side lookback check in service.py:shift_stop.
                const nowMinutes = dateToServiceMinutes(new Date());
                const stopMinutes = timeStrToServiceMinutes(stop.time);
                const isLocked = (nowMinutes - stopMinutes) > appState.editLookbackMinutes;

                circle.className.baseVal = isLocked ? "time-node locked" : "time-node";
                if (!isLocked) {
                    circle.addEventListener("mousedown", (e) => onNodeDragStart(e, trip.trip_id, stopIdx));
                }
                circle.addEventListener("mouseover", (e) => showNodeTooltip(e, stop, trip));
                circle.addEventListener("mouseout", hideTooltip);
                
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
    
    const trip = appState.trips.find(t => t.trip_id === tripId);
    if (!trip) return;
    
    appState.dragNode = {
        tripId: tripId,
        stopIdx: stopIdx,
        originalX: timeToX(trip.stops[stopIdx].time),
        originalTimeMinutes: timeStrToMinutes(trip.stops[stopIdx].time),
        // Snapshot of this trip's stop times before the drag began, used to compute
        // downstream propagation deltas during the gesture (server is authoritative on release).
        dragStartStops: JSON.parse(JSON.stringify(trip.stops)),
        element: e.target
    };
    
    e.target.classList.add("dragging");
}

function onNodeDrag(e) {
    if (!appState.dragNode) return;
    
    const svg = document.getElementById("train-chart-svg");
    const rect = svg.getBoundingClientRect();
    
    // Find relative mouse position on SVG
    const clientX = e.clientX - rect.left;
    
    // Bound movement within grid area
    const newX = Math.max(MARGIN_LEFT, Math.min(CHART_WIDTH - MARGIN_RIGHT, clientX));
    
    // Calculate time differences
    const newTimeStr = xToTime(newX);
    const newTimeMinutes = timeStrToMinutes(newTimeStr);
    const deltaMinutes = newTimeMinutes - appState.dragNode.originalTimeMinutes;
    
    const trip = appState.trips.find(t => t.trip_id === appState.dragNode.tripId);
    const stopIdx = appState.dragNode.stopIdx;
    
    // Update current stop time
    trip.stops[stopIdx].time = newTimeStr;
    trip.stops[stopIdx].x_coord = newX;
    
    // Propagate time delta (+D minutes) to all downstream stops
    for (let i = stopIdx + 1; i < trip.stops.length; i++) {
        // Load pre-drag stop reference (captured at drag start, since originalTrips no
        // longer exists now that the server is the source of truth after each commit)
        const originalTime = timeStrToMinutes(appState.dragNode.dragStartStops[i].time);

        // Propagate forward
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

    const { tripId, stopIdx, element } = appState.dragNode;
    element.classList.remove("dragging");

    const trip = appState.trips.find(t => t.trip_id === tripId);
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
            // This reload already reconciles with the server, so nothing is left to drain.
            appState.pendingRerender = false;
            return reloadScheduleFromServer();
        })
        .finally(() => {
            // Other dispatchers' updates that arrived mid-gesture were held back; now that
            // this drag has committed, take the server's current state for everything.
            if (appState.pendingRerender) {
                appState.pendingRerender = false;
                reloadScheduleFromServer();
            }
        });

    appState.dragNode = null;
    hideTooltip();
}

function updateSvgVisuals(trip) {
    // Redraw polyline points
    const pointsStr = trip.stops.map(stop => {
        const px = timeToX(stop.time);
        const py = dxfYToSvg(stop.y_coord, appState.selectedLine);
        return `${px},${py}`;
    }).join(" ");
    
    const polyline = document.getElementById(`line-${trip.trip_id}`);
    if (polyline) polyline.setAttribute("points", pointsStr);

    // Update node positions (circles), looked up by the stable id assigned in
    // drawTrainPaths rather than by position in the SVG's circle list.
    trip.stops.forEach((stop, stopIdx) => {
        const px = timeToX(stop.time);
        const circle = document.getElementById(`node-${trip.trip_id}-${stopIdx}`);
        if (circle) {
            circle.setAttribute("cx", px);
        }
    });
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
function filterTrains() {
    const query = document.getElementById("search-train").value.toLowerCase();
    const items = document.querySelectorAll(".train-item");
    
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        if (text.includes(query)) {
            item.style.display = "flex";
        } else {
            item.style.display = "none";
        }
    });
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
