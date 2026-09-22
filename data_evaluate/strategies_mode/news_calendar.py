"""
economic_news_calendar.py
=========================
รวมระบบปฏิทินข่าวสารเศรษฐกิจและการเงิน 100% (Ingestion, Scraping & Risk Evaluator)
- ดึงข้อมูลข่าวสดจาก Forex Factory (ET -> UTC ISO 8601)
- จำแนกความรุนแรง (🔴 High, 🟡 Medium, ⚪ Low, 🔵 Holiday)
- พิมพ์ UI Console รายงานข่าว และบันทึก JSON ไปยัง data_evaluate/orchestration/calendar_YYYY-MM-DD.txt
- ประเมินกรอบเวลาข่าวล่วงหน้า 30 นาที / ย้อนหลัง 15 นาที
- Instant Lookup O(1) ประเมินความเสี่ยงรายคู่เงิน (HIGH, MEDIUM, LOW, NONE_OTC)
"""

import requests
import json
import csv
import io
import sys
import os
import re
import threading
import logging
import traceback
from datetime import datetime, date, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from pathlib import Path
from bs4 import BeautifulSoup

# บังคับให้ Console พิมพ์ UTF-8
if getattr(sys.stdout, 'encoding', None) and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ─────────────────────────────────────────
#  THAI DAY/MONTH MAPPING
# ─────────────────────────────────────────
THAI_DAYS = {
    0: "วันจันทร์", 1: "วันอังคาร", 2: "วันพุธ",
    3: "วันพฤหัสบดี", 4: "วันศุกร์", 5: "วันเสาร์", 6: "วันอาทิตย์"
}
THAI_MONTHS = {
    1: "มกราคม", 2: "กุมภาพันธ์", 3: "มีนาคม", 4: "เมษายน",
    5: "พฤษภาคม", 6: "มิถุนายน", 7: "กรกฎาคม", 8: "สิงหาคม",
    9: "กันยายน", 10: "ตุลาคม", 11: "พฤศจิกายน", 12: "ธันวาคม"
}

IMPACT_ICON = {
    "High":    "🔴 High   ",
    "Medium":  "🟡 Medium ",
    "Low":     "⚪ Low    ",
    "Holiday": "🔵 Holiday",
}

IMPACT_MAP = {
    "icon--ff-impact-red":    "High",
    "icon--ff-impact-ora":    "Medium",
    "icon--ff-impact-yel":    "Low",
    "icon--ff-impact-gra":    "Holiday",
}

# ─────────────────────────────────────────
#  CONFIG & PATH RESOLUTION
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data_evaluate" / "orchestration"
FF_URL = "https://www.forexfactory.com/calendar"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.forexfactory.com/",
    "Connection": "keep-alive",
}

# Global Caches for News Evaluator
_NEWS_LOCK = threading.RLock()
_PRECALCULATED_NEWS: dict[str, str] = {}
_LAST_CALENDAR_DATE: str | None = None
_EVENTS_CACHE: list[dict] = []

logger = logging.getLogger("FINALBOT")

def log(msg: str = "") -> None:
    """Log with logger to prevent polluting Console UI"""
    logger.info(msg)

# ─────────────────────────────────────────
#  CONSOLE UI PRINTING (STRICT BACKUP 100%)
# ─────────────────────────────────────────
def print_header(target_date: date) -> None:
    """พิมพ์ header สไตล์ FINALBOT"""
    if not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")
    from monitoring.console_dashboard import thai_console_log
    thai_day   = THAI_DAYS[target_date.weekday()]
    thai_month = THAI_MONTHS[target_date.month]
    thai_year  = target_date.year + 543
    date_th    = f"{thai_day} ที่ {target_date.day} {thai_month} {thai_year}"

    thai_console_log(f"ระบบรายงานข่าวเศรษฐกิจและการเงิน : {date_th} : By Athena(Ai)")

def print_events(events: list[dict]) -> None:
    """พิมพ์ข่าวแต่ละรายการ"""
    if not isinstance(events, list):
        raise TypeError(f"events must be list, got {type(events)}")
    from monitoring.console_dashboard import thai_console_log
    for e in events:
        try:
            dt = datetime.fromisoformat(e["date"])
            dt_et = dt.astimezone(ZoneInfo("America/New_York"))
            time_display = dt_et.strftime("%H:%M")
        except Exception as ex:
            time_display = "--:--"
            log(f"[ERROR] Date parse error: {ex}")

        impact_str = IMPACT_ICON.get(e.get("impact", "Low"), "⚪ Low    ")
        title_short = e.get("title", "")[:36]
        forecast   = e.get("forecast", "") or "-"
        previous   = e.get("previous", "") or "-"
        country    = e.get("country", "")

        line = (
            f"{time_display:<12}"
            f"{title_short:<38}"
            f"{country:<10}"
            f"{impact_str:<14}"
            f"{forecast:<12}"
            f"{previous}"
        )
        thai_console_log(f" {line}")

