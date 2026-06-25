"""
LeadCapture AI — MODULE 1: Lead Finder
Scrapes Google Places API for HVAC/plumbing/roofing businesses.
Filters: has_website=true, rating>=4.0, review_count>=10
Deduplicates by phone+website.
Rate-limited and fully logged.
"""

import time
import hashlib
from typing import Optional
import httpx
from src.config import settings, logger
from src.database.connection import execute_query, execute_write

# Search keywords by trade
SEARCH_KEYWORDS = {
    "hvac": ["HVAC contractor", "heating and cooling", "air conditioning repair", "furnace repair"],
    "plumbing": ["plumber", "plumbing contractor", "drain cleaning", "water heater repair"],
    "roofing": ["roofer", "roofing contractor", "roof repair", "roof replacement"],
}

# Rate limiting: max 1 request per 1.2 seconds (50 QPM safe zone)
MIN_DELAY_SECONDS = 1.2


def _make_request(client: httpx.Client, url: str, params: dict) -> Optional[dict]:
    """Make an HTTP request with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "OK":
                return data
            elif data.get("status") == "ZERO_RESULTS":
                return {"results": []}
            elif data.get("status") == "OVER_QUERY_LIMIT":
                logger.warning("Google Places API quota exceeded. Waiting 60s...")
                time.sleep(60)
                continue
            else:
                logger.error("Google Places API error: %s", data.get("status", "UNKNOWN"))
                return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error("API key invalid or restricted. Check GOOGLE_PLACES_API_KEY.")
                return None
            logger.warning("HTTP error (attempt %d/%d): %s", attempt + 1, max_retries, e)
        except httpx.RequestError as e:
            logger.warning("Request error (attempt %d/%d): %s", attempt + 1, max_retries, e)

        if attempt < max_retries - 1:
            delay = (attempt + 1) * 2
            logger.info("Retrying in %ds...", delay)
            time.sleep(delay)

    return None


def _parse_places_result(business: dict, city: str, state: str) -> Optional[dict]:
    """Parse a single Google Places API result into our lead format."""
    name = business.get("name", "").strip()
    if not name:
        return None

    # Get website from Place Details result
    website = business.get("website", "")

    phone = business.get("formatted_phone_number", "") or business.get("international_phone_number", "")
    address = business.get("formatted_address", "") or business.get("vicinity", "")
    rating = business.get("rating", 0)
    review_count = business.get("user_ratings_total", 0)

    # Filter: must have website, rating>=4.0, review_count>=10
    if not website or rating < 4.0 or review_count < 10:
        return None

    return {
        "business_name": name,
        "website": website,
        "phone": phone,
        "address": address,
        "city": city,
        "state": state,
        "rating": rating,
        "review_count": review_count,
    }


def _fetch_place_details(client: httpx.Client, place_id: str) -> dict:
    """Fetch detailed info (website, phone) for a place."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,formatted_phone_number,website,formatted_address,rating,user_ratings_total",
        "key": settings.GOOGLE_PLACES_API_KEY,
    }
    data = _make_request(client, url, params)
    if data and data.get("result"):
        return data["result"]
    return {}


def search_city(city: str, state: str, radius_meters: int = 50000) -> list[dict]:
    """
    Search for leads in a given city/state.
    Iterates over all trade keywords and collects unique leads.
    """
    if not settings.GOOGLE_PLACES_API_KEY:
        logger.error("GOOGLE_PLACES_API_KEY is not set. Lead finder cannot run.")
        return []

    discovered = {}  # key: (phone, website) -> lead
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    trades_to_search = list(SEARCH_KEYWORDS.keys())

    logger.info("Starting lead search for %s, %s (trades: %s)", city, state, ", ".join(trades_to_search))

    with httpx.Client() as client:
        for trade in trades_to_search:
            keywords = SEARCH_KEYWORDS[trade]
            for keyword in keywords:
                query = f"{keyword} in {city}, {state}"
                logger.info("Searching: %s", query)

                params = {
                    "query": query,
                    "key": settings.GOOGLE_PLACES_API_KEY,
                }

                data = _make_request(client, base_url, params)
                if not data:
                    continue

                results = data.get("results", [])
                logger.info("Found %d results for '%s'", len(results), query)

                for place in results:
                    place_id = place.get("place_id", "")
                    if not place_id:
                        continue

                    # Get full details including website/phone
                    details = _fetch_place_details(client, place_id)
                    lead = _parse_places_result(details or place, city, state)
                    if lead:
                        dedup_key = (lead["phone"], lead["website"])
                        if dedup_key not in discovered:
                            discovered[dedup_key] = lead

                time.sleep(MIN_DELAY_SECONDS)

            # Extra delay between trade categories
            time.sleep(2)

    leads = list(discovered.values())
    logger.info("Found %d unique leads in %s, %s", len(leads), city, state)
    return leads


def save_leads(leads: list[dict]) -> tuple[int, int]:
    """Save leads to database. Returns (inserted, skipped)."""
    inserted = 0
    skipped = 0

    for lead in leads:
        try:
            # Check for duplicate by phone+website
            existing = execute_query(
                "SELECT id FROM leads WHERE phone = ? AND website = ?",
                (lead["phone"], lead["website"]),
            )
            if existing:
                skipped += 1
                continue

            execute_write(
                """INSERT INTO leads
                   (business_name, website, phone, address, city, state, rating, review_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'fresh')""",
                (
                    lead["business_name"],
                    lead["website"],
                    lead["phone"],
                    lead["address"],
                    lead["city"],
                    lead["state"],
                    lead["rating"],
                    lead["review_count"],
                ),
            )
            inserted += 1
        except Exception as e:
            logger.error("Failed to save lead '%s': %s", lead.get("business_name"), e)
            skipped += 1

    logger.info("Leads saved: %d inserted, %d skipped", inserted, skipped)
    return inserted, skipped


def run_lead_search(city: str, state: str, radius_meters: int = 50000) -> dict:
    """
    Full pipeline: search -> save -> return summary.
    """
    logger.info("=" * 50)
    logger.info("LEAD FINDER RUN: %s, %s", city, state)
    logger.info("=" * 50)

    leads = search_city(city, state, radius_meters)
    inserted, skipped = save_leads(leads)

    summary = {
        "city": city,
        "state": state,
        "found": len(leads),
        "inserted": inserted,
        "skipped": skipped,
    }
    logger.info("Lead finder summary: %s", summary)
    return summary
