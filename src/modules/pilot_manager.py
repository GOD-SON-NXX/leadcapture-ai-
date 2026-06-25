"""
LeadCapture AI — MODULE 4: Pilot Management
Manages free 7-day trial signups, daily status checks,
and generates the customer dashboard.
"""

import uuid
from datetime import datetime, timedelta, date
from typing import Optional
from src.config import settings, logger
from src.database.connection import execute_query, execute_write
from src.modules.chatbot_engine import generate_embed_code, get_conversation_count_for_business
from src.modules.email_sequences import send_sequence_email


PILOT_DAYS = 7


def create_pilot_business(lead_id: int, owner_name: str, owner_email: str) -> Optional[dict]:
    """
    Create a new business record from a lead, activating their free pilot.
    Generates unique embed code and returns the business record.
    """
    try:
        # Get the lead
        leads = execute_query("SELECT * FROM leads WHERE id = ?", (lead_id,))
        if not leads:
            logger.error("Lead %d not found for pilot creation", lead_id)
            return None
        lead = leads[0]

        # Calculate trial end date
        trial_ends_at = (datetime.utcnow() + timedelta(days=PILOT_DAYS)).isoformat()

        # Create business record first to get the real auto-increment ID
        biz_id = execute_write(
            """INSERT INTO businesses
               (lead_id, business_name, owner_name, owner_email, website,
                status, trial_ends_at, payment_status)
               VALUES (?, ?, ?, ?, ?, 'trial', ?, 'unpaid')""",
            (
                lead_id,
                lead["business_name"],
                owner_name,
                owner_email,
                lead.get("website", ""),
                trial_ends_at,
            ),
        )

        # Generate embed code using the real business ID, then update
        embed_code = generate_embed_code(biz_id, lead["business_name"])
        execute_write(
            "UPDATE businesses SET chatbot_embed_code = ? WHERE id = ?",
            (embed_code, biz_id),
        )

        # Update lead status
        execute_write(
            "UPDATE leads SET status = 'pilot', updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), lead_id),
        )

        logger.info("Pilot created for %s (business_id=%d)", lead["business_name"], biz_id)
        return {
            "id": biz_id,
            "business_name": lead["business_name"],
            "embed_code": embed_code,
            "trial_ends_at": trial_ends_at,
        }

    except Exception as e:
        logger.error("Failed to create pilot business: %s", e)
        return None