def print_summary(events: list[dict], filepath: Path) -> None:
    """พิมพ์สรุปท้าย"""
    if not isinstance(events, list):
        raise TypeError(f"events must be list, got {type(events)}")
    from monitoring.console_dashboard import thai_console_log
    high    = sum(1 for e in events if e.get("impact") == "High")
    medium  = sum(1 for e in events if e.get("impact") == "Medium")
    low     = sum(1 for e in events if e.get("impact") in ("Low", "Holiday"))
    width   = 80

    thai_console_log("-" * width)
    thai_console_log(f"[สรุป] ข่าวทั้งหมด {len(events)} รายการ  |  🔴 High: {high}  🟡 Medium: {medium}  ⚪ Low: {low}")
    thai_console_log(f"[บันทึกไฟล์] → {filepath}")
    thai_console_log("=" * width)

# ─────────────────────────────────────────
#  FETCH & PARSE ENGINE
# ─────────────────────────────────────────
def fetch_calendar(target_date: date) -> list[dict]:
    """ดึงข่าวจาก Forex Factory (JSON / CSV Feed / HTML Scraping) สำหรับวันที่ระบุ"""
    if not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")

    log(f"[FETCH] กำลังดึงข้อมูลปฏิทินข่าวสำหรับวันที่: {target_date}")
    events = []

    # 1. พยายามดึงผ่าน Official FairEconomy JSON Feed
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            for item in data:
                try:
                    dt = datetime.fromisoformat(item["date"]).astimezone(timezone.utc)
                    if dt.date() == target_date:
                        events.append({
                            "title": item.get("title", "").strip(),
                            "country": item.get("country", "").strip(),
                            "date": dt.isoformat(),
                            "impact": item.get("impact", "Low").strip(),
                            "forecast": item.get("forecast", "").strip(),
                            "previous": item.get("previous", "").strip(),
                        })
                except Exception:
                    continue
            if events:
                log(f"[FETCH] ได้รับข่าวผ่าน JSON Feed ทั้งหมด {len(events)} รายการ")
                return events
    except Exception as e:
        log(f"[WARN] FairEconomy JSON Feed error: {e}")

    # 2. พยายามดึงผ่าน Official FairEconomy CSV Feed
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.csv",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10
        )
        if r.status_code == 200 and "Title" in r.text:
            reader = csv.DictReader(io.StringIO(r.text))
            for row in reader:
                title = row.get("Title", "").strip()
                country = row.get("Country", "").strip()
                date_str = row.get("Date", "").strip()
                time_str = row.get("Time", "").strip()
                impact = row.get("Impact", "Low").strip()
                forecast = row.get("Forecast", "").strip()
                previous = row.get("Previous", "").strip()
                try:
                    m, d, y = map(int, date_str.split("-"))
                    time_clean = time_str.lower().strip()
                    if not time_clean or time_clean in ("all day", "tentative", ""):
                        dt_ny = datetime(y, m, d, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
                    else:
                        try:
                            t = datetime.strptime(time_clean, "%I:%M%p")
                            dt_ny = datetime(y, m, d, t.hour, t.minute, 0, tzinfo=ZoneInfo("America/New_York"))
                        except ValueError:
                            t = datetime.strptime(time_clean, "%I%p")
                            dt_ny = datetime(y, m, d, t.hour, 0, 0, tzinfo=ZoneInfo("America/New_York"))
                    dt_utc = dt_ny.astimezone(timezone.utc)
                    if dt_utc.date() == target_date or date(y, m, d) == target_date:
                        events.append({
                            "title": title,
                            "country": country,
                            "date": dt_utc.isoformat(),
                            "impact": impact,
                            "forecast": forecast,
                            "previous": previous,
                        })
                except Exception:
                    continue
            if events:
                log(f"[FETCH] ได้รับข่าวผ่าน CSV Feed ทั้งหมด {len(events)} รายการ")
                return events
    except Exception as e:
        log(f"[WARN] FairEconomy CSV Feed error: {e}")

    # 3. พยายามดึงผ่าน Forex Factory HTML Scraping
    try:
        day_param = target_date.strftime("%b%d.%Y").lower()
        url = f"{FF_URL}?day={day_param}"
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            page_title = soup.title.text.lower() if soup.title else ""
            if "just a moment" not in page_title and "cloudflare" not in page_title:
                html_events = parse_calendar(soup, target_date)
                if html_events:
                    return html_events
    except Exception as e:
        log(f"[WARN] HTML Scraping error: {e}")

    log(f"[INFO] ไม่พบข่าวสำหรับวันที่ {target_date} (บันทึก {len(events)} รายการ)")
    return events

def parse_calendar(soup: BeautifulSoup, target_date: date) -> list[dict]:
    """Parse HTML table → list of event dicts"""
    if not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")
    table = soup.find("table", class_=re.compile(r"calendar__table"))
    if not table:
        log("[WARN] ไม่พบตารางข่าว — FF อาจเปลี่ยน HTML structure")
        return []

    rows = table.find_all("tr", class_=re.compile(r"calendar__row"))
    events = []
    current_time_str = ""

    re_time = re.compile(r"calendar__time")
    re_currency = re.compile(r"calendar__currency")
    re_impact = re.compile(r"calendar__impact")
    re_event = re.compile(r"calendar__event")
    re_forecast = re.compile(r"calendar__forecast")
    re_previous = re.compile(r"calendar__previous")

    for row in rows:
        time_cell = row.find("td", class_=re_time)
        if time_cell:
            t = time_cell.get_text(strip=True)
            if t and t.lower() not in ("", "all day", "tentative"):
                current_time_str = t

        currency_cell = row.find("td", class_=re_currency)
        if not currency_cell:
            continue
        country = currency_cell.get_text(strip=True).upper()
        if not country:
            continue

        impact = "Low"
        impact_cell = row.find("td", class_=re_impact)
        if impact_cell:
            span = impact_cell.find("span")
            if span:
                classes = span.get("class", [])
                for cls in classes:
                    if cls in IMPACT_MAP:
                        impact = IMPACT_MAP[cls]
                        break

        event_cell = row.find("td", class_=re_event)
        if not event_cell:
            continue
        title = event_cell.get_text(strip=True)
        if not title:
            continue

        forecast_cell = row.find("td", class_=re_forecast)
        forecast = forecast_cell.get_text(strip=True) if forecast_cell else ""

        previous_cell = row.find("td", class_=re_previous)
        previous = previous_cell.get_text(strip=True) if previous_cell else ""

        date_str = _build_datetime(target_date, current_time_str)

        events.append({
            "title":    title,
            "country":  country,
            "date":     date_str,
            "impact":   impact,
            "forecast": forecast,
            "previous": previous,
        })

    log(f"[PARSE] พบข่าว {len(events)} รายการ")
    return events

def _build_datetime(target_date: date, time_str: str) -> str:
    """แปลง date + time string → ISO 8601 string (UTC)"""
    if not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")
    if not isinstance(time_str, str):
        raise TypeError(f"time_str must be str, got {type(time_str)}")

    time_str_clean = time_str.strip().lower()

    if not time_str_clean or time_str_clean in ("all day", "tentative", "") or time_str_clean.startswith("day"):
        dt_ny = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        return dt_ny.astimezone(ZoneInfo("UTC")).isoformat()

    if "th" in time_str_clean or "st" in time_str_clean or "nd" in time_str_clean or "rd" in time_str_clean:
        try:
            parts = time_str_clean.split()
            if len(parts) >= 2:
                month_map = {
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
                }
                month_str = parts[0]
                day_str = parts[1]
                if month_str in month_map:
                    day = int(re.sub(r'\D', '', day_str))
                    t = datetime(target_date.year, month_map[month_str], day, 12, 0, 0)
                    return t.astimezone(ZoneInfo("America/New_York")).astimezone(ZoneInfo("UTC")).isoformat()
        except Exception as e:
            log(f"[WARN] Could not parse ordinal time '{time_str_clean}': {e}")

    try:
        t = datetime.strptime(time_str_clean, "%I:%M%p")
    except ValueError:
        try:
            t = datetime.strptime(time_str_clean, "%I%p")
        except ValueError:
            log(f"[WARN] Could not parse time string '{time_str_clean}', using 12:00am")
            t = datetime.strptime("12:00am", "%I:%M%p")

    dt_ny = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        t.hour,
        t.minute,
        t.second,
        tzinfo=ZoneInfo("America/New_York")
    )

    return dt_ny.astimezone(ZoneInfo("UTC")).isoformat()

