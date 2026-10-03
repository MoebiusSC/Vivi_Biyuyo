"""SQLite is authoritative: inbox acknowledgement, state and effects commit together."""

import json
import sqlite3


class Journal:
    def __init__(self, root):
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "journal.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY, received INTEGER, payload TEXT, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT);
            CREATE TABLE IF NOT EXISTS effects(id INTEGER PRIMARY KEY, inbox_id INTEGER, kind TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS seen(event_id TEXT PRIMARY KEY);
        """)
        self.active = None
        self.pending = []
        self.event_id = None

    def load(self):
        row = self.db.execute("SELECT payload FROM snapshot WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def receive(self, raw, received):
        with self.db:
            cur = self.db.execute(
                "INSERT INTO inbox(received,payload) VALUES(?,?)",
                (received, json.dumps(raw, allow_nan=False)),
            )
        return cur.lastrowid

    def unprocessed(self):
        return self.db.execute("SELECT id FROM inbox WHERE done=0 ORDER BY id")

    def begin(self, ident):
        row = self.db.execute(
            "SELECT payload,received FROM inbox WHERE id=? AND done=0", (ident,)
        ).fetchone()
        if not row:
            return None
        self.active = ident
        self.pending = []
        self.event_id = None
        return json.loads(row[0]), row[1]

    def seen(self, ident):
        if self.db.execute("SELECT 1 FROM seen WHERE event_id=?", (ident,)).fetchone():
            return True
        self.event_id = ident
        return False

    def record(self, kind, payload):
        if self.active is not None:
            self.pending.append((kind, json.dumps(payload, allow_nan=False)))

    def save(self, state):
        if self.active is not None:
            return
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO snapshot VALUES(1,?)",
                (json.dumps(state, allow_nan=False),),
            )

    def finish(self, state):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO snapshot VALUES(1,?)",
                (json.dumps(state, allow_nan=False),),
            )
            self.db.executemany(
                "INSERT INTO effects(inbox_id,kind,payload) VALUES(?,?,?)",
                [(self.active, kind, payload) for kind, payload in self.pending],
            )
            if self.event_id:
                self.db.execute(
                    "INSERT OR IGNORE INTO seen VALUES(?)", (self.event_id,)
                )
            self.db.execute("UPDATE inbox SET done=1 WHERE id=?", (self.active,))
        self.active = None
        self.pending = []
        self.event_id = None

    def abort(self):
        self.active = None
        self.pending = []
        self.event_id = None

    def close(self):
        self.db.close()
