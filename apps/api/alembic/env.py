import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from core.config import get_settings
from core.database import engine  # also applies the Windows event loop policy
from models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares this metadata against the live database schema.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, so no
    database connection is made. Calls to context.execute() here emit SQL
    to stdout instead of applying it.
    """
    context.configure(
        url=get_settings().sqlalchemy_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the application's async engine.

    core.database.engine applies the Windows selector event loop policy
    required by psycopg3's async mode, and supplies the URL from app
    settings (env vars / .env) so there is no second copy in alembic.ini.
    """
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
