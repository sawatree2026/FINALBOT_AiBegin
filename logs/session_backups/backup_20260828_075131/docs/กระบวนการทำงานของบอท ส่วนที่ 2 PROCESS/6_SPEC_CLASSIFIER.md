# SPEC: MARKET STATE CLASSIFIER

## ภาพรวม
รับ output จาก Tier 1 ทั้ง 5 engines (trend, strength, volatility, structure, mtf) → จำแนกตลาดเป็น 10 ประเภทหลักโดยใช้ระบบถ่วงน้ำหนักคะแนน (Weighted Scoring System) เพื่อให้เหมาะกับการเทรด Binary Options แบบ 5 นาที

**File:** `data_evaluate/orchestration/market_classifier/market_state_classifier.py` (🔒 Part 2 Immutability)  
**Depends on:** trend, strength, volatility, structure, mtf (ทุกตัวผ่าน SSOT `IndicatorStore`)

---

## Input Schema
ส่งข้อมูลผ่าน kwargs และ payload โดยตรง:
```python
payload = {
    'm5': dict,                 # ข้อมูล indicator พื้นฐาน M5 (SSOT จาก IndicatorStore)
    'price_action': dict,       # ข้อมูล Price Action
    'ohlcv': dict               # ข้อมูลราคา OHLCV ล่าสุด
}

kwargs = {
    'trend_data': dict,         # จาก trend_engine
    'strength_data': dict,      # จาก strength_engine
    'volatility_data': dict,    # จาก volatility_engine
    'structure_data': dict,     # จาก structure_engine
    'mtf_data': dict,           # จาก mtf_engine
    'symbol': str               # ชื่อคู่เงิน (เช่น EURUSD, EURGBP-OTC)
}
```

---

## Output Schema
```python
{
    'state': str,               # 1 ใน 10 states ด้านล่าง
    'confidence': int,          # ระดับความเชื่อมั่น 0-100
    'quality_score': int,       # คะแนนคุณภาพของตลาด 0-100
    'tradeable': bool,          # ผ่านเกณฑ์ข้อมูลครบถ้วนพื้นฐานหรือไม่
    'stability': int,           # คะแนนความเสถียรของสภาวะตลาด 0-100
    'description': str,         # คำอธิบายภาษาอังกฤษเชิงแนะนำกลยุทธ์
    'breakout_prob': float,     # ความน่าจะเป็นในการเกิด Breakout
    'reversal_prob': float,     # ความน่าจะเป็นในการเกิด Reversal
    'risk_level': str,          # ระดับความเสี่ยง ('LOW' | 'MEDIUM' | 'HIGH')
    'suggested_action': str,    # ค่าคงที่ 'รอการวิเคราะห์จาก AI' — Part 2 ไม่ตัดสินใจ action เอง
    'suggested_expiry': int,    # ค่าคงที่เริ่มต้น 5 นาที — Part 2 ไม่ตัดสินใจ expiry เอง
    'metrics': dict             # ค่าน้ำหนักทางคณิตศาสตร์ทั้งหมดที่ใช้ประมวลผล
}
```

---

## 10 Market States — การคำนวณคะแนนดิบ (Weighted Scores)

ระบบจะคำนวณคะแนนดิบ (Raw Score) ของทั้ง 10 สถานะขึ้นมาพร้อมกัน จากนั้นปรับจูนด้วยตัวแปรเสริม (Boosts & Penalties) และเลือกสถานะที่ได้คะแนนสูงสุด

### 1. TRENDING_STRONG
คะแนนดิบเริ่มต้นจาก ADX (35%), Trend Strength (30%), MTF Alignment (20%) และ 1 - Noise Level (15%)
```
เงื่อนไข & การปรับแต่ง:
- เพิ่มคะแนน (+10): หากทิศทางแนวโน้มไม่ใช่ 'NONE'
- เพิ่มคะแนน (+10): หากโครงสร้างตลาดเป็น 'TRENDING' หรือ 'BREAKOUT'
- เพิ่มคะแนน (+5): หากพบการเกิด BOS (Breakout of Structure)
- เพิ่มคะแนน (+10): หาก MTF Alignment >= 70%
- หักคะแนน (-20): หากระดับ Noise > 0.6
- หักคะแนน (-20): หากระดับ Exhaustion Risk > 70%
- หักคะแนน (-15): หากทิศทางกรอบเวลาหลักกับย่อยขัดแย้งกัน (htf_ltf_conflict)
```

### 2. TRENDING_WEAK
คะแนนดิบเริ่มต้นจาก ADX (30%), Trend Strength (25%), 1 - Noise Level (25%) และ MTF Alignment (20%)
```
เงื่อนไข & การปรับแต่ง:
- เพิ่มคะแนน (+10): หากทิศทางแนวโน้มไม่ใช่ 'NONE'
- เพิ่มคะแนน (+5): หากโครงสร้างตลาดเป็น 'TRENDING' หรือ 'CORRECTIVE'
- หักคะแนน (-25): หากระดับ Exhaustion Risk > 70%
- หักคะแนน (-10): หากทิศทางกรอบเวลาหลักกับย่อยขัดแย้งกัน (htf_ltf_conflict)
- หักคะแนน (-15): หากระดับ Noise > 0.5
```

### 3. SIDEWAY_RANGE
คะแนนดิบเริ่มต้นจาก 1 - ADX (35%), โครงสร้างเป็น 'RANGING' (25%), 1 - Noise Level (20%) และ Volatility Regime ในช่วง Low หรือ Normal (20%)
```
เงื่อนไข & การปรับแต่ง:
- เพิ่มคะแนน (+15): หาก ADX < 18
- เพิ่มคะแนน (+10): หากระดับ Noise < 0.3
- หักคะแนน (-20): หากพบ BOS
- หักคะแนน (-15): หาก breakout_probability > 50%
```

### 4. BREAKOUT_EMERGING
คะแนนดิบเริ่มต้นจาก ระดับบีบตัวของ Bollinger Bands (30%), Volatility Percentile ต่ำ (20%), Breakout Probability (25%) และ BOS Detected (15%)
```
เงื่อนไข & การปรับแต่ง:
- ปัจจัยปริมาณซื้อขาย (Volume Factor): บวกคะแนนตามสัดส่วน Volume Ratio สูงสุดไม่เกิน +10 คะแนน (สำหรับคู่เงิน OTC จะได้เต็ม +10 ทันที)
- เพิ่มคะแนน (+15): หาก bbw < 0.04 (บีบอัดตัวรุนแรง)
- เพิ่มคะแนน (+10): หาก ATR Percentile < 30
- เพิ่มคะแนน (+10): หากไม่ใช่ OTC และ Volume Ratio > 1.5
- หักคะแนน (-15): หากระดับ Noise > 0.5
- หักคะแนน (-20): หากทิศทางกรอบเวลาขัดแย้งกัน
```

### 5. REVERSAL_FORMING
คะแนนดิบเริ่มต้นจาก Divergence Strength (35%), Reversal Probability (30%), Exhaustion Risk (20%) และ Overbought/Oversold Level (15%)

### 6. VOLATILE_EXPANDING
คะแนนดิบเริ่มต้นจาก Volatility Percentile สูง (40%), ATR Z-score (30%) และ Spike Detected (30%)

### 7. COMPRESSION_SQUEEZE
คะแนนดิบเริ่มต้นจาก BBW บีบตัวต่ำสุด (40%), Box Tightness (30%) และ Volatility Score ต่ำ (30%)

### 8. EXHAUSTION_CLIMAX
คะแนนดิบเริ่มต้นจาก Exhaustion Risk (40%), Volume Spike (30%) และ Overbought/Oversold Extreme (30%)

### 9. CHOPPY_UNCERTAIN
คะแนนดิบเริ่มต้นจาก Noise Level สูง (40%), MTF Conflict (30%) และ Trend Direction เป็น 'NONE' (30%)

### 10. LIQUIDITY_VOID
คะแนนดิบเริ่มต้นจาก Volume ต่ำผิดปกติ (40%), Spread กว้าง (30%) และ ADX ต่ำลงต่อเนื่อง (30%) (สำหรับ OTC ค่านี้ถูกเซ็ตเป็น 0 เสมอ)

---