# ─────────────────────────────────────────
#  EXPORT ENGINE (STRICT BACKUP 100% JSON)
# ─────────────────────────────────────────
def export_json(events: list[dict], target_date: date) -> Path:
    """บันทึก JSON ลงไฟล์ พร้อมลบไฟล์ข่าวเก่าตกค้างให้เหลือเฉพาะไฟล์วันปัจจุบัน"""
    if not isinstance(events, list):
        raise TypeError(f"events must be list, got {type(events)}")
    if not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ค้นหาและลบไฟล์ calendar_*.txt เก่าทั้งหมดใน OUTPUT_DIR ก่อนเขียนไฟล์ใหม่
    for old_file in OUTPUT_DIR.glob("calendar_*.txt"):
        try:
            old_file.unlink(missing_ok=True)
            log(f"[CLEANUP] ลบไฟล์ข่าวเก่า: {old_file.name}")
        except Exception as e:
            log(f"[WARN] ไม่สามารถลบไฟล์ข่าวเก่า {old_file.name}: {e}")

    filename = f"calendar_{target_date.isoformat()}.txt"
    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=4)

    return filepath

export_txt = export_json

# ─────────────────────────────────────────
#  EVALUATOR & ORCHESTRATION INTEGRATION
# ─────────────────────────────────────────
def ensure_calendar_news(target_date: date = None, show_ui: bool = True) -> Path:
    """
    ตรวจสอบและดึงข่าวของวันนี้อัตโนมัติบน Startup
    ลบไฟล์ปฏิทินข่าวของวันก่อนหน้าที่ตกค้างทิ้งอัตโนมัติ
    หากยังไม่มีไฟล์ calendar_YYYY-MM-DD.txt ให้ดึงสดและบันทึกทันที
    """
    if target_date is None:
        target_date = date.today()
    elif not isinstance(target_date, date):
        raise TypeError(f"target_date must be date, got {type(target_date)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"calendar_{target_date.isoformat()}.txt"
    filepath = OUTPUT_DIR / filename

    # ตรวจสอบและลบไฟล์ปฏิทินข่าวของวันก่อนหน้าที่ตกค้างทิ้งอัตโนมัติ
    for old_file in OUTPUT_DIR.glob("calendar_*.txt"):
        if old_file.name != filename:
            try:
                old_file.unlink(missing_ok=True)
                log(f"[CLEANUP] ลบไฟล์ปฏิทินข่าวตกค้าง: {old_file.name}")
            except Exception as e:
                log(f"[WARN] ไม่สามารถลบไฟล์ข่าวตกค้าง {old_file.name}: {e}")

    if not filepath.exists():
        log(f"[START] เริ่มดึงปฏิทินข่าว วันที่: {target_date}")
        events = fetch_calendar(target_date)
        saved_path = export_json(events, target_date)
        if show_ui:
            print_header(target_date)
        return saved_path
    else:
        if show_ui:
            try:
                print_header(target_date)
            except Exception as e:
                log(f"[WARN] Error displaying cached news: {e}")
        return filepath

def update_all_news_impact(symbols: list = None) -> None:
    """
    คำนวณและอัปเดตผลกระทบข่าวล่วงหน้าสำหรับทุกคู่เงิน
    ประเมินกรอบเวลาข่าวล่วงหน้า 30 นาที / ย้อนหลัง 15 นาที
    """
    if symbols is not None and not isinstance(symbols, list):
        raise TypeError(f"update_all_news_impact: symbols must be list or None, got {type(symbols)}")

    if symbols is None:
        try:
            from config_setting.config_loader import get_symbols
            symbols = get_symbols()
        except Exception:
            symbols = ["EURUSD", "GBPUSD", "EURGBP"]

    global _PRECALCULATED_NEWS, _LAST_CALENDAR_DATE, _EVENTS_CACHE
    with _NEWS_LOCK:
        try:
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y-%m-%d")

            # โหลดไฟล์ JSON เฉพาะเมื่อยังไม่มีข้อมูลของวันนี้ (ตามเวลา UTC)
            if _LAST_CALENDAR_DATE != today_str:
                calendar_file = OUTPUT_DIR / f"calendar_{today_str}.txt"

                if not calendar_file.exists():
                    log(f"[NEWS] Calendar file for {today_str} (UTC) not found (Day Rollover). Auto-fetching...")
                    try:
                        ensure_calendar_news(now_utc.date())
                    except Exception as e:
                        log(f"[ERROR] Auto-fetch news failed: {e}")
                        traceback.print_exc()
                        raise RuntimeError(f"Auto-fetch news failed: {e}") from e

                if calendar_file.exists():
                    try:
                        with open(calendar_file, "r", encoding="utf-8") as f:
                            _EVENTS_CACHE = json.load(f)
                        _LAST_CALENDAR_DATE = today_str
                    except json.JSONDecodeError as e:
                        log(f"[ERROR] Calendar JSON is corrupt: {e}. Removing file.")
                        try:
                            os.remove(calendar_file)
                        except OSError:
                            pass
                        raise RuntimeError(f"Calendar JSON is corrupt: {e}") from e
                else:
                    log(f"[WARN] Calendar file {calendar_file} not found even after auto-fetch. Using empty events.")
                    _EVENTS_CACHE = []
                    _LAST_CALENDAR_DATE = today_str

            # คำนวณทีละคู่เงิน
            for symbol in symbols:
                if not isinstance(symbol, str):
                    raise TypeError(f"symbol must be str, got {type(symbol)}")

                # 1. OTC Bypass
                if "OTC" in symbol.upper():
                    _PRECALCULATED_NEWS[symbol] = "NONE_OTC"
                    continue

                if not _EVENTS_CACHE:
                    _PRECALCULATED_NEWS[symbol] = "LOW"
                    continue

                clean_symbol = symbol.upper().replace("-OTC", "").replace("_OTC", "")
                upcoming_news = []
                past_news = []

                for event in _EVENTS_CACHE:
                    date_str = event.get("date")
                    if not date_str:
                        continue

                    event_time = datetime.fromisoformat(date_str)

                    if event_time.tzinfo is None:
                        event_time = event_time.replace(tzinfo=timezone.utc)

                    time_diff = (event_time - now_utc).total_seconds() / 60
                    impact = event.get("impact", "")
                    currency = event.get("country", "")

                    relevant = clean_symbol[:3] in currency or clean_symbol[3:] in currency
                    if relevant:
                        if 0 <= time_diff <= 30:
                            upcoming_news.append({"impact": impact})
                        elif -15 <= time_diff < 0:
                            past_news.append({"impact": impact})

                    all_news = upcoming_news + past_news

                has_high = any(n['impact'].strip().upper() == "HIGH" for n in all_news)
                has_medium = any(n['impact'].strip().upper() == "MEDIUM" for n in all_news)

                if has_high:
                    _PRECALCULATED_NEWS[symbol] = "HIGH"
                elif has_medium:
                    _PRECALCULATED_NEWS[symbol] = "MEDIUM"
                else:
                    _PRECALCULATED_NEWS[symbol] = "LOW"

        except Exception as e:
            log(f"[ERROR] update_all_news_impact error: {e}")
            traceback.print_exc()
            raise RuntimeError(f"update_all_news_impact error: {e}") from e

def check_news_impact(symbol: str = "EURUSD") -> str:
    """
    ดึงข้อมูลผลกระทบข่าวที่คำนวณไว้แล้ว (Instant Lookup)
    สำหรับ OTC จะไม่มีข่าวจริง จึงกำหนดเป็น 'NONE_OTC' เพื่อแยกจากคู่เงินปกติ
    """
    if not isinstance(symbol, str):
        raise TypeError(f"check_news_impact: symbol must be str, got {type(symbol)}")
    if "OTC" in symbol.upper():
        return 'NONE_OTC'
    with _NEWS_LOCK:
        if symbol not in _PRECALCULATED_NEWS:
            update_all_news_impact([symbol])
        return _PRECALCULATED_NEWS.get(symbol, 'LOW')

# ─────────────────────────────────────────
#  MAIN CLI
# ─────────────────────────────────────────
def main() -> None:
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            log(f"[ERROR] รูปแบบวันที่ไม่ถูกต้อง: {sys.argv[1]}  (ใช้ YYYY-MM-DD)")
            sys.exit(1)
    else:
        target_date = date.today()

    print_header(target_date)

    log(f"[START] เริ่มดึงปฏิทินข่าว วันที่: {target_date}")

    events = fetch_calendar(target_date)

    if not events:
        log("[WARN] ไม่พบข่าว — บันทึก list ว่าง")

    print_events(events)

    filepath = export_json(events, target_date)

    print_summary(events, filepath)

if __name__ == "__main__":
    main()
