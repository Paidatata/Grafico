# Interdições — Design Spec

**Data:** 2026-08-16
**Status:** Draft

---

## Objetivo

Permitir ao despachante marcar um trecho de via como interditado (uma das vias fica indisponível, e o trecho passa a ser via única compartilhada pelos dois sentidos por uma janela de tempo) e ter o sistema recalcular automaticamente os cruzamentos necessários — trens de sentidos opostos se alternam no trecho interditado, cruzando exatamente nas bordas do trecho.

Dois gatilhos de uso:
1. **Planejado** — ao montar uma grade nova (Spec 1), o despachante já desenha a interdição sabendo de uma obra futura.
2. **Reativo** — na tela de operação ao vivo, durante uma emergência real, o despachante interdita o trecho agora e o sistema recalcula os trens que ainda vão chegar até lá.

---

## Escopo

Esta spec cobre a **Spec 2a — Interdições**: o retângulo de interdição (criar/editar/rotular/excluir) e o algoritmo automático de fila via-única.

Cancelar viagem e encurtar origem/destino (retorno antecipado de um trem no meio da rota) é uma ferramenta manual separada — **Spec 2b — Edição de Viagem**, não implementada aqui. A Spec 2a assume que essa ferramenta ainda não existe: se a fila ficar longa demais, o despachante resolve arrastando nós manualmente (mecanismo que já existe hoje).

---

## Banco de Dados

### Nova tabela `interdictions`

Vive na camada *live* (como `trips`/`planned_stops`): é sempre relativa ao dia em curso, não a uma grade nomeada da Spec 1. Reseta junto no reset diário das 03:00.

```sql
CREATE TABLE interdictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    y_top           FLOAT NOT NULL,   -- menor Y da faixa (coordenada DXF, mesmo espaço de stations.y_coordinate)
    y_bottom        FLOAT NOT NULL,   -- maior Y da faixa
    start_time      TEXT NOT NULL,    -- HH:MM:SS
    end_time        TEXT NOT NULL,    -- HH:MM:SS
    description     TEXT NOT NULL DEFAULT ''
);
```

`y_top`/`y_bottom` são normalizados (min/max) na criação, independente da ordem em que o operador clicou os dois cantos.

### Nova tabela `interdiction_stop_snapshots`

Guarda, por interdição, o valor de `arrival_time`/`departure_time` de cada parada real que o algoritmo alterou — **antes** da alteração. É a baseline usada para reverter quando a interdição é editada ou excluída.

```sql
CREATE TABLE interdiction_stop_snapshots (
    interdiction_id  INTEGER NOT NULL REFERENCES interdictions(id) ON DELETE CASCADE,
    trip_id          TEXT NOT NULL,
    station_id       TEXT NOT NULL,
    arrival_time     TEXT NOT NULL,
    departure_time   TEXT NOT NULL,
    PRIMARY KEY (interdiction_id, trip_id, station_id)
);
```

Importante: a baseline é o horário **ao vivo de hoje como estava um instante antes da interdição ser criada/reaplicada** — não o template DXF. Isso importa no gatilho reativo, onde a grade de hoje já pode ter atrasos reais anteriores à interdição; reverter para o template os apagaria incorretamente.

---

## Algoritmo de fila via-única

### Quando roda

Ao criar, editar (mudar `y_top`/`y_bottom`/`start_time`/`end_time`) ou excluir uma interdição. Não roda automaticamente a cada edição manual de nó feita pelo despachante em outras viagens — só reage a mudanças na própria interdição.

### Passo 0 — Reverter afetados

Para cada linha em `interdiction_stop_snapshots` desta interdição: restaura `arrival_time`/`departure_time` daquela parada real da viagem para o valor salvo, depois apaga as linhas de snapshot desta interdição. Se a interdição foi excluída, para por aqui.

> **Emenda (2026-08-16, via Spec 2b — Edição de Viagem):** este passo agora respeita a regra geral "reset só toca o futuro" — só restaura uma parada se o horário **atualmente salvo** dela for `>= agora - edit_lookback_minutes`. Paradas mais antigas que isso ficam congeladas, mesmo que o snapshot tenha um valor diferente. Ver `2026-08-16-edicao-de-viagem-design.md` para a regra completa (a mesma se aplica a `reset_trip`).

### Passo 1 — Detectar candidatas

