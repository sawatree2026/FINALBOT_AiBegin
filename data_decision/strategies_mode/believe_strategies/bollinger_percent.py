"""Bollinger Band %B component of Believe — NEMESIS E-BOOK V2 p.37 / p.49.

ตำรา:
  p.37  "ดูเส้น Bollinger band % ว่าแตะเส้น 0 หรือเส้น 1 หรือยัง
         (เป็นไปได้ เส้นควรแตะแบบเดียวกับ STO จะทำให้ปลอดภัยที่สุด แต่จะไม่แตะก็ได้)"
  p.49  "BB% จะต้องแตะเส้น เขียว/แดง ก่อนเสมอ"

การอ่านที่ถูกต้อง: การแตะเป็น **เหตุการณ์ในอดีตของ setup** ("แตะก่อนเสมอ")
ไม่ใช่ค่า %B ขณะเข้า (ขณะเข้า %B ดีดกลับมาอยู่กลางแถบแล้ว)
→ ใช้ flag `believe_bb_touch_low/high` ที่ Part 2 ตรวจในหน้าต่าง 10 แท่ง S30
"""

import math
from typing import Dict

from .field_utils import boolean, number, text


def evaluate(fields: Dict[str, str], action: str) -> bool:
    if action not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid Believe action: {action!r}")
    percent_b = number(fields, "believe_bb_percent_b")
    if not math.isfinite(percent_b):
        raise ValueError("Invalid numeric Believe payload field: believe_bb_percent_b")

    touch = text(fields, "believe_bb_touch")
    if action == "CALL":
        # แตะเส้น 0 (ล่าง) ภายในหน้าต่าง setup หรือ กำลังแตะอยู่ตอนนี้
        return boolean(fields, "believe_bb_touch_low") or touch in {
            "LOWER", "LOWER_0", "LOWER_BAND",
        }
    if action == "PUT":
        # แตะเส้น 1 (บน) ภายในหน้าต่าง setup หรือ กำลังแตะอยู่ตอนนี้
        return boolean(fields, "believe_bb_touch_high") or touch in {
            "UPPER", "UPPER_1", "UPPER_BAND",
        }
    return False
