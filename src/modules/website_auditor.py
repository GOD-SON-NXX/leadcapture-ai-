"""
LeadCapture AI — MODULE 2: Website Auditor
Scrapes business websites, scores them on lead-capture readiness,
and sends HTML audit emails via Resend API.
"""

import re
import time
import uuid
from datetime import datetime
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from src.config import settings, logger
from src.database.connection import execute_query, execute_write
from src.modules.email_sequences import send_email


# Chatbot scripts to look for (case-insensitive)
CHATBOT_PATTERNS = [
    "botpress", "voiceflow", "tidio", "tawk.to", "intercom",
    "drift", "hubspot", "zendesk", "olark", "crisp",
    "livechat", "freshchat", "chatbot", "chatwoot",
    "manychat", "chatfuel", "landbot", "collect.chat",
    "website.chat", "getbutton.io", "smartsupp",
    "messenger", "whatsapp", "fb('messenger')",
    "fbq('init')",  # Facebook pixel
]

# Common contact form indicators
CONTACT_FORM_PATTERNS = [
    r'<form.*?action=.*?(contact|quote|estimate|appointment|schedule|book|request)',
    r'<input.*?name=.*?(email|phone|message|contact|name)',
    r'<textarea.*?name=.*?(message|details|description)',
    r'(contact|get.*?quote|free.*?estimate|book.*?now|schedule)',
]

# CTA indicators
CTA_PATTERNS = [
    r'(call now|call us|book now|schedule|get.*?quote|free.*?estimate|contact us|request.*?service)',
]


def _fetch_website(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a website's HTML content with retry logic."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    max_retries = 2
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LeadCaptureAI/1.0)"})
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            logger.warning("HTTP %d for %s (attempt %d/%d)", e.response.status_code, url, attempt + 1, max_retries)
        except httpx.RequestError as e:
            logger.warning("Request failed for %s: %s (attempt %d/%d)", url, e, attempt + 1, max_retries)

        if attempt < max_retries - 1:
            time.sleep(2)

    return None


def _check_has_chatbot(html: str) -> bool:
    """Check if website has a chatbot script embedded."""
    html_lower = html.lower()
    for pattern in CHATBOT_PATTERNS:
        if pattern.lower() in html_lower:
            return True
    return False


def _check_has_contact_form(html: str) -> bool:
    """Check if website has a contact form."""
    html_lower = html.lower()
    for pattern in CONTACT_FORM_PATTERNS:
        if re.search(pattern, html_lower):
            return True
    return False


def _check_has_phone_clickable(html: str) -> bool:
    """Check if phone number is clickable (tel: link)."""
    return bool(re.search(r'tel:\+?\d{7,}', html))


def _estimate_page_load_time(html: str) -> float:
    """
    Rough estimate of page load time based on content size and script count.
    Returns a simulated load time in seconds (1.0 = fast, 5.0 = slow).
    """
    if not html:
        return 5.0

    size_mb = len(html) / (1024 * 1024)
    script_count = html.count("<script")
    image_count = html.count("<img")

    # Rough heuristic: bigger pages with more scripts/images load slower
    est_time = 1.0 + (size_mb * 0.5) + (script_count * 0.05) + (image_count * 0.03)
    return min(round(est_time, 2), 10.0)


def calculate_score(html: str) -> dict:
    """
    Calculate lead-capture readiness score (0-100).
    Higher score = worse (more room for improvement).

    Deductions:
    - Has chatbot: -0 points (good!) No chatbot: -30 points
    - Page load > 3s: -20 points
    - No contact form: -25 points
    - No clickable phone: -15 points
    - No clear CTA: -10 points
    """
    deductions = 0
    details = {}

    # 1. Chatbot check
    has_chatbot = _check_has_chatbot(html)
    if not has_chatbot:
        deductions += 30
        details["missing_chatbot"] = True
    else:
        details["has_chatbot"] = True

    # 2. Page load speed
    load_time = _estimate_page_load_time(html)
    if load_time > 3.0:
        deductions += 20
        details["slow_page"] = {"load_time": load_time}
    if load_time < 1.5:
        deductions -= 5  # bonus for fast loading

    # 3. Contact form
    has_contact_form = _check_has_contact_form(html)
    if not has_contact_form:
        deductions += 25
        details["missing_contact_form"] = True
    else:
        details["has_contact_form"] = True

    # 4. Clickable phone
    has_phone_clickable = _check_has_phone_clickable(html)
    if not has_phone_clickable:
        deductions += 15
        details["missing_clickable_phone"] = True
    else:
        details["has_clickable_phone"] = True

    # 5. CTA check
    html_lower = html.lower()
    has_cta = bool(re.search(r'(call now|book now|get.*?quote|free.*?estimate|schedule now)', html_lower))
    if not has_cta:
        deductions += 10
        details["missing_cta"] = True
    else:
        details["has_cta"] = True

    score = max(0, 100 - deductions)
    return {
        "score": score,
        "load_time": load_time,
        "has_chatbot": has_chatbot,
        "has_contact_form": has_contact_form,
        "has_phone_clickable": has_phone_clickable,
        "has_cta": has_cta,
        "details": details,
    }


