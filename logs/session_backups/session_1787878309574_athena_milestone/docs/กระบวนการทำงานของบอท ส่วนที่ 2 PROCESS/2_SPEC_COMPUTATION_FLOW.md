# SPEC: COMPUTATION FLOW — สถาปัตยกรรมประมวลผลข้อมูลผ่าน RAM 100%

## 🚀 หลักการประมวลผล (RAM-First Architecture & Clean Handover)
ระบบใช้สถาปัตยกรรม **RAM 100% In-Memory Data Passing** เพื่อให้การประมวลผลเสร็จสิ้นภายในเวลาเพียง < 0.5 วินาที:

1. **ส่วนงานแรก (Data Feed / DataAdapter - Part 1 🔒 Immutability):** ดึงข้อมูลราคา Real-time ผ่าน WebSocket/REST เก็บไว้ใน RAM (`RAMCacheStore` / `_completed_candles` 250 แท่ง) และบันทึกไฟล์ CSV ลงดิสก์แบบ Asynchronous Background พร้อมรักษาปฏิทินข่าว 1 ไฟล์ต่อวัน
2. **ส่วนงานที่สอง (Analysis / Orchestrator - Part 2 🔒 Immutability):** รับ `candles_dict` (M1, M5, M15) จาก RAM โดยตรงผ่าน `runner.py` ที่วินาที `:01.500` เข้าประมวลผลผ่าน:
   - `IndicatorStore` (SSOT Raw Indicators — ห้ามคำนวณซ้ำซ้อน 100%)
   - `AdvancedToolsManager` (10 เครื่องมือวิเคราะห์พฤติกรรมราคาและมิติทางจิตวิทยา)
   - `Tier 1 Parallel Engines` (Trend, Strength, Volatility, Structure, MTF)
   - `MarketStateClassifier` (จัดกลุ่มสภาวะตลาด 10 รูปแบบ)
   - `Tier 3-5 Supplementary Engines` (MarketStructure, Orderflow, Noise, Liquidity)
   - `Tier 6 Synthesis Engines` (ContextSynthesizer, ProbabilityEstimator, ExplainabilityEngine, SignalThrottle)
3. **ส่งออกผลลัพธ์ (Prompt Payload):** บันทึกไฟล์ข้อมูลมาตรฐาน **99 บรรทัด (.txt)** ไปยัง `data_base/orchestrator/<SYMBOL>/<PROMPT_ID>.txt` (จำกัด 30 ไฟล์ล่าสุดต่อคู่เงิน) เพื่อส่งต่อให้ AI ในส่วนที่ 3 นำไปตัดสินใจ

---

## ⚡ แผนผังกระบวนการทำงาน (1 รอบ = 60 วินาที)

```text
[ส่วนงานที่ 1: Data Feed & RAM Cache 🔒 Part 1 Immutability]
ดึงราคาจาก IQ Option WebSocket Stream / REST (250 แท่ง M1/M5/M15)
      ↓
อัปเดตและเก็บแท่งเทียนสมบูรณ์ใน RAM (_completed_candles 250 แท่ง)
      ↓
======================= สิ้นสุดส่วนงานที่ 1 =======================
      ↓
[ส่วนงานที่ 2: Data Evaluate / Orchestration (RAM 100% 🔒 Part 2 Immutability)]
runner.py ดึง candles_dict จาก RAM ส่งตรงให้ orchestrator.process_cycle() ที่วินาที :01.500
      ↓
1. คำนวณอินดิเคเตอร์พื้นฐาน (IndicatorStore) แบบรวมศูนย์ (SSOT ห้ามคำนวณซ้ำ)
      ↓
2. วิเคราะห์พฤติกรรมตลาด 7 มิติผ่าน 10 Advanced Tools
      ↓
3. รัน Tier 1 Core Engines ทั้ง 5 ชุดแบบ Parallel (ThreadPoolExecutor)
      ↓
4. จำแนก 10 สภาวะตลาด (MarketStateClassifier)
      ↓
5. รัน Tier 3-5 Supplementary Engines แบบ Parallel
      ↓
6. เชื่อมโยงข้อมูลจริงเข้าสู่ Tier 6 Context Synthesizer & Probability Estimator
      ↓
7. บันทึกไฟล์ Prompt Payload มาตรฐาน 99 บรรทัด (.txt) (Retention 30 ไฟล์ล่าสุด)
   → บันทึกที่: data_base/orchestrator/<SYMBOL>/<PROMPT_ID>.txt
   → หมวด decision_layer: กำหนดค่าเป็น "รอการวิเคราะห์จาก AI"
      ↓
======================= สิ้นสุดส่วนงานที่ 2 =======================
      ↓
[ส่วนงานที่ 3 & 4: AI/ML Analysis & Trade Execution 🛠️ พื้นที่พัฒนา]
ml_dispatcher / ai_dispatcher อ่านไฟล์ 99 บรรทัดผ่าน Single Gateway Read Authority
      ↓
AI/ML วิเคราะห์ Action (CALL/PUT), Expiry (1-5m), Confidence Score (0-100%)
      ↓
MoneyManager & 24 Execution Gates ตรวจสอบความปลอดภัย (คะแนน >= 60% อนุมัติยิง)
      ↓
BrokerExecutor ส่งคำสั่งซื้อขายจริงสู่ IQ Option
```

---

## 📄 โครงสร้างไฟล์ Prompt Payload มาตรฐาน 99 บรรทัด (Standard Format)

