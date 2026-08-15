# Gerenciamento de Grades — Design Spec

**Data:** 2026-08-15
**Status:** Draft

---

## Objetivo

Permitir criar grades horárias novas a partir de uma tela em branco, salvar múltiplas grades nomeadas no banco de dados, e carregar qualquer delas para operação. A grade Base CPTM importada do DXF passa a ser apenas mais uma grade no sistema — sem status especial.

---

## Escopo

Esta spec cobre a **Spec 1 — Gerenciamento de Grades**. A auditoria histórica (comparação programado × realizado em dias passados) é a Spec 2, dependente desta.

---

## Banco de Dados

### Nova tabela `schedules`

```sql
CREATE TABLE schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    created_at      DATETIME DEFAULT (datetime('now')),
    last_loaded_at  DATETIME NULL
);
```

### Migração das tabelas existentes

`template_trips` e `template_planned_stops` recebem coluna `schedule_id INTEGER NOT NULL REFERENCES schedules(id)`.

Na migração inicial, cria-se a schedule `id=1, name='Grade Base CPTM'` e todos os registros existentes recebem `schedule_id=1`.

As tabelas operacionais (`trips`, `planned_stops`) **não recebem** `schedule_id` — elas sempre representam "o dia em curso" e são derivadas de qualquer grade que o operador carregar.

### Invariante

O servidor mantém em memória `current_schedule_id` (qual grade foi carregada para hoje). O reset das 03:00 em `scheduler.py` funciona igual ao atual: reseta `trips`/`planned_stops` a partir do template — mas só executa se `current_schedule_id` estiver definido. Se nenhuma grade foi carregada, o reset é no-op.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/api/schedules` | Lista todas as grades (id, name, created_at, last_loaded_at) |
| `POST` | `/api/schedules` | Cria grade vazia. Body: `{ "name": "string" }` |
| `GET` | `/api/schedules/{id}/trips` | Retorna template_trips da grade |
| `POST` | `/api/schedules/{id}/trips/batch` | Cria N viagens com headway (ver abaixo) |
| `DELETE` | `/api/schedules/{id}` | Remove grade. Erro se for a única grade existente |
| `POST` | `/api/schedules/{id}/clone` | Salvar Como. Body: `{ "name": "string" }`. Copia todos os template_trips e template_planned_stops para nova grade |
| `PATCH` | `/api/schedules/{id}` | Renomear. Body: `{ "name": "string" }` |
| `POST` | `/api/schedules/{id}/load` | Carrega grade para operação. Copia template → live tables, atualiza `last_loaded_at`, define `current_schedule_id` no servidor |

### `POST /api/schedules/{id}/trips/batch` — payload

```json
{
  "direction": "BFU-RGS" | "RGS-BFU",
  "first_departure": "06:00:00",
  "last_station": "RGS",
  "count": 4,
  "headway_seconds": 900,
  "stop_offsets": [
    { "station": "BFU", "offset_seconds": 0 },
    { "station": "LUZ", "offset_seconds": 420 },
    ...
  ]
}
```

`stop_offsets` são tempos relativos à partida da primeira viagem. O backend calcula os horários de cada viagem somando o headway ao offset.

### Renumeração ao salvar

Executada no backend sempre que o endpoint `batch` é chamado, ou via `POST /api/schedules/{id}/renumber` chamado explicitamente ao salvar a grade:

1. Separar template_trips por direção
2. Ordenar cada grupo: `departure_time ASC`; empate → estação de partida mais próxima do terminal recebe número menor (usando o índice da estação na lista `stations` de `db.py`)
3. Reatribuir `train_code`: ímpares `P1, P3, P5…`, pares `R2, R4, R6…`

---

## Frontend

### Novo tab no header

O `app-header` ganha dois botões de modo ao lado do logo:

```
[Operacional]  [Grades]
```

`switchMode('operational' | 'schedules')` em `app.js` controla qual view renderizar na `main-content`. A transição é puramente visual — sem reload de página.

### View "Grades" — estrutura

```
┌──────────────────────┬──────────────────────────────────┐
│  Painel Esquerdo     │  Canvas de Edição                │
│  (lista de grades)   │  (gráfico SVG da grade aberta)   │
│                      │                                  │
│  • Grade Base CPTM ✓ │  [mesmo SVG do modo operacional] │
│  • Grade Pico        │  [porém sem auto-scroll,         │
│  • Grade Feriado     │   sem linha do agora,            │
│                      │   sem drag de nós]               │
│  [Nova Grade]        │                                  │
│  [Abrir]             │                                  │
│  [Salvar]            │                                  │
│  [Salvar Como]       │                                  │
│  [Renomear]          │                                  │
│  [Excluir]           │                                  │
│  [Carregar p/ Hoje]  │                                  │
└──────────────────────┴──────────────────────────────────┘
```

### Canvas de edição

- Usa a mesma função `renderChart()` mas com dados de `appState.editorScheduleId` em vez das live trips
- Linha central: mostra o horário correspondente ao centro do viewport (idêntico ao `getReferenceTime()` atual); **sem** auto-scroll, **sem** amarração ao relógio
- Viagens da grade aparecem como linhas normais; nós não são arrastáveis nesta versão

### Fluxo de criação de viagem

1. **Botão direito** sobre qualquer ponto do canvas → menu contextual com "Nova Viagem"
2. Cursor entra em modo criação (cursor crosshair via CSS)
3. **Clique 1** — nó de partida: registra `{ station, time }` a partir das coordenadas SVG (`xToTime`, `yToStation`)
4. **Clique 2** — nó de chegada: registra `{ station, time }`
5. **Dialog de confirmação** abre com:
   - Origem: `[estação] às [HH:MM]`
   - Destino: `[estação] às [HH:MM]`
   - Campo: **Nº de viagens** (número, default 1)
   - Campo: **Intervalo** (MM:SS, headway entre viagens)
   - **Tabela de tempos por estação** (editável): cada estação intermediária com offset em minutos calculado da média das viagens existentes no banco no mesmo sentido. Se nenhuma viagem existir, distribui linearmente.
   - Botões: `Criar` / `Cancelar`
6. `Criar` → `POST /api/schedules/{id}/trips/batch` → viagens aparecem no canvas → renumeração executada no backend

### `yToStation` — nova função

Converte coordenada Y do SVG na estação mais próxima usando a mesma lógica de `dxfYToSvg` invertida. Snap tolerance: ±25px.

### Carregar para Hoje

Botão no painel esquerdo. Mostra dialog de confirmação: `"Carregar [nome] para operação hoje? As viagens em curso serão substituídas."`. Confirmar → `POST /api/schedules/{id}/load` → frontend volta automaticamente para o tab `Operacional`.

---

## O que esta spec NÃO inclui

- Auditoria histórica (programado × realizado em dias passados) — Spec 2
- Edição de nós por drag no editor (drag existe apenas na view Operacional)
- Importação de DXF para grades não-Base (futuro)
- Multi-linha / personalização de estações (produto separado por operadora)

---

## Dependências e riscos

| Item | Risco | Mitigação |
|------|-------|-----------|
| Migração com `schedule_id NOT NULL` | Dados existentes perdem FK | Criar schedule `id=1` antes da ALTER TABLE |
| `yToStation` snap de clique | Clique entre estações → estação errada | Tooltip mostra estação "snapped" durante modo criação |
| Renumeração com batch | Ordem pode divergir da expectativa do operador | Exibir preview da numeração no dialog antes de confirmar |
