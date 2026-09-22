# 🚀 FINAL_BOT — Intelligent Automated Trading System

> **FINALBOT** is an institutional-grade automated binary options trading system driven by a **4-Stage Quantitative Pipeline**, **Pre-Trade 3D Asset Screening**, and a **Dual-Brain Machine Learning & Cloud AI** analysis engine.

---

## 🌟 Key Features

- 🎯 **Pre-Trade 3D Asset Screening**: Scans 34 focused currency pairs, filtering for Payout $\ge$ 84%, analyzing 7 Quant Skills + 4 Binary-Specific Edges, and calculating Support/Resistance "Room-to-Run" across 4 timeframes.
- 🏗️ **4-Stage Quantitative Pipeline**: Immutable data ingestion, centralized indicator evaluation, AI/ML decision-making, and strict execution gating.
- 🧠 **Dual-Brain Analysis**: Switch seamlessly between on-device Machine Learning (`LightGBM` + `Amazon Chronos`) and Cloud Generative AI (`Google Gemini Flash Lite`).
- 🛡️ **Institutional Risk Management**: 24-point Execution Gate, fixed stake management, daily loss limits, and strict fail-fast validation.
- ⚡ **Sub-Second Execution**: Time-synced to the millisecond, ensuring precise entry at candle boundaries.

---

## 🏛️ System Architecture

The system is divided into a **Pre-Trade Screening Phase (Phase 0)** and a **4-Part Live Trading Loop**:

| Phase / Part | Module | Core Responsibility | Status |
|:---|:---|:---|:---:|
| **Phase 0** | `symbols_scanner/` | Scans 34 pairs → Filters Payout $\ge$ 84% → Analyzes 7 Skills + 4 Edges + S/R → Ranks and saves Top 4 to `symbols.json`. | 🔒 **Complete** |
| **Part 1** | `data_feed/` | Connects to broker (IQ Option) → Syncs server time → Fetches/validates the active mode's candles → Writes `data_base/output_feed`. | 🔒 **Immutable** |
| **Part 2** | `data_evaluate/` | Computes indicators via centralized `IndicatorStore` (SSOT) → Runs 10 Advanced Tools & 6 Tier Engines → Generates a strict 99-line Prompt Payload (`.txt`). | 🔒 **Immutable** |
| **Part 3** | `data_decision/` | Reads the selected mode's Payload from disk → Runs strategies, Gemini, or ML analysis → Writes a mode-specific Decision JSON. | 🛠️ **Active Dev** |
| **Part 4** | `data_trade/` | Validates Money Management rules → Passes through 24 Execution Gates (Confidence $\ge$ 60% required) → Executes order via `broker_executor.py` → Tracks results. | 🛠️ **Active Dev** |

### Mode-Specific Timeframes

The evaluation modes use separate data contracts. One process runs one selected mode at a time; changing mode changes the analysis path and the candle timeframes that must be prepared.

| Mode | Required timeframes | Role |
|:---|:---|:---|
| `strategies_mode` | **S30, M1, M5** | Rule-based strategies; M15 is not fetched or calculated. The legacy `m15_bias` payload field remains as `NOT_CALCULATED` for schema compatibility only. |
| `ai_mode` | **M15** plus the timeframes required by the AI prompt | Cloud AI analysis with M15 as the primary higher-timeframe context. |
| `ml_mode` | **M15** plus the timeframes required by the ML/Chronos model | Machine-learning analysis with M15 as the higher-timeframe context. |

Do not mix a timeframe from another mode into the current mode's payload. `strategies_mode` is intentionally separated from `ai_mode` and `ml_mode`; it is not merely a different decision engine over the same candle set.

The durable mode routing is:

`runner.py → data_feed/output_feed → data_evaluate/<mode>/output_evaluate/<mode> → data_decision/<mode>/output_decision/<mode> → data_trade`

Decision files are written to `strategies_decision`, `ai_decision`, or `ml_decision` according to the active mode. Part 4 selects only the matching directory, then reads the referenced Payload from disk for the final gate.

---

## 🗂️ Project Directory Structure

