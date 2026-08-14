# Live Chart Centering & Sidebar Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Marey chart auto-center on the current time (pausing during manual interaction, resuming after 30s idle), split the sidebar train list into two parity-grouped panels flanking the chart that live-filter to trains currently in transit at the centered time, and show a code+time label at every stop node when hovering any train's line.

**Architecture:** A "reference time" is *derived* on demand from wherever the chart's horizontal center is currently scrolled to (`xToTime(scrollLeft + clientWidth/2)`), never stored as separate state. A 15s interval recenters the chart on the real clock time unless the operator interacted (dragged a node, or scrolled the chart) in the last 30s. Both sidebar panels and the "now" line's label recompute from that same derived reference time on every scroll event and every tick, so they always agree with whatever the chart is currently showing — whether that's real "now" or a spot the operator scrolled to manually. The "now" line itself is a `position: absolute` overlay sibling to the scrollable chart container (not a child of it), so it never moves on screen regardless of scroll position.

**Tech Stack:** Vanilla JS/HTML/CSS (no build step, no framework) — unchanged from the rest of the frontend. No backend changes; all data this needs (`train_code`, `start_time`, `end_time`, `stops[].time`) is already returned by `GET /api/schedule`.

**Spec:** `docs/superpowers/specs/2026-08-14-live-chart-and-sidebar-design.md`

## Global Constraints

- Frontend-only change. Do not touch `backend/`.
- This repo has no automated frontend test harness (`frontend/tests/manual_test.md` says so explicitly). Verify every step with `node --check frontend/src/app.js`; where a step introduces non-trivial math (time/scroll conversions), verify it with a standalone Node script the same way the service-day axis fix and the train_code assignment were verified earlier in this project — extract the relevant functions, exercise them with concrete inputs, print pass/fail, then delete the scratch script. Add a scenario to `frontend/tests/manual_test.md` at the end of each task.
- Auto-scroll pause triggers are exactly two: an active node drag (`onNodeDragStart`) and a genuine (non-programmatic) `scroll` event on `#chart-container`. Selecting a trip from the sidebar also scrolls the chart but must **not** pause auto-scroll — this is a deliberate, explicit scoping decision (see spec).
- Auto-scroll tick interval is exactly `15000` ms. Resume-after-idle threshold is exactly `30000` ms. Hardcode these; do not add settings/config for them.
- The "now" line's on-screen position never changes — it is always the horizontal center of `#chart-viewport`. Only the chart content underneath it and the line's label text change.
- Sidebar split is strict prefix parity: `train_code` starting with `"P"` → left/odd panel; anything else (`"R"` or `"M"`) → right/even panel. Sort each panel by the numeric suffix of `train_code` ascending.
- `getFilteredTrips()` (existing function, filters by the Linha 10/7/710 tab) still governs what the *chart* draws — unchanged. The new in-transit filter applies only to the two sidebar panels, layered on top of `getFilteredTrips()`.

---

## Task 1: Split sidebar into odd/even panels with live in-transit filtering

