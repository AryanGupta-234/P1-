"""CLI for the local Microsoft Learn and GitHub knowledge index."""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from aie.config import data_dir
from aie.knowledge.crawler import KnowledgeStore, MicrosoftKnowledgeCrawler

knowledge_app = typer.Typer(
    no_args_is_help=True,
    help="Crawl approved Microsoft technical sources and search the local knowledge vault.",
)
console = Console()


def _store() -> KnowledgeStore:
    return KnowledgeStore(data_dir() / "knowledge" / "microsoft-knowledge.sqlite3")


@knowledge_app.command("crawl")
def crawl(
    learn_top: int = typer.Option(4, "--learn-top", min=1, max=10),
    github_files: int = typer.Option(8, "--github-files", min=1, max=20),
) -> None:
    """Fetch curated Microsoft Learn pages and Microsoft-owned GitHub Markdown."""
    try:
        result = MicrosoftKnowledgeCrawler(_store()).crawl(
            learn_top_per_query=learn_top,
            github_files_per_repo=github_files,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        console.print(f"[red]Knowledge crawl failed: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(2) from exc
    console.print("[green]Microsoft knowledge crawl finished.[/green]")
    console.print_json(json.dumps(result.to_dict(), indent=2))
    console.print_json(json.dumps(_store().stats(), indent=2))


@knowledge_app.command("search")
def search(
    query: str = typer.Argument(..., help="Search the locally indexed Microsoft documents."),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50),
) -> None:
    """Search the local index without making a network request."""
    try:
        results = _store().search(query, limit=limit)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Knowledge search failed: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(2) from exc
    if not results:
        console.print("[yellow]No local matches. Run aie knowledge crawl to populate the vault.[/yellow]")
        return
    table = Table("Rank", "Source", "Title", "Score")
    for index, result in enumerate(results, start=1):
        source = "Learn" if result["source"] == "microsoft_learn" else "GitHub"
        table.add_row(str(index), source, str(result["title"]), str(result["score"]))
    console.print(table)
    for index, result in enumerate(results, start=1):
        console.print(f"\n[bold cyan]{index}. {result['title']}[/bold cyan]")
        console.print(str(result["excerpt"]))
        console.print(f"[dim]{result['url']}[/dim]")


@knowledge_app.command("status")
def status() -> None:
    """Show the local knowledge index size and source mix."""
    try:
        stats = _store().stats()
    except OSError as exc:
        console.print(f"[red]Knowledge status unavailable: {type(exc).__name__}[/red]")
        raise typer.Exit(2) from exc
    console.print_json(json.dumps(stats, indent=2))


if __name__ == "__main__":
    knowledge_app()
