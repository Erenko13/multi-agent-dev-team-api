from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_header(text: str) -> None:
    console.print(f"\n[bold cyan]{text}[/bold cyan]")
    console.print("[dim]" + "─" * 60 + "[/dim]")


def print_agent_status(agent_name: str, message: str) -> None:
    console.print(f"  [bold green]▶ {agent_name}[/bold green]: {message}")


def print_markdown(content: str) -> None:
    console.print(Markdown(content))


def print_file_list(files: list[dict]) -> None:
    table = Table(title="Generated Files", show_lines=False)
    table.add_column("Path", style="cyan")
    table.add_column("Language", style="green")
    for f in files:
        table.add_row(f.get("path", ""), f.get("language", ""))
    console.print(table)


def print_review_comments(comments: list[dict]) -> None:
    for c in comments:
        severity = c.get("severity", "info")
        color = {"critical": "red", "major": "yellow", "minor": "blue", "suggestion": "dim"}.get(severity, "white")
        console.print(f"  [{color}][{severity.upper()}][/{color}] {c.get('file_path', '')}:{c.get('line_range', '')} — {c.get('comment', '')}")


def print_test_results(results: list[dict]) -> None:
    for r in results:
        status = "[green]PASS[/green]" if r.get("passed") else "[red]FAIL[/red]"
        console.print(f"  {status} {r.get('test_file', '')}")


def print_checkpoint(question: str) -> None:
    console.print(Panel(f"[bold yellow]{question}[/bold yellow]", title="Human Checkpoint", border_style="yellow"))
