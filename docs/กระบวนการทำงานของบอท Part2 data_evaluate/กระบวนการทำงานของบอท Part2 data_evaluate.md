# 📊 FINALBOT — กระบวนการทำงานของบอท ส่วนที่ 2: PROCESS (Data Evaluate System)

> 📅 **เอกสารฉบับนี้เขียนใหม่ทั้งหมด โดยตรวจเทียบบรรทัดต่อบรรทัดกับ source code จริง ณ commit `0990519` (22 ก.ย. 2026)**
> เอกสารชุดเดิม (ซึ่งมีเนื้อหาซ้ำกันทั้ง Part 2/3/4) ถูกลบและแทนที่ด้วยฉบับนี้
> ทุกตัวเลข ทุก path ทุกชื่อฟังก์ชัน มี `ไฟล์:บรรทัด` กำกับไว้ให้ตรวจย้อนกลับได้เสมอ
> หากโค้ดกับเอกสารขัดกัน ให้ยึด **โค้ด** เป็นหลัก แล้วกลับมาแก้เอกสารนี้

---

## 🎯 ทำความเข้าใจได้ทันที (Executive Summary)

ส่วนงานที่ 2 (**PROCESS / Data Evaluate**) คือ **"โรงงานเปลี่ยนแท่งเทียนดิบให้เป็นข้อสรุปตลาด"**
อ่านไฟล์ CSV ที่ Part 1 เขียนไว้ **จากดิสก์เท่านั้น** (ไม่รับ DataFrame ผ่าน RAM) แล้วคำนวณผ่าน 8 ชั้น
จนได้ไฟล์ **Prompt Payload** `.txt` ให้ Part 3 อ่าน

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                          ขอบเขตและสัญญาของส่วนงานที่ 2 (Contract)                                     │
├────────────────────────────────┬──────────────────────────────────┬──────────────────────────────────┤
│           จุดเริ่มต้น          │        แกนกลางการประมวลผล        │       จุดสิ้นสุดการส่งมอบ        │
├────────────────────────────────┼──────────────────────────────────┼──────────────────────────────────┤
│ data_base/output_feed/<SYM>/   │ L1 IndicatorStore  (SSOT)        │ data_base/output_evaluate/       │
│   <SYM>_S30.csv                │ L2 5 Tier-1 Engines  (parallel)  │   <mode>/<SYM>/<ID>.txt          │
│   <SYM>_M1.csv                 │ L3 10 Advanced Tools             │                                  │
│   <SYM>_M5.csv                 │ L4 MarketStateClassifier         │ • 99 บรรทัด  (ai_mode/ml_mode)   │
│   [<SYM>_M15.csv]              │ L5 9 Supplementary Modules       │ • 114 บรรทัด (strategies_mode)   │
│                                │ L6 Believe (strategies เท่านั้น)  │ • retention 30 ไฟล์/คู่เงิน      │
│ ปฏิทินข่าว (Part 2 เป็นเจ้าของ) │ L7 Deduplicate + Format          │                                  │
│                                │ L8 Serialize → .txt              │ + RAM: store.clear_symbol()      │
└────────────────────────────────┴──────────────────────────────────┴──────────────────────────────────┘
```

**หลักการ 3 ข้อที่ยึดตลอดทั้ง Part 2**

| หลักการ | ความหมายในโค้ด |
|:---|:---|
| **Single Source of Truth (SSOT)** | Indicator ทุกตัวคำนวณครั้งเดียวที่ `IndicatorStore` (Layer 1) — Engine/Classifier/Tools **ห้ามคำนวณซ้ำ** ต้องอ่านจาก `store.get_payload(symbol)` |
| **Disk-Only Boundary** | `process_cycle()` อ่าน CSV จากดิสก์เองเมื่อไม่ได้ส่ง `candles_dict` มา (`orchestrator.py:185-200`) — RAM ใช้ได้เฉพาะภายใน Part 2 |
| **Fail-Fast / No Fallback** | ทุก step ครอบด้วย `try/except` ที่ `raise` ต่อ หรือ `logger.exception` + `raise` — ไม่มีทางออกเงียบ ๆ (ดู [บัญชี Fail-Fast](#-บัญชี-fail-fast-ทั้งหมดใน-part-2)) |

---

## 🧬 3 โหมด — ความต่างจริงมีแค่ 2 ไฟล์

`data_evaluate/` มีโค้ด **3 ชุด** (`ml_mode/`, `ai_mode/`, `strategies_mode/`) ชุดละ 32 ไฟล์
แต่ผลการ `diff -rq` ทั้งโฟลเดอร์พบว่า:

| การเปรียบเทียบ | ผล |
|:---|:---|
| `ml_mode/orchestration/` vs `ai_mode/orchestration/` | **เหมือนกัน 100%** (29 ไฟล์) |
| `ml_mode/orchestrator.py` vs `ai_mode/orchestrator.py` | **เหมือนกัน 100%** (1,319 บรรทัด) |
| `exceptions.py` / `news_calendar.py` | **เหมือนกันทั้ง 3 โหมด** |
| `ml_mode/orchestration/` vs `strategies_mode/orchestration/` | ต่างกัน **1 ไฟล์** = `indicator_store/indicator_store.py` |
| `ai_mode/orchestrator.py` vs `strategies_mode/orchestrator.py` | ต่างกัน **79 บรรทัด** (ไม่มี def/class เพิ่มหรือหาย) |

> 📌 **สรุป:** `ml_mode` กับ `ai_mode` คือโค้ดชุดเดียวกันเป๊ะ — ต่างกันแค่ **ตอนรัน** ว่า `mode_loader.py`
> จะโหลด orchestrator ของโฟลเดอร์ไหน และ Part 3 จะใช้ `MLDispatcher` หรือ `SystemPrompt`
> ส่วน `strategies_mode` = โค้ดชุดนั้น **+ S30 + Believe บน M1**

### ความต่างที่ 1 — `orchestration/indicator_store/indicator_store.py` (4 จุด)

| บรรทัด | `ml_mode` / `ai_mode` | `strategies_mode` | เหตุผล |
|:--:|:---|:---|:---|
| 66 | `if df_m15 is None or df_m15.empty or len(df_m15) < 250:` → **raise** | `if df_m15 is not None and (df_m15.empty or len(df_m15) < 250):` | strategies ไม่ดึง M15 → ต้องยอมให้ `None` ผ่าน |
| 164-165 | `calculate_ema(close_m1, [5, 20, 50], …)` | `calculate_ema(close_m1, [5, **10**, 20, 50], …)` | Believe ต้องใช้ **EMA10** เป็นเส้น slow |
| 170-172 | *(ไม่มี)* | เพิ่ม `m1.update(CoreIndicators.calculate_bb(close_m1, 20, …, require_100=True))` | Believe ต้องใช้ **BB บน M1** เพื่อคำนวณ %B |
| 368 | `df_m15 = candles_dict['M15']` | `df_m15 = candles_dict.get('M15')` | กัน `KeyError` เมื่อไม่มี M15 |

### ความต่างที่ 2 — `orchestrator.py` (79 บรรทัด)

| กลุ่ม | `ml_mode` / `ai_mode` | `strategies_mode` |
|:---|:---|:---|
| TF ที่อ่านจากดิสก์ (`:189, 210, 250, 283`) | `["M1","M5","M15"]` | `["S30","M1","M5"]` |
| `min_required_candles` (`:216-218`) | `M1:250, M5:250, M15:250` | `S30:250, M1:250, M5:250` |
| บล็อก S30 (`:229-236`) | *(ไม่มี)* | เพิ่ม `final_payload['s30'] = {open, high, low, close, volume}` จากแท่ง S30 ล่าสุด |
| M15 alias (`:237-239`) | *(ไม่มี)* | `candles_dict.setdefault('M15', candles_dict['M5'])` |
| `_format_payload` (`:491, 529, 613`) | — | เพิ่ม `s30 = _req(p,'s30')`, `'m1_bias'`, และ `ohlcv.s30` |
| `_enrich_believe_analysis` (`:855-989`) | อ่าน indicator จาก **M5** | อ่าน indicator จาก **M1** ทั้งหมด (bb, stoch, rsi, macd, ema5/10/20) |
| `believe_payload` (`:981-985`) | `"timeframe": payload.get("timeframe","M5")` | `"timeframe":"M1"`, `entry_timeframe:"S30"`, `context_timeframe:"M5"`, `holding_period_minutes:5`, `analysis_window:"5 x M1 candles"` |
| payload `.txt` (`:1168, 1218-1225, 1234, 1314-1322`) | 100 `app()` = **99 บรรทัด** | 115 `app()` = **114 บรรทัด** (เพิ่มบล็อก `s30:` 7 บรรทัด, `m1_bias` 1 บรรทัด, `believe_strategy:` 7 บรรทัด) |

> ⚠️ **M15 ปลอมใน strategies_mode** — `orchestrator.py:237-239` ทำ `candles_dict.setdefault('M15', candles_dict['M5'])`
> ทำให้ `m15_bias` ใน payload **คือค่าที่คำนวณจากแท่ง M5** ไม่ใช่ M15 จริง
> comment เหนือบรรทัดนั้นเขียนว่า *"without presenting M5 as an independent M15 feed"* และ comment ถัดไประบุว่า
> *"Timeframe sync is strictly prohibited in Part 2 … Data from M1, M5, M15 must remain independent"* — **ขัดกับการกระทำของตัวเอง**
> ผลกระทบต่อเนื่องไปถึง Part 4: เกตข้อ "M15/M5 direction conflict" จะไม่มีวันเป็นจริง (ดู [`readme.md` หมวด P2](../../readme.md))

---

## 🔄 การโหลดโหมด: `mode_loader.py` (80 บรรทัด)

Part 2 ไม่ได้ `import` orchestrator ตรง ๆ — `runner.py` เรียกผ่าน `mode_loader` เสมอ

| ฟังก์ชัน | หน้าที่ |
|:---|:---|
| `normalize_evaluate_mode(value)` `:12-26` | แปลง alias → โหมดจริง: `ml`→`ml_mode`, `ai`→`ai_mode`, `strategies`/`strategy`→`strategies_mode` • ค่าว่าง default = **`ml_mode`** • ค่านอก `VALID_MODES` → `ValueError("FAIL-FAST: Unsupported evaluation mode …")` |
| `load_orchestrator_class(mode)` `:29-46` | `_install_mode_namespace()` → โหลด `data_evaluate/<mode>/orchestrator.py` เป็น module ชื่อ `finalbot_evaluate_<mode>` → คืนคลาส `Orchestrator` (ไม่มีคลาส → `ImportError`) |
| `_install_mode_namespace(mode)` `:49-72` | **Trampoline:** ลบ `sys.modules["data_evaluate.orchestration*"]` ทิ้ง แล้วสร้าง module เปล่าที่ `__path__` ชี้ไป `data_evaluate/<mode>/orchestration/` • โหลด `exceptions.py` กับ `news_calendar.py` ของโหมดนั้นเข้า `sys.modules` |
| `mode_output_dir(settings, mode)` `:75-84` | คืน `data_evaluate.mode_output_dirs[mode]` จาก settings.json (default `data_base/output_evaluate/<mode>`) |

> ⚠️ เพราะ trampoline นี้ **`data_evaluate/orchestration/` ไม่มีอยู่จริงบนดิสก์** และ `data_evaluate/` ไม่มี `__init__.py`
> โค้ดทั้งหมดเขียน `from data_evaluate.orchestration.…` ซึ่งจะใช้ได้ก็ต่อเมื่อ `load_orchestrator_class()` รันไปแล้วเท่านั้น
> → ถ้า import โมดูลใน `orchestration/` ตรง ๆ ก่อน จะได้ `ModuleNotFoundError`

---

## 📂 โครงสร้างไฟล์จริง (32 ไฟล์ต่อโหมด)

```
data_evaluate/
├── mode_loader.py                       # 80 บรรทัด — ตัวสลับโหมด (ใช้ร่วมกันทั้ง 3 โหมด)
│
├── ml_mode/            ┐
├── ai_mode/            ├─ โครงสร้างเหมือนกันทั้ง 3 โหมด (ml ≡ ai ทุกไฟล์)
└── strategies_mode/    ┘
    ├── orchestrator.py                  # ★ 1,358 บรรทัด (ml/ai = 1,319) — ผู้บัญชาการ Part 2
    ├── exceptions.py                    # 15 บรรทัด — DataEvaluateError / InvalidInputError / ComputationError
    ├── news_calendar.py                 # 606 บรรทัด — ปฏิทินข่าวเศรษฐกิจ (Part 2 เป็นเจ้าของ)
    ├── orchestration/                   # ⚠️ โฟลเดอร์นี้ "ไม่มีอยู่จริง" — ถูก trampoline ชี้มา (ดูด้านบน)
    │   ├── base_engine.py               # 105 — BaseEngine(ABC): analyze() wrapper + timing + to_engine_output()
    │   │
    │   ├── indicator_store/             # ── LAYER 1: SSOT ──
    │   │   ├── core_indicators.py       #  79 — EMA / BB / RSI / MACD / Stochastic
    │   │   ├── structural_metrics.py    # 134 — ATR / ADX / Volume / Slope / Box
    │   │   └── indicator_store.py       # 425 — IndicatorStore + Config + `store` (global singleton)
    │   │
    │   ├── market_classifier/           # ── LAYER 2 (Tier 1) + LAYER 4 ──
    │   │   ├── trend_engine.py          # 221  TIER 1  MIN_CANDLES 200
    │   │   ├── strength_engine.py       # 119  TIER 1  MIN_CANDLES 200
    │   │   ├── volatility_engine.py     # 147  TIER 1  MIN_CANDLES 200
    │   │   ├── structure_engine.py      # 134  TIER 1  MIN_CANDLES 100
    │   │   ├── mtf_engine.py            # 123  TIER 1  MIN_CANDLES  50
    │   │   ├── market_state_classifier.py # 700 ★ LAYER 4 — 10 market states
    │   │   ├── market_structure_engine.py #  78  TIER 3  MIN_CANDLES  15
    │   │   └── market_pressure_analyzer.py # 127 TIER 5  MIN_CANDLES  40
    │   │
    │   ├── advanced_tools/              # ── LAYER 3: 10 tools ──
    │   │   ├── advanced_tools_manager.py # 184 — ผู้ประสาน + ประกอบ price_action / advanced_signals
    │   │   ├── behavior_analyzer.py     # 108
    │   │   ├── candle_pattern_analyzer.py # 141
    │   │   ├── conflict_analyzer.py     # 138
    │   │   ├── continuation_analyzer.py # 206
    │   │   ├── divergence_analyzer.py   # 108
    │   │   ├── efficiency_analyzer.py   # 118
    │   │   ├── persistence_analyzer.py  # 194
    │   │   ├── price_action_handler.py  # 186
    │   │   └── transition_analyzer.py   # 135
    │   │
    │   └── (ราก orchestration/)         # ── LAYER 5: supplementary ──
    │       ├── context_synthesizer.py   # 195  TIER 6
    │       ├── probability_estimator.py # 171  TIER 6
    │       ├── explainability_engine.py # 155  TIER 8
    │       ├── liquidity_engine.py      # 132  TIER 4  MIN_CANDLES 50
    │       ├── noise_detector.py        # 146  TIER 4  MIN_CANDLES 50
    │       ├── trap_detector.py         # 136  TIER 4  MIN_CANDLES 50
    │       ├── signal_throttle.py       # 120  (ไม่มี ENGINE_NAME/TIER)
    │       └── calendar_YYYY-MM-DD.txt  # ปฏิทินข่าวของวัน (1 ไฟล์/วัน/โหมด)
    │
    └── (ผลลัพธ์ไม่ได้เขียนที่นี่)  →  data_base/output_evaluate/<mode>/<SYM>/<ID>.txt
