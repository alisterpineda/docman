"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

from datetime import datetime
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
from docman.models import Document, DocumentCopy, Operation, OperationStatus, OrganizationStatus, compute_content_hash, get_utc_now, file_needs_rehashing
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
    3. Deleting copies for missing files (cascades to Operation)
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


def find_duplicate_groups(session, repo_root: Path) -> dict[int, list[DocumentCopy]]:
    """Find all documents that have multiple copies in the repository.

    Groups DocumentCopy records by their document_id to identify duplicates.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping document_id to list of DocumentCopy records.
        Only includes documents with 2 or more copies (duplicates).
    """
    from sqlalchemy import func

    repository_path = str(repo_root)

    # Query to find documents with multiple copies
    # First, get document_ids that have count > 1
    duplicate_doc_ids = (
        session.query(DocumentCopy.document_id)
        .filter(DocumentCopy.repository_path == repository_path)
        .group_by(DocumentCopy.document_id)
        .having(func.count(DocumentCopy.id) > 1)
        .all()
    )

    # Extract just the IDs
    doc_ids = [doc_id for (doc_id,) in duplicate_doc_ids]

    if not doc_ids:
        return {}

    # Now get all copies for these documents, ordered by ID for predictable behavior
    copies = (
        session.query(DocumentCopy)
        .filter(
            DocumentCopy.document_id.in_(doc_ids),
            DocumentCopy.repository_path == repository_path,
        )
        .order_by(DocumentCopy.id)
        .all()
    )

    # Group by document_id
    groups: dict[int, list[DocumentCopy]] = {}
    for copy in copies:
        if copy.document_id not in groups:
            groups[copy.document_id] = []
        groups[copy.document_id].append(copy)

    return groups


def detect_target_conflicts(
    session, repo_root: Path
) -> dict[str, list[tuple[Operation, DocumentCopy]]]:
    """Detect pending operations that would create filename conflicts.

    Identifies cases where multiple files would be moved to the same target location.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping target path to list of (Operation, DocumentCopy) tuples.
        Only includes target paths with multiple operations (conflicts).
    """
    repository_path = str(repo_root)

    # Query all pending operations with their copies
    ops = (
        session.query(Operation, DocumentCopy)
        .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
        .filter(DocumentCopy.repository_path == repository_path)
        .filter(Operation.status == OperationStatus.PENDING)
        .all()
    )

    # Group by target path
    target_paths: dict[str, list[tuple[Operation, DocumentCopy]]] = {}
    for op, copy in ops:
        # Build target path
        if op.suggested_directory_path:
            target = f"{op.suggested_directory_path}/{op.suggested_filename}"
        else:
            target = op.suggested_filename

        if target not in target_paths:
            target_paths[target] = []
        target_paths[target].append((op, copy))

    # Return only paths with conflicts (multiple files to same location)
    conflicts = {path: ops for path, ops in target_paths.items() if len(ops) > 1}

    return conflicts


def detect_conflicts_in_operations(
    pending_ops: list[tuple[Operation, DocumentCopy]], repo_root: Path
) -> dict[str, list[tuple[Operation, DocumentCopy]]]:
    """Detect conflicts within a specific list of pending operations.

    Identifies cases where multiple operations would move files to the same target location.

    Args:
        pending_ops: List of (Operation, DocumentCopy) tuples to check.
        repo_root: Path to the repository root directory.

    Returns:
        Dictionary mapping target path to list of (Operation, DocumentCopy) tuples.
        Only includes target paths with multiple operations (conflicts).
    """
    # Group by target path
    target_paths: dict[str, list[tuple[Operation, DocumentCopy]]] = {}
    for op, copy in pending_ops:
        # Build target path
        if op.suggested_directory_path:
            target = f"{op.suggested_directory_path}/{op.suggested_filename}"
        else:
            target = op.suggested_filename

        if target not in target_paths:
            target_paths[target] = []
        target_paths[target].append((op, copy))

    # Return only paths with conflicts (multiple files to same location)
    conflicts = {path: ops for path, ops in target_paths.items() if len(ops) > 1}

    return conflicts


def get_duplicate_summary(session, repo_root: Path) -> tuple[int, int]:
    """Get summary statistics about duplicate documents in the repository.

    Args:
        session: SQLAlchemy database session.
        repo_root: Path to the repository root directory.

    Returns:
        Tuple of (unique_duplicated_docs, total_duplicate_copies).
        - unique_duplicated_docs: Number of distinct documents that have duplicates
        - total_duplicate_copies: Total number of duplicate file copies
    """
    duplicate_groups = find_duplicate_groups(session, repo_root)

    unique_duplicated_docs = len(duplicate_groups)
    total_duplicate_copies = sum(len(copies) for copies in duplicate_groups.values())

    return unique_duplicated_docs, total_duplicate_copies


