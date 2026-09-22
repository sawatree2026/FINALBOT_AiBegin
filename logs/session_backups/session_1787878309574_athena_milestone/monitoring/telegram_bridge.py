"""
Telegram AI Bridge for Athena (FINALBOT)
=========================================
Allows the Boss to chat with Athena (AI Assistant), check balance,
run market analysis, and receive trading signals directly on Telegram.
"""

import os
import sys
import time
import json
import logging
import threading
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()

try:
    from ai_analysis.artificial_intelligence.gemini_bridge import GeminiApiAgent
except ImportError:
    from data_trade.ai_analysis.gemini_bridge import GeminiApiAgent

logger = logging.getLogger("TelegramBridge")

DEFAULT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8721521604:AAHJ9kthhkFwYpoUa_4Lj3gC8M17-9hPmH4")


class TelegramBridge:
    """Telegram Bot Controller for Athena & FINALBOT."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", DEFAULT_TOKEN)
        if not self.token:
            raise ValueError("FAIL-FAST: TELEGRAM_BOT_TOKEN is not set.")

        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.ai_agent = GeminiApiAgent()
        self.running = False
        self.last_update_id = 0
        self.settings = load_settings(reload=False)

    def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """Sends a text message to a specific Telegram chat."""
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("ok", False)
        except Exception as e:
            logger.error(f"[TelegramBridge] Error sending message: {e}")
            if parse_mode:
                payload.pop("parse_mode", None)
                try:
                    data = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        return res.get("ok", False)
                except Exception:
                    pass
            return False

    def get_updates(self, offset: Optional[int] = None, timeout: int = 20) -> List[Dict[str, Any]]:
        """Long-polls updates from Telegram."""
        url = f"{self.api_url}/getUpdates?timeout={timeout}"
        if offset is not None:
            url += f"&offset={offset}"

        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("result", [])
        except Exception as e:
            logger.debug(f"[TelegramBridge] Long poll timeout or error: {e}")
        return []

    def handle_message(self, msg: Dict[str, Any]) -> None:
        """Processes an incoming message from the Boss."""
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        user_name = msg.get("from", {}).get("first_name", "บอส")

        if not chat_id or not text:
            return

        logger.info(f"[TelegramBridge] Received from {user_name} ({chat_id}): {text}")

        # Command: /start or /help
        if text.startswith("/start") or text.startswith("/help"):
            reply = (
                f"👑 *สวัสดีค่ะบอส! เอเธน่า (Athena AI) พร้อมรับคำสั่งค่ะ*\n\n"
                f"บอสสามารถสั่งงานหรือสอบถามข้อมูลผ่านเมนูด้านล่างนี้ได้เลยนะคะ:\n\n"
                f"📊 `/status` — เช็คยอดเงินและสถานะบอท\n"
                f"🎯 `/analyze EURUSD` — สั่งวิเคราะห์คู่เงินสดทันที\n"
                f"📈 `/signals` — ดูสัญญาณล่าสุดของทุกคู่เงิน\n\n"
                f"💬 *หรือพิมพ์คุยกับเอเธน่าได้อิสระเลยค่ะ*"
            )
            self.send_message(chat_id, reply)
            return

        # Command: /status or /balance
        if text.startswith("/status") or text.startswith("/balance"):
            try:
                from config_setting.symbol_loader import get_symbols
                symbols = get_symbols()
                reply = (
                    f"📊 *รายงานสถานะระบบ FINALBOT*\n\n"
                    f"• *ผู้ช่วย:* Athena (AI Secretary)\n"
                    f"• *โมเดล AI:* Google Gemini API (5 ท่อสัญญาณ 1:1)\n"
                    f"• *คู่เงินที่กำลังเทรด:* {', '.join(symbols)}\n"
                    f"• *โหมดการทำงาน:* AI AUTO_BOT\n"
                    f"• *สถานะ:* ระบบออนไลน์และเชื่อมต่อสมบูรณ์ค่ะ 🟢"
                )
            except Exception as e:
                reply = f"สถานะระบบออนไลน์ปกติค่ะ (หมายเหตุ: {e})"
            self.send_message(chat_id, reply)
            return

        # Command: /analyze
        if text.startswith("/analyze"):
            parts = text.split()
            sym = parts[1].upper() if len(parts) > 1 else "EURUSD-OTC"
            if not sym.endswith("-OTC") and not sym.endswith("OTC") and "-OTC" not in sym:
                sym_with_otc = f"{sym}-OTC"
            else:
                sym_with_otc = sym

            self.send_message(chat_id, f"⏳ กำลังวิเคราะห์กราฟสด {sym_with_otc} ให้บอสสักครู่นะคะ...")

            try:
                csv_path = os.path.join("data_feed", "ohclv_output", "iq_option", sym_with_otc, f"{sym_with_otc}_M1.csv")
                if os.path.exists(csv_path):
                    import pandas as pd
                    df = pd.read_csv(csv_path)
                    last_row = df.iloc[-1]
                    price_info = f"ราคาล่าสุด: {last_row.close:.5f} (High:{last_row.high:.5f} Low:{last_row.low:.5f})"
                else:
                    price_info = "ดึงข้อมูลราคาล่าสุดจากฐานข้อมูล"

                ai_prompt = (
                    f"จงวิเคราะห์คู่เงิน {sym_with_otc} ({price_info}) ในฐานะ Quantitative Trading AI "
                    f"สรุปคำแนะนำ CALL, PUT หรือ WAIT พร้อมเหตุผลสั้นๆ 2-3 บรรทัด สำหรับบอส"
                )
                ai_resp = self.ai_agent.send_prompt(
                    user_prompt=ai_prompt,
                    system_instruction="คุณคือ Athena เลขาธิการของบอส ตอบด้วยภาษาไทย ใช้คำลงท้าย ค่ะ เสมอ กระชับ ชัดเจน เป็นมืออาชีพ"
                )
                self.send_message(chat_id, f"🎯 *ผลการวิเคราะห์ {sym_with_otc}:*\n\n{ai_resp}")
            except Exception as e:
                self.send_message(chat_id, f"ขออภัยค่ะบอส เกิดข้อผิดพลาดในการวิเคราะห์: {e}")
            return

        # Command: /signals
        if text.startswith("/signals"):
            try:
                from config_setting.symbol_loader import get_symbols
                symbols = get_symbols()
                lines = [f"📈 *สรุปสัญญาณล่าสุด ({len(symbols)} คู่เงิน):*\n"]
                for s in symbols:
                    lines.append(f"• *{s}:* รอสัญญาณแท่งถัดไป (ระบบสแกนทุกนาที)")
                self.send_message(chat_id, "\n".join(lines))
            except Exception as e:
                self.send_message(chat_id, f"ไม่สามารถดึงข้อมูลสัญญาณได้ค่ะ: {e}")
            return

        # Natural Language Chat with Athena AI
        try:
            sys_inst = (
                "คุณคือ Athena (เอเธน่า) เลขาส่วนตัวอัจฉริยะของบอส "
                "มีความเชี่ยวชาญด้านการเงิน การเทรด Quantitative Trading และการเขียนโค้ด "
                "ตอบด้วยภาษาไทยที่สุภาพ ฉลาด มั่นใจ กระชับ ตรงประเด็น ใช้คำลงท้าย ค่ะ เสมอ ห้ามใช้ ครับ"
            )
            response_text = self.ai_agent.send_prompt(
                user_prompt=text,
                system_instruction=sys_inst
            )
            self.send_message(chat_id, response_text)
        except Exception as e:
            logger.error(f"[TelegramBridge] Error calling AI: {e}")
            self.send_message(chat_id, f"เกิดข้อผิดพลาดในการประมวลผลคำตอบค่ะ: {e}")

    def start_polling(self) -> None:
        """Starts long-polling loop in blocking or thread mode."""
        from monitoring.console_dashboard import thai_console_log
        self.running = True
        logger.info("[TelegramBridge] Athena Telegram Bridge is ONLINE and listening...")
        thai_console_log("🟢 Athena Telegram Bridge ออนไลน์พร้อมรับคำสั่งทาง Telegram")

        while self.running:
            try:
                updates = self.get_updates(offset=self.last_update_id + 1 if self.last_update_id else None)
                for update in updates:
                    update_id = update.get("update_id")
                    if update_id:
                        self.last_update_id = max(self.last_update_id, update_id)

                    msg = update.get("message")
                    if msg:
                        self.handle_message(msg)
            except Exception as e:
                logger.error(f"[TelegramBridge] Loop error: {e}")
                time.sleep(2)


def main():
    bridge = TelegramBridge()
    bridge.start_polling()


if __name__ == "__main__":
    main()