**Files:**
- Modify: `frontend/src/index.html`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/app.js`
- Modify: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `timeToX`/`xToTime` (existing, `app.js:39-55`), `timeStrToServiceMinutes` (existing, `app.js:76-79`), `appState.trips` (existing), `getFilteredTrips()` (existing, `app.js:346-357`).
- Produces: `getReferenceTime()`, `currentClockTimeStr()`, `isTripInTransitAt(trip, referenceTimeStr)`, `trainNumber(trainCode)`, `getOddTrips()`, `getEvenTrips()`, `renderTrainListPanel(listElementId, badgeElementId, trips)`, `renderTrainLists()`, `filterTrainList(side)`, `scheduleTrainListRefresh()`, `onChartScroll()` — `onChartScroll` and `scheduleTrainListRefresh` are extended (not replaced) by Task 2.

- [ ] **Step 1: Replace the single sidebar with two panels in `index.html`**

Replace the entire `<main class="main-content">...</main>` block with:

```html
        <main class="main-content">
            <!-- Sidebar Left: odd-numbered trains (destino Barra Funda) -->
            <aside class="sidebar sidebar-left glass-panel">
                <div class="panel-header">
                    <h2>Sentido BFU (Ímpares)</h2>
                    <span class="badge" id="train-count-odd">0 Trens</span>
                </div>

                <div class="search-box">
                    <span class="search-icon">🔍</span>
                    <input type="text" id="search-train-odd" placeholder="Buscar trem (ex: P15)..." oninput="filterTrainList('odd')">
                </div>

                <div class="train-list-container">
                    <ul id="train-list-odd" class="train-list">
                        <!-- Populated dynamically -->
                    </ul>
                </div>
            </aside>

            <!-- Graphic Display Area -->
            <section class="graphic-area glass-panel">
                <div class="panel-header">
                    <h2>Diagrama de Horários (Gráfico de Marey)</h2>
                    <div class="legend">
                        <span class="legend-item"><span class="line-style planned-dash"></span> Planejado</span>
                        <span class="legend-item"><span class="line-style actual-solid"></span> Realizado</span>
                        <span class="legend-item"><span class="node-style"></span> Nó Arrastável</span>
                    </div>
                </div>

                <!-- SVG Scrollable Container -->
                <div class="chart-scroll-container" id="chart-container">
                    <!-- The SVG will be generated here dynamically -->
                </div>
            </section>

            <!-- Sidebar Right: even-numbered trains (destino RGS/Mauá) -->
            <aside class="sidebar sidebar-right glass-panel">
                <div class="panel-header">
                    <h2>Sentido RGS/Mauá (Pares)</h2>
                    <span class="badge" id="train-count-even">0 Trens</span>
                </div>

                <div class="search-box">
                    <span class="search-icon">🔍</span>
                    <input type="text" id="search-train-even" placeholder="Buscar trem (ex: R2)..." oninput="filterTrainList('even')">
                </div>

                <div class="train-list-container">
                    <ul id="train-list-even" class="train-list">
                        <!-- Populated dynamically -->
                    </ul>
                </div>
            </aside>
        </main>
```

Note this drops the old `.toggle-buttons` div (Mostrar Realizado / Resetar buttons) from the sidebar entirely — Step 2 adds them to the header instead.

- [ ] **Step 2: Move the toggle buttons into the header in `index.html`**

Find the `<div class="header-controls">` block and insert a new `<div class="chart-action-buttons">` between `.line-selector` and `.file-upload-wrapper`:

```html
                <div class="chart-action-buttons">
                    <button class="btn btn-secondary btn-sm" id="btn-mock-real" onclick="loadMockRealizedData()">📈 Mostrar Realizado</button>
                    <button class="btn btn-secondary btn-sm" id="btn-reset" onclick="resetToOriginal()">🔄 Resetar</button>
                </div>
```

So `.header-controls` now contains, in order: `.line-selector`, `.chart-action-buttons`, `.file-upload-wrapper`, `#btn-save`.

- [ ] **Step 3: Add the header button spacing rule to `index.css`**

Add after the `.header-controls` rule (around line 96):

```css
.chart-action-buttons {
    display: flex;
    gap: 8px;
}
```

- [ ] **Step 4: Verify the HTML/CSS loads without console errors**