```yaml
ID: GBPUSDOTC0817145201
meta:
  timestamp: '2026-08-17T14:52:01.852518'
  symbol: GBPUSD-OTC
  session: LONDON_OPEN
  m1_open: 1.335315
  m1_age: 1852
  m1_quality: FRESH
  m5_open: 1.33532
  m5_age: 1852
  m5_quality: FRESH
market_context:
  mtf_state: RANGING
  mtf_description: Sideways Market
  m5_volatility_regime: NORMAL
  m5_news_impact: NONE
  m5_expected_volatility_%: 0.12
timeframes:
  m1:
    m1_last_candle: BULLISH
    m1_ema5: 1.33535
    m1_ema20: 1.33530
    m1_rsi: 52.4
    m1_stoch_k: 55.0
    m1_stoch_d: 50.0
    m1_macd: 0.00001
    m1_macd_signal: 0.000005
    ohlcv:
      m1_open: 1.335315
      m1_high: 1.335380
      m1_low: 1.335300
      m1_close: 1.335360
      m1_volume: 45
  m5:
    m5_bias: NEUTRAL
    m5_ema5: 1.33532
    m5_ema10: 1.33530
    m5_ema20: 1.33525
    m5_ema50: 1.33510
    m5_bb_upper: 1.33560
    m5_bb_lower: 1.33500
    m5_bb_width: 0.00060
    m5_rsi: 51.2
    m5_stoch_k: 48.0
    m5_stoch_d: 46.0
    m5_macd: 0.00002
    m5_macd_signal: 0.000015
    m5_adx: 18.5
    m5_atr: 0.00015
    m5_support: 1.33500
    m5_resistance: 1.33560
    m5_pivot: 1.33530
    ohlcv:
      m5_open: 1.33532
      m5_high: 1.33550
      m5_low: 1.33510
      m5_close: 1.33540
      m5_volume: 230
  m15:
    m15_bias: BULLISH
price_action:
  m5_pa_pattern: NONE
  m5_pa_last_candle_bias: BULLISH
  m5_pa_body_strength: STRONG
  m5_pa_wick_dominance: LOWER_WICK
  m5_pa_momentum_bias: NEUTRAL
  m5_pa_move_quality: CHAOTIC
  m5_pa_trap_alert: NONE
  m5_pa_sr_interaction: TESTING_PIVOT
  m5_pa_divergence_alert: BEARISH
  m5_pa_divergence_strength: 50
  m5_pa_market_behavior: NEUTRAL
  m5_pa_hesitation_score: 20
  m5_pa_path_efficiency: POOR
volume:
  m5_tick_volume: 1.0
  m5_volume_momentum: NO_VOLUME_DATA
  m5_volume_vs_average: 1.0
analysis:
  m5_trend_direction: NONE
  m5_trend_type: CHOPPY
  m5_trend_strength_score: 20
  mtf_alignment_%: 33
  m5_compression_quality_%: 40.47
  m5_exhaustion_risk_%: 30
  m5_bos_detected: false
  mtf_conflict_score: 0
  m5_trend_continuation_%: 82
  m5_transition_risk: MEDIUM
  m5_persistence_score: 63
decision_layer:
  dl_tradeable: true
  dl_stability_score: 33
  dl_quality_score: 33
  dl_risk_level: MEDIUM
  ai_confidence_score: รอการวิเคราะห์จาก AI
  ai_suggested_expiry_minutes: รอการวิเคราะห์จาก AI
  ai_suggested_action: รอการวิเคราะห์จาก AI
```

---

## 🛡️ กฎเหล็กควบคุมการประมวลผล (Computation Constraints)

1. **Part 1 & Part 2 Immutability Rule (Rule 18):** ห้ามแก้ไข ปรับแต่ง เพิ่ม หรือลบโค้ดใน `data_feed/` และ `data_evaluate/` เด็ดขาด 100%
2. **Strict Single Source of Truth & Zero Duplicate Calculations (Rule 10):** ไม่มีการคำนวณอินดิเคเตอร์ซ้ำซ้อน ทุกโมดูลต้องดึงค่าอ้างอิงจาก `IndicatorStore` และ `payload` แหล่งเดียวเท่านั้น
3. **Single Gateway Read Authority (Rule 8):** ใน Part 2 มีเพียง `orchestrator.py` ที่รับสิทธิ์อ่านข้อมูลดิบ/รับ `candles_dict` และใน Part 3 มีเพียง `ml_dispatcher.py` และ `ai_dispatcher.py` ที่อ่านไฟล์ 99 บรรทัด
4. **Standard 99-Line Explicit Schema & Retention Rule (Rule 20):** ไฟล์ Prompt Payload มีขนาดคงที่ 99 บรรทัดพอดีเป๊ะ พร้อม Prefix ชัดเจน และระบบ Retention 30 ไฟล์ล่าสุดต่อคู่เงิน
5. **Fail-Fast Policy:** หากข้อมูลไม่ครบถ้วน (น้อยกว่า 250 แท่ง) หรือคำนวณไม่ได้ ระบบจะหยุดทำงานทันที ไม่มีการหมกเม็ด Error
6. **Analysis Only:** ส่วนงานที่ 2 สิ้นสุดเมื่อสร้างไฟล์ Prompt 99 บรรทัดสำเร็จ โดยไม่มีการส่งคำสั่งเทรดเอง
