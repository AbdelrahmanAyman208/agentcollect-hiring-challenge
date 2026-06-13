# PLAN.md

## Architecture
The system is designed as a pipeline that can scale to thousands of records via batching.

```text
[CSV Ingestion] → [Provider Orchestrator] → [Scoring Engine] → [Output Formatter]
      │                     │                       │                  │
Reads & chunks      Fan-out async calls       Applies rules      Emits CSV/JSON
validates state     to Registry/Listing       Role + Name        Flags for review
                    & Enrichment APIs         corroboration
```

- **Data Ingestion**: A CSV parser reads `data/companies.csv`, emitting row objects.
- **Enrichment Orchestrator**: Handles rate-limiting and fan-out API requests to multiple `ContactProvider` interfaces.
- **Scoring Engine**: Evaluates collected contact points additively against our confidence logic.
- **Output Formatter**: Generates a final CSV, explicitly flagging `needs_human_review`.

## Sources & strategy
In a real-world scenario, I would chain these sources to mitigate their individual failure modes:
1. **Business Registries (e.g., OpenCorporates)**: Good for legal owners. *Failure mode*: Often lists external registered agents (law firms) instead of actual owners. We must cross-reference the `mailing_address` to detect if the agent is at a distinct law firm address.
2. **Professional Networks (e.g., LinkedIn)**: Excellent for finding titles (CFO, VP Finance). *Failure mode*: Highly prone to stale data if users don't update profiles after leaving.
3. **B2B Enrichment APIs (e.g., Apollo, Clearbit)**: Best for acquiring contact details once a name is known. *Failure mode*: Often guesses emails using `first.last@domain.com` without hard verification.

*Strategy:* Use the CSV `company_name` and `mailing_address` state to query registries. Feed the verified names and the company domain into enrichment APIs to yield contact details. Corroborate the enrichment output against the registry name.

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

3. **Question:** If we find a contact via a single enrichment source with very high provider confidence (e.g., 99%), but we cannot corroborate them against a registry or listing, should we emit them or route to human review?
   - **Why it matters:** It defines our risk appetite. Enrichment APIs often overstate confidence. If we trust them blindly, we increase false positives (emailing the wrong person for debt collection).
   - **Default assumption:** I will assume multi-source corroboration is a hard requirement to bypass human review, and a single source is capped below the automation threshold.
   - **What changes if answered:** If you trust specific vendors deeply, I would add a "trusted vendor bypass" to the scoring engine that allows a single 99% enrichment score to auto-pass.
