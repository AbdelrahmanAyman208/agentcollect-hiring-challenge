"""
Tests for the Contact Finder solution.

Covers: helper functions, confidence scoring logic, edge cases,
and the CLARIFICATIONS.md threshold behaviour.
"""

import json
import os
import csv
import tempfile
import pytest

from solve import (
    is_generic_email,
    normalize_email,
    normalize_phone,
    fuzzy_name_match,
    email_corroborates_name,
    role_priority_rank,
    extract_role_from_listing_name,
    compute_confidence,
    enrich_company,
    process,
    CONFIDENCE_THRESHOLD,
)


# ===================================================================
# Helper function tests
# ===================================================================

class TestNormalizeEmail:
    def test_lowercase_and_strip(self):
        assert normalize_email("  TEST@Example.com ") == "test@example.com"
        
    def test_none_or_empty(self):
        assert normalize_email(None) == ""
        assert normalize_email("") == ""


class TestNormalizePhone:
    def test_extract_digits(self):
        assert normalize_phone("(555) 123-4567") == "+15551234567"
        
    def test_e164_fallback(self):
        assert normalize_phone("1-800-555-1234") == "+18005551234"
        assert normalize_phone("+44 20 7123 1234") == "+442071231234"
        
    def test_none_or_empty(self):
        assert normalize_phone(None) == ""
        assert normalize_phone("") == ""


class TestIsGenericEmail:
    def test_generic_prefixes(self):
        assert is_generic_email("info@company.com") is True
        assert is_generic_email("contact@company.com") is True
        assert is_generic_email("sales@company.com") is True
        assert is_generic_email("office@sunbelt.com") is True

    def test_personal_emails(self):
        assert is_generic_email("d.ortega@company.com") is False
        assert is_generic_email("karen@bayview.com") is False
        assert is_generic_email("bob@ironcladweld.com") is False

    def test_case_insensitive(self):
        assert is_generic_email("INFO@company.com") is True
        assert is_generic_email("Sales@Company.com") is True


class TestFuzzyNameMatch:
    def test_exact_match(self):
        assert fuzzy_name_match("Daniel Ortega", "Daniel Ortega") is True

    def test_shared_surname(self):
        # "S. Murphy" and "Sean Murphy" share "Murphy"
        assert fuzzy_name_match("S. Murphy", "Sean Murphy") is True

    def test_nickname_vs_formal(self):
        # "Bob Kowalski" and "Robert Kowalski" share "Kowalski"
        assert fuzzy_name_match("Bob Kowalski", "Robert Kowalski") is True

    def test_title_stripped(self):
        assert fuzzy_name_match("Dr. Emily Hart", "Emily Hart") is True

    def test_completely_different(self):
        assert fuzzy_name_match("Tina Alvarez", "Marcus Webb") is False

    def test_none_inputs(self):
        assert fuzzy_name_match(None, "Sean Murphy") is False
        assert fuzzy_name_match("Sean Murphy", None) is False
        assert fuzzy_name_match(None, None) is False

    def test_empty_strings(self):
        assert fuzzy_name_match("", "Sean Murphy") is False
        assert fuzzy_name_match("Sean Murphy", "") is False


class TestEmailCorroboratesName:
    def test_last_name_in_email(self):
        assert email_corroborates_name("d.ortega@company.com", "Daniel Ortega") is True

    def test_first_name_in_email(self):
        assert email_corroborates_name("karen@bayview.com", "Karen Liu") is True

    def test_full_name_in_email(self):
        assert email_corroborates_name("emily.hart@vet.com", "Dr. Emily Hart") is True

    def test_no_match(self):
        assert email_corroborates_name("info@company.com", "Angela Brooks") is False

    def test_none_inputs(self):
        assert email_corroborates_name(None, "Daniel Ortega") is False
        assert email_corroborates_name("d.ortega@co.com", None) is False


class TestRolePriorityRank:
    def test_ap_is_highest_priority(self):
        assert role_priority_rank("AP Manager") < role_priority_rank("Owner")

    def test_owner_over_cfo(self):
        assert role_priority_rank("Owner") < role_priority_rank("CFO")

    def test_cfo_over_manager(self):
        assert role_priority_rank("CFO") < role_priority_rank("Manager")

    def test_unknown_role(self):
        assert role_priority_rank("Intern") > role_priority_rank("Manager")

    def test_no_role(self):
        assert role_priority_rank("") == 99
        assert role_priority_rank(None) == 99


class TestExtractRoleFromListingName:
    def test_manager_in_parens(self):
        assert extract_role_from_listing_name("Jeff (manager)") == "Manager"

    def test_no_parens(self):
        assert extract_role_from_listing_name("Daniel Ortega") is None

    def test_none_input(self):
        assert extract_role_from_listing_name(None) is None


# ===================================================================
# Confidence scoring tests — mirrors the mock data scenarios
# ===================================================================

