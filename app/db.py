from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    if url.startswith("sqlite"):
        Path("var").mkdir(exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


engine = make_engine(settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session


def initialize_database():
    """Migrate; adopt only an exactly matching pre-migration local development schema."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect, text

    config = Config("alembic.ini")
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        versioned = (
            "alembic_version" in names
            and connection.execute(text("SELECT count(*) FROM alembic_version")).scalar() > 0
        )
        if "organizations" in names and not versioned:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            if differences:
                raise RuntimeError(
                    "Unversioned schema differs from application metadata; migration adoption refused"
                )
    if "organizations" in names and not versioned:
        if settings().environment not in {"local", "test"}:
            raise RuntimeError("Unversioned production database requires reviewed migration plan")
        command.stamp(config, "8588dede27de")
    command.upgrade(config, "head")
