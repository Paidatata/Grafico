# Testes Manuais: Gráfico de Circulação Ferroviária Interativa

Este documento descreve os cenários de teste manual para validar a renderização do gráfico, a manipulação de nós de tempo e a propagação de atrasos.

## Cenário 1: Importação de Dados e Troca de Linha

1. Abra `frontend/src/index.html` em um navegador.
2. Verifique se o app inicia carregando a **Linha 10 (Turquesa)** por padrão.
3. Se o arquivo `schedule.json` não carregar automaticamente (devido a restrições CORS no protocolo `file://`), clique em **"Importar JSON"** e escolha o arquivo `frontend/data/schedule.json` ou `backend/data/schedule.json`.
4. Verifique se as listas laterais aparecem (uma de cada lado do gráfico). Como cada lista só mostra trens em trânsito no horário atual (ver Cenário 9), o conteúdo varia conforme a hora do dia e pode estar vazio — o importante é confirmar que as listas renderizam sem erro e, se houver algum trem `P...`/`R...`/`M...` em trânsito, ele aparece na lista correspondente.
5. Clique na aba **"Linha 7 (Rubi)"** e verifique se as estações no eixo Y mudam para a sequência de Jundiaí a Luz (L7).
6. Clique na aba **"Linha 710 (Unificada)"** e confirme que toda a malha integrada de Jundiaí a Rio Grande da Serra é desenhada em ordem física.

---

## Cenário 2: Seleção e Destaque de Trem

1. Na lista de trens programados, clique em um trem específico (ex: `TRIP_BFU-RGS_043600`).
2. Confirme que:
   - O item da lista fica destacado em azul.
   - O gráfico rola horizontalmente para centralizar o início da viagem do trem.
   - A linha tracejada correspondente no gráfico fica mais espessa e branca.
   - Pequenos círculos verdes (nós de estação) surgem sobre a linha.

---

## Cenário 3: Edição e Propagação de Atraso (Arrastar Nós)

1. Selecione um trem e localize um nó de parada (círculo verde).
2. Posicione o cursor sobre o nó e confirme que o cursor muda para `ew-resize` (redimensionamento leste-oeste).
3. Clique e arraste o nó para a direita (+ tempo) ou esquerda (- tempo).
4. Confirme que:
   - O nó sendo arrastado fica amarelo com uma borda de destaque.
   - Um tooltip exibe o nome da estação, o novo horário calculado e o delta do atraso em minutos (ex: `+12 min`).
   - A linha do trem se move em tempo real acompanhando o movimento do mouse.
   - **Propagação**: Todos os nós seguintes (downstream) desse trem se movem na mesma proporção de tempo, mantendo a inclinação (velocidade de viagem) idêntica entre as estações subsequentes.
   - Os horários na lista lateral correspondente (esquerda para trens `P...`, direita para `R.../M...`) se atualizam assim que você solta o mouse.

---

## Cenário 4: Comparação com Circulação Realizada

1. Clique no botão **"Mostrar Realizado"** no cabeçalho do gráfico.
2. Confirme que linhas vermelhas contínuas aparecem no gráfico representando a circulação real/realizada.
3. Compare visualmente a distância entre a linha tracejada (planejada) e a vermelha (realizada) para estimar os desvios.

## Cenário 5: Sincronização em Tempo Real Entre Despachantes

1. Abra `http://<servidor>:8000/` em duas abas (ou dois navegadores/máquinas diferentes).
2. Na aba A, arraste um nó de horário e solte.
3. Confirme que a aba B reflete a mesma alteração em até poucos segundos, sem precisar recarregar a página.

## Cenário 6: Janela de Retroação (Lookback)

1. Localize um trem com uma parada cujo horário já passou há mais tempo que o valor configurado em "edit_lookback_minutes" (15 minutos por padrão).
2. Confirme que o nó dessa parada aparece acinzentado e não é arrastável (cursor "not-allowed").
3. Confirme que paradas dentro da janela permitida continuam arrastáveis normalmente.

## Cenário 7: Servidor Indisponível

1. Pare o processo do backend (`uvicorn`).
2. Recarregue a página do gráfico.
3. Confirme que uma mensagem clara de erro de conexão aparece, em vez de silenciosamente carregar dados fictícios.

## Cenário 8: Viagens que Cruzam a Meia-Noite

1. Importe o `backend/data/schedule.json` real (ele tem ~10 viagens que cruzam a meia-noite, ex: `TRIP_BFU-RGS_231230`).
2. Localize e selecione uma dessas viagens (paradas com horário próximo de `23:5x` seguidas de paradas em `00:0x`).
3. Confirme que a linha do trem é uma polilinha contínua e crescente da esquerda para a direita — sem "voltar" para a borda esquerda do gráfico no trecho após a meia-noite.
4. Confirme que os rótulos de hora no topo/base do gráfico, à direita de "23:00", mostram "00:00", "01:00", "02:00", "03:00" (não "24:00", "25:00"...).
5. Arraste um nó de parada logo após a meia-noite (ex: `00:01`) e confirme que a propagação para as paradas seguintes (também após a meia-noite) funciona normalmente.