```

**นับ "6 Tier Engines" ที่เอกสารเดิมอ้าง:** มาจากเลข `TIER` ที่มีจริง 6 ค่า คือ **1, 3, 4, 5, 6, 8** (ไม่ใช่จำนวน engine)
**นับ "10 Advanced Tools":** ตรง — `AdvancedToolsManager.__init__` (`:20-31`) ลงทะเบียน 10 ตัวพอดี

---

## 🔁 วงจรการทำงาน: `evaluate_cycle()` → `process_cycle()`

### `evaluate_cycle(symbols)` — `orchestrator.py:133-175`

```
1. validate: symbols ต้องเป็น list และทุกตัวเป็น str มิฉะนั้น TypeError (FAIL-FAST)
2. ThreadPoolExecutor(max_workers = min(len(symbols), 20)), prefix "Part2EvalWorker"
3. submit process_cycle(symbol=sym) ทุกคู่เงิน → as_completed
4. ต่อคู่: ถ้าได้ dict/str/ไม่ใช่ None → ready_symbols
          ถ้า None → failed_symbols + logger.warning
          ถ้า exception → logger.exception → failed_symbols      ← ไม่ raise ขึ้นไป
5. ConsoleUI.show_payload_export(ready_symbols, failed_symbols)
```

> ⚠️ **Part 2 ไม่ fail ทั้งรอบเมื่อคู่เงินใดคู่หนึ่งพัง** — exception ถูกเก็บเป็น log แล้ววนต่อ
> และบรรทัด console ที่พิมพ์คือ `[Bot Evaluate Market Complete {len(ready)} asset]`
> ซึ่งถ้า `ready = 0` ก็ยังพิมพ์ `Complete 0 asset` โดยไม่มีข้อความเตือนบนจอ
> ต้องเปิด `logs/logs_data_evaluate/errors/error.log` ดูเองจึงจะรู้

### `process_cycle(symbol, …)` — `orchestrator.py:177-450` : 11 ขั้นตอน

| ขั้น | ชื่อในโค้ด |ทำอะไร | บรรทัด |
|:--:|:---|:---|:---|
| **0.0** | Load from disk | อ่าน `data_base/output_feed/<SYM>/<SYM>_{S30,M1,M5}.csv` → parse timestamp เป็น UTC → set index → sort • ไฟล์หาย = `FileNotFoundError` • ว่าง = `ValueError` | `186-201` |
| **0.0b** | Warm-up check | ทุก TF ต้องมี ≥ **250 แท่ง** มิฉะนั้น `ValueError("FAIL-FAST: Insufficient … warm-up candles on disk")` | `211-224` |
| **0.0c** | S30 snapshot | `final_payload['s30']` = OHLCV ของแท่ง S30 ล่าสุด *(strategies_mode เท่านั้น)* | `230-237` |
| **0.0d** | M15 alias | `candles_dict.setdefault('M15', candles_dict['M5'])` *(strategies_mode เท่านั้น)* | `238-240` |
| **0** | Handle OTC Volume | ถ้า symbol มี "OTC" → **copy DataFrame** แล้วตั้ง `volume = 1.0` ทุกแท่งของ S30/M1/M5 (กัน engine หาร 0) | `247-254` |
| **2** | **L1 Basic Indicators** | `store.calculate_all(symbol, candles_dict)` → `store.get_payload(symbol)` → `final_payload.update(...)` ได้ `m1`, `m5`, `m15`, `ohlcv`, `meta` | `259-265` |
| **3** | **L3 Advanced Tools** | `advanced_tools.analyze_all(symbol, basic_payload, df_m5)` → เขียนทับ `final_payload['m5']`, `['price_action']`, `['advanced_signals']` | `267-277` |
| **4** | **L2 5 Engines (parallel)** | validate `candles_dict` (ทุก TF ≥ 50 แท่ง) + `required_payload_fields = ['m5','m1','ohlcv','price_action']` → `_run_engines_parallel()` → `final_payload['analysis']` + `['engines']` | `279-313` |
| **5** | **L4 MarketStateClassifier** | `classifier.analyze(payload, symbol, trend_data, …, candles_dict)` → `final_payload['market_state']` + `['market_state_full']` | `315-349` |
| **5.05** | **L5 Supplementary Engines** | `_run_supplementary_engines(...)` → `final_payload['supplementary_engines']` (9 กุญแจ) | `351-368` |
| **5.1** | Group B fields | `expected_volatility_% = atr/close × 100` • `news_impact` (OTC = `NONE_OTC`) • OTC → set volume 1.0 / `NO_VOLUME_DATA` • `final_payload['market_context']` • `['decision_layer']` (3 ฟิลด์ท้าย = `"รอการวิเคราะห์จาก AI"`) • **`_enrich_believe_analysis()`** | `370-426` |
| **5.5** | Deduplicate | `_deduplicate_payload()` — ตัดฟิลด์ดิบที่ซ้ำออก | `428-432` |
| **6** | Format + Save | `_format_payload()` → `core_analysis` + `supplementary_data` → ถ้า `enable_txt_export` → `_save_txt_payload()` → `store.clear_symbol(symbol)` (กัน memory leak) → คืน `formatted_payload` | `434-451` |

> 📌 **หมายเหตุการนับเลขขั้น:** โค้ดข้ามเลข **1** (comment `# ── 1. Save OHLCV CSV ──` ระบุว่า "ย้ายไปเซฟตอนจบ process_cycle" แต่จริง ๆ การเซฟเกิดใน `_save_txt_payload` ของขั้น 6) และ `0.1 Timeframe Synchronization` ถูกระบุว่า **(REMOVED)**

---

## 🧮 LAYER 1 — `IndicatorStore` (Single Source of Truth)

`orchestration/indicator_store/indicator_store.py` • global singleton `store = IndicatorStore()` (`:392`)

### Config (`:29-33`)

```python
class Config:
    ROUND_DECIMALS   = 6
    ADX_PERIOD       = 14
    VOLUME_MA_PERIOD = 20
    SLOPE_PERIOD     = 10     # ระบุไว้แต่ไม่ได้ถูกใช้ในโค้ดปัจจุบัน
```

### Warm-up guard (`:62-67`) — Fail-Fast ก่อนคำนวณ

| TF | เงื่อนไข | ข้อความ |
|:--:|:---|:---|
| M1 | `None` / empty / `len < 250` | `FAIL-FAST: Insufficient M1 warm-up candles (minimum 250 required)` |
| M5 |เหมือน M1 | `FAIL-FAST: Insufficient M5 warm-up candles (minimum 250 required)` |
| M15 | **strategies:** ตรวจเฉพาะเมื่อ `is not None` • **ml/ai:** `None` ก็ raise | `FAIL-FAST: Insufficient M15 warm-up candles (minimum 250 required)` |

### Indicator ที่คำนวณจริงต่อ timeframe

| Indicator | **M5** | **M1** | **M15** | หมายเหตุ |
|:---|:--:|:--:|:--:|:---|
| EMA | 5, 10, 20, 50, **100, 200** | 5, 20, 50 → **+10 ใน strategies** | 20, 50 | `ewm(span=p, adjust=False)` |
| `bias` | ✅ `close > ema20` | ✅ `close > ema20` | ✅ `close > ema20` | → `BULLISH` / `BEARISH` |
| Bollinger (20, 2σ) | ✅ + `bb_width` + `bbw_sma_100` | ❌ → **✅ เฉพาะ strategies** | ❌ (comment ออก) | `require_100=True` บังคับ ≥ 100 แท่ง มิฉะนั้น `ValueError` |
| RSI(14) | ✅ | ✅ | ✅ | Wilder-style `ewm(alpha=1/14)` • `loss.replace(0, 1e-9)` กันหาร 0 |
| MACD (12,26,9) | ✅ + `macd_hist` | ✅ + `macd_hist` | ❌ (comment ออก) | |
| Stochastic | ✅ | ✅ | ❌ (comment ออก) | ⚠️ comment ในโค้ดเขียนว่า "(14, 3, 3)" แต่จริงคือ **13-10-3** |
| ATR(14) | ✅ `atr14` (+extended) | ❌ (comment ออก) | ❌ | |
| ADX(14) | ✅ `adx`, `di_plus`, `di_minus` | ❌ (comment ออก) | ❌ | |
| Volume metrics | ✅ `volume_ratio`, `volume_trend` | ❌ (comment ออก) | ❌ | MA 20 |
| ROC(10) | ✅ | ❌ (comment ออก) | ❌ | `< 10` แท่ง → `ValueError` |
| Linear-regression slope | ✅ `slope_10` | ❌ (comment ออก) | ❌ | |
| Floor Pivot | ✅ `pivot`, `r1`, `s1`, `support`, `resistance` | — | ❌ (comment ออก) | `P=(H+L+C)/3`, `R1=2P−L`, `S1=2P−H` จากแท่ง M5 ล่าสุด |
| Box metrics | ✅ `box_duration`, `box_tightness` | — | — | `calculate_box_metrics(high, low, atr14)` |
| OHLCV snapshot | ✅ `open/high/low/close` | ✅ `open/high/low/close` | ❌ (comment ออก) | |

**`ohlcv` (meta)** (`:211-226`) — 14 ฟิลด์: `m5_open/high/low/close/volume`, `m1_open/high/low/close/volume`,
`m1_age`, `m1_quality`, `m5_age`, `m5_quality`
→ `age`/`quality` **อ่านตรงจากคอลัมน์ที่ Part 1 เขียนมาใน CSV** ถ้าไม่มีคอลัมน์จะ default เป็น `0` / `'STALE'`

**ผลลัพธ์ `calculate_raw_indicators()`** (`:299-313`) คืน 5 กุญแจ:
```python
{'m5': {...}, 'm1': {...}, 'm15': {...} or None, 'ohlcv': {...}, 'meta': {symbol, timestamp, m5_candles, m1_candles, m15_candles}}
```

### API ของ IndicatorStore

| เมธอด | หน้าที่ |
|:---|:---|
| `calculate_raw_indicators()` `:50` | static — คำนวณ Layer 1 |
| `process_pair(symbol, df_m1, df_m5, df_m15, forming)` `:350` | คำนวณ + `set_raw()` |
| `calculate_all(symbol, candles_dict, session, forming)` `:364` | wrapper ที่ orchestrator เรียกจริง — ดึง `M1`/`M5` แบบ hard key และ `M15` แบบ `.get()` • ถ้า M1/M5 หาย → `raise Exception` |
| `set_raw` / `get_raw` `:317, 325` | เก็บ/คืน (คืนแบบ `deepcopy`) ใต้ `threading.Lock` |
| `get_full_snapshot` / `get_payload` / `get_all_symbols` `:332, 342, 337` | สำหรับ engine อื่นอ่าน |
| `clear_symbol(symbol)` `:385` | orchestrator เรียกท้าย `process_cycle` เพื่อกัน memory leak |
| `clear_all()` `:379` | ล้างทั้ง store |

---

## ⚙️ LAYER 2 — 5 Tier-1 Engines (ขนาน 5 thread)

`_run_engines_parallel()` — `orchestrator.py:634-688`
เรียกผ่าน `BaseEngine.analyze(payload, candles_dict=…)` ซึ่งครอบ `_analyze()` ด้วย timing + error wrap
(`base_engine.py:47-83` → ถ้าพังจะได้ `ComputationError("[<engine>] Computation failed: …")`)

| Engine | TIER | MIN_CANDLES | ฟิลด์ที่ orchestrator **บังคับ** ว่าต้องมี | ฟิลด์อื่นที่คืนมา |
|:---|:--:|:--:|:---|:---|
| `trend_engine` | 1 | 200 | `direction`, `strength`, `slope`, `momentum`, `type`, `confidence` | `reversal_risk`, `sustain_probability` + ค่า threshold ภายใน (`slope_impulsive`, `momentum_impulsive`, `strength_100/80/60/40`, `conf_*`) |
| `strength_engine` | 1 | 200 | `adx`, `di_plus`, `di_minus`, `rsi`, `momentum_level`, `strength_score`, `exhaustion_risk` | `macd`, `roc`, `divergence`, `confidence` |
| `volatility_engine` | 1 | 200 | `regime`, `spike_detected`, `compression_quality`, `volatility_score` | `atr`, `atr_percentile`, `bbw`, `stddev`, `expansion_probability`, `contraction_probability`, `volatility_zscore`, `bbw_compression_ratio`, `confidence` |
| `structure_engine` | 1 | 100 | `structure_type`, `bos_detected`, `support_levels`, `resistance_levels` | `structure_score`, `bos_type`, `key_zones`, `zone_proximity`, `breakout_probability`, `reversal_probability`, `box_duration`, `box_tightness`, `confidence` |
| `mtf_engine` | 1 | 50 | `alignment_score`, `htf_direction` | `directions_by_tf`, `dominant_direction`, `ltf_direction`, `htf_ltf_conflict`, `timeframes_analyzed`, `confidence_from_mtf`, `confidence` |

**Zero Tolerance validation** (`:658-680`): ถ้าได้ผลไม่ครบ 5 → `ValueError("FAIL-FAST: N engines failed to produce results: {missing}")`
และทุก engine ต้องคืน `dict` ที่มีฟิลด์บังคับครบและไม่เป็น `None` มิฉะนั้น `ValueError("FAIL-FAST: <engine> missing required field: <f>")`

ผลลัพธ์ถูกสรุปเป็น 2 กุญแจ (`:298-312`):
```python
final_payload['analysis'] = {'trend_direction', 'trend_strength', 'trend_type', 'volatility_regime'}
final_payload['engines']  = {'trend', 'strength', 'volatility', 'structure', 'mtf'}
```

---

## 🔬 LAYER 3 — 10 Advanced Tools

`advanced_tools_manager.analyze_all(symbol, basic_payload, df_m5)` — `advanced_tools_manager.py:33-184`

### ขั้นตอน
```
1. validate df_m5 ต้องเป็น DataFrame ที่ไม่ว่าง → มิฉะนั้น
   ValueError("FAIL-FAST: Cannot compute support/resistance from M5 OHLCV")
2. รัน analyzer 10 ตัว (ตามลำดับ ไม่ใช่ parallel):
   candle_pattern → trap_detector → price_action → behavior → conflict
   → continuation → divergence → efficiency → persistence → transition
3. คำนวณ body_strength / wick_dominance จาก 20 แท่งล่าสุด
4. คำนวณ sr_interaction และ rejection_zone จาก close / support / resistance / pivot
   threshold = atr × 0.5
5. map trap_alert จาก trap_detector (BULL_TRAP / BEAR_TRAP / STOP_HUNT / REJECTION / NONE)
6. ประกอบ results['price_action'] (15 ฟิลด์) + results['advanced_signals'] (6 ฟิลด์)
7. แนบผลดิบของแต่ละ analyzer: behavior, candle_pattern, trap_detector, conflict,
   continuation, divergence, efficiency, persistence, transition
```

### `price_action` — 15 ฟิลด์ (`:145-161`)
`pattern`, `last_candle_bias`, `last_candle`, `body_strength` (`STRONG` เมื่อ body > 0.1),
`rejection_zone` (`AT_PIVOT`/`AT_SUPPORT`/`AT_RESISTANCE`/`NONE`),
`wick_dominance` (`HIGH_UPPER_WICK`/`HIGH_LOWER_WICK`/`LOW_WICK`),
`momentum_bias`, `move_quality`, `trap_alert`,
`sr_interaction` (`BREAKING_ABOVE_RESISTANCE`/`BREAKING_BELOW_SUPPORT`/`TESTING_PIVOT`/`TESTING_RESISTANCE`/`TESTING_SUPPORT`/`NONE`),
`volume_momentum`, `divergence_alert`, `divergence_strength`, `market_behavior`, `hesitation_score`, `path_efficiency`

### `advanced_signals` — 6 ฟิลด์ (`:163-170`)
`conflict_score`, `continuation_probability`, `transition_risk`, `persistence_score`, `is_persistent`, `efficiency_score`

> ⚠️ **ทุก tool สืบทอด `BaseEngine` แต่ไม่มีตัวไหน override `analyze()`**
> `_analyze()` ของแต่ละตัวประกาศพารามิเตอร์แรกเป็น `candles_df: pd.DataFrame`
> ขณะที่ `BaseEngine.analyze()` ประกาศเป็น `payload: Dict[str, Any]` (`base_engine.py:47`) — **type hint โกหก** (ขัด `agent.md` Rule 2)
> รันได้เพราะ `**kwargs` กลืน `basic_payload` ไปส่งต่อให้ `_analyze()` แต่ `validate_input(payload)` ใน base จะได้รับ DataFrame

---

## 🏷️ LAYER 4 — `MarketStateClassifier` (700 บรรทัด)

`market_classifier/market_state_classifier.py` • `ENGINE_NAME` = market_state_classifier • `_analyze()` ที่ `:60`

### 10 สถานะตลาด (`VALID_STATES`, `:46-50`)
```
TRENDING_STRONG   TRENDING_WEAK    SIDEWAY_RANGE     BREAKOUT_EMERGING  REVERSAL_FORMING
ACCUMULATION      DISTRIBUTION     CHOPPY_UNCERTAIN  LIQUIDITY_VOID     UNCLEAR
```

### ลำดับการคำนวณ (`:100-133`)
```
1. validate payload ต้องมี 'm5', 'price_action', 'ohlcv'          → InvalidInputError
2. validate kwargs ครบ 7 ตัว: trend_data, strength_data, volatility_data,
   structure_data, mtf_data, symbol, candles_dict (และห้ามเป็น None) → InvalidInputError
3. is_otc = symbol ลงท้าย '_OTC' หรือ '-OTC'
4. metrics = _compute_metrics(...)        → 35 ฟิลด์ (:210-244)
5. state, confidence = _classify_state(metrics, is_otc)
6. state = _smooth_state(state, confidence)
7. quality_score  = _calculate_quality_score(state, metrics)
8. tradeable      = _is_tradeable(state, quality_score, metrics)
9. stability      = _compute_stability(metrics)
10. description   = _describe_state(state, metrics)
11. risk_level    = HIGH ถ้า noise_level > 0.5 หรือ volatility_regime == 'EXTREME'
                    LOW  ถ้า noise_level < 0.25 และ volatility_regime == 'NORMAL'
                    นอกนั้น MEDIUM
12. suggested_action = 'รอการวิเคราะห์จาก AI'   ; suggested_expiry = 5
```

### `_classify_state()` — weighted scoring (`:247-291`)
```
raw_scores  = _compute_raw_scores(metrics)        # ให้คะแนนครบทั้ง 10 state (:293-489)
adjusted    = _apply_global_modifiers(raw, m, is_otc)   # boost/penalty (:493-549)
ถ้า is_otc → adjusted['LIQUIDITY_VOID'] = 0         # volume OTC เชื่อถือไม่ได้
best_state  = max(adjusted, key=adjusted.get)
margin      = อันดับ1 − อันดับ2
confidence  = min(100, int(50 + (margin / 100) × 50))     # ถ้าไม่มีคะแนน > 0 → 50
Hysteresis: ถ้า best = LIQUIDITY_VOID แต่รอบก่อนไม่ใช่ และ margin < 15
            → ถอยไปใช้ state อันดับ 2 (ถ้าอันดับ 2 ไม่ใช่ LIQUIDITY_VOID)
```

