# PLAN.md

## Architecture
The system will be a command-line script (likely Node.js/TypeScript or Python) that processes the input CSV sequentially.
- **Data Ingestion**: A CSV parser reads `data/companies.csv`, emitting row objects (`company_name`, `mailing_address`).
- **Enrichment Pipeline**: For each row, the system orchestrates calls across multiple `ContactProvider` interfaces (abstractions over the mock APIs). It aggregates the responses.
- **Scoring Engine**: Evaluates the collected contact points against our confidence logic to select the best candidate.
- **Output Formatter**: Generates a final CSV or JSON with the required columns (`contact_name`, `contact_role`, `contact_email_or_phone`, `confidence_score`, `source`, `needs_human_review`).

## Sources & strategy
In a real-world scenario, I would use:
1. **Business Registries (e.g., OpenCorporates, Secretary of State APIs)**: Highly reliable for finding the legal owner or registered agent. Good provenance, but lacks direct emails/phones.
2. **Professional Networks (e.g., LinkedIn Company & People Search)**: Excellent for identifying current titles (CFO, VP Finance, Owner). Prone to stale data if users don't update profiles.
3. **B2B Enrichment APIs (e.g., Apollo, Clearbit, ZoomInfo)**: Best for acquiring contact details (emails, direct dials) once a name or domain is identified.
*Strategy:* First, find the company domain and key personnel names using registries/networks. Then, query enrichment APIs with those names and domains to get verifiable contact information.

## Quality
- **Dedupe approach**: Normalize emails (lowercase, strip whitespace) and phone numbers (E.164 format). Merge records that share the same contact info, combining their source lists.
- **Confidence scoring**:
  - `90-100`: Match corroborated by multiple independent sources (e.g., Registry lists Owner, Enrichment API provides verified email).
  - `70-89`: Single strong source with high internal verification (e.g., Apollo verified email for a finance role).
  - `40-69`: Deduced email (e.g., pattern matching like first.last@company.com) without hard verification, or generic role.
  - `<40`: Catch-all or unverifiable.
- **Provenance**: Every output row will append to a `source` array containing the names of the providers that contributed to the final selection.
- **"Cannot-verify" & False-positive risk**: If the top contact has a score below the threshold (to be determined from CLARIFICATIONS), we explicitly output `needs_human_review = true`. A false negative (missing a contact) is generally preferred over a false positive (harassing the wrong person or a generic support inbox about unpaid enterprise bills).

## Privacy / compliance
- **WILL DO**: Target strictly B2B professional contact information. Focus on decision-makers relevant to the context (billing/AP/owners). Respect conceptual "do-not-call" constraints and honor opt-out protocols in outreach.
- **WILL NOT DO**: No scraping of personal social media (Facebook/Instagram). No acquisition of personal webmail addresses (gmail.com, yahoo.com) unless explicitly used as the business contact. We will not use sketchy, non-compliant data brokers.

## Clarifying questions

1. **Question:** What is the minimum acceptable confidence threshold for automated outreach?
   - **Why it matters:** It dictates the balance between reach and precision. A high threshold means more manual review; a low threshold risks emailing the wrong person about sensitive unpaid bills.
   - **Default assumption:** I will assume a threshold of 70% is required to bypass human review.
   - **What changes if answered:** I will adjust the strictness of the scoring engine and determine whether generic emails (e.g., billing@company.com) can bypass review.

2. **Question:** If we identify multiple verified decision-makers (e.g., an Owner and a CFO), who is the primary target?
   - **Why it matters:** To avoid spamming multiple executives simultaneously, the system needs a deterministic ranking for roles.
   - **Default assumption:** Prioritize CFO / Accounts Payable over the Owner for larger accounts, but Owner for very small ones.
   - **What changes if answered:** The sorting logic in the pipeline will assign weights to specific job titles to bubble up the preferred contact.

3. **Question:** Are there specific compliance regimes or regional restrictions we fall under for this specific campaign?
   - **Why it matters:** It determines if we can legally gather and use phone numbers for cold outreach, or if we must rely strictly on email.
   - **Default assumption:** Standard US B2B rules apply (CAN-SPAM). Cold emails are permitted with opt-outs, but phone numbers are secondary.
   - **What changes if answered:** If strict telemarketing laws apply, we might drop phone number enrichment entirely to save costs and eliminate risk.