## Cenário 9: Listas Laterais Agrupadas e Filtradas por Trânsito

1. Abra a aplicação com o `schedule.json` real importado.
2. Confirme que existem duas listas, uma de cada lado do gráfico: "Sentido BFU (Ímpares)" à esquerda mostrando só códigos `P...`, "Sentido RGS/Mauá (Pares)" à direita mostrando só `R...`/`M...`.
3. Confirme que cada lista mostra só os trens cuja viagem (partida até chegada) inclui o horário atual — não as 251 viagens do dia inteiro.
4. Role o gráfico manualmente para um horário bem diferente do atual (ex: de manhã cedo). Confirme que as duas listas se atualizam para mostrar os trens circulando naquele horário rolado, não mais no horário atual.
5. Digite um código na busca da lista esquerda (ex: "P15") e confirme que só a lista esquerda é filtrada — a direita continua mostrando todos os trens em trânsito dela.

## Cenário 10: Linha do "Agora" e Auto-Scroll

1. Abra a aplicação. Confirme que a linha vertical amarela aparece centralizada na área do gráfico, com um rótulo mostrando o horário atual.
2. Sem tocar em nada, espere ~2 minutos (uma única tick de 15s não é perceptível: nessa escala ~8,2 px/min, 15s equivalem a ~2px, e o rótulo só muda a cada minuto). Confirme que o gráfico rastejou visivelmente para a esquerda por baixo da linha (~16px, que continua no centro) e que o rótulo da linha avançou aproximadamente 2 minutos.
3. Role o gráfico manualmente (roda do mouse ou barra de rolagem) para um horário diferente. Confirme que a linha continua fixa no centro da tela, mas o rótulo agora mostra o horário para onde você rolou — não o horário real.
4. Pare de interagir e espere 30 segundos. Confirme que o gráfico volta a rolar sozinho até o horário real aparecer centralizado outra vez.
5. Arraste um nó de horário (edição normal) e confirme que, depois de soltar, o auto-scroll também fica pausado por 30s antes de retomar.

## Cenário 11: Rótulos de Nó ao Passar o Mouse

1. Sem selecionar nenhum trem, passe o mouse sobre qualquer linha tracejada no gráfico.
2. Confirme que aparece um rótulo pequeno (código do trem + horário) ao lado de cada nó/parada daquela viagem, além do tooltip que já existia perto do cursor.
3. Tire o mouse da linha e confirme que os rótulos somem.
4. Passe o mouse rapidamente por duas linhas diferentes em seguida; confirme que os rótulos da primeira não ficam "grudados" na tela.

## Tooltip Dinâmico
- [ ] Passar o mouse lentamente sobre qualquer linha do gráfico: o tooltip deve aparecer mostrando **Trem**, **Horário** (varia conforme o mouse se move) e **Estação** (muda ao aproximar de nós diferentes)
- [ ] Confirmar que os rótulos nos nós (train_code + horário) aparecem ao entrar na linha e somem ao sair
- [ ] Passar o mouse sobre um nó individual (círculo verde): tooltip deve mostrar Trem / Estação / Horário específicos do nó
- [ ] O tooltip deve seguir o mouse enquanto ele se move sobre a linha

## Deselect Automático por Inatividade
- [ ] Selecionar um trem (clique na linha ou na sidebar): nós/círculos aparecem, linha fica highlighted na sidebar
- [ ] Não interagir com o gráfico por 30 segundos
- [ ] Confirmar que os nós desaparecem e o trem perde destaque automaticamente
- [ ] Confirmar que o auto-scroll retoma centralizado no horário atual após o deselect

## Porção Passada como Realizado
- [ ] Verificar que linhas à **esquerda** da linha amarela (agora) são **sólidas** (cor vermelha, estilo "realizado")
- [ ] Verificar que linhas à **direita** da linha amarela são **tracejadas** (azul/ciano, estilo "planejado")
- [ ] Selecionar um trem que esteja parcialmente no passado: clicar tanto na parte sólida quanto na tracejada deve selecionar o trem igualmente
- [ ] Aguardar 15 segundos: confirmar que o ponto de corte avança com o relógio
- [ ] Clicar em "Mostrar Realizado": o overlay de dados mock deve aparecer corretamente acima das linhas existentes

## Diálogo genérico

