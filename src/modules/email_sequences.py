"""
LeadCapture AI — MODULE 6: Email Sequences
Handles all email sending via Resend API or SMTP fallback.
Manages templates, tracking (open/click pixels), and sequencing.
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional
import httpx
from src.config import settings, logger
from src.database.connection import execute_query, execute_write


def _get_resend_headers() -> dict:
    """Get headers for Resend API calls."""
    return {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }


def send_email_via_resend(to: str, subject: str, html_body: str) -> bool:
    """Send email via Resend API."""
    if not settings.RESEND_API_KEY:
        logger.error("RESEND_API_KEY not set. Cannot send email.")
        return False

    url = "https://api.resend.com/emails"
    payload = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html_body,
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload, headers=_get_resend_headers())
            resp.raise_for_status()
            result = resp.json()
            logger.info("Email sent to %s | subject: %s | id: %s", to, subject, result.get("id", "unknown"))
            return True
    except httpx.HTTPStatusError as e:
        logger.error("Resend API error %d: %s", e.response.status_code, e.response.text)
    except httpx.RequestError as e:
        logger.error("Resend request error: %s", e)

    return False


def send_email(
    to: str,
    subject: str,
    html_body: str,
    tracking_id: Optional[str] = None,
    business_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    template_name: str = "generic",
) -> bool:
    """
    Send an email with tracking pixel support.
    Returns True if sent successfully.
    """
    sent = send_email_via_resend(to, subject, html_body)

    # Track the email send
    if sent and tracking_id:
        try:
            execute_write(
                """INSERT INTO emails (business_id, lead_id, template_name, recipient_email, tracking_id, sent_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (business_id, lead_id, template_name, to, tracking_id, datetime.utcnow().isoformat()),
            )
        except Exception as e:
            logger.warning("Failed to track email send: %s", e)

    return sent


def render_template(template_name: str, variables: dict) -> str:
    """
    Render an email template with variables substituted.
    Variables use {{variable_name}} syntax.
    """
    templates = {
        "audit_initial": _template_audit_initial,
        "audit_followup": _template_audit_followup,
        "audit_final": _template_audit_final,
        "pilot_welcome": _template_pilot_welcome,
        "pilot_day3_value": _template_pilot_day3_value,
        "pilot_day5_invoice": _template_pilot_day5_invoice,
        "pilot_day6_reminder": _template_pilot_day6_reminder,
        "pilot_day7_decision": _template_pilot_day7_decision,
        "billing_reminder": _template_billing_reminder,
        "billing_due": _template_billing_due,
        "billing_overdue": _template_billing_overdue,
        "activation_welcome": _template_activation_welcome,
        "deactivation_notice": _template_deactivation_notice,
    }

    template_fn = templates.get(template_name)
    if not template_fn:
        logger.warning("Unknown template: %s, using generic", template_name)
        return _template_generic(variables)

    return template_fn(variables)


def _wrap_html(body: str, unsubscribe_url: str = "") -> str:
    """Wrap body content in standard email layout."""
    unsub = ""
    if unsubscribe_url:
        unsub = f'<p style="color: #94a3b8; font-size: 12px; text-align: center; margin-top: 30px;">If you\'d rather not receive these emails, <a href="{unsubscribe_url}" style="color: #94a3b8;">unsubscribe here</a>.</p>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #2563eb; font-size: 24px;">{settings.APP_NAME}</h1>
    </div>
    {body}
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
    <p style="color: #94a3b8; font-size: 12px; text-align: center;">
        {settings.APP_NAME} — Automated Lead Capture for Local Service Businesses
    </p>
    {unsub}
</body>
</html>"""


def _template_generic(v: dict) -> str:
    body = v.get("body", "")
    return _wrap_html(f"<div>{body}</div>")


def _template_audit_initial(v: dict) -> str:
    score = v.get("score", 0)
    biz = v.get("business_name", "your business")
    score_color = "green" if score >= 70 else ("orange" if score >= 40 else "red")
    pilot_url = f"{settings.APP_URL}/pilot/signup?lead_id={v.get('lead_id', '')}"
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <div style="background: #f8fafc; border-radius: 12px; padding: 25px; margin-bottom: 25px; text-align: center;">
        <h2 style="margin: 0; color: {score_color};">Website Audit Score: {score}/100</h2>
        <p style="color: #64748b;">For {biz}</p>
    </div>

    <p>Hi there,</p>
    <p>We've analyzed your website and found <strong>opportunities to capture more leads</strong>. Your current lead capture score is <strong>{score}/100</strong>.</p>

    <p>Here's what we found:</p>
    <ul style="line-height: 1.8;">
        {"<li>❌ No chatbot — missing leads after hours</li>" if score < 70 else ""}
        {"<li>⚠️ Slow page speed — visitors may leave</li>" if v.get("slow_page") else ""}
        {"<li>✅ You have a contact form — great!</li>" if v.get("has_contact_form") else "❌ No contact form detected"}
    </ul>

    <div style="text-align: center; margin: 30px 0;">
        <a href="{pilot_url}&tracking={tracking_id}"
           style="background: #2563eb; color: white; padding: 14px 32px; border-radius: 8px;
                  text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">
            🚀 Start Free 7-Day Pilot →
        </a>
    </div>
    """
    return _wrap_html(body, unsubscribe_url=f"{settings.APP_URL}/api/track/unsubscribe/{tracking_id}")


