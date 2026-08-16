# Regulação de Partidas (Spec 4) — Design Spec

**Data:** 2026-08-16
**Status:** Draft

---

## Objetivo

Quando um trem atrasa e sua chegada pareada (Spec 3 — Tempo de Volta) violaria o tempo mínimo de volta, em vez de simplesmente concentrar o atraso inteiro numa única partida futura (deixando um intervalo grande e irregular bem antes dela), distribuir esse atraso em rampa entre as partidas seguintes da mesma origem/sentido, mantendo o intervalo entre partidas consecutivas o mais regular possível — como o serviço já opera por intervalos regulares.

---

## Escopo

Depende inteiramente do pareamento chegada↔partida já definido na **Spec 3 — Tempo de Volta**: só atua onde há `turnaround_seconds` configurado numa estação e um par identificado. Depende também da **Spec 2b — Edição de Viagem**: viagens canceladas (sem parada ativa) são naturalmente excluídas da fila de partidas consideradas, e a rampa respeita a mesma regra de lookback/cronologia que `shift_stop` já usa.

---

## Gatilho

**Novo setting** (reaproveita a tabela `settings` já existente, mesmo padrão de `edit_lookback_minutes`): `auto_regulation_enabled` (bool, default `false`).

- **Desligado (padrão):** violação de tempo mínimo (Spec 3) só é sinalizada em vermelho, como já especificado ali. A partida violada ganha, no menu de contexto, a opção **"Regular"** — aciona a rampa só para aquele par específico.
- **Ligado:** toda vez que uma chegada pareada muda e passaria a violar o tempo mínimo, o sistema roda a mesma rampa automaticamente, sem esperar clique.

Mesmo algoritmo nos dois modos — muda só quem aciona.

---

## Algoritmo da rampa

Para uma chegada `A` (estação `S`, sentido `D`) pareada pela Spec 3 com uma partida `P` (estação `S`, sentido oposto a `D`):

1. `target = A.arrival_time_efetivo + turnaround_seconds`. A chegada efetiva considera `active_last_seq` (Spec 2b) — uma viagem suprimida usa o ponto onde realmente termina agora. Se `target <= P.departure_time` atual, não há violação: nada a fazer.
2. `excess = target - P.departure_time` — o quanto falta empurrar a partida `P`.
3. Monta a lista `[D1, D2, ..., DN]`: partidas de `S`, mesmo sentido de `P`, com `departure_time > agora` (ainda não partiram), com primeira parada ativa (`active_first_seq` válido — Spec 2b já exclui canceladas naturalmente, pois não têm parada ativa nenhuma), ordenadas pelo `departure_time` atual, até `P` inclusive (`DN = P`).
4. `increment = excess / N`, com arredondamento por passo. Para `k` de `1` a `N-1`: delta de `Dk` = `round(k * excess / N)` menos qualquer delta já aplicado anteriormente a essa viagem. Para `DN`: o delta é forçado para bater exatamente em `target` (não usa a fórmula de arredondamento) — garante que o ponto-âncora nunca desvia por erro de arredondamento acumulado.
5. Aplica o delta de cada `Dk` nas próprias paradas dele — mesmo loop de propagação que `shift_stop` já usa hoje, uma vez por viagem afetada.

**Reexecução:** cada acionamento (manual ou automático) recalcula contra os horários **atuais** (já rampeados de uma execução anterior, se houver) — não contra o template. Se o atraso de `A` crescer, a rampa se estende; se diminuir, comprime de volta, sempre respeitando os mesmos limites de cronologia/lookback que `shift_stop` já valida.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/regulation/apply` | Body: `{ "trip_id": "...", "station_id": "..." }` — identifica a chegada violada (`trip_id` da viagem que chega, `station_id` do pareamento). Roda o algoritmo, aplica em `D1..DN`, retorna as viagens afetadas. |
| `PUT` | `/api/settings/auto-regulation` | Body: `{ "enabled": bool }` |

Modo automático: internamente, toda vez que uma chegada pareada é alterada (via `shift_stop`, resolução de interdição, etc.) e `auto_regulation_enabled = true`, o backend chama a mesma lógica de `apply` automaticamente antes do commit final da operação que originou a mudança.

Toda ação de regulação faz broadcast via WebSocket (mesmo canal existente) com as viagens afetadas.

---

## Frontend

- Ícone no header (mesmo estilo do toggle de tema claro/escuro) liga/desliga regulação automática — persiste via `PUT /api/settings/auto-regulation`.
- Partida destacada em vermelho pela Spec 3 (violação de tempo mínimo) ganha, no menu de contexto (botão direito), a opção **"Regular"** — só aparece quando há violação detectada ali.
- Viagens afetadas pela rampa são re-renderizadas com os novos horários exatamente como qualquer `shift_stop` já atualiza hoje — sem estilo visual novo além do que a Spec 3 já usa pra sinalizar violação (que desaparece assim que a rampa resolve).

---

## Casos de borda

**Excesso negativo (atraso diminuiu):** a rampa comprime simetricamente de volta, respeitando os mesmos limites de cronologia/lookback que `shift_stop` já valida — se algum `Dk` não puder recuar (fora da janela editável), esse trem fica onde está e a compressão é redistribuída entre os demais.

**Múltiplas violações independentes na mesma origem/sentido ao mesmo tempo:** cada acionamento de "Regular" (manual ou automático) trata uma cadeia por vez, ancorada numa chegada-alvo específica. Violações sobrepostas não são combinadas nesta versão — comportamento não definido, aceito como está.

---

## O que esta spec NÃO inclui

- Combinar/otimizar múltiplas rampas conflitantes simultâneas
- Regulação entre estações diferentes ou fora do pareamento da Spec 3
- Undo específico da rampa sem afetar outros ajustes manuais feitos nas mesmas viagens — usa o "Resetar" existente, já sujeito à regra passado/futuro da Spec 2b

---

## Dependências e riscos

| Item | Risco | Mitigação |
|------|-------|-----------|
| Depende de Spec 3 e Spec 2b | Não pode ser implementada isoladamente — pressupõe pareamento e exclusão de canceladas já funcionando | Ordem de implementação: Spec 3 e Spec 2b antes desta |
| Modo automático reescreve várias viagens sem interação do operador | Pode surpreender o despachante se ele não perceber que está ligado | Ícone de estado sempre visível no header, mesmo padrão do toggle de tema |
| Arredondamento por passo pode acumular erro de poucos segundos entre trens intermediários | Diferença imperceptível na prática (segundos) | Âncora (`DN`) sempre exata, forçada fora da fórmula de arredondamento |