### `_smooth_state()` — กัน state กระพริบ (`:551-568`)
- `_state_history = deque(maxlen=5)`
- ถ้าประวัติยังไม่ครบ 5 → คืน state ปัจจุบันตามจริง
- ครบแล้ว → นับ `Counter` ถ้า state ใดปรากฏ **≥ 3 ใน 5 รอบ** → ใช้ state นั้นแทน

### `_calculate_quality_score()` (`:570-600`)
```
ฐานตาม state:  TRENDING_STRONG 90 | BREAKOUT_EMERGING 85 | ACCUMULATION 80 | SIDEWAY_RANGE 75
              TRENDING_WEAK 65 | REVERSAL_FORMING 60 | DISTRIBUTION 45 | CHOPPY_UNCERTAIN 20
              UNCLEAR 15 | LIQUIDITY_VOID 10
หัก noise:    quality −= int(noise_level × 30)
หัก volume:   ถ้า volume_ratio < 0.5 → quality −= 20
ผสม regime:   final = (quality + regime_quality_score) / 2     → clamp 0..100
```

### `_is_tradeable()` (`:602-615`)
> docstring ระบุชัด: **"การตัดสินใจว่าจะเทรดหรือไม่ ไม่ใช่หน้าที่ของ Part 2 — มอบให้ Part 3"**
> ฟังก์ชันนี้คืน `True` แค่เมื่อ metrics มี `trend_direction`, `adx`, `rsi`, `noise_level` ครบและไม่เป็น `None`

### `_compute_stability()` (`:617-624`)
```
stability = 100 × (1 − noise) × (1 − volatility_score/100 × 0.3) × (0.5 + 0.5 × min(1, adx/50))
```

### `metrics` 35 ฟิลด์ (`:210-244`)
`trend_direction`, `trend_strength`, `trend_slope`, `trend_type`, `adx`, `rsi`, `momentum_level`, `strength_score`,
`atr_percentile`, `bbw`, `volatility_regime`, `volatility_score`, `structure_type`, `bos_detected`,
`breakout_prob`, `reversal_prob`, `alignment_score`, `htf_direction`, `volume_ratio`, `noise_level`,
`rsi_extreme_bull`, `rsi_extreme_bear`, `wick_lower_ratio`, `wick_upper_ratio`, `compression_detected`,
`divergence_detected`, `volume_surge`, `adaptive_adx_threshold`, `consistency_score`, `cleanliness_score`,
`directionality_score`, `regime_quality_score`, `is_otc`

---

## 🧩 LAYER 5 — Supplementary Modules (9 กุญแจ)

`_run_supplementary_engines()` — `orchestrator.py:689-849`

### ขั้นที่ 1 — 4 โมดูลขนาน (`ThreadPoolExecutor`, `:712-740`)
validate ก่อน: `candles_dict` ต้องมี `M5` และเป็น DataFrame ไม่ว่าง → มิฉะนั้น `ValueError("[SupplementaryEngines] FAIL-FAST: …")`

| key | โมดูล | TIER | MIN_CANDLES | ฟิลด์ที่คืน |
|:--:|:---|:--:|:--:|:---|
| `ms` | `market_structure_engine` | 3 | 15 | `status`, `regime`, `structure`, `last_high`, `last_low`, `trend_strength` |
| `mp` | `market_pressure_analyzer` | 5 | 40 | `buy_pressure`, `sell_pressure`, `dominant_side`, `absorption_detected`, `effort_vs_result`, `pressure_imbalance`, `confidence` |
| `liq` | `liquidity_engine` | 4 | 50 | `equal_highs`, `equal_lows`, `liquidity_above`, `liquidity_below`, `liquidity_sweep_detected`, `sweep_type`, `liquidity_score`, `confidence` |
| `noise` | `noise_detector` | 4 | 50 | `noise_level`, `noise_category`, `choppiness_index`, `whipsaw_detected`, `wick_noise_ratio`, `direction_changes`, `is_clean`, `confidence` |

### ขั้นที่ 2 — `regime_quality_scorer` (`:743-759`)
**ไม่ใช่คลาส** — ประกอบขึ้นจาก `state_data['metrics']` ของ Layer 4:
```python
{'consistency_score', 'cleanliness_score', 'directionality_score',
 'overall_quality'  = metrics['regime_quality_score'],
 'is_tradeable_regime' = overall_quality >= 60,
 'confidence' = min(100, overall_quality + 10)}
```
ถ้า `state_data` ไม่มี `metrics` → `rq_res = {}` (dict ว่าง ไม่ raise)

### ขั้นที่ 3 — ประกอบ `MarketContext` (`:762-792`)
`SimpleNamespace` ที่รวมผลทุกชั้นไว้ด้วยกัน — **มีค่า default แบบ fallback** ทุกฟิลด์ เช่น
`continuation_probability: 50`, `divergence_detected: False`, `quality_score: 50`, `confidence_tier: 'MEDIUM'`
และ `ctx.timeframe = "M5"` (hardcode)

### ขั้นที่ 4 — 3 synthesis engines (`:795-824`)

| key | โมดูล | TIER | ฟิลด์ที่คืน |
|:--:|:---|:--:|:---|
| `context_synthesizer` | `context_synthesizer.py` | 6 | `directional_bias`, `bias_strength`, `market_clarity`, `risk_level`, `market_read`, `tradeable`, `synthesis_quality`, `confidence` |
| `probability_estimator` | `probability_estimator.py` | 6 | `up_probability`, `down_probability`, `direction`, `edge`, `estimate_confidence`, `expected_magnitude`, `has_edge`, `confidence` |
| `explainability_engine` | `explainability_engine.py` | 8 | `summary`, `supporting_factors`, `opposing_factors`, `key_drivers`, `factor_balance`, `explanation_available`, `confidence` |

ทั้งสามรับ `context=ctx` และแต่ละขั้นเขียนผลกลับเข้า `ctx` (`ctx.synthesized_context`, `ctx.probability`, `ctx.explanation`)

### ขั้นที่ 5 — `signal_throttle` (`:825-837`)
```python
action = payload['decision_layer']['suggested_action']    # = 'รอการวิเคราะห์จาก AI' เสมอในขั้นนี้
allowed, reason = signal_throttle.allow(symbol, action)
→ {'allowed', 'reason', 'status'}
```
`SignalThrottle` (`signal_throttle.py:22-33`) — `default_cooldown_seconds=300`, `global_cooldown_seconds=60`, `adaptive=True`
cooldown ปรับตามผลเทรดล่าสุด: แพ้ → `max(180, default−120)` (3–5 นาที) • ชนะ → `min(600, default+120)` (5–10 นาที)

> ⚠️ เพราะ `suggested_action` ยังเป็นข้อความไทย `"รอการวิเคราะห์จาก AI"` ณ ขั้นนี้ (Part 3 ยังไม่ได้วิเคราะห์)
> `signal_throttle.allow()` จึงถูกเรียกด้วย action ที่ไม่ใช่ `CALL`/`PUT`/`WAIT` เสมอ และ **ไม่มีโค้ดใดเรียก `record_signal()`**
> → cooldown แบบ adaptive ไม่เคยทำงานจริง

### ผลลัพธ์รวม (`:839-848`) — 9 กุญแจ
```python
final_payload['supplementary_engines'] = {
  'explainability_engine', 'liquidity_engine', 'noise_detector', 'probability_estimator',
  'signal_throttle', 'context_synthesizer', 'market_structure_engine',
  'market_pressure_analyzer', 'regime_quality_scorer'
}
```

---

## 🎯 LAYER 6 — Believe (`strategies_mode` เท่านั้น)

`_enrich_believe_analysis(payload)` — `orchestrator.py:854-1090`
ถูกเรียกในขั้น 5.1 (`:423`) และเขียน 6 กุญแจกลับเข้า payload

### แหล่งข้อมูล (ต่างจาก ml/ai mode)
| ตัวแปร | `ml_mode` / `ai_mode` | **`strategies_mode`** |
|:---|:---|:---|
| `close` | `ohlcv.m5_close` | **`ohlcv.m1_close`** |
| BB upper/lower | `m5.bb_upper/lower` | **`m1.bb_upper/lower`** |
| Stochastic | `m5.stoch_k/d` | **`m1.stoch_k/d`** |
| RSI | `m5.rsi14` | **`m1.rsi14`** |
| MACD | `m5.macd/signal` | **`m1.macd/signal`** |
| EMA fast/slow/20 | `m5.ema5/ema10/ema20` | **`m1.ema5/ema10/ema20`** |

> docstring: *"Believe's trigger is evaluated on M1 because five one-minute candles represent the five-minute holding horizon."*

### ตัวแปรสถานะที่คำนวณ (`:892-937`)
| ตัวแปร | สูตร |
|:---|:---|
| `bb_pct_b` | `(close − lower) / (upper − lower)` • ถ้า `upper == lower` → 0.5 • ถ้าออกนอก [0,1] → 0.5 |
| `stochastic_extreme` | `stoch_k ≤ 10` → `OVERSOLD_10` • `≥ 90` → `OVERBOUGHT_90` • นอกนั้น `MID` |
| `ma_cross_direction` | `ema5 ≥ ema10` → `GOLDEN_CROSS` • เท่ากันเป๊ะ → `FLAT` • นอกนั้น `DEATH_CROSS` |
| `hook_confirmed` | `k ≥ d` **และ** ((`k ≥ 50` และ bullish_structure) หรือ (`k ≤ 50` และ bearish_structure)) |
| `crossed_50` | `(k ≥ 50 และ d < 50)` หรือ `(k ≤ 50 และ d > 50)` |
| `is_surfing_extreme` | `(k ≤ 10 หรือ k ≥ 90)` และ `(d ≤ 20 หรือ d ≥ 80)` |
| `bullish_structure` | `market_state_full.structure_shift ∈ {BULLISH_SHIFT, BULLISH}` หรือ `market_state ∈ {UPTREND, BULLISH}` หรือ `trend_direction ∈ {UP, UPTREND, BULLISH}` หรือ `price_action.market_behavior ∈ {BULLISH, STRONG_BULLISH}` |
| `risk_filter_ok` | `trap_alert ∉ {TRAP, GRID_BLOCK}` และ `pattern ∉ {DOJI, GRAY_DOJI}` |

### ระบบให้คะแนนแบบถ่วงน้ำหนัก (`:939-968`)
| เงื่อนไข | น้ำหนัก (ฝั่งที่ตรงโครงสร้าง) |
|:---|:--:|
| `ema5 ≥ ema10` (bullish) / `<` (bearish) | **0.30** |
| `stochastic_extreme == OVERSOLD_10` / `OVERBOUGHT_90` | **0.25** |
| `bb_pct_b ≤ 0.20` / `≥ 0.80` | **0.15** |
| `rsi < 30` / `> 70` | **0.15** |
| Divergence ตรวจพบและทิศตรงกัน | **0.15** |
| `macd > macd_signal` / `<` | **0.10** |
| `risk_filter_ok` | **+0.05 ทั้งสองฝั่ง** |

```
bullish_signal = bullish_score ≥ 0.60  AND  bullish_structure
bearish_signal = bearish_score ≥ 0.60  AND  bearish_structure
ถ้าเป็นทั้งคู่ → เปรียบเทียบคะแนน ใครมากกว่าชนะ
signal_direction = 'BUY' | 'SELL' | 'WAIT'
extreme_confirmed = max(bull, bear) ≥ 0.75 AND (bullish_signal OR bearish_signal)
setup_type = 'EXTREME_BELIEVE' ถ้า extreme_confirmed ไม่งั้น 'BASE_BELIEVE'
```

