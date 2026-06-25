"""
LeadCapture AI — MODULE 3: Chatbot Engine
Custom AI chatbot using OpenAI GPT-4o-mini.
Server-Sent Events for real-time streaming.
Configurable per business with custom system prompts.
Stores all conversations in SQLite.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional, AsyncGenerator
from pydantic import BaseModel

from openai import AsyncOpenAI
from src.config import settings, logger
from src.database.connection import execute_query, execute_write
from src.modules.email_sequences import send_email


# Default system prompt template
SYSTEM_PROMPT_TEMPLATE = """You are a friendly and helpful assistant for {business_name}, a local service business.

Your job is to help website visitors:
1. Answer frequently asked questions about services, pricing, and availability
2. Book appointments by collecting lead information
3. Qualify leads by gathering essential details

IMPORTANT RULES:
- Be friendly, professional, and conversational
- Always try to collect: customer name, phone number, service needed, zip/postal code, and preferred time
- If someone asks for pricing, give a general range and offer to connect them with the team
- If someone seems ready to book, confirm their details and promise an email confirmation
- For complex questions you can't answer, say "Let me connect you with the team" (this will alert the business owner)
- Keep responses concise and helpful
- Business hours: {hours}
- Services offered: {services}
- Business phone: {phone}

When you collect a lead's information, confirm it back to them clearly before ending the conversation."""


class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str


class LeadInfo(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    service_needed: Optional[str] = None
    zip_code: Optional[str] = None
    preferred_time: Optional[str] = None


def get_or_create_client() -> AsyncOpenAI:
    """Get OpenAI client. Raises if API key not set."""
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set. Chatbot cannot run.")
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def get_business_config(business_id: int) -> Optional[dict]:
    """Get chatbot configuration for a business."""
    rows = execute_query(
        "SELECT * FROM businesses WHERE id = ? AND status IN ('trial', 'active')",
        (business_id,),
    )
    return rows[0] if rows else None


def get_system_prompt(business: dict) -> str:
    """Generate the system prompt for a specific business."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        business_name=business.get("business_name", "Your Business"),
        hours=business.get("hours", "Monday-Friday, 8am-6pm"),
        services=business.get("services", "HVAC, plumbing, and related services"),
        phone=business.get("phone", "(555) 123-4567"),
    )


def generate_embed_code(business_id: int, business_name: str) -> str:
    """Generate the chatbot embed snippet for a business website."""
    return f"""<!-- LeadCapture AI Chatbot - {business_name} -->
<script>
(function() {{
    var lc = document.createElement('script'); lc.async = true; lc.defer = true;
    lc.src = '{settings.APP_URL}/static/embed.js?business_id={business_id}&v={uuid.uuid4().hex[:8]}';
    var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(lc, s);
}})();
</script>
<!-- End LeadCapture AI Chatbot -->"""


async def stream_chat_response(
    business_id: int,
    conversation_id: int,
    user_message: str,
    conversation_history: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Stream a chatbot response using OpenAI streaming.
    Yields SSE-formatted text chunks.
    """
    business = get_business_config(business_id)
    if not business:
        yield f"data: {json.dumps({'error': 'Business not found or inactive'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        client = get_or_create_client()
    except ValueError as e:
        logger.error(str(e))
        yield f"data: {json.dumps({'error': 'Chatbot is not configured. Please contact support.'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    system_prompt = get_system_prompt(business)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=500,
            stream=True,
        )

        full_response = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                yield f"data: {json.dumps({'content': content})}\n\n"

        # Save the conversation
        _save_conversation_messages(conversation_id, user_message, full_response)

        # Check if we need to escalate (bot suggested connecting with team)
        if "let me connect you with the team" in full_response.lower():
            _trigger_escalation(business_id, conversation_id, business)

        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error("OpenAI streaming error for business %d: %s", business_id, e)
        yield f"data: {json.dumps({'error': 'Sorry, I encountered an error. Please try again.'})}\n\n"
        yield "data: [DONE]\n\n"


def create_conversation(business_id: int) -> int:
    """Create a new conversation record and return its ID."""
    conv_id = execute_write(
        "INSERT INTO conversations (business_id, messages_json, created_at) VALUES (?, '[]', ?)",
        (business_id, datetime.utcnow().isoformat()),
    )
    logger.info("Created conversation %d for business %d", conv_id, business_id)
    return conv_id


