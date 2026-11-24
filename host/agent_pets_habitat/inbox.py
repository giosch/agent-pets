"""Durable local handoff between short-lived hook processes and the host."""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .adapters import Signal


def connect(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "activity.sqlite3", timeout=1)
    db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, observed REAL, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY, generation TEXT)")
    if not db.execute("SELECT 1 FROM identity WHERE id=1").fetchone():
        db.execute("INSERT OR IGNORE INTO identity VALUES (1, ?)", (uuid.uuid4().hex,))
    return db


def enqueue(directory, signal):
    with closing(connect(directory)) as db, db:
        payload = asdict(signal)
        if not signal.command_key:
            payload.pop("command_key")
        if not signal.progress_kind:
            for name in ("progress_done", "progress_total", "progress_kind"):
                payload.pop(name)
        db.execute("INSERT INTO events(observed,payload) VALUES (?,?)",
                   (time.time(), json.dumps(payload)))


def drain(directory, habitat):
    # Only the host drains. Its JSON checkpoint advances atomically with the session.
    with closing(connect(directory)) as db:
        generation, = db.execute("SELECT generation FROM identity").fetchone()
        db.commit()
        while True:
            rows = db.execute("SELECT id,observed,payload FROM events ORDER BY id LIMIT 64").fetchall()
            if not rows:
                return
            for number, observed, payload in rows:
                habitat.apply(Signal(**json.loads(payload)), (generation, number), observed)
            with db:
                db.execute("DELETE FROM events WHERE id <= ?", (rows[-1][0],))
