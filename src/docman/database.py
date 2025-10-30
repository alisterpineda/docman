"""Database configuration and session management for docman."""

from collections.abc import Generator
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
    # Get the path to the alembic directory (relative to this file)
    # The structure is: src/docman/database.py and alembic/ at project root
    project_root = Path(__file__).parent.parent.parent
    alembic_dir = project_root / "alembic"
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(
            f"Alembic configuration not found at {alembic_ini}. "
            "Please run 'alembic init alembic' first."
        )

    # Create Alembic config
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(alembic_dir))

    # Set the database URL dynamically
    db_path = get_database_path()
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    # Run migrations to the latest revision
    command.upgrade(alembic_cfg, "head")


def ensure_database() -> None:
    """
    Ensure the database exists and is up to date with migrations.

    This function:
    1. Ensures the app config directory exists
    2. Creates the database file if it doesn't exist
    3. Runs any pending migrations to update the schema

    This is idempotent and safe to call multiple times.
    """
    from docman.config import ensure_app_config

    # Ensure the app config directory exists
    ensure_app_config()

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
