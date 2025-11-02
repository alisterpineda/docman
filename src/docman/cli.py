"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

from pathlib import Path

import click

from docling.document_converter import DocumentConverter

from docman.config import ensure_app_config
from docman.database import ensure_database, get_session
from docman.llm_config import (
    ProviderConfig,
    add_provider,
    get_active_provider,
    get_api_key,
    get_provider,
    get_providers,
    remove_provider,
    set_active_provider,
)
from docman.llm_providers import get_provider as get_llm_provider
from docman.llm_wizard import run_llm_wizard
from docman.models import Document, DocumentCopy, PendingOperation, compute_content_hash, get_utc_now, file_needs_rehashing
from docman.processor import extract_content
from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    compute_prompt_hash,
    load_organization_instructions,
)
from docman.repo_config import (
    create_instructions_template,
    edit_instructions_interactive,
    load_instructions,
    save_instructions,
)
from docman.repository import (
    SUPPORTED_EXTENSIONS,
    RepositoryError,
    discover_document_files,
    discover_document_files_shallow,
    get_repository_root,
)
from docman.file_operations import (
    ConflictResolution,
    FileConflictError,
    FileNotFoundError as DocmanFileNotFoundError,
    FileOperationError,
    move_file,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="docman")
def main() -> None:
    """docman - Organize documents using AI-powered tools."""
    try:
        ensure_app_config()
    except OSError as e:
        click.secho(
            f"Warning: Failed to initialize app config: {e}", fg="yellow", err=True
        )

    try:
        ensure_database()
    except Exception as e:
        click.secho(
            f"Warning: Failed to initialize database: {e}", fg="yellow", err=True
        )


@main.command()
@click.argument("directory", default=".")
def init(directory: str) -> None:
    """Initialize a new docman repository in the specified directory."""
    target_path = Path(directory).resolve()

    # Check if target directory exists
    if not target_path.exists():
        click.secho(f"Error: Directory '{directory}' does not exist", fg="red", err=True)
        raise click.Abort()

    if not target_path.is_dir():
        click.secho(f"Error: '{directory}' is not a directory", fg="red", err=True)
        raise click.Abort()

    docman_dir = target_path / ".docman"

    # Check if .docman already exists
    if docman_dir.exists():
        click.echo(f"docman repository already exists in {docman_dir}/")
        return

    # Create .docman directory and config.yaml
    try:
        docman_dir.mkdir(parents=True, exist_ok=True)

        # Create empty config.yaml
        config_file = docman_dir / "config.yaml"
        config_file.touch()

        # Create instructions template
        create_instructions_template(target_path)

        click.echo(f"Initialized empty docman repository in {docman_dir}/")
        click.echo()

        # Prompt to edit instructions
        if click.confirm("Would you like to edit document organization instructions now?", default=True):
            if edit_instructions_interactive(target_path):
                click.secho("✓ Instructions updated!", fg="green")
            else:
                click.secho(
                    "Warning: Could not open editor. Set $EDITOR or edit .docman/instructions.md manually.",
                    fg="yellow"
                )
        else:
            click.echo()
            click.echo("Instructions template created at .docman/instructions.md")
            click.echo("Edit this file before running 'docman plan'.")

    except PermissionError:
        click.secho(
            f"Error: Permission denied to create {docman_dir}", fg="red", err=True
        )
        raise click.Abort()
    except Exception as e:
        click.secho(
            f"Error: Failed to initialize repository: {e}", fg="red", err=True
        )
        raise click.Abort()