1. Abra qualquer fluxo que use `showDialog` (após as próximas tasks, ex.: "Nova Viagem" na view Grades).
2. Confirme que o campo obrigatório vazio impede o "Confirmar" (foco volta ao campo).
3. Confirme que "Cancelar" fecha o diálogo sem aplicar nenhuma mudança.

## Menu de contexto genérico

1. Após a Task 13 estar implementada, clique com o botão direito num nó de viagem na view Grades.
2. Confirme que o menu aparece na posição do cursor.
3. Confirme que clicar fora do menu o fecha sem executar nenhuma ação.

## Alternância de modo (Operacional / Grades)

1. Ao carregar a página, confirme que a aba "Operacional" está ativa e o gráfico do dia aparece.
2. Clique em "Grades" — confirme que a área operacional some (sem perder o estado do gráfico) e a view de grades aparece.
3. Clique de volta em "Operacional" — confirme que o gráfico volta exatamente como estava (mesmo scroll, mesma seleção).

## Grades — lista e CRUD

1. Abra "Grades" — confirme "Grade Base CPTM" na lista.
2. "Nova Grade" com um nome — confirme que aparece selecionada na lista.
3. "Renomear" — confirme que o nome muda na lista.
4. "Salvar Como" — confirme uma cópia com o novo nome, com as mesmas viagens.
5. "Excluir" — confirme que some da lista; tentar excluir a única grade restante deve mostrar um erro, não excluir.
6. "Carregar p/ Hoje" — confirme o diálogo de confirmação, e que a tela volta para "Operacional" mostrando as viagens carregadas.

## Editor de grade (canvas somente leitura)

1. Em "Grades", selecione uma grade com viagens.
2. Confirme que as linhas aparecem no canvas do editor, no mesmo layout do gráfico operacional.
3. Confirme que não há nós arrastáveis nem linha "agora" nem auto-scroll nessa view.

## Criação de viagem em duas etapas

1. Em "Grades", botão direito no canvas → "Nova Viagem".
2. Clique em dois pontos do canvas (estações/horários diferentes) — confirme que o diálogo mostra origem/destino corretos.
3. Preencha prefixo, número de viagens e intervalo; confirme — as novas linhas aparecem no canvas, espaçadas pelo intervalo.
4. Tente confirmar sem prefixo — confirme que o foco volta ao campo e nada é criado.

## Editar prefixo pós-criação

1. Em "Grades", botão direito numa viagem existente → "Editar prefixo".
2. Troque o prefixo e confirme — a viagem e as demais do mesmo sentido são renumeradas.

## Criar interdição

1. Botão direito num ponto vazio do gráfico — confirme que aparece o menu de contexto com a opção "🚧 Interditar via".
2. Clique na opção — confirme o cursor em cruz e que um retângulo tracejado começa a aparecer e seguir o mouse conforme ele se move (âncora no ponto do botão direito).
3. Clique num segundo ponto (tempo/estação diferente) — confirme que o retângulo tracejado some e o diálogo abre com hora inicial/final pré-preenchidas pelos dois pontos.
4. Preencha a descrição e confirme — a chamada `POST /api/interdictions` deve retornar 200 (verificar na aba Network) e o retângulo vermelho translúcido definitivo aparece no gráfico com a descrição como rótulo.
5. Repita o botão direito num ponto vazio enquanto já há um retângulo em andamento (não deveria acontecer na prática, mas) — confirme que um segundo menu não abre por cima do arraste em curso.

## Editar/excluir interdição

1. Com uma interdição criada, confirme o retângulo vermelho translúcido no gráfico, com a descrição visível.
2. Clique no retângulo — confirme o diálogo abre pré-preenchido.
3. Altere a descrição, salve — confirme que o rótulo atualiza.
4. Reabra e clique "Excluir" — confirme o retângulo some do gráfico.

## Deslocamento de viagem retida pela interdição

1. Crie uma interdição que afete dois trens de sentidos opostos com tempos de cruzamento próximos.
2. Confirme que o trem retido é desenhado como: diagonal normal até `S_prev` (a última estação real antes da faixa), um segmento **reto e horizontal exatamente sobre a linha de grade de `S_prev`** (de `arrival_time` original até o novo `departure_time`), depois diagonal normal — com a mesma inclinação (velocidade) do resto da viagem — até a próxima parada. Nada de cotovelo na borda do retângulo vermelho.
3. Selecione o trem retido e confirme que paradas **antes** de `S_prev` (incluindo a origem) não mudaram; só `S_prev.departure_time` em diante.
4. Confirme que o cruzamento entre as duas retas (retida e prioritária) cai exatamente na borda do retângulo (topo ou base), nunca no meio.
5. Confirme que um trem que cruza sem ser retido (primeiro da fila) continua com uma linha reta normal, sem nenhum deslocamento.
6. Numa interdição que afete vários pares de trens em sequência (janela de tempo larga, ex.: 4h), confirme que os cruzamentos aparecem em fila, um de cada vez, todos tocando a borda — nenhuma linha deve "ir e voltar" (zigue-zague) ou duas linhas de sentidos opostos cruzarem dentro da faixa. Confirme isso especificamente para cruzamentos que já ficaram no **passado** (trecho vermelho "Realizado") — não só nos futuros (tracejado azul).
7. Recarregue a página com a interdição ainda ativa — confirme que a viagem retida continua desenhada do mesmo jeito (mesmo deslocamento), sem depender da resposta original de criação.

