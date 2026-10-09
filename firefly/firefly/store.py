"""SQLite storage for peers and messages. Thread-safe (one lock, one connection).

`version` increases on every write, so the UI can redraw only when
something actually changed.
"""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS peers (
    hash        TEXT PRIMARY KEY,      -- destination hash (hex)
    kind        TEXT NOT NULL,         -- lxmf | propagation | nomadnode
    name        TEXT,
    last_heard  REAL,
    hops        INTEGER,
    saved       INTEGER DEFAULT 0,
    stump       TEXT,                  -- Stump node name if it beacons as one
    stump_ver   TEXT,
    stamp_cost  INTEGER,
    extra       TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    peer        TEXT NOT NULL,
    outgoing    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    title       TEXT,
    ts          REAL NOT NULL,
    state       TEXT NOT NULL,         -- pending sending sent delivered stored failed received
    method      TEXT,                  -- opportunistic direct propagated
    lxm_hash    TEXT,
    rssi        REAL,
    snr         REAL,
    verified    INTEGER DEFAULT 1,     -- 0 = LXMF signature could not be validated
    attachments TEXT,                  -- short human description of fields we can't render
    unread      INTEGER DEFAULT 0,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS messages_peer ON messages(peer, ts);
CREATE INDEX IF NOT EXISTS messages_hash ON messages(lxm_hash);
CREATE TABLE IF NOT EXISTS blocked (
    hash        TEXT PRIMARY KEY,      -- LXMF address (hex)
    name        TEXT,                  -- the name they had when blocked, for the list
    ts          REAL
);
"""


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")    # fewer writes on the SD card
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.version = 0

    def _migrate(self):
        """Add columns introduced after a database was created; existing messages stay."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(messages)")}
        for name, kind in (("audio_mode", "INTEGER"), ("audio_path", "TEXT"), ("audio_secs", "REAL")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE messages ADD COLUMN {name} {kind}")
        self.db.commit()

    def _write(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            self.version += 1
            return cur

    def _read(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ---------------------------------------------------------------- peers
    def upsert_peer(self, hash_hex, kind, name=None, hops=None, heard=True, **extra):
        with self.lock:
            row = self.db.execute("SELECT hash FROM peers WHERE hash=?", (hash_hex,)).fetchone()
            now = time.time() if heard else None
            if row is None:
                self._write("INSERT INTO peers(hash, kind, name, last_heard, hops) VALUES (?,?,?,?,?)",
                            (hash_hex, kind, name, now, hops))
            else:
                sets, args = [], []
                if name:
                    sets.append("name=?"); args.append(name)
                if hops is not None:
                    sets.append("hops=?"); args.append(hops)
                if now:
                    sets.append("last_heard=?"); args.append(now)
                if sets:
                    self._write(f"UPDATE peers SET {', '.join(sets)} WHERE hash=?", (*args, hash_hex))
            for k, v in extra.items():
                if k in ("stump", "stump_ver", "stamp_cost", "saved", "extra"):
                    self._write(f"UPDATE peers SET {k}=? WHERE hash=?", (v, hash_hex))

    def peer(self, hash_hex):
        rows = self._read("SELECT * FROM peers WHERE hash=?", (hash_hex,))
        return rows[0] if rows else None

    def peers(self, kind="lxmf"):
        return self._read("SELECT * FROM peers WHERE kind=? ORDER BY saved DESC, last_heard DESC", (kind,))

    def set_saved(self, hash_hex, saved):
        self._write("UPDATE peers SET saved=? WHERE hash=?", (1 if saved else 0, hash_hex))

    def delete_peer(self, hash_hex):
        self._write("DELETE FROM peers WHERE hash=?", (hash_hex,))

    # ---------------------------------------------------------------- messages
    def add_message(self, peer, outgoing, content, state, ts=None, title="", method=None, lxm_hash=None,
                    rssi=None, snr=None, verified=True, attachments=None, unread=False,
                    audio_mode=None, audio_path=None, audio_secs=None):
        cur = self._write(
            "INSERT INTO messages(peer, outgoing, content, title, ts, state, method, lxm_hash, rssi, snr,"
            " verified, attachments, unread, audio_mode, audio_path, audio_secs)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (peer, 1 if outgoing else 0, content, title, ts or time.time(), state, method, lxm_hash,
             rssi, snr, 1 if verified else 0, attachments, 1 if unread else 0, audio_mode, audio_path, audio_secs))
        return cur.lastrowid

    def voice_notes(self, peer, limit=20):
        return self._read("SELECT * FROM messages WHERE peer=? AND audio_mode IS NOT NULL "
                          "ORDER BY ts DESC, id DESC LIMIT ?", (peer, limit))

    def has_message(self, lxm_hash):
        return bool(self._read("SELECT 1 FROM messages WHERE lxm_hash=?", (lxm_hash,)))

    def update_message(self, msg_id, **fields):
        allowed = {"state", "method", "lxm_hash", "reason"}
        sets = [(k, v) for k, v in fields.items() if k in allowed]
        if sets:
            self._write(f"UPDATE messages SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                        (*[v for _, v in sets], msg_id))

    def message(self, msg_id):
        rows = self._read("SELECT * FROM messages WHERE id=?", (msg_id,))
        return rows[0] if rows else None

    def messages(self, peer, limit=200):
        rows = self._read("SELECT * FROM messages WHERE peer=? ORDER BY ts DESC, id DESC LIMIT ?", (peer, limit))
        return rows[::-1]

    def mark_read(self, peer):
        with self.lock:
            if self.db.execute("SELECT 1 FROM messages WHERE peer=? AND unread=1", (peer,)).fetchone():
                self._write("UPDATE messages SET unread=0 WHERE peer=?", (peer,))

    def conversations(self):
        return self._read("""
            SELECT m.peer, m.content, m.ts, m.outgoing, m.state, m.audio_mode,
                   (SELECT COUNT(*) FROM messages u WHERE u.peer=m.peer AND u.unread=1) AS unread,
                   p.name, p.stump, p.hops
            FROM messages m LEFT JOIN peers p ON p.hash=m.peer
            WHERE m.id = (SELECT id FROM messages x WHERE x.peer=m.peer ORDER BY ts DESC, id DESC LIMIT 1)
            ORDER BY m.ts DESC""")

    # ---------------------------------------------------------------- deleting and blocking
    def delete_message(self, msg_id):
        """Removes one message. Returns the audio file paths it owned, for the caller to delete."""
        rows = self._read("SELECT audio_path FROM messages WHERE id=?", (msg_id,))
        self._write("DELETE FROM messages WHERE id=?", (msg_id,))
        return [r["audio_path"] for r in rows if r["audio_path"]]

    def delete_conversation(self, peer):
        """Removes every message with this peer, and the contact. Returns audio file paths."""
        rows = self._read("SELECT audio_path FROM messages WHERE peer=? AND audio_path IS NOT NULL", (peer,))
        with self.lock:
            self.db.execute("DELETE FROM messages WHERE peer=?", (peer,))
            self.db.execute("DELETE FROM peers WHERE hash=?", (peer,))
            self.db.commit()
            self.version += 1
        return [r["audio_path"] for r in rows]

    def block(self, peer, name=None):
        self._write("INSERT OR REPLACE INTO blocked(hash, name, ts) VALUES (?,?,?)", (peer, name, time.time()))

    def unblock(self, peer):
        self._write("DELETE FROM blocked WHERE hash=?", (peer,))

    def blocked(self):
        return self._read("SELECT * FROM blocked ORDER BY ts DESC")

    def is_blocked(self, peer):
        return bool(self._read("SELECT 1 FROM blocked WHERE hash=?", (peer,)))

    def unread_total(self):
        return self._read("SELECT COUNT(*) AS n FROM messages WHERE unread=1")[0]["n"]

    def pending_outgoing(self):
        return self._read("SELECT * FROM messages WHERE outgoing=1 AND state IN ('pending','stamping','sending')")
