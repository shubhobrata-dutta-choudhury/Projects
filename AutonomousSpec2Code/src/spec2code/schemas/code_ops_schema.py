"""
Pillar 1: Strict Pydantic Schemas for Code Generation & File Modifications.

Instead of extracting raw markdown code blocks via brittle regexes, the LLM is forced
to emit strictly validated Pydantic models describing:
- Its chain-of-thought architectural plan or bug diagnosis
- Explicit file operations (`create`, `overwrite`, or `patch`)
- Companion unit tests (`test_agent_generated.py`)
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class SearchReplacePatch(BaseModel):
    """
    A targeted search-and-replace diff block when modifying an existing file.
    """

    search_block: str = Field(..., min_length=1, description="Exact substring in the current file to find.")
    replace_block: str = Field(..., description="Replacement substring to substitute in place of search_block.")


class FileModification(BaseModel):
    """
    Structured representation of a file creation, full overwrite, or targeted patch operation.
    Prevents directory traversal and arbitrary file corruption.
    """

    action: Literal["create", "overwrite", "patch"] = Field(
        ...,
        description="Type of file modification to perform inside the sandbox.",
    )
    filepath: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_]+\.py$",
        description="Relative filename inside the sandbox (no path traversal allowed).",
    )
    content: str | None = Field(
        default=None,
        description="Complete file content when action is 'create' or 'overwrite'.",
    )
    patches: list[SearchReplacePatch] = Field(
        default_factory=list,
        description="List of search/replace blocks when action is 'patch'.",
    )
    rationale: str = Field(
        ...,
        min_length=5,
        description="Explanation of why this file modification is being made.",
    )

    @field_validator("filepath")
    @classmethod
    def forbid_path_traversal(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError(f"Unsafe filepath '{v}': path traversal or nested directories are forbidden.")
        return v

    @model_validator(mode="after")
    def validate_action_payload(self) -> "FileModification":
        if self.action in ("create", "overwrite"):
            if not self.content or not self.content.strip():
                raise ValueError(f"FileModification with action='{self.action}' requires non-empty 'content'.")
        elif self.action == "patch":
            if not self.patches and not self.content:
                raise ValueError("FileModification with action='patch' requires non-empty 'patches' or fallback 'content'.")
        return self

    def apply(self, existing_content: str | None = None) -> str:
        """
        Applies this modification deterministically and returns the resulting file text.
        """
        if self.action in ("create", "overwrite"):
            assert self.content is not None
            return self.content

        # Patch mode
        if existing_content is None:
            if self.content is not None:
                return self.content
            raise ValueError(f"Cannot apply 'patch' to non-existent file '{self.filepath}' without existing content.")

        updated = existing_content
        if self.patches:
            for idx, patch in enumerate(self.patches, start=1):
                if patch.search_block not in updated:
                    # If fallback full content was also provided, use it safely; otherwise raise descriptive error
                    if self.content:
                        return self.content
                    raise ValueError(
                        f"Patch #{idx} failed on '{self.filepath}': search_block not found in existing file."
                    )
                updated = updated.replace(patch.search_block, patch.replace_block, 1)
            return updated

        if self.content is not None:
            return self.content
        return updated


class CodeGenerationResponse(BaseModel):
    """
    Structured output schema required from the Generator Agent on initial code synthesis.
    """

    architectural_plan: str = Field(
        ...,
        min_length=15,
        description="Step-by-step reasoning covering data structures, algorithmic complexity, and edge cases.",
    )
    implementation_op: FileModification = Field(
        ...,
        description="File creation operation for the target Python module specified in the FeatureSpec.",
    )
    agent_test_op: FileModification = Field(
        ...,
        description="File creation operation for 'test_agent_generated.py' containing unit and edge-case tests.",
    )


class RepairPatchResponse(BaseModel):
    """
    Structured output schema required from the Debugger/Repair Agent during FSM self-correction loops.
    """

    failure_root_cause: str = Field(
        ...,
        min_length=10,
        description="Detailed diagnosis of why the AST check or pytest execution failed based on traceback/stderr.",
    )
    fix_strategy: str = Field(
        ...,
        min_length=10,
        description="Explanation of the exact code changes being made to resolve the failure without breaking other tests.",
    )
    modifications: list[FileModification] = Field(
        ...,
        min_length=1,
        description="One or more file modifications (overwrite or patch) to fix the implementation and/or agent tests.",
    )