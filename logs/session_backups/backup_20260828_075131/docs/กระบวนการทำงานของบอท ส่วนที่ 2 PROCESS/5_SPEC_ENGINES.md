# SPEC: TIER 1 ENGINES (Input → Output)

## ภาพรวม
5 engines ทำงานประมวลผลพร้อมกันในรูปแบบขนาน (Parallel Processing) จากข้อมูลที่ผ่านการประมวลผลจาก `IndicatorStore` (SSOT) และแท่งเทียน ผลลัพธ์สุดท้ายจะถูกส่งต่อให้ Market State Classifier เพื่อประเมินทิศทางและคุณภาพรวมของตลาด

---

## 1. trend_engine.py
**Input:** Candles (M5)  
**Indicators:** EMA20, EMA50, EMA100, EMA200, Linear Regression Slope (จาก `IndicatorStore`)

**Output:**
```python
{
    'direction': 'UP' | 'DOWN' | 'NONE',
    'strength': int,             # คะแนนกำลังของแนวโน้ม 0-100
    'slope': float,              # Linear Regression Slope
    'momentum': float,           # โมเมนตัมปัจจุบัน
    'type': 'IMPULSIVE' | 'CORRECTIVE' | 'CHOPPY',
    'confidence': int,           # 0-100
    'reversal_risk': int,        # 0-100
    'sustain_probability': int   # 0-100
}
```

**กฎและตรรกะสำคัญ:**
* **การคำนวณแยกตามมูลค่าสินทรัพย์:** เพื่อรองรับความผันผวนที่ต่างกัน โค้ดมีการแยกเกณฑ์สำหรับ Forex (ราคา < 5.0 เช่น EURUSD ~ 1.08) ออกจาก Crypto/Indices (ราคา >= 5.0) ทำให้มีค่าเกณฑ์สำหรับบวกคะแนนความชัน (Slope) และโมเมนตัมที่เหมาะสมต่อประเภทสินทรัพย์อย่างแม่นยำ
* **UP:** ราคา > EMA20 > EMA50 > EMA100
* **DOWN:** ราคา < EMA20 < EMA50 < EMA100
* **NONE:** ราคาหรือเส้นค่าเฉลี่ย EMA พันกันสับสนไร้แนวโน้ม

---

## 2. strength_engine.py
**Input:** Candles (M5)  
**Indicators:** ADX(14), DI+(14), DI-(14), RSI(14), MACD(12,26,9), ROC(10) (จาก `IndicatorStore`)

**Output:**
```python
{
    'adx': float,                # 0-100
    'di_plus': float,            # 0-100
    'di_minus': float,           # 0-100
    'rsi': float,                # 0-100
    'macd': float,               # ค่า MACD หลัก
    'momentum_level': 'WEAK' | 'NORMAL' | 'STRONG' | 'EXTREME',
    'roc': float,                # Rate of Change
    'divergence': 'BULLISH' | 'BEARISH' | 'NONE',
    'strength_score': int,       # คะแนนความแข็งแกร่งรวม 0-100
    'exhaustion_risk': int,      # ความเสี่ยงที่เทรนด์จะหมดพลัง 0-100
    'confidence': int            # 0-100 (คำนวณจาก strength_score + 10)
}
```

**กฎและตรรกะสำคัญ:**
* **Momentum Level:** จำแนกจากค่า ADX:
  - ADX < 20 ➡️ WEAK (แนวโน้มอ่อนแอ)
  - ADX 20-35 ➡️ NORMAL
  - ADX 35-50 ➡️ STRONG
  - ADX > 50 ➡️ EXTREME (แนวโน้มรุนแรงมาก)

---

## 3. volatility_engine.py
**Input:** Candles (M5)  
**Indicators:** ATR(14), Bollinger Bands(20,2), StdDev(20), Historical ATR Percentile (จาก `IndicatorStore`)

