# 🛡️ FINALBOT — กระบวนการทำงานของบอท ส่วนที่ 4: EXECUTION

> ✅ **ตรวจทานและเขียนใหม่ให้ตรงโค้ดจริง ณ commit `e709349`** (2026-09-26)
> (เอกสารรุ่นก่อนซ้ำกับไฟล์ Part 3 ทั้งดุ้นและอ้าง Digital fallback ที่ถูกลบแล้ว — เขียนใหม่ทั้งหมด)

---

## 🎯 หน้าที่

อ่าน **Decision JSON** ของโหมดที่ active → กลั่นด้วย ExecutionGate + MoneyManager →
ยิงออเดอร์จริงผ่าน broker → ติดตามจนครบอายุ → บันทึก history

```
data_base/<mode>/output_decision/<…>/<SYMBOL>/<ID>.json   ← อ่าน (ตรงโหมดเท่านั้น)
        ↓  ExecutorManager (โหลดผ่าน config_setting/mode_loader.py)
   ExecutionGate → MoneyManager → BrokerExecutor → OrderTracker
        ↓
data_base/<mode>/output_trade/trades_history.csv + <SYMBOL>.csv
```

---

## 🗂️ โครงสร้างไฟล์จริง (ใหม่)

```
data_trade/
└── strategies_mode/                  ← ที่อยู่ปัจจุบันของ executor/gate ทั้ง 3 โหมด
    ├── executor_manager.py             ExecutorManager (coordinator)
    ├── payload_sanitizer.py            ตัด legacy decision_layer ก่อนเข้า gate
    └── execution_gate/
        ├── gate_controller.py            ExecutionGate
        ├── money_manager.py              MoneyManager (7 เงื่อนไข)
        ├── broker_executor.py            BrokerExecutor (retry ≤3)
        └── order_tracker.py              OrderTracker (ThreadPool 10)
```
> ⚠️ โค้ด Part 4 ของ **ทั้ง 3 โหมด** ยังกองอยู่ในโฟลเดอร์ `strategies_mode/`
> (เลือกพฤติกรรมรายโหมดภายใน) — จดไว้เป็นงานจัดโครงสร้าง F-10

---

## 🧭 การเลือกไฟล์ decision ตามโหมด (`executor_manager.process_decision_files`)

| active_mode | โฟลเดอร์ที่อ่าน |
|---|---|
| strategies_mode | `strategies_decision/` (fallback `output_decision/`) |
| ml_mode | `ml_decision/` (fallback เดิม) |
| ai_mode | `ai_decision/` (fallback เดิม) |

- กันประมวลผลซ้ำด้วย key `mode:path:mtime`
- decision ต้องมี `payload_filepath` ที่อยู่จริง → ไม่งั้น **fail-fast**
- โหลด executor ผ่าน `mode_loader.load_executor_manager()` ซึ่งตั้ง `trade_history_file`
  เป็น `data_base/<mode>/output_trade/trades_history.csv` ให้ MoneyManager อัตโนมัติ

---

## 🚦 ExecutionGate (`gate_controller.py`) — policy `part4-regime-gated-trend-v1`

| ค่าคงที่ | ค่า |
|---|---|
| `MIN_ADX` | 20.0 |
| `MIN_DATA_QUALITY` | 50.0 |
| `min_confidence` | `ai_mode.min_confidence` → fallback `ml_mode.min_confidence` → 55.0 (clamp 0-100) |
| `expected_expiry` | **3 นาที ถ้า strategies_mode · 5 นาที ถ้าโหมดอื่น** |

**เงื่อนไขปฏิเสธ (16 ข้อ):** WAIT/invalid action · expiry ไม่ตรง expected · confidence ต่ำกว่าเกณฑ์ ·
Gemini/Chronos disagreement · HTF direction หาย · M5 direction หาย · M5 regime หาย · ADX หาย/ต่ำกว่า 20 ·
risk หาย/สูง (HIGH,CRITICAL,EXTREME) · ข้อมูล STALE/quality<50 · regime CHOPPY · HTF/M5 ขัดกัน · action สวน HTF

- **HTF context:** `strategies_mode` → **M5** · โหมดอื่น → **M15**
- ไม่ผ่าน → บังคับ `action=WAIT` + รวมเหตุผลทั้งหมดลง `reason`
- ผ่าน → คืน `approved=True` พร้อม `context_timeframe`, `htf_direction`, `m5_regime`, `m5_adx`, `risk_level`, `data_quality_ok` เพื่อ audit

---

## 💰 MoneyManager — 7 เงื่อนไข (`can_trade`)

1 ห้ามยิงซ้ำคู่เงินที่มีออเดอร์ค้าง · 2 เต็มโควตาออเดอร์พร้อมกัน · 3 เต็มโควตาไม้ต่อวัน ·
4 แพ้ติดกันถึงโควตา + cooldown (TZ +07) · 5 แตะ daily SL · 6 แตะ daily TP · 7 balance < stake
→ ผ่านครบคืน `RISK_GATES_PASSED`

ค่าจาก `settings.json → account`: `stake_per_trade 35` · `max_daily_loss 500` · `max_daily_profit 1000` ·
`max_daily_trades 200` · `max_concurrent_orders 100` · `max_consecutive_losses 100` · `cooldown_minutes 5`
(default ในโค้ดอนุรักษ์นิยมกว่า: 20/3/3)

---

## 📡 BrokerExecutor

- `api.buy(stake, symbol, action, expiry)` · ไล่ category `["turbo","binary"]` ตอน register symbol
- **retry สูงสุด 3 ครั้ง** ต่อออเดอร์ · fail-fast ถ้า symbol/action/stake/api ไม่ถูกต้อง
- ❌ **ไม่มี Digital Option fallback** — ถูกลบตามวินัย Zero-Fallback (docstring เก่าที่อ้างถึงถูกล้างแล้ว)

## 📊 OrderTracker

- ผลลัพธ์ 3 ค่า: **WIN / LOSE / EQUAL** (EQUAL = คืนเงิน)
- เขียน `data_base/<mode>/output_trade/<SYMBOL>.csv` + `trades_history.csv` (schema:
  `timestamp, order_id, symbol, action, stake, expiry_minutes, result, profit_amount, confidence_score, ai_engine, reason_th`)
- ThreadPool 10 workers + lock · แจ้ง `money_manager.record_trade_result()` เมื่อจบสัญญา

---

## 🔐 Credentials & การรัน

- **secret ทั้งหมดมาจาก environment** (`IQ_EMAIL`, `IQ_PASSWORD`, `GEMINI_API_KEY` ผ่าน `.env`) —
  `config_setting/config_loader.py` ให้ env ชนะ `settings.json` (ซึ่งถูก blank ไว้)
- `enable_live_execution=false` = **fail-fast error** ไม่ใช่ signal-only mode
- single-instance lock: `msvcrt` (Windows) / `fcntl` (POSIX) ที่ `logs/runner.lock`
- ทดสอบระบบต้องรันผ่าน `runner.py` แบบ foreground เท่านั้น และ kill ทันทีเมื่อจบ

---

## 🛡️ กฎที่เกี่ยวข้อง

Mode-matched routing (อ่าน decision โหมดตัวเองเท่านั้น) · Zero-Fallback · Fail-Fast ·
Foreground-only execution · Second-by-second logging · ห้ามรายงาน "สมบูรณ์" โดยไม่มีหลักฐานจาก log/output จริง

📎 ดูเพิ่ม: [ส่วนที่ 3 DECISION](../กระบวนการทำงานของบอท%20Part3%20data_decision/กระบวนการทำงานของบอท%20ส่วนที่%203%20OUTPUT.md) ·
[ส่วนที่ 2 PROCESS](../กระบวนการทำงานของบอท%20Part2%20data_evaluate/กระบวนการทำงานของบอท%20Part2%20data_evaluate.md)