### 6 กุญแจที่เขียนกลับเข้า payload (`:1078-1089`)
| กุญแจ | เนื้อหา |
|:---|:---|
| `believe` | `symbol`, `timeframe:"M1"`, `entry_timeframe:"S30"`, `context_timeframe:"M5"`, `holding_period_minutes:5`, `analysis_window:"5 x M1 candles"`, `close_price`, `indicators_raw` (9), `believe_trigger_states` (ma_crossover / bb_state / stochastic_state), `market_structure_fractals` (7), `extreme_combination_extras` (4), `risk_and_market_filters` (grid_filter 6 + candle_safety 3) |
| `ap_confirmation` | `ap_active`, `signal` (`AP_BULLISH`/`AP_BEARISH`/`AP_NEUTRAL`), `source: [BOLLINGER, STOCH, MACD, MOMENTUM]`, `confidence` |
| `ns_confirmation` | `ns_active` (เมื่อ `|rsi−50| < 20` และ `|stoch_k−50| < 20`), `signal`, `source: [RSI, STOCH, STRUCTURE]`, `confidence` |
| `extreme_believe` | `setup_type`, `is_active`, `score`, `reasons` (5 ข้อ) |
| `believe_signal_type` | `EXTREME_BELIEVE` / `BASE_BELIEVE` |
| `belief_summary` | `status` (`active`/`watch`), `direction` (**BUY/SELL/WAIT**), `confidence` (HIGH/MEDIUM/LOW), `score`, `signal` |

> 📌 **มีแค่ 6 ฟิลด์ของ `belief_summary` + `extreme_believe` ที่ถูกเขียนลงไฟล์ `.txt`** (บล็อก `believe_strategy:`)
> ส่วน `ap_confirmation` / `ns_confirmation` / `believe` (รายละเอียดเต็ม) **อยู่ใน RAM เท่านั้น** — Part 3 อ่านไม่ได้

> ⚠️ `signal_direction` ใช้คำว่า **BUY / SELL** — Part 3 (`believe_analyzer._direction()`) เป็นตัวแปลเป็น CALL / PUT

---

## 🧹 LAYER 7 — `_deduplicate_payload()` (`orchestrator.py:1092-1122`)

ตัดฟิลด์ดิบที่ Layer 1 คำนวณไว้แต่ซ้ำกับผลของ Engine เพื่อลดขนาด payload

| แหล่ง | ฟิลด์ที่ถูก `pop()` ทิ้ง |
|:---|:---|
| `engines.strength` | `adx`, `di_plus`, `di_minus`, `rsi`, `macd`, `roc` |
| `engines.volatility` | `atr`, `atr_percentile`, `bbw`, `stddev` |
| `engines.structure` | `support_levels`, `resistance_levels`, `box_duration`, `box_tightness` |
| `engines.trend` | `slope` |
| `market_state_full.metrics` | 18 ฟิลด์: `adx`, `rsi`, `atr_percentile`, `bbw`, `trend_direction`, `trend_strength`, `trend_slope`, `trend_type`, `momentum_level`, `strength_score`, `volatility_regime`, `volatility_score`, `structure_type`, `bos_detected`, `breakout_prob`, `reversal_prob`, `alignment_score`, `htf_direction` |

> ⚠️ `_deduplicate_payload()` แก้ dict ต้นฉบับแบบ in-place แล้ว `return p` — ขัด `agent.md` Rule 3 (Immutability of Payloads)

---

## 📐 LAYER 8 — `_format_payload()` (`orchestrator.py:464-632`)

เปลี่ยน payload ดิบ → โครงสร้าง 2 กุญแจ โดย **ห้ามมี fallback** — ใช้ `_req()` (`:474-488`) ที่ `raise` ทันทีถ้าฟิลด์หายหรือเป็น `None`:
```python
raise ValueError(f"Required field missing: {path}")
raise ValueError(f"Required field is None: {path}")
```

### `core_analysis` — **74 ฟิลด์** (ตรวจนับจริงจากโค้ด)

> ⚠️ comment ในโค้ดบรรทัด `:499` เขียนว่า `# ─── CORE ANALYSIS (83 Fields) ───` แต่**นับจริงได้ 74**
> ตัวเลข "74 ฟิลด์" ที่เอกสาร Part 1 รุ่นเก่าอ้าง **คือจำนวนนี้** — ไม่ได้ผิด
> สิ่งที่คลาดเคลื่อนคือเอกสารเก่าเอา "74 ฟิลด์" ไปเรียกเป็นจำนวนบรรทัดของไฟล์ `.txt` (จริงคือ 99/114 บรรทัด)

| กลุ่ม | จำนวน | ฟิลด์ |
|:---|:--:|:---|
| Market Context & State | 5 | `state`, `description`, `volatility_regime`, `news_impact`, `expected_volatility_%` |
| M5 Indicators | 18 | `m5_bias`, `m5_ema5/10/20/50`, `m5_bb_upper/lower/width`, `m5_rsi`, `m5_stoch_k/d`, `m5_macd`, `m5_macd_signal`, `m5_adx`, `m5_atr`, `m5_support`, `m5_resistance`, `m5_pivot` |
| M1 Indicators | 9 | `m1_bias` *(strategies เท่านั้น)*, `m1_last_candle`, `m1_ema5`, `m1_ema20`, `m1_rsi`, `m1_stoch_k/d`, `m1_macd`, `m1_macd_signal` |
| M15 Indicators | 1 | `m15_bias` |
| Price Action | 13 | `pa_pattern`, `pa_last_candle_bias`, `pa_body_strength`, `pa_wick_dominance`, `pa_momentum_bias`, `pa_move_quality`, `pa_trap_alert`, `pa_sr_interaction`, `pa_divergence_alert`, `pa_divergence_strength`, `pa_market_behavior`, `pa_hesitation_score`, `pa_path_efficiency` |
| Volume | 3 | `vol_tick_volume`, `vol_momentum`, `vol_vs_average` — OTC บังคับเป็น `1.0` / `NO_VOLUME_DATA` / `1.0` |
| Engines | 18 | `eng_trend_direction/strength/type`, `eng_strength_momentum_bias/momentum_strength/exhaustion_risk`, `eng_volatility_regime/compression_detected/compression_quality/score`, `eng_structure_type/bos_detected`, `eng_mtf_alignment_score/htf_direction`, `eng_indicator_conflict_score`, `eng_trend_continuation_%`, `eng_regime_transition_risk`, `eng_momentum_persistence_score` |
| Decision Layer | 7 | `dl_tradeable`, `dl_stability_score`, `dl_quality_score`, `dl_risk_level`, `dl_confidence_score`, `dl_suggested_expiry_minutes`, `dl_suggested_action` |

**3 ฟิลด์สุดท้ายของ `decision_layer`** ถูกเติมเป็นข้อความไทย `"รอการวิเคราะห์จาก AI"` (`:418-420`)
เพื่อให้ Part 3 เป็นผู้กรอก — ตรงตาม `agent.md` Rule 21

### `supplementary_data` — 11 กุญแจ (`:600-627`)
```
meta                  : timestamp, symbol, session, m1_open/age/quality, m5_open/age/quality  (10 ฟิลด์)
ohlcv                 : s30 {5}, m1 {5}, m5 {5}     ← volume ของ m1/m5 = 'NONE_OTC' ถ้าเป็นคู่ OTC
full_engine_output    : engines ทั้ง 5 (หลัง dedup)
full_market_state     : ผล MarketStateClassifier เต็ม
supplementary_engines : 9 กุญแจจาก Layer 5
recent_ai_memory      : list(self.ai_memory)   ← ⚠️ ว่างเสมอ (ดู หมวด dead code)
believe / ap_confirmation / ns_confirmation / extreme_believe / belief_summary
```

`_derive_session()` (`:591-598`) — แปลงชั่วโมง UTC เป็นชื่อเซสชัน:
`00-07 SYDNEY/TOKYO` • `07-12 LONDON_OPEN` • `12-16 NY/LONDON_OVERLAP` • `16-21 NY_AFTERNOON` • `21-24 SYDNEY_OPEN`

---

## 📄 LAYER 9 — ไฟล์ Prompt Payload `.txt`

### `_format_core_analysis_output()` (`:1161-1323`)

สร้างรายการบรรทัดด้วย `app = lines.append` แล้ว `"\n".join(lines)`

| โหมด | จำนวน `app()` | จำนวนบรรทัดในไฟล์ |
|:---|:--:|:--:|
| `ml_mode` | 100 | **99 บรรทัด** + trailing newline |
| `ai_mode` | 100 | **99 บรรทัด** + trailing newline |
| `strategies_mode` | 115 | **114 บรรทัด** + trailing newline |

> 📌 **ตัวเลข "99 บรรทัดพอดีเป๊ะ" ใน `agent.md` Rule 20 ใช้ได้แค่กับ `ml_mode` / `ai_mode`**
> `strategies_mode` (โหมดที่ active อยู่ปัจจุบัน) ให้ **114 บรรทัด**
> และ docstring ของ `evaluate_cycle()` (`:136`) เขียนว่า *"writes 100-line prompt payload"* ซึ่งไม่ตรงทั้งคู่

### โครงสร้างไฟล์ (strategies_mode — 114 บรรทัด)

```yaml
ID:EURGBPOTC0920015903          # ← บรรทัดเดียวที่ไม่มี space หลัง ':'
meta:                           #  11 บรรทัด: timestamp, symbol, ai_model, session,
                                #    m1_open/age/quality, m5_open/age/quality
s30:                            #   7 บรรทัด ★ เพิ่มเฉพาะ strategies_mode
                                #    s30_bias = BULLISH ถ้า close >= open (แค่สีแท่ง ไม่ใช่อินดิเคเตอร์)
                                #    s30_open/high/low/close/volume
market_context:                 #   6 บรรทัด: mtf_state, mtf_description, m5_volatility_regime,
                                #    m5_news_impact, m5_expected_volatility_%
timeframes:
  m1:                           #  10 บรรทัด: m1_bias ★, m1_last_candle, ema5, ema20, rsi,
                                #    stoch_k, stoch_d, macd, macd_signal
    ohlcv:                      #   6 บรรทัด: m1_open/high/low/close/volume
  m5:                           #  19 บรรทัด: m5_bias, ema5/10/20/50, bb_upper/lower/width, rsi,
                                #    stoch_k/d, macd/signal, adx, atr, support, resistance, pivot
    ohlcv:                      #   6 บรรทัด: m5_open/high/low/close/volume
  m15:                          #   2 บรรทัด: m15_bias  ← strategies_mode = ค่าจาก M5 (ดู M15 ปลอม)
price_action:                   #  14 บรรทัด: m5_pa_*
volume:                         #   4 บรรทัด: m5_tick_volume, m5_volume_momentum, m5_volume_vs_average
analysis:                       #  12 บรรทัด: m5_trend_direction/type/strength_score, mtf_alignment_%,
                                #    m5_compression_quality_%, m5_exhaustion_risk_%, m5_bos_detected,
                                #    mtf_conflict_score, m5_trend_continuation_%, m5_transition_risk,
                                #    m5_persistence_score
decision_layer:                 #   8 บรรทัด: dl_tradeable, dl_stability_score, dl_quality_score,
                                #    dl_risk_level, ai_confidence_score, ai_suggested_expiry_minutes,
                                #    ai_suggested_action   (= "รอการวิเคราะห์จาก AI")
believe_strategy:               #   7 บรรทัด ★ เพิ่มเฉพาะ strategies_mode
                                #    believe_status, believe_direction, believe_confidence,
                                #    believe_score, extreme_believe_active, extreme_believe_setup
                                # (บรรทัดว่างปิดท้าย 1 บรรทัด)
```

**การจัดรูปแบบ:** key ถูก pad เป็นกว้าง 25 ตัวอักษรใน `_generate_yaml_text()` — แต่ฟังก์ชันนั้น**ไม่ได้ถูกเรียก** (ดู dead code)
`_format_core_analysis_output()` ใช้ `app(f"  key: {value}")` ตรง ๆ กับ indent 2/4/6 space

