# Tempo de Volta (Rotação de Trens) — Design Spec

**Data:** 2026-08-16
**Status:** Draft

---

## Objetivo

Permitir configurar, por estação, um tempo mínimo de volta (turnaround): o intervalo mínimo entre um trem chegar naquela estação e o trem de sentido oposto poder partir de lá. Com isso, o sistema infere e desenha visualmente qual chegada corresponde a qual partida de sentido oposto (mesmo trem físico), e avisa quando uma partida já planejada fica abaixo desse mínimo.

---

## Escopo

Configuração por estação (qualquer estação, não só os terminais RGS/BFU — o operador pode alterar destinos e uma grade nova pode terminar viagens em qualquer ponto). Pareamento e validação são **derivados em runtime a partir dos horários já existentes na grade** — esta spec não gera viagens novas nem altera horários automaticamente.

---

## Banco de Dados

### Nova coluna em `stations`

```sql
ALTER TABLE stations ADD COLUMN turnaround_seconds INTEGER NULL;
```

`NULL` = não configurado, sem pareamento/validação para aquela estação.

Nenhuma tabela nova. O pareamento chegada↔partida não é persistido — é recalculado no frontend a partir do schedule já sincronizado (mesmo padrão de qualquer cliente conectado calcular o mesmo resultado a partir do mesmo estado).

---

## Algoritmo de pareamento (frontend)

Recalculado sempre que o schedule ou algum `turnaround_seconds` muda — função pura de leitura, sem chamada de API dedicada.

Para cada estação `S` com `turnaround_seconds` configurado, e para cada sentido de origem `D` (`BFU-RGS` / `RGS-BFU`):

- **Chegadas**: viagens cuja última parada é `S`, vindas no sentido `D` — ordenadas por `arrival_time` ascendente.
- **Partidas**: viagens cuja primeira parada é `S`, indo no sentido oposto a `D` — ordenadas por `departure_time` ascendente.
- Pareia a i-ésima chegada com a i-ésima partida, na ordem cronológica (mesmo trem físico, mesma plataforma: ordem de chegada = ordem de saída). Sobras de qualquer lado (mais chegadas que partidas, ou vice-versa) ficam sem par — não é erro (ex.: último trem do dia; trem que só está entrando em operação ali).
- Para cada par: `gap = departure_time - arrival_time`.
  - `gap >= turnaround_seconds` → par válido, desenha conector.
  - `gap < turnaround_seconds` → **violação**: destaque visual de aviso; correção é manual (arrastar nó), o sistema não bloqueia nem ajusta sozinho.

Mesmo padrão de fila FCFS por ordem cronológica já usado no algoritmo da Spec 2a (Interdições) — aqui é validação/exibição, não geração de atraso.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `PUT` | `/api/stations/{id}/turnaround` | Body: `{ "turnaround_seconds": int \| null }`. `null` remove a configuração. |

`ScheduleOut` (retorno de `GET /api/schedule`) ganha o campo `station_turnarounds: { [station_id]: seconds }`, contendo só as estações configuradas — evita endpoint de leitura dedicado, reaproveita o fetch/broadcast que já existe.

Mudança em `PUT /api/stations/{id}/turnaround` faz broadcast via WebSocket (mesmo canal existente) para sincronizar todas as telas conectadas.

---

## Frontend

### Configurar

Clique na `station-grid-line` (linha horizontal da estação no gráfico, hoje sem handler) abre diálogo:

- Título: "Tempo de volta em [nome da estação]"
- Campo: tempo (aceita `MM:SS` ou segundos), vazio se não configurado
- Botões: `Salvar` / `Remover` / `Cancelar`

`Salvar`/`Remover` → `PUT /api/stations/{id}/turnaround`.

### Desenho do conector

Para cada par válido (chegada → partida oposta): uma linha fina horizontal sobre a `station-grid-line`, de `timeToX(arrival_time)` até `timeToX(departure_time)`, na altura `dxfYToSvg(station.y_coordinate)`. Mesmo princípio visual do "trecho parado" da Spec 2a (Interdições), aplicado na borda da estação em vez de no meio da via.

### Violação

Par com `gap < turnaround_seconds`: conector e/ou nó de partida destacados em cor de aviso (vermelho). Não bloqueia nada — o operador corrige manualmente arrastando o nó, mecanismo que já existe (`shift_stop`).

### Cadeia ao passar o mouse

`mouseenter` numa viagem monta a cadeia futura seguindo os pares (chegada → próxima partida → chegada dessa partida → próxima partida → ...) até não achar mais par. A viagem sob o mouse recebe ênfase total; cada elo seguinte na cadeia fica progressivamente mais discreto (opacidade decrescente por distância). `mouseleave` reverte ao estado normal. Aditivo ao clique de seleção já existente (`selectTrip`) — não o substitui.

---

## O que esta spec NÃO inclui

- Bloquear/impedir salvar uma partida abaixo do mínimo — só aviso visual
- Geração automática de viagem de retorno nova — viagens dos dois sentidos continuam criadas independentemente (Spec 1 batch / DXF)
- Sugestão de horário ao criar grade nova baseada no tempo de volta (possível refinamento futuro da Spec 1, fora desta spec)
- Cadeia retroativa (viagens passadas que aquele trem já fez) — só futuro
- Pareamento entre estações diferentes ou entre linhas diferentes — sempre mesma estação

---

## Dependências e riscos

| Item | Risco | Mitigação |
|------|-------|-----------|
| Pareamento posicional (i-ésima chegada ↔ i-ésima partida) | Em estação com múltiplas plataformas, a ordem "real" pode não ser a cronológica estrita | Aceito — nessas estações cruzamento é esperado, aviso de violação não impede nada, operador ajusta manualmente |
| `station_turnarounds` recalculado a cada mudança de schedule | Custo de recomputar pareamento no cliente a cada broadcast | Função pura sobre poucas dezenas de viagens por estação; custo desprezível |