def generate_audit_email_html(lead: dict, audit: dict) -> str:
    """Generate an HTML email with audit score and CTA."""
    score = audit["score"]
    score_color = "green" if score >= 70 else ("orange" if score >= 40 else "red")
    score_label = "Good" if score >= 70 else ("Needs Work" if score >= 40 else "Poor")

    issues = []
    if not audit["has_chatbot"]:
        issues.append("<li>❌ <strong>No chatbot</strong> — You're missing leads who visit outside business hours</li>")
    if audit["load_time"] > 3:
        issues.append(f"⚠️ <strong>Slow page load</strong> ({audit['load_time']}s) — Visitors may leave before seeing your content</li>")
    if not audit["has_contact_form"]:
        issues.append("❌ <strong>No contact form</strong> — Makes it harder for customers to reach you</li>")
    if not audit["has_phone_clickable"]:
        issues.append("⚠️ <strong>Phone not clickable</strong> — Mobile users can't tap to call</li>")
    if not audit["has_cta"]:
        issues.append("⚠️ <strong>No clear call-to-action</strong> — Visitors don't know what to do next</li>")

    if not issues:
        issues.append("<li>✅ Your website looks good! Let's make it even better.</li>")

    tracking_id = str(uuid.uuid4())
    pixel_url = f"{settings.APP_URL}/api/track/open/{tracking_id}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #2563eb;">LeadCapture AI</h1>
        <p>Website Audit Report for <strong>{lead['business_name']}</strong></p>
    </div>

    <div style="background: #f8fafc; border-radius: 12px; padding: 25px; margin-bottom: 25px; text-align: center;">
        <h2 style="margin: 0; color: {score_color};">Score: {score}/100</h2>
        <p style="color: #64748b;">{score_label}</p>
    </div>

    <h3>Issues Found:</h3>
    <ul style="line-height: 1.8; padding-left: 20px;">
        {''.join(issues)}
    </ul>

    <h3>How LeadCapture AI Can Help:</h3>
    <ul style="line-height: 1.8;">
        <li>🤖 <strong>24/7 Chatbot</strong> — Never miss a lead, even after hours</li>
        <li>📋 <strong>Smart Lead Capture</strong> — Collect name, phone, and service needs automatically</li>
        <li>📊 <strong>Dashboard</strong> — See every conversation and lead in real-time</li>
        <li>💲 <strong>Free 7-Day Pilot</strong> — No credit card required</li>
    </ul>

    <div style="text-align: center; margin: 30px 0;">
        <a href="{settings.APP_URL}/api/track/click/{tracking_id}?redirect=/pilot/signup?lead_id={lead['id']}"
           style="background: #2563eb; color: white; padding: 14px 32px; border-radius: 8px;
                  text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">
            🚀 Start Free Pilot →
        </a>
    </div>

    <p style="color: #94a3b8; font-size: 12px; text-align: center;">
        If you'd rather not receive these reports, <a href="{settings.APP_URL}/api/track/unsubscribe/{tracking_id}">unsubscribe here</a>.
    </p>

    <img src="{pixel_url}" width="1" height="1" alt="" style="display:none;"/>
</body>
</html>"""
    return html, tracking_id


def audit_website(lead: dict) -> Optional[dict]:
    """
    Full audit pipeline: fetch website -> score -> send email -> store results.
    Returns the audit dict or None on failure.
    """
    logger.info("Auditing website for %s (%s)", lead["business_name"], lead["website"])

    website = lead.get("website", "")
    if not website:
        logger.warning("No website for lead %s, skipping audit", lead["business_name"])
        return None

    html = _fetch_website(website)
    if not html:
        logger.warning("Could not fetch website for %s", lead["business_name"])
        return None

    audit = calculate_score(html)

    # Generate and send email
    email_html, tracking_id = generate_audit_email_html(lead, audit)
    lead_email = lead.get("email", "")
    owner_email = lead.get("owner_email", "")

    # Send to the best available email
    recipient = owner_email or lead_email
    if recipient:
        try:
            send_email(
                to=recipient,
                subject=f"Website Audit Report for {lead['business_name']} — Score: {audit['score']}/100",
                html_body=email_html,
                tracking_id=tracking_id,
            )
            audit["email_sent"] = True
        except Exception as e:
            logger.error("Failed to send audit email to %s: %s", recipient, e)
            audit["email_sent"] = False
    else:
        # No email available — we'll generate a tracking ID anyway for potential future use
        audit["email_sent"] = False
        logger.info("No email address for %s, storing audit without sending", lead["business_name"])

    # Store audit in database
    try:
        audit_id = execute_write(
            """INSERT INTO audits (lead_id, score, email_sent_at, email_html)
               VALUES (?, ?, ?, ?)""",
            (lead["id"], audit["score"], datetime.utcnow().isoformat() if audit.get("email_sent") else None, email_html),
        )
        audit["audit_id"] = audit_id

        # Update lead status to 'audited'
        execute_write(
            "UPDATE leads SET status = 'audited', score = ?, has_chatbot = ?, updated_at = ? WHERE id = ?",
            (audit["score"], 1 if audit["has_chatbot"] else 0, datetime.utcnow().isoformat(), lead["id"]),
        )
    except Exception as e:
        logger.error("Failed to store audit for lead %s: %s", lead["business_name"], e)

    return audit


def run_batch_audit(limit: int = 10) -> dict:
    """
    Run audits on 'fresh' leads that haven't been audited yet.
    """
    logger.info("=" * 50)
    logger.info("BATCH AUDIT RUN — Processing up to %d leads", limit)
    logger.info("=" * 50)

    leads = execute_query(
        "SELECT * FROM leads WHERE status = 'fresh' AND website IS NOT NULL AND website != '' LIMIT ?",
        (limit,),
    )

    results = {"processed": 0, "success": 0, "failed": 0}
    for lead in leads:
        try:
            result = audit_website(lead)
            if result:
                results["success"] += 1
            else:
                results["failed"] += 1
            results["processed"] += 1
        except Exception as e:
            logger.error("Audit failed for %s: %s", lead["business_name"], e)
            results["failed"] += 1

        # Be polite to target websites
        time.sleep(3)

    logger.info("Batch audit complete: %s", results)
    return results