def _template_audit_followup(v: dict) -> str:
    biz = v.get("business_name", "your business")
    pilot_url = f"{settings.APP_URL}/pilot/signup?lead_id={v.get('lead_id', '')}"
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <p>Hi there,</p>
    <p>I wanted to follow up on our website audit for <strong>{biz}</strong>.</p>

    <p>Our AI chatbot can help you:</p>
    <ul style="line-height: 1.8;">
        <li>🤖 Answer customer questions 24/7</li>
        <li>📞 Capture name, phone, and service needs automatically</li>
        <li>📊 Track every lead in a simple dashboard</li>
        <li>💲 Only $97/month after a free 7-day trial</li>
    </ul>

    <div style="text-align: center; margin: 30px 0;">
        <a href="{pilot_url}&tracking={tracking_id}"
           style="background: #2563eb; color: white; padding: 14px 32px; border-radius: 8px;
                  text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">
            🚀 Start Your Free Pilot →
        </a>
    </div>
    """
    return _wrap_html(body, unsubscribe_url=f"{settings.APP_URL}/api/track/unsubscribe/{tracking_id}")


def _template_audit_final(v: dict) -> str:
    biz = v.get("business_name", "your business")
    pilot_url = f"{settings.APP_URL}/pilot/signup?lead_id={v.get('lead_id', '')}"
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <p>Hi there,</p>
    <p>This is our final follow-up regarding the website audit for <strong>{biz}</strong>.</p>

    <p>Our free 7-day pilot offer is still available. You'll get:</p>
    <ul style="line-height: 1.8;">
        <li>✅ A custom AI chatbot for your website</li>
        <li>✅ Real-time lead capture and notifications</li>
        <li>✅ Full dashboard with conversation logs</li>
        <li>✅ No credit card required</li>
    </ul>

    <p>After 7 days, <strong>it's just ${settings.MONTHLY_PRICE}/month</strong> with no long-term contract.</p>

    <div style="text-align: center; margin: 30px 0;">
        <a href="{pilot_url}&tracking={tracking_id}"
           style="background: #2563eb; color: white; padding: 14px 32px; border-radius: 8px;
                  text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">
            🚀 Claim Your Free Pilot →
        </a>
    </div>
    """
    return _wrap_html(body, unsubscribe_url=f"{settings.APP_URL}/api/track/unsubscribe/{tracking_id}")


def _template_pilot_welcome(v: dict) -> str:
    biz = v.get("business_name", "your business")
    dashboard_url = f"{settings.APP_URL}/dashboard/{v.get('business_id', '')}"
    embed_code = v.get("embed_code", "")
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <p>Welcome to {settings.APP_NAME}, <strong>{v.get('owner_name', 'there')}</strong>!</p>

    <p>Your 7-day free pilot for <strong>{biz}</strong> is now active. Here's everything you need to know:</p>

    <h3>📋 Step 1: Install Your Chatbot</h3>
    <p>Add this snippet to your website (just before the closing &lt;/body&gt; tag):</p>
    <pre style="background: #1e293b; color: #e2e8f0; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 13px;">{embed_code}</pre>

    <h3>📊 Step 2: View Your Dashboard</h3>
    <p>See your conversations, leads captured, and pilot status:</p>
    <div style="text-align: center; margin: 15px 0;">
        <a href="{dashboard_url}&tracking={tracking_id}"
           style="background: #2563eb; color: white; padding: 12px 28px; border-radius: 8px;
                  text-decoration: none; font-weight: bold; display: inline-block;">
            📊 Open Dashboard →
        </a>
    </div>

    <h3>💡 Tips for Success</h3>
    <ul style="line-height: 1.8;">
        <li>Test the chatbot on your own website</li>
        <li>Set your business hours and services in the dashboard</li>
        <li>You'll get daily summary emails with lead activity</li>
    </ul>

    <p>Questions? Reply to this email and we'll help you get set up.</p>
    """
    return _wrap_html(body)


def _template_pilot_day3_value(v: dict) -> str:
    biz = v.get("business_name", "your business")
    conv_count = v.get("conversations_count", 0)
    dashboard_url = f"{settings.APP_URL}/dashboard/{v.get('business_id', '')}"
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your {settings.APP_NAME} pilot for <strong>{biz}</strong> is going strong!</p>

    <h3>📊 Pilot Progress — Day 3</h3>
    <div style="background: #f0fdf4; border-radius: 12px; padding: 20px; margin: 15px 0;">
        <p style="font-size: 18px; text-align: center;">
            <strong>Conversations captured: {conv_count}</strong>
        </p>
    </div>

    <p>You've already captured <strong>{conv_count} conversations</strong> through your chatbot. Each one represents a potential customer who visited your website.</p>

    <div style="text-align: center; margin: 25px 0;">
        <a href="{dashboard_url}&tracking={tracking_id}"
           style="background: #2563eb; color: white; padding: 12px 28px; border-radius: 8px;
                  text-decoration: none; font-weight: bold; display: inline-block;">
            📊 View Conversations →
        </a>
    </div>

    <p>On <strong>Day 5</strong>, we'll send you the invoice info if you'd like to continue after the trial. No pressure!</p>
    """
    return _wrap_html(body)


