# 🚀 FINAL_BOT — Intelligent Automated Trading System

> **FINALBOT** is an institutional-grade automated binary options trading system driven by a **4-Stage Quantitative Pipeline**, **Pre-Trade 3D Asset Screening**, and a **Dual-Brain Machine Learning & Cloud AI** analysis engine.
>
> ✅ **เอกสารฉบับนี้ตรวจทานให้ตรงโค้ดจริง ณ commit `e709349` (2026-09-26)** — ทุกตัวเลข/เส้นทาง/พารามิเตอร์อ้างอิงจาก source

---

## 🌟 Key Features

- 🎯 **Pre-Trade 3D Asset Screening**: scans 34 focused currency pairs, filters for Payout ≥ 84%, analyzes 7 Quant Skills + 4 Binary-Specific Edges, and calculates Support/Resistance "Room-to-Run" across timeframes.
- 🏗️ **4-Stage Quantitative Pipeline**: immutable data ingestion, centralized indicator evaluation, mode-specific decision-making, and strict execution gating.
- 🧠 **Dual-Brain Analysis**: on-device ML (`LightGBM` + `Chronos-2 ONNX`) or Cloud Generative AI (`Google Gemini`) or rule-based **Believe (NEMESIS)** — one mode per process.
- 🛡️ **Institutional Risk Management**: Execution Gate (16 rejection checks) + Money Manager (7 risk gates), fixed stake, daily limits, confidence ≥ 55%, and strict fail-fast validation.
- 🔐 **Env-only secrets**: `config_loader` ให้ environment (`.env`) ชนะ `settings.json` เสมอ
  > 🚨 **สถานะจริง 2026-09-27:** commit `a179f32` ใส่ค่า credential จริงกลับเข้าไปใน `settings.json` อีกครั้ง
  > → ถือว่า**รั่วซ้ำ** ต้อง rotate ทันที และรอการเคาะว่าจะ blank อีกหรือไม่ (ประเด็น F-6b reopen)
- ⚡ **Sub-Second Execution**: time-synced to the millisecond; entries fire at S30 candle boundaries.

---

## 🏛️ System Architecture

| Phase / Part | Module | Core Responsibility | Status |
|:---|:---|:---|:---:|
| **Phase 0** | `symbols_scanner/` | Scan 34 pairs → Payout ≥ 84% → 7 Skills + 4 Edges + S/R → rank Top-N to `symbols.json` | 🔒 Complete |
| **Part 1** | `data_feed/` | Connect IQ Option → sync server time → fetch/validate the mode's candles → write `data_base/<mode>/output_feed` | 🔒 Immutable |
| **Part 2** | `data_evaluate/<mode>/` | Compute indicators via centralized `IndicatorStore` (SSOT) → run engines/tools → write the **99-line payload** `.txt` | 🔒 Contract-locked |
| **Part 3** | `data_decision/<mode>/` | Read payload from disk → Believe / Gemini / ML analysis → write mode-specific Decision JSON | 🛠️ Active Dev |
| **Part 4** | `data_trade/strategies_mode/` | Mode-matched decision read → Execution Gate → Money Manager → Broker Executor → Order Tracker | 🛠️ Active Dev |

> 🧭 **Central dispatcher:** `config_setting/mode_loader.py` normalizes the mode alias and loads the
> mode-specific orchestrator + executor for all 4 Parts (single source of truth for mode routing).

### Mode-Specific Timeframes & Contracts

| Mode | Required timeframes | Role / notes |
|:---|:---|:---|
| `strategies_mode` | **S30, M1, M5** (+ **M15 fetched** for the `m15_window` check) | Rule-based Believe · S30=Entry, M1=Trigger, M5=Context · **M15 is never emitted on the payload** (`m15:` section disabled) · **expiry = 3 นาที** |
| `ai_mode` | M1, M5, **M15** | Cloud Gemini analysis · expiry = 5 นาที |
| `ml_mode` | M1, M5, **M15** | LightGBM + Chronos · expiry = 5 นาที |

Do not mix a timeframe from another mode into the current mode's payload.

### Durable mode routing (disk-only boundaries)

```text
runner.py → data_feed → data_base/<mode>/output_feed/<SYMBOL>/<SYMBOL>_<TF>.csv
          → data_evaluate/<mode> → data_base/<mode>/output_evaluate/<SYMBOL>/<ID>.txt   (99 lines)
          → data_decision/<mode> → data_base/<mode>/output_decision/<mode>_decision/<SYMBOL>/<ID>.json
          → data_trade (mode-matched) → gate → money → broker → order tracker
          → data_base/<mode>/output_trade/trades_history.csv
```

Part boundaries are **disk-only**: DataFrames/payloads never cross Parts through RAM.
A missing file, invalid mode, missing broker connection, or disabled live execution stops the cycle explicitly.

---

## 🗂️ Project Directory Structure