class TestComputeConfidence:
    """Test compute_confidence against the specific scenarios in the mocks."""

    def test_high_confidence_three_sources_agree(self):
        """Cedar Ridge: 3 sources, names agree, personal email — should be high."""
        result = compute_confidence(
            registry={"name": "Daniel Ortega", "role": "Owner", "source_url": "mock://reg"},
            listing={"name": "Daniel Ortega", "phone": "+1-402-555-0148", "source_url": "mock://list"},
            enrichment={"email": "d.ortega@cedarridgeplumbing.com", "phone": None,
                        "provider_confidence": 84, "source_url": "mock://enr"},
        )
        assert result["confidence_score"] >= CONFIDENCE_THRESHOLD
        assert result["contact_name"] == "Daniel Ortega"
        assert result["contact_role"] == "Owner"
        assert len(result["sources"]) == 3

    def test_generic_email_no_name_scores_low(self):
        """Sunbelt: generic office@ email, no name — must score below threshold."""
        result = compute_confidence(
            registry=None,
            listing={"name": None, "phone": "+1-480-555-0133", "source_url": "mock://list"},
            enrichment={"email": "office@sunbeltroofingaz.com", "phone": "+1-480-555-0133",
                        "provider_confidence": 66, "source_url": "mock://enr"},
        )
        assert result["confidence_score"] < CONFIDENCE_THRESHOLD

    def test_single_weak_enrichment_scores_low(self):
        """Riverside: enrichment-only, generic info@ email, low conf — very low."""
        result = compute_confidence(
            registry=None,
            listing=None,
            enrichment={"email": "info@riversideprint.biz", "phone": None,
                        "provider_confidence": 41, "source_url": "mock://enr"},
        )
        assert result["confidence_score"] < 30

    def test_no_sources_at_all(self):
        """Companies with no mock data should score 0."""
        result = compute_confidence(registry=None, listing=None, enrichment=None)
        assert result["confidence_score"] == 0
        assert result["contact_name"] == ""
        assert result["contact_email_or_phone"] == ""

    def test_conflicting_names_penalised(self):
        """Coastal Breeze: registry says Tina Alvarez, listing says Marcus Webb."""
        result = compute_confidence(
            registry={"name": "Tina Alvarez", "role": "Manager", "source_url": "mock://reg"},
            listing={"name": "Marcus Webb", "phone": "+1-941-555-0146", "source_url": "mock://list"},
            enrichment=None,
        )
        assert result["confidence_score"] < CONFIDENCE_THRESHOLD

    def test_registry_only_no_contact_method(self):
        """Northgate: registry has name+role but no phone or email."""
        result = compute_confidence(
            registry={"name": "Thomas Reed", "role": "Registered Agent", "source_url": "mock://reg"},
            listing=None,
            enrichment=None,
        )
        assert result["confidence_score"] < CONFIDENCE_THRESHOLD
        assert result["contact_email_or_phone"] == ""


# ===================================================================
# Integration: enrich_company + threshold behaviour
# ===================================================================

class TestEnrichCompany:
    def test_below_threshold_clears_contact(self):
        """When confidence < 70, contact info must be cleared and needs_human_review = True."""
        row = enrich_company("Test Co", {
            "enrichment": {"email": "info@test.com", "phone": None,
                           "provider_confidence": 30, "source_url": "mock://enr"}
        })
        assert row["needs_human_review"] is True
        assert row["contact_email_or_phone"] == ""

    def test_above_threshold_emits_contact(self):
        """When confidence >= 70, contact info is emitted and needs_human_review = False."""
        row = enrich_company("Strong Co", {
            "registry": {"name": "Alice Smith", "role": "Owner", "source_url": "mock://reg"},
            "listing": {"name": "Alice Smith", "phone": "+1-555-0100", "source_url": "mock://list"},
            "enrichment": {"email": "alice@strong.com", "phone": "+1-555-0100",
                           "provider_confidence": 90, "source_url": "mock://enr"},
        })
        assert row["needs_human_review"] is False
        assert row["contact_email_or_phone"] != ""

    def test_provenance_always_present(self):
        """Every output row must have at least source attribution if any provider responded."""
        row = enrich_company("Some Co", {
            "listing": {"name": None, "phone": "+1-555-0100", "source_url": "mock://list"},
        })
        assert "mock://list" in row["source"]


# ===================================================================
# End-to-end: process function
# ===================================================================

class TestProcess:
    def test_end_to_end_with_real_fixtures(self, tmp_path):
        """Run the full pipeline against the actual mock data and verify output."""
        csv_path = os.path.join(
            os.path.dirname(__file__), "challenge", "data", "companies.csv"
        )
        mocks_path = os.path.join(
            os.path.dirname(__file__), "challenge", "mocks", "enrichment_responses.json"
        )
        output_path = str(tmp_path / "results.csv")

        process(csv_path=csv_path, mocks_path=mocks_path, output_path=output_path)

        # Verify the output file was created
        assert os.path.exists(output_path)

        with open(output_path, "r") as f:
            reader = list(csv.DictReader(f))

        # Should have all 30 companies from the CSV
        assert len(reader) == 30

        # Every row must have the required fields
        required_fields = {
            "company_name", "contact_name", "contact_role",
            "contact_email_or_phone", "confidence_score",
            "source", "needs_human_review",
        }
        for row in reader:
            assert set(row.keys()) == required_fields

        # Spot-checks
        cedar = next(r for r in reader if r["company_name"] == "Cedar Ridge Plumbing LLC")
        assert cedar["needs_human_review"] == "False"
        assert int(cedar["confidence_score"]) >= 70

        sunbelt = next(r for r in reader if r["company_name"] == "Sunbelt Roofing Co")
        assert sunbelt["needs_human_review"] == "True"
        assert int(sunbelt["confidence_score"]) < 70

        # Companies with no mock data should be flagged for review
        redwood = next(r for r in reader if r["company_name"] == "Redwood Cabinetry")
        assert redwood["needs_human_review"] == "True"
        assert int(redwood["confidence_score"]) == 0