## Classification Logic & State Smoothing
เพื่อให้ระบบไม่เปลี่ยนสถานะไปมารวดเร็วเกินไป (Rapid Flipping) จนส่งผลต่อระบบส่งสัญญาณเทรด ระบบใช้หลักการดังนี้:

1. **State history:** ระบบจะเก็บประวัติสถานะย้อนหลังไว้สูงสุด 5 แท่ง (`_state_history`)
2. **Buffer Margin สำหรับ Liquidity Void:** หากระบบตัดสินใจเลือก `LIQUIDITY_VOID` แต่แท่งก่อนหน้าไม่ใช่ จะต้องมีคะแนนนำสถานะอันดับสองมากกว่าหรือเท่ากับ 15 คะแนนเท่านั้นเพื่อบังคับเปลี่ยน หากไม่ถึงจะยกเลิกและปรับไปใช้สถานะอันดับสองทดแทน
3. **State Smoothing logic:** หากคะแนนความเชื่อมั่น (Confidence) ต่ำกว่า 60 และสถานะใหม่ขัดแย้งกับประวัติส่วนใหญ่ใน 3 แท่งก่อนหน้า ระบบจะดึงสถานะเดิมมาคงสภาพไว้ชั่วคราวเพื่อรอการยืนยันในแท่งถัดไป

---

## Composite Score & Metrics Scoring
การคำนวณหาคะแนนคุณภาพของตลาด (`quality_score` 0-100) คำนวณแบบถ่วงน้ำหนักจากคะแนนที่ประมวลผลได้:
- **Trend Score (35%)**: `(trend_strength × 0.3) + (trend_confidence × 0.7)`
- **Strength Score (30%)**: `(adx / 100 × 50) + (strength_score × 0.5)`
- **Volatility Score (20%)**: `volatility_score`
- **Structure Score (15%)**: `structure_score`

ค่ารวมทั้งหมดจะถูกนำไปปรับค่าความสั่นไหวกับค่า MTF Multiplier (`alignment_score` สูงช่วยเพิ่มความคุ้มค่า และหักคะแนนหากตลาดมีความขัดแย้งในกรอบเวลารุ่นพี่)

---

## Tradeable Flag — เกณฑ์ข้อมูลครบถ้วนเท่านั้น (ไม่ Block ตาม State)

**พฤติกรรมจริงของ `_is_tradeable()`:** ฟิลด์ `tradeable` **ไม่ใช่** การประเมินความเสี่ยงหรือ hard block ตาม market state — เป็นแค่การเช็คว่าข้อมูลพื้นฐานที่จำเป็นต่อการวิเคราะห์ครบถ้วนหรือไม่เท่านั้น:

```python
def _is_tradeable(self, state, quality, m) -> bool:
    # คืนค่า False ก็ต่อเมื่อ metrics dict ว่างเปล่า หรือขาดคีย์ที่จำเป็น
    # (trend_direction, adx, rsi, noise_level)
    # นอกจากนั้นคืนค่า True เสมอ ไม่ว่า state จะเป็นอะไร
```

**หลักการออกแบบ (ตั้งใจ ไม่ใช่บั๊ก):** การตัดสินใจว่าจะเทรดหรือไม่เทรดจริง **ไม่ใช่หน้าที่ของ Part 2** — Part 2 มีหน้าที่แค่คำนวณและส่งข้อมูล `state`, `quality_score`, `risk_level`, `stability` ให้ครบถ้วนแม่นยำที่สุดเท่านั้น ส่วนการตัดสินใจเทรดจริง ถูกส่งต่อให้ **AI และ Gate Controller (Part 3 & 4)** เป็นผู้ตัดสินใจเองทั้งหมด

---

## 🛡️ กฎข้อบังคับ (Strict Rules)
1. **Part 1 & Part 2 Immutability Rule (Rule 18):** ซอร์สโค้ดใน `data_feed/` และ `data_evaluate/` ห้ามแก้ไข ปรับแต่ง เพิ่ม หรือลบโดยเด็ดขาด 100%
2. **Strict Single Source of Truth & Zero Duplicate Calculations (Rule 10):** ทุกการคำนวณใช้ข้อมูลจาก `IndicatorStore` และ `payload` โดยตรง ห้ามคำนวณใหม่เองเด็ดขาด
