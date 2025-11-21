"""
Plan command for docman CLI.

This module contains the plan command which generates LLM organization
suggestions for scanned documents.
"""

from pathlib import Path

import click

from docman.cli.utils import (
    cleanup_orphaned_copies,
    get_duplicate_summary,
    require_database,
)
from docman.database import get_session
from docman.llm_config import get_active_provider, get_api_key
from docman.llm_providers import get_provider as get_llm_provider
from docman.llm_wizard import run_llm_wizard
from docman.models import (
    Document,
    DocumentCopy,
    Operation,
    OperationStatus,
    OrganizationStatus,
    file_needs_rehashing,
    get_utc_now,
)
from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    format_examples,
    generate_instructions,
    get_examples,
    serialize_folder_definitions,
)
from docman.repo_config import get_folder_definitions, get_variable_patterns
from docman.repository import (
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    discover_document_files,
    discover_document_files_shallow,
    get_repository_root,
)


@click.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively process subdirectories",
)
@click.option(
    "--reprocess",
    is_flag=True,
    default=False,
    help="Reprocess all files, including those already organized or ignored",
)
@click.option(
    "--scan",
    "scan_first",
    is_flag=True,
    default=False,
    help="Scan for new documents before generating suggestions",
)
@require_database
def plan(
    path: str | None,
    recursive: bool,
    reprocess: bool,
    scan_first: bool,
) -> None:
    """
    Generate LLM organization suggestions for scanned documents.

    This command processes documents that have already been scanned (via 'docman scan')
    and generates LLM-powered organization suggestions for them.

    Arguments:
        PATH: Optional path to a file or directory (default: entire repository).
              Relative to current working directory.

    Options:
        -r, --recursive: Recursively process subdirectories when PATH is a directory.
        --reprocess: Reprocess all files, including those already organized or ignored.
        --scan: Scan for new documents before generating suggestions.

    Examples:
        - 'docman plan': Generate suggestions for all unorganized documents
        - 'docman plan --scan': Scan entire repository, then generate suggestions
        - 'docman plan docs/': Generate suggestions for docs directory
        - 'docman plan docs/ -r': Generate suggestions for docs directory recursively
        - 'docman plan --reprocess': Reprocess all documents, including organized ones

    Note: Run 'docman scan' first to discover and extract content from new documents.
    """
    from docman.models import (
        OperationStatus,
        OrganizationStatus,
        operation_needs_regeneration,
        query_documents_needing_suggestions,
    )

    # Find the repository root
    repo_root = None

    if path:
        # Try to find repository from the provided path
        search_start_path = Path(path).resolve()
        try:
            repo_root = get_repository_root(start_path=search_start_path)
        except RepositoryError:
            # Path doesn't lead to a repository, try from cwd
            try:
                repo_root = get_repository_root(start_path=Path.cwd())
            except RepositoryError:
                # Neither path nor cwd is in a repository
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            raise click.Abort()

    repository_path = str(repo_root)

    # If --scan flag is set, run scan first
    if scan_first:
        from docman.cli.scan import scan as scan_command

        click.echo(f"Scanning documents in repository: {repository_path}\n")
        # Invoke scan command directly
        ctx = click.get_current_context()
        ctx.invoke(scan_command, path=path, recursive=recursive, rescan=False)
        click.echo()

    click.echo(f"Generating suggestions for documents in repository: {repository_path}")

    # Check if LLM provider is configured
    active_provider = get_active_provider()
    llm_provider_instance = None

    if not active_provider:
        click.echo()
        click.secho("No LLM provider configured.", fg="yellow")
        click.echo("An LLM provider is required to generate document organization suggestions.")
        click.echo()

        if not click.confirm("Would you like to set up an LLM provider now?"):
            click.echo("Aborted. Run 'docman llm add' to configure an LLM provider.")
            raise click.Abort()

        # Run wizard
        if not run_llm_wizard():
            click.secho("Setup failed or cancelled.", fg="yellow")
            raise click.Abort()

        # Get the newly configured provider
        active_provider = get_active_provider()
        if not active_provider:
            click.secho("Error: Failed to configure LLM provider.", fg="red")
            raise click.Abort()

    # Initialize LLM provider
    try:
        api_key = get_api_key(active_provider.name)
        if not api_key:
            click.secho(
                f"Error: API key not found for provider '{active_provider.name}'.",
                fg="red"
            )
            raise click.Abort()

        llm_provider_instance = get_llm_provider(active_provider, api_key)
        click.echo(f"Using LLM provider: {active_provider.name} ({active_provider.model})")
        click.echo()
    except Exception as e:
        click.secho(f"Error initializing LLM provider: {e}", fg="red")
        raise click.Abort()


    # Load organization instructions from folder definitions
    from docman.repo_config import get_default_filename_convention

    folder_definitions = get_folder_definitions(repo_root)
    if not folder_definitions:
        click.echo()
        click.secho(
            "Error: No folder definitions found.",
            fg="red",
        )
        click.echo()
        click.echo("Run 'docman define <path> --desc \"description\"' to create folder definitions.")
        click.echo("Or run 'docman pattern add <name> --desc \"description\"' to define variable patterns first.")
        raise click.Abort()

    default_filename_convention = get_default_filename_convention(repo_root)
    try:
        organization_instructions = generate_instructions(repo_root)
        if not organization_instructions:
            click.echo()
            click.secho("Error: Failed to generate instructions from folder definitions.", fg="red")
            raise click.Abort()
    except ValueError as e:
        # Catch YAML syntax errors from load_repo_config()
        click.secho(f"Error: {e}", fg="red")
        raise click.Abort()
    click.echo("Using instructions generated from folder definitions")
    click.echo()

    # Build prompts for LLM (done once for entire repository)
    # Use structured output if provider supports it
    system_prompt = build_system_prompt(
        use_structured_output=llm_provider_instance.supports_structured_output
    )

    # Get model name from active provider
    model_name = active_provider.model if active_provider else None

    # Compute prompt hash for caching (based on system prompt + organization instructions + model)
    # When using auto-instructions, include serialized folder definitions in the hash
    prompt_components = system_prompt
    if organization_instructions:
        prompt_components += "\n" + organization_instructions
    if model_name:
        prompt_components += "\n" + model_name
    if folder_definitions:
        # Include serialized folder definitions to detect structure changes
        prompt_components += "\n" + serialize_folder_definitions(
            folder_definitions, default_filename_convention
        )

    import hashlib
    sha256_hash = hashlib.sha256()
    sha256_hash.update(prompt_components.encode("utf-8"))
    current_prompt_hash = sha256_hash.hexdigest()

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Clean up orphaned copies (files that no longer exist)
        deleted_count, _ = cleanup_orphaned_copies(session, repo_root)
        if deleted_count > 0:
            click.echo(f"Cleaned up {deleted_count} orphaned file(s)\n")

        # Determine path filter for querying documents
        path_filter = None
        if path:
            # Validate and convert path
            target_path = Path(path).resolve()
            if not target_path.exists():
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

            # Validate path is within repository
            try:
                rel_path = target_path.relative_to(repo_root)
                path_filter = str(rel_path)
            except ValueError:
                click.secho(
                    f"Error: Path '{path}' is outside the repository at {repo_root}",
                    fg="red",
                    err=True,
                )
                raise click.Abort()

        # Query for scanned documents that need suggestions
        documents_to_process = query_documents_needing_suggestions(
            session=session,
            repo_root=repo_root,
            path_filter=path_filter,
            reprocess=reprocess,
            recursive=recursive,
        )

        if not documents_to_process:
            click.echo("No scanned documents found that need suggestions.")
            click.echo()
            click.echo("Tip: Run 'docman scan' to discover and extract content from new documents.")
            return

        click.echo(f"Found {len(documents_to_process)} scanned document(s) to process\n")

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

        # Count unscanned files for warning
        if path_filter:
            # Count files in the filtered path
            target_path = repo_root / path_filter
            if target_path.is_file():
                all_files = [target_path.relative_to(repo_root)]
            elif recursive:
                all_files = discover_document_files(repo_root, root_path=target_path) if target_path != repo_root else discover_document_files(repo_root)
            else:
                all_files = discover_document_files_shallow(repo_root, target_path)
        else:
            # Count all files in repository
            all_files = discover_document_files(repo_root)

        scanned_paths = {copy.file_path for copy, _ in documents_to_process}
        unscanned_files = [f for f in all_files if str(f) not in scanned_paths]
        unscanned_count = len(unscanned_files)

        if unscanned_count > 0:
            click.secho(
                f"Warning: Found {unscanned_count} unscanned file(s) in the specified path.",
                fg="yellow",
            )
            click.echo("   Run 'docman scan' to process these files first.")
            click.echo()

        # Counters for summary
        pending_ops_created = 0
        pending_ops_updated = 0
        skipped_count = 0

        # Process each scanned document
        for idx, (copy, document) in enumerate(documents_to_process, start=1):
            file_path_str = copy.file_path
            percentage = int((idx / len(documents_to_process)) * 100)

            # Show progress
            click.echo(
                f"[{idx}/{len(documents_to_process)}] {percentage}% "
                f"Generating suggestions: {file_path_str}"
            )

            # Check if document has content (extraction must have succeeded during scan)
            if not document or not document.content:
                click.echo("  Skipping (no content available)")
                skipped_count += 1
                continue

            # Check for existing pending operation
            existing_pending_op = (
                session.query(Operation)
                .filter(Operation.document_copy_id == copy.id)
                .filter(Operation.status == OperationStatus.PENDING)
                .first()
            )

            # Determine if we need to generate new suggestions
            needs_generation, invalidation_reason = operation_needs_regeneration(
                operation=existing_pending_op,
                current_prompt_hash=current_prompt_hash,
                document_content_hash=document.content_hash,
                model_name=model_name,
            )

            # Reset organization status if conditions changed
            if invalidation_reason and copy.organization_status == OrganizationStatus.ORGANIZED:
                copy.organization_status = OrganizationStatus.UNORGANIZED

            if needs_generation and invalidation_reason:
                click.echo(f"  {invalidation_reason}, regenerating suggestions...")

            if needs_generation:
                # Use LLM to generate suggestions
                try:
                    # Build user prompt with document-specific information
                    user_prompt = build_user_prompt(
                        file_path_str,
                        document.content,
                        organization_instructions,
                        examples=examples_str,
                    )
                    suggestions = llm_provider_instance.generate_suggestions(
                        system_prompt,
                        user_prompt
                    )

                    if existing_pending_op:
                        # Update existing pending operation
                        existing_pending_op.suggested_directory_path = suggestions["suggested_directory_path"]
                        existing_pending_op.suggested_filename = suggestions["suggested_filename"]
                        existing_pending_op.reason = suggestions["reason"]
                        existing_pending_op.prompt_hash = current_prompt_hash
                        existing_pending_op.document_content_hash = document.content_hash
                        existing_pending_op.model_name = model_name
                        pending_ops_updated += 1
                    else:
                        # Create new pending operation
                        pending_op = Operation(
                            document_copy_id=copy.id,
                            suggested_directory_path=suggestions["suggested_directory_path"],
                            suggested_filename=suggestions["suggested_filename"],
                            reason=suggestions["reason"],
                            prompt_hash=current_prompt_hash,
                            document_content_hash=document.content_hash,
                            model_name=model_name,
                        )
                        session.add(pending_op)
                        pending_ops_created += 1

                    click.echo(
                        f"  -> {suggestions['suggested_directory_path']}/"
                        f"{suggestions['suggested_filename']}"
                    )
                except Exception as e:
                    # Skip file if LLM fails
                    click.echo(f"  Warning: LLM suggestion failed ({str(e)}), skipping")
                    # Delete existing pending operation if it exists (now invalid)
                    if existing_pending_op:
                        session.delete(existing_pending_op)
                    skipped_count += 1
            else:
                click.echo("  Reusing existing suggestions (prompt unchanged)")

        # Commit all changes
        session.commit()

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Summary:")
        click.echo(f"  Pending operations created: {pending_ops_created}")
        click.echo(f"  Pending operations updated: {pending_ops_updated}")
        click.echo(f"  Skipped (no content or LLM errors): {skipped_count}")
        click.echo(f"  Total scanned documents processed: {len(documents_to_process)}")
        if unscanned_count > 0:
            click.echo(f"  Unscanned files found: {unscanned_count}")
        click.echo("=" * 50)

        # Check for duplicates and show warning
        unique_dup_docs, total_dup_copies = get_duplicate_summary(session, repo_root)
        if unique_dup_docs > 0:
            click.echo()
            click.secho(
                f"Warning: Found {unique_dup_docs} duplicate document(s) "
                f"with {total_dup_copies} total copies",
                fg="yellow",
            )
            click.echo()
            click.echo("Tip: Run 'docman dedupe' to resolve duplicate files")
            click.echo("       before generating LLM suggestions to save costs.")
            click.echo()
            if pending_ops_created > 0 or pending_ops_updated > 0:
                click.echo(
                    f"Note: {pending_ops_created + pending_ops_updated} LLM suggestion(s) were generated."
                )
                estimated_saveable = sum(
                    1
                    for doc_id, copies in find_duplicate_groups(session, repo_root).items()
                    if len(copies) > 1
                    for _ in copies[1:]  # All but one copy per group
                )
                if estimated_saveable > 0:
                    click.echo(
                        f"      ~{estimated_saveable} LLM call(s) could be saved by deduplicating first."
                    )
        click.echo()

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass
