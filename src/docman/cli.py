"""
docman - A CLI tool for organizing documents.

This tool uses docling and LLM models (cloud or local) to help organize,
move, and rename documents intelligently.
"""

from pathlib import Path

import click

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
from docman.models import Document, DocumentCopy, PendingOperation, compute_content_hash
from docman.processor import extract_content
from docman.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    get_directory_structure,
    load_custom_instructions,
)
from docman.repo_config import (
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

        click.echo(f"Initialized empty docman repository in {docman_dir}/")
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
                    # Recursive discovery in subdirectory
                    all_files = discover_document_files(repo_root)
                    rel_target = target_path.relative_to(repo_root)
                    document_files = [
                        f for f in all_files if f.parts[:len(rel_target.parts)] == rel_target.parts
                    ]
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

    # Build prompts for LLM (done once for entire repository)
    system_prompt = build_system_prompt()
    directory_structure = get_directory_structure(repo_root)
    custom_instructions = load_custom_instructions(repo_root)

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
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

        # Process each file
        for idx, file_path in enumerate(document_files, start=1):
            file_path_str = str(file_path)
            percentage = int((idx / len(document_files)) * 100)

            # Check if copy already exists in this repository at this path
            if file_path_str in existing_copy_paths:
                # Retrieve existing copy
                click.echo(
                    f"[{idx}/{len(document_files)}] {percentage}% "
                    f"Reusing existing copy: {file_path}"
                )
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
                    content = extract_content(full_path)

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

                # Create document copy for this repository
                copy = DocumentCopy(
                    document_id=document.id,
                    repository_path=repository_path,
                    file_path=file_path_str,
                )
                session.add(copy)
                session.flush()  # Get the copy.id for the pending operation

            # Step 2: Create pending operation if it doesn't exist (always runs)
            existing_pending_op = (
                session.query(PendingOperation)
                .filter(PendingOperation.document_copy_id == copy.id)
                .first()
            )

            if not existing_pending_op:
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
                            directory_structure,
                            custom_instructions,
                        )
                        suggestions = llm_provider_instance.generate_suggestions(
                            system_prompt,
                            user_prompt
                        )

                        pending_op = PendingOperation(
                            document_copy_id=copy.id,
                            suggested_directory_path=suggestions["suggested_directory_path"],
                            suggested_filename=suggestions["suggested_filename"],
                            reason=suggestions["reason"],
                            confidence=suggestions["confidence"],
                        )
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

                        pending_op = PendingOperation(
                            document_copy_id=copy.id,
                            suggested_directory_path=current_directory,
                            suggested_filename=current_filename,
                            reason="LLM analysis failed, kept original location",
                            confidence=0.5,
                        )
                else:
                    # Fallback to stub if no content or LLM not available
                    file_path_obj = Path(file_path_str)
                    current_directory = (
                        str(file_path_obj.parent) if file_path_obj.parent != Path('.') else ""
                    )
                    current_filename = file_path_obj.name

                    pending_op = PendingOperation(
                        document_copy_id=copy.id,
                        suggested_directory_path=current_directory,
                        suggested_filename=current_filename,
                        reason="No content available for analysis",
                        confidence=0.5,
                    )

                session.add(pending_op)
                pending_ops_created += 1
            else:
                click.echo("  Pending operation already exists")

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
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
def reset(path: str | None, yes: bool) -> None:
    """
    Clear all pending operations for a repository.

    Removes all pending operations from the database for the specified repository.
    By default, uses the current directory to find the repository.

    Arguments:
        PATH: Optional path to a directory within the repository (default: current directory).

    Options:
        -y, --yes: Skip confirmation prompt and delete immediately.

    Examples:
        - 'docman reset': Clear pending operations for repository in current directory
        - 'docman reset /path/to/repo': Clear pending operations for specified repository
        - 'docman reset -y': Clear without confirmation prompt
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
    click.echo(f"Repository: {repository_path}")

    # Get database session
    session_gen = get_session()
    session = next(session_gen)

    try:
        # Query pending operations for this repository
        pending_ops_to_delete = (
            session.query(PendingOperation)
            .join(DocumentCopy)
            .filter(DocumentCopy.repository_path == repository_path)
            .all()
        )

        count = len(pending_ops_to_delete)

        if count == 0:
            click.echo("No pending operations found for this repository.")
            return

        # Show count and ask for confirmation
        click.echo(f"Found {count} pending operation(s) to delete.")

        if not yes:
            if not click.confirm("Are you sure you want to delete these pending operations?"):
                click.echo("Aborted.")
                return

        # Delete all pending operations
        for op in pending_ops_to_delete:
            session.delete(op)

        session.commit()

        click.echo(f"Successfully deleted {count} pending operation(s).")

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
    """Set custom organization instructions for a repository.

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
    """Show custom organization instructions for a repository.

    Displays the current custom instructions configured for the repository.

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
        click.secho("Custom Organization Instructions:", bold=True)
        click.echo()
        click.echo(instructions)
        click.echo()
    else:
        click.echo("No custom instructions configured for this repository.")
        click.echo()
        click.echo("Run 'docman config set-instructions' to add instructions.")


if __name__ == "__main__":
    main()