def update_business_config(business_id: int, **kwargs) -> bool:
    """Update business configuration fields."""
    allowed_fields = {"services", "hours", "phone", "owner_email", "owner_name", "email"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    values.append(business_id)

    try:
        execute_write(
            f"UPDATE businesses SET {set_clause} WHERE id = ?",
            tuple(values),
        )
        return True
    except Exception as e:
        logger.error("Failed to update business %d: %s", business_id, e)
        return False


def get_pilot_days_remaining(business: dict) -> int:
    """Return days remaining in the pilot trial."""
    trial_end = business.get("trial_ends_at")
    if not trial_end:
        return 0

    try:
        end_date = datetime.fromisoformat(trial_end)
        remaining = (end_date - datetime.utcnow()).days
        return max(0, remaining)
    except Exception:
        return 0


def get_pilot_day(business: dict) -> int:
    """Return which day of the pilot we're on (1-based)."""
    created = business.get("created_at")
    if not created:
        return 0

    try:
        created_date = datetime.fromisoformat(created).date()
        today = date.today()
        elapsed = (today - created_date).days
        return min(elapsed + 1, PILOT_DAYS + 1)  # Day 8 = trial ended
    except Exception:
        return 0


def get_business_dashboard(business_id: int) -> Optional[dict]:
    """Generate dashboard data for a business."""
    businesses = execute_query("SELECT * FROM businesses WHERE id = ?", (business_id,))
    if not businesses:
        return None
    biz = businesses[0]

    conversations = execute_query(
        "SELECT * FROM conversations WHERE business_id = ? ORDER BY created_at DESC LIMIT 20",
        (business_id,),
    )

    leads_captured = execute_query(
        "SELECT COUNT(*) as count FROM conversations WHERE business_id = ?",
        (business_id,),
    )[0]["count"]

    days_remaining = get_pilot_days_remaining(biz)
    pilot_day = get_pilot_day(biz)

    return {
        "business": dict(biz),
        "conversations": [dict(c) for c in conversations],
        "leads_captured": leads_captured,
        "days_remaining": days_remaining,
        "pilot_day": pilot_day,
        "is_active": biz["status"] in ("trial", "active"),
    }


def run_daily_pilot_checks() -> dict:
    """
    Daily job that checks all pilot businesses and sends appropriate emails.
    This is the core automation that runs on a schedule.
    """
    logger.info("=" * 50)
    logger.info("DAILY PILOT CHECKS RUNNING")
    logger.info("=" * 50)

    results = {
        "checked": 0,
        "day1_welcome": 0,
        "day3_value": 0,
        "day5_invoice": 0,
        "day6_reminder": 0,
        "day7_decision": 0,
        "expired": 0,
    }

    businesses = execute_query(
        "SELECT * FROM businesses WHERE status IN ('trial', 'active', 'grace')"
    )

    for biz in businesses:
        results["checked"] += 1
        biz_id = biz["id"]
        pilot_day = get_pilot_day(biz)
        owner_email = biz.get("owner_email", "")
        biz_name = biz.get("business_name", "Your Business")

        if not owner_email:
            logger.warning("Business %d has no owner email, skipping pilot emails", biz_id)
            continue

        try:
            if biz["status"] == "trial":
                if pilot_day == 1:
                    # Day 1: Welcome email with setup instructions
                    success = send_sequence_email(
                        template_name="pilot_welcome",
                        variables={
                            "owner_name": biz.get("owner_name", "there"),
                            "business_name": biz_name,
                            "business_id": biz_id,
                            "embed_code": biz.get("chatbot_embed_code", ""),
                        },
                        to=owner_email,
                        subject=f"Welcome to {settings.APP_NAME}! Your 7-Day Pilot Starts Now",
                        business_id=biz_id,
                    )
                    if success:
                        results["day1_welcome"] += 1

                elif pilot_day == 3:
                    # Day 3: Value email with conversation count
                    conv_count = get_conversation_count_for_business(biz_id)
                    success = send_sequence_email(
                        template_name="pilot_day3_value",
                        variables={
                            "owner_name": biz.get("owner_name", "there"),
                            "business_name": biz_name,
                            "business_id": biz_id,
                            "conversations_count": conv_count,
                        },
                        to=owner_email,
                        subject=f"Your {settings.APP_NAME} Pilot: {conv_count} Conversations Captured!",
                        business_id=biz_id,
                    )
                    if success:
                        results["day3_value"] += 1

                elif pilot_day == 5:
                    # Day 5: Invoice request
                    success = send_sequence_email(
                        template_name="pilot_day5_invoice",
                        variables={
                            "owner_name": biz.get("owner_name", "there"),
                            "business_name": biz_name,
                            "business_id": biz_id,
                        },
                        to=owner_email,
                        subject=f"Continue After Your Trial — ${settings.MONTHLY_PRICE}/Month",
                        business_id=biz_id,
                    )
                    if success:
                        results["day5_invoice"] += 1

                elif pilot_day == 6:
                    # Day 6: Reminder
                    success = send_sequence_email(
                        template_name="pilot_day6_reminder",
                        variables={
                            "owner_name": biz.get("owner_name", "there"),
                            "business_name": biz_name,
                            "business_id": biz_id,
                        },
                        to=owner_email,
                        subject="⏰ Your Pilot Ends Tomorrow!",
                        business_id=biz_id,
                    )
                    if success:
                        results["day6_reminder"] += 1

                elif pilot_day >= 8:
                    # Trial ended, check payment status
                    if biz["payment_status"] != "paid":
                        # Day 7+: Decision email
                        send_sequence_email(
                            template_name="pilot_day7_decision",
                            variables={
                                "owner_name": biz.get("owner_name", "there"),
                                "business_name": biz_name,
                                "business_id": biz_id,
                            },
                            to=owner_email,
                            subject="Your Free Pilot Has Ended — Here's What's Next",
                            business_id=biz_id,
                        )
                        results["day7_decision"] += 1

                        # Deactivate trial
                        execute_write(
                            "UPDATE businesses SET status = 'expired' WHERE id = ? AND status = 'trial'",
                            (biz_id,),
                        )
                        results["expired"] += 1

            # Monthly billing checks for active businesses
            elif biz["status"] == "active" and biz["payment_status"] == "paid":
                _check_monthly_billing(biz)

        except Exception as e:
            logger.error("Error in pilot check for business %d: %s", biz_id, e)

    logger.info("Daily pilot check results: %s", results)
    return results


def _check_monthly_billing(biz: dict) -> None:
    """Check if monthly billing is due for an active business.
    Fires each email type only once per cycle by checking business status.
    """
    try:
        biz_id = biz["id"]
        owner_email = biz.get("owner_email", "")
        due_date_str = biz.get("monthly_due_date", "")
        biz_name = biz.get("business_name", "")

        if not due_date_str or not owner_email:
            return

        # Parse the due date (format: YYYY-MM-DD)
        due_parts = due_date_str.split("-")
        if len(due_parts) != 3:
            return

        due_day = int(due_parts[2])
        today = date.today()

        # Day 25: Send reminder (only once per month)
        if today.day == 25 and biz["payment_status"] == "paid":
            # Check we haven't already sent a reminder this month
            recent_reminders = execute_query(
                """SELECT COUNT(*) as count FROM emails
                   WHERE business_id = ? AND template_name = 'billing_reminder'
                   AND strftime('%Y-%m', sent_at) = strftime('%Y-%m', 'now')""",
                (biz_id,),
            )
            if recent_reminders and recent_reminders[0]["count"] == 0:
                send_sequence_email(
                    template_name="billing_reminder",
                    variables={
                        "owner_name": biz.get("owner_name", "there"),
                        "business_name": biz_name,
                        "due_date": f"{due_date_str}",
                        "business_id": biz_id,
                    },
                    to=owner_email,
                    subject=f"Payment Reminder — ${settings.MONTHLY_PRICE} Due Soon",
                    business_id=biz_id,
                )

        # Due date: Send "payment due" email (only once per month)
        if today.day == due_day and biz["payment_status"] == "paid":
            recent_due = execute_query(
                """SELECT COUNT(*) as count FROM emails
                   WHERE business_id = ? AND template_name = 'billing_due'
                   AND strftime('%Y-%m', sent_at) = strftime('%Y-%m', 'now')""",
                (biz_id,),
            )
            if recent_due and recent_due[0]["count"] == 0:
                send_sequence_email(
                    template_name="billing_due",
                    variables={
                        "owner_name": biz.get("owner_name", "there"),
                        "business_name": biz_name,
                        "business_id": biz_id,
                    },
                    to=owner_email,
                    subject=f"Payment Due — ${settings.MONTHLY_PRICE}",
                    business_id=biz_id,
                )

        # Grace period (3 days after due date): move to grace status (once)
        if today.day == due_day + 3 and biz["status"] == "active":
            execute_write(
                "UPDATE businesses SET status = 'grace', payment_status = 'pending' WHERE id = ? AND status = 'active'",
                (biz_id,),
            )
            logger.info("Business %d moved to grace period", biz_id)

        # Overdue (after grace period): deactivate (once)
        if today.day >= due_day + 6 and biz["status"] in ("active", "grace"):
            execute_write(
                "UPDATE businesses SET status = 'expired' WHERE id = ? AND status IN ('active', 'grace')",
                (biz_id,),
            )
            send_sequence_email(
                template_name="deactivation_notice",
                variables={
                    "owner_name": biz.get("owner_name", "there"),
                    "business_name": biz_name,
                    "business_id": biz_id,
                },
                to=owner_email,
                subject="Your Chatbot Has Been Paused",
                business_id=biz_id,
            )
            logger.info("Business %d deactivated for non-payment", biz_id)

    except Exception as e:
        logger.error("Monthly billing check error: %s", e)