Para cada viagem ao vivo (excluindo as já fora do escopo pelo caso de borda "trem já dentro", ver abaixo): interpola entre as duas paradas reais que cercam a faixa `[y_top, y_bottom]` (usando os horários ao vivo **atuais**, pós passo 0) para achar `entry_time`/`exit_time` — o instante em que a linha da viagem cruzaria a faixa, assumindo velocidade constante entre as duas estações reais (mesma premissa de linha reta que o gráfico já desenha). Direção da viagem vem de comparar o Y da primeira e da última parada dela mesma. Descarta quem não cruza a faixa dentro de `[start_time, end_time]` da interdição.

**Trem já dentro da interdição no momento da criação/edição:** se `entry_time <= now < exit_time` (comparado ao horário em que a interdição está sendo aplicada), essa viagem fica **fora do cálculo automático** — o despachante ajusta manualmente arrastando os nós, porque só ele sabe o que já passou e o que já parou no campo. Isso vale para os dois sentidos; se houver um trem de cada sentido já dentro simultaneamente, ambos ficam fora do automático. No gatilho planejado (grade futura) isso normalmente não ocorre, já que nenhum trem "está circulando" ainda.

### Passo 2 — Sequenciar e Reter na Estação (S_prev)

> **Emenda (2026-08-20, correção de regressão):** a primeira implementação deste passo aplicava o delta a partir da parada logo *após* a faixa (deixando o trecho estação-anterior→estação-depois com velocidade alterada, um erro de modelagem — trens não mudam de velocidade pra absorver espera) e depois, numa segunda tentativa, deslocava a viagem inteira a partir da própria origem dela (o que resolvia a velocidade mas destruía o headway em relação aos trens seguintes do mesmo sentido, já que só aquele trem se movia). Este texto substitui as duas tentativas: o trem espera parado numa **estação real** (nunca no meio da via), e a preservação do headway da frota vira responsabilidade explícita da Spec 4 (ver `2026-08-16-regulacao-de-partidas-design.md`, seção "Gatilho de Cascata por Interdição").

Ordena as candidatas remanescentes por `entry_time` ascendente — ordem sempre pelo horário nativo (não reavaliada depois de aplicar atrasos, é FCFS pelo horário de entrada natural). Percorre em ordem mantendo `ocupante` (direção) e `livre_em` (quando a faixa libera), inicialmente vazios (faixa livre):

- Mesma direção do ocupante atual → passa sem espera; atualiza `livre_em` para o maior entre o atual e o `exit_time` desta viagem.
- Direção oposta e `entry_time >= livre_em` → passa sem espera; vira o novo ocupante (`ocupante = direção`, `livre_em = exit_time`).
- Direção oposta e `entry_time < livre_em` → **retida**:
  - `delta = livre_em - entry_time`.
  - Identifica-se a **Estação Anterior (S_prev)**: a última parada real que o trem fará antes de cruzar a faixa da interdição. O trem não pode esperar no meio da via — ele aguarda obrigatoriamente na plataforma desta estação.
  - Salva snapshot (se ainda não salvo) da parada `S_prev` e de todas as paradas seguintes desta viagem.
  - **Aplicação do delta:** o `arrival_time` em `S_prev` permanece o original (o trem chega na hora certa). Soma-se `delta` ao `departure_time` de `S_prev` e aos horários (chegada e partida) de todas as paradas a jusante. Paradas **antes** de `S_prev` não mudam.
  - Vira o novo ocupante, com `livre_em = exit_time + delta`.

**Premissa assumida:** nunca há disputa entre dois trens do mesmo sentido — só a oposição de sentidos gera espera.

**Preservação de headway:** reter um trem em `S_prev` não pode, por si só, "engolir" o intervalo planejado para os trens seguintes do mesmo sentido. Ver `2026-08-16-regulacao-de-partidas-design.md`, seção "Gatilho de Cascata por Interdição", para a propagação obrigatória desse mesmo `delta` à frota.

### Passo 3 — Persistir e notificar

