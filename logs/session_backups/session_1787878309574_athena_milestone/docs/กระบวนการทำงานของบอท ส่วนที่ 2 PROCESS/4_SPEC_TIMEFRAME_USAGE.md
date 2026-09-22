# SPEC: TIMEFRAME USAGE — M1, M5, M15

## หลักการใช้ TF
```
M15 → บอกทิศทางใหญ่ (Bias: BULLISH / BEARISH / NEUTRAL)
M5  → บอกสภาวะตลาดและสัญญาณหลัก (Market State & Analysis)
M1  → บอก Timing เข้าเทรด (Entry Confirmation)
```

---

## M15 — Higher Timeframe Bias

### หน้าที่
- กำหนดทิศทางหลักของตลาดเพื่อควบคุมทิศทางการเทรด
- ป้องกันการเข้าออเดอร์สวนทางเทรนใหญ่ M15
- ใช้เป็นตัวคัดกรองหลัก (Filter) เท่านั้น

### การคำนวณและประเมินผล
ใน `data_evaluate` ระบบจะดึงข้อมูลแท่งเทียน M15 ล่าสุดมาหาทิศทางหลัก:
* **BULLISH:** แนวโน้มขาขึ้น (ราคาปิด > EMA20 M15) ➡️ กรองให้รับเฉพาะสัญญาณ **CALL**
* **BEARISH:** แนวโน้มขาลง (ราคาปิด < EMA20 M15) ➡️ กรองให้รับเฉพาะสัญญาณ **PUT**
* **NEUTRAL:** สภาวะตลาดออกข้างไร้แนวโน้มชัดเจน ➡️ งดเว้นการเทรดหรือคัดกรองสัญญาณออกทันที

---

## M5 — Signal Timeframe

### หน้าที่
- กำหนดสภาวะตลาด (Market State) 10 รูปแบบผ่าน Classifier
- ประมวลผลดัชนีชี้วัดดิบและสถิติประยุกต์เชิงโครงสร้างทั้งหมด (EMA, BB, BBW, RSI, MACD, Stochastic, ATR, ADX, Slope, Volume Ratio, Box Squeeze, Pivot Points) ผ่าน `IndicatorStore` (SSOT)
- ตรวจจับความขัดแย้งของราคาและเครื่องมือชั้นสูงใน Advanced Tools

---

## M1 — Entry Timing Timeframe

### หน้าที่
- ยืนยันจังหวะเข้าเทรดและทำหน้าที่กรองสัญญาณหลอก (False Breakout / Trap)
- ห้ามนำข้อมูล M1 ไปใช้จำแนกสภาวะตลาดใหญ่

### เงื่อนไขการยืนยันเข้าเทรด (Entry Confirmation Logic)
เมื่อเกิดสัญญาณจาก M5 ระบบจะนำข้อมูล M1 มาตรวจสอบความสอดคล้อง:
```
สัญญาณ M5 = CALL และ:
  M1 RSI14 < 60        → ตลาดยังไม่ถึงโซนซื้อมากเกินไป (Overbought)
  M1 MACD > MACD_Signal → โมเมนตัมฝั่งขึ้นยังสอดคล้อง
  M1 Last_Candle = BULLISH → แท่งล่าสุดของ M1 ยืนยันขาขึ้น
  M15 Bias = BULLISH   → ทิศทางใหญ่ตรงกัน
→ ยืนยันเข้าเทรด (ENTRY CONFIRMED)

สัญญาณ M5 = PUT และ:
  M1 RSI14 > 40        → ตลาดยังไม่ถึงโซนขายมากเกินไป (Oversold)
  M1 MACD < MACD_Signal → โมเมนตัมฝั่งลงยังสอดคล้อง
  M1 Last_Candle = BEARISH → แท่งล่าสุดของ M1 ยืนยันขาลง
  M15 Bias = BEARISH   → ทิศทางใหญ่ตรงกัน
→ ยืนยันเข้าเทรด (ENTRY CONFIRMED)

หากตรวจสอบแล้วเงื่อนไขไม่ตรงกันทั้งหมด ➡️ ยกเลิกคำสั่ง (NO_SIGNAL)
```

---

## โครงสร้างข้อมูลรายกรอบเวลา (IndicatorStore Layout)

```python
IndicatorStore['EURUSD'] = {
    'raw': {
        'm15': {
            'bias': 'BULLISH' | 'BEARISH' | 'NEUTRAL'
        },
        'm5': {
            'ema5': float, 'ema10': float, 'ema20': float, 'ema50': float, 'ema100': float, 'ema200': float,
            'bb_upper': float, 'bb_lower': float, 'bb_width': float, 'bbw_sma_100': float,
            'rsi7': float, 'rsi14': float,
            'macd': float, 'macd_signal': float, 'macd_hist': float,
            'stoch_k': float, 'stoch_d': float,
            'atr14': float, 'atr_percentile': float, 'atr_zscore': float, 'atr_recent_avg': float, 'atr_past_avg': float,
            'adx': float, 'di_plus': float, 'di_minus': float, 'dx': float,
            'roc': float,
            'volume': float, 'volume_ma20': float, 'volume_ratio': float, 'volume_spike': bool,
            'slope_10': float, 'slope_20': float, 'slope_50': float,
            'pivot': float, 'r1': float, 'r2': float, 's1': float, 's2': float,
            'box_duration': int, 'box_tightness': float,
            'bias': str
        },
        'm1': {
            'ema5': float, 'ema10': float, 'ema20': float, 'ema50': float,
            'rsi7': float, 'rsi14': float,
            'macd': float, 'macd_signal': float,
            'stoch_k': float, 'stoch_d': float,
            'bb_upper': float, 'bb_lower': float,
            'atr14': float,
            'pivot': float, 'r1': float, 's1': float,
            'volume': float, 'volume_ratio': float,
            'open': float, 'high': float, 'low': float, 'close': float
        },
        'meta': {
            'close': float, 'high': float, 'low': float, 'open': float,
            'session': str,
            'm1_open': float, 'm1_age': int, 'm1_quality': str,
            'm5_open': float, 'm5_age': int, 'm5_quality': str
        }
    }
}
```

---

## กฎเหล็กควบคุมกรอบเวลา (Constraints)
1. **Part 1 & Part 2 Immutability Rule (Rule 18):** ห้ามแก้ไข ปรับแต่ง เพิ่ม หรือลบโค้ดใน `data_feed/` และ `data_evaluate/` เด็ดขาด 100%
2. **Strict Single Source of Truth (Rule 10):** ข้อมูลทุก Timeframe ถูกคำนวณผ่าน `IndicatorStore` แหล่งเดียว ห้ามโมดูลย่อยคำนวณซ้ำ
3. **ทิศทาง Bias สองฝั่งเด็ดขาด:** การรับส่งข้อมูลคำสั่งเทรดจะต้องสอดคล้องกับ M15 Bias เสมอ ห้ามทำการเข้าส่งคำสั่งเทรด CALL เมื่อ Bias เป็น BEARISH และห้ามเข้าคำสั่งเทรด PUT เมื่อ Bias เป็น BULLISH
4. **การป้องกันระดับเวลา M1:** ห้ามนำระดับแท่งเทียน M1 ไปประเมินสภาวะตลาดรวม (Market State) หรือใช้งานเป็นสัญญาณตั้งต้นหลักอย่างเด็ดขาด
5. **การตรวจสอบความสดใหม่ของระดับใหญ่:** ข้อมูล M15 ที่ป้อนจะต้องมีค่าอัปเดตต่อเนื่อง หากตรวจพบอายุข้อมูลล่าช้าเกิน 40 นาทีระบบจะตัดการส่งคำสั่งทันทีเพื่อป้องกันความเสี่ยง (Fail-Fast)
