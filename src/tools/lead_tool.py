# src/tools/lead_tool.py

import json
import uuid
import datetime
import requests
from typing import Optional, Dict, Any, List
from langchain_core.tools import tool

from src.config.settings import LEADS_FILE, SLACK_WEBHOOK_URL
from src.utils.logger import get_logger

logger = get_logger("LeadTool")


def _ensure_leads_file():
    """Ensures data directory and leads.json exist."""
    if not LEADS_FILE.parent.exists():
        LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LEADS_FILE.exists():
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)


def load_all_leads() -> List[Dict[str, Any]]:
    """Loads all captured leads from storage."""
    _ensure_leads_file()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Error reading {LEADS_FILE}: {e}. Returning empty list.")
        return []


def save_lead_record(record: Dict[str, Any]) -> bool:
    """Appends a new lead record to leads.json."""
    _ensure_leads_file()
    try:
        leads = load_all_leads()
        leads.append(record)
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump(leads, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save lead record: {e}")
        return False


def notify_slack_lead(lead_record: Dict[str, Any]):
    """Sends a Slack notification for a new captured lead if configured."""
    if not SLACK_WEBHOOK_URL:
        return

    try:
        payload = {
            "text": f"🚀 *New High-Intent Lead Captured!* [{lead_record['lead_id']}]",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "🌟 New Lead Received - IT Cybx Live Bot"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Name:*\n{lead_record.get('name', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Email:*\n{lead_record.get('email', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Phone / WhatsApp:*\n{lead_record.get('phone', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Store / Brand:*\n{lead_record.get('store_url_or_name', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Platform:*\n{lead_record.get('platform', 'N/A')}"},
                        {"type": "mrkdwn", "text": f"*Service Interest:*\n{lead_record.get('service_interest', 'N/A')}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Notes & Requirements:*\n{lead_record.get('notes', 'None provided')}"}
                }
            ]
        }
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=6)
        if resp.status_code == 200:
            logger.info(f"Slack notification sent for lead {lead_record['lead_id']}")
        else:
            logger.warning(f"Slack webhook returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Failed to send Slack webhook for lead: {e}")


@tool
def capture_lead(
    name: str,
    email: str,
    phone: str = "",
    store_url_or_name: str = "",
    platform: str = "",
    service_interest: str = "",
    notes: str = "",
    language: str = "en"
) -> str:
    """
    Captures visitor contact information, brand/store details, and growth interests
    so the IT Cybx team can review and follow up with a tailored proposal.

    Args:
        name: Full name of the client or brand owner.
        email: Valid email address.
        phone: Optional phone or WhatsApp number.
        store_url_or_name: Optional store URL or brand name (e.g. 'mystore.com').
        platform: Optional e-commerce platform (e.g. 'Shopify', 'Salla', 'Zid', 'WooCommerce').
        service_interest: Service they want (e.g. 'The Growth Audit', 'Shopify Store Build', 'CRO Sprint', 'Growth Marketing').
        notes: Specific goals, current monthly revenue, or questions.
        language: 'en' for English, 'ar' for Arabic.

    Returns:
        Formatted confirmation message for the user.
    """
    logger.info(f"Tool capture_lead called: name='{name}', email='{email}', interest='{service_interest}', lang='{language}'")
    is_ar = language.lower() == "ar"

    # Input validation
    clean_name = name.strip() if name else ""
    clean_email = email.strip() if email else ""

    if not clean_name or len(clean_name) < 2:
        if is_ar:
            return "يرجى تزويدنا بالاسم الكريم لنتمكن من تسجيل استفسارك ومتابعتك."
        return "Please provide your full name so our growth team can connect with you."

    if not clean_email or "@" not in clean_email or "." not in clean_email:
        if is_ar:
            return "يرجى تزويدنا ببريد إلكتروني صحيح لنتمكن من إرسال تفاصيل الخطة والعرض المناسب لمتجرك."
        return "Please provide a valid email address so we can send you our review and proposals."

    lead_id = f"LEAD-{uuid.uuid4().hex[:6].upper()}"
    timestamp = datetime.datetime.now().isoformat()

    lead_record = {
        "lead_id": lead_id,
        "created_at": timestamp,
        "name": clean_name,
        "email": clean_email,
        "phone": phone.strip() if phone else "",
        "store_url_or_name": store_url_or_name.strip() if store_url_or_name else "",
        "platform": platform.strip() if platform else "",
        "service_interest": service_interest.strip() if service_interest else "General Growth Inquiry",
        "notes": notes.strip() if notes else "",
        "language": "ar" if is_ar else "en",
        "status": "NEW",
    }

    # Save to storage
    save_lead_record(lead_record)
    logger.info(f"Saved lead {lead_id} for {clean_name} ({clean_email})")

    # Send Slack notification if webhook is configured
    notify_slack_lead(lead_record)

    # Format localized confirmation
    if is_ar:
        return (
            f"تم استلام تفاصيل استفسارك بنجاح!\n\n"
            f"• **رقم المرجع:** {lead_id}\n"
            f"• **الاسم:** {clean_name}\n"
            f"• **البريد الإلكتروني:** {clean_email}\n"
            + (f"• **رقم التواصل / واتساب:** {phone.strip()}\n" if phone else "")
            + (f"• **المتجر / العلامة التجارية:** {store_url_or_name.strip()}\n" if store_url_or_name else "")
            + (f"• **المنصة:** {platform.strip()}\n" if platform else "")
            + (f"• **الخدمة المطلوبة:** {service_interest.strip()}\n" if service_interest else "")
            + f"\nيقوم فريق **IT Cybx** بمراجعة تفاصيل متجرك حالياً وسنتواصل معك عبر البريد الإلكتروني خلال 24 ساعة لتقديم الخطة المناسبة لنمو متجرك."
        )
    else:
        return (
            f"Thank you! Your growth inquiry has been successfully received.\n\n"
            f"• **Reference ID:** {lead_id}\n"
            f"• **Name:** {clean_name}\n"
            f"• **Email:** {clean_email}\n"
            + (f"• **Phone / WhatsApp:** {phone.strip()}\n" if phone else "")
            + (f"• **Store / Brand:** {store_url_or_name.strip()}\n" if store_url_or_name else "")
            + (f"• **Platform:** {platform.strip()}\n" if platform else "")
            + (f"• **Service Interest:** {service_interest.strip()}\n" if service_interest else "")
            + f"\nThe **IT Cybx** growth team will review your requirements and follow up via email within 24 hours with tailored recommendations."
        )


if __name__ == "__main__":
    test_res = capture_lead.invoke({
        "name": "Sarah Jenkins",
        "email": "sarah@beautyco.co.uk",
        "phone": "+44 791 234 5678",
        "store_url_or_name": "beautyco.co.uk",
        "platform": "Shopify",
        "service_interest": "The Growth Audit ($150)",
        "notes": "Looking to improve checkout conversion rate in Q4",
        "language": "en"
    })
    print("\n=======================================================")
    print("             LEAD CAPTURE TOOL TEST                    ")
    print("=======================================================")
    print(test_res + "\n")