```text
FINALBOT_Begin/
├── main.py                      # System entry point
├── runner.py                    # Core loop controller (PureAIRunner), time-synced execution
├── .env                         # Environment variables & API Keys (Do not commit)
├── config_setting/              # Centralized configuration (settings.json, symbols.json)
├── symbols_scanner/             # [Phase 0] Pre-trade asset screening & ranking engine
├── data_feed/                   # [Part 1] Broker data ingestion & validation (Immutable)
├── data_evaluate/               # [Part 2] Indicator computation & payload generation (Immutable)
├── data_decision/              # [Part 3] Strategies, ML/Chronos, and Cloud AI dispatchers
├── data_trade/                  # [Part 4] Risk management, execution gates, and order tracking
├── data_base/                   # Output storage (OHLCV CSVs, 99-line payloads, trade history)
├── logs/                        # Second-by-second execution and error logs
└── docs/                        # Comprehensive system documentation and architecture specs
```

---

## ⚙️ Getting Started

### 1. Prerequisites
- Python 3.10+
- IQ Option Account (Demo or Live)
- Required Python packages (e.g., `iqoptionapi`, `lightgbm`, `pandas`, `numpy`, `google-generativeai`, `ta-lib`)

### 2. Configuration
1. Set broker credentials in the process environment; never commit them:
   - `IQ_EMAIL`
   - `IQ_PASSWORD`
2. Review and adjust `config_setting/settings.json` for:
   - Active mode (`strategies_mode`, `ai_mode`, or `ml_mode`)
   - Risk parameters (Fixed stake amount, daily loss limits)
   - Target payout percentage (default: 84%)
   - Broker account (`DEMO`/`PRACTICE` for broker-connected dry operation, or `REAL`)
   - `data_trade.enable_live_execution=true`; disabling it is a fail-fast error, not signal-only/mock execution.

### 3. Running the System

**Step 1: Run the Asset Scanner (Phase 0)**  
*(This will generate the top 4 ranked pairs in `config_setting/symbols.json`)*
```bash
python symbols_scanner/main_filter.py
python symbols_scanner/secondary_filter.py
```

**Step 2: Start the Live Trading Loop**
```bash
python runner.py --mode strategies
# or: python runner.py --mode ai
# or: python runner.py --mode ml
```

The selected mode is process-wide for the complete cycle. `runner.py` passes only symbols between coordinators; each Part reads the previous Part's durable files from disk. The broker adapter is the real configured adapter (`IQ_OPTION` by default); no mock, fake broker, simulated order, or signal-only execution path is permitted.

### End-to-End Flow

```text
main.py / runner.py
  -> BrokerFactory -> real IQ Option adapter (DEMO/PRACTICE or REAL)
  -> Part 1 data_feed
       -> data_base/output_feed/<SYMBOL>/<SYMBOL>_<TIMEFRAME>.csv
  -> Part 2 data_evaluate/<active_mode>
       -> data_base/output_evaluate/<active_mode>/<SYMBOL>/<ID>.txt
  -> Part 3 data_decision
       -> strategies_decision, ai_decision, or ml_decision/<SYMBOL>/<ID>.json
  -> Part 4 data_trade
       -> mode-matched decision JSON
       -> Payload filepath from JSON
       -> ExecutionGate -> MoneyManager -> BrokerExecutor -> real broker order
       -> OrderTracker / trade history
```

Part boundaries are disk-only. DataFrames, payload dictionaries, and payload text may exist inside one Part while it is processing, but they must not be passed to another Part. A missing file, invalid mode, missing broker connection, or disabled live execution stops the cycle explicitly.

---

## 🖥️ Expected Console Output (Startup Sequence)

```text
01:34:41 - Connecting to broker... | IQ Option
01:34:44 - IQ Option connection successful
01:34:47 - Scanning and evaluating suitable assets...
01:35:05 - Asset screening complete. Top pairs selected.
01:35:05 - Active symbols: GBPUSD-OTC, GBPJPY-OTC, AUDUSD-OTC, EURUSD-OTC
01:35:05 - Time Sync: 0.216s
01:35:05 - Account: DEMO | Balance: $24.25
01:35:05 - Economic Calendar loaded for today.
01:35:11 - ML Brain connected successfully (Model: LIGHTGBM_CHRONOS)
01:35:15 - Candle data validated (250 candles S30/M1/M5/M15): 4 pairs ready.
01:35:15 - Awaiting next minute boundary for analysis cycle (Starts at 01:36:01)...
```

---

## 🛡️ Strict System Disciplines (Core Rules)

