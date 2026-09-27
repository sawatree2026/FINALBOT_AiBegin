"""Stochastic component of Believe — NEMESIS E-BOOK V2 p.37 / p.49.

ตำรา:
  p.37  "ดู STO ว่าแตะเส้น 90 หรือเส้น 10 หรือยัง (สำคัญมากๆ จะต้องแตะถึงจะเข้าออเดอร์ได้)"
        CALL: STO ต้องข้ามผ่านเส้น 50 + โผล่ขึ้นมาจากเส้น 10
        PUT : STO ต้องข้ามผ่านเส้น 50 + โผล่ลงมาจากเส้น 90
  p.49  "STO จะต้องแตะเส้น เขียว/แดง" + จุดเข้า: STO หักหัว ขึ้น/ลง

→ การแตะ 10/90 เป็นเงื่อนไขบังคับ (ตรวจในหน้าต่าง 10 แท่ง S30 ที่ Part 2)
→ การ "โผล่ออกมา/หักหัว" = touch + ทิศทางปัจจุบันสวนกลับ + พ้นเส้น 10/90 แล้ว
→ การข้ามเส้น 50 = สถานะปัจจุบันของ %K เทียบ 50
"""

from typing import Dict

from .field_utils import boolean, number


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    k = number(fields, "believe_sto_k")

    # ข้อระวังข้อ 3 (p.37): STO ห้ามพันกัน
    if boolean(fields, "believe_risk_sto_tangled"):
        return False

    if action == "CALL":
        touched = boolean(fields, "believe_sto_touch_low")     # แตะเส้น 10 ในหน้าต่าง setup
        emerged = boolean(fields, "believe_sto_emerged_up")    # โผล่ขึ้น/หักหัวขึ้น พ้น 10 แล้ว
        crossed_50 = k > 50                                    # ข้ามผ่านเส้น 50 แล้ว
    else:
        touched = boolean(fields, "believe_sto_touch_high")    # แตะเส้น 90 ในหน้าต่าง setup
        emerged = boolean(fields, "believe_sto_emerged_dn")    # โผล่ลง/หักหัวลง พ้น 90 แล้ว
        crossed_50 = k < 50                                    # ข้ามผ่านเส้น 50 แล้ว

    # p.37 ขั้น 2-3: ต้องแตะ + โผล่ออกมา + ข้าม 50 ครบ
    return touched and emerged and crossed_50
