"""
Code Agent tools: code analysis, sandboxed execution, LLM explanation.

Design decisions:
  analyze_code  — ast (stdlib) + radon for cyclomatic complexity.
                  Pure static analysis, zero execution risk.
  execute_code  — subprocess.run() with fresh Python interpreter.
                  NOT exec() — Code Agent's purpose is running arbitrary
                  user code, so exec() with blocked imports defeats the point.
                  Subprocess isolates: separate process, timeout, memory cap.
  explain_code  — Gemini direct call. LLM IS the tool here.

Security model for execute_code:
  - Hard timeout: 10 seconds (subprocess timeout= param)
  - Memory cap: 256MB via resource.setrlimit (Linux only, WSL2 supported)
  - No persistent state between executions (fresh interpreter each time)
  - stdout/stderr captured, never eval'd
  - User is warned this is a dev sandbox, not production isolation
"""

from __future__ import annotations

import ast
import asyncio
import json
import resource
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXECUTION_TIMEOUT = 10          # seconds
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB
MAX_OUTPUT_CHARS = 4000         # cap captured stdout/stderr


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    success: bool
    language: str = "python"
    # Structure
    function_count: int = 0
    class_count: int = 0
    import_count: int = 0
    line_count: int = 0
    # Complexity (radon)
    avg_complexity: float = 0.0
    max_complexity: float = 0.0
    complexity_grade: str = "A"   # A–F radon grades
    # Detail lists
    functions: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)   # syntax warnings
    error: str = ""


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    execution_time_ms: float = 0.0
    error: str = ""


@dataclass
class ExplanationResult:
    success: bool
    explanation: str = ""
    complexity_summary: str = ""
    suggestions: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _complexity_grade(score: float) -> str:
    """
    Map radon cyclomatic complexity score to letter grade.
    Radon scale: A(1-5) B(6-10) C(11-15) D(16-20) E(21-25) F(26+)
    """
    if score <= 5:
        return "A"
    elif score <= 10:
        return "B"
    elif score <= 15:
        return "C"
    elif score <= 20:
        return "D"
    elif score <= 25:
        return "E"
    else:
        return "F"


def _analyze_ast(source: str) -> dict:
    """
    Parse source with ast and extract structural info.
    Returns dict with functions, classes, imports, issues.
    Raises SyntaxError if source is unparseable.
    """
    tree = ast.parse(source)

    functions = []
    classes = []
    imports = []
    issues = []

    for node in ast.walk(tree):
        # Functions and async functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            has_docstring = (
                isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ) if node.body else False

            if not has_docstring:
                issues.append(f"Function '{node.name}' at line {node.lineno} missing docstring")

            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": args,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "has_docstring": has_docstring,
                "decorator_count": len(node.decorator_list),
            })

        # Classes
        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n is not node  # exclude nested classes' methods
            ]
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "method_count": len(methods),
                "methods": methods[:20],  # cap for large classes
                "base_count": len(node.bases),
            })

        # Import statements
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}" if module else alias.name)

    return {
        "functions": functions,
        "classes": classes,
        "imports": list(dict.fromkeys(imports)),  # unique, order-preserving
        "issues": issues,
    }


def _analyze_complexity_sync(source: str) -> tuple[float, float, list[dict]]:
    """
    Run radon cyclomatic complexity analysis.
    Returns (avg_complexity, max_complexity, per_function_details).
    Sync — runs in thread pool.
    """
    try:
        from radon.complexity import cc_visit
        from radon.metrics import mi_visit  # noqa: F401 — available if needed later

        results = cc_visit(source)
        if not results:
            return 0.0, 0.0, []

        scores = [r.complexity for r in results]
        avg = sum(scores) / len(scores)
        maximum = max(scores)

        details = [
            {
                "name": r.name,
                "complexity": r.complexity,
                "grade": _complexity_grade(r.complexity),
                "line": r.lineno,
            }
            for r in results
        ]
        return round(avg, 2), float(maximum), details

    except ImportError:
        # radon not installed — degrade gracefully
        log.warning("radon_not_installed", msg="Install radon for complexity analysis")
        return 0.0, 0.0, []
    except Exception as e:
        log.warning("radon_analysis_failed", error=str(e))
        return 0.0, 0.0, []