@main.command()
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
def plan(path: str | None, recursive: bool, reprocess: bool) -> None:
    """
    Process documents in the repository.

    Discovers document files and extracts their content using docling,
    storing them in the database.

    Arguments:
        PATH: Optional path to a file or directory (default: current directory).
              Relative to current working directory.

    Options:
        -r, --recursive: Recursively process subdirectories when PATH is a directory.
        --reprocess: Reprocess all files, including those already organized or ignored.

    Examples:
        - 'docman plan': Process entire repository recursively (backward compatible)
        - 'docman plan .': Process current directory only (non-recursive)
        - 'docman plan docs/': Process docs directory only (non-recursive)
        - 'docman plan docs/ -r': Process docs directory recursively
        - 'docman plan file.pdf': Process single file
        - 'docman plan -r': Process entire repository recursively (same as no args)
        - 'docman plan --reprocess': Reprocess all files, including organized ones
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
        skipped_count = 0  # Files skipped due to LLM or content extraction errors
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
                        session.query(Operation).filter(
                            Operation.document_copy_id == copy.id
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

            # Step 2: Check organization status and skip if already organized/ignored
            # (unless --reprocess flag is set)
            if not reprocess and copy.organization_status in (OrganizationStatus.ORGANIZED, OrganizationStatus.IGNORED):
                status_label = "organized" if copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  Skipping (already {status_label})")
                continue

            # Step 3: Create or update pending operation based on prompt hash
            existing_pending_op = (
                session.query(Operation)
                .filter(Operation.document_copy_id == copy.id)
                .filter(Operation.status == OperationStatus.PENDING)
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
                # Reset organization status since conditions changed
                if copy.organization_status == OrganizationStatus.ORGANIZED:
                    copy.organization_status = OrganizationStatus.UNORGANIZED
            elif document and existing_pending_op.document_content_hash != document.content_hash:
                # Document content has changed, need to regenerate
                needs_generation = True
                invalidation_reason = "Document content changed"
                # Reset organization status since content changed
                if copy.organization_status == OrganizationStatus.ORGANIZED:
                    copy.organization_status = OrganizationStatus.UNORGANIZED
            elif model_name and existing_pending_op.model_name != model_name:
                # Model changed (redundant with prompt hash, but explicit)
                needs_generation = True
                invalidation_reason = "Model changed"
                # Reset organization status since model changed
                if copy.organization_status == OrganizationStatus.ORGANIZED:
                    copy.organization_status = OrganizationStatus.UNORGANIZED

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
                            pending_op = Operation(
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
                        # Skip file if LLM fails
                        click.echo(f"  Warning: LLM suggestion failed ({str(e)}), skipping file")
                        # Delete existing pending operation if it exists (now invalid)
                        if existing_pending_op:
                            session.delete(existing_pending_op)
                        skipped_count += 1
                        continue
                else:
                    # No content available (extraction failed) or LLM not configured
                    # Don't create pending operation, but file is already counted in failed_count if extraction failed
                    if existing_pending_op:
                        # Delete stale pending operation
                        session.delete(existing_pending_op)
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
        click.echo(f"  Skipped (LLM or content errors): {skipped_count}")
        click.echo(f"  Pending operations created: {pending_ops_created}")
        click.echo(f"  Pending operations updated: {pending_ops_updated}")
        click.echo(f"  Total files: {len(document_files)}")
        click.echo("=" * 50)

        # Check for duplicates and show warning
        unique_dup_docs, total_dup_copies = get_duplicate_summary(session, repo_root)
        if unique_dup_docs > 0:
            click.echo()
            click.secho(
                f"⚠️  Found {unique_dup_docs} duplicate document(s) "
                f"with {total_dup_copies} total copies",
                fg="yellow",
            )
            click.echo()
            click.echo("💡 Tip: Run 'docman dedupe' to resolve duplicate files")
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
            session.query(Operation, DocumentCopy)
            .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
            .filter(DocumentCopy.repository_path == repository_path)
            .filter(Operation.status == OperationStatus.PENDING)
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

        # Detect duplicates and conflicts
        duplicate_groups = find_duplicate_groups(session, repo_root)
        target_conflicts = detect_target_conflicts(session, repo_root)

        # Build a lookup for document_copy_id to document_id
        copy_to_doc_id = {copy.id: copy.document_id for _, copy in pending_ops}

        # Separate operations into duplicates and non-duplicates
        duplicate_ops = []
        non_duplicate_ops = []

        for pending_op, doc_copy in pending_ops:
            if doc_copy.document_id in duplicate_groups:
                duplicate_ops.append((pending_op, doc_copy))
            else:
                non_duplicate_ops.append((pending_op, doc_copy))

        # Display header
        click.echo()
        click.secho(f"Pending Operations ({len(pending_ops)}):", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
        click.echo()

        # Initialize counter for all operations
        group_idx = 1

        # Display duplicate groups first
        if duplicate_ops:
            # Group duplicate operations by document_id
            dup_groups_display: dict[int, list[tuple[Operation, DocumentCopy]]] = {}
            for pending_op, doc_copy in duplicate_ops:
                if doc_copy.document_id not in dup_groups_display:
                    dup_groups_display[doc_copy.document_id] = []
                dup_groups_display[doc_copy.document_id].append((pending_op, doc_copy))

            # Display each duplicate group
            for document_id, group_ops in dup_groups_display.items():
                # Get content hash for display
                first_copy = group_ops[0][1]
                doc = session.query(Document).filter(Document.id == document_id).first()
                content_hash_display = doc.content_hash[:8] if doc else "unknown"

                # Display group header
                click.secho(
                    f"[⚠️  DUPLICATE GROUP - {len(group_ops)} copies, hash: {content_hash_display}...]",
                    fg="yellow",
                    bold=True,
                )
                click.echo()

                # Display each operation in the group
                for sub_idx, (pending_op, doc_copy) in enumerate(group_ops, start=1):
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

                    # Check for conflict with this target
                    conflict_warning = ""
                    if suggested_path in target_conflicts:
                        # Find which other operations conflict
                        conflicting_ops = target_conflicts[suggested_path]
                        if len(conflicting_ops) > 1:
                            # Build list of conflicting indices
                            conflict_refs = []
                            for conf_op, conf_copy in conflicting_ops:
                                if conf_copy.id != doc_copy.id:
                                    # Find the index/sub-index of the conflicting operation
                                    # For simplicity, just mark as conflict
                                    conflict_refs.append("another file")
                            if conflict_refs:
                                conflict_warning = f" ⚠️ CONFLICT: Same target as {conflict_refs[0]}"

                    # Check if it's a move or just a rename
                    operation_type = ""
                    op_color = "cyan"
                    if current_path == suggested_path:
                        operation_type = "(no change)"
                        op_color = "white"

                    # Display operation with sub-numbering
                    click.echo(f"  [{group_idx}{chr(96 + sub_idx)}] {current_path}")

                    # Show organization status
                    status_label = doc_copy.organization_status.value
                    status_color = "white"
                    if doc_copy.organization_status == OrganizationStatus.ORGANIZED:
                        status_color = "green"
                    elif doc_copy.organization_status == OrganizationStatus.IGNORED:
                        status_color = "yellow"
                    click.secho(f"    Status: {status_label}", fg=status_color)

                    click.secho(
                        f"    → {suggested_path} {operation_type}{conflict_warning}",
                        fg=op_color,
                    )
                    click.secho(f"    Confidence: {confidence:.0%}", fg=confidence_color)
                    click.echo(f"    Reason: {pending_op.reason}")
                    click.echo()

                group_idx += 1

        # Display non-duplicate operations
        for idx, (pending_op, doc_copy) in enumerate(non_duplicate_ops, start=group_idx):
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

            # Check for conflict
            conflict_warning = ""
            if suggested_path in target_conflicts and len(target_conflicts[suggested_path]) > 1:
                conflict_warning = " ⚠️ CONFLICT"

            # Check if it's a move or just a rename
            if current_path == suggested_path:
                operation_type = "(no change)"
                op_color = "white"
            else:
                operation_type = ""
                op_color = "cyan"

            # Display operation
            click.echo(f"[{idx}] {current_path}")

            # Show organization status
            status_label = doc_copy.organization_status.value
            status_color = "white"
            if doc_copy.organization_status == OrganizationStatus.ORGANIZED:
                status_color = "green"
            elif doc_copy.organization_status == OrganizationStatus.IGNORED:
                status_color = "yellow"
            click.secho(f"  Status: {status_label}", fg=status_color)

            click.secho(f"  → {suggested_path} {operation_type}{conflict_warning}", fg=op_color)
            click.secho(f"  Confidence: {confidence:.0%}", fg=confidence_color)
            click.echo(f"  Reason: {pending_op.reason}")
            click.echo()

        # Display summary
        click.echo("=" * 50)
        click.echo(f"Total pending operations: {len(pending_ops)}")

        # Add duplicate and conflict stats
        if duplicate_groups:
            total_dup_copies = sum(len(copies) for copies in duplicate_groups.values())
            click.secho(
                f"Duplicate groups: {len(duplicate_groups)} ({total_dup_copies} total copies)",
                fg="yellow",
            )

        if target_conflicts:
            total_conflicts = sum(len(ops) for ops in target_conflicts.values())
            click.secho(
                f"Files with conflicting targets: {total_conflicts}",
                fg="yellow",
            )

        click.echo()

        if duplicate_groups:
            click.echo("💡 Tip: Run 'docman dedupe' to resolve duplicates")
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


# Helper functions for review command (shared with apply/reject)
def _resolve_repository_root(path: str | None) -> Path:
    """
    Find and return the repository root path.

    Args:
        path: Optional path to search from (file or directory)

    Returns:
        Path object representing the repository root

    Raises:
        click.Abort: If repository cannot be found
    """
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

    return repo_root


def _validate_review_flags(
    path: str | None,
    apply_all: bool,
    reject_all: bool,
    dry_run: bool,
    force: bool,
    recursive: bool
) -> None:
    """
    Validate that review command flags are properly specified.

    Args:
        path: Optional path argument
        apply_all: Whether --apply-all flag is set
        reject_all: Whether --reject-all flag is set
        dry_run: Whether --dry-run flag is set
        force: Whether --force flag is set
        recursive: Whether --recursive flag is set

    Raises:
        click.Abort: If validation fails
    """
    # Check for mutually exclusive bulk actions
    if apply_all and reject_all:
        click.secho(
            "Error: Cannot use both --apply-all and --reject-all",
            fg="red",
            err=True,
        )
        raise click.Abort()

    # Check that --dry-run is only used with bulk modes
    if dry_run and not (apply_all or reject_all):
        click.secho(
            "Error: --dry-run can only be used with --apply-all or --reject-all",
            fg="red",
            err=True,
        )
        raise click.Abort()

    # Check that --force is only used with --apply-all
    if force and not apply_all:
        click.secho(
            "Warning: --force is ignored (only applies with --apply-all)",
            fg="yellow",
        )

    # Check that --recursive is only used with --reject-all
    if recursive and not reject_all:
        click.secho(
            "Warning: -r/--recursive is ignored (only applies with --reject-all)",
            fg="yellow",
        )


def _query_pending_operations(
    session,
    repo_root: Path,
    path: str | None,
    recursive: bool = True
) -> list:
    """
    Query pending operations with optional path filtering.

    Args:
        session: Database session
        repo_root: Repository root path
        path: Optional path to filter by (file or directory)
        recursive: Whether to recursively process directories (default True for apply, False for reject)

    Returns:
        List of (Operation, DocumentCopy) tuples

    Raises:
        click.Abort: If path doesn't exist
    """
    repository_path = str(repo_root)

    # Query pending operations for this repository
    query = (
        session.query(Operation, DocumentCopy)
        .join(DocumentCopy, Operation.document_copy_id == DocumentCopy.id)
        .filter(DocumentCopy.repository_path == repository_path)
        .filter(Operation.status == OperationStatus.PENDING)
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

    return query.all()


def _handle_interactive_review(
    session,
    repo_root: Path,
    path: str | None
) -> None:
    """
    Handle interactive review mode - review each operation individually.

    User can choose to apply, reject, or skip each operation.

    Args:
        session: Database session
        repo_root: Repository root path
        path: Optional path filter
    """
    # Query pending operations (always recursive in interactive mode)
    pending_ops = _query_pending_operations(session, repo_root, path, recursive=True)

    if not pending_ops:
        click.echo("No pending operations found.")
        if path:
            click.echo(f"  (filtered by: {path})")
        return

    # Detect conflicts before applying
    conflicts = detect_conflicts_in_operations(pending_ops, repo_root)
    if conflicts:
        click.secho(f"\n⚠️  Warning: {len(conflicts)} target conflict(s) detected", fg="yellow")
        click.echo("Multiple files will attempt to move to the same location:")
        for target, ops in conflicts.items():
            click.echo(f"\n  Target: {target}")
            for op, copy in ops:
                click.echo(f"    - {copy.file_path}")
        click.echo()

        if not click.confirm("Continue anyway?"):
            raise click.Abort()

    # Show summary
    click.echo()
    click.secho(f"Operations to review: {len(pending_ops)}", bold=True)
    click.echo(f"Repository: {str(repo_root)}")
    if path:
        click.echo(f"Filter: {path}")
    click.echo()

    # Process each operation interactively
    applied_count = 0
    rejected_count = 0
    skipped_count = 0
    failed_count = 0
    failed_operations = []
    user_quit = False
    last_processed_idx = 0

    for idx, (pending_op, doc_copy) in enumerate(pending_ops, start=1):
        # Check if user quit
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
            click.echo(f"  Reason: {pending_op.reason}")
            click.secho(f"  Confidence: {pending_op.confidence:.0%}", fg="green" if pending_op.confidence >= 0.8 else "yellow")
            click.echo()

            if click.confirm("Remove this pending operation?", default=True):
                # Mark as organized and accept operation since it's already at the target location
                pending_op.status = OperationStatus.ACCEPTED
                doc_copy.accepted_operation_id = pending_op.id
                doc_copy.organization_status = OrganizationStatus.ORGANIZED
                click.secho("  ✓ Removed", fg="green")
            else:
                click.secho("  ○ Kept", fg="white")

            skipped_count += 1
            continue

        # Display operation details
        click.echo(f"  Current:  {current_path}")
        click.echo(f"  Suggested: {target.relative_to(repo_root)}")
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
                "  [A]pply / [R]eject / [S]kip / [Q]uit / [H]elp",
                type=str,
                default="A" if confidence >= 0.85 else "S",
                show_default=True,
            ).strip().upper()

            if action in ["A", "APPLY"]:
                # Apply: move file and mark as ACCEPTED
                try:
                    move_file(source, target, conflict_resolution=ConflictResolution.SKIP, create_dirs=True)
                    click.secho("  ✓ Applied", fg="green")

                    # Update the document copy's file path in the database
                    doc_copy.file_path = str(target.relative_to(repo_root))

                    # Mark the file as organized and accept the operation
                    pending_op.status = OperationStatus.ACCEPTED
                    doc_copy.accepted_operation_id = pending_op.id
                    doc_copy.organization_status = OrganizationStatus.ORGANIZED

                    applied_count += 1
                except FileConflictError as e:
                    # Check if this file is part of a duplicate group
                    source_doc_id = doc_copy.document_id
                    duplicate_groups = find_duplicate_groups(session, repo_root)

                    if source_doc_id in duplicate_groups and len(duplicate_groups[source_doc_id]) > 1:
                        # This is a duplicate - offer more contextual options
                        click.secho(f"  ⚠️  CONFLICT: Target already exists", fg="yellow")
                        click.echo(f"    Current: {e.source}")
                        click.echo(f"    Target:  {e.target}")
                        click.echo()
                        click.echo("These files have identical content (duplicates detected)")
                        click.echo()
                        click.echo("Choose action:")
                        click.echo("  [D]elete this copy (recommended)")
                        click.echo("  [R]ename → {}_1{}".format(target.stem, target.suffix))
                        click.echo("  [O]verwrite existing file")
                        click.echo("  [S]kip")
                        click.echo()

                        choice = click.prompt(
                            "Your choice",
                            type=click.Choice(['D', 'R', 'O', 'S'], case_sensitive=False),
                            default='D'
                        )

                        if choice.upper() == 'D':
                            # Delete source copy from database
                            session.delete(doc_copy)
                            # Delete file from disk
                            if source.exists():
                                source.unlink()
                            click.secho("  ✓ Deleted duplicate copy", fg="green")
                            applied_count += 1
                        elif choice.upper() == 'R':
                            # Use RENAME conflict resolution
                            new_target = move_file(source, target, conflict_resolution=ConflictResolution.RENAME, create_dirs=True)
                            doc_copy.file_path = str(new_target.relative_to(repo_root))
                            pending_op.status = OperationStatus.ACCEPTED
                            doc_copy.accepted_operation_id = pending_op.id
                            doc_copy.organization_status = OrganizationStatus.ORGANIZED
                            click.secho(f"  ✓ Renamed to {new_target.name}", fg="green")
                            applied_count += 1
                        elif choice.upper() == 'O':
                            # Use OVERWRITE conflict resolution
                            move_file(source, target, conflict_resolution=ConflictResolution.OVERWRITE, create_dirs=True)
                            doc_copy.file_path = str(target.relative_to(repo_root))
                            pending_op.status = OperationStatus.ACCEPTED
                            doc_copy.accepted_operation_id = pending_op.id
                            doc_copy.organization_status = OrganizationStatus.ORGANIZED
                            click.secho("  ✓ Overwritten", fg="green")
                            applied_count += 1
                        else:
                            # Skip
                            click.echo("  ○ Skipped")
                            skipped_count += 1
                    else:
                        # Not a duplicate - show original error message
                        click.secho("  ✗ Skipped: Target file already exists", fg="yellow")
                        failed_operations.append((current_path, str(e)))
                        skipped_count += 1
                except DocmanFileNotFoundError as e:
                    click.secho("  ✗ Failed: Source file not found", fg="red")
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
                break

            elif action in ["R", "REJECT"]:
                # Reject: mark operation as REJECTED
                pending_op.status = OperationStatus.REJECTED
                click.secho("  ✗ Rejected", fg="red")
                rejected_count += 1
                break

            elif action in ["S", "SKIP"]:
                # Skip: leave as pending
                click.secho("  ○ Skipped by user", fg="yellow")
                skipped_count += 1
                break

            elif action in ["Q", "QUIT"]:
                # Quit: stop processing
                click.echo()
                click.secho("Quitting...", fg="yellow")
                user_quit = True
                break

            elif action in ["H", "HELP"]:
                # Show help
                click.echo()
                click.echo("  Commands:")
                click.echo("    [A]pply  - Move this file to the suggested location")
                click.echo("    [R]eject - Reject this suggestion (marks as rejected, won't show again)")
                click.echo("    [S]kip   - Skip this operation (keeps as pending for later review)")
                click.echo("    [Q]uit   - Stop processing and exit")
                click.echo("    [H]elp   - Show this help message")
                click.echo()
                continue

            else:
                click.secho(f"  Invalid option '{action}'. Type 'H' for help.", fg="red")
                continue

    # Commit changes to database
    session.commit()

    # Display summary
    click.echo()
    click.echo("=" * 50)
    click.secho("Summary:", bold=True)
    click.secho(f"  Applied: {applied_count}", fg="green")
    click.secho(f"  Rejected: {rejected_count}", fg="red")
    click.secho(f"  Skipped: {skipped_count}", fg="yellow")
    click.secho(f"  Failed: {failed_count}", fg="red" if failed_count > 0 else "white")

    if user_quit:
        remaining = len(pending_ops) - last_processed_idx
        if remaining > 0:
            click.secho(f"  Not processed (quit early): {remaining}", fg="white")

    if failed_operations:
        click.echo()
        click.secho("Failed operations:", fg="red", bold=True)
        for file_path, error in failed_operations:
            click.echo(f"  {file_path}")
            click.echo(f"    {error}")

    click.echo("=" * 50)


def _handle_bulk_apply(
    session,
    repo_root: Path,
    path: str | None,
    yes: bool,
    force: bool,
    dry_run: bool
) -> None:
    """
    Handle bulk apply mode - apply all operations without individual prompts.

    Args:
        session: Database session
        repo_root: Repository root path
        path: Optional path filter
        yes: Skip confirmation prompts
        force: Overwrite existing files
        dry_run: Preview without making changes
    """
    # Query pending operations
    pending_ops = _query_pending_operations(session, repo_root, path, recursive=True)

    if not pending_ops:
        click.echo("No pending operations found.")
        if path:
            click.echo(f"  (filtered by: {path})")
        return

    # Detect conflicts before applying
    conflicts = detect_conflicts_in_operations(pending_ops, repo_root)
    if conflicts:
        click.secho(f"\n⚠️  Warning: {len(conflicts)} target conflict(s) detected", fg="yellow")
        click.echo("Multiple files will attempt to move to the same location:")
        for target, ops in conflicts.items():
            click.echo(f"\n  Target: {target}")
            for op, copy in ops:
                click.echo(f"    - {copy.file_path}")
        click.echo()

    # Show what will be applied
    click.echo()
    if dry_run:
        click.secho("DRY RUN - No changes will be made", fg="yellow", bold=True)
        click.echo()

    click.secho(f"Operations to apply: {len(pending_ops)}", bold=True)
    click.echo(f"Repository: {str(repo_root)}")
    if path:
        click.echo(f"Filter: {path}")
    click.echo()

    # Confirm if not using -y flag and not in dry-run
    if not yes and not dry_run:
        if not click.confirm(f"Apply {len(pending_ops)} operation(s)?"):
            click.echo("Aborted.")
            return

    # Determine conflict resolution strategy
    conflict_resolution = ConflictResolution.OVERWRITE if force else ConflictResolution.SKIP

    # Apply each operation
    applied_count = 0
    skipped_count = 0
    failed_count = 0
    failed_operations = []

    for idx, (pending_op, doc_copy) in enumerate(pending_ops, start=1):
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

            # Non-interactive: always accept and mark as organized
            if not dry_run:
                pending_op.status = OperationStatus.ACCEPTED
                doc_copy.accepted_operation_id = pending_op.id
                doc_copy.organization_status = OrganizationStatus.ORGANIZED

            skipped_count += 1
            continue

        # Display operation details
        click.echo(f"  Current:  {current_path}")
        click.echo(f"  Suggested: {target.relative_to(repo_root)}")

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

            # Mark the file as organized and accept the operation
            pending_op.status = OperationStatus.ACCEPTED
            doc_copy.accepted_operation_id = pending_op.id
            doc_copy.organization_status = OrganizationStatus.ORGANIZED

            applied_count += 1
        except FileConflictError as e:
            click.secho("  ✗ Skipped: Target file already exists", fg="yellow")
            click.secho("    Use --force to overwrite", fg="yellow")
            failed_operations.append((current_path, str(e)))
            skipped_count += 1
        except DocmanFileNotFoundError as e:
            click.secho("  ✗ Failed: Source file not found", fg="red")
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

    if failed_operations and not dry_run:
        click.echo()
        click.secho("Failed operations:", fg="red", bold=True)
        for file_path, error in failed_operations:
            click.echo(f"  {file_path}")
            click.echo(f"    {error}")

    click.echo("=" * 50)


def _handle_bulk_reject(
    session,
    repo_root: Path,
    path: str | None,
    yes: bool,
    recursive: bool,
    dry_run: bool
) -> None:
    """
    Handle bulk reject mode - reject all operations without individual prompts.

    Args:
        session: Database session
        repo_root: Repository root path
        path: Optional path filter
        yes: Skip confirmation prompts
        recursive: Whether to recursively process directories (False by default for safety)
        dry_run: Preview without making changes
    """
    # Query pending operations - reject defaults to non-recursive for safety
    pending_ops = _query_pending_operations(session, repo_root, path, recursive=recursive)

    if not pending_ops:
        click.echo("No pending operations found.")
        if path:
            click.echo(f"  (filtered by: {path})")
        return

    count = len(pending_ops)

    # Show what will be rejected
    click.echo()
    if dry_run:
        click.secho("DRY RUN - No changes will be made", fg="yellow", bold=True)
        click.echo()

    click.secho(f"Operations to reject: {count}", bold=True)
    click.echo(f"Repository: {str(repo_root)}")
    if path:
        click.echo(f"Filter: {path}")
        target_path = Path(path).resolve()
        if target_path.is_dir() and recursive:
            click.echo("Mode: Recursive")
        elif target_path.is_dir():
            click.echo("Mode: Non-recursive (current directory only)")
    click.echo()

    # Show the operations that will be deleted
    if count <= 10:
        # Show all if there are 10 or fewer
        for pending_op, doc_copy in pending_ops:
            click.echo(f"  - {doc_copy.file_path}")
    else:
        # Show first 5 and last 3 if there are more than 10
        for pending_op, doc_copy in pending_ops[:5]:
            click.echo(f"  - {doc_copy.file_path}")
        click.echo(f"  ... and {count - 8} more ...")
        for pending_op, doc_copy in pending_ops[-3:]:
            click.echo(f"  - {doc_copy.file_path}")

    click.echo()

    # Confirm if not using -y flag
    if not yes and not dry_run:
        if not click.confirm(f"Reject (delete) {count} pending operation(s)?"):
            click.echo("Aborted.")
            return

    if dry_run:
        click.secho(f"[DRY RUN] Would reject {count} operation(s)", fg="cyan")
        return

    # Mark all pending operations as rejected
    for pending_op, doc_copy in pending_ops:
        pending_op.status = OperationStatus.REJECTED

    session.commit()

    click.secho(f"✓ Successfully rejected {count} pending operation(s).", fg="green")


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "--apply-all",
    is_flag=True,
    default=False,
    help="Apply all operations (bulk mode)"
)
@click.option(
    "--reject-all",
    is_flag=True,
    default=False,
    help="Reject all operations (bulk mode)"
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts"
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing files (only with --apply-all)"
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview changes without making them (only with --apply-all or --reject-all)"
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    default=False,
    help="Recursive directory processing (only with --reject-all)"
)
def review(
    path: str | None,
    apply_all: bool,
    reject_all: bool,
    yes: bool,
    force: bool,
    dry_run: bool,
    recursive: bool
) -> None:
    """
    Review and process pending organization operations.

    Interactive mode (default): Review each operation and choose to apply,
    reject, or skip it. Press 'H' during review for help.

    Bulk modes: Use --apply-all or --reject-all for batch operations.

    Examples:
        - 'docman review': Review all operations interactively
        - 'docman review docs/': Review operations in docs/ directory
        - 'docman review --apply-all -y': Apply all without prompts
        - 'docman review --reject-all docs/': Reject all in docs/ (non-recursive)
        - 'docman review --reject-all -r': Reject all recursively
    """
    # Validate flags
    _validate_review_flags(path, apply_all, reject_all, dry_run, force, recursive)

    # Find repository root
    repo_root = _resolve_repository_root(path)
    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Route to appropriate handler based on mode
        if apply_all:
            _handle_bulk_apply(session, repo_root, path, yes, force, dry_run)
        elif reject_all:
            _handle_bulk_reject(session, repo_root, path, yes, recursive, dry_run)
        else:
            _handle_interactive_review(session, repo_root, path)

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
    "unmark_all",
    is_flag=True,
    default=False,
    help="Unmark all files in the repository",
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
    help="Recursively unmark files in subdirectories",
)
def unmark(path: str | None, unmark_all: bool, yes: bool, recursive: bool) -> None:
    """
    Unmark files that were previously organized or ignored.

    Sets the organization status back to 'unorganized' and deletes any pending
    operations, allowing the files to be reprocessed by the next 'plan' command.

    Arguments:
        PATH: Optional path to unmark files for (default: requires --all flag).

    Options:
        --all, -a: Unmark all files in the repository
        -y, --yes: Skip confirmation prompts
        -r, --recursive: Recursively unmark files in subdirectories

    Examples:
        - 'docman unmark --all': Unmark all files (with confirmation)
        - 'docman unmark --all -y': Unmark all without prompts
        - 'docman unmark docs/': Unmark files in docs directory
        - 'docman unmark docs/ -r': Unmark files in docs and subdirectories
        - 'docman unmark file.pdf': Unmark specific file
    """
    # Validate flags
    if not unmark_all and not path:
        click.secho(
            "Error: Must specify either --all or a PATH to unmark files.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman unmark --all")
        click.echo("  docman unmark docs/")
        click.echo("  docman unmark file.pdf")
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
        # Query document copies for this repository
        query = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
            .filter(DocumentCopy.organization_status.in_([OrganizationStatus.ORGANIZED, OrganizationStatus.IGNORED]))
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
                    import os
                    sep = os.sep
                    query = query.filter(
                        DocumentCopy.file_path.startswith(rel_path),
                        ~DocumentCopy.file_path.op('LIKE')(f"{rel_path}{sep}%{sep}%")
                    )
            else:
                click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
                raise click.Abort()

        document_copies = query.all()
        count = len(document_copies)

        if count == 0:
            click.echo("No organized or ignored files found.")
            if path:
                click.echo(f"  (filtered by: {path})")
            return

        # Show what will be unmarked
        click.echo()
        click.secho(f"Files to unmark: {count}", bold=True)
        click.echo(f"Repository: {repository_path}")
        if path:
            click.echo(f"Filter: {path}")
            if target_path.is_dir() and recursive:
                click.echo("Mode: Recursive")
            elif target_path.is_dir():
                click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        # Show the files that will be unmarked
        if count <= 10:
            # Show all if there are 10 or fewer
            for doc_copy in document_copies:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")
        else:
            # Show first 5 and last 3 if there are more than 10
            for doc_copy in document_copies[:5]:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")
            click.echo(f"  ... and {count - 8} more ...")
            for doc_copy in document_copies[-3:]:
                status_label = "organized" if doc_copy.organization_status == OrganizationStatus.ORGANIZED else "ignored"
                click.echo(f"  - {doc_copy.file_path} ({status_label})")

        click.echo()

        # Confirm if not using -y flag
        if not yes:
            if not click.confirm(f"Unmark {count} file(s)?"):
                click.echo("Aborted.")
                return

        # Unmark all files and delete pending operations
        for doc_copy in document_copies:
            # Reset organization status
            doc_copy.organization_status = OrganizationStatus.UNORGANIZED

            # Delete any pending operations
            pending_ops = session.query(Operation).filter(
                Operation.document_copy_id == doc_copy.id,
                Operation.status == OperationStatus.PENDING
            ).all()
            for pending_op in pending_ops:
                session.delete(pending_op)

        session.commit()

        click.secho(f"✓ Successfully unmarked {count} file(s).", fg="green")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.command()
@click.argument("path", default=None, required=False)
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
    help="Recursively ignore files in subdirectories",
)
def ignore(path: str | None, yes: bool, recursive: bool) -> None:
    """
    Mark files to be ignored by docman.

    Sets the organization status to 'ignored', preventing the files from being
    processed by 'plan' commands (unless --reprocess flag is used). Any existing
    pending operations will be deleted.

    Arguments:
        PATH: Path to file or directory to ignore (required).

    Options:
        -y, --yes: Skip confirmation prompts
        -r, --recursive: Recursively ignore files in subdirectories

    Examples:
        - 'docman ignore docs/': Ignore files in docs directory
        - 'docman ignore docs/ -r': Ignore files in docs and subdirectories
        - 'docman ignore file.pdf': Ignore specific file
    """
    # Validate path argument
    if not path:
        click.secho(
            "Error: Must specify a PATH to ignore files.",
            fg="red",
            err=True,
        )
        click.echo()
        click.echo("Examples:")
        click.echo("  docman ignore docs/")
        click.echo("  docman ignore file.pdf")
        raise click.Abort()

    # Find the repository root
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

    repository_path = str(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query document copies for this repository
        query = (
            session.query(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
        )

        # Filter by path
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
                import os
                sep = os.sep
                query = query.filter(
                    DocumentCopy.file_path.startswith(rel_path),
                    ~DocumentCopy.file_path.op('LIKE')(f"{rel_path}{sep}%{sep}%")
                )
        else:
            click.secho(f"Error: Path '{path}' does not exist", fg="red", err=True)
            raise click.Abort()

        document_copies = query.all()
        count = len(document_copies)

        if count == 0:
            click.echo("No files found.")
            click.echo(f"  (filtered by: {path})")
            return

        # Show what will be ignored
        click.echo()
        click.secho(f"Files to ignore: {count}", bold=True)
        click.echo(f"Repository: {repository_path}")
        click.echo(f"Filter: {path}")
        if target_path.is_dir() and recursive:
            click.echo("Mode: Recursive")
        elif target_path.is_dir():
            click.echo("Mode: Non-recursive (current directory only)")
        click.echo()

        # Show the files that will be ignored
        if count <= 10:
            # Show all if there are 10 or fewer
            for doc_copy in document_copies:
                click.echo(f"  - {doc_copy.file_path}")
        else:
            # Show first 5 and last 3 if there are more than 10
            for doc_copy in document_copies[:5]:
                click.echo(f"  - {doc_copy.file_path}")
            click.echo(f"  ... and {count - 8} more ...")
            for doc_copy in document_copies[-3:]:
                click.echo(f"  - {doc_copy.file_path}")

        click.echo()

        # Confirm if not using -y flag
        if not yes:
            if not click.confirm(f"Ignore {count} file(s)?"):
                click.echo("Aborted.")
                return

        # Mark all files as ignored and delete pending operations
        for doc_copy in document_copies:
            # Set organization status to ignored
            doc_copy.organization_status = OrganizationStatus.IGNORED

            # Delete any pending operations
            pending_ops = session.query(Operation).filter(
                Operation.document_copy_id == doc_copy.id,
                Operation.status == OperationStatus.PENDING
            ).all()
            for pending_op in pending_ops:
                session.delete(pending_op)

        session.commit()

        click.secho(f"✓ Successfully ignored {count} file(s).", fg="green")

    finally:
        # Close the session
        try:
            next(session_gen)
        except StopIteration:
            pass


@main.command()
@click.argument("path", default=None, required=False)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Automatically delete duplicate copies without confirmation (bulk mode)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be deleted without actually deleting files",
)
def dedupe(path: str | None, yes: bool, dry_run: bool) -> None:
    """
    Find and resolve duplicate files in the repository.

    Identifies documents with multiple copies (same content, different locations)
    and allows you to delete duplicates, keeping only one copy of each document.

    Interactive mode (default): Review each duplicate group and choose which copy to keep.
    Bulk mode (-y): Automatically keep the first copy found and delete the rest.

    Arguments:
        PATH: Optional path to limit deduplication scope (default: entire repository).

    Options:
        -y, --yes: Skip confirmation prompts (bulk mode)
        --dry-run: Preview changes without modifying files

    Examples:
        - 'docman dedupe': Interactive deduplication of entire repository
        - 'docman dedupe docs/': Deduplicate only files in docs directory
        - 'docman dedupe -y --dry-run': Preview bulk deduplication
        - 'docman dedupe -y': Auto-delete duplicates (keep first copy)
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

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Find all duplicate groups
        all_duplicate_groups = find_duplicate_groups(session, repo_root)

        # Filter by path if provided
        if path:
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

            # Filter duplicate groups to only include copies in target path
            filtered_groups: dict[int, list[DocumentCopy]] = {}
            for doc_id, copies in all_duplicate_groups.items():
                # Filter copies to those in target path
                matching_copies = [
                    copy
                    for copy in copies
                    if (repo_root / copy.file_path).resolve().is_relative_to(target_path)
                ]
                # Only include if we still have duplicates after filtering
                if len(matching_copies) > 1:
                    filtered_groups[doc_id] = matching_copies

            duplicate_groups = filtered_groups
        else:
            duplicate_groups = all_duplicate_groups

        if not duplicate_groups:
            click.echo("No duplicate files found.")
            if path:
                click.echo(f"  (searched in: {path})")
            return

        # Calculate statistics
        total_groups = len(duplicate_groups)
        total_copies = sum(len(copies) for copies in duplicate_groups.values())
        duplicate_copies = total_copies - total_groups  # All but one per group

        # Display header
        click.echo()
        click.secho(f"Found {total_groups} duplicate group(s)", bold=True)
        click.echo(f"Total copies: {total_copies}")
        click.echo(f"Duplicates to resolve: {duplicate_copies}")
        if path:
            click.echo(f"Scope: {path}")
        click.echo()

        if dry_run:
            click.secho("DRY RUN MODE - No files will be deleted", fg="yellow")
            click.echo()

        # Track what to delete
        copies_to_delete: list[DocumentCopy] = []

        # Process each duplicate group
        for group_idx, (document_id, copies) in enumerate(duplicate_groups.items(), start=1):
            # Get document for display
            doc = session.query(Document).filter(Document.id == document_id).first()
            content_hash_display = doc.content_hash[:8] if doc else "unknown"

            # Display group header
            click.secho(
                f"[Group {group_idx}/{total_groups}] {len(copies)} copies, "
                f"hash: {content_hash_display}...",
                fg="cyan",
                bold=True,
            )
            click.echo()

            # Display all copies in this group with metadata
            for idx, copy in enumerate(copies, start=1):
                file_path = repo_root / copy.file_path
                if file_path.exists():
                    stat = file_path.stat()
                    size_kb = stat.st_size / 1024
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    click.echo(f"  [{idx}] {copy.file_path}")
                    click.echo(f"      Size: {size_kb:.1f} KB, Modified: {mtime}")
                else:
                    click.echo(f"  [{idx}] {copy.file_path}")
                    click.secho("      (file not found on disk)", fg="red")

            click.echo()

            if yes:
                # Bulk mode: keep first, delete rest
                copies_to_delete.extend(copies[1:])
                click.echo(f"  Keeping: [1] {copies[0].file_path}")
                click.secho(f"  Deleting: {len(copies) - 1} duplicate(s)", fg="yellow")
                click.echo()
            else:
                # Interactive mode: ask user which to keep
                click.echo("Which copy do you want to keep?")
                click.echo("  Enter number to keep that copy")
                click.echo("  Enter 'a' to keep all (skip this group)")
                click.echo("  Enter 's' to skip this group")
                click.echo()

                while True:
                    choice = click.prompt("Your choice", type=str, default="1")

                    if choice.lower() in ["a", "all"]:
                        click.echo("  Keeping all copies, skipping group.")
                        break
                    elif choice.lower() in ["s", "skip"]:
                        click.echo("  Skipping group.")
                        break
                    else:
                        try:
                            choice_idx = int(choice)
                            if 1 <= choice_idx <= len(copies):
                                # Keep the chosen copy, delete the rest
                                kept_copy = copies[choice_idx - 1]
                                for idx, copy in enumerate(copies):
                                    if idx != (choice_idx - 1):
                                        copies_to_delete.append(copy)

                                click.echo(f"  Keeping: [{choice_idx}] {kept_copy.file_path}")
                                click.secho(
                                    f"  Marking {len(copies) - 1} duplicate(s) for deletion",
                                    fg="yellow",
                                )
                                break
                            else:
                                click.secho(
                                    f"  Invalid choice. Please enter 1-{len(copies)}, 'a', or 's'",
                                    fg="red",
                                )
                        except ValueError:
                            click.secho(
                                f"  Invalid input. Please enter 1-{len(copies)}, 'a', or 's'",
                                fg="red",
                            )

                click.echo()

        # Show summary
        if not copies_to_delete:
            click.echo("No duplicates selected for deletion.")
            return

        click.echo("=" * 50)
        click.secho(f"Summary: {len(copies_to_delete)} file(s) to delete", bold=True)
        click.echo()

        # Show files to be deleted
        for copy in copies_to_delete:
            click.echo(f"  - {copy.file_path}")

        click.echo()

        if dry_run:
            click.secho("DRY RUN: No files were deleted.", fg="yellow")
            return

        # Final confirmation if not in bulk mode
        if not yes:
            if not click.confirm(f"Delete {len(copies_to_delete)} file(s)?"):
                click.echo("Aborted.")
                return

        # Delete files and database records
        deleted_count = 0
        failed_count = 0

        for copy in copies_to_delete:
            file_path = repo_root / copy.file_path

            try:
                # Delete file from disk if it exists
                if file_path.exists():
                    file_path.unlink()

                # Delete from database (will cascade to Operation)
                session.delete(copy)
                deleted_count += 1
            except Exception as e:
                click.secho(f"  Error deleting {copy.file_path}: {e}", fg="red")
                failed_count += 1

        # Commit changes
        session.commit()

        # Show results
        click.echo()
        if deleted_count > 0:
            click.secho(f"✓ Successfully deleted {deleted_count} duplicate file(s).", fg="green")
        if failed_count > 0:
            click.secho(f"✗ Failed to delete {failed_count} file(s).", fg="red")

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
    type=click.Choice(["google", "local"], case_sensitive=False),
    help="Provider type (google, local, etc.)",
)
@click.option("--model", type=str, help="Model identifier (e.g., gemini-1.5-flash, google/gemma-2-2b-it)")
@click.option("--api-key", type=str, help="API key (not needed for local models)")
def llm_add(name: str | None, provider: str | None, model: str | None, api_key: str | None) -> None:
    """Add a new LLM provider configuration.

    If options are not provided, an interactive wizard will guide you through setup.
    """
    # Local providers don't need API keys
    if provider == "local":
        api_key = ""

    # If any option is missing (except api_key for local), use the wizard
    required_options = [name, provider, model]
    if provider != "local":
        required_options.append(api_key)

    if not all(required_options):
        if not run_llm_wizard():
            click.secho("Setup failed or cancelled.", fg="yellow")
            raise click.Abort()
        return

    # All required options provided - add provider directly
    # At this point we know all values are not None due to the check above
    assert name is not None
    assert provider is not None
    assert model is not None
    if provider != "local":
        assert api_key is not None
    else:
        api_key = ""

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

    # Show API key status (but not the actual key) - local models don't need keys
    if provider.provider_type != "local":
        api_key = get_api_key(provider.name)
        if api_key:
            click.secho("API Key: Configured ✓", fg="green")
        else:
            click.secho("API Key: Not found ✗", fg="red")
    else:
        click.secho("API Key: Not required (local model)", fg="cyan")
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

    # Get API key (not needed for local models)
    api_key = get_api_key(provider.name)
    if not api_key and provider.provider_type != "local":
        click.secho("Error: API key not found for this provider.", fg="red")
        raise click.Abort()

    # For local models, use empty string
    if provider.provider_type == "local":
        api_key = ""

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
