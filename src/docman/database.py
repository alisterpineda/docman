"""Database configuration and session management for docman."""

from collections.abc import Generator
from contextlib import ExitStack
from importlib import resources
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from docman.config import get_app_config_dir


def get_database_path() -> Path:
    """
    Get the path to the SQLite database file.

    The database is stored in the app config directory as 'docman.db'.

    Returns:
        Path to the database file.
    """
    return get_app_config_dir() / "docman.db"


def get_engine() -> Engine:
    """
    Create and return a SQLAlchemy engine for the SQLite database.

    Returns:
        SQLAlchemy Engine configured for the docman database.
    """
    db_path = get_database_path()
    # Use check_same_thread=False to allow using the engine across threads
    # This is safe for our use case since we're not sharing connections
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,  # Set to True for SQL query debugging
    )
    return engine


def get_session_factory() -> sessionmaker:  # type: ignore[type-arg]
    """
    Create and return a session factory.

    Returns:
        A sessionmaker instance configured with the database engine.
    """
    engine = get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """
    Get a database session.

    This is a generator function that yields a session and ensures
    it's properly closed after use.

    Usage:
        with next(get_session()) as session:
            # Use session here
            pass

    Yields:
        SQLAlchemy Session instance.
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def run_migrations() -> None:
    """
    Run Alembic migrations to bring the database up to date.

    This function locates the alembic.ini file and runs all pending
    migrations to ensure the database schema is current.
    """
    with ExitStack() as exit_stack:
        try:
            docman_pkg = resources.files("docman")
        except ModuleNotFoundError as exc:
            raise FileNotFoundError(
                "The 'docman' package could not be located when loading Alembic resources."
            ) from exc

        try:
            alembic_ini = exit_stack.enter_context(
                resources.as_file(docman_pkg / "alembic.ini")
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Alembic configuration not packaged with docman. "
                "Reinstall docman to restore migration assets."
            ) from exc
        if not Path(alembic_ini).exists():
            raise FileNotFoundError(
                "Alembic configuration not packaged with docman. "
                "Reinstall docman to restore migration assets."
            )

        try:
            alembic_dir = exit_stack.enter_context(
                resources.as_file(docman_pkg / "alembic")
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Alembic migration scripts not packaged with docman. "
                "Reinstall docman to restore migration assets."
            ) from exc
        if not Path(alembic_dir).exists():
            raise FileNotFoundError(
                "Alembic migration scripts not packaged with docman. "
                "Reinstall docman to restore migration assets."
            )

        # Create Alembic config
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(alembic_dir))

    # Set the database URL dynamically
    db_path = get_database_path()
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Run migrations to the latest revision
    command.upgrade(alembic_cfg, "head")


def _is_database_current() -> bool:
    """
    Quick check if database exists and is at the current migration version.

    This is a performance optimization to avoid running Alembic checks on every invocation.
    We check for a version marker file that contains the current migration revision.

    Returns:
        True if database exists and is current, False otherwise.
    """
    db_path = get_database_path()
    if not db_path.exists():
        return False

    # Version marker file stores the current migration revision
    version_marker = get_app_config_dir() / ".db_version"
    if not version_marker.exists():
        return False

    try:
        # Read the stored version
        stored_version = version_marker.read_text().strip()

        # Get the current head revision from Alembic
        # This is fast since it just reads from the migrations directory
        with ExitStack() as exit_stack:
            docman_pkg = resources.files("docman")
            alembic_ini = exit_stack.enter_context(
                resources.as_file(docman_pkg / "alembic.ini")
            )
            alembic_dir = exit_stack.enter_context(
                resources.as_file(docman_pkg / "alembic")
            )

            from alembic.script import ScriptDirectory
            script = ScriptDirectory(str(alembic_dir))
            head_revision = script.get_current_head()

            # Check if versions match
            return stored_version == head_revision

    except Exception:
        # If anything goes wrong, assume we need to run migrations
        return False


def _update_version_marker() -> None:
    """Update the version marker file with the current migration revision."""
    try:
        with ExitStack() as exit_stack:
            docman_pkg = resources.files("docman")
            alembic_dir = exit_stack.enter_context(
                resources.as_file(docman_pkg / "alembic")
            )

            from alembic.script import ScriptDirectory
            script = ScriptDirectory(str(alembic_dir))
            head_revision = script.get_current_head()

            # Write the current version to the marker file
            version_marker = get_app_config_dir() / ".db_version"
            version_marker.write_text(head_revision)

    except Exception:
        # If we can't update the marker, migrations will run next time
        pass


def ensure_database() -> None:
    """
    Ensure the database exists and is up to date with migrations.

    This function:
    1. Ensures the app config directory exists
    2. Creates the database file if it doesn't exist
    3. Runs any pending migrations to update the schema (cached for performance)

    This is idempotent and safe to call multiple times.
    Performance optimization: checks version marker to skip migrations when not needed.
    """
    from docman.config import ensure_app_config

    # Ensure the app config directory exists
    ensure_app_config()

    # Fast path: check if database is current without running Alembic
    if _is_database_current():
        return

    db_path = get_database_path()

    # If database doesn't exist, create it
    if not db_path.exists():
        # Create an empty database file
        # The migrations will create the actual tables
        engine = get_engine()
        # This creates the file
        with engine.connect():
            pass

    # Run migrations to ensure schema is up to date
    run_migrations()

    # Update the version marker for next time
    _update_version_marker()
