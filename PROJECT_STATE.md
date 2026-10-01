# FINALBOT System Architecture & Project State (Single Source of Truth)

## 1. Operating Modes (แยก 3 Mode เด็ดขาดทุก Part)
1. **strategies_mode (Nemesis Believe / Extreme):**
   - **Timeframes:** S30 (Entry), M1 (Trigger), M15 (Context / Bias). M5 ถูกตัดออกถาวรไม่ดึง feed และไม่คำนวณ.
   - **Indicators (E-Book Nemesis V.2 p.38):**
     - BB %B: Period 41, StdDev 2.0, Source Close, MA SMA, Overbought 1, Oversold 0.
     - Moving Average: EMA 3 (Fast, Red), SMA 6 (Slow, Green).
     - Stochastic: (13, 10, 3) lines 90/10.
     - MACD: (15, 35, 9).
     - Fractal: 5.
   - **Strategy Variations:**
     - **Believe Pure (Confidence 75%, Expiry 3m):**
       - CALL: BB% แตะ 0, STO แตะ 10 แล้วงัดขึ้น/ตัด 50, EMA 3 ตัด SMA 6 ขึ้น (Golden Cross).
       - PUT: BB% แตะ 1, STO แตะ 90 แล้วหักลง/ตัด 50, EMA 3 ตัด SMA 6 ลง (Death Cross).
       - Filter: ไม่มี Grid ขวาง, ไม่มีแท่งเทียนสีเทา, STO ไม่พันกัน.
     - **Believe Extreme (Confidence 88%, Expiry 3m):**
       - Primary: เกิด Divergence (STO หรือ RSI).
       - Position: MACD (15, 35, 9) อยู่ฝั่งตรงข้ามเส้น 0 (CALL อยู่ใต้ 0, PUT อยู่เหนือ 0).
       - Trigger: Believe Trigger (STO วกตัวออกจาก 10/90 + MA Cross).
2. **ai_mode:** Gemini + Chronos Dual Agreement, Expiry 5m, Context M15 + M5.
3. **ml_mode:** LightGBM / XGBoost signal models.

## 2. Pipeline Architecture (4 Parts)
- **Part 1: data_feed/strategies_mode/**
  - `data_adapter.py`: Ingest เฉพาะ S30, M1, M15 (M5 removed).
  - `data_cache_store.py`: Warmup requirements `{"S30": 250, "M1": 250, "M15": 250}`.
- **Part 2: data_evaluate/strategies_mode/**
  - `orchestrator.py`: คำนวณอินดิเคเตอร์ S30/M1/M15 ตาม Nemesis V.2 (BB 41/2.0, STO 13/10/3, MACD 15/35/9, EMA3/SMA6).
  - Export payload 99-line contract ลง SSD `data_base/strategies_mode/output_evaluate/<SYMBOL>/`.
- **Part 3: data_decision/strategies_mode/**
  - `decision_manager.py`: อ่าน payload จาก Part 2 ประเมิน Believe Pure / Believe Extreme.
  - `believe_strategies/`: `believe_analyzer.py`, `bollinger_percent.py`, `stochastic.py`, `moving_average.py`, `macd.py`, `divergence.py`.
  - Export decision JSON ลง SSD `data_base/strategies_mode/output_decision/<SYMBOL>/`.
- **Part 4: data_trade/strategies_mode/**
  - `executor_manager.py` & `execution_gate/gate_controller.py`:
    - ตรวจเงื่อนไข Gate (expiry=3m, confidence threshold, believe conditions met).
    - ส่งคำสั่งเทรดผ่าน `broker_executor.py` และบันทึกลง `order_tracker.py`.

## 3. Bug Fixes & Operational Alignment (2026-09-28)
- **Believe Filters Relaxed:** ปลดตัวกรอง `doji_window_15m` และ `gray_window_15m` ที่บล็อกออเดอร์ 100% ตลอด 15 นาที ให้ตรวจสอบเฉพาะแท่งก่อนหน้า (`prev_candle_bad`) ตาม E-Book Nemesis V.2 น.11
- **BB% Alignment:** ปรับ `bollinger_percent.py` ให้รองรับการเข้าเทรดในโซน (CALL <= 0.40, PUT >= 0.60 หรือแตะเส้น) ตามคำแนะนำ E-Book น.37 ("จะไม่แตะก็ได้")
- **Stochastic 50-Cross Continuity:** ปรับ `stochastic.py` ให้ตรวจการข้ามผ่าน 50 อย่างต่อเนื่องร่วมกับจังหวะ MA Cross ตาม E-Book น.37/49
- **12-Candle Setup Touch & 6-Candle Trigger Window (Part 2 & Part 3):** ขยายหน้าต่างจำประวัติการแตะจุดกลับตัว (BB% touch 0/1, STO touch 10/90) เป็น 12 แท่ง S30 (= 6 นาที) เพื่อรองรับรอบการเดินทางของ STO (13,10,3) จากโซน 0/10 ไปตัดเส้น 50 ได้ครบคลื่น โดยคงหน้าต่างตรวจจังหวะ MA Cross ที่ 6 แท่งล่าสุด
- **Removal of M15 Filter & Trend Blocking:** ตัดเงื่อนไข M15 ออกทั้งหมด และปลดล็อกการบังคับทิศทางตามเทรนด์ใหญ่ ให้ระบบ Believe ตัดสินใจเข้าออเดอร์ตามอินดิเคเตอร์กลับตัว (BB% + STO + MA) ตามตำราโดยตรง
- **Part 4 Direct Passthrough Execution (Zero Gate Delay):** ปลดเงื่อนไขทั้งหมดใน Part 4 สำหรับ strategies_mode คำสั่งใดที่ผ่านการตัดสินใจจาก Part 3 มาแล้ว Part 4 จะส่งคำสั่งเข้าโบรกเกอร์ทันทีโดยไม่มีการดีดทิ้งหรือตรวจสอบซ้ำซ้อน
- **Expiry 3m Harmonization (Part 3 & Part 4):** ปรับจูน `expiry_minutes: 3` ให้ตรงกันระหว่าง `believe_analyzer.py`, `gate_controller.py`, และ `executor_manager.py` แก้ไขปัญหา Gate ดีดออเดอร์ทิ้งสำเร็จ 100%
- **Believe Extreme Activation:** เปิดการทำงาน `STRATEGY_BELIEVE_EXTREME` (Confidence 88%) เมื่อตรวจพบ Divergence + MACD ฝั่งตรงข้ามเส้น 0 ร่วมกับสัญญาณ Believe ตาม E-Book น.50