**Helper ในการฟอร์แมต** (`:1170-1186`)
- `_fmt_bool(v)` → `true` / `false` ตัวพิมพ์เล็ก
- `_fmt_num(v)` → ว่างถ้า `None`/`''` • float ที่ `|v| < 1e-4` ใช้ `f"{v:.6f}"` • float อื่น `round(v, 6)` • **ถ้าเป็น string (เช่น `"รอการวิเคราะห์จาก AI"`) คืน string นั้นตามเดิม**

### `ai_model` ในบล็อก `meta` (`:1190-1201`)
```
ถ้า ml_mode.enabled  → settings.ml_mode.model            (ปัจจุบัน "CHRONOS_2_ONNX")
elif ai_mode.enabled → settings.ai_mode.provider          ("GEMINI")
else                 → "NONE"
```
> ⚠️ อ่านจาก `enabled` ไม่ใช่จาก `active_mode` — ใน `settings.json` ปัจจุบัน **ทั้ง `ml_mode.enabled` และ `ai_mode.enabled` เป็น `true` พร้อมกัน**
> แม้ `active_mode = "strategies_mode"` → payload จะเขียน `ai_model: CHRONOS_2_ONNX` ซึ่งไม่ใช่สมองที่ทำงานจริง

### `_save_txt_payload()` (`:1325-1356`)

```
prompt_id = symbol.replace('-','').replace('_','')  +  ts_clean[4:14]
            ts_clean = timestamp ลบ '-' ':' 'T' '.' แล้วตัด 14 ตัวแรก
            → ts_clean[4:14] = MMDDHHMMSS
ตัวอย่าง   EURGBP-OTC @ 2026-09-20T01:59:03  →  EURGBPOTC0920015903

filepath  = {orchestrator_log_dir}/{symbol}/{prompt_id}.txt
            orchestrator_log_dir = settings.data_evaluate.output_dir
            ซึ่ง runner.py override เป็น mode_output_dir() ก่อนสร้าง Orchestrator
            → data_base/output_evaluate/<mode>/<SYMBOL>/<ID>.txt

Retention = sorted(txt files, key=mtime); ถ้า > 30 → ลบ txt_files[:-30]
            การลบครอบด้วย try/except OSError: pass  (silent)
```

| โหมด | ปลายทางจริง |
|:---|:---|
| `strategies_mode` | `data_base/output_evaluate/strategies_mode/<SYM>/<ID>.txt` |
| `ai_mode` | `data_base/output_evaluate/ai_mode/<SYM>/<ID>.txt` |
| `ml_mode` | `data_base/output_evaluate/ml_mode/<SYM>/<ID>.txt` |

> 📌 **ใน repo ปัจจุบันยังไม่มีโฟลเดอร์ `data_base/output_evaluate/`** — payload ที่พบ 354 ไฟล์อยู่ใน
> `data_base/output_decision/ai_decision/` ซึ่งเป็นผลงานของ Part 3 ไม่ใช่ Part 2
> path เก่าที่ปรากฏใน log: `data_evaluate/payload_output/`, `data_base/orchestrator/`, `data_base/evaluate_output/`

---

## 📰 ปฏิทินข่าวเศรษฐกิจ — Part 2 เป็นเจ้าของ

`news_calendar.py` (606 บรรทัด) — **เหมือนกันทั้ง 3 โหมด** และถูกเรียกจาก `Orchestrator.__init__()` (`:111-117`) ไม่ใช่จาก Part 1

### `ensure_calendar_news(target_date=None, show_ui=True)` (`:417-454`)
```
1. target_date = date.today() ถ้าไม่ระบุ
2. OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
3. ลบไฟล์ calendar_*.txt ทุกไฟล์ที่ไม่ใช่ของวันนี้          ← Rule 22: 1 ไฟล์/วัน
4. ถ้าไฟล์วันนี้ยังไม่มี → fetch_calendar() → export_json() → print_header()
   ถ้ามีแล้ว → print_header() จาก cache (ไม่ต้องต่อเน็ต)
```
> ⚠️ `Orchestrator.__init__` ครอบด้วย `try/except` ที่ `logger.exception(...)` แล้ว **`raise` ต่อ** (`:115-117`)
> → ถ้าดึงข่าวไม่สำเร็จ **บอทสตาร์ทไม่ติด**

### `fetch_calendar()` — 3 แหล่งตามลำดับ (`:158-259`)
| ลำดับ | แหล่ง | timeout |
|:--:|:---|:--:|
| 1 | `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (Official JSON Feed) | 10 s |
| 2 | `https://nfs.faireconomy.media/ff_calendar_thisweek.csv` (Official CSV Feed) | 10 s |
| 3 | `https://www.forexfactory.com/calendar` (HTML scraping ด้วย BeautifulSoup) | — |

> ⚠️ นี่คือ **fallback chain 3 ชั้น** ซึ่งขัด `agent.md` Rule 7 ("ห้ามมีระบบสำรองใด ๆ โดยไม่มีข้อยกเว้น")
> แต่ละชั้นที่ล้มเหลวจะ `log("[WARN] … error: …")` แล้วลองชั้นถัดไป

### `IMPACT_MAP` / `IMPACT_ICON` (`:50-64`)
```
icon--ff-impact-red → High    (🔴)     icon--ff-impact-yel → Low     (⚪)
icon--ff-impact-ora → Medium  (🟡)     icon--ff-impact-gra → Holiday (🔵)
```

### `update_all_news_impact(symbols)` (`:456-561`)
- ประเมินกรอบเวลา: **ข่าวที่จะเกิดใน 30 นาทีข้างหน้า** (`0 ≤ time_diff ≤ 30`) และ **ข่าวที่เกิดแล้วใน 15 นาทีที่ผ่านมา** (`−15 ≤ time_diff < 0`)
- ผลลัพธ์ต่อ symbol เก็บใน `_PRECALCULATED_NEWS` (global dict, คุ้มครองด้วย `_NEWS_LOCK = threading.RLock()`)
- ค่าที่เป็นไปได้: `HIGH` → `MEDIUM` → `LOW` → **`NONE_OTC`** (คู่ OTC ข้ามทุกการคำนวณ)
- Day rollover: ถ้า `_LAST_CALENDAR_DATE != today` → ตรวจไฟล์วันนี้ ถ้าไม่มีจะ auto-fetch

### `check_news_impact(symbol)` (`:563-577`) — ตัวที่ orchestrator เรียกจริง
```python
if "OTC" in symbol.upper():  return 'NONE_OTC'
with _NEWS_LOCK:
    if symbol not in _PRECALCULATED_NEWS:
        update_all_news_impact([symbol])      # ← คำนวณเฉพาะ symbol ที่ขอ (O(1) lookup หลังจากนั้น)
    return _PRECALCULATED_NEWS.get(symbol, 'LOW')
```
ถูกเรียกที่ `orchestrator.py:387` เฉพาะคู่ที่ไม่ใช่ OTC

### ⚠️ Path ที่โค้ดคำนวณผิด
```python
# news_calendar.py:67-68
BASE_DIR   = Path(__file__).resolve().parent.parent        # = data_evaluate/<mode>/
OUTPUT_DIR = BASE_DIR / "data_evaluate" / "orchestration"  # = data_evaluate/<mode>/data_evaluate/orchestration/
```
→ path ที่ได้นี้**ซ้อน `data_evaluate` สองชั้น** ขณะที่ไฟล์ที่มีอยู่จริงใน repo อยู่ที่
`data_evaluate/<mode>/orchestration/calendar_2026-09-21.txt` (ผลงานของโค้ดเวอร์ชันก่อนจัดโฟลเดอร์)
เมื่อรันครั้งต่อไป ระบบจะสร้างโฟลเดอร์ซ้อนใหม่และเขียนที่นั่น ส่วนไฟล์เก่าจะกลายเป็นกำพร้า
และเพราะ `OUTPUT_DIR` อยู่ใต้โฟลเดอร์โหมด → **แต่ละโหมดมีปฏิทินข่าวของตัวเองคนละไฟล์** (ไม่แชร์กัน)

---

## 🚨 บัญชี Fail-Fast ทั้งหมดใน Part 2

| จุด | เงื่อนไข | Exception | อ้างอิง |
|:---|:---|:---|:---|
| `evaluate_cycle` | `symbols` ไม่ใช่ list / มีสมาชิกไม่ใช่ str | `TypeError` | `orchestrator.py:140, 143` |
| `process_cycle` | ไฟล์ CSV หาย | `FileNotFoundError("FAIL-FAST: CSV file not found for {sym} {tf} at {path}")` | `:192` |
| `process_cycle` | CSV ว่าง | `ValueError("FAIL-FAST: Empty CSV file …")` | `:196` |
| `process_cycle` | `candles_dict` ไม่ใช่ dict | `TypeError` | `:208` |
| `process_cycle` | TF หาย/ว่าง | `ValueError("FAIL-FAST: Missing or empty {tf} data …")` | `:212` |
| `process_cycle` | แท่ง < 250 | `ValueError("FAIL-FAST: Insufficient {tf} warm-up candles on disk …")` | `:223` |
| ขั้น 4 | `candles_dict` ว่าง / TF ว่าง / แท่ง < 50 | `ValueError("FAIL-FAST: …")` | `:282-287` |
| ขั้น 4 | payload ขาด `m5`/`m1`/`ohlcv`/`price_action` | `ValueError("FAIL-FAST: Missing required payload field: {f}")` | `:293` |
| `_run_engines_parallel` | engine คืนผลไม่ครบ 5 | `ValueError("FAIL-FAST: N engines failed …")` | `:659` |
| `_run_engines_parallel` | engine คืน `None` / non-dict / ขาดฟิลด์บังคับ | `ValueError("FAIL-FAST: …")` | `:672-679` |
| ขั้น 5 | classifier ไม่พร้อม / payload ไม่ใช่ dict / engine data หาย / candles_dict หาย | `ValueError("FAIL-FAST: …")` | `:318-326` |
| ขั้น 5 | ผล classifier ไม่ใช่ dict / ไม่มี `state` | `ValueError("FAIL-FAST: MarketStateClassifier …")` | `:341-343` |
| ขั้น 5.05 | `candles_dict` ไม่มี `M5` / `df_m5` ไม่ valid | `ValueError("[SupplementaryEngines] FAIL-FAST: …")` | `:706-710` |
| ขั้น 5.05 | โมดูลเสริมคืน non-dict | `ValueError("[<module>] returned non-dict result")` | `:730, 798, 808, 818` |
| ขั้น 5.1 | `close_price` ไม่ valid | `ValueError("Failed to calculate expected_vol …")` | `:379-381` |
| `_format_payload` | ฟิลด์หาย / เป็น `None` | `ValueError("Required field missing: {path}")` / `("Required field is None: {path}")` | `:483, 486` |
| `IndicatorStore` | M1/M5/M15 < 250 แท่ง | `ValueError("FAIL-FAST: Insufficient … warm-up candles")` | `indicator_store.py:62-67` |
| `IndicatorStore` | M5 < 10 แท่ง (ROC) / < 1 แท่ง (Pivot) | `ValueError` | `indicator_store.py:107-108, 121-122` |
| `CoreIndicators.calculate_bb` | `require_100=True` และข้อมูล < 100 แท่ง | `ValueError("Not enough data to calculate bbw_sma_100")` | `core_indicators.py:28-29` |
| `CoreIndicators.calc_rsi` | RSI เป็น NaN | `ValueError("RSI is NaN")` | `core_indicators.py:45-46` |
| `BaseEngine.analyze` | payload เป็น `None` / `validate_input` ไม่ผ่าน | `InvalidInputError` | `base_engine.py:55-58` |
| `BaseEngine.analyze` | `_analyze` พัง / คืน non-dict | `ComputationError` | `base_engine.py:63-68` |
| `MarketStateClassifier` | payload ขาด `m5`/`price_action`/`ohlcv` หรือ kwargs ไม่ครบ 7 | `InvalidInputError` | `market_state_classifier.py:74-88` |
| `AdvancedToolsManager` | `df_m5` ไม่ใช่ DataFrame / ว่าง | `ValueError("FAIL-FAST: Cannot compute support/resistance from M5 OHLCV")` | `advanced_tools_manager.py:40-41` |
| `MarketStructureEngine` | แท่ง < `lookback` | `ValueError("FAIL-FAST: Neutral state removed")` | `market_structure_engine.py:24-25` |
| `Orchestrator.__init__` | โหลด config / classifier / news calendar พัง | `logger.exception` แล้ว **`raise` ต่อ** | `:105-106, 115-117` |
| `_save_txt_payload` | เขียนไฟล์พัง | `logger.exception` แล้ว **`raise` ต่อ** | `:442-445` |
| `mode_loader` | โหมดไม่รู้จัก / ไม่พบ orchestrator / ไม่มีคลาส `Orchestrator` | `ValueError` / `FileNotFoundError` / `ImportError` (ล้วนขึ้นต้น `FAIL-FAST:`) | `mode_loader.py:22, 35, 42-44` |