Run (server must already be running per the project's `run` skill; if not, start it first):

```bash
curl -s -o /dev/null -w "status: %{http_code}\n" http://127.0.0.1:8000/
```

Expected: `status: 200`. Open the page in a browser and confirm via DevTools console that there are no errors yet (the JS below still references the old `train-list`/`search-train`/`train-count` ids at this point, so the train lists will be empty/broken until Step 5 — that's expected mid-task, not a regression to chase down).

- [ ] **Step 5: Add the reference-time and in-transit helpers to `app.js`**

Insert after `dateToServiceMinutes` (currently `app.js:81-84`, right before `minutesToTimeStr`):

```javascript
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

// True if referenceTimeStr falls within [trip.start_time, trip.end_time], in
// service-day minutes so trips crossing midnight behave the same way the
// backend's chronology/lookback checks and the drag-lock check already do.
function isTripInTransitAt(trip, referenceTimeStr) {
    const ref = timeStrToServiceMinutes(referenceTimeStr);
    const start = timeStrToServiceMinutes(trip.start_time);
    const end = timeStrToServiceMinutes(trip.end_time);
    return ref >= start && ref <= end;
}

// "P15" -> 15. Used to sort each sidebar panel by departure order (parser.py
// assigns train_code numbers in departure order already, so sorting by number
// is equivalent to sorting by start_time).
function trainNumber(trainCode) {
    return parseInt(trainCode.slice(1), 10);
}
```

- [ ] **Step 6: Add `getOddTrips`/`getEvenTrips` to `app.js`**

Insert immediately after `getFilteredTrips` (currently `app.js:346-357`):

```javascript
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
```

- [ ] **Step 7: Replace `renderTrainList` with `renderTrainListPanel`/`renderTrainLists` in `app.js`**

Replace the entire existing `renderTrainList` function (currently `app.js:320-344`):

```javascript
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
}
```

- [ ] **Step 8: Update `renderApp` to call `renderTrainLists` in `app.js`**

Replace (currently `app.js:315-318`):

```javascript
function renderApp() {
    renderTrainLists();
    renderChart();
}
```

- [ ] **Step 9: Replace `filterTrains` with `filterTrainList` in `app.js`**

Replace the entire existing `filterTrains` function (currently `app.js:747-759`):

```javascript
function filterTrainList(side) {
    const inputId = side === "odd" ? "search-train-odd" : "search-train-even";
    const listId = side === "odd" ? "train-list-odd" : "train-list-even";

    const query = document.getElementById(inputId).value.toLowerCase();
    const items = document.querySelectorAll(`#${listId} .train-item`);

    items.forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(query) ? "flex" : "none";
    });
}
```

- [ ] **Step 10: Add the live-refresh-on-scroll wiring in `app.js`**

Insert right after `filterTrainList` (the function added in Step 9):

```javascript
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
    scheduleTrainListRefresh();
}
```

- [ ] **Step 11: Attach the scroll listener once at load time in `app.js`**

Replace the existing `window.onload` (currently `app.js:183-185`):

```javascript
window.onload = function() {
    loadDefaultSchedule();
    document.getElementById("chart-container").addEventListener("scroll", onChartScroll);
};
```

- [ ] **Step 12: Verify syntax**

Run: `node --check frontend/src/app.js`
Expected: no output (clean exit).

- [ ] **Step 13: Verify the in-transit filter logic with a standalone Node script**

Create a temporary file `frontend/_verify_task1.js`:

```javascript
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'src/app.js'), 'utf8');
const idx = src.indexOf('// Station metadata');
const snippet = src.slice(0, idx) + '\nmodule.exports = { isTripInTransitAt, trainNumber, timeStrToServiceMinutes };\n';
const tmpPath = path.join(__dirname, '_task1_helpers.tmp.js');
fs.writeFileSync(tmpPath, snippet);
const { isTripInTransitAt, trainNumber } = require(tmpPath);
fs.unlinkSync(tmpPath);

function check(label, actual, expected) {
    const pass = actual === expected;
    console.log((pass ? 'PASS' : 'FAIL'), label, '->', actual, pass ? '' : `(expected ${expected})`);
}

const daytimeTrip = { start_time: '05:00:00', end_time: '05:30:00' };
check('before start', isTripInTransitAt(daytimeTrip, '04:59:00'), false);
check('at start', isTripInTransitAt(daytimeTrip, '05:00:00'), true);
check('mid-journey', isTripInTransitAt(daytimeTrip, '05:15:00'), true);
check('at end', isTripInTransitAt(daytimeTrip, '05:30:00'), true);
check('after end', isTripInTransitAt(daytimeTrip, '05:31:00'), false);

// Real midnight-crossing trip from the schedule: BFU 23:12:30 -> RGS 00:08:00
const midnightTrip = { start_time: '23:12:30', end_time: '00:08:00' };
check('midnight: before start', isTripInTransitAt(midnightTrip, '23:00:00'), false);
check('midnight: just after start', isTripInTransitAt(midnightTrip, '23:15:00'), true);
check('midnight: just after midnight, still in transit', isTripInTransitAt(midnightTrip, '00:03:00'), true);
check('midnight: at end', isTripInTransitAt(midnightTrip, '00:08:00'), true);
check('midnight: after end', isTripInTransitAt(midnightTrip, '00:10:00'), false);

check('trainNumber P15', trainNumber('P15'), 15);
check('trainNumber R2', trainNumber('R2'), 2);
check('trainNumber M248', trainNumber('M248'), 248);
```

Run: `node frontend/_verify_task1.js`
Expected: every line prefixed `PASS`. If any line says `FAIL`, fix the corresponding function before continuing.

Then delete the scratch file:

```bash
rm frontend/_verify_task1.js
```

- [ ] **Step 14: Manually verify in the browser**

With the backend server running and the real `schedule.json` imported (see `frontend/tests/manual_test.md` Scenario 1 for how to import), reload the page and confirm:
- The left panel header reads "Sentido BFU (Ímpares)" and only shows `P...` codes.
- The right panel header reads "Sentido RGS/Mauá (Pares)" and only shows `R...`/`M...` codes.
- Both panels show far fewer than 251 trains each (only ones in transit right now) — the badge count should be small (typically single digits outside rush hour, since most of the day's 251 trips aren't running at any given instant).
- Typing in the left search box only filters the left list; the right list is unaffected, and vice versa.
- "Mostrar Realizado" and "Resetar" now appear in the header, and still work (click a train in either list to select it, then click "Resetar" — it should still prompt and reset that trip).

- [ ] **Step 15: Add manual_test.md Scenario 9**

Append to `frontend/tests/manual_test.md`:

```markdown
## Cenário 9: Listas Laterais Agrupadas e Filtradas por Trânsito

1. Abra a aplicação com o `schedule.json` real importado.
2. Confirme que existem duas listas, uma de cada lado do gráfico: "Sentido BFU (Ímpares)" à esquerda mostrando só códigos `P...`, "Sentido RGS/Mauá (Pares)" à direita mostrando só `R...`/`M...`.
3. Confirme que cada lista mostra só os trens cuja viagem (partida até chegada) inclui o horário atual — não as 251 viagens do dia inteiro.
4. Role o gráfico manualmente para um horário bem diferente do atual (ex: de manhã cedo). Confirme que as duas listas se atualizam para mostrar os trens circulando naquele horário rolado, não mais no horário atual.
5. Digite um código na busca da lista esquerda (ex: "P15") e confirme que só a lista esquerda é filtrada — a direita continua mostrando todos os trens em trânsito dela.
```

- [ ] **Step 16: Commit**

```bash
git add frontend/src/index.html frontend/src/index.css frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: split sidebar into odd/even panels, live-filtered to trains in transit"
```

---

## Task 2: Auto-scroll clock — "now" line overlay, 15s recenter, pause/resume on interaction

**Files:**
- Modify: `frontend/src/index.html`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/app.js`
- Modify: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `timeToX` (existing), `getReferenceTime`/`currentClockTimeStr` (Task 1), `scheduleTrainListRefresh`/`onChartScroll` (Task 1, extended here), `onNodeDragStart` (existing, `app.js:573-592`, extended here), `selectTrip` (existing, `app.js:372-388`, refactored here to reuse the new shared helper).
- Produces: `centerChartOnTime(timeStr, options)`, `markUserInteraction()`, `updateNowLineLabel()`, `autoScrollTick()`, `autoScrollResumeCheck()`, `startAutoScrollClock()` — none of these are consumed by later tasks, but `centerChartOnTime` and `markUserInteraction` are the two hooks any future interaction-tracking feature would extend.

- [ ] **Step 1: Wrap the chart container and add the now-line overlay markup in `index.html`**

Replace the `<!-- SVG Scrollable Container -->` block inside `.graphic-area` (added in Task 1 Step 1):

```html
                <!-- Viewport wrapper: hosts the scrollable chart plus the fixed-position "now" line overlay -->
                <div class="chart-viewport" id="chart-viewport">
                    <div class="chart-scroll-container" id="chart-container">
                        <!-- The SVG will be generated here dynamically -->
                    </div>
                    <div class="now-line-overlay" id="now-line-overlay">
                        <div class="now-line"></div>
                        <div class="now-line-label" id="now-line-label">--:--</div>
                    </div>
                </div>
```

- [ ] **Step 2: Add the viewport/overlay CSS to `index.css`**

Add after the `.chart-scroll-container` rule (around line 287):

```css
.chart-viewport {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
}

.now-line-overlay {
    position: absolute;
    top: 0;
    left: 50%;
    height: 100%;
    width: 0;
    pointer-events: none;
    z-index: 10;
}

.now-line {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: 2px;
    background-color: var(--accent-highlight);
    box-shadow: 0 0 8px rgba(255, 204, 0, 0.6);
}

.now-line-label {
    position: absolute;
    top: 4px;
    left: 6px;
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 600;
    color: var(--accent-highlight);
    background-color: rgba(0, 0, 0, 0.5);
    padding: 2px 6px;
    border-radius: 4px;
    white-space: nowrap;
}
```

`.chart-viewport` becomes the flex:1 child of `.graphic-area` (previously `.chart-scroll-container` held that role directly); `.chart-scroll-container`'s existing `flex: 1` rule now applies to it as a child of `.chart-viewport` instead, filling the same space it did before. Because `.now-line-overlay` is a *sibling* of `.chart-scroll-container`, not a descendant of it, it never scrolls when the container's content does — `left: 50%` always lands on the viewport's true horizontal center.

- [ ] **Step 3: Add the new `appState` fields in `app.js`**

Replace the existing `appState` object (currently `app.js:151-161`):

```javascript
let appState = {
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
    lastInteractionAt: 0
};
```

- [ ] **Step 4: Add the auto-scroll clock functions to `app.js`**

Insert a new section after the "Sidebar Controllers" section's last function (`exportData`, currently ending at `app.js:802`), i.e. at the end of the file:

```javascript
// ==========================================================================
// Auto-Scroll Clock ("now" line stays centered; the chart moves beneath it)
// ==========================================================================
const AUTO_SCROLL_TICK_MS = 15000;
const AUTO_SCROLL_RESUME_IDLE_MS = 30000;
const AUTO_SCROLL_RESUME_CHECK_MS = 1000;

// Scrolls the chart so timeStr's X position lands at the horizontal center of
// the visible viewport. Shared by "select a train" and the auto-scroll clock,
// so both always land through the same math.
function centerChartOnTime(timeStr, { smooth = true } = {}) {
    const container = document.getElementById("chart-container");
    if (!container) return;

    const x = timeToX(timeStr);
    const targetLeft = Math.max(0, x - container.clientWidth / 2);

    appState.isProgrammaticScroll = true;
    container.scrollTo({ left: targetLeft, behavior: smooth ? "smooth" : "auto" });

    // scrollend fires once a smooth-scroll animation actually settles; without
    // it the flag would clear after the animation's first frame and every
    // remaining frame's scroll event would be misread as user interaction,
    // permanently pausing the auto-scroll clock.
    const clearFlag = () => { appState.isProgrammaticScroll = false; };
    container.addEventListener("scrollend", clearFlag, { once: true });
    // Fallback for browsers without scrollend: this container's smooth
    // scrolls never take anywhere near this long to settle.
    setTimeout(clearFlag, 1000);
}

function markUserInteraction() {
    appState.lastInteractionAt = Date.now();
    appState.autoScrollPaused = true;
}

function updateNowLineLabel() {
    const label = document.getElementById("now-line-label");
    if (label) label.textContent = getReferenceTime().substring(0, 5);
}

function autoScrollTick() {
    if (!appState.autoScrollPaused) {
        centerChartOnTime(currentClockTimeStr(), { smooth: true });
    }
}

function autoScrollResumeCheck() {
    if (!appState.autoScrollPaused) return;
    if (Date.now() - appState.lastInteractionAt >= AUTO_SCROLL_RESUME_IDLE_MS) {
        appState.autoScrollPaused = false;
    }
}

function startAutoScrollClock() {
    centerChartOnTime(currentClockTimeStr(), { smooth: false });
    updateNowLineLabel();
    setInterval(autoScrollTick, AUTO_SCROLL_TICK_MS);
    setInterval(autoScrollResumeCheck, AUTO_SCROLL_RESUME_CHECK_MS);
}
```

- [ ] **Step 5: Wire `startAutoScrollClock` into the initial load in `app.js`**

Replace the success handler inside `loadDefaultSchedule` (currently `app.js:187-203`):

```javascript
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
            startAutoScrollClock();
        })
        .catch(err => {
            console.error("Could not reach the schedule server.", err);
            document.getElementById("chart-container").innerHTML =
                '<p style="padding: 40px; color: var(--text-secondary);">Não foi possível conectar ao servidor. Verifique se o backend está rodando.</p>';
        });
}
```

`startAutoScrollClock` is called after `initSchedule`, which synchronously calls `renderApp()` → `renderChart()`, so `#chart-container` already has its real `clientWidth`/`scrollWidth` by the time the first `centerChartOnTime` call runs.

- [ ] **Step 6: Extend `onChartScroll` to mark interaction and update the line label in `app.js`**

Replace the `onChartScroll` function added in Task 1 Step 10:

```javascript
function onChartScroll() {
    if (!appState.isProgrammaticScroll) {
        markUserInteraction();
    }
    updateNowLineLabel();
    scheduleTrainListRefresh();
}
```

- [ ] **Step 7: Mark node-drag as an interaction in `app.js`**

Modify `onNodeDragStart` (currently `app.js:573-592`) — add one line at the top of the function body:

```javascript
function onNodeDragStart(e, tripId, stopIdx) {
    e.preventDefault();
    e.stopPropagation();

    markUserInteraction();

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
```

- [ ] **Step 8: Refactor `selectTrip` to reuse `centerChartOnTime` in `app.js`**

Replace `selectTrip` (currently `app.js:372-388`):

```javascript
function selectTrip(tripId) {
    appState.selectedTripId = appState.selectedTripId === tripId ? null : tripId;
    renderApp();

    // Scroll chart horizontally to show selected train. Deliberately does NOT
    // call markUserInteraction() — selecting a trip from the list is a
    // separate, pre-existing behavior from the two auto-scroll pause
    // triggers (node drag, manual chart scroll) and must not pause the clock.
    if (appState.selectedTripId) {
        const trip = appState.trips.find(t => t.trip_id === tripId);
        if (trip) {
            centerChartOnTime(trip.start_time);
        }
    }
}
```

- [ ] **Step 9: Verify syntax**

Run: `node --check frontend/src/app.js`
Expected: no output.

- [ ] **Step 10: Verify the centering math with a standalone Node script**

Create a temporary file `frontend/_verify_task2.js`:

