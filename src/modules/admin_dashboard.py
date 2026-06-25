"""
LeadCapture AI — MODULE 7: Admin Dashboard
Simple HTML dashboard with system metrics and management actions.
No auth for MVP (add basic auth later).
"""

from datetime import datetime
from src.config import settings, logger
from src.database.connection import execute_query
from src.modules.payment_handler import get_revenue_stats


def get_dashboard_stats() -> dict:
    """Aggregate all dashboard statistics."""
    try:
        # Core counts
        total_leads = execute_query("SELECT COUNT(*) as count FROM leads")[0]["count"]
        fresh_leads = execute_query("SELECT COUNT(*) as count FROM leads WHERE status = 'fresh'")[0]["count"]
        audited_leads = execute_query("SELECT COUNT(*) as count FROM leads WHERE status = 'audited'")[0]["count"]
        dead_leads = execute_query("SELECT COUNT(*) as count FROM leads WHERE status = 'dead'")[0]["count"]

        # Pilots and customers
        total_businesses = execute_query("SELECT COUNT(*) as count FROM businesses")[0]["count"]
        active_pilots = execute_query("SELECT COUNT(*) as count FROM businesses WHERE status = 'trial'")[0]["count"]
        active_customers = execute_query("SELECT COUNT(*) as count FROM businesses WHERE status = 'active'")[0]["count"]
        expired = execute_query("SELECT COUNT(*) as count FROM businesses WHERE status = 'expired'")[0]["count"]
        grace_period = execute_query("SELECT COUNT(*) as count FROM businesses WHERE status = 'grace'")[0]["count"]

        # Communications
        audits_sent = execute_query("SELECT COUNT(*) as count FROM audits WHERE email_sent_at IS NOT NULL")[0]["count"]
        total_conversations = execute_query("SELECT COUNT(*) as count FROM conversations")[0]["count"]

        # Emails
        emails_sent = execute_query("SELECT COUNT(*) as count FROM emails")[0]["count"]
        emails_opened = execute_query("SELECT COUNT(*) as count FROM emails WHERE opened = 1")[0]["count"]
        emails_clicked = execute_query("SELECT COUNT(*) as count FROM emails WHERE clicked = 1")[0]["count"]

        # Revenue
        revenue = get_revenue_stats()

        # Churn rate (expired / total businesses that ever had a trial)
        churn_rate = 0
        if total_businesses > 0:
            churn_rate = round((expired / total_businesses) * 100, 1)

        return {
            "leads": {
                "total": total_leads,
                "fresh": fresh_leads,
                "audited": audited_leads,
                "dead": dead_leads,
            },
            "businesses": {
                "total": total_businesses,
                "active_pilots": active_pilots,
                "active_customers": active_customers,
                "expired": expired,
                "grace_period": grace_period,
            },
            "communications": {
                "audits_sent": audits_sent,
                "total_conversations": total_conversations,
            },
            "emails": {
                "total_sent": emails_sent,
                "opened": emails_opened,
                "clicked": emails_clicked,
                "open_rate": round((emails_opened / emails_sent * 100), 1) if emails_sent > 0 else 0,
                "click_rate": round((emails_clicked / emails_sent * 100), 1) if emails_sent > 0 else 0,
            },
            "revenue": revenue,
            "churn_rate": churn_rate,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to get dashboard stats: %s", e)
        return {"error": str(e)}


def generate_dashboard_html() -> str:
    """Generate the admin dashboard HTML page."""
    stats = get_dashboard_stats()

    if "error" in stats:
        return f"<html><body><h1>Error loading dashboard</h1><p>{stats['error']}</p></body></html>"

    leads = stats["leads"]
    biz = stats["businesses"]
    comms = stats["communications"]
    emails = stats["emails"]
    revenue = stats["revenue"]
    churn = stats["churn_rate"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{settings.APP_NAME} — Admin Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #f1f5f9; color: #1e293b; }}
        .header {{ background: #1e293b; color: white; padding: 20px 30px; }}
        .header h1 {{ font-size: 24px; }}
        .header p {{ color: #94a3b8; font-size: 14px; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 30px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .card h3 {{ color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 15px; }}
        .stat {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }}
        .stat:last-child {{ border-bottom: none; }}
        .stat-label {{ color: #64748b; }}
        .stat-value {{ font-weight: 600; font-size: 16px; }}
        .stat-value.green {{ color: #16a34a; }}
        .stat-value.red {{ color: #dc2626; }}
        .stat-value.blue {{ color: #2563eb; }}
        .stat-value.orange {{ color: #ea580c; }}
        .section-title {{ font-size: 18px; margin: 30px 0 15px; color: #1e293b; }}
        table {{ width: 100%; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #f8fafc; text-align: left; padding: 12px 15px; font-size: 12px; text-transform: uppercase; color: #64748b; letter-spacing: 1px; }}
        td {{ padding: 12px 15px; border-top: 1px solid #f1f5f9; font-size: 14px; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge-active {{ background: #dcfce7; color: #16a34a; }}
        .badge-trial {{ background: #dbeafe; color: #2563eb; }}
        .badge-expired {{ background: #fef2f2; color: #dc2626; }}
        .badge-grace {{ background: #fff7ed; color: #ea580c; }}
        .badge-paid {{ background: #dcfce7; color: #16a34a; }}
        .badge-pending {{ background: #fff7ed; color: #ea580c; }}
        .btn {{ display: inline-block; padding: 6px 14px; border-radius: 6px; text-decoration: none;
                font-size: 13px; font-weight: 500; border: none; cursor: pointer; }}
        .btn-primary {{ background: #2563eb; color: white; }}
        .btn-danger {{ background: #dc2626; color: white; }}
        .btn-success {{ background: #16a34a; color: white; }}
        .btn-sm {{ padding: 4px 10px; font-size: 12px; }}
        .actions {{ display: flex; gap: 6px; }}
        .nav {{ display: flex; gap: 15px; margin-top: 10px; }}
        .nav a {{ color: #94a3b8; text-decoration: none; font-size: 14px; }}
        .nav a:hover {{ color: white; }}
        @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{settings.APP_NAME} Admin</h1>
        <p>System Dashboard — Last updated: {stats['timestamp'][:19]}</p>
        <div class="nav">
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/payments">💳 Payments</a>
            <a href="/admin/leads">📋 Leads</a>
            <a href="/admin/conversations">💬 Conversations</a>
        </div>
    </div>

    <div class="container">
        <!-- Key Metrics -->
        <div class="grid">
            <div class="card">
                <h3>📊 Leads</h3>
                <div class="stat"><span class="stat-label">Total</span><span class="stat-value blue">{leads['total']}</span></div>
                <div class="stat"><span class="stat-label">Fresh</span><span class="stat-value">{leads['fresh']}</span></div>
                <div class="stat"><span class="stat-label">Audited</span><span class="stat-value">{leads['audited']}</span></div>
                <div class="stat"><span class="stat-label">Dead</span><span class="stat-value red">{leads['dead']}</span></div>
            </div>
            <div class="card">
                <h3>🏢 Businesses</h3>
                <div class="stat"><span class="stat-label">Total</span><span class="stat-value blue">{biz['total']}</span></div>
                <div class="stat"><span class="stat-label">Active Pilots</span><span class="stat-value blue">{biz['active_pilots']}</span></div>
                <div class="stat"><span class="stat-label">Paying Customers</span><span class="stat-value green">{biz['active_customers']}</span></div>
                <div class="stat"><span class="stat-label">Grace Period</span><span class="stat-value orange">{biz['grace_period']}</span></div>
                <div class="stat"><span class="stat-label">Expired</span><span class="stat-value red">{biz['expired']}</span></div>
            </div>
            <div class="card">
                <h3>💰 Revenue</h3>
                <div class="stat"><span class="stat-label">MRR</span><span class="stat-value green">${revenue['mrr']:.0f}</span></div>
                <div class="stat"><span class="stat-label">This Month</span><span class="stat-value green">${revenue['monthly_revenue']:.0f}</span></div>
                <div class="stat"><span class="stat-label">Total Revenue</span><span class="stat-value green">${revenue['total_revenue']:.0f}</span></div>
                <div class="stat"><span class="stat-label">Churn Rate</span><span class="stat-value red">{churn}%</span></div>
            </div>
            <div class="card">
                <h3>📬 Communications</h3>
                <div class="stat"><span class="stat-label">Audits Sent</span><span class="stat-value blue">{comms['audits_sent']}</span></div>
                <div class="stat"><span class="stat-label">Conversations</span><span class="stat-value">{comms['total_conversations']}</span></div>
                <div class="stat"><span class="stat-label">Emails Sent</span><span class="stat-value">{emails['total_sent']}</span></div>
                <div class="stat"><span class="stat-label">Open Rate</span><span class="stat-value">{emails['open_rate']}%</span></div>
                <div class="stat"><span class="stat-label">Click Rate</span><span class="stat-value">{emails['click_rate']}%</span></div>
            </div>
        </div>

        <!-- Recent Businesses -->
        <h2 class="section-title">📋 Recent Businesses</h2>"""

    # Recent businesses table
    businesses = execute_query(
        """SELECT id, business_name, owner_name, owner_email, status, payment_status,
                  created_at, trial_ends_at
           FROM businesses ORDER BY created_at DESC LIMIT 20"""
    )

    html += """
        <table>
            <tr>
                <th>Business</th>
                <th>Owner</th>
                <th>Email</th>
                <th>Status</th>
                <th>Payment</th>
                <th>Created</th>
                <th>Actions</th>
            </tr>"""

    for biz_row in businesses:
        status_badge = f"badge-{biz_row['status']}" if biz_row['status'] in ('active', 'trial', 'expired', 'grace') else ""
        pay_badge = f"badge-{biz_row['payment_status']}" if biz_row['payment_status'] in ('paid', 'pending') else ""
        html += f"""
            <tr>
                <td><strong>{biz_row['business_name']}</strong></td>
                <td>{biz_row['owner_name'] or '-'}</td>
                <td>{biz_row['owner_email'] or '-'}</td>
                <td><span class="badge {status_badge}">{biz_row['status']}</span></td>
                <td><span class="badge {pay_badge}">{biz_row['payment_status']}</span></td>
                <td>{biz_row['created_at'][:10]}</td>
                <td class="actions">
                    <a href="/admin/business/{biz_row['id']}" class="btn btn-primary btn-sm">View</a>
                    <a href="/admin/deactivate/{biz_row['id']}" class="btn btn-danger btn-sm"
                       onclick="return confirm('Deactivate this business?')">Deactivate</a>
                </td>
            </tr>"""

    html += "</table>"

    # Pending payments section
    pending = execute_query(
        """SELECT p.id, p.amount, p.wise_reference, p.created_at,
                  b.business_name, b.owner_name
           FROM payments p
           JOIN businesses b ON p.business_id = b.id
           WHERE p.status = 'pending'
           ORDER BY p.created_at DESC LIMIT 20"""
    )

    if pending:
        html += f"""
        <h2 class="section-title" style="margin-top: 40px;">💳 Pending Payments</h2>
        <table>
            <tr>
                <th>Business</th>
                <th>Owner</th>
                <th>Amount</th>
                <th>Wise Ref</th>
                <th>Date</th>
                <th>Actions</th>
            </tr>"""

        for p in pending:
            html += f"""
            <tr>
                <td><strong>{p['business_name']}</strong></td>
                <td>{p['owner_name'] or '-'}</td>
                <td><strong>${p['amount']:.0f}</strong></td>
                <td>{p['wise_reference'] or '-'}</td>
                <td>{p['created_at'][:10]}</td>
                <td class="actions">
                    <a href="/admin/verify-payment/{p['id']}" class="btn btn-success btn-sm"
                       onclick="return confirm('Verify this payment and activate customer?')">✅ Verify</a>
                    <a href="/admin/reject-payment/{p['id']}" class="btn btn-danger btn-sm"
                       onclick="return confirm('Reject this payment?')">✕ Reject</a>
                </td>
            </tr>"""

        html += "</table>"

    html += """
    </div>
</body>
</html>"""

    return html
