"""
app/core/producer/summarizer.py — LLM-Powered Module Summarizer
================================================================
Takes a ParsedFile (structured static analysis output) and calls the LLM
to produce a rich, human+AI-readable summary for the OKF concept file.

Design principle: We give the LLM STRUCTURED input (function names,
docstrings, imports) — NOT raw source code. This:
  - Saves tokens (cheaper)
  - Gives the LLM better signal (less noise)
  - Produces more consistent output
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.producer.parser import ParsedFile
from app.utils.llm_client import generate_text


@dataclass
class ModuleSummary:
    """LLM-generated summary for a single source file module."""
    title: str                  # Short module title (5 words max)
    description: str            # 1-2 sentence summary
    purpose: str                # What problem does this module solve?
    key_functions: list[str]    # Top functions/methods worth highlighting
    tags: list[str]             # 3-6 relevant tags for metadata search
    type: str                   # "module" | "api" | "database" | "config" | "test"
    depends_on_notes: str       # Human-readable note on key dependencies
    raw_llm_output: str         # The full LLM response (for debugging)


def summarize_file(parsed: ParsedFile) -> ModuleSummary:
    """
    Use the LLM to generate a rich summary of a parsed source file.

    Args:
        parsed: The structured ParsedFile from parser.py

    Returns:
        ModuleSummary with all fields populated.
    """
    prompt = _build_prompt(parsed)
    raw_response, _, _ = generate_text(prompt, temperature=0.2)  # discard tokens, not needed here
    return _parse_llm_response(raw_response, parsed)


def _build_prompt(parsed: ParsedFile) -> str:
    """
    Construct a structured prompt for the LLM.
    We feed it the EXTRACTED structure, not raw source code.
    """
    # Build function list
    func_lines = []
    for f in parsed.functions[:15]:  # Cap at 15 to avoid prompt bloat
        async_prefix = "async " if f.is_async else ""
        args = ", ".join(parsed.functions[0].args[:5]) if parsed.functions else ""
        doc = f'  → "{f.docstring[:80]}..."' if f.docstring else ""
        func_lines.append(f"  - {async_prefix}{f.name}({args}){doc}")

    # Build class list
    class_lines = []
    for c in parsed.classes[:8]:
        bases = f"(extends {', '.join(c.base_classes)})" if c.base_classes else ""
        method_names = ", ".join(m.name for m in c.methods[:6])
        doc = f'  → "{c.docstring[:80]}..."' if c.docstring else ""
        class_lines.append(f"  - class {c.name} {bases}{doc}")
        if method_names:
            class_lines.append(f"    methods: {method_names}")

    # Build imports (top-level only, skip relative)
    top_imports = [
        imp for imp in parsed.imports[:10]
        if not imp.startswith(".")
    ]

    prompt = f"""You are a senior software engineer writing documentation for an AI knowledge base (OKF - Open Knowledge Format).

Analyse this source file and produce a structured summary.

## File Information
- Path: {parsed.file_path}
- Language: {parsed.language}
- Lines of code: {parsed.line_count}
- Module docstring: {parsed.module_docstring or "None"}

## Imports / Dependencies
{chr(10).join(f"  - {imp}" for imp in top_imports) or "  (none)"}

## Functions Defined
{chr(10).join(func_lines) or "  (none)"}

## Classes Defined
{chr(10).join(class_lines) or "  (none)"}

---

Respond in EXACTLY this format (no extra text, no markdown formatting around the sections):

TITLE: <5 words max, the module's role>
DESCRIPTION: <1-2 sentences: what this file does>
PURPOSE: <1 sentence: what developer problem it solves>
TYPE: <one of: module | api | database | config | test | architecture | concept>
TAGS: <comma-separated, 3-6 lowercase tags relevant to this file>
KEY_FUNCTIONS: <comma-separated list of the 3-5 most important function/class names>
DEPENDS_ON_NOTES: <1 sentence: which key external libs or internal modules it relies on>
"""
    return prompt


def _parse_llm_response(response: str, parsed: ParsedFile) -> ModuleSummary:
    """
    Parse the structured LLM response into a ModuleSummary.
    Falls back to sensible defaults if any field is missing.
    """
    fields: dict[str, str] = {}
    for line in response.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().upper()] = value.strip()

    def get(key: str, default: str = "") -> str:
        return fields.get(key, default)

    def get_list(key: str) -> list[str]:
        raw = get(key)
        return [item.strip() for item in raw.split(",") if item.strip()]

    # Fallback title from filename
    fallback_title = parsed.file_path.split("/")[-1].replace("_", " ").replace(".py", "")

    return ModuleSummary(
        title=get("TITLE", fallback_title),
        description=get("DESCRIPTION", "No description available."),
        purpose=get("PURPOSE", ""),
        key_functions=get_list("KEY_FUNCTIONS"),
        tags=get_list("TAGS"),
        type=get("TYPE", "module"),
        depends_on_notes=get("DEPENDS_ON_NOTES", ""),
        raw_llm_output=response,
    )
