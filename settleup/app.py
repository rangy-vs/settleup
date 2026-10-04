"""FastAPI app. `create_app(db_path)` is a factory so tests can use an isolated database.

Security model: no accounts. A group's random link token is its only credential (like a shared
doc link), so anyone with the link can edit. All input is length/range validated and every SQL
statement is parameterised."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from . import db
from .ledger import Expense, LedgerError, Settlement, balances, simplify

MAX_CENTS = 10**9
Name = Field(min_length=1, max_length=40)


def _clean(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("must not be blank")
    return v


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    members: list[str] = Field(min_length=1, max_length=30)

    @field_validator("members")
    @classmethod
    def unique_members(cls, v):
        v = [_clean(m)[:40] for m in v]
        if len({m.lower() for m in v}) != len(v):
            raise ValueError("member names must be unique (case-insensitive)")
        return v

    @field_validator("name")
    @classmethod
    def clean_name(cls, v): return _clean(v)


class MemberIn(BaseModel):
    name: str = Name

    @field_validator("name")
    @classmethod
    def clean_name(cls, v): return _clean(v)


class ExpenseIn(BaseModel):
    description: str = Field(min_length=1, max_length=120)
    payer: str = Name
    amount_cents: int = Field(gt=0, le=MAX_CENTS)
    split_type: str = Field(default="equal", pattern="^(equal|shares|exact)$")
    participants: list[str] | None = None          # equal
    shares: dict[str, int] | None = None           # shares: {name: weight}
    amounts: dict[str, int] | None = None          # exact:  {name: cents}


class SettlementIn(BaseModel):
    payer: str = Name
    payee: str = Name
    amount_cents: int = Field(gt=0, le=MAX_CENTS)


def create_app(db_path: str | None = None) -> FastAPI:
    path = db_path or os.environ.get("SETTLEUP_DB", "settleup.db")
    db.init(path)
    app = FastAPI(title="settleup", version="1.0.0")
    static = Path(__file__).parent / "static"

    def get_group(con, gid: str) -> dict:
        g = db.load_group(con, gid)
        if not g:
            raise HTTPException(404, "group not found")
        return g

    def summarize(g: dict) -> dict:
        exps = [Expense(e["payer"], e["cents"], e["split_type"], e["split"]) for e in g["expenses"]]
        sets = [Settlement(s["payer"], s["payee"], s["cents"]) for s in g["settlements"]]
        bal = balances(g["members"], exps, sets)
        return {"balances": bal, "transfers": [{"from": a, "to": b, "cents": c} for a, b, c in simplify(bal)]}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    @app.post("/api/groups", status_code=201)
    def create_group(body: GroupIn):
        with db.connect(path) as con:
            gid = db.new_group(con, body.name, body.members)
            return db.load_group(con, gid)

    @app.get("/api/groups/{gid}")
    def read_group(gid: str):
        with db.connect(path) as con:
            g = get_group(con, gid)
            return {**g, **summarize(g)}

    @app.post("/api/groups/{gid}/members", status_code=201)
    def add_member(gid: str, body: MemberIn):
        with db.connect(path) as con:
            g = get_group(con, gid)
            if len(g["members"]) >= 30:
                raise HTTPException(400, "group is limited to 30 members")
            if body.name.lower() in {m.lower() for m in g["members"]}:
                raise HTTPException(409, "member already exists")
            con.execute("INSERT INTO members VALUES (?, ?)", (gid, body.name))
            con.commit()
            return {"members": g["members"] + [body.name]}

    @app.post("/api/groups/{gid}/expenses", status_code=201)
    def add_expense(gid: str, body: ExpenseIn):
        with db.connect(path) as con:
            g = get_group(con, gid)
            if body.split_type == "equal":
                split = {m: 1 for m in (body.participants or g["members"])}
            elif body.split_type == "shares":
                split = body.shares or {}
            else:
                split = body.amounts or {}
            exp = Expense(body.payer, body.amount_cents, body.split_type, split)
            try:
                exp.owed()
                balances(g["members"], [exp])          # validates every name is a real member
            except LedgerError as e:
                raise HTTPException(400, str(e))
            cur = con.execute("INSERT INTO expenses(group_id, description, payer, cents, split_type, split) VALUES (?,?,?,?,?,?)",
                              (gid, " ".join(body.description.split()), body.payer, body.amount_cents,
                               body.split_type, json.dumps(split)))
            con.commit()
            return {"id": cur.lastrowid, "owed": exp.owed()}

    @app.delete("/api/groups/{gid}/expenses/{eid}", status_code=204)
    def delete_expense(gid: str, eid: int):
        with db.connect(path) as con:
            get_group(con, gid)
            if con.execute("DELETE FROM expenses WHERE id=? AND group_id=?", (eid, gid)).rowcount == 0:
                raise HTTPException(404, "expense not found")
            con.commit()

    @app.post("/api/groups/{gid}/settlements", status_code=201)
    def add_settlement(gid: str, body: SettlementIn):
        with db.connect(path) as con:
            g = get_group(con, gid)
            if body.payer == body.payee:
                raise HTTPException(400, "payer and payee must differ")
            if not {body.payer, body.payee} <= set(g["members"]):
                raise HTTPException(400, "unknown member")
            cur = con.execute("INSERT INTO settlements(group_id, payer, payee, cents) VALUES (?,?,?,?)",
                              (gid, body.payer, body.payee, body.amount_cents))
            con.commit()
            return {"id": cur.lastrowid}

    @app.get("/api/groups/{gid}/balances")
    def read_balances(gid: str):
        with db.connect(path) as con:
            return summarize(get_group(con, gid))

    return app


app = create_app() if os.environ.get("SETTLEUP_AUTOCREATE") else None
