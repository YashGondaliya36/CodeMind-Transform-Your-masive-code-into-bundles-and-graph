"""
codemind_okf/cli.py — Main CLI Entry Point
==========================================
`codemind index .`  — Generate OKF bundle from a local codebase
`codemind init`     — Drop AI IDE config files (.cursorrules, AGENTS.md, etc.)
`codemind status`   — Show current bundle stats

Usage:
    pip install codemind-okf
    cd my-project
    codemind index .
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from codemind_okf.core.crawler import crawl
from codemind_okf.core.parser import parse_file
from codemind_okf.core.summarizer import summarize_fast
from codemind_okf.core.writer import write_okf_file
from codemind_okf.core.index_builder import build_index, append_to_log

app = typer.Typer(
    name="codemind",
    help="CodeMind OKF — Generate AI-ready knowledge bundles for any codebase.",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── Commands ──────────────────────────────────────────────────────────────────


@app.command()
def index(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the project root (default: current directory).",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Path = typer.Option(
        None,
        "--output", "-o",
        help="Output directory for the .okf bundle (default: <path>/.okf).",
    ),
    languages: str = typer.Option(
        "python,javascript,typescript",
        "--lang", "-l",
        help="Comma-separated list of languages to index.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing .okf bundle instead of incrementally updating.",
    ),
):
    """
    [bold green]Generate an OKF knowledge bundle from a local codebase.[/bold green]

    Crawls the project directory, parses all source files with AST analysis,
    and writes structured .okf/modules/*.md files. Zero LLM cost.

    Examples:
        codemind index .
        codemind index /path/to/my-project
        codemind index . --lang python
    """
    project_root = path.resolve()
    bundle_root = output or (project_root / ".okf")
    project_name = project_root.name
    lang_list = [l.strip() for l in languages.split(",") if l.strip()]

    # ── Banner ────────────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold white]CodeMind OKF Indexer[/bold white]\n"
        f"[dim]Project:[/dim] [cyan]{project_root}[/cyan]\n"
        f"[dim]Output: [/dim] [cyan]{bundle_root}[/cyan]\n"
        f"[dim]Languages:[/dim] [yellow]{', '.join(lang_list)}[/yellow]",
        border_style="green",
        expand=False,
    ))

    # ── Handle overwrite ──────────────────────────────────────────────────────
    modules_dir = bundle_root / "modules"
    if overwrite and bundle_root.exists():
        console.print("[yellow]⚠ Overwrite mode: removing existing bundle...[/yellow]")
        shutil.rmtree(bundle_root)
    modules_dir.mkdir(parents=True, exist_ok=True)

    # ── Crawl ─────────────────────────────────────────────────────────────────
    console.print("\n[bold]🔍 Crawling project files...[/bold]")
    result = crawl(project_root, lang_list)

    if result.total_files == 0:
        console.print("[red]✗ No source files found. Check the path and language flags.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"  Found [bold green]{result.total_files}[/bold green] files "
        f"([dim]{result.skipped_count} skipped[/dim])"
    )

    # ── Parse + Summarize + Write ─────────────────────────────────────────────
    written = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("[green]Indexing modules...", total=result.total_files)

        for crawled in result.files:
            progress.update(task, description=f"[cyan]{crawled.relative_path}[/cyan]")
            try:
                parsed = parse_file(crawled.path, crawled.relative_path, crawled.language)
                summary = summarize_fast(parsed)
                write_okf_file(bundle_root, parsed, summary)
                written += 1
            except Exception as e:
                errors += 1
                console.print(f"  [red]✗ {crawled.relative_path}: {e}[/red]")
            finally:
                progress.advance(task)

    # ── Build index.md ────────────────────────────────────────────────────────
    console.print("\n[bold]📚 Building index.md...[/bold]")
    build_index(bundle_root, project_name)
    append_to_log(bundle_root, f"codemind index — {written} modules, {errors} errors")

    # ── Summary ───────────────────────────────────────────────────────────────
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[green]✓ Modules indexed[/green]", f"[bold]{written}[/bold]")
    table.add_row("[yellow]⚠ Errors[/yellow]", f"[bold]{errors}[/bold]")
    table.add_row("[blue]Bundle location[/blue]", f"[cyan]{bundle_root}[/cyan]")

    console.print(Panel(
        table,
        title="[bold green]✓ Indexing Complete[/bold green]",
        border_style="green",
    ))

    console.print(
        "\n[dim]Next step:[/dim] Run [bold]codemind init[/bold] to drop AI IDE config files "
        "into this project.\n"
    )


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."),
        help="Project root to initialise (default: current directory).",
        resolve_path=True,
    ),
    cursor: bool = typer.Option(True, help="Generate .cursorrules for Cursor AI."),
    agents: bool = typer.Option(True, help="Generate .agents/AGENTS.md for Antigravity/AI IDEs."),
    copilot: bool = typer.Option(True, help="Generate .github/copilot-instructions.md."),
):
    """
    [bold green]Drop AI IDE instruction files into a project.[/bold green]

    Generates .cursorrules, .agents/AGENTS.md, and .github/copilot-instructions.md
    to tell Cursor, Antigravity, and GitHub Copilot to use the .okf/ bundle as context.

    Examples:
        codemind init
        codemind init /path/to/my-project
    """
    project_root = path.resolve()
    bundle_path = project_root / ".okf"

    if not bundle_path.exists():
        console.print(
            "[yellow]⚠ No .okf bundle found. Run [bold]codemind index .[/bold] first.[/yellow]"
        )

    template_content = {
        "cursorrules": (TEMPLATES_DIR / "cursorrules.txt").read_text(encoding="utf-8"),
        "agents_md": (TEMPLATES_DIR / "agents_md.txt").read_text(encoding="utf-8"),
        "copilot": (TEMPLATES_DIR / "copilot_instructions.txt").read_text(encoding="utf-8"),
    }

    created = []

    if cursor:
        dest = project_root / ".cursorrules"
        dest.write_text(template_content["cursorrules"], encoding="utf-8")
        created.append(str(dest.relative_to(project_root)))

    if agents:
        agents_dir = project_root / ".agents"
        agents_dir.mkdir(exist_ok=True)
        dest = agents_dir / "AGENTS.md"
        dest.write_text(template_content["agents_md"], encoding="utf-8")
        created.append(str(dest.relative_to(project_root)))

    if copilot:
        gh_dir = project_root / ".github"
        gh_dir.mkdir(exist_ok=True)
        dest = gh_dir / "copilot-instructions.md"
        dest.write_text(template_content["copilot"], encoding="utf-8")
        created.append(str(dest.relative_to(project_root)))

    console.print(Panel(
        "\n".join(f"[green]✓[/green] [cyan]{f}[/cyan]" for f in created),
        title="[bold green]✓ AI IDE Config Files Created[/bold green]",
        border_style="green",
    ))
    console.print(
        "\n[dim]These files tell Cursor, Antigravity, and Copilot to use [/dim]"
        "[cyan].okf/index.md[/cyan][dim] as their primary codebase context.[/dim]\n"
    )


@app.command()
def status(
    path: Path = typer.Argument(Path("."), help="Project root.", resolve_path=True),
):
    """
    [bold green]Show the current OKF bundle stats for a project.[/bold green]
    """
    bundle_root = path.resolve() / ".okf"

    if not bundle_root.exists():
        console.print(
            "[red]✗ No .okf bundle found.[/red] "
            "Run [bold cyan]codemind index .[/bold cyan] to generate one."
        )
        raise typer.Exit(code=1)

    modules_dir = bundle_root / "modules"
    module_files = list(modules_dir.glob("*.md")) if modules_dir.is_dir() else []

    type_counts: dict[str, int] = {}
    for md in module_files:
        try:
            import frontmatter as fm
            post = fm.loads(md.read_text(encoding="utf-8"))
            t = str(post.metadata.get("type", "module"))
            type_counts[t] = type_counts.get(t, 0) + 1
        except Exception:
            type_counts["unknown"] = type_counts.get("unknown", 0) + 1

    table = Table(title=f"OKF Bundle — {path.resolve().name}", box=None)
    table.add_column("Layer", style="cyan", no_wrap=True)
    table.add_column("Files", style="green", justify="right")

    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        table.add_row(t.title(), str(count))

    table.add_section()
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{len(module_files)}[/bold]")

    console.print(table)


@app.command()
def action(
    path: Path = typer.Argument(
        Path("."),
        help="Project root (default: current directory).",
        resolve_path=True,
    ),
):
    """
    [bold green]Add a GitHub Action that auto-builds the OKF bundle on every push.[/bold green]

    Creates .github/workflows/okf-build.yml in the project.
    Whenever code is pushed to main, the bundle is regenerated automatically.

    Example:
        codemind action
    """
    project_root = path.resolve()
    workflows_dir = project_root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    action_template = (TEMPLATES_DIR / "github_action.yml").read_text(encoding="utf-8")
    dest = workflows_dir / "okf-build.yml"
    dest.write_text(action_template, encoding="utf-8")

    console.print(Panel(
        f"[green]✓[/green] [cyan]{dest.relative_to(project_root)}[/cyan]\n\n"
        "[dim]Commit and push this file to GitHub. On every push to main,\n"
        "the OKF bundle will be auto-regenerated and committed back.[/dim]",
        title="[bold green]✓ GitHub Action Created[/bold green]",
        border_style="green",
    ))


@app.command()
def mcp():
    """
    [bold green]Start Model Context Protocol (MCP) server over STDIO.[/bold green]

    Connects CodeMind tools natively to Cursor, Claude Desktop, Antigravity, or Zed.

    Example mcp.json config for Cursor / Claude Desktop:
    {
      "mcpServers": {
        "codemind": {
          "command": "codemind",
          "args": ["mcp"]
        }
      }
    }
    """
    from codemind_okf.mcp import run_mcp_server
    run_mcp_server()


def main():
    app()


if __name__ == "__main__":
    main()

