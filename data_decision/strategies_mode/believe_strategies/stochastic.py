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
<<<<<<< HEAD
    d = number(fields, "believe_sto_d")
    zone = text(fields, "believe_sto_zone")
    cross = text(fields, "believe_sto_cross")
    hook = boolean(fields, "believe_sto_hook_confirmed")
    cross_50 = boolean(fields, "believe_sto_cross_50")
    tangled = boolean(fields, "believe_risk_sto_tangled")

    if tangled:
        return False

    # Nemesis V.2 Rule (p.37, 44, 49):
    # CALL: STO must touch 10 (OVERSOLD_10) and reverse (hook up, cross 50, or K cross D up)
    # PUT: STO must touch 90 (OVERBOUGHT_90) and reverse (hook down, cross 50, or K cross D down)
    if action == "CALL":
        has_touched = ("10" in zone or "OVERSOLD" in zone or k <= 15.0)
        has_reversed = hook or cross_50 or cross in {"GOLDEN_CROSS", "UP", "BULLISH", "CALL"} or (k > d and k > 10.0)
        return has_touched and has_reversed

    if action == "PUT":
        has_touched = ("90" in zone or "OVERBOUGHT" in zone or k >= 85.0)
        has_reversed = hook or cross_50 or cross in {"DEATH_CROSS", "DOWN", "BEARISH", "PUT"} or (k < d and k < 90.0)
        return has_touched and has_reversed

    return False
=======

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
>>>>>>> 3cc7c09a67c2b4e94aacdcf96972a9d9405fef74
