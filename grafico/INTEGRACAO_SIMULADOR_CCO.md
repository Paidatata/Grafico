# Especificação de Integração: Telemetria Ferroviária / Simulador ➔ Gráfico CCO

Este documento especifica a arquitetura e contrato de dados para alimentação do **Gráfico Espaço-Tempo** (`Grafico`) a partir de fontes de telemetria (inicialmente o **Simulador CCO** e, futuramente, os sistemas reais de sinalização/rastreamento da ferrovia).

---

## 1. Diretriz Arquitetural

1. **Fluxo Uni-Direcional (Consumo de Telemetria)**:
   O `Grafico` atua como uma **ferramenta de visualização, monitoramento e planejamento de circulação**. Ele **somente consome** dados da ferrovia/simulador e **não envia comandos de volta** para a tração ou sinalização física/simulada.

2. **Propósito do Gráfico**:
   - **Planejamento de Circulação**: Desenhar interdições, ajustar horários e simular rampas de regulação para análise de impacto e tomada de decisão do controlador (CCO).
   - **Monitoramento Realizado vs. Planejado**: Comparar visualmente a grade teórica/programada com os horários reais percorrida pelos trens.

3. **Agnosticismo da Fonte de Dados**:
   A interface de entrada do `Grafico` é totalmente agnóstica. O contrato de telemetria é idêntico se a fonte for o **Simulador CCO** (fase de testes) ou o **Sistema de Sinalização Real** (fase de produção).

```
┌───────────────────────────────────────────────────────────┐
│              Fonte de Telemetria                          │
│                                                           │
│  ┌───────────────────────┐     ┌───────────────────────┐  │ (Eventos de Chegada/Partida / Posição)  ┌─────────────────────────┐
│  │     Simulador CCO     │ ou  │ Ferrovia Real (Sinal) │  │ ──────────────────────────────────────► │     Backend FastAPI     │ ──► Interface SVG
│  └───────────────────────┘     └───────────────────────┘  │                                         │        (Grafico)        │     (Gráfico CCO)
└───────────────────────────────────────────────────────────┘                                         └─────────────────────────┘
```

---

## 2. Contrato de Entrada de Dados (API de Telemetria)

### 2.1 Carga da Grade Teórica Programada (`POST /api/template/import`)

Disparado para carregar a programação teórica do dia.

```json
[
  {
    "trip_id": "TRIP_BFU-RGS_050000",
    "direction": "BFU-RGS",
    "train_code": "P0501",
    "stops": [
      { "station": "BFU", "time": "05:00:00" },
      { "station": "LUZ", "time": "05:08:00" },
      { "station": "BAS", "time": "05:13:00" },
      { "station": "SCS", "time": "05:28:00" },
      { "station": "SAN", "time": "05:37:00" },
      { "station": "MAU", "time": "05:46:00" },
      { "station": "RGS", "time": "05:57:00" }
    ]
  }
]
```

---

### 2.2 Eventos de Telemetria em Tempo Real (Chegada / Partida de Estação)

Conforme os trens progridem na simulação ou na ferrovia real, a fonte de telemetria envia atualizações dos eventos ocorridos em cada estação.

#### Endpoint recomendável: `POST /api/telemetry/event`
```json
{
  "event_type": "station_event",
  "trip_id": "TRIP_BFU-RGS_050000",
  "train_code": "P0501",
  "station_id": "LUZ",
  "action": "departure",
  "actual_time": "05:09:15"
}
```

* **Campos:**
  - `trip_id`: Identificador único da viagem associada ao trem.
  - `train_code`: Prefixo comercial do trem (ex: `"P0501"`).
  - `station_id`: Sigla da estação (`BFU`, `LUZ`, `BAS`, `SCS`, `SAN`, `MAU`, `RGS`).
  - `action`: `"arrival"` (evento de entrada na estação) ou `"departure"` (evento de partida da estação).
  - `actual_time`: Horário exato em que o evento ocorreu no formato `"HH:MM:SS"`.

---

### 2.3 Atualização de Previsão de Horários (`POST /api/stops/shift`)

Quando o sistema de rastreamento/simulador detecta um atraso e recalcular a estimativa de chegada para as estações futuras:

```json
{
  "trip_id": "TRIP_BFU-RGS_050000",
  "station_id": "BAS",
  "new_time": "05:15:30"
}
```

---

## 3. Exemplo Prático de Envio em Python (Adapter de Telemetria)

Script genérico para ler eventos do simulador (ou de um broker MQTT/Kafka da ferrovia real) e publicar no `Grafico`:

```python
import requests

GRAFICO_API = "http://localhost:8000/api"

def registrar_evento_ferrovia(trip_id, station_id, action, actual_time):
    """Envia um evento real/simulado de chegada ou partida para o Gráfico."""
    payload = {
        "event_type": "station_event",
        "trip_id": trip_id,
        "station_id": station_id,
        "action": action,
        "actual_time": actual_time
    }
    # Atualiza a paradas no gráfico para refletir o realizado
    resp = requests.post(f"{GRAFICO_API}/stops/shift", json={
        "trip_id": trip_id,
        "station_id": station_id,
        "new_time": actual_time
    })
    print(f"[{actual_time}] Trem {trip_id} - {action} em {station_id}: HTTP {resp.status_code}")
```

---

## 4. Benefícios dessa Arquitetura

1. **Independência dos Sistemas**: O simulador e a ferrovia real operam de forma autônoma sem dependência síncrona do gráfico.
2. **Zero Risco Operacional**: Como o gráfico é somente leitura em relação aos trens, ferramentas de planejamento e simulação de interdições podem ser usadas livremente pelo operador CCO para prever cenários sem risco de interferir na circulação real.
3. **Transição Transparente (Simulador ➔ Produção)**: A substituição do simulador pela telemetria real exige apenas alterar a fonte emissora do JSON de eventos, mantendo 100% da API e do frontend intactos.
