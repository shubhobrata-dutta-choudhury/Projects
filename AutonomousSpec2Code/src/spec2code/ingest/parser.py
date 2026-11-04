"""
Spec Ingestion Parser (`JSON` and `Markdown` -> `FeatureSpec`).

Demonstrates how semi-structured Markdown documents and structured JSON files
can both be normalized into a single strictly-validated Pydantic `FeatureSpec` model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from spec2code.schemas.spec_schema import (
    AcceptanceTestCase,
    FeatureSpec,
    SpecConstraints,
)


def parse_spec_file(path: str | Path) -> FeatureSpec:
    """
    Loads a feature specification from a `.json` or `.md` file and validates it into a `FeatureSpec`.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Specification file not found: {file_path}")

    raw_text = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        return parse_json_spec(raw_text)
    elif suffix in (".md", ".markdown"):
        return parse_markdown_spec(raw_text, default_spec_id=file_path.stem)

    raise ValueError(f"Unsupported specification file extension '{suffix}'. Expected .json or .md.")


def parse_json_spec(raw_json: str) -> FeatureSpec:
    """
    Parses a JSON string directly into a validated `FeatureSpec`.
    """
    data = json.loads(raw_json)
    return FeatureSpec.model_validate(data)


def parse_markdown_spec(raw_md: str, default_spec_id: str = "markdown_spec") -> FeatureSpec:
    """
    Parses a structured Markdown specification into a validated `FeatureSpec`.

    Supported Markdown structure:
    - `# Title` (H1 heading)
    - Metadata bullets or YAML-like key/values (`spec_id`, `target_filename`, `difficulty`)
    - `## Description`
    - `## Entry Points` (code blocks or bullet items)
    - `## Edge Cases` (bullet items)
    - `## Constraints` (bullet items like `time_complexity: O(1)`)
    - `## Acceptance Tests` (one or more ```python code blocks containing `def test_...` functions)
    """
    lines = raw_md.splitlines()

    # 1. Extract H1 Title
    title = default_spec_id.replace("_", " ").title()
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # 2. Split Markdown into H2 sections (`## Section Name`)
    sections: dict[str, str] = {}
    current_section = "header"
    buffer: list[str] = []

    for line in lines:
        if line.startswith("## "):
            sections[current_section] = "\n".join(buffer).strip()
            current_section = line[3:].strip().lower()
            buffer = []
        elif not line.startswith("# "):
            buffer.append(line)
    sections[current_section] = "\n".join(buffer).strip()

    # 3. Parse Metadata from header/metadata section
    header_text = sections.get("header", "") + "\n" + sections.get("metadata", "")
    spec_id = _extract_kv(header_text, "spec_id") or default_spec_id
    target_filename = _extract_kv(header_text, "target_filename")
    if not target_filename:
        raise ValueError("Markdown spec must declare `target_filename: <module>.py` in its metadata header.")
    difficulty_raw = (_extract_kv(header_text, "difficulty") or "medium").lower()
    difficulty = difficulty_raw if difficulty_raw in ("easy", "medium", "hard") else "medium"

    # 4. Description
    description = sections.get("description", "").strip()
    if not description:
        description = header_text.strip()

    # 5. Entry Points
    entry_points_raw = sections.get("entry points", "")
    entry_points = _extract_code_or_bullets(entry_points_raw)

    # 6. Edge Cases
    edge_cases_raw = sections.get("edge cases", "")
    edge_cases = _extract_bullets(edge_cases_raw)

    # 7. Constraints
    constraints_raw = sections.get("constraints", "")
    time_comp = _extract_kv(constraints_raw, "time_complexity") or "Not specified"
    space_comp = _extract_kv(constraints_raw, "space_complexity") or "Not specified"
    allowed_imports_str = _extract_kv(constraints_raw, "allowed_imports")
    if allowed_imports_str:
        allowed_imports = [
            item.strip().strip("`'\"")
            for item in allowed_imports_str.strip("[]").split(",")
            if item.strip()
        ]
        constraints = SpecConstraints(
            time_complexity=time_comp,
            space_complexity=space_comp,
            allowed_imports=allowed_imports,
        )
    else:
        constraints = SpecConstraints(
            time_complexity=time_comp,
            space_complexity=space_comp,
        )

    # 8. Acceptance Tests
    tests_raw = sections.get("acceptance tests", "")
    acceptance_tests = _extract_acceptance_tests(tests_raw)

    return FeatureSpec(
        spec_id=spec_id,
        title=title,
        difficulty=difficulty,  # type: ignore[arg-type]
        description=description,
        target_filename=target_filename,
        entry_points=entry_points,
        edge_cases=edge_cases,
        constraints=constraints,
        acceptance_tests=acceptance_tests,
    )


def _extract_kv(text: str, key: str) -> str | None:
    """
    Matches lines like `- **target_filename**: `lru_cache_ttl.py`` or `target_filename: lru_cache_ttl.py`.
    """
    pattern = rf"(?im)^\s*(?:[-\*]\s*)?\*\*?{re.escape(key)}\*\*?\s*:\s*`?([^`\n]+)`?\s*$"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None


def _extract_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip().strip("`"))
    return items


def _extract_code_or_bullets(text: str) -> list[str]:
    code_blocks = re.findall(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    items: list[str] = []
    for block in code_blocks:
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("def ") or s.startswith("class "):
                items.append(s)
    if items:
        return items
    return _extract_bullets(text)


def _extract_acceptance_tests(text: str) -> list[AcceptanceTestCase]:
    code_blocks = re.findall(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    cases: list[AcceptanceTestCase] = []

    for block in code_blocks:
        # Split block into individual `def test_...` functions if multiple exist in one block
        test_funcs = re.split(r"(?m)(?=^def test_)", block.strip())
        for chunk in test_funcs:
            cleaned = chunk.strip()
            if not cleaned:
                continue
            fn_match = re.match(r"^def\s+(test_[a-zA-Z0-9_]+)\s*\(", cleaned)
            if fn_match:
                test_id = fn_match.group(1)
                doc_match = re.search(r'"""(.*?)"""', cleaned, flags=re.DOTALL)
                desc = doc_match.group(1).strip() if doc_match else f"Acceptance test {test_id}"
                cases.append(
                    AcceptanceTestCase(
                        test_id=test_id,
                        description=desc,
                        test_code=cleaned,
                    )
                )
    return cases