1. **Immutability of Part 1 & 2**: The `data_feed/` and `data_evaluate/` modules are 100% complete and **must not be modified**.
2. **Single Source of Truth (SSOT)**: No duplicate indicator calculations. All modules must reference the centralized `IndicatorStore`.
3. **Single Gateway Authority**: Only the active mode's Part 2 `orchestrator.py` reads raw CSV files, and Part 3 reads the persisted payload through the mode's decision dispatcher.
4. **99-Line Explicit Schema**: Prompt payload files must be **exactly 99 lines**, with a strict retention policy of the latest 30 files per asset.
5. **Background Process Rule**: Always test via `runner.py` in an open terminal. **Never** leave the process running hidden in the background. Kill it immediately after testing.

---

## 📈 Trading Strategy — Believe (NEMESIS)

**Believe** คือกลยุทธ์หลักที่บอทใช้ในการตัดสินใจเข้าออเดอร์ ออกแบบโดย NEMESIS TRADER

Part 2 writes the Believe payload with the fixed roles `S30 = Entry`, `M1 = Trigger`,
and `M5 = Context`, with a fixed five-minute holding period. The payload includes
separate S30 indicators, M1/M5 evidence, divergence and candle-risk fields, and
grid candidates for all three timeframes. It never calculates or fetches M15 in
`strategies_mode`; the legacy M15 compatibility field is `NOT_CALCULATED`.

| รายการ | ค่า |
|:---|:---|
| **Candle TF** | S30 (30 วินาที) — Primary signal chart |
| **Expiry / ถือครอง** | 5 นาที |
| **TF ที่ใช้ในระบบ** | S30 (Entry), M1 (Trigger), M5 (Context) |

### 🔢 Indicators (Core — 3 ตัวบังคับ)

| # | Indicator | Settings | เงื่อนไขเข้า CALL | เงื่อนไขเข้า PUT |
|---|-----------|----------|-----------------|----------------|
| 1 | **Bollinger Band %B** | Period 20, StdDev 2 | BB% แตะเส้น 0 (ล่าง) | BB% แตะเส้น 1 (บน) |
| 2 | **Stochastic** | **13-10-3**, เส้น 10/90 | STO โผล่ขึ้นจากเส้น 10, hook up, ข้าม 50 | STO โผล่ลงจากเส้น 90, hook down, ข้าม 50 |
| 3 | **MA Crossover** | Fast (แดง) vs Slow (เขียว) | เส้นแดงตัดเขียวขึ้น | เส้นแดงตัดเขียวลง |

### 🛑 Risk Filters (บังคับทุกข้อ)
1. ห้ามมีเส้นกริด (Support/Resistance) ขวางข้างหน้า
2. ห้ามมีแท่งเทียนสีเทา (Gray/Doji candle)
3. STO ห้ามพันกัน (ห้าม tangled)

### 🔀 เทคนิคผสมผสาน (EXTREME level)
ผสม Divergence จาก AP/NS (STO/RSI) + MACD ข้ามเส้น 0 ก่อน แล้วหาจุดเข้าด้วย Believe

---

## 📚 Documentation

For deep dives into specific components, refer to the `docs/` directory:
- [กระบวนการทำงานของบอท ส่วนที่ 1 INPUT](docs/กระบวนการทำงานของบอท%20ส่วนที่%201%20INPUT/กระบวนการทำงานของบอท%20ส่วนที่%201%20INPUT.md)
- [กระบวนการทำงานของบอท ส่วนที่ 2 PROCESS](docs/กระบวนการทำงานของบอท%20ส่วนที่%202%20PROCESS/7_กระบวนการทำงานของบอท%20ส่วนที่%202%20PROCESS.md)
- [กระบวนการทำงานของบอท ส่วนที่ 3 OUTPUT](docs/กระบวนการทำงานของบอท%20ส่วนที่%203%20OUTPUT/กระบวนการทำงานของบอท%20ส่วนที่%203%20OUTPUT.md)
- [Model Critique & Roadmap](docs/MODEL_CRITIQUE_AND_ROADMAP.md)

---
> **⚠️ Disclaimer**: This system is for educational and quantitative research purposes. Trading binary options carries a high level of risk and may not be suitable for all investors. Always test thoroughly in a DEMO environment before deploying real capital.
