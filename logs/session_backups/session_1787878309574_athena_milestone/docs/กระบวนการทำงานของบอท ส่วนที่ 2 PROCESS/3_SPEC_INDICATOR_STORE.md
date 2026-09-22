# SPEC: INDICATOR STORE — ห้องคำนวณและเก็บ Indicator (Single Source of Truth)

## หลักการประมวลผล (SSOT Principle & Zero Duplicate Calculations)
เพื่อประสิทธิภาพสูงสุดและหลีกเลี่ยงความซ้ำซ้อนในสถาปัตยกรรม บอทใช้หลักการคำนวณแบบรวมศูนย์ (**Single Source of Truth - SSOT**):
```
OHLCV Data ➡️ คำนวณครั้งเดียว (IndicatorStore) ➡️ ส่งต่อผลลัพธ์ผ่าน Payload ➡️ ทุกโมดูลใช้อ้างอิงร่วมกัน 100%
```
* **คำนวณรอบเดียว (60 วินาที):** คำนวณค่าดัชนีดิบ (Raw Indicators) ทั้งหมดจากข้อมูลแท่งเทียนที่ผ่านการคลีนแล้วเพียงครั้งเดียวในแต่ละรอบของการทำงาน
* **ห้ามคำนวณซ้ำซ้อนเด็ดขาด (Rule 10):** ห้ามโมดูลย่อยใดๆ (Advanced Tools, Engines, Classifier, AI Dispatcher) เขียนโค้ดคำนวณอินดิเคเตอร์หรือค่าสถิติซ้ำซ้อน ทุกโมดูลต้องดึงค่าอ้างอิงจาก `IndicatorStore` และ `payload` เท่านั้น

---

## สถาปัตยกรรมระบบเก็บข้อมูล (File Layout)
ระบบจะทำการแยกการวิเคราะห์คำนวณออกเป็น 3 ไฟล์หลักเพื่อความเป็นระเบียบและง่ายต่อการดูแลรักษา:

1. **`basic_indicators.py`**  
   ทำหน้าที่คิดคำนวณอินดิเคเตอร์ทางเทคนิคทั่วไปตามมาตรฐานสากล (EMA, Bollinger Bands, RSI, MACD, Stochastic, ATR, ADX) โดยใช้ระบบ Pandas Vectorization
2. **`structural_indicators.py`**  
   ทำหน้าที่ประมวลผลดัชนีสถิติเชิงโครงสร้างที่ออกแบบมาสำหรับบอทนี้โดยเฉพาะ (Linear Regression Slope, Volume Ratio, Box Squeeze, Pivot Points, Rate of Change)
3. **`indicator_store.py`**  
   ทำหน้าที่เป็น Orchestrator สำหรับ Layer 1 ในการดึงเอาข้อมูลจากทั้งสองไฟล์ย่อยข้างต้นมารวมกัน จัดระบบล็อก (Thread Lock) เพื่อความปลอดภัย และเป็น Instance Singleton ให้โมดูลอื่นดึงข้อมูลไปใช้

---

## ดัชนีทางเทคนิคที่คำนวณเก็บไว้ (Layer 1: Raw Indicators)

### 1. กรอบเวลา M5 (TF M5 Indicators)
| Indicator | แหล่งคำนวณ | รายการดัชนีและค่าการตั้งค่าหลัก |
|-----------|------------|---------------------------------|
| **EMA** | `BasicIndicators` | `ema5`, `ema10`, `ema20`, `ema50`, `ema100`, `ema200` |
| **Trend Bias** | `BasicIndicators` | `bias` ('BULLISH' เมื่อ Close > EMA20, 'BEARISH' เมื่อ Close <= EMA20) |
| **Bollinger Bands** | `BasicIndicators` | `bb_upper`, `bb_lower`, `bb_width`, `bbw_sma_100` (ค่า BB: 20, 2) |
| **RSI** | `BasicIndicators` | `rsi7`, `rsi14` (RSI ดั้งเดิมแบบ Wilder's Smoothing) |
| **MACD** | `BasicIndicators` | `macd`, `macd_signal`, `macd_hist` (ค่ามาตรฐาน: 12, 26, 9) |
| **Stochastic** | `BasicIndicators` | `stoch_k`, `stoch_d` (ค่ามาตรฐาน: 14, 3, 3) |
| **ATR** | `BasicIndicators` | `atr14`, `atr_percentile`, `atr_zscore`, `atr_recent_avg`, `atr_past_avg` |
| **ADX / DMI** | `BasicIndicators` | `adx`, `di_plus`, `di_minus`, `dx` (ADX 14) |
| **Rate of Change** | `StructuralIndicators` | `roc` (Rate of Change เทียบย้อนหลัง 10 แท่งเทียน) |
| **Volume Analysis** | `StructuralIndicators` | `volume`, `volume_ma20`, `volume_ratio` (ลิมิตสูงสุด 10.0), `volume_spike` (> 2.0) |
| **Slope Analysis** | `StructuralIndicators` | `slope_10`, `slope_20`, `slope_50` (คำนวณด้วย Linear Regression) |
| **Pivot Points** | `StructuralIndicators` | `pivot`, `r1`, `r2`, `s1`, `s2` <br>• **วิธีคำนวณ:** ใช้แท่งเทียน M5 ที่ปิดสมบูรณ์เท่านั้น (`iloc[-1]`) จาก `drop_forming()` |
| **Box Metrics** | `StructuralIndicators` | `box_duration` (จำนวนแท่งที่ไซด์เวย์), `box_tightness` (ความแคบเทียบกับ ATR) |

### 2. กรอบเวลา M1 (TF M1 Indicators)
| Indicator | แหล่งคำนวณ | รายการดัชนีและค่าการตั้งค่าหลัก |
|-----------|------------|---------------------------------|
| **EMA** | `BasicIndicators` | `ema5`, `ema10`, `ema20`, `ema50` |
| **RSI** | `BasicIndicators` | `rsi7`, `rsi14` |
| **MACD** | `BasicIndicators` | `macd`, `macd_signal` |
| **Stochastic** | `BasicIndicators` | `stoch_k`, `stoch_d` |
| **ATR** | `BasicIndicators` | `atr14` |
| **Bollinger Bands** | `BasicIndicators` | `bb_upper`, `bb_lower` |
| **Pivot Points** | `StructuralIndicators` | `pivot`, `r1`, `s1` — ใช้แท่งล่าสุด (`iloc[-1]`) เสมอ |
| **Volume Analysis** | `StructuralIndicators` | `volume`, `volume_ratio` |

### 3. กรอบเวลา M15 (TF M15 Indicators)
* **Trend Bias (`bias`):** 'BULLISH' หรือ 'BEARISH' ประเมินจากความสัมพันธ์ระหว่างราคาปิดกับเส้น EMA20 ของแท่ง M15
* **Fail-Fast Safety Check:** หากแท่ง M15 ล่าสุดมีอายุข้อมูลเกิน 40 นาที (`m15_age_ms > 2400000`) ระบบจะเกิด Error หยุดการทำงานทันทีเพื่อป้องกันสัญญาณเก่าล้าสมัยทำงานผิดพลาด

---

## โครงสร้างข้อมูล Metadata ความสมบูรณ์ของแท่งเทียน (Forming & Age Data)
ในแต่ละรอบการสร้าง Payload จะเก็บความสมบูรณ์ของข้อมูลไว้ในส่วนหัว (`meta`) เสมอ:
* **Session Classification:** จำแนกตามเวลาสากล UTC:
  - `00:00 - 07:00 UTC` ➡️ **SYDNEY/TOKYO**
  - `07:00 - 12:00 UTC` ➡️ **LONDON_OPEN**
  - `12:00 - 16:00 UTC` ➡️ **NY/LONDON_OVERLAP**
  - `16:00 - 21:00 UTC` ➡️ **NY_AFTERNOON**
  - `21:00 - 24:00 UTC` ➡️ **SYDNEY_OPEN**
* **Candle Age & Quality:**
  - `m1_open` / `m5_open`: ราคาเปิดของแท่งเทียนกำลังก่อตัว
  - `m1_age` / `m5_age`: เวลาอายุแท่งเทียนในหน่วย **มิลลิวินาที (Integer ms)**
  - `m1_quality` / `m5_quality`: สถานะความสดใหม่ของข้อมูล (`FRESH` หรือ `STALE` ตามกฎ Rule 16)

---

## กฎเหล็กความปลอดภัย (Security Constraints)
1. **Part 1 & Part 2 Immutability Rule (Rule 18):** ห้ามแก้ไข ปรับแต่ง เพิ่ม หรือลบโค้ดใน `data_feed/` และ `data_evaluate/` เด็ดขาด 100%
2. **ห้ามมีค่า NaN หรือ Null:** หากฟังก์ชันคำนวณ Linear Regression หรือการป้อนค่าดัชนีใดๆ ประสบปัญหาข้อมูลขาดช่วงจนเกิดค่า `NaN` หรือหารด้วยศูนย์ (`ZeroDivisionError`) ระบบจะต้องยกเลิกกระบวนการทำงานทันที (Fail-Fast)
3. **ขีดจำกัด Volume Ratio:** ค่าอัตราส่วนความแรงปริมาณซื้อขาย (`volume_ratio`) จะถูกคำนวณและจำกัดเพดานความแรงไว้ที่ระดับสูงสุดไม่เกิน `10.0` เท่า เพื่อป้องกันค่ากระโดดผิดธรรมชาติ
4. **การเข้าถึงแบบ Read-Only:** ข้อมูลที่คำนวณแล้วจะถือเป็น Immutable ห้ามแก้ไขตัวแปรต้นฉบับ
5. **Warm-up 250 แท่งสมบูรณ์:** ต้องมีแท่งเทียนครบ 250 แท่งในทุก timeframe (M1, M5, M15) ก่อนเริ่มคำนวณ (`FAIL-FAST` หากไม่ครบ)