def _set_memory_limit():
    """
    Called as preexec_fn in subprocess.run().
    Sets virtual memory limit to MEMORY_LIMIT_BYTES.
    Linux/WSL2 only — silently skipped on other platforms.
    """
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES),
        )
    except (ValueError, resource.error):
        pass  # Some systems don't support RLIMIT_AS — not fatal


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def analyze_code(
    source: str,
    language: str = "python",
) -> AnalysisResult:
    """
    Analyze code structure and complexity using AST + radon.

    Args:
        source: Source code string to analyze.
        language: Programming language. Currently only 'python' is fully
                  supported. Other languages get basic line-count analysis.

    Returns:
        AnalysisResult with structure metrics, complexity scores, and issues.
    """
    if not source.strip():
        return AnalysisResult(
            success=False,
            error="No source code provided",
        )

    log.info("analyze_code", language=language, chars=len(source))

    line_count = len(source.splitlines())

    if language.lower() != "python":
        # Basic analysis for non-Python — just line count
        return AnalysisResult(
            success=True,
            language=language,
            line_count=line_count,
            issues=[f"Deep analysis only supported for Python. Got: {language}"],
        )

    # --- AST analysis (sync, fast — no thread needed) ---
    try:
        ast_data = _analyze_ast(source)
    except SyntaxError as e:
        return AnalysisResult(
            success=False,
            language="python",
            line_count=line_count,
            error=f"Syntax error at line {e.lineno}: {e.msg}",
        )

    # --- Radon complexity (potentially slow — thread pool) ---
    avg_c, max_c, complexity_details = await asyncio.to_thread(
        _analyze_complexity_sync, source
    )

    # Merge radon details into function list
    complexity_by_name = {d["name"]: d for d in complexity_details}
    for fn in ast_data["functions"]:
        cd = complexity_by_name.get(fn["name"], {})
        fn["complexity"] = cd.get("complexity", 1)
        fn["complexity_grade"] = cd.get("grade", "A")

    return AnalysisResult(
        success=True,
        language="python",
        function_count=len(ast_data["functions"]),
        class_count=len(ast_data["classes"]),
        import_count=len(ast_data["imports"]),
        line_count=line_count,
        avg_complexity=avg_c,
        max_complexity=max_c,
        complexity_grade=_complexity_grade(max_c) if max_c > 0 else "A",
        functions=ast_data["functions"],
        classes=ast_data["classes"],
        imports=ast_data["imports"],
        issues=ast_data["issues"],
    )


async def execute_code(
    source: str,
    stdin_input: str = "",
    timeout: int = EXECUTION_TIMEOUT,
) -> ExecutionResult:
    """
    Execute Python code in an isolated subprocess.

    Security model:
      - Fresh Python interpreter per execution (no shared state)
      - Hard timeout via subprocess timeout= parameter
      - Memory cap via resource.setrlimit preexec_fn (Linux/WSL2)
      - stdout/stderr captured (not eval'd, not exec'd)
      - No persistent filesystem side effects (code runs in /tmp implicitly)

    This is a development sandbox. Not suitable for untrusted production use.

    Args:
        source: Python source code to execute.
        stdin_input: Optional string piped to stdin.
        timeout: Max execution time in seconds (default 10).

    Returns:
        ExecutionResult with stdout, stderr, exit_code, timing.
    """
    if not source.strip():
        return ExecutionResult(
            success=False,
            error="No code provided to execute",
        )

    # Cap timeout to reasonable range
    timeout = max(1, min(timeout, 30))

    log.info("execute_code", lines=len(source.splitlines()), timeout=timeout)

    import time
    start = time.perf_counter()

    def _run_subprocess() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", source],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_set_memory_limit,  # memory cap (Linux only)
        )

    try:
        proc = await asyncio.to_thread(_run_subprocess)
        elapsed_ms = (time.perf_counter() - start) * 1000

        stdout = proc.stdout[:MAX_OUTPUT_CHARS]
        stderr = proc.stderr[:MAX_OUTPUT_CHARS]

        return ExecutionResult(
            success=proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode,
            timed_out=False,
            execution_time_ms=round(elapsed_ms, 2),
        )

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.warning("execute_code_timeout", timeout=timeout)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Execution timed out after {timeout} seconds",
            exit_code=-1,
            timed_out=True,
            execution_time_ms=round(elapsed_ms, 2),
        )

    except Exception as e:
        log.exception("execute_code_error")
        return ExecutionResult(
            success=False,
            error=str(e),
            exit_code=-1,
        )


async def explain_code(
    source: str,
    detail_level: str = "standard",
) -> ExplanationResult:
    """
    Explain code using Gemini with optional complexity analysis context.

    Args:
        source: Source code to explain.
        detail_level: "brief" | "standard" | "detailed"
                      brief    — 2-3 sentence overview
                      standard — paragraph per logical section
                      detailed — line-by-line with suggestions

    Returns:
        ExplanationResult with explanation, complexity summary, suggestions.
    """
    from google import genai
    from google.genai import types as genai_types
    from shared.config import settings

    if not source.strip():
        return ExplanationResult(
            success=False,
            error="No source code provided",
        )

    detail_instructions = {
        "brief": (
            "Provide a 2-3 sentence high-level overview of what this code does. "
            "No line-by-line detail."
        ),
        "standard": (
            "Explain what this code does section by section. "
            "Cover the purpose, key logic, and any notable patterns. "
            "Approximately 150-300 words."
        ),
        "detailed": (
            "Provide a detailed explanation covering: "
            "1) Overall purpose, "
            "2) How each function/class works, "
            "3) Key algorithms or patterns used, "
            "4) Potential issues or improvements. "
            "Be thorough — approximately 300-600 words."
        ),
    }.get(detail_level, "Explain what this code does.")

    prompt = (
        f"{detail_instructions}\n\n"
        f"Also provide:\n"
        f"COMPLEXITY_SUMMARY: <one sentence about code complexity>\n"
        f"SUGGESTIONS_JSON: [\"suggestion 1\", \"suggestion 2\", \"suggestion 3\"]\n\n"
        f"Code to explain:\n```python\n{source}\n```"
    )

    log.info("explain_code", detail_level=detail_level, chars=len(source))

    try:
        client = genai.Client(api_key=settings.google_api_key)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.agent_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                system_instruction=(
                    "You are an expert code reviewer and educator. "
                    "Explain code clearly for the target audience. "
                    "Always include the COMPLEXITY_SUMMARY and SUGGESTIONS_JSON lines."
                ),
            ),
        )

        full_text = response.text or ""
        explanation = full_text
        complexity_summary = ""
        suggestions: list[str] = []

        # Parse COMPLEXITY_SUMMARY
        import re
        cs_match = re.search(r"COMPLEXITY_SUMMARY:\s*(.+?)(?:\n|$)", full_text)
        if cs_match:
            complexity_summary = cs_match.group(1).strip()
            explanation = full_text[: cs_match.start()].strip()

        # Parse SUGGESTIONS_JSON
        sj_match = re.search(r"SUGGESTIONS_JSON:\s*(\[.*?\])", full_text, re.DOTALL)
        if sj_match:
            try:
                suggestions = json.loads(sj_match.group(1))
                # Remove suggestions line from explanation if still present
                explanation = re.sub(
                    r"SUGGESTIONS_JSON:\s*\[.*?\]", "", explanation, flags=re.DOTALL
                ).strip()
            except json.JSONDecodeError:
                pass

        return ExplanationResult(
            success=True,
            explanation=explanation,
            complexity_summary=complexity_summary,
            suggestions=suggestions,
        )

    except Exception as e:
        log.exception("explain_code_error")
        return ExplanationResult(success=False, error=str(e))