def _template_pilot_day5_invoice(v: dict) -> str:
    biz = v.get("business_name", "your business")
    tracking_id = v.get("tracking_id", "")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your 7-day free pilot for <strong>{biz}</strong> is almost complete!</p>

    <h3>💲 Continue for ${settings.MONTHLY_PRICE}/Month</h3>
    <p>To keep your chatbot active after the trial, send <strong>${settings.MONTHLY_PRICE}</strong> via Wise to:</p>

    <div style="background: #f8fafc; border-radius: 12px; padding: 20px; margin: 15px 0;">
        <p><strong>Account Name:</strong> {settings.WISE_ACCOUNT_NAME}</p>
        <p><strong>Account Number:</strong> {settings.WISE_ACCOUNT_NUMBER}</p>
        <p><strong>Routing Number:</strong> {settings.WISE_ROUTING_NUMBER}</p>
        <p><strong>Email:</strong> {settings.WISE_EMAIL}</p>
        <p style="margin-top: 10px;"><em>Reference: Please include your business name so we can match the payment.</em></p>
    </div>

    <p>Once we receive payment, your account will be upgraded immediately and your chatbot stays active.</p>

    <p>Your trial ends in <strong>2 days</strong> (Day 7). If you decide not to continue, your chatbot will be paused and we'll keep your data for 30 days in case you come back.</p>
    """
    return _wrap_html(body)


def _template_pilot_day6_reminder(v: dict) -> str:
    biz = v.get("business_name", "your business")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Quick reminder — your <strong>{settings.APP_NAME}</strong> pilot for <strong>{biz}</strong> ends <strong>tomorrow</strong>!</p>

    <h3>⏰ Trial Ends Tomorrow</h3>
    <p>Send <strong>${settings.MONTHLY_PRICE}</strong> via Wise to keep your chatbot active:</p>

    <div style="background: #f8fafc; border-radius: 12px; padding: 20px; margin: 15px 0;">
        <p><strong>{settings.WISE_ACCOUNT_NAME}</strong></p>
        <p>Account: {settings.WISE_ACCOUNT_NUMBER}</p>
        <p>Routing: {settings.WISE_ROUTING_NUMBER}</p>
        <p>Email: {settings.WISE_EMAIL}</p>
    </div>

    <p>Or if you have questions, just reply to this email!</p>
    """
    return _wrap_html(body)


def _template_pilot_day7_decision(v: dict) -> str:
    biz = v.get("business_name", "your business")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your 7-day free pilot for <strong>{biz}</strong> has ended.</p>

    <p>If you've sent payment, we'll activate your account as soon as we receive it — usually within 24 hours.</p>

    <p>If you haven't yet, your chatbot is now paused. Don't worry — you can reactivate anytime by sending payment and emailing us.</p>

    <div style="background: #f8fafc; border-radius: 12px; padding: 20px; margin: 15px 0; text-align: center;">
        <p><strong>Reactivate by sending ${settings.MONTHLY_PRICE} via Wise:</strong></p>
        <p>{settings.WISE_ACCOUNT_NAME} | {settings.WISE_ACCOUNT_NUMBER}</p>
        <p>{settings.WISE_EMAIL}</p>
    </div>

    <p>We'll keep your data for 30 days. Thanks for trying {settings.APP_NAME}!</p>
    """
    return _wrap_html(body)


def _template_billing_reminder(v: dict) -> str:
    biz = v.get("business_name", "your business")
    due_date = v.get("due_date", "end of month")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>This is a friendly reminder that your <strong>{settings.APP_NAME}</strong> subscription for <strong>{biz}</strong> is due on <strong>{due_date}</strong>.</p>

    <div style="background: #f8fafc; border-radius: 12px; padding: 20px; margin: 15px 0; text-align: center;">
        <p><strong>Amount Due: ${settings.MONTHLY_PRICE}</strong></p>
        <p>Send via Wise to:</p>
        <p>{settings.WISE_ACCOUNT_NAME} | {settings.WISE_ACCOUNT_NUMBER}</p>
    </div>

    <p>Please include your business name as the payment reference.</p>
    """
    return _wrap_html(body)


def _template_billing_due(v: dict) -> str:
    biz = v.get("business_name", "your business")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your <strong>{settings.APP_NAME}</strong> subscription for <strong>{biz}</strong> is now due.</p>

    <div style="background: #fef2f2; border-radius: 12px; padding: 20px; margin: 15px 0; text-align: center;">
        <p><strong style="color: #dc2626;">Amount Due: ${settings.MONTHLY_PRICE}</strong></p>
        <p>Please send via Wise immediately to avoid service interruption.</p>
        <p>{settings.WISE_ACCOUNT_NAME} | {settings.WISE_ACCOUNT_NUMBER}</p>
        <p>{settings.WISE_EMAIL}</p>
    </div>

    <p>You have a <strong>3-day grace period</strong> before your chatbot is paused.</p>
    """
    return _wrap_html(body)


def _template_billing_overdue(v: dict) -> str:
    biz = v.get("business_name", "your business")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your <strong>{settings.APP_NAME}</strong> subscription for <strong>{biz}</strong> is now overdue.</p>

    <div style="background: #fef2f2; border-radius: 12px; padding: 20px; margin: 15px 0; text-align: center;">
        <p><strong style="color: #dc2626;">Your chatbot has been paused</strong></p>
        <p>To reactivate, send <strong>${settings.MONTHLY_PRICE}</strong> via Wise:</p>
        <p>{settings.WISE_ACCOUNT_NAME} | {settings.WISE_ACCOUNT_NUMBER}</p>
    </div>

    <p>Once we receive payment, we'll reactivate your chatbot within 24 hours. Your data is safe.</p>

    <p><a href="{settings.APP_URL}/reactivate?business_id={v.get('business_id', '')}" style="color: #2563eb;">Click here to reactivate</a></p>
    """
    return _wrap_html(body)


def _template_activation_welcome(v: dict) -> str:
    biz = v.get("business_name", "your business")
    dashboard_url = f"{settings.APP_URL}/dashboard/{v.get('business_id', '')}"

    body = f"""
    <p>Congratulations, <strong>{v.get('owner_name', 'there')}</strong>!</p>
    <p>Your <strong>{settings.APP_NAME}</strong> subscription for <strong>{biz}</strong> is now <strong>active</strong>.</p>

    <h3>✅ What's Next?</h3>
    <ul style="line-height: 1.8;">
        <li>Your chatbot is running and capturing leads</li>
        <li>Check your dashboard for new conversations</li>
        <li>Your monthly billing date is: <strong>{v.get('monthly_due_date', 'TBD')}</strong></li>
    </ul>

    <div style="text-align: center; margin: 25px 0;">
        <a href="{dashboard_url}"
           style="background: #2563eb; color: white; padding: 12px 28px; border-radius: 8px;
                  text-decoration: none; font-weight: bold; display: inline-block;">
            📊 Go to Dashboard →
        </a>
    </div>

    <p>Thanks for choosing {settings.APP_NAME}!</p>
    """
    return _wrap_html(body)


def _template_deactivation_notice(v: dict) -> str:
    biz = v.get("business_name", "your business")

    body = f"""
    <p>Hi <strong>{v.get('owner_name', 'there')}</strong>,</p>
    <p>Your <strong>{settings.APP_NAME}</strong> subscription for <strong>{biz}</strong> has been deactivated due to non-payment.</p>

    <p>Don't worry — we've kept all your data. You can reactivate anytime.</p>

    <div style="text-align: center; margin: 25px 0;">
        <a href="{settings.APP_URL}/reactivate?business_id={v.get('business_id', '')}"
           style="background: #2563eb; color: white; padding: 14px 32px; border-radius: 8px;
                  text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">
            🔄 Reactivate Now →
        </a>
    </div>
    """
    return _wrap_html(body)


def send_sequence_email(
    template_name: str,
    variables: dict,
    to: str,
    subject: str,
    business_id: Optional[int] = None,
    lead_id: Optional[int] = None,
) -> bool:
    """Render, track, and send a sequence email in one call."""
    tracking_id = str(uuid.uuid4())
    variables["tracking_id"] = tracking_id

    html_body = render_template(template_name, variables)

    return send_email(
        to=to,
        subject=subject,
        html_body=html_body,
        tracking_id=tracking_id,
        business_id=business_id,
        lead_id=lead_id,
        template_name=template_name,
    )
