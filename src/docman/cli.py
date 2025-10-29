"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="docman")
def main() -> None:
    """docman - Organize documents using AI-powered tools."""
    pass


@main.command()
def organize() -> None:
    """Organize documents in the current directory."""
    click.echo("Document organization feature coming soon!")


if __name__ == "__main__":
    main()