**Output:**
```python
{
    'atr': float,
    'atr_percentile': float,     # ATR เทียบกับประวัติย้อนหลัง 100 แท่ง
    'bbw': float,                # ความกว้างเส้น Bollinger Band Width
    'stddev': float,             # ค่าเบี่ยงเบนมาตรฐาน (bbw / 4.0)
    'regime': 'LOW' | 'NORMAL' | 'HIGH' | 'EXTREME',
    'volatility_score': int,     # 0-100
    'expansion_probability': int,# ความน่าจะเป็นในการขยายตัว 0-100
    'contraction_probability': int, # ความน่าจะเป็นในการหดตัว 0-100
    'volatility_zscore': float,  # Z-score ของความผันผวน
    'spike_detected': bool,      # ตรวจจับแรงกระชากของราคาผิดปกติ
    'confidence': int,           # ระดับความมั่นใจ 0-100
    'bbw_compression_ratio': float, # อัตราส่วนบีบอัดตัว BBW ในปัจจุบันเทียบกับอดีต
    'compression_quality': float # คะแนนคุณภาพความตึงของการบีบอัดราคา 0-100
}
```

**กฎและตรรกะสำคัญ:**
* **Regime Classification:**
  - LOW ➡️ atr_percentile < 25
  - NORMAL ➡️ atr_percentile 25-75
  - HIGH ➡️ atr_percentile 75-90
  - EXTREME ➡️ atr_percentile > 90
* **Spike Detection:** ตรวจจับเมื่อค่า Z-score ของ ATR เบี่ยงเบนออกไปมากกว่า 2.0 เท่า

---

## 4. structure_engine.py
**Input:** Candles (M5)  
**Indicators:** Swing High/Low, Pivot Points, S1/R1, Box Duration, Box Tightness (จาก `IndicatorStore`)

**Output:**
```python
{
    'support_levels': [float, ...],      # ระดับแนวรับสูงสุด 3 ค่า
    'resistance_levels': [float, ...],    # ระดับแนวต้านสูงสุด 3 ค่า
    'structure_type': 'TRENDING' | 'RANGING' | 'BREAKOUT',
    'structure_score': int,              # 0-100
    'bos_detected': bool,                # การทำลายโครงสร้างราคา
    'bos_type': 'BULLISH' | 'BEARISH' | 'NONE',
    'key_zones': dict,                   # โซนแนวรับ/ต้านและกึ่งกลางที่สำคัญ
    'zone_proximity': str,               # ความใกล้ของราคาต่อแนวรับต้าน
    'breakout_probability': int,         # ความน่าจะเป็นในการเกิด Breakout (60% หากพบ BOS, อื่นๆ 30%)
    'reversal_probability': int,         # ความน่าจะเป็นในการเกิด Reversal (40% หากพบ BOS, อื่นๆ 50%)
    'confidence': int,                   # ระดับความเชื่อมั่น 0-100
    'box_duration': int,                 # ระยะเวลาที่ราคาวิ่งอยู่ในกรอบบีบอัดตัว
    'box_tightness': float               # ความแคบแน่นของกรอบบีบอัดราคา
}
```

---

## 5. mtf_engine.py
**Input:** Candles M1, M5, M15  
**Indicators:** ประเมินทิศทางและกำลังแนวโน้มแยกตามแท่งเทียนแต่ละระดับเวลา

**Output:**
```python
{
    'directions_by_tf': dict,            # ทิศทางจำแนกตามกรอบเวลา {'M1': 'UP', 'M5': 'DOWN', ...}
    'alignment_score': int,              # คะแนนการมองเห็นในทิศทางเดียวกันของแต่ละกรอบเวลา 0-100
    'dominant_direction': 'UP' | 'DOWN' | 'NONE', # ทิศทางเด่นที่เห็นพ้องต้องกันส่วนใหญ่
    'htf_direction': str,                # ทิศทางของกรอบเวลารุ่นพี่ (Higher Timeframe)
    'ltf_direction': str,                # ทิศทางของกรอบเวลารุ่นน้อง (Lower Timeframe)
    'htf_ltf_conflict': bool,            # ความขัดแย้งของทิศทางระหว่างรุ่นพี่กับรุ่นน้อง
    'timeframes_analyzed': list,         # รายการกรอบเวลาที่มีข้อมูลคำนวณจริง
    'confidence_from_mtf': int,          # ระดับความมั่นใจเชิงกรอบเวลา 0-100
    'confidence': int                    # 0-100
}
```

