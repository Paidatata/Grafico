# Testes Manuais: Gráfico de Circulação Ferroviária Interativa

Este documento descreve os cenários de teste manual para validar a renderização do gráfico, a manipulação de nós de tempo e a propagação de atrasos.

## Cenário 1: Importação de Dados e Troca de Linha

1. Abra `frontend/src/index.html` em um navegador.
2. Verifique se o app inicia carregando a **Linha 10 (Turquesa)** por padrão.
3. Se o arquivo `schedule.json` não carregar automaticamente (devido a restrições CORS no protocolo `file://`), clique em **"Importar JSON"** e escolha o arquivo `frontend/data/schedule.json` ou `backend/data/schedule.json`.
4. Verifique se a lista à esquerda exibe os trens (ex: `BFU-RGS 043600`, `BFU-RGS 043730`).
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
   - Os horários na lista lateral à esquerda se atualizam assim que você solta o mouse.

---

## Cenário 4: Comparação com Circulação Realizada

1. Clique no botão **"Mostrar Realizado"** na barra lateral.
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