```text
FINALBOT_AiBegin/
├── main.py                      # System entry point
├── runner.py                    # Core loop controller (DataFeedRunner), S30-boundary execution
├── requirements.txt             # Python dependencies (import-scanned)
├── .env.example                 # Template — copy to .env and fill real secrets (never commit .env)
├── .gitignore                   # Keeps .env / logs / data_base / backups out of git
├── agent.md                     # Athena operating rules (project governance)
├── config_setting/              # settings.json (SSOT), symbols.json, mode_loader.py, config_loader.py
├── symbols_scanner/             # [Phase 0] pre-trade screening & ranking
├── data_feed/                   # [Part 1] รายโหมด: strategies_mode/ · ai_mode/ (ยังไม่มี ml_mode/)
├── data_evaluate/               # [Part 2] รายโหมด: strategies_mode/ · ai_mode/ · ml_mode/ + mode_loader.py
├── data_decision/               # [Part 3] strategies_mode (Believe) / ai_mode (Gemini + ML)
├── data_trade/                  # [Part 4] strategies_mode/executor_manager + execution_gate/*
├── data_base/                   # per-mode outputs: output_feed / output_evaluate / output_decision / output_trade
├── athena_traderist/            # ⚠️ parallel Athena experiment (state files only — see audit F-8)
├── logs/                        # second-by-second execution & error logs
└── docs/                        # Part 1-4 docs + `strategies nemesis/` (E-BOOK V1/V2)
```

---

## ⚙️ Getting Started

### 1. Prerequisites
- Python 3.10+ (repo มี `.pyc` ของ 3.11/3.12 — ควร pin ให้ตรงเครื่องที่รัน)
- IQ Option account (**DEMO/PRACTICE** recommended)
- `pip install -r requirements.txt`
  (imports จริง: `iqoptionapi`, `pandas`, `numpy`, `lightgbm`, `google-generativeai`,
  `python-dotenv`, `PyYAML`, `requests`, `beautifulsoup4`, `onnxruntime`)
- Single-instance lock ใช้ `msvcrt` บน Windows และ `fcntl` บน POSIX

### 2. Configuration
1. **Secrets ผ่าน environment เท่านั้น:**
   ```powershell
   copy .env.example .env     # แล้วเติม IQ_EMAIL / IQ_PASSWORD / GEMINI_API_KEY
   ```
   `config_loader._apply_env_overrides()` ให้ค่าจาก env ชนะ `settings.json`
   ⚠️ ณ commit `a179f32` มีค่าจริงค้างใน `settings.json` — อย่าเชื่อไฟล์นั้นว่าเป็นแหล่ง secret และต้อง rotate
2. ปรับ `settings.json` สำหรับ: active mode · risk parameters (stake, daily limits) ·
   target payout (default 84) · broker account (`DEMO`/`PRACTICE`/`REAL`) ·
   `data_trade.enable_live_execution` (ปิด = fail-fast error ไม่ใช่ signal-only)

### 3. Running

**Step 1 — Phase 0 scanner**
```bash
python symbols_scanner/main_filter.py
python symbols_scanner/secondary_filter.py
```

**Step 2 — live loop (one mode per process)**
```bash
python runner.py --mode strategies
# or: python runner.py --mode ai
# or: python runner.py --mode ml
```

The broker adapter is the real configured adapter (`IQ_OPTION`); no mock, fake broker,
simulated order, or signal-only execution path is permitted.

### End-to-End Flow