def _save_conversation_messages(conversation_id: int, user_msg: str, assistant_msg: str) -> None:
    """Append user and assistant messages to the conversation."""
    try:
        rows = execute_query(
            "SELECT messages_json FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        if not rows:
            return

        messages = json.loads(rows[0]["messages_json"])
        now = datetime.utcnow().isoformat()

        messages.append({"role": "user", "content": user_msg, "timestamp": now})
        messages.append({"role": "assistant", "content": assistant_msg, "timestamp": now})

        # Try to extract lead info from the conversation
        lead_info = _extract_lead_info(messages)
        if lead_info.get("name"):
            execute_write(
                """UPDATE conversations SET
                   customer_name = ?, customer_phone = ?, service_needed = ?,
                   zip_code = ?, preferred_time = ?, messages_json = ?
                   WHERE id = ?""",
                (
                    lead_info.get("name", ""),
                    lead_info.get("phone", ""),
                    lead_info.get("service_needed", ""),
                    lead_info.get("zip_code", ""),
                    lead_info.get("preferred_time", ""),
                    json.dumps(messages),
                    conversation_id,
                ),
            )
        else:
            execute_write(
                "UPDATE conversations SET messages_json = ? WHERE id = ?",
                (json.dumps(messages), conversation_id),
            )
    except Exception as e:
        logger.error("Failed to save conversation messages: %s", e)


def _extract_lead_info(messages: list[dict]) -> dict:
    """Basic heuristic extraction of lead info from conversation messages."""
    info = {}

    for msg in messages:
        content = msg.get("content", "").lower()

        # Name detection (simple heuristic)
        if "name is" in content:
            idx = content.find("name is") + 8
            info["name"] = content[idx:].split(".")[0].strip().title()

        # Phone detection
        phone_match = re.search(r'(\+?\d[\d\s\-\(\)]{7,}\d)', content)
        if phone_match:
            info["phone"] = phone_match.group(1).strip()

        # Zip code
        zip_match = re.search(r'\b(\d{5})\b', content)
        if zip_match:
            info["zip_code"] = zip_match.group(1)

    return info


def _trigger_escalation(business_id: int, conversation_id: int, business: dict) -> None:
    """Send escalation email to business owner when chatbot can't handle a request."""
    try:
        conv = execute_query(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        )
        if not conv:
            return

        conv = conv[0]
        owner_email = business.get("owner_email") or business.get("email", "")

        if not owner_email:
            logger.warning("No email for business %d, skipping escalation", business_id)
            return

        subject = f"🔔 Customer needs help — {conv.get('customer_name', 'Unknown')}"
        body = f"""
        <h3>Customer Requesting Live Assistance</h3>
        <p><strong>Customer:</strong> {conv.get('customer_name', 'Not provided')}</p>
        <p><strong>Phone:</strong> {conv.get('customer_phone', 'Not provided')}</p>
        <p><strong>Service Needed:</strong> {conv.get('service_needed', 'Not provided')}</p>
        <p><strong>Zip Code:</strong> {conv.get('zip_code', 'Not provided')}</p>
        <p><strong>Preferred Time:</strong> {conv.get('preferred_time', 'Not provided')}</p>
        <p><a href="{settings.APP_URL}/admin/conversations/{conversation_id}">View Full Conversation</a></p>
        """

        send_email(
            to=owner_email,
            subject=subject,
            html_body=body,
            business_id=business_id,
        )

        # Mark conversation as escalated
        execute_write(
            "UPDATE conversations SET status = 'escalated' WHERE id = ?",
            (conversation_id,),
        )

        logger.info("Escalation email sent for conversation %d", conversation_id)
    except Exception as e:
        logger.error("Failed to trigger escalation: %s", e)


def get_conversations_for_business(business_id: int, limit: int = 50) -> list[dict]:
    """Get recent conversations for a business."""
    return execute_query(
        "SELECT * FROM conversations WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
        (business_id, limit),
    )


def get_conversation_count_for_business(business_id: int) -> int:
    """Get total conversation count for a business."""
    rows = execute_query(
        "SELECT COUNT(*) as count FROM conversations WHERE business_id = ?",
        (business_id,),
    )
    return rows[0]["count"] if rows else 0
