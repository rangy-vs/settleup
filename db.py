"""SQLite persistence (stdlib only). One short-lived connection per request."""
from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS members(group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL, PRIMARY KEY (group_id, name));
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    description TEXT NOT NULL, payer TEXT NOT NULL, cents INTEGER NOT NULL CHECK(cents > 0),
    split_type TEXT NOT NULL, split TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settlements(id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    payer TEXT NOT NULL, payee TEXT NOT NULL, cents INTEGER NOT NULL CHECK(cents > 0), created TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init(path: str | Path) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)


def new_group(con, name: str, members: list[str]) -> str:
    gid = secrets.token_urlsafe(6)          # unguessable link token: the group "password"
    con.execute("INSERT INTO groups(id, name) VALUES (?, ?)", (gid, name))
    con.executemany("INSERT INTO members VALUES (?, ?)", [(gid, m) for m in members])
    con.commit()
    return gid


def group_exists(con, gid: str) -> bool:
    return con.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone() is not None


def load_group(con, gid: str) -> dict | None:
    g = con.execute("SELECT id, name FROM groups WHERE id=?", (gid,)).fetchone()
    if not g:
        return None
    return {
        "id": g["id"], "name": g["name"],
        "members": [r["name"] for r in con.execute("SELECT name FROM members WHERE group_id=? ORDER BY rowid", (gid,))],
        "expenses": [{"id": r["id"], "description": r["description"], "payer": r["payer"], "cents": r["cents"],
                      "split_type": r["split_type"], "split": json.loads(r["split"])}
                     for r in con.execute("SELECT * FROM expenses WHERE group_id=? ORDER BY id", (gid,))],
        "settlements": [{"id": r["id"], "payer": r["payer"], "payee": r["payee"], "cents": r["cents"]}
                        for r in con.execute("SELECT * FROM settlements WHERE group_id=? ORDER BY id", (gid,))],
    }
