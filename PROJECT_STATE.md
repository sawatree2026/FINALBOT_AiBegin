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
