"""
Pillar 3: AST Static Security & Quality Guard (`src/spec2code/sandbox/ast_guard.py`).

Before executing any LLM-generated Python code inside the subprocess sandbox,
we parse its Abstract Syntax Tree (`ast.parse`) to deterministically verify:
1. Syntax validity (`SyntaxError` caught before spawning a subprocess)
2. Security policy compliance (blocks forbidden imports like `os`, `subprocess`, `shutil`, `socket`
   and dangerous built-in calls like `eval()`, `exec()`, `open()`, `__import__()`)
3. Code quality telemetry (calculates type-hint coverage and docstring coverage across public functions/classes)
"""

from __future__ import annotations

import ast
from spec2code.schemas.execution_schema import ASTValidationResult, ASTViolation
from spec2code.schemas.spec_schema import SpecConstraints

# Globally prohibited modules in any generated sandbox code
ALWAYS_FORBIDDEN_MODULES = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "socket",
    "urllib",
    "http",
    "requests",
    "pathlib",
    "multiprocessing",
    "threading",
}

ALWAYS_FORBIDDEN_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
}


def validate_code_ast(
    files: dict[str, str],
    constraints: SpecConstraints,
    target_filename: str,
) -> ASTValidationResult:
    """
    Runs static AST verification on a mapping of `{filename: python_source_code}`.

    - For `target_filename` (the implementation module), enforces `constraints.allowed_imports`,
      forbidden calls, and calculates type-hint + docstring coverage.
    - For test files (`test_*.py`), allows `pytest` and the target module import while still
      enforcing syntax and security restrictions.
    """
    violations: list[ASTViolation] = []
    public_fn_count = 0
    typed_fn_count = 0
    doc_target_count = 0
    documented_count = 0

    target_module_name = target_filename[:-3] if target_filename.endswith(".py") else target_filename
    allowed_impl_imports = set(constraints.allowed_imports) | {"__future__"}

    for filepath, source in files.items():
        is_test_file = filepath.startswith("test_")
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError as exc:
            violations.append(
                ASTViolation(
                    filepath=filepath,
                    line_number=exc.lineno,
                    violation_type="SyntaxError",
                    message=f"{exc.msg} (text: {exc.text.strip() if exc.text else 'N/A'})",
                    is_blocking=True,
                )
            )
            continue

        # Walk AST for imports and calls
        for node in ast.walk(tree):
            # 1. Check `import x`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    _check_import_node(
                        filepath=filepath,
                        lineno=node.lineno,
                        root_mod=root_mod,
                        is_test_file=is_test_file,
                        allowed_impl_imports=allowed_impl_imports,
                        target_module_name=target_module_name,
                        violations=violations,
                    )

            # 2. Check `from x import y`
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    _check_import_node(
                        filepath=filepath,
                        lineno=node.lineno,
                        root_mod=root_mod,
                        is_test_file=is_test_file,
                        allowed_impl_imports=allowed_impl_imports,
                        target_module_name=target_module_name,
                        violations=violations,
                    )

            # 3. Check function calls (`eval(...)`, `os.system(...)`, etc.)
            elif isinstance(node, ast.Call):
                call_name = _resolve_call_name(node.func)
                if call_name:
                    base_fn = call_name.split(".")[0]
                    if (
                        call_name in ALWAYS_FORBIDDEN_BUILTINS
                        or base_fn in ALWAYS_FORBIDDEN_BUILTINS
                        or call_name in constraints.forbidden_constructs
                    ):
                        violations.append(
                            ASTViolation(
                                filepath=filepath,
                                line_number=getattr(node, "lineno", None),
                                violation_type="ForbiddenCall",
                                message=f"Call to forbidden function/construct '{call_name}()' is prohibited in sandbox.",
                                is_blocking=True,
                            )
                        )

        # 4. Inspect quality metrics on the primary implementation module
        if filepath == target_filename:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc_target_count += 1
                    if ast.get_docstring(node):
                        documented_count += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_public = not node.name.startswith("_") or node.name == "__init__"
                    if is_public:
                        public_fn_count += 1
                        if _has_type_annotations(node):
                            typed_fn_count += 1
                        else:
                            violations.append(
                                ASTViolation(
                                    filepath=filepath,
                                    line_number=node.lineno,
                                    violation_type="MissingTypeHints",
                                    message=f"Function/method '{node.name}' is missing parameter or return type hints.",
                                    is_blocking=False,
                                )
                            )

                    if node.name != "__init__":
                        doc_target_count += 1
                        if ast.get_docstring(node):
                            documented_count += 1
                        else:
                            violations.append(
                                ASTViolation(
                                    filepath=filepath,
                                    line_number=node.lineno,
                                    violation_type="MissingDocstring",
                                    message=f"Public function/method '{node.name}' is missing a docstring.",
                                    is_blocking=False,
                                )
                            )

    blocking_exists = any(v.is_blocking for v in violations)
    type_ratio = (typed_fn_count / public_fn_count) if public_fn_count > 0 else 1.0
    doc_ratio = (documented_count / doc_target_count) if doc_target_count > 0 else 1.0

    return ASTValidationResult(
        passed=not blocking_exists,
        violations=violations,
        public_functions_count=public_fn_count,
        type_hint_coverage_ratio=round(type_ratio, 3),
        docstring_coverage_ratio=round(doc_ratio, 3),
    )


def _check_import_node(
    filepath: str,
    lineno: int,
    root_mod: str,
    is_test_file: bool,
    allowed_impl_imports: set[str],
    target_module_name: str,
    violations: list[ASTViolation],
) -> None:
    if root_mod in ALWAYS_FORBIDDEN_MODULES:
        violations.append(
            ASTViolation(
                filepath=filepath,
                line_number=lineno,
                violation_type="ForbiddenImport",
                message=f"Importing restricted system/network module '{root_mod}' is forbidden.",
                is_blocking=True,
            )
        )
        return

    if is_test_file:
        allowed_test_mods = allowed_impl_imports | {"pytest", "math", "time", target_module_name}
        if root_mod not in allowed_test_mods:
            violations.append(
                ASTViolation(
                    filepath=filepath,
                    line_number=lineno,
                    violation_type="DisallowedTestImport",
                    message=f"Test file imported '{root_mod}', which is not in allowed modules {sorted(allowed_test_mods)}.",
                    is_blocking=True,
                )
            )
    else:
        if root_mod not in allowed_impl_imports:
            violations.append(
                ASTViolation(
                    filepath=filepath,
                    line_number=lineno,
                    violation_type="ConstraintViolationImport",
                    message=(
                        f"Implementation imported '{root_mod}', which violates spec allowed_imports: "
                        f"{sorted(allowed_impl_imports)}."
                    ),
                    is_blocking=True,
                )
            )


def _resolve_call_name(func_node: ast.AST) -> str | None:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        prefix = _resolve_call_name(func_node.value)
        if prefix:
            return f"{prefix}.{func_node.attr}"
        return func_node.attr
    return None


def _has_type_annotations(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    has_return = fn_node.returns is not None
    non_self_args = [a for a in fn_node.args.args if a.arg not in ("self", "cls")]
    all_args_typed = all(a.annotation is not None for a in non_self_args)
    return has_return and all_args_typed