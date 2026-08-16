# Edição de Viagem (Spec 2b) — Design Spec

**Data:** 2026-08-16
**Status:** Draft

---

## Objetivo

Dar ao despachante duas ferramentas manuais para reconfigurar uma viagem já programada, sem precisar recriá-la: **suprimir o restante de uma viagem** (ela termina antes do planejado — inclusive, no caso extremo, virar cancelamento) e **mudar de onde uma viagem já programada parte** (ela passa a originar de uma parada mais à frente na rota, reaproveitando um trem físico que ficou livre).

Motivação original: a Spec 2a (Interdições) pode gerar filas longas na via única. Em vez de deixar um trem esperando muito tempo, o despachante pode encerrar sua viagem numa estação intermediária e, separadamente, adiantar uma viagem já programada de sentido oposto para sair dali — sem inventar viagem nova nem horário novo.

---

## Escopo

Cobre exclusivamente a camada **live** (viagens do dia corrente) — o mesmo escopo de `shift_stop`/`reset_trip`. Não altera grades/templates (Spec 1). Assume Spec 2a (Interdições) e Spec 3 (Tempo de Volta) como contexto de uso, mas não depende delas para funcionar — são operações independentes, usadas juntas por julgamento do operador.

---

## Modelo de dados e semântica das operações

### Novas colunas em `trips` (só live)

```sql
ALTER TABLE trips ADD COLUMN active_first_seq INTEGER NULL;
ALTER TABLE trips ADD COLUMN active_last_seq INTEGER NULL;
```

`NULL` em ambas = rota completa ativa (comportamento atual, default). Nenhuma linha de `planned_stops` é apagada por nenhuma das duas operações — os dados continuam lá; só passam a renderizar fora da janela `[active_first_seq, active_last_seq]`.

### Suprimir a partir daqui

Clique num nó → botão direito → "Suprimir a partir daqui". Define `active_last_seq = sequence_order do nó imediatamente anterior ao clicado`. Tudo a partir do nó clicado (inclusive) passa a renderizar tracejado/cinza.

Clicar no **primeiro** nó da viagem produz `active_last_seq` antes de qualquer parada — nenhuma parada ativa, viagem inteira tracejada. Isso **é** o cancelamento: mesmo mecanismo, sem comando separado, sem estado novo pra manter.

### Alterar partida

Clique no nó de partida **atual** da viagem → botão direito → "Alterar partida" → cursor entra em modo de escolha; clique em outro nó da mesma viagem, mais à frente e dentro da janela ativa, confirma. Define `active_first_seq = sequence_order do nó escolhido`.

Usa o horário que aquela parada **já tinha** — nada é inventado. Se o operador quiser outro horário, arrasta o nó normalmente depois (mesmo mecanismo de `shift_stop`/drag que já existe).

Só é permitido mover a origem **pra frente** (encurtando o início). Não é possível escolher uma parada anterior à origem atual — isso exigiria inventar horário pra um trecho que a viagem não tinha mais. Para reverter, ver regra de reset abaixo.

### Validação de lookback

As duas operações validam o nó-alvo contra o mesmo `edit_lookback_minutes` que `shift_stop` já usa (mesmo `LookbackExceededError`): não é possível aplicar em algo cujo horário salvo seja mais antigo que `agora - edit_lookback_minutes`.

### Renderização

Paradas com `sequence_order < active_first_seq` ou `sequence_order > active_last_seq` desenham tracejado/cinza, sem alça de drag (não editáveis por essas paradas).

---

## Regra "reset só toca o futuro" (aplicada em todo o sistema)

Esta spec introduz uma regra compartilhada, usada por **qualquer** operação de reversão do sistema — não só as desta spec:

> Uma reversão só pode alterar uma parada (horário, ou janela `active_first_seq`/`active_last_seq`) se o horário **atualmente salvo** dessa parada for `>= agora - edit_lookback_minutes`. Paradas mais antigas que isso ficam congeladas — a reversão não as toca, mesmo que o alvo (template ou snapshot) seja diferente.

Aplicações:
- **`reset_trip`** (já existe): cada parada só volta ao template se ainda estiver dentro da janela editável; paradas "no passado" mantêm o que de fato ocorreu.
- **`active_first_seq`/`active_last_seq`** desta spec: um corte só é desfeito automaticamente pelo `reset_trip` se o nó-fronteira do corte ainda estiver dentro da janela editável. Um corte feito há muito tempo (fora da janela) é permanente, mesmo depois de "Resetar".
- **Spec 2a (Interdições), Passo 0** — já escrita e commitada — recebe a mesma regra por emenda (ver nota no próprio documento): a reversão para o snapshot pré-interdição só toca paradas dentro da janela editável.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/trips/{trip_id}/suppress-from/{station_id}` | Define `active_last_seq` até a parada anterior a `station_id`. Valida lookback. |
| `POST` | `/api/trips/{trip_id}/depart-from/{station_id}` | Define `active_first_seq = sequence_order de station_id`. Valida lookback. |

`POST /api/trips/{trip_id}/reset` (existente) passa a respeitar a regra acima: restaura horários e zera `active_first_seq`/`active_last_seq` apenas onde a paradas/corte ainda estiverem dentro da janela editável.

---

## Frontend

- Menu de contexto (botão direito) em qualquer nó ganha **"Suprimir a partir daqui"**.
- Menu de contexto no nó de partida atual da viagem ganha **"Alterar partida"** — fluxo de dois cliques (escolher comando → clicar no novo nó de partida), mesmo padrão de interação de dois cliques já usado na Spec 1.
- Paradas fora da janela ativa renderizam tracejado/cinza, sem drag.
- Broadcast via WebSocket nas duas ações (mesmo canal existente), pra sincronizar despachantes conectados.

---

## Integração com Spec 3 (Tempo de Volta)

O algoritmo de pareamento chegada↔partida da Spec 3 passa a considerar a parada **efetiva** de cada viagem — `active_last_seq` como chegada, `active_first_seq` como partida — em vez do literal primeiro/último `sequence_order`. Uma viagem suprimida ou com partida alterada participa do pareamento pelo ponto onde ela realmente começa/termina agora.

---

## O que esta spec NÃO inclui

- Geração automática de viagem de retorno — o operador escolhe manualmente qual viagem já programada vira o retorno, usando "Alterar partida"
- Mover a origem pra trás (estender o início) — só "Resetar" (dentro da janela editável) desfaz um corte
- Undo específico da supressão/alteração, preservando outros ajustes manuais feitos na mesma viagem — só o "Resetar" geral, agora respeitando a regra passado/futuro
- Alterações em grade/template (Spec 1) — só camada live

---

## Dependências e riscos

| Item | Risco | Mitigação |
|------|-------|-----------|
| Regra "reset só toca o futuro" é cross-cutting | Muda comportamento de `reset_trip` que já existe e é usado por outras specs (2a) | Documentado como regra compartilhada nesta spec; emenda registrada na Spec 2a |
| "Alterar partida" com fluxo de dois cliques | Pode ser confuso qual nó é o "novo" vs qual é o "atual" durante o modo de escolha | Cursor/estado visual deve deixar claro que está em modo de escolha (mesmo tratamento que outros modos de dois cliques no app) |
| Paradas suprimidas continuam recebendo delta de `shift_stop` se algo a montante mudar | Trecho invisível ficando "desatualizado" de forma inofensiva, já que não é renderizado | Aceitável — se um dia a parada for reativada (via Resetar dentro da janela), os horários já estarão consistentes |