---

## กฎการจัดการปริมาณการซื้อขาย (Volume Management Rules: Normal vs OTC)

การพิจารณาค่า **Volume** และ **Volume Ratio** มีความแตกต่างกันอย่างเด็ดขาดตามประเภทตลาดเพื่อความแม่นยำของ Classifier:

### 1. ตลาดปกติ (Normal Pairs)
* **การใช้ปริมาณซื้อขายจริง:** การคำนวณหาน้ำหนักความเสถียรสำหรับการยืนยันการทะลุกรอบ (`BREAKOUT_EMERGING`) หรือการสะสมกำลัง (`ACCUMULATION` / `DISTRIBUTION`) จะอ้างอิงและจำกัดน้ำหนักตามการเพิ่มของปริมาณการซื้อขายจริงในแท่งเทียนนั้นๆ (เช่น `min(1.0, volume_ratio / 1.5) * 10`)
* **Liquidity Void Check:** คำนวณความเบาบางและเตือนการเกิดช่องว่างของสภาพคล่องจากการลดลงของ Volume จริงและการลดลงของ ADX คู่ขนานกัน หากพบจะคำนวณคะแนนเป็นบวกและบังคับจำแนกสภาวะเลี่ยงการส่งคำสั่งทันที

### 2. ตลาด OTC (Over-the-Counter Pairs)
* **การตัดความน่าเชื่อถือของปริมาณซื้อขาย:** ตลาด OTC ไม่มีปริมาณการซื้อขายที่แท้จริงจากศูนย์กลางการแลกเปลี่ยน ดังนั้นใน `orchestrator.py` ปริมาณการซื้อขายของแท่งเทียนจะถูกจัดสรรแบบคงค่ามาตรฐานที่ `1.0` และ `volume_ratio = 1.0`
* **การชดเชยคะแนนสภาวะตลาด (Full Volume Credit):** ใน `market_state_classifier.py` หากระบุเป็นคู่ OTC ระบบจะข้ามการตรวจสอบอัตราส่วนการเพิ่มปริมาณซื้อขายดิบ แต่จะจัดสรรคะแนนให้เต็มตามเงื่อนไขสภาวะตลาดนั้นโดยตรง (Full Volume Credit) เพื่อให้ไม่สูญเสียความคุ้มค่าของการประเมินแนวโน้มอื่นๆ
* **Liquidity Void Zeroed:** สำหรับ OTC ค่าคะแนนดิบของสถานะ `LIQUIDITY_VOID` จะถูกบังคับเป็น `0` เสมอ เพื่อหลีกเลี่ยงการตัดสิทธิ์การเทรดที่อาจเกิดจากความไม่สมบูรณ์ของค่าปริมาณซื้อขายจำลอง

---

## 🛡️ กฎข้อบังคับการประมวลผล (Engine Execution Rules)
1. **Part 1 & Part 2 Immutability Rule (Rule 18):** ซอร์สโค้ดใน `data_feed/` และ `data_evaluate/` ห้ามแก้ไขเด็ดขาด 100%
2. **Strict Single Source of Truth & Zero Duplicate Calculations (Rule 10):** ทุก Engine ต้องดึงค่าอินดิเคเตอร์จาก `IndicatorStore` แหล่งเดียวเท่านั้น ห้ามเขียนสูตรคำนวณ EMA, RSI, BB, MACD, ATR ซ้ำซ้อนเด็ดขาด