```text
main.py / runner.py
  -> BrokerFactory -> real IQ Option adapter (DEMO/PRACTICE or REAL)
  -> Part 1 data_feed -> data_base/<mode>/output_feed/<SYMBOL>/<SYMBOL>_<TF>.csv
  -> Part 2 orchestrator (<mode>) -> data_base/<mode>/output_evaluate/<SYMBOL>/<ID>.txt   (99 lines)
  -> Part 3 (<mode>) -> data_base/<mode>/output_decision/<mode>_decision/<SYMBOL>/<ID>.json
  -> Part 4 (mode-matched) -> ExecutionGate -> MoneyManager -> BrokerExecutor -> OrderTracker
  -> data_base/<mode>/output_trade/trades_history.csv
```

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
01:35:15 - Candle data validated (250 candles): pairs ready.
01:35:15 - Awaiting next S30 boundary for analysis cycle (Starts at 01:35:31)...
```

---

## 🛡️ Strict System Disciplines (Core Rules)

1. **Part 1/2 contract**: `data_feed/` และ `data_evaluate/` รักษา SSD boundary, timeframe contract และ
   payload schema 99 บรรทัด — การแก้ใด ๆ ต้องคงสัญญาเหล่านี้
2. **99-line payload**: serializer กรองด้วย whitelist `allowed_prefixes` → เกิน 99 = fail-fast · ไม่ครบ = pad
3. **Single Source of Truth**: indicator ทั้งหมดคำนวณผ่าน `IndicatorStore` เท่านั้น
4. **Single Gateway Authority**: orchestrator ของโหมดอ่าน CSV ดิบ · Part 3 อ่าน payload จากดิสก์ ·
   Part 4 อ่าน decision ของโหมดตัวเองเท่านั้น
5. **Zero-Mock / Zero-Fallback**: ข้อมูลขาด = raise · ห้ามค่าประมาณ ค่าเก่า หรือโมเดลแทน
6. **Env-only secrets**: ห้าม commit ค่า secret ลงไฟล์ใด ๆ
7. **Background Process Rule**: เทสต์ผ่าน `runner.py` แบบ foreground ใน terminal ที่มองเห็น และ kill ทันทีเมื่อจบ

---

## 📈 Trading Strategy — Believe (NEMESIS)

**Believe** คือกลยุทธ์หลักของ `strategies_mode` ออกแบบโดย NEMESIS TRADER
(อ้างอิง E-BOOK V1/V2 ใน `docs/strategies nemesis/`)

| รายการ | ค่าจริงในโค้ด |
|:---|:---|
| Candle TF | **S30** = Entry · **M1** = Trigger · **M5** = Context |
| Expiry / ถือครอง | **3 นาที** (strategies) · gate บังคับค่านี้ · ai/ml = 5 นาที |
| รอบวิเคราะห์ | ทุก S30 boundary (30 วินาที) |

### Indicators (core 3 ตัว — ต้องผ่านครบ)

| # | Indicator | Settings จริง | เงื่อนไข CALL | เงื่อนไข PUT |
|---|-----------|----------|----------------|----------------|
| 1 | **Bollinger Band %B** | 20, 2σ | `%B ≤ 0.45` หรือ touch LOWER/NONE | `%B ≥ 0.55` หรือ touch UPPER/NONE |
| 2 | **Stochastic** | 13-10-3 · เส้น 10/90 | extreme (zone OVERSOLD/10 หรือ `min(k,d) ≤ 35`) **OR** reversal (hook/cross50) | extreme (OVERBOUGHT/90 หรือ `max(k,d) ≥ 65`) **OR** reversal · และต้องไม่ tangled |
| 3 | **MA Crossover** | EMA 3 (แดง) vs **SMA 6** (เขียว) | ตัดขึ้น + confirmed | ตัดลง + confirmed |

> 📚 **ต่างจาก E-BOOK อย่างไร:** เล่ม V2 น.38 แสดง BB period **41** และบังคับ "BB/STO ต้องแตะเส้น 0/1 · 90/10"
> — โค้ดปัจจุบันใช้ BB 20 และผ่อนปรนเป็น 0.45/0.55 · ≤35/≥65 (ประเด็นเปิด F-4)
> · ส่วน MA ช้าถูกแก้เป็น **SMA 6** ตรงตามเล่มแล้ว (commit `a179f32`)

### Risk filters (บังคับทุกข้อ)
1. ห้ามมีเส้นกริด (S/R) ขวางข้างหน้า (`believe_risk_grid_block`)
2. ห้ามมีแท่งเทียนสีเทา/โดจิ (`believe_risk_gray_candle`)
3. STO ห้ามพันกัน (`believe_risk_sto_tangled`)
4. (เพิ่มในโค้ด) ไม่มี trap alert · room-to-run ผ่าน

### Multi-TF alignment
`S30 == M1 == M5 == candidate` มิฉะนั้น `WAIT` · secondary conditions
(price action, divergence, MACD, RSI, AP, NS) เป็น confirmation/วินิจฉัย ไม่บังคับเข้า

### 🔀 EXTREME level
ผสม Divergence (AP/NS: STO/RSI) + MACD เทียบเส้น 0 ก่อน แล้วหาจุดเข้าด้วย Believe
(ในโค้ด: `extreme_believe_active` = diagnostic)

---

## 📚 Documentation

- [ส่วนที่ 1 INPUT — `data_feed/`](docs/กระบวนการทำงานของบอท%20Part1%20data_feed/กระบวนการทำงานของบอท%20Part1%20data_feed.md)
- [ส่วนที่ 2 PROCESS — `data_evaluate/`](docs/กระบวนการทำงานของบอท%20Part2%20data_evaluate/กระบวนการทำงานของบอท%20Part2%20data_evaluate.md)
- [ส่วนที่ 3 DECISION — `data_decision/`](docs/กระบวนการทำงานของบอท%20Part3%20data_decision/กระบวนการทำงานของบอท%20ส่วนที่%203%20OUTPUT.md)
- [ส่วนที่ 4 EXECUTION — `data_trade/`](docs/กระบวนการทำงานของบอท%20Part4%20data_trade/กระบวนการทำงานของบอท%20Part4%20data_trade.md)
- [E-BOOK NEMESIS V1/V2 + indicator scripts](docs/strategies%20nemesis/)

> 🔧 ลิงก์ชุดเดิมชี้ไปยังโฟลเดอร์ที่ไม่มีอยู่จริง (`…ส่วนที่ 1 INPUT/` ฯลฯ) และ `docs/MODEL_CRITIQUE_AND_ROADMAP.md`
> ไม่เคยมีใน repo — แก้ไขแล้วในการตรวจทาน 2026-09-26

---
> **⚠️ Disclaimer**: This system is for educational and quantitative research purposes. Trading binary options carries a high level of risk and may not be suitable for all investors. Always test thoroughly in a DEMO environment before deploying real capital.
