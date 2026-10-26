"""Base declarativa, convenciones de nombres y tipos comunes."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

# Nombres de restricciones estables: Alembic los necesita para operar en modo batch sobre SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def UtcDateTime() -> DateTime:  # noqa: N802 - se usa como un tipo de columna
    return DateTime(timezone=True)


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Enum guardado como texto, con restricción CHECK sobre los valores permitidos."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )
