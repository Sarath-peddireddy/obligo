"""Small additive migration for databases created before contract source clauses."""
from sqlalchemy import inspect, text

from app.database import Base, engine


def initialize_database() -> None:
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(782393103)"))
        Base.metadata.create_all(bind=connection)
        columns = {column["name"] for column in inspect(connection).get_columns("contracts")}
        if "source_clause" not in columns:
            connection.execute(text("ALTER TABLE contracts ADD COLUMN source_clause TEXT"))
        if "workspace_id" not in columns:
            connection.execute(text("ALTER TABLE contracts ADD COLUMN workspace_id VARCHAR(64)"))
        session_columns = {column["name"] for column in inspect(connection).get_columns("browser_sessions")}
        if "workspace_id" not in session_columns:
            connection.execute(text("ALTER TABLE browser_sessions ADD COLUMN workspace_id VARCHAR(64)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_contracts_workspace_id ON contracts (workspace_id)"))
        connection.execute(text("UPDATE obligations SET review_status = 'pending_review' WHERE review_status = 'pending'"))
