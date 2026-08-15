# Chart UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Três melhorias de UX no gráfico: tooltip dinâmico com horário e estação no mouse, deselecionar trem ao retomar auto-scroll por inatividade, e renderizar a porção passada das linhas planejadas com visual de "realizado".

**Architecture:** Todas as mudanças são frontend-only (vanilla JS + CSS). Feature 1 adiciona `mousemove` no polyline para interpolação ao vivo. Feature 2 adiciona efeito colateral em `autoScrollResumeCheck`. Feature 3 divide cada polyline em dois segmentos (passado/futuro) e atualiza o split no tick de 15s.

**Tech Stack:** Vanilla JS (ES2020), SVG DOM API, CSS custom properties. Sem framework, sem build step.

---

## Arquivos alterados

| Arquivo | Tipo | Responsabilidade |
|---|---|---|
| `frontend/src/app.js` | Modificar | Tooltip dinâmico, deselect, split passado/futuro |
| `frontend/src/index.css` | Modificar | Novo classe `.train-path-past` |
| `frontend/tests/manual_test.md` | Modificar | Cenários de teste para as 3 features |

---

## Task 1: Tooltip dinâmico — horário e estação no mouse

**Contexto:** `showTripTooltip(e, trip)` é chamado no `mouseover` do polyline e mostra Trem/Partida/Chegada estáticos. O tooltip não acompanha o mouse nem mostra a posição atual.

**Mudança:** substituir por `mousemove` + `showTripTooltipDynamic(e, trip)` que calcula o horário no X do mouse via `xToTime()` e a estação mais próxima pelo Y mais próximo em coordenadas SVG.

**Files:**
- Modify: `frontend/src/app.js`

- [ ] **Step 1: Adicionar `showTripTooltipDynamic(e, trip)` logo após `showTripTooltip`**

Localizar em `app.js` a função `showTripTooltip` (linha ≈ 834) e adicionar a nova função logo abaixo dela:

```js
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
```

- [ ] **Step 2: Substituir `mouseover → showTripTooltip` por `mouseover + mousemove` em `drawTrainPaths`**

Localizar em `drawTrainPaths` (linha ≈ 580) o bloco:

```js
        // Show tooltip and per-node labels on hover
        polyline.addEventListener("mouseover", (e) => {
            showTripTooltip(e, trip);
            showHoverNodeLabels(trip);
        });
```

Substituir por:

```js
        // Show per-node labels on hover; tooltip tracks mouse dynamically
        polyline.addEventListener("mouseover", () => {
            showHoverNodeLabels(trip);
        });
        polyline.addEventListener("mousemove", (e) => {
            showTripTooltipDynamic(e, trip);
        });
```

> **Nota:** o `mouseout` já existe e fecha o tooltip — não precisa mudar.

- [ ] **Step 3: Verificar manualmente**

Iniciar o servidor: `cd grafico && uvicorn backend.src.app:app --reload`

Abrir `http://localhost:8000/` e:
1. Passar o mouse lentamente sobre qualquer linha do gráfico
2. Confirmar que o tooltip aparece e mostra **Trem**, **Horário** (varia enquanto o mouse se move) e **Estação** (muda ao passar perto de nós diferentes)
3. Confirmar que os rótulos nos nós (`showHoverNodeLabels`) continuam aparecendo ao entrar na linha

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app.js
git commit -m "feat: tooltip dinâmico com horário e estação na posição do mouse"
```

---

## Task 2: Desselecionar trem ao retomar auto-scroll por inatividade

**Contexto:** `autoScrollResumeCheck()` roda a cada 1s. Quando o tempo sem interação supera `AUTO_SCROLL_RESUME_IDLE_MS` (30s), muda `appState.autoScrollPaused = false`. Após isso, `autoScrollTick` volta a centralizar o gráfico no horário atual. O trem selecionado (com nós visíveis) permanece selecionado indefinidamente.

**Mudança:** ao retomar auto-scroll, limpar `selectedTripId` e re-renderizar.

**Files:**
- Modify: `frontend/src/app.js`

- [ ] **Step 1: Atualizar `autoScrollResumeCheck` para desselecionar ao retomar**

Localizar a função `autoScrollResumeCheck` (linha ≈ 1013):

```js
function autoScrollResumeCheck() {
    if (!appState.autoScrollPaused) return;
    if (Date.now() - appState.lastInteractionAt >= AUTO_SCROLL_RESUME_IDLE_MS) {
        appState.autoScrollPaused = false;
    }
}
```

Substituir por:

```js
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
```

- [ ] **Step 2: Verificar manualmente**

1. Clicar em qualquer linha no gráfico — os nós (círculos verdes) devem aparecer e o trem fica selecionado na sidebar
2. Não interagir com o gráfico por 30 segundos
3. Confirmar que os nós desaparecem e o trem na sidebar perde o destaque (deselect automático)
4. Confirmar que o gráfico volta a se mover automaticamente para o horário atual

> Dica: reduzir `AUTO_SCROLL_RESUME_IDLE_MS` temporariamente para `5000` (5s) para agilizar o teste, restaurar para `30000` depois.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app.js
git commit -m "feat: desselecionar trem automaticamente ao retomar auto-scroll por inatividade"
```

---

## Task 3: Porção passada das linhas planejadas renderizada como "realizado"

**Contexto:** hoje cada trip é desenhada como uma única `<polyline>` com classe `train-path-planned` (tracejado). Queremos que a porção à esquerda do horário atual seja renderizada como `train-path-past` (sólido, visual de realizado) e a porção à direita como `train-path-planned` (tracejado). O ponto de corte é o X do horário atual (`timeToX(currentClockTimeStr())`). O split atualiza a cada ciclo do tick de 15s.

**Arquitetura da mudança:**
- Nova função `splitTripAtNow(trip, selectedLine)` → `{ pastPoints, futurePoints }` em coordenadas SVG
- `drawTrainPaths` passa a criar dois polylines por trip: `line-{id}-past` e `line-{id}-future`
- `updateSvgVisuals` atualiza os pontos de ambos
- `autoScrollTick` chama `renderChart()` a cada tick para manter o split atualizado (além do re-render já feito em `autoScrollResumeCheck`)

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/app.js`

- [ ] **Step 1: Adicionar classe CSS `.train-path-past` em `index.css`**

Localizar o bloco `.train-path-actual` (linha ≈ 291 do CSS) e adicionar logo após:

```css
.train-path-past {
    fill: none;
    stroke: var(--accent-actual);
    stroke-width: 2.5;
    cursor: pointer;
    transition: stroke-width 0.2s;
}