```javascript
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'src/app.js'), 'utf8');
const idx = src.indexOf('// Station metadata');
const snippet = src.slice(0, idx) + '\nmodule.exports = { timeToX, xToTime, CHART_WIDTH, MARGIN_LEFT, USABLE_WIDTH };\n';
const tmpPath = path.join(__dirname, '_task2_helpers.tmp.js');
fs.writeFileSync(tmpPath, snippet);
const { timeToX, xToTime } = require(tmpPath);
fs.unlinkSync(tmpPath);

function check(label, actual, expected) {
    const pass = actual === expected;
    console.log((pass ? 'PASS' : 'FAIL'), label, '->', actual, pass ? '' : `(expected ${expected})`);
}

// Mirrors centerChartOnTime's target-left formula without touching the DOM.
function targetLeftFor(timeStr, clientWidth) {
    const x = timeToX(timeStr);
    return Math.max(0, x - clientWidth / 2);
}

const clientWidth = 1400; // representative viewport width
const targetLeft = targetLeftFor('12:00:00', clientWidth);
const centerX = targetLeft + clientWidth / 2;
check('centering round-trip: center lands back on the requested time', xToTime(centerX), '12:00:00');

// Near the left edge, the clamp to 0 must not push the "centered" point off
// what's actually achievable — just confirm it never goes negative.
const earlyTargetLeft = targetLeftFor('04:00:05', clientWidth);
check('never scrolls negative near the left edge', earlyTargetLeft >= 0, true);
```

Run: `node frontend/_verify_task2.js`
Expected: both lines say `PASS`.

Then delete the scratch file:

```bash
rm frontend/_verify_task2.js
```

- [ ] **Step 11: Manually verify in the browser**

