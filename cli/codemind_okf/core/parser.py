"""
codemind_okf/core/parser.py — Source Code AST Parser
======================================================
Standalone — no FastAPI dependency.
Extracts structured information from source files without calling an LLM.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from codemind_okf.core.file_utils import safe_read

try:
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjavascript
    import tree_sitter_typescript as tstypescript
    TS_AVAILABLE = True
except ImportError:
    TS_AVAILABLE = False


@dataclass
class FunctionInfo:
    """Represents a parsed function or method."""
    name: str
    docstring: str | None
    args: list[str]
    is_async: bool
    line_number: int
    decorators: list[str] = field(default_factory=list)


@dataclass
class ClassInfo:
    """Represents a parsed class definition."""
    name: str
    docstring: str | None
    base_classes: list[str]
    methods: list[FunctionInfo]
    line_number: int


@dataclass
class ParsedFile:
    """Structured representation of a source file after static analysis."""
    file_path: str          # Relative path (for display)
    language: str
    module_docstring: str | None
    imports: list[str]
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    line_count: int
    parse_error: str | None = None


def parse_file(file_path: Path, relative_path: str, language: str) -> ParsedFile:
    """
    Parse a source file and extract structured information.

    Args:
        file_path:     Absolute path to the source file.
        relative_path: Relative path from repo root (for display only).
        language:      "python" | "javascript" | "typescript"

    Returns:
        ParsedFile with all extracted information.
    """
    source = safe_read(file_path)
    if source is None:
        return ParsedFile(
            file_path=relative_path, language=language,
            module_docstring=None, imports=[], functions=[], classes=[],
            line_count=0, parse_error="File could not be read.",
        )

    line_count = source.count("\n") + 1

    if language == "python":
        return _parse_python(source, relative_path, line_count)
    else:
        return _parse_js_ts(source, relative_path, language, line_count)


# ── Python Parser (AST-based) ─────────────────────────────────────────────────

def _parse_python(source: str, file_path: str, line_count: int) -> ParsedFile:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ParsedFile(
            file_path=file_path, language="python",
            module_docstring=None, imports=[], functions=[], classes=[],
            line_count=line_count, parse_error=f"SyntaxError: {e}",
        )

    module_docstring = ast.get_docstring(tree)
    imports = _extract_python_imports(tree)
    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node.col_offset, int) and node.col_offset == 0:
                functions.append(_extract_python_function(node))
        elif isinstance(node, ast.ClassDef):
            classes.append(_extract_python_class(node))

    return ParsedFile(
        file_path=file_path, language="python",
        module_docstring=module_docstring, imports=imports,
        functions=functions, classes=classes, line_count=line_count,
    )


def _get_node_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        if hasattr(node.value, "id"):
            return f"{node.value.id}.{node.attr}"
        return node.attr
    return "unknown"


def _extract_python_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    return FunctionInfo(
        name=node.name,
        docstring=ast.get_docstring(node),
        args=[arg.arg for arg in node.args.args],
        is_async=isinstance(node, ast.AsyncFunctionDef),
        line_number=node.lineno,
        decorators=[_get_node_name(dec) for dec in node.decorator_list],
    )


def _extract_python_class(node: ast.ClassDef) -> ClassInfo:
    return ClassInfo(
        name=node.name,
        docstring=ast.get_docstring(node),
        base_classes=[_get_node_name(base) for base in node.bases],
        methods=[
            _extract_python_function(item)
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ],
        line_number=node.lineno,
    )


def _extract_python_imports(tree: ast.AST) -> list[str]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return sorted(set(imports))


# ── JavaScript / TypeScript Parser ────────────────────────────────────────────

def _parse_js_ts(source: str, file_path: str, language: str, line_count: int) -> ParsedFile:
    if not TS_AVAILABLE:
        return ParsedFile(
            file_path=file_path, language=language, module_docstring=None,
            imports=_extract_js_imports_regex(source),
            functions=_extract_js_functions_regex(source),
            classes=_extract_js_classes_regex(source),
            line_count=line_count,
        )

    if file_path.endswith(".ts"):
        lang = Language(tstypescript.language_typescript())
    elif file_path.endswith(".tsx"):
        lang = Language(tstypescript.language_tsx())
    else:
        lang = Language(tsjavascript.language())

    parser = Parser(lang)
    tree = parser.parse(source.encode("utf8"))

    import_query = lang.query("(import_statement source: (string) @import)")
    function_query = lang.query("""
        (function_declaration name: (identifier) @name parameters: (formal_parameters) @params)
        (lexical_declaration (variable_declarator name: (identifier) @name value: (arrow_function parameters: (formal_parameters) @params)))
    """)
    class_query = lang.query("(class_declaration name: (identifier) @name)")

    imports = []
    for match in import_query.matches(tree.root_node):
        for node in match[1].values():
            if isinstance(node, list): node = node[0]
            imports.append(node.text.decode("utf8").strip("'\""))
    imports = sorted(set(imports))

    functions = []
    for match in function_query.matches(tree.root_node):
        nodes = match[1]
        name_node = nodes.get("name")
        params_node = nodes.get("params")
        if isinstance(name_node, list): name_node = name_node[0]
        if isinstance(params_node, list): params_node = params_node[0]
        if name_node and params_node:
            name = name_node.text.decode("utf8")
            params = [p.strip() for p in params_node.text.decode("utf8").strip("()").split(",") if p.strip()]
            functions.append(FunctionInfo(
                name=name, docstring=None, args=params,
                is_async=b"async" in source[:name_node.start_byte][-20:].lower().encode(),
                line_number=name_node.start_point[0] + 1,
            ))

    classes = []
    for match in class_query.matches(tree.root_node):
        nodes = match[1]
        name_node = nodes.get("name")
        if isinstance(name_node, list): name_node = name_node[0]
        if name_node:
            classes.append(ClassInfo(
                name=name_node.text.decode("utf8"), docstring=None,
                base_classes=[], methods=[], line_number=name_node.start_point[0] + 1,
            ))

    return ParsedFile(
        file_path=file_path, language=language, module_docstring=None,
        imports=imports, functions=functions, classes=classes, line_count=line_count,
    )


def _extract_js_functions_regex(source: str) -> list[FunctionInfo]:
    patterns = [
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
        r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>",
    ]
    functions = []
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            functions.append(FunctionInfo(
                name=match.group(1),
                docstring=None,
                args=[a.strip() for a in match.group(2).split(",") if a.strip()],
                is_async="async" in match.group(0),
                line_number=source[:match.start()].count("\n") + 1,
            ))
    return functions


def _extract_js_classes_regex(source: str) -> list[ClassInfo]:
    return [
        ClassInfo(
            name=m.group(1), docstring=None,
            base_classes=[m.group(2)] if m.group(2) else [],
            methods=[], line_number=source[:m.start()].count("\n") + 1,
        )
        for m in re.finditer(r"(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", source)
    ]


def _extract_js_imports_regex(source: str) -> list[str]:
    imports = set()
    for m in re.finditer(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", source):
        imports.add(m.group(1))
    for m in re.finditer(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", source):
        imports.add(m.group(1))
    return sorted(imports)
