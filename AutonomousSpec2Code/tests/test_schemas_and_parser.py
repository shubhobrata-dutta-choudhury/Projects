"""
Unit tests for Pillar 1 (Strict Pydantic Schemas) & Spec Ingestion Parser (JSON & Markdown).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spec2code.ingest.parser import parse_spec_file
from spec2code.schemas.code_ops_schema import FileModification, SearchReplacePatch
from spec2code.schemas.spec_schema import AcceptanceTestCase


def test_parse_all_sample_specs() -> None:
    """Verifies that both JSON and Markdown specs in `specs/` parse into valid FeatureSpec models."""
    spec1 = parse_spec_file("specs/01_rate_limiter.json")
    assert spec1.spec_id == "spec_01_rate_limiter"
    assert spec1.target_filename == "rate_limiter.py"
    assert len(spec1.acceptance_tests) == 3

    spec2 = parse_spec_file("specs/02_lru_cache_ttl.md")
    assert spec2.spec_id == "spec_02_lru_cache_ttl"
    assert spec2.target_filename == "lru_cache_ttl.py"
    assert spec2.difficulty == "hard"
    assert len(spec2.acceptance_tests) == 3

    spec3 = parse_spec_file("specs/03_interval_merger.json")
    assert spec3.spec_id == "spec_03_interval_merger"
    assert spec3.target_filename == "interval_merger.py"
    assert len(spec3.acceptance_tests) == 3


def test_acceptance_test_requires_assert_or_raises() -> None:
    """Ensures AcceptanceTestCase rejects test code without assertions."""
    with pytest.raises(ValidationError):
        AcceptanceTestCase(
            test_id="test_noop",
            description="Test without assertion",
            test_code="def test_noop():\n    x = 1 + 1\n    return x",
        )


def test_file_modification_blocks_path_traversal() -> None:
    """Ensures FileModification strictly rejects path traversal or subdirectories."""
    with pytest.raises(ValidationError):
        FileModification(
            action="create",
            filepath="../evil.py",
            content="x = 1",
            rationale="Attempt path traversal.",
        )


def test_file_modification_search_replace_patch() -> None:
    """Verifies deterministic application of SearchReplacePatch in FileModification."""
    original = "def add(a: int, b: int) -> int:\n    return a - b\n"
    mod = FileModification(
        action="patch",
        filepath="math_mod.py",
        patches=[
            SearchReplacePatch(
                search_block="return a - b",
                replace_block="return a + b",
            )
        ],
        rationale="Fix subtraction bug in add().",
    )
    updated = mod.apply(existing_content=original)
    assert "return a + b" in updated
    assert "return a - b" not in updated