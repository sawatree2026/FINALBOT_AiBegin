# 🧠 FINALBOT — กระบวนการทำงานของบอท ส่วนที่ 3: DECISION

> ✅ **ตรวจทานและเขียนใหม่ให้ตรงโค้ดจริง ณ commit `e709349`** (2026-09-26)
> โครงสร้างไฟล์/ฟังก์ชัน/ฟิลด์ทุกจุดอ้างอิงจาก source จริง — หากโค้ดกับเอกสารขัดกัน ให้ยึดโค้ดแล้วแก้เอกสารนี้

---

## 🎯 หน้าที่

อ่าน **Payload 99 บรรทัด** (`.txt`) ที่ Part 2 เขียนบนดิสก์ → วิเคราะห์ตาม `active_mode` →
เขียน **Decision JSON** ลงโฟลเดอร์ของโหมดนั้นให้ Part 4 มาอ่าน
**ห้ามส่ง payload object/text ข้าม Part ผ่าน RAM** (boundary = ดิสก์เท่านั้น)

```
data_base/<mode>/output_evaluate/<SYMBOL>/<ID>.txt        ← อ่าน
                    ↓  เลือก engine ตาม active_mode
data_base/<mode>/output_decision/<mode>_decision/…json    ← เขียน  (ดูตารางโหมดด้านล่าง)
```

---

## 🗂️ โครงสร้างไฟล์จริง (ใหม่)

```
data_decision/
├── strategies_mode/
│   ├── decision_manager.py            ← DecisionManager (coordinator)
│   └── believe_strategies/
│       ├── believe_analyzer.py          analyze_payload_file() — จุดเข้าหลัก
│       ├── bollinger_percent.py         core #1 (BB %B)
│       ├── stochastic.py                core #2
│       ├── moving_average.py            core #3
│       ├── grid.py · support_resistance.py · price_action.py
│       ├── divergence.py · macd.py · rsi.py · ap.py · ns.py
│       └── field_utils.py               strict reader (fail-fast)
└── ai_mode/
    ├── artificial_intelligence/  ai_dispatcher.py (SystemPrompt) · gemini_bridge.py · deepseek_bridge.py
    └── machine_learning/         ml_dispatcher.py · dual_brain.py · machine_lightgbm.py ·
                                  machine_chronos.py · feature_extractor.py ·
                                  machine_learning_model/EURUSD_lightgbm/
```
> การ route ทั้ง 4 Part ทำผ่าน **`config_setting/mode_loader.py`** (central dispatcher) —
> `normalize_mode()` รับ alias (`strategies|ml|ai`) และ `load_executor_manager()` ผูก Part 4

---

## 🔀 Routing ตามโหมด (`decision_manager.py`)

| `active_mode` | Engine | โฟลเดอร์ decision |
|---|---|---|
| `strategies_mode` ⭐ | `believe_analyzer.analyze_payload_file()` | `data_base/strategies_mode/output_decision/strategies_decision/` |
| `ai_mode` | `SystemPrompt.process_ai_decision()` | `…/ai_decision/` |
| `ml_mode` | `MLDispatcher.get_instance().process_payload_file()` | `…/ml_decision/` |

- เลือก payload ล่าสุดจาก mtime (`_latest_payload`) · **ไม่มี payload = `raise FileNotFoundError` (fail-fast)**
- กันประมวลผลซ้ำด้วย `self._processed`
- เขียนแบบ atomic: `.tmp` → `flush` → `os.fsync` → `os.replace`
- Metadata ที่เติมเสมอ: `payload_id`, `payload_filepath` (abspath), `source_part="data_evaluate"`, `mode`, `written_at`

---

## 💎 เส้นทาง strategies → Believe (NEMESIS)

### สัญญา payload ที่ analyzer บังคับ (42 fields — **ขาดตัวเดียว raise**)
`id, s30_bias, m1_bias, m5_bias, believe_direction, believe_bb_percent_b, believe_bb_touch,
believe_sto_k/d/zone/cross/hook_confirmed/cross_50, believe_risk_sto_tangled,
believe_ma_cross, believe_ma_cross_confirmed, believe_risk_grid_block/gray_candle/trap_alert/room_to_run_clear,
m5_pa_pattern/last_candle_bias/sr_interaction/divergence_alert,
s30_macd, s30_macd_signal, s30_macd_histogram, s30_rsi, ap_signal, ns_signal,
believe_confidence, believe_status, m5_trend_type, dl_risk_level, extreme_believe_active,
m1_adx, m5_quality`

> 🔒 **FIX 2026-09-26:** analyzer **ไม่มีค่า default ประดิษฐ์** อีกต่อไป
> (เดิมเคยแต่ง `believe_confidence="HIGH"`, `dl_risk_level="LOW"`, `m1_adx=25.0` ฯลฯ)
> — ฟิลด์ขาด = fail-fast ตามวินัย Zero-Mock

### การตัดสินใจ
```
candidate   = believe_direction (CALL/PUT) มิฉะนั้น WAIT   # WAIT เป็นผลถูกต้อง ไม่ถูกแทนด้วยทิศอื่น
aligned     = s30 == m1 == m5 == candidate
core        = bollinger_percent AND stochastic AND moving_average      # ต้องผ่านครบ
filters     = ไม่ grid_block · ไม่ gray_candle · ไม่ stoch_tangled · ไม่ trap · room_to_run ไม่ False
action      = candidate ถ้า (aligned AND core ครบ AND filters ผ่าน) มิฉะนั้น WAIT
confidence  = HIGH→85 · MEDIUM→70 · อื่น→60   (WAIT→0)
expiry      = 3 นาที  (strategies)   # ⚠️ ต่างจาก readme เก่าที่เขียน 5 — ดู DOC_AUDIT M-8
```
- **core #1 BB %B:** CALL ผ่านเมื่อ `%B ≤ 0.45` หรือ touch ∈ {LOWER,…,NONE} · PUT เมื่อ `%B ≥ 0.55` หรือ touch ∈ {UPPER,…,NONE}
- **core #2 STO:** `(extreme OR reversal)` และไม่ tangled · extreme = zone OVERSOLD/"10"/`min(k,d)≤35` (CALL) หรือ OVERBOUGHT/"90"/`max(k,d)≥65` (PUT)
- **core #3 MA:** `believe_ma_cross` ∈ {GOLDEN_CROSS/UP/…} และ `believe_ma_cross_confirmed = TRUE`
- secondary (price_action, grid_clear, support_resistance_clear, divergence, macd, rsi, ap, ns) = **confirmation/วินิจฉัยเท่านั้น ไม่บังคับเข้า**

### Decision JSON (ตัวอย่างฟิลด์)
`ID, symbol, action, expiry_minutes, confidence_score, engine_used="STRATEGY_BELIEVE",
believe_status, believe_direction, s30/m1/m5_direction, m1_bias, m5_bias, m5_regime, m1_adx,
risk_level, data_quality, extreme_believe_active, core_conditions{}, secondary_conditions{},
risk_filters{}, conditions_met, failed_conditions[], reason_th` + metadata ข้างต้น

---

## 🤖 เส้นทาง ai_mode (Cloud AI)

- `ai_dispatcher.SystemPrompt` อ่าน payload 99 บรรทัดจากดิสก์ → ส่ง Gemini (`primary_model` ใน settings)
- **API key มาจาก environment เท่านั้น** (`GEMINI_API_KEY` ผ่าน `.env`) — `settings.json` เก็บค่าว่าง
- key ว่าง/bridge ล่ม = **fail-fast ชัดเจน** (ไม่มีการ fallback โมเดล)
- เขียนเพิ่ม: `data_trade/ai_output/<SYMBOL>/decision_<SYM>_<TS>.json` + CSV audit
- ⚠️ ยังใช้งานจริงไม่ได้จนกว่าบอสตั้ง `GEMINI_API_KEY`

## 🧠 เส้นทาง ml_mode (Dual-Brain)

- `MLDispatcher` (singleton) → LightGBM + Chronos-2 ONNX → `agreement_valid`
- ⚠️ ยังใช้งานจริงไม่ได้จนกว่ามีไฟล์ `chronos-2-onnx/model.onnx` (fail-fast ตอนสร้าง engine)

---

## 🛡️ กฎที่เกี่ยวข้อง

| กฎ | เนื้อหา |
|---|---|
| Single Gateway | อ่าน payload ผ่าน dispatcher/analyzer ของโหมดเท่านั้น |
| SSOT | ห้ามคำนวณ indicator ซ้ำ — อ่านจาก payload |
| Zero-Mock / Fail-Fast | ฟิลด์ขาด/ผิดชนิด = raise · ห้ามค่าแทน |
| Immutability | ห้าม mutate dict ที่รับมา |
| Mode routing | เขียน decision ลงโฟลเดอร์โหมดตัวเองเท่านั้น |

📎 ดูเพิ่ม: [ส่วนที่ 4 EXECUTION](../กระบวนการทำงานของบอท%20Part4%20data_trade/กระบวนการทำงานของบอท%20Part4%20data_trade.md) ·
[ส่วนที่ 2 PROCESS](../กระบวนการทำงานของบอท%20Part2%20data_evaluate/กระบวนการทำงานของบอท%20Part2%20data_evaluate.md) ·
รายการตรวจทาน: `DOC_AUDIT_2026-09-24.md` (อยู่ในคลังเอกสารของ AI session)
