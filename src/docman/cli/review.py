"""Review command for docman CLI.

This module contains the review command and its helper functions for reviewing
and processing pending organization operations. Supports both interactive and
bulk modes for applying or rejecting operations.
"""

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

import click

from docman.cli.utils import require_database
from docman.database import get_session
from docman.file_operations import (
    ConflictResolution,
    FileConflictError,
    FileNotFoundError as DocmanFileNotFoundError,
    FileOperationError,
    move_file,
)
from docman.llm_config import get_active_provider, get_api_key
from docman.llm_providers import get_provider as get_llm_provider
from docman.models import (
    Document,
    DocumentCopy,
    Operation,
    OperationStatus,
    OrganizationStatus,
)
from docman.path_alignment import check_path_alignment
from docman.path_security import PathSecurityError, validate_target_path
from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    generate_instructions,
    serialize_folder_definitions,
)
from docman.repo_config import (
    get_default_filename_convention,
    get_folder_definitions,
    get_variable_patterns,
)
from docman.repository import RepositoryError, get_repository_root

# Import helper functions from utils module
from docman.cli.utils import detect_conflicts_in_operations, find_duplicate_groups


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


def _format_suggestion_as_json(suggestion: dict[str, str]) -> str:
    """Format an LLM suggestion as pretty-printed JSON.

    Args:
        suggestion: Dictionary with suggested_directory_path, suggested_filename, reason.

    Returns:
        Pretty-printed JSON string.
    """
    return json.dumps(
        {
            "suggested_directory_path": suggestion["suggested_directory_path"],
            "suggested_filename": suggestion["suggested_filename"],
            "reason": suggestion["reason"]
        },
        indent=2
    )


def _regenerate_suggestion(
    session,
    pending_op: Operation,
    doc_copy: DocumentCopy,
    document: Document,
    repo_root: Path,
    user_prompt: str,
) -> tuple[bool, dict[str, str] | None]:
    """Regenerate LLM suggestion with a pre-built user prompt.

    Args:
        session: Database session
        pending_op: The operation to regenerate (not modified)
        doc_copy: The document copy being processed
        document: The canonical document with content
        repo_root: Repository root path
        user_prompt: Pre-built user prompt (includes base prompt + conversation history)

    Returns:
        Tuple of (success: bool, suggestions: dict | None)
        - success: True if generation succeeded, False otherwise
        - suggestions: Dict with suggested_directory_path, suggested_filename, reason if success, None otherwise
    """
    try:
        # Get LLM provider
        active_provider = get_active_provider()
        api_key = get_api_key(active_provider.name)
        llm_provider_instance = get_llm_provider(active_provider, api_key)

        # Load organization instructions from folder definitions
        organization_instructions = generate_instructions(repo_root)
        if not organization_instructions:
            click.secho(
                "  Error: No folder definitions found.",
                fg="red"
            )
            click.echo("  Run 'docman define <path> --desc \"description\"' to create folder definitions.")
            return False, None

        # Build system prompt (user prompt is already provided)
        system_prompt = build_system_prompt(
            use_structured_output=llm_provider_instance.supports_structured_output
        )

        # Generate new suggestion
        click.echo("  Generating new suggestion...")
        suggestions = llm_provider_instance.generate_suggestions(
            system_prompt,
            user_prompt
        )

        # Validate the new suggestion before returning it
        try:
            validate_target_path(
                repo_root,
                suggestions["suggested_directory_path"],
                suggestions["suggested_filename"]
            )
        except PathSecurityError as e:
            click.secho(f"  Error: LLM generated invalid path: {e}", fg="red")
            return False, None

        # Return the suggestion without persisting to database
        return True, suggestions

    except Exception as e:
        click.secho(f"  Error regenerating suggestion: {e}", fg="red")
        return False, None


