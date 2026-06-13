# ABOUT.md

## Why this role
I am passionate about building intelligent systems that move beyond brittle scraping into reliable, context-aware data enrichment. The focus on verifiable, provenance-driven pipelines aligns with my philosophy of treating AI outputs as fallible signals that require rigorous validation.

## How you work with AI tools
I use LLMs (Claude, GPT-4) as high-level orchestrators and brainstorming partners, and tools like Copilot for boilerplate. However, I never trust an AI to invent data: I strictly limit its role to parsing, scoring, and routing data from verifiable sources. If an LLM suggests a probabilistic regex or unstructured extraction, I enforce hard fallbacks and explicit "needs_human_review" flags to ensure safety.

## Your last project (structured)
- **One ambiguity** you faced and how you resolved it: We lacked a clear priority order for targeting executives in a large enterprise client list. I resolved it by looking at past successful deals and defining a tiered fallback system (CFO > VP Finance > Director).
- **One tradeoff** you made and why: I chose to drop scraping LinkedIn via headless browsers in favor of a commercial enrichment API, trading higher operational cost for significantly better reliability and compliance.
- **One mistake** you made and what you changed: I initially merged duplicate records by taking the newest entry, which sometimes overwrote verified phone numbers with null values. I changed the logic to intelligently merge fields, preserving non-null values.
- **One review comment** that made you change your mind: A reviewer pointed out that my confidence scoring was a black box. I changed it from a complex neural-net model back to a simple, rule-based additive scoring system that the sales team could actually understand and debug.

## Anything you'd improve about THIS challenge or our CLAUDE.md
The separation of PLAN and BUILD is an excellent approach to filtering candidates. One improvement could be to include a mock "catch-all" or "honeypot" email in the `enrichment_responses.json` to explicitly test if candidates filter out known bad/spam-trap domains.