### จุดที่ **ไม่** Fail-Fast (เงียบไว้)
| จุด | พฤติกรรม |
|:---|:---|
| `evaluate_cycle` ต่อคู่เงิน (`:157-166`) | `logger.exception` → เก็บเข้า `failed_symbols` → วนคู่ถัดไป |
| Retention ลบไฟล์เก่า (`:1348-1352`) | `except OSError: pass` — silent |
| `rq_res` เมื่อ `state_data` ไม่มี `metrics` (`:754-755`) | คืน `{}` ว่าง ไม่ raise |
| `check_news_impact` เมื่อ symbol ไม่อยู่ใน cache | เรียก `update_all_news_impact([symbol])` แล้ว default `'LOW'` |

---

## 🔢 ตารางค่าคงที่ทั้งหมดใน Part 2 (พร้อมที่มา)

| ค่า | ตัวเลข | ไฟล์:บรรทัด |
|:---|:---:|:---|
| ThreadPool ของ `evaluate_cycle` | ≤ 20 workers (`Part2EvalWorker`) | `orchestrator.py:149-151` |
| ThreadPool ของ 5 Engines | 5 workers | `orchestrator.py:644` |
| ThreadPool ของ 4 supplementary | 4 workers (`:712-717`) | `orchestrator.py:712` |
| แท่งขั้นต่ำที่อ่านจากดิสก์ | 250 ต่อ TF | `orchestrator.py:216-218` |
| แท่งขั้นต่ำก่อนรัน engine | 50 ต่อ TF | `orchestrator.py:286` |
| `ROUND_DECIMALS` | 6 | `indicator_store.py:30` |
| `ADX_PERIOD` / `VOLUME_MA_PERIOD` / `SLOPE_PERIOD` | 14 / 20 / 10 | `indicator_store.py:31-33` |
| Warm-up guard ของ IndicatorStore | M1 250, M5 250, M15 250 | `indicator_store.py:62-67` |
| Bollinger | period 20, 2σ | `core_indicators.py:13-17` |
| `bbw_sma_100` window | 100 | `core_indicators.py:29-30` |
| RSI period | 14 (`alpha = 1/14`) | `core_indicators.py:34-40` |
| MACD | 12 / 26 / 9 | `core_indicators.py:50-55` |
| **Stochastic** | **13 → 10 → 3** | `core_indicators.py:70-78` |
| Floor Pivot | `P=(H+L+C)/3`, `R1=2P−L`, `S1=2P−H` | `indicator_store.py:127-146` |
| `sr_interaction` threshold | `atr × 0.5` | `advanced_tools_manager.py:108` |
| `body_strength` = STRONG เมื่อ | body > 0.1 | `advanced_tools_manager.py:150` |
| wick dominance lookback | 20 แท่ง | `advanced_tools_manager.py:63` |
| จำนวน market state | 10 | `market_state_classifier.py:46-50` |
| state history | `deque(maxlen=5)`, ต้อง ≥ 3 ใน 5 | `market_state_classifier.py:54-55, 565-567` |
| confidence formula | `min(100, 50 + margin/100 × 50)` | `market_state_classifier.py:272-274` |
| LIQUIDITY_VOID hysteresis | margin ≥ 15 | `market_state_classifier.py:279-286` |
| `is_tradeable_regime` | `overall_quality ≥ 60` | `orchestrator.py:751` |
| risk_level HIGH เมื่อ | `noise > 0.5` หรือ `volatility_regime == EXTREME` | `market_state_classifier.py:113` |
| stability formula | `100(1−noise)(1−vol/100×0.3)(0.5+0.5·min(1,adx/50))` | `market_state_classifier.py:623` |
| Believe signal threshold | score ≥ **0.60** + structure ตรง | `orchestrator.py:970-971` |
| Believe EXTREME threshold | score ≥ **0.75** | `orchestrator.py:977` |
| Believe weights | 0.30 / 0.25 / 0.15 / 0.15 / 0.15 / 0.10 / +0.05 | `orchestrator.py:939-968` |
| BB %B ยืนยัน | ≤ 0.20 (bull) / ≥ 0.80 (bear) • แตะขอบ ≤ 0.15 / ≥ 0.85 | `orchestrator.py:949, 952, 935` |
| Stochastic extreme | k ≤ 10 / k ≥ 90 | `orchestrator.py:899-903` |
| NS active | `|rsi−50| < 20` และ `|stoch_k−50| < 20` | `orchestrator.py:1057` |
| SignalThrottle cooldown | default 300 s, global 60 s, แพ้ → ≥180 s, ชนะ → ≤600 s | `signal_throttle.py:22-25, 92-94` |
| Retention payload | **30 ไฟล์ล่าสุด/คู่เงิน** | `orchestrator.py:1343-1348` |
| payload line count | 99 (ai/ml) / **114** (strategies) | `_format_core_analysis_output` |
| `core_analysis` field count | **74** (comment บอก 83 — ผิด) | `orchestrator.py:499` |
| key padding width | 25 ตัวอักษร (ในฟังก์ชันที่ไม่ได้ใช้) | `orchestrator.py:1151` |
| News fetch timeout | 10 s (ทั้ง JSON และ CSV feed) | `news_calendar.py:172, 202` |
| News window | ล่วงหน้า 30 นาที / ย้อนหลัง 15 นาที | `news_calendar.py:459, 541-544` |
| Log rotation ของ Part 2 | 50 MB × 1000 backup | `console_dashboard.py:92-93` |

---

## 🗑️ Dead Code ใน Part 2 (มีอยู่แต่ไม่มีผู้เรียก)

| รายการ | ตำแหน่ง | หมายเหตุ |
|:---|:---|:---|
| `_generate_yaml_text()` | `orchestrator.py:1136-1159` (ทั้ง 3 โหมด) | ตัวเดียวที่ `import yaml` และจัด key pad 25 ตัวอักษร — **ไม่ถูกเรียก** payload จริงมาจาก `_format_core_analysis_output()` |
| `_flatten_dict()` | `orchestrator.py:1124-1134` | เรียกตัวเองแบบ recursive เท่านั้น ไม่มีผู้เรียกจากภายนอก |
| `run_parallel_processing()` | `indicator_store.py:397` | ฟังก์ชันระดับ module — ไม่มีผู้เรียก |
| `export_txt_payload()` | `orchestrator.py:452-462` | สวิตช์ debug แบบ on-demand — ไม่มีผู้เรียก |
| `update_ai_memory()` | `orchestrator.py:123-131` | ไม่มีผู้เรียก → `self.ai_memory` ว่างตลอด → `supplementary_data.recent_ai_memory` = `[]` เสมอ |
| `IndicatorStore.get_full_snapshot()` / `get_all_symbols()` | `indicator_store.py:332, 337` | ไม่มีผู้เรียกใน flow ปกติ |
| `Config.SLOPE_PERIOD` | `indicator_store.py:33` | ประกาศไว้ แต่โค้ดใช้เลข `10` ตรง ๆ |
| indicator ที่ comment ทิ้งเป็นแถบ | `indicator_store.py:246-297` (M15) • `:176-195` (M1) | ทุกบรรทัดระบุเหตุผล "Removed as not used by any engine" |
| M15 เกือบทั้งหมด | — | ในทุกโหมด M15 คำนวณแค่ `ema20`, `ema50`, `bias`, `rsi14` — ที่เหลือ (BB, MACD, Stoch, ATR, ADX, Volume, ROC, Slope, Pivot, OHLCV) **comment ออกหมด** |

---

## 🔗 สัญญาระหว่าง Part 2 กับ Part ต่าง ๆ

### รับจาก Part 1
| สิ่งที่ได้รับ | ทางไหน |
|:---|:---|
| แท่งเทียน OHLCV + `age` + `quality` | **ไฟล์ CSV** `data_base/output_feed/<SYM>/<SYM>_<TF>.csv` (8 คอลัมน์, 250 แถว) |
| ข่าวเศรษฐกิจ | `news_calendar.py` ดึงเอง (Part 2 เป็นเจ้าของ ไม่ใช่ Part 1) |

### ส่งให้ Part 3
| สิ่งที่ส่ง | ทางไหน |
|:---|:---|
| Prompt Payload | **ไฟล์ `.txt`** `data_base/output_evaluate/<mode>/<SYM>/<ID>.txt` (99 หรือ 114 บรรทัด) |
| ผู้มีสิทธิ์อ่าน | `believe_analyzer.py` (strategies) / `SystemPrompt` ใน `ai_dispatcher.py` (ai) / `MLDispatcher` (ml) — ผ่าน `DecisionManager.process_latest()` |
| สิ่งที่ **ไม่** ส่ง | `ap_confirmation`, `ns_confirmation`, `believe` รายละเอียดเต็ม, ผล supplementary engines ส่วนใหญ่ — อยู่แค่ใน RAM แล้วถูกทิ้ง |

### สิ่งที่ Part 4 คาดหวังแต่ Part 2 ไม่ได้ส่งให้ตรง
| Part 4 (`gate_controller.py`) ต้องการ | Part 2 ส่งให้ | ผล |
|:---|:---|:---|
| `m15_direction` | `m15_bias` — แต่ใน strategies_mode ค่านี้**คำนวณจาก M5** | เกตผ่านเสมอแต่ตรวจสอบผิดตัว |
| `m5_direction` | `m5_bias` (ย่อหน้า 4 space) | `_extract_evidence()` ใช้ regex `^\s*…` จึงอ่านได้ ✅ |
| `m5_regime` | `m5_trend_type` | อ่านได้ ✅ |
| `m5_adx` | `m5_adx` | อ่านได้ ✅ |
| `risk_level` | `dl_risk_level` | ⚠️ key คนละชื่อ — gate ค้นหา `risk_level`/`risk` ซึ่ง**ไม่มี**ใน payload → `Missing risk evidence` |
| `quality_score` | `dl_quality_score` | ⚠️ key คนละชื่อ — gate ค้นหา `quality_score` → ไม่เจอ |
| `m1_quality`, `m5_quality` | มี ✅ | อ่านได้ |

---

## 🖥️ Log ของ Part 2

`setup_logging()` (`console_dashboard.py:67`) แยก log ของ Part 2 ออกจาก Part 1 ด้วย **ชื่อ logger**

| ไฟล์ | Level | เนื้อหา |
|:---|:---|:---|
| `logs/logs_data_evaluate/errors/error.log` | `ERROR`+ | error ของ Part 2 |
| `logs/logs_data_evaluate/warnings/warning.log` | `WARNING` เท่านั้น | warning ของ Part 2 |