def _persist_reprocessed_suggestion(
    pending_op: Operation,
    doc_copy: DocumentCopy,
    in_memory_suggestion: dict[str, str],
    repo_root: Path,
) -> None:
    """Persist an in-memory re-processed suggestion to the database.

    This should only be called after a successful file operation (move/rename/overwrite).

    Args:
        pending_op: The operation to update
        doc_copy: The document copy being processed
        in_memory_suggestion: Dict with suggested_directory_path, suggested_filename, reason
        repo_root: Repository root path
    """
    # Get active provider and compute prompt hash for tracking
    active_provider = get_active_provider()
    organization_instructions = generate_instructions(repo_root)
    llm_provider_instance = get_llm_provider(active_provider, get_api_key(active_provider.name))
    system_prompt = build_system_prompt(
        use_structured_output=llm_provider_instance.supports_structured_output
    )
    model_name = active_provider.model

    # Load folder definitions and default convention to include in hash computation (if applicable)
    folder_definitions = get_folder_definitions(repo_root)
    default_filename_convention = get_default_filename_convention(repo_root)

    # Compute prompt hash the same way plan command does
    # Include serialized folder definitions to maintain hash consistency
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

    sha256_hash = hashlib.sha256()
    sha256_hash.update(prompt_components.encode("utf-8"))
    current_prompt_hash = sha256_hash.hexdigest()

    # Update operation with in-memory suggestion
    pending_op.suggested_directory_path = in_memory_suggestion["suggested_directory_path"]
    pending_op.suggested_filename = in_memory_suggestion["suggested_filename"]
    pending_op.reason = in_memory_suggestion["reason"]
    pending_op.prompt_hash = current_prompt_hash
    pending_op.document_content_hash = doc_copy.document.content_hash
    pending_op.model_name = model_name


def _find_common_prefix(path1: str, path2: str) -> tuple[str, str, str]:
    """
    Find the common prefix between two paths at the component level.

    Returns:
        tuple: (common_prefix, path1_remainder, path2_remainder)
    """
    parts1 = path1.split('/')
    parts2 = path2.split('/')

    # Find common prefix components
    common_parts = []
    for p1, p2 in zip(parts1, parts2):
        if p1 == p2:
            common_parts.append(p1)
        else:
            break

    # Build the common prefix
    common_prefix = '/'.join(common_parts)

    # Build the remainders
    if common_parts:
        path1_remainder = '/'.join(parts1[len(common_parts):])
        path2_remainder = '/'.join(parts2[len(common_parts):])
        # Add separator if either path has a remainder
        if path1_remainder or path2_remainder:
            common_prefix += '/'
    else:
        path1_remainder = path1
        path2_remainder = path2

    return common_prefix, path1_remainder, path2_remainder


def _format_path_comparison(label: str, path: str, common_prefix: str, remainder: str, is_suggested: bool = False) -> None:
    """
    Display a path with color highlighting for differences.

    Args:
        label: Label to display (e.g., "Current:" or "Suggested:")
        path: Full path string
        common_prefix: Common prefix portion (displayed in dim)
        remainder: Different portion (colored based on is_suggested)
        is_suggested: True for suggested path (green), False for current path (red)
    """
    # Fixed column alignment - align paths after label
    # "  Suggested:" is 12 chars, add 2 more for spacing = 14 total
    label_width = 14
    padded_label = f"  {label}".ljust(label_width)

    # Use diff-style colors: red for removals (current), green for additions (suggested)
    diff_color = 'green' if is_suggested else 'red'

    # Build the colored output
    if common_prefix and remainder:
        # Show common part in default color, different part in diff color
        output = (
            padded_label +
            common_prefix +
            click.style(remainder, fg=diff_color, bold=True)
        )
    elif remainder:
        # No common prefix, entire path is different
        output = padded_label + click.style(remainder, fg=diff_color, bold=True)
    else:
        # Entire path is common (shouldn't happen in practice)
        output = padded_label + path

    click.echo(output)


def _open_file_with_default_app(file_path: Path) -> bool:
    """
    Open a file with the system's default application.

    Args:
        file_path: Path to the file to open

    Returns:
        True if the file was opened successfully, False otherwise
    """
    try:
        system = platform.system()

        if system == "Darwin":  # macOS
            subprocess.run(["open", str(file_path)], check=True)
        elif system == "Windows":
            # Use os.startfile for Windows (more reliable than subprocess)
            os.startfile(str(file_path))
        else:  # Linux and other Unix-like systems
            subprocess.run(["xdg-open", str(file_path)], check=True)

        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        # Command not found (e.g., xdg-open not available)
        return False
    except Exception:
        # Catch any other exceptions (e.g., os.startfile failures)
        return False


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
    # Load folder definitions for path alignment checking
    try:
        folder_defs = get_folder_definitions(repo_root)
        var_patterns = get_variable_patterns(repo_root)
    except ValueError:
        # YAML syntax error - skip alignment checking
        folder_defs = {}
        var_patterns = {}

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

        # Track conversation state for re-processing iterations
        # Will be initialized on first [P]rocess action
        current_user_prompt = None

        # Track in-memory re-processed suggestion (not persisted until successfully applied)
        in_memory_suggestion: dict[str, str] | None = None

        # Current path
        current_path = doc_copy.file_path
        source = repo_root / current_path

        # Suggested path with security validation
        # Use in-memory suggestion if available (from re-processing), otherwise use DB suggestion
        if in_memory_suggestion:
            suggested_dir = in_memory_suggestion["suggested_directory_path"]
            suggested_filename = in_memory_suggestion["suggested_filename"]
            display_reason = in_memory_suggestion["reason"]
        else:
            suggested_dir = pending_op.suggested_directory_path
            suggested_filename = pending_op.suggested_filename
            display_reason = pending_op.reason

        try:
            target = validate_target_path(repo_root, suggested_dir, suggested_filename)
        except PathSecurityError as e:
            # Invalid path detected - prompt user to reject it to clean up the queue
            click.echo()
            click.secho(
                "  ⚠️  Security Error: Invalid path suggestion detected",
                fg="red",
            )
            click.echo(f"  File: {current_path}")
            click.echo(f"  Invalid suggestion: {suggested_dir}/{suggested_filename}")
            click.echo(f"  Reason: {str(e)}")
            click.echo()

            if click.confirm("Reject this invalid operation to clean it up?", default=True):
                pending_op.status = OperationStatus.REJECTED
                click.secho("  ✗ Rejected (invalid path)", fg="red")
                rejected_count += 1
            else:
                click.secho("  ○ Skipped (will appear again next time)", fg="yellow")
                skipped_count += 1
            continue

        # Show progress
        percentage = int((idx / len(pending_ops)) * 100)
        click.echo()
        click.echo(f"[{idx}/{len(pending_ops)}] {percentage}%")

        # Check if it's a no-op (file already at target location)
        if source.resolve() == target.resolve():
            click.echo(f"  {current_path}")
            click.secho("  → (no change needed, already at target location)", fg="yellow")
            click.echo(f"  Reason: {pending_op.reason}")
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
        suggested_path = str(target.relative_to(repo_root))
        common_prefix, current_remainder, suggested_remainder = _find_common_prefix(
            current_path, suggested_path
        )

        _format_path_comparison("Current:", current_path, common_prefix, current_remainder)
        _format_path_comparison("Suggested:", suggested_path, common_prefix, suggested_remainder, is_suggested=True)
        click.echo(f"  Reason: {display_reason}")

        # Check path alignment with folder structure
        is_aligned, alignment_warning = check_path_alignment(
            suggested_dir, folder_defs, var_patterns
        )
        if not is_aligned and alignment_warning:
            click.secho(f"  ⚠️  {alignment_warning}", fg="yellow")

        click.echo()

        # Prompt user for action
        while True:
            action = click.prompt(
                "  [A]pply / [R]eject / [S]kip / [O]pen / [P]rocess / [Q]uit / [H]elp",
                type=str,
                default="S",
                show_default=True,
            ).strip().upper()

            if action in ["A", "APPLY"]:
                # Apply: move file and mark as ACCEPTED
                try:
                    move_file(source, target, conflict_resolution=ConflictResolution.SKIP, create_dirs=True)
                    click.secho("  ✓ Applied", fg="green")

                    # Update the document copy's file path in the database
                    doc_copy.file_path = str(target.relative_to(repo_root))

                    # If there's an in-memory suggestion from re-processing, persist it to the database NOW
                    # (after successful file move)
                    if in_memory_suggestion:
                        try:
                            _persist_reprocessed_suggestion(pending_op, doc_copy, in_memory_suggestion, repo_root)
                        except ValueError as e:
                            # Catch YAML syntax errors - file already moved, just warn
                            click.secho(f"  ⚠️  Warning: {e}", fg="yellow")
                            click.echo("  File moved successfully, but operation metadata may be incomplete.")

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
                        click.secho("  ⚠️  CONFLICT: Target already exists", fg="yellow")
                        click.echo(f"    Current: {e.source}")
                        click.echo(f"    Target:  {e.target}")
                        click.echo()
                        click.echo("These files have identical content (duplicates detected)")
                        click.echo()
                        click.echo("Choose action:")
                        click.echo("  [D]elete this copy (recommended)")
                        click.echo(f"  [R]ename → {target.stem}_1{target.suffix}")
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

                            # If there's an in-memory suggestion from re-processing, persist it now
                            if in_memory_suggestion:
                                try:
                                    _persist_reprocessed_suggestion(pending_op, doc_copy, in_memory_suggestion, repo_root)
                                except ValueError as e:
                                    # Catch YAML syntax errors - file already moved, just warn
                                    click.secho(f"  ⚠️  Warning: {e}", fg="yellow")
                                    click.echo("  File moved successfully, but operation metadata may be incomplete.")

                            pending_op.status = OperationStatus.ACCEPTED
                            doc_copy.accepted_operation_id = pending_op.id
                            doc_copy.organization_status = OrganizationStatus.ORGANIZED
                            click.secho(f"  ✓ Renamed to {new_target.name}", fg="green")
                            applied_count += 1
                        elif choice.upper() == 'O':
                            # Use OVERWRITE conflict resolution
                            move_file(source, target, conflict_resolution=ConflictResolution.OVERWRITE, create_dirs=True)
                            doc_copy.file_path = str(target.relative_to(repo_root))

                            # If there's an in-memory suggestion from re-processing, persist it now
                            if in_memory_suggestion:
                                try:
                                    _persist_reprocessed_suggestion(pending_op, doc_copy, in_memory_suggestion, repo_root)
                                except ValueError as e:
                                    # Catch YAML syntax errors - file already moved, just warn
                                    click.secho(f"  ⚠️  Warning: {e}", fg="yellow")
                                    click.echo("  File moved successfully, but operation metadata may be incomplete.")

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

            elif action in ["O", "OPEN"]:
                # Open: open the file with default application
                file_path = repo_root / doc_copy.file_path
                if not file_path.exists():
                    click.secho("  ✗ Error: File not found", fg="red")
                    continue

                if _open_file_with_default_app(file_path):
                    click.secho("  ✓ Opened file with default application", fg="green")
                else:
                    click.secho("  ✗ Error: Failed to open file", fg="red")
                    click.echo("    (No default application found or system command failed)")

                # Continue in the loop to re-prompt for action
                continue

            elif action in ["P", "PROCESS"]:
                # Process: regenerate suggestion with additional instructions
                click.echo()
                click.secho("Re-process this suggestion with additional instructions", fg="cyan")
                click.echo()

                user_feedback = click.prompt(
                    "  Your feedback for the LLM (or press Enter to cancel)",
                    type=str,
                    default="",
                    show_default=False,
                ).strip()

                if not user_feedback:
                    click.echo("  Cancelled re-processing")
                    continue  # Don't increment idx, stay in while loop to re-prompt

                # Initialize base user prompt on first re-process
                if current_user_prompt is None:
                    # Load organization instructions from folder definitions
                    try:
                        organization_instructions = generate_instructions(repo_root)
                    except ValueError as e:
                        # Catch YAML syntax errors from load_repo_config()
                        click.secho(f"  Error: {e}", fg="red")
                        continue

                    if not organization_instructions:
                        click.secho(
                            "  Error: No folder definitions found.",
                            fg="red"
                        )
                        click.echo("  Run 'docman define <path> --desc \"description\"' to create folder definitions.")
                        continue

                    # Build base user prompt
                    file_path_str = str(doc_copy.file_path)
                    current_user_prompt = build_user_prompt(
                        file_path_str,
                        doc_copy.document.content,
                        organization_instructions,
                    )

                # Capture current suggestion before regeneration
                # Use in-memory suggestion if available, otherwise use DB suggestion
                if in_memory_suggestion:
                    current_suggestion = in_memory_suggestion
                else:
                    current_suggestion = {
                        "suggested_directory_path": pending_op.suggested_directory_path,
                        "suggested_filename": pending_op.suggested_filename,
                        "reason": pending_op.reason,
                    }

                # Append current suggestion and user feedback to prompt
                current_user_prompt += "\n\n" + _format_suggestion_as_json(current_suggestion)
                current_user_prompt += f"\n\n<userFeedback>\n{user_feedback}\n</userFeedback>"

                # Regenerate suggestion with growing prompt (returns new suggestion without persisting)
                success, new_suggestion = _regenerate_suggestion(
                    session,
                    pending_op,
                    doc_copy,
                    doc_copy.document,
                    repo_root,
                    current_user_prompt,
                )

                if success and new_suggestion:
                    click.echo()
                    click.secho("✓ New suggestion generated!", fg="green")
                    click.echo()

                    # Store new suggestion in memory (will be persisted only if user applies)
                    in_memory_suggestion = new_suggestion

                    # Re-compute target path with new suggestion (already validated in _regenerate_suggestion)
                    suggested_dir = new_suggestion["suggested_directory_path"]
                    suggested_filename = new_suggestion["suggested_filename"]
                    target = validate_target_path(repo_root, suggested_dir, suggested_filename)

                    # Re-display operation details with new suggestion
                    suggested_path = str(target.relative_to(repo_root))
                    common_prefix, current_remainder, suggested_remainder = _find_common_prefix(
                        current_path, suggested_path
                    )

                    _format_path_comparison("Current:", current_path, common_prefix, current_remainder)
                    _format_path_comparison("Suggested:", suggested_path, common_prefix, suggested_remainder, is_suggested=True)
                    click.echo(f"  Reason: {new_suggestion['reason']}")
                    click.echo()
                    # Continue in while loop to prompt for next action
                    continue
                else:
                    click.echo()
                    click.secho("Failed to regenerate suggestion. Keeping current suggestion.", fg="yellow")
                    # Continue in while loop to allow user to choose another action
                    continue

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
                click.echo("    [O]pen   - Open file with default application for preview")
                click.echo("    [P]rocess - Re-generate suggestion with additional instructions")
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
    # Load folder definitions for path alignment checking
    try:
        folder_defs = get_folder_definitions(repo_root)
        var_patterns = get_variable_patterns(repo_root)
    except ValueError:
        # YAML syntax error - skip alignment checking
        folder_defs = {}
        var_patterns = {}

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

    # Check for unaligned paths and show summary warning
    if folder_defs:
        unaligned_count = sum(
            1 for op, _ in pending_ops
            if not check_path_alignment(
                op.suggested_directory_path, folder_defs, var_patterns
            )[0]
        )
        if unaligned_count > 0:
            click.secho(
                f"⚠️  {unaligned_count} path(s) don't align with folder structure",
                fg="yellow"
            )

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

        # Suggested path with security validation
        suggested_dir = pending_op.suggested_directory_path
        suggested_filename = pending_op.suggested_filename
        try:
            target = validate_target_path(repo_root, suggested_dir, suggested_filename)
        except PathSecurityError as e:
            # Invalid path detected - automatically reject it to clean up the queue
            click.echo()
            click.secho(
                "  ⚠️  Security Error: Invalid path suggestion detected",
                fg="red",
            )
            click.echo(f"  File: {current_path}")
            click.echo(f"  Invalid suggestion: {suggested_dir}/{suggested_filename}")
            click.echo(f"  Reason: {str(e)}")

            # Auto-reject invalid operations in bulk mode (unless dry run)
            if not dry_run:
                pending_op.status = OperationStatus.REJECTED
                click.secho("  ✗ Auto-rejected (invalid path)", fg="red")
            else:
                click.secho("  [DRY RUN] Would auto-reject this invalid operation", fg="cyan")

            failed_count += 1
            failed_operations.append((current_path, "Invalid path: " + str(e)))
            continue

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
        suggested_path = str(target.relative_to(repo_root))
        common_prefix, current_remainder, suggested_remainder = _find_common_prefix(
            current_path, suggested_path
        )

        _format_path_comparison("Current:", current_path, common_prefix, current_remainder)
        _format_path_comparison("Suggested:", suggested_path, common_prefix, suggested_remainder, is_suggested=True)

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


@click.command()
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
@require_database
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
    str(repo_root)

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
