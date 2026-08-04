# agents/data_analysis/tools.py
"""
Data Analysis Agent tools.

Tools:
  run_python_code       — Execute Python in isolated namespace
  statistical_analysis  — Descriptive stats on JSON data
  create_chart          — Generate chart, return base64 PNG

Design decisions:
  - run_python_code: restricted namespace, no subprocess/os
  - Charts: matplotlib Agg backend (no display), base64 output
  - All tools: return str (Gemini bridge expects strings)
  - Errors: returned as strings so Gemini can report them
"""

from __future__ import annotations

import base64
import io
import json
import math
import traceback
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class CodeResult:
    success: bool
    output: str
    error: str = ""
    variables: dict[str, Any] = None

    def __post_init__(self):
        if self.variables is None:
            self.variables = {}


@dataclass
class StatsResult:
    success: bool
    stats: dict[str, Any] = None
    error: str = ""

    def __post_init__(self):
        if self.stats is None:
            self.stats = {}


@dataclass
class ChartResult:
    success: bool
    image_base64: str = ""
    chart_type: str = ""
    error: str = ""


# ── Tool implementations ──────────────────────────────────────────────────────

def _blocked_import(name: str, *args, **kwargs):
    """Replaces __import__ in sandbox — blocks all runtime imports."""
    raise ImportError(
        f"Import of '{name}' is not allowed in the sandbox. "
        f"Available modules: numpy (np), pandas (pd), math, "
        f"statistics, json, re, datetime, collections, itertools"
    )

# Safe builtins for code execution sandbox
_SAFE_BUILTINS = {
    "__import__": _blocked_import,  # ← KEY ADDITION
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "dir": dir,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "getattr": getattr,
    "hasattr": hasattr,
    "hash": hash,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "setattr": setattr,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}

# Modules available in sandbox
_SAFE_MODULES = {
    "json": __import__("json"),
    "math": __import__("math"),
    "statistics": __import__("statistics"),
    "itertools": __import__("itertools"),
    "functools": __import__("functools"),
    "collections": __import__("collections"),
    "re": __import__("re"),
    "datetime": __import__("datetime"),
}

# Optional scientific modules (present in our requirements)
try:
    import numpy as np
    _SAFE_MODULES["numpy"] = np
    _SAFE_MODULES["np"] = np
except ImportError:
    pass

try:
    import pandas as pd
    _SAFE_MODULES["pandas"] = pd
    _SAFE_MODULES["pd"] = pd
except ImportError:
    pass


async def run_python_code(code: str, timeout_seconds: int = 10) -> CodeResult:
    """
    Execute Python code in a restricted sandbox.

    Sandbox rules:
    - No import of os, sys, subprocess, socket, etc.
    - No __import__ override
    - stdout captured via io.StringIO
    - Variables from execution namespace returned
    - Hard timeout via asyncio (not threading — simpler)

    This is for data analysis code that uses pandas/numpy/math.
    Not a general-purpose Python executor.
    """
    import asyncio
    import sys

    exec_globals: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        **_SAFE_MODULES,  # numpy/np, pandas/pd, math, etc. pre-loaded
    }

    captured_output = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = captured_output

    try:
        compiled = compile(code, "<agent_code>", "exec")
        exec_locals: dict[str, Any] = {}

        # CORRECT: sync function in thread pool, not async
        def _run_sync() -> None:
            exec(compiled, exec_globals, exec_locals)  # noqa: S102

        await asyncio.wait_for(
            asyncio.to_thread(_run_sync),
            timeout=timeout_seconds,
        )

        output = captured_output.getvalue()

        safe_vars: dict[str, Any] = {}
        for k, v in exec_locals.items():
            if k.startswith("_"):
                continue
            try:
                json.dumps(v)
                safe_vars[k] = v
            except (TypeError, ValueError):
                safe_vars[k] = repr(v)

        logger.info("code_executed", output_lines=output.count("\n"))
        return CodeResult(success=True, output=output, variables=safe_vars)

    except asyncio.TimeoutError:
        return CodeResult(
            success=False,
            output="",
            error=f"Code execution timed out after {timeout_seconds}s",
        )
    except Exception as exc:
        tb = traceback.format_exc()
        logger.warning("code_execution_error", error=str(exc))
        return CodeResult(success=False, output="", error=tb)

    finally:
        sys.stdout = original_stdout


async def statistical_analysis(
    data: list[float | int] | list[dict[str, Any]],
    column: str | None = None,
) -> StatsResult:
    """
    Compute descriptive statistics on numeric data.

    Handles two input formats:
    1. Flat list of numbers: [1, 2, 3, 4, 5]
    2. List of dicts with a named column:
       [{"price": 10.5}, {"price": 20.0}]
       Pass column="price" for this format.

    Returns: count, mean, median, std_dev, min, max,
             percentiles (25/75), skewness.
    """
    import statistics as stats_lib

    try:
        # Extract numeric series
        if column and isinstance(data[0], dict):
            series = [
                float(row[column])
                for row in data
                if column in row and row[column] is not None
            ]
        else:
            series = [float(x) for x in data if x is not None]

        if len(series) < 2:
            return StatsResult(
                success=False,
                error="Need at least 2 data points for analysis",
            )

        # Sort for percentile calculation
        sorted_series = sorted(series)
        n = len(sorted_series)

        def percentile(p: float) -> float:
            """Linear interpolation percentile."""
            idx = (p / 100) * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            return sorted_series[lo] + frac * (sorted_series[hi] - sorted_series[lo])

        # Skewness (Pearson's)
        mean_val = stats_lib.mean(series)
        std_val = stats_lib.stdev(series)
        if std_val > 0:
            skewness = sum((x - mean_val) ** 3 for x in series) / (
                n * std_val ** 3
            )
        else:
            skewness = 0.0

        result_stats = {
            "count": n,
            "mean": round(mean_val, 4),
            "median": round(stats_lib.median(series), 4),
            "std_dev": round(std_val, 4),
            "variance": round(stats_lib.variance(series), 4),
            "min": round(min(series), 4),
            "max": round(max(series), 4),
            "range": round(max(series) - min(series), 4),
            "p25": round(percentile(25), 4),
            "p75": round(percentile(75), 4),
            "iqr": round(percentile(75) - percentile(25), 4),
            "skewness": round(skewness, 4),
        }

        logger.info("stats_computed", n=n, mean=result_stats["mean"])
        return StatsResult(success=True, stats=result_stats)

    except (KeyError, ValueError, IndexError) as exc:
        return StatsResult(success=False, error=f"Data error: {exc}")
    except Exception as exc:
        logger.exception("stats_error")
        return StatsResult(success=False, error=str(exc))


async def create_chart(
    chart_type: str,
    data: dict[str, Any],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
) -> ChartResult:
    """
    Generate a chart and return as base64-encoded PNG.

    Supported chart_type values:
      "bar"   — data: {"labels": [...], "values": [...]}
      "line"  — data: {"x": [...], "y": [...]}
      "scatter" — data: {"x": [...], "y": [...]}
      "histogram" — data: {"values": [...], "bins": int (optional)}
      "pie"   — data: {"labels": [...], "values": [...]}

    Returns base64 PNG string (no file I/O — container friendly).
    Uses Agg backend — no display required.
    """
    import matplotlib
    matplotlib.use("Agg")  # Must set before importing pyplot
    import matplotlib.pyplot as plt

    try:
        fig, ax = plt.subplots(figsize=(10, 6))

        chart_type = chart_type.lower().strip()

        if chart_type == "bar":
            labels = data["labels"]
            values = data["values"]
            ax.bar(labels, values, color="steelblue", edgecolor="white")

        elif chart_type == "line":
            ax.plot(data["x"], data["y"], marker="o", color="steelblue", linewidth=2)

        elif chart_type == "scatter":
            ax.scatter(data["x"], data["y"], color="steelblue", alpha=0.7)

        elif chart_type == "histogram":
            bins = data.get("bins", 20)
            ax.hist(data["values"], bins=bins, color="steelblue", edgecolor="white")

        elif chart_type == "pie":
            ax.pie(
                data["values"],
                labels=data["labels"],
                autopct="%1.1f%%",
                startangle=90,
            )

        else:
            return ChartResult(
                success=False,
                error=f"Unknown chart type: {chart_type}. "
                      f"Use: bar, line, scatter, histogram, pie",
            )

        # Styling
        if title:
            ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
        if x_label and chart_type != "pie":
            ax.set_xlabel(x_label, fontsize=11)
        if y_label and chart_type != "pie":
            ax.set_ylabel(y_label, fontsize=11)

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()

        # Encode to base64
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        image_b64 = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)  # Prevent memory leak

        logger.info("chart_created", chart_type=chart_type, title=title)
        return ChartResult(success=True, image_base64=image_b64, chart_type=chart_type)

    except KeyError as exc:
        plt.close("all")
        return ChartResult(success=False, error=f"Missing data key: {exc}")
    except Exception as exc:
        plt.close("all")
        logger.exception("chart_error")
        return ChartResult(success=False, error=str(exc))