.train-path-past:hover {
    stroke-width: 4;
}
```

- [ ] **Step 2: Adicionar `splitTripAtNow(trip, selectedLine)` em `app.js`**

Adicionar antes de `drawTrainPaths`:

```js
function splitTripAtNow(trip, selectedLine) {
    const nowX = timeToX(currentClockTimeStr());
    const stopsWithCoords = trip.stops.map(stop => ({
        x: timeToX(stop.time),
        y: dxfYToSvg(stop.y_coord, selectedLine)
    }));

    const pastPoints = [];
    const futurePoints = [];

    for (let i = 0; i < stopsWithCoords.length; i++) {
        const p = stopsWithCoords[i];
        if (p.x <= nowX) {
            pastPoints.push(p);
        } else {
            // First future point: interpolate the crossing to get exact split
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
```

- [ ] **Step 3: Extrair helper `attachTripLineEvents` e refatorar `drawTrainPaths`**

No início de `drawTrainPaths`, adicionar o helper local antes do `lineTrips.forEach`:

```js
function attachTripLineEvents(polyline, trip) {
    polyline.addEventListener("mouseover", () => showHoverNodeLabels(trip));
    polyline.addEventListener("mousemove", (e) => showTripTooltipDynamic(e, trip));
    polyline.addEventListener("mouseout", () => { hideTooltip(); clearHoverNodeLabels(); });
    polyline.addEventListener("click", () => selectTrip(trip.trip_id));
}
```

Substituir o bloco de criação do polyline planejado (que começa em `const polyline = document.createElementNS(SVG_NS, "polyline")` e vai até `svg.appendChild(polyline)`) por:

```js
        const isSelected = appState.selectedTripId === trip.trip_id;
        const { pastPoints, futurePoints } = splitTripAtNow(trip, appState.selectedLine);

        if (pastPoints.length >= 2) {
            const pastLine = document.createElementNS(SVG_NS, "polyline");
            pastLine.setAttribute("points", pastPoints.map(p => `${p.x},${p.y}`).join(" "));
            pastLine.setAttribute("id", `line-${trip.trip_id}-past`);
            pastLine.className.baseVal = "train-path-past";
            attachTripLineEvents(pastLine, trip);
            svg.appendChild(pastLine);
        }

        if (futurePoints.length >= 2) {
            const futureLine = document.createElementNS(SVG_NS, "polyline");
            futureLine.setAttribute("points", futurePoints.map(p => `${p.x},${p.y}`).join(" "));
            futureLine.setAttribute("id", `line-${trip.trip_id}-future`);
            futureLine.className.baseVal = `train-path-planned ${isSelected ? 'highlighted' : ''}`;
            attachTripLineEvents(futureLine, trip);
            svg.appendChild(futureLine);
        } else if (pastPoints.length >= 2) {
            // Trip entirely in the past: past polyline is the only click target (already added above)
        }
```

> **Atenção:** remover também o bloco `const polyline = ...` e o `polyline.addEventListener("mouseover"...` original que ficam logo antes do bloco de seleção de nós. O bloco de nós (`if (isSelected) { trip.stops.forEach(...)`) permanece intacto.

- [ ] **Step 4: Atualizar `updateSvgVisuals` para os dois polylines**

Substituir a função `updateSvgVisuals` inteira (linha ≈ 766) por:

```js
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
```

- [ ] **Step 5: Atualizar `autoScrollTick` para re-renderizar o gráfico a cada tick**

O re-render a cada 15s mantém o split passado/futuro atualizado sem custo perceptível para o operador. Localizar `autoScrollTick` (linha ≈ 1007):

```js
function autoScrollTick() {
    if (appState.dragNode) return;
    if (!appState.autoScrollPaused) {
        centerChartOnTime(currentClockTimeStr(), { smooth: true });
    }
    updateNowLineLabel();
}
```

Substituir por:

```js
function autoScrollTick() {
    if (appState.dragNode) return;
    updateNowLineLabel();
    if (!appState.autoScrollPaused) {
        centerChartOnTime(currentClockTimeStr(), { smooth: true });
        renderChart();
    }
}
```

- [ ] **Step 6: Verificar manualmente**

1. Abrir `http://localhost:8000/`
2. Confirmar que linhas à **esquerda** da linha amarela (agora) aparecem como **sólidas** na cor de realizado (`--accent-actual`, vermelho no escuro / vermelho mais escuro no claro)
3. Confirmar que linhas à **direita** da linha amarela continuam **tracejadas** (planejado)
4. Selecionar um trem que esteja parcialmente no passado — confirmar que a seleção funciona clicando tanto na parte passada quanto na futura
5. Aguardar 15 segundos e confirmar que o split avança conforme o relógio
6. Clicar em "Mostrar Realizado" — confirmar que o overlay de realizados mock ainda aparece acima das linhas

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app.js frontend/src/index.css
git commit -m "feat: renderizar porção passada das linhas planejadas como realizado"
```

---

## Task 4: Atualizar cenários de teste manual

**Files:**
- Modify: `frontend/tests/manual_test.md`

- [ ] **Step 1: Adicionar cenários de teste para as 3 features**

Abrir `frontend/tests/manual_test.md` e adicionar a seção:

```markdown
## Tooltip Dinâmico (Task 1)
- [ ] Passar o mouse lentamente sobre uma linha planejada: o tooltip deve mostrar Trem, Horário (varia com o mouse) e Estação (varia ao aproximar de nós)
- [ ] Confirmar que os rótulos nos nós (train_code + time) aparecem ao entrar na linha e somem ao sair
- [ ] Passar o mouse sobre nós individuais (círculos verdes): tooltip deve mostrar Trem / Estação / Horário específicos do nó

## Deselect Automático (Task 2)
- [ ] Selecionar um trem (clique na linha ou na sidebar): nós aparecem, linha fica highlighted
- [ ] Não interagir por 30s: nós devem desaparecer, linha perde highlight
- [ ] Confirmar que o auto-scroll retoma ao mesmo tempo

## Passado como Realizado (Task 3)
- [ ] Verificar que linhas à esquerda da linha amarela (now) são sólidas (cor de realizado)
- [ ] Verificar que linhas à direita são tracejadas (planejado)
- [ ] Selecionar trem parcialmente no passado: clicar nas porções passada e futura deve selecionar igualmente
- [ ] Aguardar 15s: confirmar que o ponto de corte avança
- [ ] Clicar "Mostrar Realizado": overlay de dados mock deve aparecer corretamente acima
```

- [ ] **Step 2: Commit**

```bash
git add frontend/tests/manual_test.md
git commit -m "docs: adicionar cenários de teste manual para melhorias de UX do gráfico"
```

---

## Self-Review

**Cobertura dos requisitos:**
- ✅ Tooltip com horário no mouse + estação mais próxima + nome do trem (Task 1)
- ✅ Deselect ao retomar auto-scroll por inatividade (Task 2)
- ✅ Porção passada como realizado (Task 3)

**Checagem de placeholders:** nenhum "TBD" ou "similar à task N" — todo código completo.

**Consistência de nomes:**
- `splitTripAtNow` → usado em `drawTrainPaths`, `updateSvgVisuals` — ✅
- `showTripTooltipDynamic` → definido em Task 1 Step 1, referenciado em Task 1 Step 2 e Task 3 Step 3 — ✅
- `attachTripLineEvents` → definido e usado em Task 3 Step 3 — ✅
- IDs `line-{id}-past` / `line-{id}-future` → criados em `drawTrainPaths`, lidos em `updateSvgVisuals` — ✅
- `renderChart()` em `autoScrollTick` → já existe, chamada válida — ✅

**Risco identificado:** Task 3 Step 3 exige remover cuidadosamente o bloco original do `polyline` em `drawTrainPaths` sem tocar no bloco de nós (círculos) que vem logo após. Recomenda-se ler o arquivo antes de editar para confirmar os limites exatos do bloco a substituir.