## Cascata de atraso preserva o headway

1. Com um trem retido por uma interdição (delay > 0), identifique a próxima partida do **mesmo sentido** depois dele na grade.
2. Confirme que essa partida seguinte também deslocou — pelo mesmo Δt do trem retido — e que o intervalo (headway) entre as duas partidas ficou igual ao original.
3. Confirme que uma partida do **sentido oposto** que ocorre depois do trem retido NÃO desloca (a cascata é só por sentido).
4. Numa interdição com vários pares retidos em sequência, confirme que os deslocamentos se acumulam corretamente ao longo do dia (cada nova retenção soma seu próprio Δt aos trens seguintes, sem sobrescrever o que já tinha sido deslocado por retenções anteriores).

## Interdição aciona regulação automática

1. Configure um tempo de volta numa estação onde uma viagem atrasada pela interdição termina.
2. Ligue a regulação automática (ícone no header).
3. Crie uma interdição que atrase essa viagem — confirme que a partida pareada naquela estação também se ajusta (rampa), sem precisar clicar em "Regular" manualmente.
4. Com a regulação automática desligada, repita — confirme que a partida pareada NÃO se ajusta sozinha.

## Sincronização ao vivo de interdições

1. Abra o app em duas abas.
2. Crie uma interdição na aba A — confirme que a aba B atualiza sozinha (retângulo e doglegs).
3. Edite e depois exclua na aba A — confirme que a aba B acompanha as duas mudanças.

## Suprimir a partir daqui / cancelar

1. Selecione uma viagem, botão direito num nó intermediário → "Suprimir a partir daqui" → confirme.
2. Verifique (aba Network) que `active_last_seq` corresponde ao nó anterior ao clicado.
3. Repita no primeiro nó da viagem — confirme que a mensagem de confirmação menciona cancelamento da viagem inteira.

## Alterar partida

1. Selecione uma viagem, botão direito no nó de partida atual → "Alterar partida".
2. Clique num nó mais à frente da mesma viagem — confirme que a partida muda para essa estação, mantendo o horário que a parada já tinha.
3. Tente escolher um nó de outra viagem enquanto o modo está ativo — confirme que nada acontece.

## Renderização de trecho suprimido

1. Suprima parte de uma viagem — confirme que o trecho suprimido fica tracejado/cinza, sem alça de arraste.
2. Confirme que o trecho ainda ativo continua arrastável normalmente.
3. Cancele uma viagem inteira (suprimir a partir do primeiro nó) — confirme que a viagem inteira fica tracejada.

## Configurar tempo de volta

1. Clique na linha horizontal de uma estação no gráfico — confirme o diálogo "Tempo de volta em [estação]".
2. Digite "10:00", confirme — reabra e confirme que o valor persiste.
3. Limpe o campo, confirme — reabra e confirme que está vazio (removido).

## Pareamento e conector de tempo de volta

1. Configure um tempo de volta numa estação com ao menos uma chegada e uma partida de sentido oposto.
2. Confirme o conector horizontal ligando chegada e partida na linha da estação.
3. Arraste a partida pra antes do mínimo — confirme que o conector fica vermelho, sem bloquear o arraste.
4. Confirme que uma estação **sem** tempo de volta configurado não mostra nenhum conector, mesmo com chegadas/partidas de sentido oposto.

## Cadeia de rotação ao passar o mouse

1. Configure tempos de volta que encadeiem ao menos 3 viagens (A -> B -> C).
2. Passe o mouse sobre a viagem A — confirme A em ênfase total, B mais discreta, C ainda mais discreta.
3. Tire o mouse — confirme que tudo volta ao normal.

## Toggle de regulação automática

1. Confirme o ícone ⚙️ no header, inativo por padrão.
2. Clique — confirme que ativa visualmente e persiste (recarregar a página mantém o estado).

## Regular manualmente uma violação

1. Configure um tempo de volta e provoque uma violação (arraste uma chegada para atrasar).
2. Selecione a viagem de partida violada, botão direito no nó de origem — confirme a opção "Regular".
3. Clique — confirme que a partida (e intermediárias, se houver) se ajustam e a violação some.