Reload the page and confirm:
- On load, the chart is already scrolled so the yellow vertical "now" line sits at the horizontal center of the chart area, and its label shows the current time (HH:MM).
- Wait ~15 seconds without touching anything: the chart visibly scrolls left slightly (or stays put if within the same minute), and the line's label time advances.
- Manually scroll the chart (mouse wheel or drag the horizontal scrollbar) to a different part of the schedule. Confirm the yellow line stays fixed at the center of the viewport (it does *not* jump back), and its label now shows whatever time you scrolled to.
- Wait 30+ seconds without touching the chart. Confirm it smoothly scrolls back so the line's label shows the real current time again.
- Start dragging a node (mousedown on a circle, don't release yet in a second browser action, or just drag it a bit and release): confirm the same 30s-idle-then-resume behavior applies after finishing the drag.
- Confirm dragging a node and the resulting shift request still work exactly as before (this task didn't change any shift logic, only added the interaction-tracking side effect).

- [ ] **Step 12: Add manual_test.md Scenario 10**

Append to `frontend/tests/manual_test.md`:

```markdown
## Cenário 10: Linha do "Agora" e Auto-Scroll

1. Abra a aplicação. Confirme que a linha vertical amarela aparece centralizada na área do gráfico, com um rótulo mostrando o horário atual.
2. Sem tocar em nada, espere ~15 segundos. Confirme que o gráfico rola sozinho para a esquerda por baixo da linha (que continua no centro) e o rótulo da linha avança.
3. Role o gráfico manualmente (roda do mouse ou barra de rolagem) para um horário diferente. Confirme que a linha continua fixa no centro da tela, mas o rótulo agora mostra o horário para onde você rolou — não o horário real.
4. Pare de interagir e espere 30 segundos. Confirme que o gráfico volta a rolar sozinho até o horário real aparecer centralizado outra vez.
5. Arraste um nó de horário (edição normal) e confirme que, depois de soltar, o auto-scroll também fica pausado por 30s antes de retomar.
```

- [ ] **Step 13: Commit**

```bash
git add frontend/src/index.html frontend/src/index.css frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: auto-center chart on current time with pause/resume on interaction"
```

---

## Task 3: Hover-driven code+time labels at every stop node

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/app.js`
- Modify: `frontend/tests/manual_test.md`

**Interfaces:**
- Consumes: `timeToX`, `dxfYToSvg`, `SVG_NS` (all existing), `drawTrainPaths` (existing, `app.js:490-568`, modified here).
- Produces: `showHoverNodeLabels(trip)`, `clearHoverNodeLabels()` — not consumed elsewhere.

- [ ] **Step 1: Add the hover label CSS to `index.css`**

Add after the `.time-node.locked` rule (around line 385):

```css
/* Hover Node Labels (code + time shown at every stop while hovering a line) */
.hover-node-label-bg {
    fill: rgba(0, 0, 0, 0.75);
    stroke: var(--accent-highlight);
    stroke-width: 1;
    pointer-events: none;
}

.hover-node-label {
    fill: var(--accent-highlight);
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 600;
    pointer-events: none;
}
```

- [ ] **Step 2: Add `showHoverNodeLabels`/`clearHoverNodeLabels` to `app.js`**

Insert right after `updateSvgVisuals` (currently ending at `app.js:708`), before the "Tooltip & Helper Logic" section comment:

```javascript
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
```

`group` is created once per SVG lifetime and appended last, so it always paints on top of every polyline/circle already drawn; `renderChart()` clears the whole SVG (including this group) on every re-render, and the next hover recreates it via the `if (!group)` check — no stale references survive a re-render.

- [ ] **Step 3: Wire the hover handlers onto the polyline in `app.js`**

In `drawTrainPaths` (currently `app.js:490-568`), replace these two lines:

```javascript
        polyline.addEventListener("mouseover", (e) => showTripTooltip(e, trip));
        polyline.addEventListener("mouseout", hideTooltip);
```

with:

```javascript
        polyline.addEventListener("mouseover", (e) => {
            showTripTooltip(e, trip);
            showHoverNodeLabels(trip);
        });
        polyline.addEventListener("mouseout", () => {
            hideTooltip();
            clearHoverNodeLabels();
        });
```

- [ ] **Step 4: Verify syntax**

Run: `node --check frontend/src/app.js`
Expected: no output.

- [ ] **Step 5: Manually verify in the browser**

Reload the page and confirm:
- Hover the mouse over any train's dashed line (selected or not). Small labels reading `{código} {HH:MM}` appear next to every stop node of that specific train, on top of a small dark background box.
- Move the mouse off the line: the labels disappear (the cursor tooltip also disappears, as before).
- Hover a *different* train's line right after: the previous train's labels are fully gone and only the new train's labels show (no leftover/duplicated labels from the previous hover).
- Hover the currently-selected train's line (the one with visible draggable circles): the new hover labels appear alongside the existing circles without visual glitches.

- [ ] **Step 6: Add manual_test.md Scenario 11**

Append to `frontend/tests/manual_test.md`:

```markdown
## Cenário 11: Rótulos de Nó ao Passar o Mouse

1. Sem selecionar nenhum trem, passe o mouse sobre qualquer linha tracejada no gráfico.
2. Confirme que aparece um rótulo pequeno (código do trem + horário) ao lado de cada nó/parada daquela viagem, além do tooltip que já existia perto do cursor.
3. Tire o mouse da linha e confirme que os rótulos somem.
4. Passe o mouse rapidamente por duas linhas diferentes em seguida; confirme que os rótulos da primeira não ficam "grudados" na tela.
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/index.css frontend/src/app.js frontend/tests/manual_test.md
git commit -m "feat: show train code and time at every node on line hover"
```

---

## Final Verification (after all three tasks)

- [ ] Run `node --check frontend/src/app.js` one more time — clean.
- [ ] Restart the backend server, re-import the real `backend/data/schedule.json`, and walk through manual_test.md Scenarios 9, 10, and 11 back to back in one browser session to confirm the three features don't interfere with each other (e.g. dragging a node while a hover-label is showing on a different train, or the sidebar refreshing correctly right after an auto-scroll tick).
- [ ] `git log --oneline -3` shows the three feature commits from this plan.
