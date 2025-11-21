"""Debug-prompt command for docman CLI.

This module contains the debug-prompt command for generating and displaying
the LLM prompt that would be sent for a specific file.
"""

import json
from pathlib import Path

import click

from docman.cli.utils import require_database
from docman.database import get_session
from docman.llm_config import get_active_provider, get_api_key
from docman.llm_providers import get_provider as get_llm_provider
from docman.models import DocumentCopy, file_needs_rehashing
from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    format_examples,
    generate_instructions,
    get_examples,
)
from docman.repository import (
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    get_repository_root,
)


@click.command("debug-prompt")
@click.argument("file_path", type=str)
@require_database
def debug_prompt(file_path: str) -> None:
    """
    Generate and display the LLM prompt for a specific file.

    This debugging command shows the exact prompt that would be sent to the LLM
    for organizing the specified document. Useful for testing and debugging
    prompt templates.

    Arguments:
        FILE_PATH: Path to the document file (relative to current directory).

    Examples:
        - 'docman debug-prompt invoice.pdf': Show prompt for invoice.pdf
        - 'docman debug-prompt docs/report.pdf': Show prompt for report.pdf
    """
    from sqlalchemy import select

    from docman.processor import ProcessingResult, process_document_file

    # Find the repository root
    try:
        repo_root = get_repository_root(start_path=Path.cwd())
    except RepositoryError:
        click.secho("Error: Not in a docman repository.", fg="red", err=True)
        click.echo("Run 'docman init' to initialize a repository.")
        raise click.Abort()

    # Resolve the file path
    target_path = Path(file_path).resolve()

    # Validate file exists
    if not target_path.exists():
        click.secho(f"Error: File '{file_path}' does not exist", fg="red", err=True)
        raise click.Abort()

    # Validate file is within repository
    try:
        rel_path = target_path.relative_to(repo_root)
    except ValueError:
        click.secho(
            f"Error: File '{file_path}' is outside the repository at {repo_root}",
            fg="red",
            err=True,
        )
        raise click.Abort()

    # Validate file type
    if target_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        click.secho(
            f"Error: Unsupported file type '{target_path.suffix}'. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            fg="red",
            err=True,
        )
        raise click.Abort()

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Try to find existing document in database first
        file_path_str = str(rel_path)
        copy = session.execute(
            select(DocumentCopy)
            .where(DocumentCopy.repository_path == str(repo_root))
            .where(DocumentCopy.file_path == file_path_str)
        ).scalar_one_or_none()

        document_content = None
        needs_rescan = False

        # Check if we can reuse existing content from database
        if copy and copy.document and copy.document.content is not None:
            # Check if file has changed since last scan
            if file_needs_rehashing(copy, target_path):
                # File has changed, need to re-extract content
                click.echo(f"File has changed since last scan, re-extracting content from: {file_path_str}\n")
                needs_rescan = True
            else:
                # File unchanged, use existing content from database
                document_content = copy.document.content
                click.echo(f"Using existing content from database for: {file_path_str}\n")

        if document_content is None:
            # Need to extract content from file
            # Determine if this is a retry of a failed extraction (only if not already set due to stale content)
            if not needs_rescan:
                needs_rescan = copy and copy.document and copy.document.content is None

            if needs_rescan:
                click.echo(f"Re-extracting content (previous extraction failed) for: {file_path_str}\n")
            else:
                click.echo(f"Extracting content from: {file_path_str}\n")

            try:
                # Force rescan if we're retrying a failed extraction, otherwise process_document_file
                # will see unchanged metadata and return REUSED_COPY without re-extracting
                copy, result = process_document_file(
                    session, repo_root, rel_path, str(repo_root), rescan=needs_rescan
                )

                if result in (ProcessingResult.NEW_DOCUMENT, ProcessingResult.DUPLICATE_DOCUMENT,
                             ProcessingResult.CONTENT_UPDATED, ProcessingResult.REUSED_COPY) and copy and copy.document:
                    document_content = copy.document.content

                    # Guard against None content even after successful processing result
                    if document_content is None:
                        click.secho(
                            "Error: Document content is empty after extraction",
                            fg="red",
                            err=True,
                        )
                        raise click.Abort()
                else:
                    error_msg = "Failed to extract content from file"
                    if result == ProcessingResult.EXTRACTION_FAILED:
                        error_msg = "Content extraction failed"
                    elif result == ProcessingResult.HASH_FAILED:
                        error_msg = "Failed to compute content hash"

                    click.secho(
                        f"Error: {error_msg}",
                        fg="red",
                        err=True,
                    )
                    raise click.Abort()
            except Exception as e:
                click.secho(f"Error: Failed to process document: {e}", fg="red", err=True)
                raise click.Abort()

        # Check if LLM provider is configured
        active_provider = get_active_provider()
        if not active_provider:
            click.secho(
                "Warning: No LLM provider configured. Using default settings.",
                fg="yellow",
            )
            click.echo("Run 'docman llm add' to configure an LLM provider.")
            click.echo()
            # Use default: structured output = True (like Gemini)
            supports_structured_output = True
        else:
            # Get provider settings
            try:
                api_key = get_api_key(active_provider.name)
                if api_key:
                    llm_provider_instance = get_llm_provider(active_provider, api_key)
                    supports_structured_output = llm_provider_instance.supports_structured_output
                else:
                    supports_structured_output = True
            except Exception:
                supports_structured_output = True

        # Load organization instructions from folder definitions
        try:
            organization_instructions = generate_instructions(repo_root)
            if not organization_instructions:
                click.secho(
                    "Error: No folder definitions found.",
                    fg="red",
                    err=True,
                )
                click.echo("Run 'docman define <path> --desc \"description\"' to create folder definitions.")
                raise click.Abort()
        except ValueError as e:
            # Catch YAML syntax errors from load_repo_config()
            click.secho(f"Error: {e}", fg="red", err=True)
            raise click.Abort()

        # Get examples from successfully organized documents
        examples_data = get_examples(
            session=session,
            repo_root=repo_root,
            limit=3,
        )

        examples_str = None
        if examples_data:
            examples_str = format_examples(examples_data)
            num_ex = len(examples_data)
            click.echo(f"Using {num_ex} example(s) from previously organized documents\n")

        # Build prompts
        system_prompt = build_system_prompt(use_structured_output=supports_structured_output)
        user_prompt = build_user_prompt(
            file_path_str, document_content, organization_instructions, examples=examples_str
        )

        # Display the prompts with nice formatting
        click.echo("=" * 80)
        click.secho("DEBUG PROMPT OUTPUT", bold=True, fg="cyan")
        click.echo("=" * 80)
        click.echo()
        click.secho(f"File: {file_path_str}", bold=True)
        click.echo(f"Content length: {len(document_content)} characters")
        if active_provider:
            click.echo(f"Provider: {active_provider.name}")
            click.echo(f"Model: {active_provider.model}")
        click.echo(f"Structured output: {supports_structured_output}")
        click.echo(f"Few-shot examples: {len(examples_data) if examples_data else 0}")
        click.echo()

        # System prompt section
        click.echo("=" * 80)
        click.secho("SYSTEM PROMPT", bold=True, fg="yellow")
        click.echo("=" * 80)
        click.echo()
        click.echo(system_prompt)
        click.echo()

        # User prompt section
        click.echo("=" * 80)
        click.secho("USER PROMPT", bold=True, fg="green")
        click.echo("=" * 80)
        click.echo()
        click.echo(user_prompt)
        click.echo()
        click.echo("=" * 80)

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
