"""
LeadCapture AI — Main Application Entry Point
FastAPI server with all module routes, scheduling, and static file serving.
"""

import json
import os
import uuid
from datetime import datetime, date
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings, logger
from src.database.connection import init_db, execute_query, execute_write

# Import modules
from src.modules import lead_finder
from src.modules import website_auditor
from src.modules import chatbot_engine
from src.modules import pilot_manager
from src.modules import payment_handler
from src.modules import email_sequences
from src.modules import admin_dashboard


# ---- Request Models ----
class LeadSearchRequest(BaseModel):
    city: str
    state: str
    radius_meters: int = 50000


class ChatStartRequest(BaseModel):
    business_id: int


class ChatMessageRequest(BaseModel):
    conversation_id: int
    business_id: int
    message: str


class PilotSignupRequest(BaseModel):
    lead_id: int
    owner_name: str
    owner_email: str
    services: str = ""
    hours: str = "Monday-Friday, 8am-6pm"
    phone: str = ""


class PaymentRecordRequest(BaseModel):
    business_id: int
    amount: float
    wise_reference: str = ""


class BusinessUpdateRequest(BaseModel):
    services: str = None
    hours: str = None
    phone: str = None
    owner_email: str = None
    owner_name: str = None


# ---- App Lifecycle ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("=" * 50)
    logger.info("%s starting up...", settings.APP_NAME)
    logger.info("=" * 50)

    # Initialize database
    init_db()

    # Schedule background jobs
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()

    # Daily pilot checks at 8 AM
    scheduler.add_job(
        pilot_manager.run_daily_pilot_checks,
        "cron",
        hour=8,
        minute=0,
        id="daily_pilot_checks",
        replace_existing=True,
    )

    # Daily batch audit at 9 AM
    scheduler.add_job(
        website_auditor.run_batch_audit,
        "cron",
        hour=9,
        minute=0,
        kwargs={"limit": 5},
        id="daily_batch_audit",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started.")
    logger.info("%s is ready!", settings.APP_NAME)

    yield

    scheduler.shutdown()
    logger.info("Shutting down %s.", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Verify database is accessible
        execute_query("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"

    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================
# API ROUTES — Lead Finder
# ============================================================

@app.post("/api/leads/search")
async def api_search_leads(req: LeadSearchRequest):
    """Search for leads in a city/state."""
    result = lead_finder.run_lead_search(req.city, req.state, req.radius_meters)
    return JSONResponse(result)


@app.get("/api/leads")
async def api_get_leads(
    status: str = None,
    city: str = None,
    limit: int = 50,
    offset: int = 0,
):
    """Get leads with optional filters."""
    query = "SELECT * FROM leads WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if city:
        query += " AND city = ?"
        params.append(city)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    leads = execute_query(query, tuple(params))
    return JSONResponse({"leads": leads, "count": len(leads)})


# ============================================================
# API ROUTES — Website Audits
# ============================================================

@app.post("/api/audit/run")
async def api_run_audit(lead_id: int = Query(...)):
    """Run a website audit for a specific lead."""
    leads = execute_query("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not leads:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = website_auditor.audit_website(leads[0])
    if not result:
        raise HTTPException(status_code=400, detail="Audit failed")
    return JSONResponse(result)


@app.post("/api/audit/batch")
async def api_run_batch_audit(limit: int = 10):
    """Run batch audits on fresh leads."""
    result = website_auditor.run_batch_audit(limit=limit)
    return JSONResponse(result)


# ============================================================
# API ROUTES — Chatbot Engine
# ============================================================

@app.post("/api/chat/start")
async def api_chat_start(req: ChatStartRequest):
    """Start a new conversation."""
    conv_id = chatbot_engine.create_conversation(req.business_id)
    return JSONResponse({"conversation_id": conv_id, "business_id": req.business_id})


@app.get("/api/chat/stream")
async def api_chat_stream(
    conversation_id: int,
    business_id: int,
    message: str,
):
    """Stream chatbot response using SSE."""
    # Get existing conversation
    convs = execute_query(
        "SELECT * FROM conversations WHERE id = ? AND business_id = ?",
        (conversation_id, business_id),
    )
    if not convs:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = convs[0]
    messages_json = json.loads(conv.get("messages_json", "[]"))

    async def event_generator():
        async for chunk in chatbot_engine.stream_chat_response(
            business_id=business_id,
            conversation_id=conversation_id,
            user_message=message,
            conversation_history=messages_json,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/chat/conversations/{business_id}")
async def api_get_conversations(business_id: int, limit: int = 50):
    """Get conversations for a business."""
    convs = chatbot_engine.get_conversations_for_business(business_id, limit)
    return JSONResponse({"conversations": convs})


# ============================================================
# API ROUTES — Pilot Management
# ============================================================

@app.get("/pilot/signup")
async def pilot_signup_page(lead_id: int = None):
    """Render pilot signup form."""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Start Free Pilot - LeadCapture AI</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   background: #f1f5f9; display: flex; justify-content: center; align-items: center;
                   min-height: 100vh; padding: 20px; }
            .card { background: white; border-radius: 16px; padding: 40px; max-width: 500px;
                    width: 100%; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
            h1 { color: #1e293b; font-size: 28px; margin-bottom: 5px; }
            .subtitle { color: #64748b; margin-bottom: 25px; }
            .form-group { margin-bottom: 18px; }
            label { display: block; color: #374151; font-weight: 500; margin-bottom: 5px; font-size: 14px; }
            input, textarea { width: 100%; padding: 10px 14px; border: 1px solid #d1d5db; border-radius: 8px;
                             font-size: 14px; transition: border-color 0.2s; }
            input:focus, textarea:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
            .btn { width: 100%; padding: 12px; background: #2563eb; color: white; border: none; border-radius: 8px;
                   font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
            .btn:hover { background: #1d4ed8; }
            .features { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
            .feature { background: #f8fafc; border-radius: 8px; padding: 12px; text-align: center; font-size: 13px; color: #475569; }
            .feature emoji { font-size: 20px; display: block; margin-bottom: 4px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚀 Start Free Pilot</h1>
            <p class="subtitle">7 days free · No credit card required · Cancel anytime</p>

            <div class="features">
                <div class="feature"><span style="font-size: 20px; display: block;">🤖</span>AI Chatbot</div>
                <div class="feature"><span style="font-size: 20px; display: block;">📋</span>Lead Capture</div>
                <div class="feature"><span style="font-size: 20px; display: block;">📊</span>Dashboard</div>
                <div class="feature"><span style="font-size: 20px; display: block;">📬</span>Email Alerts</div>
            </div>

            <form action="/api/pilot/signup" method="POST">
                <input type="hidden" name="lead_id" value=\"""" + str(lead_id or "") + """\">
                <div class="form-group">
                    <label>Your Name</label>
                    <input type="text" name="owner_name" required placeholder="John Smith">
                </div>
                <div class="form-group">
                    <label>Email Address</label>
                    <input type="email" name="owner_email" required placeholder="john@mycompany.com">
                </div>
                <div class="form-group">
                    <label>Services Offered</label>
                    <input type="text" name="services" placeholder="e.g., HVAC repair, installation, maintenance">
                </div>
                <div class="form-group">
                    <label>Business Hours</label>
                    <input type="text" name="hours" value="Mon-Fri 8am-6pm" placeholder="Mon-Fri 8am-6pm">
                </div>
                <div class="form-group">
                    <label>Business Phone</label>
                    <input type="text" name="phone" placeholder="(555) 123-4567">
                </div>
                <button type="submit" class="btn">🚀 Start My Free Pilot</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.post("/api/pilot/signup")
async def api_pilot_signup(request: Request):
    """Handle pilot signup form submission."""
    form = await request.form()
    lead_id = int(form.get("lead_id", 0))
    owner_name = form.get("owner_name", "")
    owner_email = form.get("owner_email", "")
    services = form.get("services", "")
    hours = form.get("hours", "Mon-Fri 8am-6pm")
    phone = form.get("phone", "")

    if not lead_id or not owner_name or not owner_email:
        return HTMLResponse("""
        <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>❌ Missing required fields</h2>
            <p>Please go back and fill in all required fields.</p>
            <a href="/pilot/signup" style="color: #2563eb;">Try again</a>
        </body></html>
        """, status_code=400)

    result = pilot_manager.create_pilot_business(lead_id, owner_name, owner_email)
    if not result:
        return HTMLResponse("""
        <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>❌ Failed to create pilot</h2>
            <p>Please try again or contact support.</p>
            <a href="/pilot/signup" style="color: #2563eb;">Try again</a>
        </body></html>
        """, status_code=500)

    # Update business config
    pilot_manager.update_business_config(
        result["id"],
        services=services,
        hours=hours,
        phone=phone,
    )

    success_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Pilot Activated! - LeadCapture AI</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   background: #f1f5f9; display: flex; justify-content: center; align-items: center;
                   min-height: 100vh; padding: 20px; }}
            .card {{ background: white; border-radius: 16px; padding: 40px; max-width: 600px;
                    width: 100%; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }}
            h1 {{ color: #16a34a; font-size: 24px; }}
            .embed-box {{ background: #1e293b; color: #e2e8f0; padding: 15px; border-radius: 8px;
                        font-family: monospace; font-size: 12px; margin: 15px 0; overflow-x: auto; }}
            .btn {{ display: inline-block; padding: 12px 28px; background: #2563eb; color: white;
                   text-decoration: none; border-radius: 8px; font-weight: 600; margin-top: 15px; }}
            .btn:hover {{ background: #1d4ed8; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✅ Pilot Activated!</h1>
            <p style="color: #64748b; margin-top: 8px;">Your 7-day free trial has started for <strong>{result['business_name']}</strong></p>

            <h3 style="margin-top: 25px;">📋 Install Your Chatbot</h3>
            <p>Add this snippet to your website just before the closing &lt;/body&gt; tag:</p>
            <div class="embed-box">{result['embed_code']}</div>

            <h3>📊 Your Dashboard</h3>
            <a href="/dashboard/{result['id']}" class="btn">📊 Open Dashboard →</a>

            <p style="color: #64748b; margin-top: 20px; font-size: 14px;">
                A welcome email with setup instructions has been sent to <strong>{owner_email}</strong>.
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(success_html)


@app.get("/dashboard/{business_id}")
async def business_dashboard(business_id: int):
    """Render a business's dashboard page."""
    data = pilot_manager.get_business_dashboard(business_id)
    if not data:
        return HTMLResponse("<h1>Business not found</h1>", status_code=404)

    biz = data["business"]
    convs = data["conversations"]
    days_left = data["days_remaining"]

    status_color = {
        "trial": "blue",
        "active": "green",
        "expired": "red",
        "grace": "orange",
    }.get(biz["status"], "gray")

    conv_rows = ""
    for c in convs[:10]:
        conv_rows += f"""
        <tr>
            <td>{c.get('customer_name', 'Anonymous')}</td>
            <td>{c.get('customer_phone', '—')}</td>
            <td>{c.get('service_needed', '—')}</td>
            <td>{c.get('zip_code', '—')}</td>
            <td>{c['created_at'][:10]}</td>
            <td><span class="badge badge-{c['status']}">{c['status']}</span></td>
        </tr>"""

    if not conv_rows:
        conv_rows = "<tr><td colspan='6' style='text-align: center; color: #94a3b8;'>No conversations yet. Install your chatbot to start capturing leads!</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Dashboard - {biz['business_name']} - {settings.APP_NAME}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f1f5f9; color: #1e293b; }}
        .header {{ background: #1e293b; color: white; padding: 20px 30px; }}
        .header h1 {{ font-size: 22px; }}
        .header p {{ color: #94a3b8; font-size: 14px; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 30px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .card h3 {{ color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .card .value {{ font-size: 28px; font-weight: 700; }}
        .card .value.green {{ color: #16a34a; }}
        .card .value.blue {{ color: #2563eb; }}
        .card .value.orange {{ color: #ea580c; }}
        .card .value.red {{ color: #dc2626; }}
        .section-title {{ font-size: 18px; margin: 25px 0 15px; }}
        table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #f8fafc; text-align: left; padding: 12px 15px; font-size: 12px; text-transform: uppercase; color: #64748b; }}
        td {{ padding: 12px 15px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge-active {{ background: #dcfce7; color: #16a34a; }}
        .badge-closed {{ background: #f1f5f9; color: #64748b; }}
        .badge-escalated {{ background: #fef2f2; color: #dc2626; }}
        .embed-box {{ background: #1e293b; color: #e2e8f0; padding: 15px; border-radius: 8px;
                    font-family: monospace; font-size: 12px; margin-top: 10px; overflow-x: auto; }}
        @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 {biz['business_name']}</h1>
        <p>Owner: {biz.get('owner_name', 'Not set')} · {biz.get('owner_email', 'No email')}</p>
    </div>

    <div class="container">
        <div class="grid">
            <div class="card">
                <h3>Status</h3>
                <div class="value" style="color: {status_color};">{biz['status'].upper()}</div>
            </div>
            <div class="card">
                <h3>Pilot Days Left</h3>
                <div class="value {'orange' if days_left <= 3 else 'blue'}">{days_left}</div>
                <p style="font-size: 12px; color: #94a3b8;">of 7 days</p>
            </div>
            <div class="card">
                <h3>Leads Captured</h3>
                <div class="value green">{data['leads_captured']}</div>
            </div>
            <div class="card">
                <h3>Payment</h3>
                <div class="value" style="color: {'#16a34a' if biz['payment_status'] == 'paid' else '#ea580c'};">{biz['payment_status'].upper()}</div>
            </div>
        </div>

        {f'''
        <div class="card" style="margin-bottom: 25px;">
            <h3 style="color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">📋 Your Embed Code</h3>
            <p style="font-size: 13px; color: #64748b; margin-bottom: 8px;">Add this to your website just before &lt;/body&gt;:</p>
            <div class="embed-box">{biz.get('chatbot_embed_code', 'N/A')}</div>
        </div>
        ''' if biz.get('chatbot_embed_code') else ''}

        <h2 class="section-title">💬 Recent Conversations</h2>
        <table>
            <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Service</th>
                <th>Zip</th>
                <th>Date</th>
                <th>Status</th>
            </tr>
            {conv_rows}
        </table>
    </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/reactivate")
async def reactivate_page(business_id: int = None):
    """Simple reactivation page."""
    if not business_id:
        return HTMLResponse("<h1>Missing business ID</h1>", status_code=400)

    biz = execute_query("SELECT * FROM businesses WHERE id = ?", (business_id,))
    if not biz:
        return HTMLResponse("<h1>Business not found</h1>", status_code=404)

    biz = biz[0]
    success = payment_handler.reactivate_business(business_id)

    if success:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>✅ Reactivated!</h2>
            <p>{biz['business_name']} is now active again.</p>
            <a href="/dashboard/{business_id}" style="color: #2563eb;">Go to Dashboard</a>
        </body></html>
        """)
    else:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>💰 Payment Required</h2>
            <p>Send ${settings.MONTHLY_PRICE} via Wise to reactivate {biz['business_name']}.</p>
            <p><strong>{settings.WISE_ACCOUNT_NAME}</strong> | {settings.WISE_ACCOUNT_NUMBER}</p>
            <p>After sending payment, <a href="/admin" style="color: #2563eb;">contact admin</a> to verify.</p>
        </body></html>
        """)


# ============================================================
# API ROUTES — Tracking & Email Events
# ============================================================

@app.get("/api/track/open/{tracking_id}")
async def track_email_open(tracking_id: str):
    """Track email open via pixel."""
    try:
        execute_write(
            "UPDATE emails SET opened = 1 WHERE tracking_id = ?",
            (tracking_id,),
        )
    except Exception as e:
        logger.warning("Failed to track open: %s", e)

    # Return 1x1 transparent pixel
    return Response(
        content=b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b",
        media_type="image/gif",
    )


@app.get("/api/track/click/{tracking_id}")
async def track_email_click(tracking_id: str, redirect: str = "/"):
    """Track email click and redirect."""
    try:
        execute_write(
            "UPDATE emails SET clicked = 1 WHERE tracking_id = ?",
            (tracking_id,),
        )
    except Exception as e:
        logger.warning("Failed to track click: %s", e)

    return RedirectResponse(url=redirect)


@app.get("/api/track/unsubscribe/{tracking_id}")
async def track_unsubscribe(tracking_id: str):
    """Handle unsubscribe by setting the email as unsubscribed."""
    try:
        # Delete the tracking record so no more emails are sent to this recipient
        email = execute_query("SELECT * FROM emails WHERE tracking_id = ?", (tracking_id,))
        if email and email[0].get("recipient_email"):
            logger.info("Unsubscribe request for: %s", email[0]["recipient_email"])
    except Exception:
        pass

    return HTMLResponse("""
    <!DOCTYPE html>
    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h2>✅ Unsubscribed</h2>
        <p>You've been unsubscribed from these emails.</p>
    </body></html>
    """)


# ============================================================
# API ROUTES — Payments
# ============================================================

@app.post("/api/payments/record")
async def api_record_payment(req: PaymentRecordRequest):
    """Record a new payment (for customers to submit)."""
    pid = payment_handler.record_payment(req.business_id, req.amount, req.wise_reference)
    if not pid:
        raise HTTPException(status_code=500, detail="Failed to record payment")
    return JSONResponse({"payment_id": pid, "status": "pending"})


@app.get("/api/payments")
async def api_get_payments(limit: int = 50):
    """Get all payments for admin view."""
    payments = payment_handler.get_all_payments(limit)
    return JSONResponse({"payments": payments})


@app.get("/api/payments/pending")
async def api_get_pending_payments():
    """Get pending payments for admin review."""
    pending = payment_handler.get_pending_payments()
    return JSONResponse({"payments": pending})


# ============================================================
# API ROUTES — Pilot Checks (Manual trigger)
# ============================================================

@app.post("/api/pilot/run-daily-checks")
async def api_run_daily_checks():
    """Manually trigger daily pilot checks."""
    result = pilot_manager.run_daily_pilot_checks()
    return JSONResponse(result)


# ============================================================
# ADMIN ROUTES
# ============================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_page():
    """Admin dashboard page."""
    return admin_dashboard.generate_dashboard_html()


@app.get("/admin/payments", response_class=HTMLResponse)
async def admin_payments_page():
    """Admin payments management page."""
    payments = payment_handler.get_all_payments()
    pending = payment_handler.get_pending_payments()

    rows = ""
    for p in payments:
        badge = f"badge-{p['status']}" if p['status'] in ('paid', 'pending', 'failed') else ""
        actions = ""
        if p['status'] == 'pending':
            actions = f"""
                <a href="/admin/verify-payment/{p['id']}" class="btn btn-success btn-sm"
                   onclick="return confirm('Verify this payment?')">✅ Verify</a>
                <a href="/admin/reject-payment/{p['id']}" class="btn btn-danger btn-sm"
                   onclick="return confirm('Reject this payment?')">✕ Reject</a>
            """
        rows += f"""
        <tr>
            <td>{p['business_name']}</td>
            <td>{p['owner_name'] or '-'}</td>
            <td><strong>${p['amount']:.0f}</strong></td>
            <td>{p['wise_reference'] or '-'}</td>
            <td><span class="badge {badge}">{p['status']}</span></td>
            <td>{p['created_at'][:10]}</td>
            <td class="actions">{actions}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Payments - Admin - {settings.APP_NAME}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f1f5f9; color: #1e293b; }}
        .header {{ background: #1e293b; color: white; padding: 20px 30px; }}
        .header h1 {{ font-size: 22px; }}
        .nav a {{ color: #94a3b8; text-decoration: none; margin-right: 15px; font-size: 14px; }}
        .nav a:hover {{ color: white; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 30px; }}
        h2 {{ margin: 20px 0 10px; }}
        table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 30px; }}
        th {{ background: #f8fafc; text-align: left; padding: 12px 15px; font-size: 12px; text-transform: uppercase; color: #64748b; }}
        td {{ padding: 12px 15px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge-paid {{ background: #dcfce7; color: #16a34a; }}
        .badge-pending {{ background: #fff7ed; color: #ea580c; }}
        .badge-failed {{ background: #fef2f2; color: #dc2626; }}
        .btn {{ display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 500; }}
        .btn-success {{ background: #16a34a; color: white; }}
        .btn-danger {{ background: #dc2626; color: white; }}
        .btn-sm {{ padding: 4px 10px; font-size: 12px; }}
        .actions {{ display: flex; gap: 6px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>💳 Payment Management</h1>
        <div class="nav">
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/payments">💳 Payments</a>
            <a href="/admin/leads">📋 Leads</a>
        </div>
    </div>
    <div class="container">
        <h2>Pending Payments ({len(pending)})</h2>
        <table>
            <tr>
                <th>Business</th>
                <th>Owner</th>
                <th>Amount</th>
                <th>Wise Ref</th>
                <th>Status</th>
                <th>Date</th>
                <th>Actions</th>
            </tr>
            {rows if rows else '<tr><td colspan="7" style="text-align: center; color: #94a3b8;">No payments found</td></tr>'}
        </table>
    </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/admin/leads", response_class=HTMLResponse)
async def admin_leads_page(limit: int = 100):
    """Admin leads list page."""
    leads = execute_query("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,))

    rows = ""
    for lead in leads:
        rows += f"""
        <tr>
            <td><strong>{lead['business_name']}</strong></td>
            <td>{lead.get('website', '—')[:40]}</td>
            <td>{lead.get('phone', '—')}</td>
            <td>{lead.get('city', '')}, {lead.get('state', '')}</td>
            <td>{lead.get('rating', '—')}</td>
            <td>{lead.get('review_count', 0)}</td>
            <td><span class="badge badge-{lead['status']}">{lead['status']}</span></td>
            <td>{lead.get('score', '—')}</td>
            <td><a href="/admin/audit/{lead['id']}" class="btn btn-primary btn-sm">Audit</a></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Leads - Admin - {settings.APP_NAME}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f1f5f9; color: #1e293b; }}
        .header {{ background: #1e293b; color: white; padding: 20px 30px; }}
        .header h1 {{ font-size: 22px; }}
        .nav a {{ color: #94a3b8; text-decoration: none; margin-right: 15px; font-size: 14px; }}
        .nav a:hover {{ color: white; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 30px; }}
        table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #f8fafc; text-align: left; padding: 12px 15px; font-size: 12px; text-transform: uppercase; color: #64748b; }}
        td {{ padding: 12px 15px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge-fresh {{ background: #dbeafe; color: #2563eb; }}
        .badge-audited {{ background: #fef3c7; color: #d97706; }}
        .badge-pilot {{ background: #dcfce7; color: #16a34a; }}
        .badge-paid {{ background: #dcfce7; color: #16a34a; }}
        .badge-dead {{ background: #f1f5f9; color: #64748b; }}
        .btn {{ display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 500; }}
        .btn-primary {{ background: #2563eb; color: white; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Lead Management</h1>
        <div class="nav">
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/payments">💳 Payments</a>
            <a href="/admin/leads">📋 Leads</a>
        </div>
    </div>
    <div class="container">
        <table>
            <tr>
                <th>Business</th>
                <th>Website</th>
                <th>Phone</th>
                <th>Location</th>
                <th>Rating</th>
                <th>Reviews</th>
                <th>Status</th>
                <th>Score</th>
                <th>Actions</th>
            </tr>
            {rows if rows else '<tr><td colspan="9" style="text-align: center; color: #94a3b8;">No leads found</td></tr>'}
        </table>
    </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/admin/audit/{lead_id}")
async def admin_audit_lead(lead_id: int):
    """Admin trigger audit for a specific lead."""
    leads = execute_query("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not leads:
        return HTMLResponse("<h1>Lead not found</h1>", status_code=404)

    result = website_auditor.audit_website(leads[0])
    if result:
        return RedirectResponse(url="/admin/leads", status_code=303)
    return HTMLResponse("<h1>Audit failed</h1>", status_code=500)


@app.get("/admin/verify-payment/{payment_id}")
async def admin_verify_payment(payment_id: int):
    """Admin verify a payment."""
    success = payment_handler.verify_payment(payment_id)
    if success:
        return RedirectResponse(url="/admin/payments", status_code=303)
    return HTMLResponse("<h1>Verification failed</h1>", status_code=500)


@app.get("/admin/reject-payment/{payment_id}")
async def admin_reject_payment(payment_id: int):
    """Admin reject a payment."""
    success = payment_handler.reject_payment(payment_id)
    if success:
        return RedirectResponse(url="/admin/payments", status_code=303)
    return HTMLResponse("<h1>Rejection failed</h1>", status_code=500)


@app.get("/admin/deactivate/{business_id}")
async def admin_deactivate_business(business_id: int):
    """Admin deactivate a business."""
    success = payment_handler.deactivate_business(business_id)
    if success:
        return RedirectResponse(url="/admin", status_code=303)
    return HTMLResponse("<h1>Deactivation failed</h1>", status_code=500)


@app.get("/admin/business/{business_id}")
async def admin_view_business(business_id: int):
    """Admin view a single business detail."""
    biz = execute_query("SELECT * FROM businesses WHERE id = ?", (business_id,))
    if not biz:
        return HTMLResponse("<h1>Business not found</h1>", status_code=404)
    biz = biz[0]

    conversations = execute_query(
        "SELECT * FROM conversations WHERE business_id = ? ORDER BY created_at DESC LIMIT 50",
        (business_id,),
    )
    payments = execute_query(
        "SELECT * FROM payments WHERE business_id = ? ORDER BY created_at DESC",
        (business_id,),
    )

    conv_rows = ""
    for c in conversations:
        msgs = json.loads(c.get("messages_json", "[]"))
        msg_count = len(msgs) // 2
        conv_rows += f"""
        <tr>
            <td>{c.get('customer_name', 'Anonymous')}</td>
            <td>{c.get('customer_phone', '—')}</td>
            <td>{c.get('service_needed', '—')}</td>
            <td>{msg_count}</td>
            <td><span class="badge badge-{c['status']}">{c['status']}</span></td>
            <td>{c['created_at'][:16]}</td>
            <td><a href="/admin/conversation/{c['id']}" class="btn btn-sm btn-primary">View</a></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>{biz['business_name']} - Admin</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, sans-serif; background: #f1f5f9; padding: 30px; }}
    .card {{ background: white; border-radius: 12px; padding: 25px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    h1 {{ font-size: 22px; margin-bottom: 5px; }}
    .info {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .info-item {{ padding: 8px 0; border-bottom: 1px solid #f1f5f9; }}
    .label {{ color: #64748b; font-size: 12px; text-transform: uppercase; }}
    table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; }}
    th {{ background: #f8fafc; padding: 10px; font-size: 12px; color: #64748b; text-align: left; }}
    td {{ padding: 10px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
    .badge-active {{ background: #dcfce7; color: #16a34a; }}
    .badge-trial {{ background: #dbeafe; color: #2563eb; }}
    .badge-expired {{ background: #f1f5f9; color: #64748b; }}
    .btn {{ display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 12px; }}
    .btn-primary {{ background: #2563eb; color: white; }}
    .btn-sm {{ padding: 4px 10px; font-size: 11px; }}
</style>
</head>
<body>
    <a href="/admin" style="color: #2563eb; text-decoration: none;">← Back to Dashboard</a>
    <h1>{biz['business_name']}</h1>
    <div class="card">
        <div class="info">
            <div class="info-item"><div class="label">Owner</div>{biz.get('owner_name', '—')}</div>
            <div class="info-item"><div class="label">Email</div>{biz.get('owner_email', '—')}</div>
            <div class="info-item"><div class="label">Status</div>{biz['status']}</div>
            <div class="info-item"><div class="label">Payment</div>{biz['payment_status']}</div>
            <div class="info-item"><div class="label">Trial Ends</div>{biz.get('trial_ends_at', '—')[:10]}</div>
            <div class="info-item"><div class="label">Monthly Due</div>{biz.get('monthly_due_date', '—')}</div>
            <div class="info-item"><div class="label">Services</div>{biz.get('services', '—')}</div>
            <div class="info-item"><div class="label">Hours</div>{biz.get('hours', '—')}</div>
        </div>
    </div>
    <h2 style="margin: 20px 0 10px;">💬 Conversations ({len(conversations)})</h2>
    <table>
        <tr><th>Customer</th><th>Phone</th><th>Service</th><th>Messages</th><th>Status</th><th>Date</th><th>Actions</th></tr>
        {conv_rows if conv_rows else '<tr><td colspan="7" style="text-align:center;color:#94a3b8;">No conversations</td></tr>'}
    </table>
</body></html>"""
    return HTMLResponse(html)


@app.get("/admin/conversation/{conversation_id}")
async def admin_view_conversation(conversation_id: int):
    """Admin view a single conversation with full messages."""
    conv = execute_query("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if not conv:
        return HTMLResponse("<h1>Conversation not found</h1>", status_code=404)
    conv = conv[0]

    messages = json.loads(conv.get("messages_json", "[]"))
    msg_html = ""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")[:19]
        align = "right" if role == "user" else "left"
        bg = "#2563eb" if role == "user" else "#f1f5f9"
        color = "white" if role == "user" else "#1e293b"
        msg_html += f"""
        <div style="display:flex; justify-content:{align}; margin-bottom:10px;">
            <div style="background:{bg}; color:{color}; padding:10px 14px; border-radius:12px;
                        max-width:70%; font-size:14px; line-height:1.5;">
                <strong style="font-size:11px; opacity:0.7;">{role.upper()}</strong><br>
                {content}
                <div style="font-size:10px; opacity:0.5; margin-top:4px;">{ts}</div>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>Conversation #{conversation_id}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, sans-serif; background: #f8fafc; padding: 20px; }}
    .header {{ margin-bottom: 20px; }}
    .info {{ display: flex; gap: 20px; color: #64748b; font-size: 14px; }}
    .chat {{ max-width: 800px; margin: 0 auto; }}
    a {{ color: #2563eb; text-decoration: none; }}
</style>
</head>
<body>
    <div class="header">
        <a href="/admin/business/{conv['business_id']}">← Back to Business</a>
        <h1>💬 Conversation #{conversation_id}</h1>
        <div class="info">
            <span>Customer: {conv.get('customer_name', 'Unknown')}</span>
            <span>Phone: {conv.get('customer_phone', '—')}</span>
            <span>Service: {conv.get('service_needed', '—')}</span>
            <span>Status: {conv['status']}</span>
        </div>
    </div>
    <div class="chat">
        {msg_html if msg_html else '<p style="text-align:center;color:#94a3b8;">No messages in this conversation.</p>'}
    </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/admin/conversations")
async def admin_all_conversations(limit: int = 100):
    """Admin view all conversations."""
    convs = execute_query(
        """SELECT c.*, b.business_name FROM conversations c
           JOIN businesses b ON c.business_id = b.id
           ORDER BY c.created_at DESC LIMIT ?""",
        (limit,),
    )

    rows = ""
    for c in convs:
        rows += f"""
        <tr>
            <td>{c['id']}</td>
            <td><a href="/admin/business/{c['business_id']}" style="color:#2563eb;">{c['business_name']}</a></td>
            <td>{c.get('customer_name', 'Anonymous')}</td>
            <td>{c.get('customer_phone', '—')}</td>
            <td>{c.get('service_needed', '—')}</td>
            <td><span class="badge badge-{c['status']}">{c['status']}</span></td>
            <td>{c['created_at'][:16]}</td>
            <td><a href="/admin/conversation/{c['id']}" class="btn btn-sm btn-primary">View</a></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>All Conversations - Admin</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, sans-serif; background: #f1f5f9; padding: 30px; }}
    h1 {{ margin-bottom: 15px; }}
    table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    th {{ background: #f8fafc; padding: 12px; font-size: 12px; color: #64748b; text-align: left; }}
    td {{ padding: 12px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
    .badge-active {{ background: #dcfce7; color: #16a34a; }}
    .badge-closed {{ background: #f1f5f9; color: #64748b; }}
    .badge-escalated {{ background: #fef2f2; color: #dc2626; }}
    .btn {{ display: inline-block; padding: 4px 10px; border-radius: 6px; text-decoration: none; font-size: 11px; }}
    .btn-primary {{ background: #2563eb; color: white; }}
    a {{ color: #2563eb; text-decoration: none; }}
</style>
</head>
<body>
    <a href="/admin" style="margin-bottom:15px;display:inline-block;">← Back to Dashboard</a>
    <h1>💬 All Conversations</h1>
    <table>
        <tr><th>ID</th><th>Business</th><th>Customer</th><th>Phone</th><th>Service</th><th>Status</th><th>Date</th><th>Actions</th></tr>
        {rows if rows else '<tr><td colspan="8" style="text-align:center;color:#94a3b8;">No conversations</td></tr>'}
    </table>
</body></html>"""
    return HTMLResponse(html)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    """Landing page."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{settings.APP_NAME} — Automated Lead Generation</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f8fafc; color: #1e293b; line-height: 1.6; }}
        .hero {{ background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
                color: white; padding: 80px 20px; text-align: center; }}
        .hero h1 {{ font-size: 48px; margin-bottom: 15px; }}
        .hero p {{ font-size: 18px; color: #94a3b8; max-width: 600px; margin: 0 auto 30px; }}
        .btn {{ display: inline-block; padding: 14px 32px; border-radius: 8px; text-decoration: none;
                font-size: 16px; font-weight: 600; margin: 0 8px; }}
        .btn-primary {{ background: #2563eb; color: white; }}
        .btn-primary:hover {{ background: #1d4ed8; }}
        .btn-outline {{ border: 2px solid #475569; color: #e2e8f0; }}
        .btn-outline:hover {{ border-color: #2563eb; color: #2563eb; }}
        .container {{ max-width: 1100px; margin: 0 auto; padding: 60px 20px; }}
        .features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; }}
        .feature {{ background: white; border-radius: 12px; padding: 30px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .feature h3 {{ font-size: 18px; margin-bottom: 10px; }}
        .feature p {{ color: #64748b; font-size: 14px; }}
        .section-title {{ text-align: center; font-size: 32px; margin-bottom: 40px; }}
        .footer {{ text-align: center; padding: 40px; color: #94a3b8; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>{settings.APP_NAME}</h1>
        <p>Automated lead capture and conversion for local service businesses. Find leads, audit websites, deploy AI chatbots, and convert — all without human sales calls.</p>
        <div>
            <a href="/admin" class="btn btn-primary">📊 Admin Dashboard</a>
            <a href="/health" class="btn btn-outline">🩺 Health Check</a>
        </div>
    </div>
    <div class="container">
        <h2 class="section-title">How It Works</h2>
        <div class="features">
            <div class="feature">
                <h3>🔍 Find Leads</h3>
                <p>Scrape Google Places for HVAC, plumbing, and roofing businesses. Filter by rating, reviews, and website presence.</p>
            </div>
            <div class="feature">
                <h3>📋 Audit Websites</h3>
                <p>Automatically audit websites for lead capture readiness. Score and send detailed reports via email.</p>
            </div>
            <div class="feature">
                <h3>🤖 AI Chatbot</h3>
                <p>Custom GPT-4o-mini chatbot for each business. Real-time conversations with SSE streaming. 24/7 lead capture.</p>
            </div>
            <div class="feature">
                <h3>🚀 Free Pilot</h3>
                <p>7-day free trial with full chatbot functionality. Dashboard, email alerts, and daily progress updates.</p>
            </div>
            <div class="feature">
                <h3>💲 Simple Payments</h3>
                <p>Manual Wise verification. Monthly billing with grace periods and easy reactivation.</p>
            </div>
            <div class="feature">
                <h3>📊 Full Dashboard</h3>
                <p>Admin dashboard with MRR, churn rate, conversation logs, and payment management.</p>
            </div>
        </div>
    </div>
    <div class="footer">
        <p>{settings.APP_NAME} v1.0.0 · Built for local service businesses</p>
    </div>
</body>
</html>""")


# ============================================================
# Startup
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.app:app", host="0.0.0.0", port=port, reload=True)