Commit. Broadcast via WebSocket (mesmo canal que já existe para `shift_stop`) com a interdição e, para cada viagem afetada, `{trip_id, entry_time, exit_time}`.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/interdictions` | Cria. Body: `{y_top, y_bottom, start_time, end_time, description}`. Roda o algoritmo. |
| `PUT` | `/api/interdictions/{id}` | Edita (mesmo body). Reverte afetados e reaplica com os novos limites. |
| `DELETE` | `/api/interdictions/{id}` | Reverte afetados, remove a interdição. |

`GET /api/schedule` passa a incluir a lista de interdições ativas (evita chamada extra no load inicial).

Toda resposta de create/edit inclui, por viagem afetada, `{trip_id, entry_time, exit_time}` — a janela real de cruzamento já calculada pelo backend (passo 1+2). O frontend **não reimplementa** a fila FCFS; só usa esses dois horários pra desenhar.

---

## Frontend

### Criar / editar interdição

Botão "Interditar via" ativa modo de dois cliques no canvas (mesmo padrão de dois cliques já usado na criação de grade da Spec 1), livre de estações/nós — define os cantos opostos do retângulo. Ao soltar o segundo clique, abre diálogo com:

- Descrição (texto livre)
- Hora inicial / final (pré-preenchidas pela posição do clique, editáveis)
- Botões `Criar` / `Cancelar`

Clicar numa interdição existente reabre o mesmo diálogo, pré-preenchido, com opção adicional `Excluir`. Sem redimensionamento por arraste das bordas no MVP — só via diálogo.

### Desenho

> **Emenda (2026-08-20, correção de regressão):** substitui a versão anterior, que desenhava o "dogleg" (espera) na borda do retângulo — geometricamente inválido, já que a borda geralmente não coincide com nenhuma estação real, então o trecho de espera não correspondia a lugar nenhum onde um trem pudesse fisicamente estar parado.

`<rect>` SVG semitransparente vermelho, posicionado com `timeToX`/`dxfYToSvg` a partir de `y_top`/`y_bottom`/`start_time`/`end_time`. Descrição como rótulo (tooltip ou texto pequeno sobre o retângulo).

O frontend não desenha mais doglegs (linhas horizontais de espera) nas bordas do retângulo vermelho. Para cada viagem afetada:

- A espera visual ocorre na estação `S_prev` (a mesma que o Passo 2 usa para aplicar o delta).
- Desenha-se uma linha horizontal (espera na plataforma) exatamente sobre a `station-grid-line` correspondente a `S_prev`, indo do `arrival_time` (original, sem o delta) até o novo `departure_time` (que recebeu o delta).
- Dali, a reta da viagem cruza a interdição com sua velocidade de cruzeiro (inclinação) original, tocando apenas as bordas da zona vermelha sem quebras — nenhum vértice extra é necessário na própria borda.

### Tempo real

Create/edit/delete faz broadcast via WebSocket com a interdição e as viagens afetadas (`{trip_id, entry_time, exit_time}` ou "revertida"), para sincronizar todas as telas de despachante conectadas.

---

## O que esta spec NÃO inclui

- Cancelar viagem / encurtar origem-destino (Spec 2b)
- Redimensionamento do retângulo por arraste (só via diálogo)
- Recuperação automática de atraso após o fim da interdição — o atraso acumulado propaga normalmente a jusante (como `shift_stop` já faz); só para de gerar **novas** esperas depois do `end_time`
- Interdições recorrentes ligadas a uma grade nomeada da Spec 1 — toda interdição é ad-hoc, vive só na camada live do dia
- Múltiplas interdições simultâneas afetando a mesma viagem (comportamento indefinido, não validado pela UI)
- Resolução automática de trens já dentro do trecho no momento da criação — sempre manual

---

## Dependências e riscos

| Item | Risco | Mitigação |
|------|-------|-----------|
| Editar/excluir interdição descarta ajustes manuais não relacionados feitos nas mesmas viagens depois que a interdição foi aplicada | Despachante perde um ajuste manual que não tinha nada a ver com a interdição | Snapshot é só das paradas que a *própria interdição* alterou — ajustes em paradas fora desse alcance não são tocados. Documentar o comportamento na UI (ex.: aviso no diálogo de edição). |
| Interdições sobrepostas | Comportamento indefinido | Fora de escopo, aceito nesta versão |
| `entry_time`/`exit_time` por interpolação linear entre estações reais | Se a viagem tiver poucas paradas reais muito espaçadas, a estimativa de cruzamento pode ficar grosseira | Aceitável — mesma premissa de linha reta que o gráfico já usa para tudo mais |
| Faixa `[y_top, y_bottom]` abrange uma estação real | Comportamento não definido nesta spec (assume-se que a interdição fica entre estações, conforme uso pretendido) | Fora de escopo, mesmo tratamento de "não validado" que interdições sobrepostas |
