"""
Spec Ingestion package for loading JSON and Markdown specifications.
"""

from spec2code.ingest.parser import (
    parse_json_spec,
    parse_markdown_spec,
    parse_spec_file,
)

__all__ = [
    "parse_json_spec",
    "parse_markdown_spec",
    "parse_spec_file",
]