- `Part2Filter` (`console_dashboard.py:130-132`) จับ logger ที่ชื่อขึ้นต้นด้วย:
  `data_evaluate`, `Orchestrator`, `AdvancedToolsManager`, `IndicatorStore`, `MarketStateClassifier`,
  `TrendEngine`, `StrengthEngine`, `VolatilityEngine`, `StructureEngine`, `MTFEngine`,
  `ExplainabilityEngine`, `LiquidityEngine`, `NoiseDetector`, `ProbabilityEstimator`,
  `SignalThrottle`, `ContextSynthesizer`, `MarketStructureEngine`, `MarketPressureAnalyzer`
  (`console_dashboard.py:109-128`)
- ⚠️ `indicator_store.py:22-25` เรียก `logging.basicConfig(...)` เองที่ระดับ module — ชนกับ `setup_logging()` ของ `console_dashboard.py`
  (อันไหนรันก่อนมีผลต่อ format ของ root logger)
- Console: `[ Payload Export: n/m | Failed: … ]` และ `[Bot Evaluate Market Complete n asset]` (`console_dashboard.py:415-419`)
- ⚠️ logger ชื่อ `TrapDetector`, `BehaviorAnalyzer`, `CandlePatternAnalyzer` ฯลฯ **ไม่อยู่ใน `part2_names`**
  → log ของ tool เหล่านั้นจะไปลง `logs_data_feed/` (Part 1) แทน

---

## 🧪 การทดสอบและตรวจสอบ Part 2

### วิธีรัน (ต้องผ่าน `runner.py` เท่านั้น — `agent.md` Rule 13/14/15)
```powershell
python runner.py --mode strategies     # โหมดที่ active อยู่
python runner.py --mode ai
python runner.py --mode ml
```
⚠️ รันได้เฉพาะ **Windows** (`runner.py:17` import `msvcrt`)
⚠️ ปัจจุบัน**สตาร์ทไม่ผ่าน**เพราะ `ExecutorManager.__init__` import `chronos_dispatcher` ที่หายไปจาก repo (`readme.md` P1) — เกิดขึ้น**ก่อน** Part 2 ทำงาน

### Two-Tier Verification (Rule 17)

**Tier 1 — Code Inspection**

| ตรวจอะไร | ที่ไหน |
|:---|:---|
| โหมดที่โหลดถูกโฟลเดอร์ | `mode_loader.load_orchestrator_class()` + `sys.modules["data_evaluate.orchestration"].__path__` |
| `orchestrator_log_dir` ชี้ถูกที่ | `runner.py:158-160` override ก่อนสร้าง Orchestrator |
| TF ที่อ่านตรงกับโหมด | `orchestrator.py:189` (strategies = S30/M1/M5) |

**Tier 2 — Live Data Inspection**

| ตรวจอะไร | เกณฑ์ |
|:---|:---|
| `data_base/output_evaluate/<mode>/<SYM>/` ถูกสร้าง | มีโฟลเดอร์ต่อคู่เงิน |
| จำนวนบรรทัดของ `.txt` | **99** (ai/ml) หรือ **114** (strategies) — นับด้วย `wc -l` จะได้เท่านี้พอดีเพราะมี trailing newline |
| บรรทัดแรก | `ID:<SYMBOLไม่มีขีด><MMDDHHMMSS>` และ **ไม่มี space หลัง `:`** |
| ID ตรงกับ timestamp ใน `meta.timestamp` | MMDDHHMMSS ต้องตรงกับเวลาไทยของรอบนั้น |
| จำนวนไฟล์ต่อโฟลเดอร์ | **ไม่เกิน 30** (retention) |
| `m15_bias` | ใน strategies_mode จะมีค่า (มาจาก M5) — **ไม่ควรว่าง** ถ้าว่างแปลว่า alias ไม่ทำงาน |
| `believe_strategy:` block | ต้องมี 6 ฟิลด์: status / direction / confidence / score / extreme_believe_active / extreme_believe_setup |
| `believe_direction` | `BUY` / `SELL` / `WAIT` (ไม่ใช่ CALL/PUT) |
| 3 ฟิลด์ท้ายของ `decision_layer` | ต้องเป็น `รอการวิเคราะห์จาก AI` |
| `ai_model` ใน `meta` | ตรงกับสมองที่ใช้งานจริง (ปัจจุบันจะขึ้น `CHRONOS_2_ONNX` แม้รัน strategies_mode — ดูหมายเหตุ) |
| `calendar_<วันนี้>.txt` | มี 1 ไฟล์ต่อโหมด และ**อยู่ที่ path ซ้อน 2 ชั้น** (ดูหัวข้อปฏิทินข่าว) |
| `logs/logs_data_evaluate/errors/error.log` | ไม่มี traceback ใหม่ |

---

## 📌 สรุปความพร้อมส่งมอบส่วนงานที่ 2 (Delivery Sign-Off)

✅ อ่าน CSV 8 คอลัมน์จากดิสก์เท่านั้น (Disk-Only Boundary) พร้อม warm-up guard 250 แท่ง
✅ คำนวณ indicator ครั้งเดียวที่ `IndicatorStore` (SSOT) — Engine/Classifier/Tools อ่านต่อ ไม่คำนวณซ้ำ
✅ รัน 5 Tier-1 Engines แบบขนาน + validate ฟิลด์บังคับครบทุกตัว
✅ รัน 10 Advanced Tools → ประกอบ `price_action` (15) + `advanced_signals` (6)
✅ จำแนกตลาดเป็น 1 ใน 10 state ด้วย weighted scoring + hysteresis + smoothing
✅ รัน 9 supplementary modules (TIER 3/4/5/6/8) → `supplementary_engines`
✅ คำนวณ Believe บน M1 (strategies_mode) ด้วย weighted score ≥ 0.60 / EXTREME ≥ 0.75
✅ ตัดฟิลด์ซ้ำด้วย `_deduplicate_payload()` แล้วจัดรูปเป็น `core_analysis` 74 ฟิลด์ + `supplementary_data` 11 กุญแจ
✅ Serialize เป็น `.txt` **99 บรรทัด** (ai/ml) หรือ **114 บรรทัด** (strategies) ที่ `data_base/output_evaluate/<mode>/<SYM>/<ID>.txt`
✅ Retention 30 ไฟล์ล่าสุดต่อคู่เงิน + `store.clear_symbol()` กัน memory leak
✅ เป็นเจ้าของปฏิทินข่าวเศรษฐกิจ (1 ไฟล์/วัน/โหมด, cache รายวัน, pre-calculated lookup ใต้ `_NEWS_LOCK`)

**สิ่งที่ Part 2 ไม่ทำโดยเจตนา:** ไม่ตัดสินใจเทรด (`_is_tradeable()` ตรวจแค่ความครบของข้อมูล — docstring ระบุชัดว่า
*"The actual decision to trade or not trade is NOT the responsibility of Part 2"*), ไม่ยิงออเดอร์, ไม่แก้ไขข้อมูลของ Part 1

---

## 🔍 ภาคผนวก: เทียบกับเอกสาร Part 2 รุ่นก่อน

เอกสารรุ่นก่อนของ Part 2 (ซึ่งมีเนื้อหา**ซ้ำกัน byte-for-byte กับ Part 3 และ Part 4**) ระบุไว้ดังนี้

| ข้ออ้างเดิม | ความจริง |
|:---|:---|
| "Prompt Payload มาตรฐาน **99 บรรทัด**" | 99 บรรทัดเฉพาะ `ai_mode`/`ml_mode` • `strategies_mode` = **114 บรรทัด** |
| "ผ่าน **24 Execution Gates**" | Part 4 มี **15 ข้อตรวจสอบ** (`gate_controller.py`) — และไม่ใช่งานของ Part 2 |
| "`ml_dispatcher.py` และ `ai_dispatcher.py` เป็น **2 โมดูลเดียว**ที่ได้รับสิทธิ์อ่านไฟล์ 99 บรรทัด" | มีผู้อ่านที่ 3 คือ `believe_analyzer.py` (strategies_mode) และทั้งสามถูกเรียกผ่าน `DecisionManager` |
| "Expiry **1-5 นาที**" | Part 4 บังคับ `expiry_minutes == 5` เท่านั้น — ค่าอื่น reject |
| "Confidence Score 0-100%" | ถูกต้อง แต่ threshold ที่ Part 4 ใช้คือ **55%** |
| โมดูลชื่อ `ai_analysis/` | ชื่อจริงคือ **`data_decision/`** |
| Part 2 ส่ง "Payload **74 ฟิลด์**" | **74 = จำนวนฟิลด์ใน `core_analysis` จริง** ✅ แต่ comment ในโค้ดเขียนว่า "83 Fields" ซึ่งผิด และจำนวน**บรรทัด**ของไฟล์คือ 99/114 |
| ไม่เอ่ยถึง S30 / Believe / strategies_mode เลย | ทั้งสามอย่างเป็นหัวใจของโหมดที่ active อยู่ปัจจุบัน |
| ไม่เอ่ยถึง `mode_loader.py` และการ trampoline `sys.modules` | เป็นกลไกสำคัญที่สุดในการสลับโหมด |

---

## 📚 เอกสารที่เกี่ยวข้อง

| เอกสาร | path |
|:---|:---|
| กฎวินัย AI 27 ข้อ | `agent.md` (Rule 10 SSOT, Rule 18 Part 1&2 Immutability, Rule 20 Payload schema, Rule 21 Handover, Rule 22 News calendar) |
| ภาพรวมระบบ + P1–P13 | `readme.md` |
| Part 1 INPUT | `docs/กระบวนการทำงานของบอท Part1 data_feed/กระบวนการทำงานของบอท Part1 data_feed.md` |
| Part 3 OUTPUT | `docs/กระบวนการทำงานของบอท Part3 data_decision/กระบวนการทำงานของบอท ส่วนที่ 3 OUTPUT.md` *(ยังไม่ซิงก์กับโค้ด)* |
| Part 4 TRADE | `docs/กระบวนการทำงานของบอท Part4 data_trade/กระบวนการทำงานของบอท Part4 data_trade.md` *(ยังไม่ซิงก์กับโค้ด)* |
| E-BOOK ต้นฉบับกลยุทธ์ Believe | `docs/strategies/E-BOOK [V.1] ทำกำไร 10 วินาที by nemesis.pdf` |
| error log ของ Part 2 | `logs/logs_data_evaluate/errors/error.log` |

---

> **📝 บันทึกการปรับปรุงเอกสาร**
> **22 ก.ย. 2026** — เขียนใหม่ทั้งฉบับ (แทนที่ไฟล์เดิมที่มีเนื้อหาซ้ำกับ Part 3/4) ให้ตรงกับ source code ณ commit `0990519`
> เพิ่ม: ผล `diff` จริงของ 3 โหมด (ต่างแค่ 2 ไฟล์), กลไก `mode_loader` trampoline, 11 ขั้นตอนของ `process_cycle`,
> ตาราง indicator ต่อ TF (active vs comment ออก), 10 market states + สูตร scoring/smoothing/quality/stability,
> 9 supplementary modules พร้อม TIER, Believe บน M1 + น้ำหนักคะแนน, `core_analysis` 74 ฟิลด์,
> schema payload 99/114 บรรทัด, ปฏิทินข่าว 3 แหล่ง + path ที่ซ้อน 2 ชั้น, บัญชี Fail-Fast ทุกจุด,
> ตารางค่าคงที่ 40+ รายการพร้อม `file:line`, บัญชี dead code, สัญญาระหว่าง Part 2 ↔ Part 1/3/4
> แก้: "99 บรรทัด" → 99/114 ตามโหมด • "24 Execution Gates" → 15 (และไม่ใช่หน้าที่ Part 2) • `ai_analysis/` → `data_decision/` • Expiry 1-5 นาที → 5 นาทีตายตัว
> หมายเหตุ: ตัวเลข "74 ฟิลด์" ในเอกสารรุ่นก่อน **ถูกต้อง** ในความหมายของ `core_analysis` — ฉบับนี้ระบุให้ชัดว่าคนละหน่วยกับจำนวนบรรทัดของไฟล์
