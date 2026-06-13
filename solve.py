import csv
import json
import re

def calculate_score(company, providers):
    registry = providers.get("registry", {})
    listing = providers.get("listing", {})
    enrichment = providers.get("enrichment", {})

    r_name = registry.get("name")
    r_role = registry.get("role")
    
    l_name = listing.get("name")
    l_phone = listing.get("phone")

    e_email = enrichment.get("email")
    e_phone = enrichment.get("phone")
    e_conf = enrichment.get("provider_confidence", 0)

    score = 0
    contact_name = ""
    contact_role = ""
    contact_email_or_phone = ""
    sources = []

    if registry and registry.get("source_url"): sources.append(registry["source_url"])
    if listing and listing.get("source_url"): sources.append(listing["source_url"])
    if enrichment and enrichment.get("source_url"): sources.append(enrichment["source_url"])

    # Base names & roles
    contact_name = r_name or l_name or ""
    contact_role = r_role or ""

    # Check agreement
    name_agrees = False
    phone_agrees = False
    
    if r_name and l_name:
        # Check if they share at least one name part
        r_parts = set(r_name.lower().split())
        l_parts = set(l_name.lower().split())
        if r_parts.intersection(l_parts):
            name_agrees = True

    if e_email and contact_name:
        # check if email starts with first letter of name or something
        name_parts = contact_name.lower().replace(".", "").replace(",", "").split()
        if len(name_parts) > 0 and name_parts[0] in e_email.lower():
            name_agrees = True
        elif len(name_parts) > 1 and name_parts[-1] in e_email.lower():
            name_agrees = True

    if l_phone and e_phone and l_phone == e_phone:
        phone_agrees = True

    # Scoring logic
    if e_email or e_phone:
        # We have a contact method
        is_generic = e_email and any(g in e_email.lower() for g in ["info@", "contact@", "sales@", "office@"])
        
        base_score = e_conf
        if is_generic:
            base_score -= 30
        
        if name_agrees:
            score = max(base_score + 20, 90)
        elif phone_agrees:
            score = max(base_score + 15, 85)
        elif r_name and e_email and not name_agrees and not is_generic:
            # Conflicting or unverified name with email
            score = base_score - 10
        else:
            score = base_score
            
        contact_email_or_phone = e_email if e_email else e_phone
    elif l_phone:
        # Only listing phone
        contact_email_or_phone = l_phone
        score = 40
        if name_agrees:
            score = 60
    else:
        # No contact method
        score = 0

    # Adapt to CLARIFICATIONS.md: Role priority
    role_bonus = 0
    if contact_role:
        r_lower = contact_role.lower()
        if "ap" in r_lower or "payable" in r_lower or "cfo" in r_lower or "finance" in r_lower:
            role_bonus = 10
        elif "owner" in r_lower or "founder" in r_lower or "president" in r_lower:
            role_bonus = 5
            
    score += role_bonus

    score = min(max(int(score), 0), 100)
    
    return {
        "contact_name": contact_name,
        "contact_role": contact_role,
        "contact_email_or_phone": contact_email_or_phone,
        "confidence_score": score,
        "source": ", ".join(sources)
    }

def process():
    with open('challenge/mocks/enrichment_responses.json', 'r') as f:
        mocks = json.load(f)

    results = []
    with open('challenge/data/companies.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            company = row['company_name']
            providers = mocks.get(company, {})
            
            outcome = calculate_score(company, providers)
            
            needs_review = False
            if outcome["confidence_score"] < 70:
                needs_review = True
                outcome["contact_email_or_phone"] = ""
            
            results.append({
                "company_name": company,
                "contact_name": outcome["contact_name"],
                "contact_role": outcome["contact_role"],
                "contact_email_or_phone": outcome["contact_email_or_phone"],
                "confidence_score": outcome["confidence_score"],
                "source": outcome["source"],
                "needs_human_review": needs_review
            })

    with open('output.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "contact_name", "contact_role", "contact_email_or_phone", "confidence_score", "source", "needs_human_review"])
        writer.writeheader()
        writer.writerows(results)
    
    print("Done. Wrote to output.csv")

if __name__ == "__main__":
    process()
