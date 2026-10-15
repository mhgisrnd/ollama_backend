import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.registry import ClientRecord, ClientRegistration, ToolCatalog, ToolRegistration


class ClientNotFound(Exception):
    pass


class RegistryStore:
    """Short, transactional SQLite operations, each with its own connection."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                app_version TEXT NOT NULL, registered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, tools_json TEXT NOT NULL DEFAULT '[]',
                tools_revision INTEGER NOT NULL DEFAULT 0, tools_updated_at TEXT
            )""")

    @staticmethod
    def _record(row):
        return ClientRecord(**{key: row[key] for key in (
            "client_id", "display_name", "app_version", "registered_at", "updated_at",
        )})

    def register(self, client_id: str, body: ClientRegistration) -> ClientRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("""INSERT INTO clients (client_id, display_name, app_version, registered_at, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(client_id) DO UPDATE SET
                display_name=excluded.display_name, app_version=excluded.app_version,
                updated_at=excluded.updated_at""", (client_id, body.display_name, body.app_version, now, now))
            return self._record(db.execute("SELECT * FROM clients WHERE client_id=?", (client_id,)).fetchone())

    def list_clients(self) -> list[ClientRecord]:
        with self._connect() as db:
            return [self._record(row) for row in db.execute("SELECT * FROM clients ORDER BY client_id")]

    @staticmethod
    def _catalog(row):
        if row is None:
            raise ClientNotFound()
        return ToolCatalog(client_id=row["client_id"], revision=row["tools_revision"],
                           updated_at=row["tools_updated_at"], tools=json.loads(row["tools_json"]))

    def get_tools(self, client_id: str) -> ToolCatalog:
        with self._connect() as db:
            return self._catalog(db.execute("SELECT * FROM clients WHERE client_id=?", (client_id,)).fetchone())

    def replace_tools(self, client_id: str, body: ToolRegistration) -> ToolCatalog:
        tools_json = json.dumps([tool.model_dump() for tool in body.tools], ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            # Full replacement is atomic. Identical retries do not advance the revision.
            result = db.execute("""UPDATE clients SET
                tools_revision=tools_revision + CASE WHEN tools_json != ? THEN 1 ELSE 0 END,
                tools_updated_at=CASE WHEN tools_json != ? THEN ? ELSE tools_updated_at END,
                tools_json=? WHERE client_id=?""", (tools_json, tools_json, now, tools_json, client_id))
            if result.rowcount == 0:
                raise ClientNotFound()
            return self._catalog(db.execute("SELECT * FROM clients WHERE client_id=?", (client_id,)).fetchone())
