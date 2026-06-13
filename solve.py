"""
Contact Finder — Minimal Slice (Stage B)

Reads challenge/data/companies.csv, queries the mocked providers in
challenge/mocks/enrichment_responses.json, and outputs one enriched row
per company with confidence scoring, provenance, and needs_human_review.

Scoring philosophy (adapted from CLARIFICATIONS.md):
  - Precision over recall: a high needs_human_review rate on genuinely
    hard rows is a GOOD result.
  - Confidence threshold: 70.  Below → needs_human_review = True and
    contact_email_or_phone is cleared.
  - Confidence is built additively from independent, explainable signals.

Role priority (from CLARIFICATIONS.md):
  AP / Accounts Payable  >  Owner / Founder  >  CFO / Finance  >  Manager / Fallback
"""

import csv
import json
import os
import re


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 70

GENERIC_EMAIL_PREFIXES = ("info@", "contact@", "sales@", "office@", "admin@",
                          "support@", "billing@", "hello@")

# Priority: lower number = better role.  Used when multiple contacts are
# available (future extension) and as a small confidence bonus.
ROLE_PRIORITY = {
    "ap manager":        1,
    "accounts payable":  1,
    "ap":                1,
    "owner":             2,
    "founder":           2,
    "president":         2,
    "cfo":               3,
    "finance lead":      3,
    "finance director":  3,
    "manager":           4,
    "office manager":    4,
    "registered agent":  5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_generic_email(email: str) -> bool:
    """Return True if the email starts with a generic/catch-all prefix."""
    lower = email.lower()
    return any(lower.startswith(p) for p in GENERIC_EMAIL_PREFIXES)


def _name_tokens(name: str) -> set[str]:
    """Split a name into normalised tokens, stripping dots and titles."""
    # Remove common titles and parentheticals
    cleaned = re.sub(r"\(.*?\)", "", name)  # "(manager)" → ""
    cleaned = re.sub(r"\b(dr|mr|mrs|ms|jr|sr)\b\.?", "", cleaned, flags=re.I)
    tokens = set(cleaned.lower().replace(".", " ").replace(",", " ").split())
    # Drop single-letter tokens (initials like "S." → "s") for intersection,
    # but keep them for initial-matching below.
    return tokens


def fuzzy_name_match(name_a: str, name_b: str) -> bool:
    """
    Return True if two name strings likely refer to the same person.

    Handles: exact match, shared surname ("S. Murphy" / "Sean Murphy"),
    nickname vs formal ("Bob Kowalski" / "Robert Kowalski" — shares
    "kowalski"), and title-stripped matches ("Dr. Emily Hart" / "Emily Hart").
    """
    if not name_a or not name_b:
        return False

    a_tokens = _name_tokens(name_a)
    b_tokens = _name_tokens(name_b)

    # Must share at least one substantive token (length > 1)
    shared = {t for t in a_tokens & b_tokens if len(t) > 1}
    if shared:
        return True

    # Check if one name's initial matches the other's first-letter token
    # e.g. "S." in name_b matches "Sean" in name_a
    a_initials = {t[0] for t in a_tokens if len(t) == 1}
    b_initials = {t[0] for t in b_tokens if len(t) == 1}
    a_firsts = {t[0] for t in a_tokens if len(t) > 1}
    b_firsts = {t[0] for t in b_tokens if len(t) > 1}

    if a_initials & b_firsts or b_initials & a_firsts:
        return True

    return False


def email_corroborates_name(email: str, name: str) -> bool:
    """
    Return True if the email's local part contains at least one substantive
    name part (length ≥ 2) from the given name.

    Examples:
      "d.ortega@..." + "Daniel Ortega" → True ("ortega" in local part)
      "karen@..."    + "Karen Liu"     → True ("karen" in local part)
      "info@..."     + "Angela Brooks" → False (generic, but this fn only
                                         checks name presence — caller also
                                         checks is_generic_email separately)
    """
    if not email or not name:
        return False
    local_part = email.split("@")[0].lower()
    for token in _name_tokens(name):
        if len(token) >= 2 and token in local_part:
            return True
    return False


def role_priority_rank(role: str) -> int:
    """Return a priority rank (lower = better) for the given role string."""
    if not role:
        return 99
    r = role.lower().strip()
    # Try exact match first, then substring matching
    if r in ROLE_PRIORITY:
        return ROLE_PRIORITY[r]
    for key, rank in ROLE_PRIORITY.items():
        if key in r or r in key:
            return rank
    return 6  # unknown role — still better than no role


def extract_role_from_listing_name(listing_name: str) -> str | None:
    """
    Some listing names embed a role in parentheses, e.g. 'Jeff (manager)'.
    Extract and return it, or None.
    """
    if not listing_name:
        return None
    match = re.search(r"\(([^)]+)\)", listing_name)
    if match:
        return match.group(1).strip().title()
    return None


# ---------------------------------------------------------------------------
# Core: Confidence Scoring
# ---------------------------------------------------------------------------

def compute_confidence(
    registry: dict | None,
    listing: dict | None,
    enrichment: dict | None,
) -> dict:
    """
    Build a confidence score from additive, explainable signals.

    Returns a dict with:
      contact_name, contact_role, contact_email_or_phone,
      confidence_score (0–100), sources (list of source_url strings),
      scoring_breakdown (dict of signal → points, for debugging).
    """
    r_name = (registry or {}).get("name")
    r_role = (registry or {}).get("role")
    l_name = (listing or {}).get("name")
    l_phone = (listing or {}).get("phone")
    e_email = (enrichment or {}).get("email")
    e_phone = (enrichment or {}).get("phone")
    e_conf = (enrichment or {}).get("provider_confidence", 0)

    # Collect provenance URLs
    sources = []
    for provider in (registry, listing, enrichment):
        if provider and provider.get("source_url"):
            sources.append(provider["source_url"])

    # ------------------------------------------------------------------
    # Determine best contact name and role
    # ------------------------------------------------------------------
    # Prefer registry name (authoritative), fall back to listing
    contact_name = r_name or l_name or ""

    # Role: registry role first, or try to extract from listing name
    listing_role = extract_role_from_listing_name(l_name) if l_name else None
    contact_role = r_role or listing_role or ""

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------
    source_count = sum(1 for s in (registry, listing, enrichment) if s)
    has_name = bool(r_name or l_name)
    has_contact_method = bool(e_email or e_phone or l_phone)
    names_agree = fuzzy_name_match(r_name, l_name) if (r_name and l_name) else False
    phones_agree = (l_phone and e_phone and l_phone == e_phone)
    email_corr = email_corroborates_name(e_email, contact_name) if (e_email and contact_name) else False
    generic_email = is_generic_email(e_email) if e_email else False
    names_conflict = (r_name and l_name and not fuzzy_name_match(r_name, l_name))

    # ------------------------------------------------------------------
    # Additive scoring  (each signal is independently explainable)
    # ------------------------------------------------------------------
    breakdown = {}

    # 1. Enrichment provider base (0–40 pts)
    #    If no enrichment, give a small base if we still have contact info
    if enrichment:
        base = round(e_conf * 0.45)
        breakdown["enrichment_base"] = base
    elif has_contact_method:
        base = 25
        breakdown["fallback_base"] = base
    else:
        base = 0
        breakdown["no_contact_base"] = base

    # 2. Name identified (+15)
    if has_name:
        breakdown["name_identified"] = 15

    # 3. Contact method available (+10)
    if has_contact_method:
        breakdown["contact_method"] = 10

    # 4. Multi-source name agreement (+15)
    if names_agree:
        breakdown["names_agree"] = 15

    # 5. Phone corroboration across providers (+10)
    if phones_agree:
        breakdown["phones_agree"] = 10

    # 6. Email corroborates name (+10)
    if email_corr:
        breakdown["email_corroborates"] = 10

    # 7. Role identified (+5)
    if contact_role:
        breakdown["role_identified"] = 5

    # Penalties
    if generic_email:
        breakdown["generic_email_penalty"] = -15

    if source_count == 1:
        breakdown["single_source_penalty"] = -5

    if names_conflict:
        breakdown["name_conflict_penalty"] = -15

    if not has_name:
        breakdown["no_name_penalty"] = -5

    score = base + sum(v for k, v in breakdown.items() if k != "enrichment_base"
                       and k != "fallback_base" and k != "no_contact_base")
    score += base  # base was set above but not included in breakdown sum — fix:
    # Recalculate cleanly:
    score = sum(breakdown.values())

    score = max(0, min(100, score))

    # ------------------------------------------------------------------
    # Best contact method: prefer email over phone
    # ------------------------------------------------------------------
    if e_email:
        contact_email_or_phone = e_email
    elif e_phone:
        contact_email_or_phone = e_phone
    elif l_phone:
        contact_email_or_phone = l_phone
    else:
        contact_email_or_phone = ""

    return {
        "contact_name": contact_name,
        "contact_role": contact_role,
        "contact_email_or_phone": contact_email_or_phone,
        "confidence_score": score,
        "sources": sources,
        "scoring_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def enrich_company(company_name: str, providers: dict) -> dict:
    """
    Take a company name and its mock-provider responses and return a
    fully-scored output row.
    """
    registry = providers.get("registry")
    listing = providers.get("listing")
    enrichment = providers.get("enrichment")

    result = compute_confidence(registry, listing, enrichment)

    needs_review = result["confidence_score"] < CONFIDENCE_THRESHOLD

    return {
        "company_name": company_name,
        "contact_name": result["contact_name"],
        "contact_role": result["contact_role"],
        "contact_email_or_phone": "" if needs_review else result["contact_email_or_phone"],
        "confidence_score": result["confidence_score"],
        "source": " | ".join(result["sources"]),
        "needs_human_review": needs_review,
    }


def process(
    csv_path: str = "challenge/data/companies.csv",
    mocks_path: str = "challenge/mocks/enrichment_responses.json",
    output_path: str = "output/results.csv",
):
    """End-to-end pipeline: read CSV → enrich → write results."""
    with open(mocks_path, "r") as f:
        mocks = json.load(f)

    results = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company = row["company_name"]
            providers = mocks.get(company, {})
            results.append(enrich_company(company, providers))

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    fieldnames = [
        "company_name", "contact_name", "contact_role",
        "contact_email_or_phone", "confidence_score",
        "source", "needs_human_review",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Print summary
    total = len(results)
    confident = sum(1 for r in results if not r["needs_human_review"])
    review = total - confident
    print(f"Processed {total} companies -> {confident} confident, {review} need human review.")
    print(f"Output written to {output_path}")


if __name__ == "__main__":
    process()
