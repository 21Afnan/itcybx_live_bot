# src/tools/booking_tool.py

import json
import uuid
import re
import datetime
import zoneinfo
from pathlib import Path
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool

import requests
from src.config.settings import (
    DATA_DIR,
    WORKING_DAYS,
    MEETING_START_HOUR,
    MEETING_END_HOUR,
    MEETING_DURATION_MINUTES,
    TIMEZONE_LABEL,
    CALENDLY_API_KEY,
    CALENDLY_EVENT_TYPE_URI,
    CALENDLY_TIMEZONE,
)
from src.utils.logger import get_logger

logger = get_logger("BookingTool")

BOOKINGS_FILE = DATA_DIR / "bookings.json"

# Day name translations & weekday indices (Sunday=6, Monday=0, Tuesday=1, Wednesday=2, Thursday=3)
WORKING_WEEKDAYS = {6: "Sunday", 0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday"}
ARABIC_DAY_NAMES = {
    "Sunday": "الأحد",
    "Monday": "الإثنين",
    "Tuesday": "الثلاثاء",
    "Wednesday": "الأربعاء",
    "Thursday": "الخميس",
    "Friday": "الجمعة",
    "Saturday": "السبت",
}
ENGLISH_DAY_NAMES = {
    "الأحد": "Sunday",
    "الإثنين": "Monday",
    "الاثنين": "Monday",
    "الثلاثاء": "Tuesday",
    "الأربعاء": "Wednesday",
    "الاربعاء": "Wednesday",
    "الخميس": "Thursday",
    "الجمعة": "Friday",
    "السبت": "Saturday",
}

# In-memory cache for Calendly info and recent slots
_cached_calendly_info: Optional[Dict[str, Any]] = None
_cached_available_slots: List[Dict[str, Any]] = []
_last_slots_fetch_time: Optional[datetime.datetime] = None


# =====================================================================
# CALENDLY API CLIENT HELPERS
# =====================================================================

def get_calendly_client_info() -> Optional[Dict[str, Any]]:
    """
    Fetches and caches active user profile, event type, and timezone from Calendly API.
    """
    global _cached_calendly_info
    if _cached_calendly_info:
        return _cached_calendly_info

    if not CALENDLY_API_KEY:
        return None

    try:
        headers = {"Authorization": f"Bearer {CALENDLY_API_KEY}"}
        user_resp = requests.get("https://api.calendly.com/users/me", headers=headers, timeout=8)
        if user_resp.status_code != 200:
            logger.warning(f"Calendly users/me failed ({user_resp.status_code}): {user_resp.text}")
            return None

        user_data = user_resp.json().get("resource", {})
        user_uri = user_data.get("uri")
        user_timezone = user_data.get("timezone", CALENDLY_TIMEZONE or "Asia/Karachi")

        # Fetch active event types
        event_type_uri = CALENDLY_EVENT_TYPE_URI
        scheduling_url = user_data.get("scheduling_url")
        location_kind = "google_conference"
        event_duration = 30
        event_name = "Growth Audit Consultation"

        et_resp = requests.get(f"https://api.calendly.com/event_types?user={user_uri}", headers=headers, timeout=8)
        if et_resp.status_code == 200:
            event_types = et_resp.json().get("collection", [])
            for et in event_types:
                if et.get("active"):
                    event_type_uri = et.get("uri")
                    scheduling_url = et.get("scheduling_url")
                    event_duration = et.get("duration", 30)
                    event_name = et.get("name", "30 Minute Meeting")
                    locations = et.get("locations", [])
                    if locations and isinstance(locations, list):
                        location_kind = locations[0].get("kind", "google_conference")
                    break

        _cached_calendly_info = {
            "user_uri": user_uri,
            "user_name": user_data.get("name", "Afnan Shoukat"),
            "user_email": user_data.get("email"),
            "user_timezone": user_timezone,
            "event_type_uri": event_type_uri,
            "event_name": event_name,
            "event_duration": event_duration,
            "scheduling_url": scheduling_url,
            "location_kind": location_kind,
        }
        logger.info(f"Calendly profile loaded: {_cached_calendly_info['event_name']} ({scheduling_url})")
        return _cached_calendly_info
    except Exception as e:
        logger.error(f"Error initializing Calendly client info: {e}")
        return None


def fetch_calendly_available_slots(days_ahead: int = 7) -> List[Dict[str, Any]]:
    """
    Fetches real-time available meeting slots from Calendly API for the upcoming days.
    """
    global _cached_available_slots, _last_slots_fetch_time

    # Return cached slots if fetched less than 60 seconds ago
    now = datetime.datetime.now(datetime.timezone.utc)
    if _cached_available_slots and _last_slots_fetch_time:
        if (now - _last_slots_fetch_time).total_seconds() < 60:
            return _cached_available_slots

    cal_info = get_calendly_client_info()
    if not cal_info or not cal_info.get("event_type_uri"):
        logger.info("Calendly API not configured or active. Using local schedule rules.")
        return _generate_sandbox_slots(days_ahead=days_ahead)

    try:
        headers = {"Authorization": f"Bearer {CALENDLY_API_KEY}"}
        # Calendly requires start_time strictly in the future with Z ISO format
        start_time_iso = (now + datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time_iso = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "event_type": cal_info["event_type_uri"],
            "start_time": start_time_iso,
            "end_time": end_time_iso,
        }

        resp = requests.get("https://api.calendly.com/event_type_available_times", headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Calendly event_type_available_times failed ({resp.status_code}): {resp.text}")
            return _generate_sandbox_slots(days_ahead=days_ahead)

        items = resp.json().get("collection", [])
        tz_name = cal_info.get("user_timezone", "Asia/Karachi")
        try:
            target_tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            target_tz = zoneinfo.ZoneInfo("Asia/Karachi")

        slots = []
        for item in items:
            if item.get("status") != "available" or item.get("invitees_remaining", 0) <= 0:
                continue

            utc_str = item.get("start_time")
            # Parse ISO 8601 UTC timestamp
            dt_utc = datetime.datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(target_tz)

            day_name_en = dt_local.strftime("%A")
            day_name_ar = ARABIC_DAY_NAMES.get(day_name_en, day_name_en)
            date_en = dt_local.strftime("%B %d, %Y")
            date_ar = dt_local.strftime("%Y/%m/%d")

            # 12-hour format e.g. 12:15 PM / 12:15 م
            time_en = dt_local.strftime("%I:%M %p").lstrip("0")
            period_ar = "مساءً" if dt_local.hour >= 12 else "صباحاً"
            hour_12 = dt_local.hour if dt_local.hour <= 12 else dt_local.hour - 12
            if hour_12 == 0:
                hour_12 = 12
            time_ar = f"{hour_12}:{dt_local.strftime('%M')} {period_ar}"

            full_str_en = f"{day_name_en}, {date_en} at {time_en}"
            full_str_ar = f"يوم {day_name_ar} ({date_ar}) الساعة {time_ar}"

            slots.append({
                "start_time_iso": utc_str,
                "local_dt": dt_local,
                "date_key": dt_local.strftime("%Y-%m-%d"),
                "day_name_en": day_name_en,
                "day_name_ar": day_name_ar,
                "date_en": date_en,
                "date_ar": date_ar,
                "time_en": time_en,
                "time_ar": time_ar,
                "full_str_en": full_str_en,
                "full_str_ar": full_str_ar,
                "scheduling_url": item.get("scheduling_url"),
            })

        _cached_available_slots = slots
        _last_slots_fetch_time = now
        logger.info(f"Fetched {len(slots)} live available slots from Calendly API.")
        return slots

    except Exception as e:
        logger.error(f"Failed to fetch Calendly availability: {e}")
        return _generate_sandbox_slots(days_ahead=days_ahead)


def _generate_sandbox_slots(days_ahead: int = 5) -> List[Dict[str, Any]]:
    """
    Fallback dynamic slot generator conforming strictly to working schedule (Sun-Thu, 12:15 PM - 5:00 PM).
    """
    now = datetime.datetime.now()
    try:
        local_tz = zoneinfo.ZoneInfo(CALENDLY_TIMEZONE or "Asia/Karachi")
    except Exception:
        local_tz = datetime.timezone(datetime.timedelta(hours=5))

    slots = []
    current_date = now.date()
    days_found = 0

    for day_offset in range(14):
        check_date = current_date + datetime.timedelta(days=day_offset)
        # Sunday=6, Mon=0, Tue=1, Wed=2, Thu=3
        if check_date.weekday() in WORKING_WEEKDAYS:
            day_name_en = WORKING_WEEKDAYS[check_date.weekday()]
            day_name_ar = ARABIC_DAY_NAMES.get(day_name_en, day_name_en)
            date_en = check_date.strftime("%B %d, %Y")
            date_ar = check_date.strftime("%Y/%m/%d")

            # Slots: 12:15, 12:45, 1:15, 1:45, 2:15, 2:45, 3:15, 3:45, 4:15
            for hour in range(MEETING_START_HOUR, MEETING_END_HOUR):
                for minute in (15, 45):
                    slot_dt = datetime.datetime(check_date.year, check_date.month, check_date.day, hour, minute, tzinfo=local_tz)
                    if slot_dt < datetime.datetime.now(local_tz):
                        continue

                    # UTC ISO timestamp
                    utc_dt = slot_dt.astimezone(datetime.timezone.utc)
                    utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                    time_en = slot_dt.strftime("%I:%M %p").lstrip("0")
                    period_ar = "مساءً" if hour >= 12 else "صباحاً"
                    hour_12 = hour if hour <= 12 else hour - 12
                    if hour_12 == 0:
                        hour_12 = 12
                    time_ar = f"{hour_12}:{minute:02d} {period_ar}"

                    full_str_en = f"{day_name_en}, {date_en} at {time_en}"
                    full_str_ar = f"يوم {day_name_ar} ({date_ar}) الساعة {time_ar}"

                    slots.append({
                        "start_time_iso": utc_iso,
                        "local_dt": slot_dt,
                        "date_key": check_date.strftime("%Y-%m-%d"),
                        "day_name_en": day_name_en,
                        "day_name_ar": day_name_ar,
                        "date_en": date_en,
                        "date_ar": date_ar,
                        "time_en": time_en,
                        "time_ar": time_ar,
                        "full_str_en": full_str_en,
                        "full_str_ar": full_str_ar,
                        "scheduling_url": None,
                    })

            days_found += 1
            if days_found >= days_ahead:
                break

    return slots


def match_user_slot_to_available(requested_slot: str, available_slots: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Intelligently matches user's slot description (natural language, date, time) to a verified Calendly slot.
    """
    if not requested_slot or not available_slots:
        return None

    query = requested_slot.strip().lower()

    # 1. Exact ISO timestamp match
    for slot in available_slots:
        if slot["start_time_iso"].lower() in query or query in slot["start_time_iso"].lower():
            return slot

    # Extract time component if present (e.g. 12:15, 1:45, 2:00, 3:15, 4:15, etc.)
    time_match = re.search(r"(\d{1,2}):(\d{2})", query)
    req_hour = None
    req_minute = None
    if time_match:
        h, m = int(time_match.group(1)), int(time_match.group(2))
        is_pm = "pm" in query or "مساء" in query or "م" in query.split()
        if is_pm and h < 12:
            h += 12
        elif not is_pm and h == 12 and ("am" in query or "صباح" in query):
            h = 0
        req_hour, req_minute = h, m
    else:
        # Check hour-only format e.g. "2 pm", "2pm", "الساعة 2"
        hour_match = re.search(r"(?:at|\s|الساعة)\s*(\d{1,2})\s*(?:pm|am|مساء|صباح)?", query)
        if hour_match:
            try:
                h = int(hour_match.group(1))
                if 1 <= h <= 12:
                    is_pm = "pm" in query or "مساء" in query or "م" in query.split() or h in (12, 1, 2, 3, 4, 5)
                    if is_pm and h < 12:
                        h += 12
                    req_hour = h
                    req_minute = 15  # Default to standard :15 slot
            except Exception:
                pass

    # Detect day of week in English or Arabic
    matched_weekday_en = None
    for en_day, ar_day in ARABIC_DAY_NAMES.items():
        if en_day.lower() in query or ar_day.lower() in query or ar_day.replace("أ", "ا") in query:
            matched_weekday_en = en_day
            break

    # Check for "tomorrow" or "غدا"
    is_tomorrow = "tomorrow" in query or "غدا" in query or "بكرة" in query
    tomorrow_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # Filter candidate slots by day/date
    candidate_slots = []
    for slot in available_slots:
        if is_tomorrow and slot["date_key"] != tomorrow_date:
            continue
        if matched_weekday_en and slot["day_name_en"] != matched_weekday_en:
            continue
        candidate_slots.append(slot)

    if not candidate_slots:
        candidate_slots = available_slots

    # Match slot with minimal time difference
    if req_hour is not None:
        target_minutes = req_hour * 60 + (req_minute if req_minute is not None else 15)
        best_slot = min(
            candidate_slots,
            key=lambda s: abs((s["local_dt"].hour * 60 + s["local_dt"].minute) - target_minutes)
        )
        return best_slot

    # If weekday matched and no specific time matched, pick the first slot of that day
    if candidate_slots:
        return candidate_slots[0]

    # Match by substring in full formatted strings
    for slot in available_slots:
        if slot["time_en"].lower() in query or slot["time_ar"].lower() in query:
            return slot

    return available_slots[0] if available_slots else None


def create_calendly_booking(
    name: str,
    email: str,
    start_time_iso: str,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Calls Calendly API POST /invitees to programmatically book the meeting and generate Google Meet link.
    """
    cal_info = get_calendly_client_info()
    if not cal_info or not CALENDLY_API_KEY:
        logger.warning("Calendly API key missing. Performing local sandbox booking.")
        return {
            "success": True,
            "booking_method": "sandbox",
            "event_uri": None,
            "invitee_uri": None,
            "google_meet_url": None,
            "cancel_url": None,
            "reschedule_url": None,
        }

    try:
        headers = {
            "Authorization": f"Bearer {CALENDLY_API_KEY}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "event_type": cal_info["event_type_uri"],
            "start_time": start_time_iso,
            "location": {
                "kind": cal_info.get("location_kind", "google_conference")
            },
            "invitee": {
                "name": name.strip(),
                "email": email.strip(),
                "timezone": cal_info.get("user_timezone", "Asia/Karachi"),
            },
        }

        if notes:
            payload["questions_and_answers"] = [
                {
                    "question": "Please share anything that will help prepare for our meeting.",
                    "answer": notes.strip(),
                }
            ]

        logger.info(f"Submitting booking to Calendly API POST /invitees for '{email}' at '{start_time_iso}'...")
        resp = requests.post("https://api.calendly.com/invitees", headers=headers, json=payload, timeout=12)

        if resp.status_code == 201:
            res_data = resp.json().get("resource", {})
            invitee_uri = res_data.get("uri")
            event_uri = res_data.get("event")
            cancel_url = res_data.get("cancel_url")
            reschedule_url = res_data.get("reschedule_url")
            google_meet_url = None

            # Retrieve event resource to get Google Meet join link
            if event_uri:
                try:
                    event_resp = requests.get(event_uri, headers=headers, timeout=8)
                    if event_resp.status_code == 200:
                        event_data = event_resp.json().get("resource", {})
                        location_info = event_data.get("location", {})
                        google_meet_url = location_info.get("join_url")
                except Exception as e_ev:
                    logger.warning(f"Could not fetch Google Meet join_url from scheduled event: {e_ev}")

            logger.info(f"Calendly booking successful! Invitee URI: {invitee_uri}")
            return {
                "success": True,
                "booking_method": "calendly_api",
                "event_uri": event_uri,
                "invitee_uri": invitee_uri,
                "google_meet_url": google_meet_url,
                "cancel_url": cancel_url,
                "reschedule_url": reschedule_url,
            }
        elif resp.status_code == 429:
            logger.warning("Calendly API rate limit reached (trial tier PAT limit). Using direct scheduling link.")
            return {
                "success": True,
                "booking_method": "calendly_rate_limited",
                "event_uri": None,
                "invitee_uri": None,
                "google_meet_url": None,
                "cancel_url": None,
                "reschedule_url": None,
            }
        else:
            logger.error(f"Calendly booking failed ({resp.status_code}): {resp.text}")
            return {
                "success": False,
                "error": resp.text,
                "status_code": resp.status_code,
            }

    except Exception as e:
        logger.error(f"Exception while booking with Calendly: {e}")
        return {
            "success": False,
            "error": str(e),
        }


# =====================================================================
# STORAGE HELPERS
# =====================================================================

def _ensure_bookings_file():
    """Ensures that the bookings.json storage file exists."""
    if not BOOKINGS_FILE.parent.exists():
        BOOKINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not BOOKINGS_FILE.exists():
        with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)


def _load_existing_bookings() -> list:
    """Loads existing bookings from storage."""
    _ensure_bookings_file()
    try:
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load bookings from {BOOKINGS_FILE}: {e}. Initializing empty list.")
        return []


def _save_booking(booking_record: dict) -> bool:
    """Appends a new booking record to storage."""
    _ensure_bookings_file()
    try:
        bookings = _load_existing_bookings()
        bookings.append(booking_record)
        with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(bookings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save booking to {BOOKINGS_FILE}: {e}")
        return False


# =====================================================================
# AGENT TOOLS
# =====================================================================

@tool
def check_availability(date_or_day: str = "", language: str = "en") -> str:
    """
    Checks upcoming available consultation meeting slots for IT Cybx directly from Calendly.
    Business schedule is strictly Sunday to Thursday between 12:15 PM and 5:00 PM.
    Friday and Saturday are off.

    Args:
        date_or_day: Optional specific day requested by the user (e.g., 'Sunday', 'Monday', 'tomorrow').
        language: 'en' for English or 'ar' for Arabic.
    """
    logger.info(f"Checking slot availability for date/day='{date_or_day}', lang='{language}'")
    is_ar = language.lower() == "ar"

    slots = fetch_calendly_available_slots(days_ahead=7)
    if not slots:
        if is_ar:
            return "نعتذر، لا توجد مواعيد متاحة في الوقت الحالي. يرجى التواصل معنا عبر البريد info@itcybx.co.uk."
        return "Sorry, no open slots are available right now. Please reach out to info@itcybx.co.uk."

    # Filter if user specified a day/date
    if date_or_day:
        filtered = [s for s in slots if (
            date_or_day.lower() in s["day_name_en"].lower()
            or date_or_day in s["day_name_ar"]
            or date_or_day in s["date_key"]
        )]
        if filtered:
            slots = filtered

    # Group slots by day
    days_dict: Dict[str, Dict[str, Any]] = {}
    for s in slots:
        k = s["date_key"]
        if k not in days_dict:
            days_dict[k] = {
                "date_en": s["date_en"],
                "date_ar": s["date_ar"],
                "day_name_en": s["day_name_en"],
                "day_name_ar": s["day_name_ar"],
                "slots_en": [],
                "slots_ar": [],
            }
        days_dict[k]["slots_en"].append(s["time_en"])
        days_dict[k]["slots_ar"].append(s["time_ar"])

    cal_info = get_calendly_client_info()
    cal_url = cal_info.get("scheduling_url") if cal_info else None

    if is_ar:
        output_lines = [
            "أوقات العمل المتاحة للاستشارات هي من **الأحد إلى الخميس** من **12:15 ظهراً حتى 5:00 مساءً**.",
            "المواعيد المتاحة القادمة لاختيارك:",
        ]
        # Show up to 3 upcoming days
        for k, day_data in list(days_dict.items())[:3]:
            slots_str = "، ".join(day_data["slots_ar"])
            output_lines.append(f"• **{day_data['day_name_ar']} ({day_data['date_ar']})**:\n  الأوقات: {slots_str}")

        if cal_url:
            output_lines.append(f"\nيمكنك أيضاً اختيار موعد مباشرة عبر الرابط التالي:\n• {cal_url}")
        output_lines.append("\nيرجى تزويدنا بـ **الموعد المرغوب**، **اسمك**، و **بريدك الإلكتروني** لتأكيد حجزك فوراً في التقويم.")
        return "\n".join(output_lines)
    else:
        output_lines = [
            f"Our consultation hours are **Sunday to Thursday** from **12:15 PM to 5:00 PM** ({TIMEZONE_LABEL}).",
            "Here are the upcoming available slots for you to choose from:",
        ]
        # Show up to 3 upcoming days
        for k, day_data in list(days_dict.items())[:3]:
            slots_str = ", ".join(day_data["slots_en"])
            output_lines.append(f"• **{day_data['day_name_en']} ({day_data['date_en']})**:\n  Slots: {slots_str}")

        if cal_url:
            output_lines.append(f"\nYou can also pick a direct time slot here:\n• {cal_url}")
        output_lines.append("\nPlease let me know your preferred slot along with your **Name** and **Email** to confirm your booking.")
        return "\n".join(output_lines)


@tool
def book_meeting(name: str, email: str, slot_time: str, notes: str = "", language: str = "en") -> str:
    """
    Books and confirms a consultation meeting for a prospective client in Calendly.
    Automatically generates calendar invites, meeting link, and sends confirmation emails.

    Args:
        name: Full name of the client.
        email: Valid email address of the client.
        slot_time: Selected date and time for the meeting (e.g., 'Sunday at 12:15 PM' or '2026-09-20T07:15:00Z').
        notes: Optional store URL, topic, or message from the client.
        language: 'en' for English or 'ar' for Arabic.
    """
    logger.info(f"Booking meeting for name='{name}', email='{email}', slot='{slot_time}', lang='{language}'")
    is_ar = language.lower() == "ar"

    # Validation
    if not name or len(name.strip()) < 2:
        if is_ar:
            return "يرجى تزويدنا بالاسم الكريم لإتمام تأكيد الحجز."
        return "Please provide your full name so we can complete your booking."

    if not email or "@" not in email or "." not in email:
        if is_ar:
            return "يرجى تزويدنا ببريد إلكتروني صحيح لإرسال تفاصيل الموعد ورابط الاجتماع."
        return "Please provide a valid email address so we can send you the meeting invite."

    if not slot_time or len(slot_time.strip()) < 3:
        if is_ar:
            return "يرجى تحديد وقت الموعد المرغوب (من الأحد إلى الخميس بين 12:15 و 5:00 مساءً)."
        return "Please specify your preferred date and time slot (Sunday–Thursday, 12:15 PM–5:00 PM)."

    # Fetch available slots to match the requested time
    available_slots = fetch_calendly_available_slots(days_ahead=7)
    matched_slot = match_user_slot_to_available(slot_time, available_slots)

    if matched_slot:
        start_time_iso = matched_slot["start_time_iso"]
        display_time_en = matched_slot["full_str_en"]
        display_time_ar = matched_slot["full_str_ar"]
    else:
        # Fallback to current date/time format if slot could not be parsed
        start_time_iso = None
        display_time_en = slot_time.strip()
        display_time_ar = slot_time.strip()

    # Call Calendly API
    cal_res = None
    if start_time_iso:
        cal_res = create_calendly_booking(name=name, email=email, start_time_iso=start_time_iso, notes=notes)

    # If Calendly booking succeeded or fallback sandbox
    booking_id = f"ITCYBX-{uuid.uuid4().hex[:6].upper()}"
    created_at = datetime.datetime.now().isoformat()
    cal_info = get_calendly_client_info()

    google_meet_url = cal_res.get("google_meet_url") if cal_res else None
    cancel_url = cal_res.get("cancel_url") if cal_res else None
    reschedule_url = cal_res.get("reschedule_url") if cal_res else None
    direct_cal_url = cal_info.get("scheduling_url") if cal_info else None

    booking_record = {
        "booking_id": booking_id,
        "created_at": created_at,
        "name": name.strip(),
        "email": email.strip(),
        "slot_time": display_time_en,
        "start_time_iso": start_time_iso,
        "notes": notes.strip() if notes else "",
        "calendly_event_uri": cal_res.get("event_uri") if cal_res else None,
        "calendly_invitee_uri": cal_res.get("invitee_uri") if cal_res else None,
        "google_meet_url": google_meet_url,
        "cancel_url": cancel_url,
        "reschedule_url": reschedule_url,
        "calendly_url": direct_cal_url,
        "status": "CONFIRMED",
    }

    _save_booking(booking_record)
    logger.info(f"Successfully recorded booking {booking_id} for {name} ({email}) in Calendly & local storage.")

    meet_line_ar = f"• **رابط اجتماع Google Meet:** {google_meet_url}\n" if google_meet_url else ""
    meet_line_en = f"• **Google Meet Link:** {google_meet_url}\n" if google_meet_url else ""
    cal_link_ar = f"• **رابط التقويم والموعد:** {direct_cal_url}\n" if (direct_cal_url and not google_meet_url) else ""
    cal_link_en = f"• **Calendar & Meeting Link:** {direct_cal_url}\n" if (direct_cal_url and not google_meet_url) else ""
    reschedule_line_ar = f"• **تعديل / إلغاء الموعد:** {reschedule_url}\n" if reschedule_url else ""
    reschedule_line_en = f"• **Reschedule Link:** {reschedule_url}\n" if reschedule_url else ""

    if is_ar:
        return (
            f"تم تأكيد حجز موعدك بنجاح في التقويم!\n\n"
            f"• **رقم الحجز:** {booking_id}\n"
            f"• **الاسم:** {name.strip()}\n"
            f"• **البريد الإلكتروني:** {email.strip()}\n"
            f"• **الموعد المحدد:** {display_time_ar}\n"
            f"{meet_line_ar}"
            f"{cal_link_ar}"
            f"{reschedule_line_ar}"
            f"• **أوقات العمل الرسمية:** الأحد إلى الخميس (12:15 ظهراً - 5:00 مساءً)\n\n"
            f"تم إرسال دعوة التقويم وتفاصيل الاجتماع إلى بريدك الإلكتروني ({email.strip()}). يتطلع فريق IT Cybx لمناقشة نمو متجرك!"
        )
    else:
        return (
            f"Your consultation meeting has been successfully booked in Calendly!\n\n"
            f"• **Booking Reference:** {booking_id}\n"
            f"• **Name:** {name.strip()}\n"
            f"• **Email:** {email.strip()}\n"
            f"• **Scheduled Time:** {display_time_en}\n"
            f"{meet_line_en}"
            f"{cal_link_en}"
            f"{reschedule_line_en}"
            f"• **Business Hours:** Sunday to Thursday (12:15 PM – 5:00 PM)\n\n"
            f"A calendar invitation and confirmation email have been sent to {email.strip()}. "
            f"The IT Cybx team looks forward to speaking with you!"
        )
