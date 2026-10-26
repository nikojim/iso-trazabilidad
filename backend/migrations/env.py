from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db.session import create_db_engine
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_database_url())
    try:
        with engine.connect() as connection:
            # El modo batch de SQLite recrea las tablas: con las claves externas activas, borrar
            # la tabla vieja dispararía ON DELETE CASCADE / SET NULL sobre las que la referencian
            # (p. ej. se perderían todas las referencias al recrear "documents"). El PRAGMA solo
            # tiene efecto fuera de una transacción; al final se verifica la integridad.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.commit()
            if violations:
                raise RuntimeError(f"La migración dejó claves externas inválidas: {violations}")
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