def cleanup_orphaned_copies(session, repo_root: Path) -> tuple[int, int]:
    """Clean up document copies for files that no longer exist.

    This function performs garbage collection by:
    1. Checking all DocumentCopy records for the repository
    2. Verifying if the file still exists on disk
    3. Deleting copies for missing files (cascades to PendingOperation)
    4. Updating last_seen_at for files that exist

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Tuple of (deleted_count, updated_count).
    """
    repository_path = str(repo_root)

    # Query all copies for this repository
    copies = (
        session.query(DocumentCopy)
        .filter(DocumentCopy.repository_path == repository_path)
        .all()
    )

    deleted_count = 0
    updated_count = 0
    current_time = get_utc_now()

    for copy in copies:
        file_path = repo_root / copy.file_path

        if not file_path.exists():
            # File no longer exists - delete the copy (cascades to pending operations)
            session.delete(copy)
            deleted_count += 1
        else:
            # File exists - update last_seen_at
            copy.last_seen_at = current_time
            updated_count += 1

    session.commit()
    return deleted_count, updated_count


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively process subdirectories",
)
def plan(path: str | None, recursive: bool) -> None:
    """
    Process documents in the repository.

    Discovers document files and extracts their content using docling,
    storing them in the database.

    Arguments:
        PATH: Optional path to a file or directory (default: current directory).
              Relative to current working directory.

    Options:
        -r, --recursive: Recursively process subdirectories when PATH is a directory.

    Examples:
        - 'docman plan': Process entire repository recursively (backward compatible)
        - 'docman plan .': Process current directory only (non-recursive)
        - 'docman plan docs/': Process docs directory only (non-recursive)
        - 'docman plan docs/ -r': Process docs directory recursively
        - 'docman plan file.pdf': Process single file
        - 'docman plan -r': Process entire repository recursively (same as no args)
    """
    # Find the repository root
    # Strategy: Try from the provided path first (if any), then fall back to cwd
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
    click.echo(f"Processing documents in repository: {repository_path}")

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

    # For backward compatibility: if no path provided, process entire repository recursively
    # This maintains the original behavior of 'docman plan' with no arguments
    if path is None and not recursive:
        # Default behavior - process entire repository recursively
        document_files = discover_document_files(repo_root)
        click.echo("Discovering documents recursively in entire repository...")
    else:
        # If path is None but recursive flag is set, treat as current directory
        if path is None:
            path = "."
        # Explicit path provided - handle accordingly
        # Convert path to absolute Path object
        target_path = Path(path).resolve()

        # Validate path exists
        if not target_path.exists():
            click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
            raise click.Abort()

        # Validate path is within repository
        try:
            target_path.relative_to(repo_root)
        except ValueError:
            click.secho(
                f"Error: Path '{path}' is outside the repository at {repo_root}",
                fg="red",
                err=True,
            )
            raise click.Abort()

        # Determine what files to process
        if target_path.is_file():
            # Single file mode
            if target_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                click.secho(
                    f"Error: Unsupported file type '{target_path.suffix}'. "
                    f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
                    fg="red",
                    err=True,
                )
                raise click.Abort()

            # Create list with single relative path
            rel_path = target_path.relative_to(repo_root)
            document_files = [rel_path]
            click.echo(f"Processing single file: {rel_path}")
        else:
            # Directory mode
            if recursive:
                # Recursive discovery from the target directory
                if target_path == repo_root:
                    document_files = discover_document_files(repo_root)
                    click.echo("Discovering documents recursively in entire repository...")
                else:
                    # Recursive discovery in subdirectory - pass target_path as root_path
                    document_files = discover_document_files(repo_root, root_path=target_path)
                    rel_target = target_path.relative_to(repo_root)
                    click.echo(f"Discovering documents recursively in: {rel_target}")
            else:
                # Shallow discovery - only immediate files
                document_files = discover_document_files_shallow(repo_root, target_path)
                rel_target = target_path.relative_to(repo_root)
                click.echo(f"Discovering documents in: {rel_target} (non-recursive)")

    if not document_files:
        click.echo("No document files found in repository.")
        return

    click.echo(f"Found {len(document_files)} document file(s)\n")

    # Check if document organization instructions exist (required)
    organization_instructions = load_organization_instructions(repo_root)
    if not organization_instructions:
        click.echo()
        click.secho("Error: Document organization instructions are required.", fg="red")
        click.echo()
        click.echo("Run 'docman config set-instructions' to create them.")
        raise click.Abort()

    # Build prompts for LLM (done once for entire repository)
    # Use structured output if provider supports it
    system_prompt = build_system_prompt(
        use_structured_output=llm_provider_instance.supports_structured_output
    )

    # Get model name from active provider
    model_name = active_provider.model if active_provider else None

    # Compute prompt hash for caching (based on system prompt + organization instructions + model)
    current_prompt_hash = compute_prompt_hash(system_prompt, organization_instructions, model_name)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Clean up orphaned copies (files that no longer exist)
        deleted_count, _ = cleanup_orphaned_copies(session, repo_root)
        if deleted_count > 0:
            click.echo(f"Cleaned up {deleted_count} orphaned file(s)\n")

        # Query existing copies in this repository
        existing_copies = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
            .all()
        )
        existing_copy_paths = {copy.file_path for copy in existing_copies}

        # Counters for summary
        processed_count = 0
        reused_count = 0
        failed_count = 0
        duplicate_count = 0  # Same document, different location
        pending_ops_created = 0
        pending_ops_updated = 0

        # Create a single DocumentConverter instance to reuse for all files
        converter = DocumentConverter()

        # Process each file
        for idx, file_path in enumerate(document_files, start=1):
            file_path_str = str(file_path)
            percentage = int((idx / len(document_files)) * 100)

            # Check if copy already exists in this repository at this path
            if file_path_str in existing_copy_paths:
                # Retrieve existing copy
                copy = (
                    session.query(DocumentCopy)
                    .filter(
                        DocumentCopy.repository_path == repository_path,
                        DocumentCopy.file_path == file_path_str,
                    )
                    .first()
                )
                if not copy:
                    click.echo("  Error: Expected copy not found in database")
                    failed_count += 1
                    continue

                full_path = repo_root / file_path

                # Check if file content has changed
                if file_needs_rehashing(copy, full_path):
                    click.echo(
                        f"[{idx}/{len(document_files)}] {percentage}% "
                        f"Checking for changes: {file_path}"
                    )

                    # File metadata changed, rehash to check content
                    try:
                        content_hash = compute_content_hash(full_path)
                    except Exception as e:
                        click.echo(f"  Error computing hash: {e}")
                        failed_count += 1
                        continue

                    # Check if content actually changed
                    if content_hash != copy.document.content_hash:
                        click.echo("  Content changed, updating document...")

                        # Content changed - update or create new document
                        new_document = (
                            session.query(Document)
                            .filter(Document.content_hash == content_hash)
                            .first()
                        )

                        if new_document:
                            # Document with this content already exists
                            click.echo(f"  Found existing document (hash: {content_hash[:8]}...)")
                            copy.document_id = new_document.id
                            duplicate_count += 1
                        else:
                            # Extract new content
                            content = extract_content(full_path, converter=converter)
                            if content is None:
                                click.echo("  Warning: Content extraction failed")
                            else:
                                click.echo(f"  Extracted {len(content)} characters")
                                processed_count += 1

                            # Create new document
                            new_document = Document(content_hash=content_hash, content=content)
                            session.add(new_document)
                            session.flush()

                            # Update copy to point to new document
                            copy.document_id = new_document.id

                        # Delete existing pending operation (will be regenerated)
                        session.query(PendingOperation).filter(
                            PendingOperation.document_copy_id == copy.id
                        ).delete()

                    # Update stored metadata
                    stat = full_path.stat()
                    copy.stored_content_hash = content_hash
                    copy.stored_size = stat.st_size
                    copy.stored_mtime = stat.st_mtime
                    session.flush()
                else:
                    click.echo(
                        f"[{idx}/{len(document_files)}] {percentage}% "
                        f"Reusing existing copy: {file_path}"
                    )
                    reused_count += 1
            else:
                # Show progress
                click.echo(f"[{idx}/{len(document_files)}] {percentage}% Processing: {file_path}")

                # Step 1: Create new document and copy
                # Compute content hash
                full_path = repo_root / file_path
                try:
                    content_hash = compute_content_hash(full_path)
                except Exception as e:
                    click.echo(f"  Error computing hash: {e}")
                    failed_count += 1
                    continue

                # Find or create canonical document
                document = (
                    session.query(Document)
                    .filter(Document.content_hash == content_hash)
                    .first()
                )

                if document:
                    # Document already exists (found in another repo or location)
                    click.echo(f"  Found existing document (hash: {content_hash[:8]}...)")
                    duplicate_count += 1
                else:
                    # New document - extract content
                    content = extract_content(full_path, converter=converter)

                    if content is None:
                        click.echo("  Warning: Content extraction failed")
                        failed_count += 1
                        # Still create the document with None content
                    else:
                        click.echo(f"  Extracted {len(content)} characters")
                        processed_count += 1

                    # Create new canonical document
                    document = Document(content_hash=content_hash, content=content)
                    session.add(document)
                    session.flush()  # Get the document.id for the copy

                # Create document copy for this repository with stored metadata
                stat = full_path.stat()
                copy = DocumentCopy(
                    document_id=document.id,
                    repository_path=repository_path,
                    file_path=file_path_str,
                    stored_content_hash=content_hash,
                    stored_size=stat.st_size,
                    stored_mtime=stat.st_mtime,
                )
                session.add(copy)
                session.flush()  # Get the copy.id for the pending operation

            # Step 2: Create or update pending operation based on prompt hash
            existing_pending_op = (
                session.query(PendingOperation)
                .filter(PendingOperation.document_copy_id == copy.id)
                .first()
            )

            # Get the document to check content hash
            document = session.query(Document).filter(Document.id == copy.document_id).first()

            # Determine if we need to generate new suggestions
            needs_generation = False
            invalidation_reason = None

            if not existing_pending_op:
                needs_generation = True
            elif existing_pending_op.prompt_hash != current_prompt_hash:
                # Prompt or model has changed, need to regenerate
                needs_generation = True
                invalidation_reason = "Prompt or model changed"
            elif document and existing_pending_op.document_content_hash != document.content_hash:
                # Document content has changed, need to regenerate
                needs_generation = True
                invalidation_reason = "Document content changed"
            elif model_name and existing_pending_op.model_name != model_name:
                # Model changed (redundant with prompt hash, but explicit)
                needs_generation = True
                invalidation_reason = "Model changed"

            if needs_generation and invalidation_reason:
                click.echo(f"  {invalidation_reason}, regenerating suggestions...")

            if needs_generation:
                # Generate LLM suggestions
                document = session.query(Document).filter(Document.id == copy.document_id).first()

                if document and document.content and llm_provider_instance:
                    # Use LLM to generate suggestions
                    try:
                        click.echo("  Generating LLM suggestions...")
                        # Build user prompt with document-specific information
                        user_prompt = build_user_prompt(
                            file_path_str,
                            document.content,
                            organization_instructions,
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
                            existing_pending_op.confidence = suggestions["confidence"]
                            existing_pending_op.prompt_hash = current_prompt_hash
                            existing_pending_op.document_content_hash = document.content_hash if document else None
                            existing_pending_op.model_name = model_name
                            pending_ops_updated += 1
                        else:
                            # Create new pending operation
                            pending_op = PendingOperation(
                                document_copy_id=copy.id,
                                suggested_directory_path=suggestions["suggested_directory_path"],
                                suggested_filename=suggestions["suggested_filename"],
                                reason=suggestions["reason"],
                                confidence=suggestions["confidence"],
                                prompt_hash=current_prompt_hash,
                                document_content_hash=document.content_hash if document else None,
                                model_name=model_name,
                            )
                            session.add(pending_op)
                            pending_ops_created += 1

                        click.echo(
                            f"  → {suggestions['suggested_directory_path']}/"
                            f"{suggestions['suggested_filename']}"
                        )
                    except Exception as e:
                        # Fallback to stub if LLM fails
                        click.echo(f"  Warning: LLM suggestion failed ({str(e)}), using fallback")
                        file_path_obj = Path(file_path_str)
                        current_directory = (
                            str(file_path_obj.parent) if file_path_obj.parent != Path('.') else ""
                        )
                        current_filename = file_path_obj.name

                        if existing_pending_op:
                            # Update existing pending operation
                            existing_pending_op.suggested_directory_path = current_directory
                            existing_pending_op.suggested_filename = current_filename
                            existing_pending_op.reason = "LLM analysis failed, kept original location"
                            existing_pending_op.confidence = 0.5
                            existing_pending_op.prompt_hash = current_prompt_hash
                            existing_pending_op.document_content_hash = document.content_hash if document else None
                            existing_pending_op.model_name = model_name
                            pending_ops_updated += 1
                        else:
                            # Create new pending operation
                            pending_op = PendingOperation(
                                document_copy_id=copy.id,
                                suggested_directory_path=current_directory,
                                suggested_filename=current_filename,
                                reason="LLM analysis failed, kept original location",
                                confidence=0.5,
                                prompt_hash=current_prompt_hash,
                                document_content_hash=document.content_hash if document else None,
                                model_name=model_name,
                            )
                            session.add(pending_op)
                            pending_ops_created += 1
                else:
                    # Fallback to stub if no content or LLM not available
                    file_path_obj = Path(file_path_str)
                    current_directory = (
                        str(file_path_obj.parent) if file_path_obj.parent != Path('.') else ""
                    )
                    current_filename = file_path_obj.name

                    if existing_pending_op:
                        # Update existing pending operation
                        existing_pending_op.suggested_directory_path = current_directory
                        existing_pending_op.suggested_filename = current_filename
                        existing_pending_op.reason = "No content available for analysis"
                        existing_pending_op.confidence = 0.5
                        existing_pending_op.prompt_hash = current_prompt_hash
                        existing_pending_op.document_content_hash = document.content_hash if document else None
                        existing_pending_op.model_name = model_name
                        pending_ops_updated += 1
                    else:
                        # Create new pending operation
                        pending_op = PendingOperation(
                            document_copy_id=copy.id,
                            suggested_directory_path=current_directory,
                            suggested_filename=current_filename,
                            reason="No content available for analysis",
                            confidence=0.5,
                            prompt_hash=current_prompt_hash,
                            document_content_hash=document.content_hash if document else None,
                            model_name=model_name,
                        )
                        session.add(pending_op)
                        pending_ops_created += 1
            else:
                click.echo("  Reusing existing suggestions (prompt unchanged)")

        # Commit all changes
        session.commit()

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Summary:")
        click.echo(f"  New documents processed: {processed_count}")
        click.echo(f"  Duplicate documents (already known): {duplicate_count}")
        click.echo(f"  Reused copies (already in this repo): {reused_count}")
        click.echo(f"  Failed (hash or extraction errors): {failed_count}")
        click.echo(f"  Pending operations created: {pending_ops_created}")
        click.echo(f"  Pending operations updated: {pending_ops_updated}")
        click.echo(f"  Total files: {len(document_files)}")
        click.echo("=" * 50)

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.command()
@click.argument("path", default=None, required=False)
def status(path: str | None) -> None:
    """
    Show pending organization operations for a repository.

    Displays all pending operations with suggested file reorganizations,
    including confidence scores and reasons for each suggestion.

    Arguments:
        PATH: Optional path to filter operations (default: show all in repository).

    Examples:
        - 'docman status': Show all pending operations
        - 'docman status docs/': Show pending operations in docs directory
        - 'docman status file.pdf': Show pending operation for specific file
    """
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
                click.secho(
                    "Error: Not in a docman repository. Use 'docman init' to create one.",
                    fg="red",
                    err=True,
                )
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            click.secho(
                "Error: Not in a docman repository. Use 'docman init' to create one.",
                fg="red",
                err=True,
            )
            raise click.Abort()

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query pending operations for this repository
        query = (
            session.query(PendingOperation, DocumentCopy)
            .join(DocumentCopy, PendingOperation.document_copy_id == DocumentCopy.id)
            .filter(DocumentCopy.repository_path == repository_path)
        )

        # Filter by path if provided
        if path:
            target_path = Path(path).resolve()

            # Check if path is a file or directory
            if target_path.is_file():
                # Single file - filter by exact match
                rel_path = str(target_path.relative_to(repo_root))
                query = query.filter(DocumentCopy.file_path == rel_path)
            elif target_path.is_dir():
                # Directory - filter by prefix
                rel_path = str(target_path.relative_to(repo_root))
                # Match files in this directory (prefix match)
                query = query.filter(DocumentCopy.file_path.startswith(rel_path))

        pending_ops = query.all()

        if not pending_ops:
            click.echo("No pending operations found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Display header
        click.echo()
        click.secho(f"Pending Operations ({len(pending_ops)}):", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
        click.echo()

        # Display each operation
        for idx, (pending_op, doc_copy) in enumerate(pending_ops, start=1):
            # Determine confidence color
            confidence = pending_op.confidence
            if confidence >= 0.8:
                confidence_color = "green"
            elif confidence >= 0.6:
                confidence_color = "yellow"
            else:
                confidence_color = "red"

            # Current path
            current_path = doc_copy.file_path

            # Suggested path
            suggested_dir = pending_op.suggested_directory_path
            suggested_filename = pending_op.suggested_filename
            if suggested_dir:
                suggested_path = f"{suggested_dir}/{suggested_filename}"
            else:
                suggested_path = suggested_filename

            # Check if it's a move or just a rename
            if current_path == suggested_path:
                operation_type = "(no change)"
                op_color = "white"
            else:
                operation_type = ""
                op_color = "cyan"

            # Display operation
            click.echo(f"[{idx}] {current_path}")
            click.secho(f"  → {suggested_path} {operation_type}", fg=op_color)
            click.secho(f"  Confidence: {confidence:.0%}", fg=confidence_color)
            click.echo(f"  Reason: {pending_op.reason}")
            click.echo()

        # Display summary
        click.echo("=" * 50)
        click.echo(f"Total pending operations: {len(pending_ops)}")
        click.echo()
        click.echo("To apply these changes, run:")
        click.echo("  docman apply --all       # Review each operation interactively")
        click.echo("  docman apply --all -y    # Apply all operations without prompts")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "--all",
    "-a",
    "apply_all",
    is_flag=True,
    default=False,
    help="Apply all pending operations",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing files at target locations",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview changes without applying them",
)
def apply(path: str | None, apply_all: bool, yes: bool, force: bool, dry_run: bool) -> None:
    """
    Apply pending organization operations.

    Moves files to their suggested locations based on LLM analysis.

    By default (without -y flag), runs in interactive mode where you can
    review each operation individually and choose to apply or skip it.

    Arguments:
        PATH: Optional path to apply operations for (default: requires --all flag).

    Options:
        --all, -a: Apply all pending operations in the repository
        -y, --yes: Skip confirmation prompts and interactive mode (auto-approve all)
        --force: Overwrite existing files at target locations
        --dry-run: Preview what would happen without making changes

    Interactive Mode:
        When running without -y, you'll be prompted for each operation with:
        [A]pply - Move the file to suggested location
        [S]kip  - Skip this operation (keeps it pending)
        [Q]uit  - Stop processing and exit
        [H]elp  - Show help for available options

    Examples:
        - 'docman apply --all': Interactive mode for all operations
        - 'docman apply --all -y': Apply all without prompts (bulk mode)
        - 'docman apply docs/': Interactive mode for docs directory
        - 'docman apply file.pdf': Interactive mode for single file
        - 'docman apply file.pdf -y': Apply single file without prompt
        - 'docman apply --all --dry-run': Preview all changes
    """
    # Validate flags
    if not apply_all and not path:
        click.secho(
            "Error: Must specify either --all or a PATH to apply operations.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman apply --all -y")
        click.echo("  docman apply docs/")
        click.echo("  docman apply file.pdf")
        raise click.Abort()

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
                click.secho(
                    "Error: Not in a docman repository. Use 'docman init' to create one.",
                    fg="red",
                    err=True,
                )
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            click.secho(
                "Error: Not in a docman repository. Use 'docman init' to create one.",
                fg="red",
                err=True,
            )
            raise click.Abort()

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query pending operations for this repository
        query = (
            session.query(PendingOperation, DocumentCopy)
            .join(DocumentCopy, PendingOperation.document_copy_id == DocumentCopy.id)
            .filter(DocumentCopy.repository_path == repository_path)
        )

        # Filter by path if provided
        if path:
            target_path = Path(path).resolve()

            # Check if path is a file or directory
            if target_path.is_file():
                # Single file - filter by exact match
                rel_path = str(target_path.relative_to(repo_root))
                query = query.filter(DocumentCopy.file_path == rel_path)
            elif target_path.is_dir():
                # Directory - filter by prefix
                rel_path = str(target_path.relative_to(repo_root))
                # Match files in this directory (prefix match)
                query = query.filter(DocumentCopy.file_path.startswith(rel_path))
            else:
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

        pending_ops = query.all()

        if not pending_ops:
            click.echo("No pending operations found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Show what will be applied
        click.echo()
        if dry_run:
            click.secho("DRY RUN - No changes will be made", fg="yellow", bold=True)
            click.echo()

        click.secho(f"Operations to apply: {len(pending_ops)}", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
        click.echo()

        # Determine if we should run in interactive mode
        # Interactive mode: when user hasn't provided -y flag and not in dry-run
        interactive_mode = not yes and not dry_run

        # No additional confirmation needed - either interactive mode handles per-op,
        # or -y flag means user already confirmed they want to auto-apply all

        # Determine conflict resolution strategy
        conflict_resolution = ConflictResolution.OVERWRITE if force else ConflictResolution.SKIP

        # Apply each operation
        applied_count = 0
        skipped_count = 0
        failed_count = 0
        failed_operations = []
        user_quit = False
        last_processed_idx = 0

        for idx, (pending_op, doc_copy) in enumerate(pending_ops, start=1):
            # Check if user quit in interactive mode
            if user_quit:
                break

            # Track which operation we're processing
            last_processed_idx = idx

            # Current path
            current_path = doc_copy.file_path
            source = repo_root / current_path

            # Suggested path
            suggested_dir = pending_op.suggested_directory_path
            suggested_filename = pending_op.suggested_filename
            if suggested_dir:
                target = repo_root / suggested_dir / suggested_filename
            else:
                target = repo_root / suggested_filename

            # Show progress
            percentage = int((idx / len(pending_ops)) * 100)
            click.echo()
            click.echo(f"[{idx}/{len(pending_ops)}] {percentage}%")

            # Check if it's a no-op (file already at target location)
            if source.resolve() == target.resolve():
                click.echo(f"  {current_path}")
                click.secho("  → (no change needed, already at target location)", fg="yellow")

                # In interactive mode, ask if user wants to remove this pending operation
                if interactive_mode:
                    click.echo(f"  Reason: {pending_op.reason}")
                    click.secho(f"  Confidence: {pending_op.confidence:.0%}", fg="green" if pending_op.confidence >= 0.8 else "yellow")
                    click.echo()

                    if click.confirm("Remove this pending operation?", default=True):
                        session.delete(pending_op)
                        click.secho("  ✓ Removed", fg="green")
                    else:
                        click.secho("  ○ Kept", fg="white")
                else:
                    # Non-interactive: always delete
                    if not dry_run:
                        session.delete(pending_op)

                skipped_count += 1
                continue

            # Display operation details
            click.echo(f"  Current:  {current_path}")
            click.echo(f"  Suggested: {target.relative_to(repo_root)}")

            # In interactive mode, show more details and prompt
            if interactive_mode:
                click.echo(f"  Reason: {pending_op.reason}")

                # Color-code confidence
                confidence = pending_op.confidence
                if confidence >= 0.8:
                    confidence_color = "green"
                elif confidence >= 0.6:
                    confidence_color = "yellow"
                else:
                    confidence_color = "red"
                click.secho(f"  Confidence: {confidence:.0%}", fg=confidence_color)
                click.echo()

                # Prompt user for action
                while True:
                    action = click.prompt(
                        "  [A]pply / [S]kip / [Q]uit / [H]elp",
                        type=str,
                        default="A",
                        show_default=True,
                    ).strip().upper()

                    if action in ["A", "APPLY"]:
                        break
                    elif action in ["S", "SKIP"]:
                        click.secho("  ○ Skipped by user", fg="yellow")
                        skipped_count += 1
                        break
                    elif action in ["Q", "QUIT"]:
                        click.echo()
                        click.secho("Quitting...", fg="yellow")
                        user_quit = True
                        break
                    elif action in ["H", "HELP"]:
                        click.echo()
                        click.echo("  Commands:")
                        click.echo("    [A]pply - Move this file to the suggested location")
                        click.echo("    [S]kip  - Skip this operation (keep pending)")
                        click.echo("    [Q]uit  - Stop processing and exit")
                        click.echo("    [H]elp  - Show this help message")
                        click.echo()
                        continue
                    else:
                        click.secho(f"  Invalid option '{action}'. Type 'H' for help.", fg="red")
                        continue

                # If user chose skip or quit, move to next operation
                if action in ["S", "SKIP"] or user_quit:
                    continue

            if dry_run:
                click.secho("  [DRY RUN] Would move file", fg="cyan")
                applied_count += 1
                continue

            # Perform the move
            try:
                move_file(source, target, conflict_resolution=conflict_resolution, create_dirs=True)
                click.secho("  ✓ Applied", fg="green")

                # Update the document copy's file path in the database
                doc_copy.file_path = str(target.relative_to(repo_root))

                # Delete the pending operation
                session.delete(pending_op)

                applied_count += 1
            except FileConflictError as e:
                click.secho(f"  ✗ Skipped: Target file already exists", fg="yellow")
                click.secho(f"    Use --force to overwrite", fg="yellow")
                failed_operations.append((current_path, str(e)))
                skipped_count += 1
            except DocmanFileNotFoundError as e:
                click.secho(f"  ✗ Failed: Source file not found", fg="red")
                failed_operations.append((current_path, str(e)))
                failed_count += 1
            except (FileOperationError, PermissionError) as e:
                click.secho(f"  ✗ Failed: {e}", fg="red")
                failed_operations.append((current_path, str(e)))
                failed_count += 1
            except Exception as e:
                click.secho(f"  ✗ Failed: Unexpected error: {e}", fg="red")
                failed_operations.append((current_path, str(e)))
                failed_count += 1

        # Commit changes to database
        if not dry_run:
            session.commit()

        # Display summary
        click.echo()
        click.echo("=" * 50)
        click.secho("Summary:", bold=True)
        if dry_run:
            click.secho(f"  Would apply: {applied_count}", fg="cyan")
            click.secho(f"  Would skip: {skipped_count}", fg="yellow")
        else:
            click.secho(f"  Applied: {applied_count}", fg="green")
            click.secho(f"  Skipped: {skipped_count}", fg="yellow")
            click.secho(f"  Failed: {failed_count}", fg="red" if failed_count > 0 else "white")

            if user_quit:
                remaining = len(pending_ops) - last_processed_idx
                if remaining > 0:
                    click.secho(f"  Not processed (quit early): {remaining}", fg="white")

        if failed_operations and not dry_run:
            click.echo()
            click.secho("Failed operations:", fg="red", bold=True)
            for file_path, error in failed_operations:
                click.echo(f"  {file_path}")
                click.echo(f"    {error}")

        click.echo("=" * 50)

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "--all",
    "-a",
    "reject_all",
    is_flag=True,
    default=False,
    help="Reject all pending operations",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts",
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursively reject operations in subdirectories",
)
def reject(path: str | None, reject_all: bool, yes: bool, recursive: bool) -> None:
    """
    Reject (delete) pending organization operations.

    Removes suggestions from the database without applying them. This is useful
    when you disagree with the LLM's suggestions or want to start fresh.

    Arguments:
        PATH: Optional path to reject operations for (default: requires --all flag).

    Options:
        --all, -a: Reject all pending operations in the repository
        -y, --yes: Skip confirmation prompts
        -r, --recursive: Recursively reject operations in subdirectories

    Examples:
        - 'docman reject --all': Reject all pending operations (with confirmation)
        - 'docman reject --all -y': Reject all without prompts
        - 'docman reject docs/': Reject operations for docs directory
        - 'docman reject docs/ -r': Reject operations in docs and subdirectories
        - 'docman reject file.pdf': Reject operation for specific file
    """
    # Validate flags
    if not reject_all and not path:
        click.secho(
            "Error: Must specify either --all or a PATH to reject operations.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman reject --all")
        click.echo("  docman reject docs/")
        click.echo("  docman reject file.pdf")
        raise click.Abort()

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
                click.secho(
                    "Error: Not in a docman repository. Use 'docman init' to create one.",
                    fg="red",
                    err=True,
                )
                raise click.Abort()
    else:
        # No path provided, use current directory
        try:
            repo_root = get_repository_root(start_path=Path.cwd())
        except RepositoryError:
            click.secho(
                "Error: Not in a docman repository. Use 'docman init' to create one.",
                fg="red",
                err=True,
            )
            raise click.Abort()

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query pending operations for this repository
        query = (
            session.query(PendingOperation, DocumentCopy)
            .join(DocumentCopy, PendingOperation.document_copy_id == DocumentCopy.id)
            .filter(DocumentCopy.repository_path == repository_path)
        )

        # Filter by path if provided
        if path:
            target_path = Path(path).resolve()

            # Check if path is a file or directory
            if target_path.is_file():
                # Single file - filter by exact match
                rel_path = str(target_path.relative_to(repo_root))
                query = query.filter(DocumentCopy.file_path == rel_path)
            elif target_path.is_dir():
                # Directory - filter by prefix
                rel_path = str(target_path.relative_to(repo_root))
                if recursive:
                    # Match files in this directory and all subdirectories (prefix match)
                    query = query.filter(DocumentCopy.file_path.startswith(rel_path))
                else:
                    # Match only files directly in this directory (not subdirectories)
                    # This is a bit complex - we need files that start with rel_path
                    # but don't have additional path separators after it
                    import os
                    sep = os.sep
                    # Files in the directory: rel_path/filename (no more separators after directory)
                    query = query.filter(
                        DocumentCopy.file_path.startswith(rel_path),
                        ~DocumentCopy.file_path.op('LIKE')(f"{rel_path}{sep}%{sep}%")
                    )
            else:
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

        pending_ops_to_delete = query.all()
        count = len(pending_ops_to_delete)

        if count == 0:
            click.echo("No pending operations found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Show what will be rejected
        click.echo()
        click.secho(f"Operations to reject: {count}", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
            if target_path.is_dir() and recursive:
                click.echo("Mode: Recursive")
            elif target_path.is_dir():
                click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        # Show the operations that will be deleted
        if count <= 10:
            # Show all if there are 10 or fewer
            for pending_op, doc_copy in pending_ops_to_delete:
                click.echo(f"  - {doc_copy.file_path}")
        else:
            # Show first 5 and last 3 if there are more than 10
            for pending_op, doc_copy in pending_ops_to_delete[:5]:
                click.echo(f"  - {doc_copy.file_path}")
            click.echo(f"  ... and {count - 8} more ...")
            for pending_op, doc_copy in pending_ops_to_delete[-3:]:
                click.echo(f"  - {doc_copy.file_path}")

        click.echo()

        # Confirm if not using -y flag
        if not yes:
            if not click.confirm(f"Reject (delete) {count} pending operation(s)?"):
                click.echo("Aborted.")
                return

        # Delete all pending operations
        for pending_op, doc_copy in pending_ops_to_delete:
            session.delete(pending_op)

        session.commit()

        click.secho(f"✓ Successfully rejected {count} pending operation(s).", fg="green")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.group()
def llm() -> None:
    """Manage LLM provider configurations."""
    pass


@llm.command(name="add")
@click.option("--name", type=str, help="Name for this provider configuration")
@click.option(
    "--provider",
    type=click.Choice(["google"], case_sensitive=False),
    help="Provider type (google, etc.)",
)
@click.option("--model", type=str, help="Model identifier (e.g., gemini-1.5-flash)")
@click.option("--api-key", type=str, help="API key (will be prompted if not provided)")
def llm_add(name: str | None, provider: str | None, model: str | None, api_key: str | None) -> None:
    """Add a new LLM provider configuration.

    If options are not provided, an interactive wizard will guide you through setup.
    """
    # If any option is missing, use the wizard
    if not all([name, provider, model, api_key]):
        if not run_llm_wizard():
            click.secho("Setup failed or cancelled.", fg="yellow")
            raise click.Abort()
        return

    # All options provided - add provider directly
    # At this point we know all values are not None due to the check above
    assert name is not None
    assert provider is not None
    assert model is not None
    assert api_key is not None

    try:
        provider_config = ProviderConfig(
            name=name,
            provider_type=provider,
            model=model,
            is_active=False,  # Will be set to True if it's the first provider
        )

        # Test connection
        click.echo("Testing connection...")
        llm_provider = get_llm_provider(provider_config, api_key)
        try:
            llm_provider.test_connection()
            click.secho("✓ Connection successful!", fg="green")
        except Exception as e:
            click.secho("✗ Connection test failed:", fg="red")
            click.secho(f"  {str(e)}", fg="red")
            raise click.Abort()

        # Add provider
        add_provider(provider_config, api_key)
        click.secho(f"✓ Provider '{name}' added successfully!", fg="green")

        # Check if it was set as active
        if provider_config.is_active:
            click.secho(f"Provider '{name}' is now active.", fg="green")

    except ValueError as e:
        click.secho(f"Error: {e}", fg="red")
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error: Failed to add provider: {e}", fg="red")
        raise click.Abort()


@llm.command(name="list")
def llm_list() -> None:
    """List all configured LLM providers."""
    providers = get_providers()

    if not providers:
        click.echo("No LLM providers configured.")
        click.echo()
        click.echo("Run 'docman llm add' to add a provider.")
        return

    click.echo()
    click.secho("Configured LLM Providers:", bold=True)
    click.echo()

    for provider in providers:
        active_marker = "● " if provider.is_active else "○ "
        color = "green" if provider.is_active else "white"

        click.secho(f"{active_marker}{provider.name}", fg=color, bold=provider.is_active)
        click.echo(f"  Type: {provider.provider_type}")
        click.echo(f"  Model: {provider.model}")
        if provider.endpoint:
            click.echo(f"  Endpoint: {provider.endpoint}")
        click.echo()


@llm.command(name="remove")
@click.argument("name")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
def llm_remove(name: str, yes: bool) -> None:
    """Remove an LLM provider configuration.

    Arguments:
        NAME: The name of the provider to remove.
    """
    # Check if provider exists
    provider = get_provider(name)
    if not provider:
        click.secho(f"Error: Provider '{name}' not found.", fg="red")
        raise click.Abort()

    # Confirm deletion
    if not yes:
        click.echo("Provider to remove:")
        click.echo(f"  Name: {provider.name}")
        click.echo(f"  Type: {provider.provider_type}")
        click.echo(f"  Model: {provider.model}")
        click.echo()

        if not click.confirm(f"Are you sure you want to remove '{name}'?"):
            click.echo("Aborted.")
            return

    # Remove provider
    if remove_provider(name):
        click.secho(f"✓ Provider '{name}' removed successfully.", fg="green")

        # Check if there's a new active provider
        active = get_active_provider()
        if active:
            click.echo(f"Active provider is now: {active.name}")
    else:
        click.secho(f"Error: Failed to remove provider '{name}'.", fg="red")
        raise click.Abort()


@llm.command(name="set-active")
@click.argument("name")
def llm_set_active(name: str) -> None:
    """Set a provider as the active one.

    Arguments:
        NAME: The name of the provider to activate.
    """
    if set_active_provider(name):
        click.secho(f"✓ Provider '{name}' is now active.", fg="green")
    else:
        click.secho(f"Error: Provider '{name}' not found.", fg="red")
        raise click.Abort()


@llm.command(name="show")
@click.argument("name", required=False)
def llm_show(name: str | None) -> None:
    """Show details of an LLM provider.

    Arguments:
        NAME: The name of the provider to show (defaults to active provider).
    """
    if name:
        provider = get_provider(name)
        if not provider:
            click.secho(f"Error: Provider '{name}' not found.", fg="red")
            raise click.Abort()
    else:
        provider = get_active_provider()
        if not provider:
            click.echo("No active provider configured.")
            click.echo()
            click.echo("Run 'docman llm add' to add a provider.")
            return

    click.echo()
    click.secho(f"Provider: {provider.name}", bold=True)
    if provider.is_active:
        click.secho("  (Active)", fg="green")
    click.echo()
    click.echo(f"Type: {provider.provider_type}")
    click.echo(f"Model: {provider.model}")
    if provider.endpoint:
        click.echo(f"Endpoint: {provider.endpoint}")
    click.echo()

    # Show API key status (but not the actual key)
    api_key = get_api_key(provider.name)
    if api_key:
        click.secho("API Key: Configured ✓", fg="green")
    else:
        click.secho("API Key: Not found ✗", fg="red")
    click.echo()


@llm.command(name="test")
@click.argument("name", required=False)
def llm_test(name: str | None) -> None:
    """Test connection to an LLM provider.

    Arguments:
        NAME: The name of the provider to test (defaults to active provider).
    """
    if name:
        provider = get_provider(name)
        if not provider:
            click.secho(f"Error: Provider '{name}' not found.", fg="red")
            raise click.Abort()
    else:
        provider = get_active_provider()
        if not provider:
            click.echo("No active provider configured.")
            click.echo()
            click.echo("Run 'docman llm add' to add a provider.")
            return

    click.echo(f"Testing connection to '{provider.name}'...")

    # Get API key
    api_key = get_api_key(provider.name)
    if not api_key:
        click.secho("Error: API key not found for this provider.", fg="red")
        raise click.Abort()

    # Test connection
    try:
        llm_provider = get_llm_provider(provider, api_key)
        llm_provider.test_connection()
        click.secho("✓ Connection successful!", fg="green")
    except Exception as e:
        click.secho("✗ Connection failed:", fg="red")
        click.secho(f"  {str(e)}", fg="red")
        raise click.Abort()


@main.group()
def config() -> None:
    """Manage repository configuration."""
    pass


@config.command(name="set-instructions")
@click.option("--text", type=str, help="Set instructions directly from command line")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def config_set_instructions(text: str | None, path: str) -> None:
    """Set document organization instructions for a repository.

    Opens the instructions file in your default editor ($EDITOR) if --text is not provided.
    Use this to define how documents should be organized in your repository.

    Examples:
        docman config set-instructions
        docman config set-instructions --text "Organize by date and category"
        docman config set-instructions --path /path/to/repo
    """
    # Find repository root
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    if text is not None:
        # Set instructions directly from command line
        try:
            save_instructions(repo_root, text)
            click.secho("✓ Instructions saved successfully!", fg="green")
        except Exception as e:
            click.secho(f"Error: Failed to save instructions: {e}", fg="red")
            raise click.Abort()
    else:
        # Open editor
        click.echo("Opening instructions file in editor...")
        if edit_instructions_interactive(repo_root):
            click.secho("✓ Instructions updated!", fg="green")
        else:
            click.secho("Error: Could not open editor. Set $EDITOR environment variable or use --text.", fg="red")
            raise click.Abort()


@config.command(name="show-instructions")
@click.option("--path", type=str, default=".", help="Repository path (default: current directory)")
def config_show_instructions(path: str) -> None:
    """Show document organization instructions for a repository.

    Displays the current document organization instructions for the repository.

    Examples:
        docman config show-instructions
        docman config show-instructions --path /path/to/repo
    """
    # Find repository root
    try:
        repo_root = get_repository_root(start_path=Path(path).resolve())
    except RepositoryError:
        raise click.Abort()

    # Load instructions
    instructions = load_instructions(repo_root)

    if instructions:
        click.echo()
        click.secho("Document Organization Instructions:", bold=True)
        click.echo()
        click.echo(instructions)
        click.echo()
    else:
        click.echo("No document organization instructions found for this repository.")
        click.echo()
        click.echo("Run 'docman config set-instructions' to create them.")


if __name__ == "__main__":
    main()
