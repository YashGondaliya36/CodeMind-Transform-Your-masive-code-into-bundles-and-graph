"""
codemind_okf/core/summarizer.py — Fast AST-Based Module Summarizer
====================================================================
Generates a ModuleSummary deterministically from AST output.
Zero LLM cost. Standalone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codemind_okf.core.parser import ParsedFile


@dataclass
class ModuleSummary:
    """Full structured summary of a module."""
    title: str
    description: str
    purpose: str
    key_functions: list[str]
    tags: list[str]
    type: str
    depends_on_notes: str = "Dependencies extracted via AST."
    raw_llm_output: str = "[FAST MODE - NO LLM OUTPUT]"


def summarize_fast(parsed: ParsedFile) -> ModuleSummary:
    """
    Generate a ModuleSummary from AST output — fast, deterministic, $0 cost.
    """
    path_obj = Path(parsed.file_path)
    filename = path_obj.name

    # Title from filename
    title = (
        filename
        .replace("_", " ").replace("-", " ")
        .rsplit(".", 1)[0].title()
    )

    # Type via path heuristics
    lower_path = parsed.file_path.lower()
    mod_type = "module"
    if any(k in lower_path for k in ("api", "route", "controller", "router", "endpoint")):
        mod_type = "api"
    elif any(k in lower_path for k in ("db", "database", "schema", "model", "orm", "repo")):
        mod_type = "database"
    elif any(k in lower_path for k in ("config", "setting", "env", "conf")):
        mod_type = "config"
    elif "test" in lower_path:
        mod_type = "test"
    elif any(k in lower_path for k in ("component", "ui", "view", "page")):
        mod_type = "concept"

    # Build tags
    tags: set[str] = {mod_type}
    if len(path_obj.parts) > 1:
        parent = path_obj.parts[-2].lower()
        if parent not in ("src", "app", "components", "pages", "lib", "core", "utils"):
            tags.add(parent)
    for imp in parsed.imports[:5]:
        if not imp.startswith("."):
            base = imp.split(".")[0]
            if base not in ("os", "sys", "typing", "pathlib", "json", "datetime", "re"):
                tags.add(base.lower())

    # Key functions & classes
    key_functions = [f.name for f in parsed.functions[:5]] + [c.name for c in parsed.classes[:3]]
    class_names = [c.name for c in parsed.classes[:3]]

    # Description
    if parsed.module_docstring:
        description = parsed.module_docstring.strip().split("\n\n")[0]
        if len(description) > 300:
            description = description[:297] + "..."
        purpose = f"Provides functionality for {title.lower()}."
    else:
        if class_names:
            description = f"Contains definitions for {', '.join(class_names)}."
        elif parsed.functions:
            func_names = [f.name for f in parsed.functions[:3]]
            description = f"Contains functions: {', '.join(func_names)}."
        else:
            description = "Structural module containing configuration, exports, or data schemas."
        purpose = f"Provides core logic and definitions for the {title} component."

    return ModuleSummary(
        title=title,
        description=description,
        purpose=purpose,
        key_functions=key_functions,
        tags=list(tags)[:6],
        type=mod_type,
    )
