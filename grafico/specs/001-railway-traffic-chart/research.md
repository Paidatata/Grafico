# Research: DXF Parsing & Time-Distance Visualization

This document details the technical discoveries and architectural decisions for the Railway Traffic Chart feature.

## 1. DXF Coordinate Mapping Analysis

Through reverse-engineering the AutoCAD drawing `L10 DOM.dxf`, we mapped the geometric coordinates to railway time and distance axes.

### Y-Axis (Station Sequence)
The drawing contains two vertical segments (rows) mapping the unified CPTM Line 710 service:

- **Row 1 (Line 10 - Turquesa)**: Spans Y = `500.32` to `5860.32` (from Rio Grande da Serra to Barra Funda).
- **Row 2 (Line 7 - Rubi)**: Spans Y = `6180.32` to `11520.32` (from Luz to Jundiaí).

The exact station Y-level mapping is:

| Station Code | Station Name | Y Coordinate | Line |
|---|---|---|---|
| **RGS** | Rio Grande da Serra | 500.32 | Line 10 |
| **RPI** | Ribeirão Pires | 1100.32 | Line 10 |
| **GPT** | Guapituba | 1660.32 | Line 10 |
| **MAU** | Mauá | 2100.32 | Line 10 |
| **CPV** | Capuava | 2500.32 | Line 10 |
| **SAN** | Santo André | 2980.32 | Line 10 |
| **PSA** | Prefeito Saladino | 3220.32 | Line 10 |
| **UTG** | Utinga | 3420.32 | Line 10 |
| **SCS** | São Caetano do Sul | 3860.32 | Line 10 |
| **TMD** | Tamanduateí | 4180.32 | Line 10 |
| **IPG** | Ipiranga | 4380.32 | Line 10 |
| **MOC** | Juventus-Mooca | 4740.32 | Line 10 |
| **BAS** | Brás | 4980.32 | Line 10 |
| **LUZ** | Luz | 5380.32 | Line 10 |
| **BFU** | Barra Funda | 5860.32 | Line 10 |
| **LUZ** | Luz | 6180.32 | Line 7 |
| **ABR** | Água Branca | 6420.32 | Line 7 |
| **LPA** | Lapa | 6700.32 | Line 7 |
| **PQR** | Piqueri | 6980.32 | Line 7 |
| **PRU** | Pirituba | 7300.32 | Line 7 |
| **VCL** | Vila Clarice | 7500.32 | Line 7 |
| **JRG** | Jaraguá | 7900.32 | Line 7 |
| **VPL** | Vila Aurora | 8260.32 | Line 7 |
| **PRT** | Perus | 8700.32 | Line 7 |
| **CAI** | Caieiras | 9260.32 | Line 7 |
| **FMO** | Franco da Rocha | 9500.32 | Line 7 |
| **BFI** | Baltazar Fidélis | 9940.32 | Line 7 |
| **FDR** | Francisco Morato | 10300.32 | Line 7 |
| **BTJ** | Botujuru | 10580.32 | Line 7 |
| **CLP** | Campo Limpo Paulista | 10900.32 | Line 7 |
| **VAU** | Várzea Paulista | 11220.32 | Line 7 |
| **JUN** | Jundiaí | 11520.32 | Line 7 |

### X-Axis (Time scale)
- Grid length: `28800` units represents 24 hours.
- Time resolution:
  - **1 hour = 1200 units**
  - **1 minute = 20 units**
  - **1 second = 0.333 units**
- Formula to convert geometric coordinate `X` to time:
  $$\text{Total Minutes} = \frac{X}{20.0}$$
  $$\text{Hour} = \lfloor \frac{\text{Total Minutes}}{60} \rfloor \pmod{24}$$
  $$\text{Minute} = \lfloor \text{Total Minutes} \rfloor \pmod{60}$$

---

## 2. Architectural Decisions

### DXF Data Extraction Method
- **Decision**: Custom light-weight line-by-line DXF parser in standard Python.
- **Rationale**: Re-writing/inspecting DXF group codes (0 for entities, 8 for layers, 10/20 for X/Y coordinates) avoids introducing external dependencies like `ezdxf`. It runs out of the box on standard Python 3 deployments and executes in milliseconds for the 17MB file.
- **Alternatives considered**:
  - `ezdxf`: Rejected because installing external packages requires user system modification and internet access, whereas native parsing is fully self-contained and sufficient for our needs.

### Frontend Rendering Engine
- **Decision**: Scalable Vector Graphics (SVG).
- **Rationale**: The user requirements mandate interactive node dragging on the frontend to edit schedule times and propagate updates downstream. SVG maps each station stop to a draggable DOM element `<circle>` and train lines to `<polyline>`. This lets us bind standard mouse/touch drag events directly to individual nodes.
- **Alternatives considered**:
  - HTML5 Canvas: Rejected because tracking drags/clicks on shapes inside canvas requires complex pixel collision algorithms and custom coordinate transformations, raising codebase complexity unnecessarily.
