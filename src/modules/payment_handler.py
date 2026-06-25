"""
LeadCapture AI — MODULE 5: Payment & Activation
Manual Wise payment verification system.
No Stripe — admin marks payments as received via Wise transfers.
Manages billing cycles, grace periods, and reactivation.
"""

from datetime import datetime, date, timedelta
from typing import Optional
from src.config import settings, logger
from src.database.connection import execute_query, execute_write
from src.modules.email_sequences import send_sequence_email


def record_payment(business_id: int, amount: float, wise_reference: str = "") -> Optional[int]:
    """Record a new payment record (pending verification)."""
    try:
        payment_id = execute_write(
            """INSERT INTO payments (business_id, amount, wise_reference, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (business_id, amount, wise_reference, datetime.utcnow().isoformat()),
        )
        logger.info("Payment recorded: %d for business %d ($%.2f)", payment_id, business_id, amount)

        # Update business payment status
        execute_write(
            "UPDATE businesses SET payment_status = 'pending' WHERE id = ?",
            (business_id,),
        )

        return payment_id
    except Exception as e:
        logger.error("Failed to record payment: %s", e)
        return None


def verify_payment(payment_id: int) -> bool:
    """
    Admin marks a payment as verified/paid.
    This is the manual Wise verification step.
    """
    try:
        payments = execute_query(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        )
        if not payments:
            logger.error("Payment %d not found", payment_id)
            return False

        payment = payments[0]

        # Update payment status
        execute_write(
            "UPDATE payments SET status = 'paid', verified_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), payment_id),
        )

        # Calculate monthly due date (e.g., 15th of NEXT month)
        today = date.today()
        due_day = 15  # Default billing day
        next_month = today.month + 1
        next_year = today.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        monthly_due = f"{next_year}-{next_month:02d}-{due_day:02d}"

        # Activate the business
        biz_id = payment["business_id"]
        execute_write(
            """UPDATE businesses SET
               payment_status = 'paid',
               status = 'active',
               monthly_due_date = ?
               WHERE id = ?""",
            (monthly_due, biz_id),
        )

        logger.info("Payment %d verified. Business %d activated.", payment_id, biz_id)

        # Send activation welcome email
        biz = execute_query("SELECT * FROM businesses WHERE id = ?", (biz_id,))
        if biz:
            biz = biz[0]
            owner_email = biz.get("owner_email", "")
            if owner_email:
                send_sequence_email(
                    template_name="activation_welcome",
                    variables={
                        "owner_name": biz.get("owner_name", "there"),
                        "business_name": biz.get("business_name", "Your Business"),
                        "business_id": biz_id,
                        "monthly_due_date": monthly_due,
                    },
                    to=owner_email,
                    subject=f"Welcome to {settings.APP_NAME}! Your Chatbot is Active",
                    business_id=biz_id,
                )

        return True

    except Exception as e:
        logger.error("Failed to verify payment %d: %s", payment_id, e)
        return False


def reject_payment(payment_id: int) -> bool:
    """Mark a payment as failed."""
    try:
        execute_write(
            "UPDATE payments SET status = 'failed' WHERE id = ?",
            (payment_id,),
        )
        logger.info("Payment %d marked as failed.", payment_id)
        return True
    except Exception as e:
        logger.error("Failed to reject payment %d: %s", payment_id, e)
        return False


def get_pending_payments() -> list[dict]:
    """Get all pending payments for admin review."""
    return execute_query(
        """SELECT p.*, b.business_name, b.owner_name, b.owner_email
           FROM payments p
           JOIN businesses b ON p.business_id = b.id
           WHERE p.status = 'pending'
           ORDER BY p.created_at DESC"""
    )


def get_all_payments(limit: int = 50) -> list[dict]:
    """Get recent payments."""
    return execute_query(
        """SELECT p.*, b.business_name, b.owner_name
           FROM payments p
           JOIN businesses b ON p.business_id = b.id
           ORDER BY p.created_at DESC LIMIT ?""",
        (limit,),
    )


def deactivate_business(business_id: int) -> bool:
    """Deactivate a business (pause chatbot)."""
    try:
        execute_write(
            "UPDATE businesses SET status = 'expired' WHERE id = ?",
            (business_id,),
        )
        logger.info("Business %d deactivated.", business_id)

        # Send deactivation notice
        biz = execute_query("SELECT * FROM businesses WHERE id = ?", (business_id,))
        if biz:
            biz = biz[0]
            owner_email = biz.get("owner_email", "")
            if owner_email:
                send_sequence_email(
                    template_name="deactivation_notice",
                    variables={
                        "owner_name": biz.get("owner_name", "there"),
                        "business_name": biz.get("business_name", "Your Business"),
                        "business_id": business_id,
                    },
                    to=owner_email,
                    subject="Your Chatbot Has Been Paused",
                    business_id=business_id,
                )

        return True
    except Exception as e:
        logger.error("Failed to deactivate business %d: %s", business_id, e)
        return False


def reactivate_business(business_id: int) -> bool:
    """
    Reactivate an expired business.
    They need to have paid or need new payment.
    """
    try:
        biz = execute_query("SELECT * FROM businesses WHERE id = ?", (business_id,))
        if not biz:
            return False
        biz = biz[0]

        if biz["payment_status"] == "paid":
            # Was paid before expiry, reactivate
            execute_write(
                "UPDATE businesses SET status = 'active' WHERE id = ?",
                (business_id,),
            )
            logger.info("Business %d reactivated (was paid).", business_id)
            return True
        else:
            # Needs payment first
            logger.info("Business %d needs payment to reactivate.", business_id)
            return False

    except Exception as e:
        logger.error("Failed to reactivate business %d: %s", business_id, e)
        return False


def get_mrr() -> float:
    """Calculate Monthly Recurring Revenue."""
    active = execute_query(
        "SELECT COUNT(*) as count FROM businesses WHERE status = 'active'"
    )
    count = active[0]["count"] if active else 0
    return count * settings.MONTHLY_PRICE


def get_revenue_stats() -> dict:
    """Get revenue summary statistics."""
    total_payments = execute_query(
        "SELECT COALESCE(SUM(amount), 0) as total FROM payments WHERE status = 'paid'"
    )
    this_month = execute_query(
        """SELECT COALESCE(SUM(amount), 0) as total FROM payments
           WHERE status = 'paid'
           AND strftime('%Y-%m', verified_at) = strftime('%Y-%m', 'now')"""
    )

    return {
        "total_revenue": total_payments[0]["total"] if total_payments else 0,
        "monthly_revenue": this_month[0]["total"] if this_month else 0,
        "mrr": get_mrr(),
    }
