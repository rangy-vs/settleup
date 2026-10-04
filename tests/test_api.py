import pytest
from fastapi.testclient import TestClient

from settleup.app import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "t.db")))


def make_group(c, members=("alice", "bob", "carol")):
    r = c.post("/api/groups", json={"name": "Apt 4B", "members": list(members)})
    assert r.status_code == 201
    return r.json()["id"]


def test_create_and_read_group(client):
    gid = make_group(client)
    g = client.get(f"/api/groups/{gid}").json()
    assert g["name"] == "Apt 4B" and g["members"] == ["alice", "bob", "carol"]
    assert g["balances"] == {"alice": 0, "bob": 0, "carol": 0} and g["transfers"] == []


def test_group_ids_are_unguessable_and_unique(client):
    ids = {make_group(client) for _ in range(20)}
    assert len(ids) == 20 and all(len(i) >= 8 for i in ids)


def test_unknown_group_404(client):
    assert client.get("/api/groups/nope").status_code == 404
    assert client.get("/api/groups/nope/balances").status_code == 404


def test_equal_expense_and_transfers(client):
    gid = make_group(client)
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "Groceries", "payer": "alice", "amount_cents": 3000})
    assert r.status_code == 201 and r.json()["owed"] == {"alice": 1000, "bob": 1000, "carol": 1000}
    b = client.get(f"/api/groups/{gid}/balances").json()
    assert b["balances"] == {"alice": 2000, "bob": -1000, "carol": -1000}
    assert sorted((t["from"], t["to"], t["cents"]) for t in b["transfers"]) == [("bob", "alice", 1000), ("carol", "alice", 1000)]


def test_split_among_subset_and_odd_cents(client):
    gid = make_group(client)
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "Pizza", "payer": "bob", "amount_cents": 1000,
                                                         "participants": ["alice", "bob", "carol"]})
    assert sum(r.json()["owed"].values()) == 1000


def test_shares_and_exact_splits(client):
    gid = make_group(client)
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "Rent", "payer": "alice", "amount_cents": 100000,
                                                         "split_type": "shares", "shares": {"alice": 2, "bob": 1, "carol": 1}})
    assert r.json()["owed"] == {"alice": 50000, "bob": 25000, "carol": 25000}
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "Dinner", "payer": "bob", "amount_cents": 5000,
                                                         "split_type": "exact", "amounts": {"alice": 1000, "carol": 4000}})
    assert r.status_code == 201


def test_exact_split_mismatch_rejected(client):
    gid = make_group(client)
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "x", "payer": "alice", "amount_cents": 5000,
                                                         "split_type": "exact", "amounts": {"alice": 1, "bob": 1}})
    assert r.status_code == 400 and "sum" in r.json()["detail"]


def test_unknown_member_in_expense_rejected(client):
    gid = make_group(client)
    r = client.post(f"/api/groups/{gid}/expenses", json={"description": "x", "payer": "mallory", "amount_cents": 100})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [
    {"description": "x", "payer": "alice", "amount_cents": 0},
    {"description": "x", "payer": "alice", "amount_cents": -5},
    {"description": "", "payer": "alice", "amount_cents": 100},
    {"description": "x", "payer": "alice", "amount_cents": 10**12},
    {"description": "x", "payer": "alice", "amount_cents": 12.5},
    {"description": "x", "payer": "alice", "amount_cents": 100, "split_type": "bogus"},
])
def test_invalid_expense_payloads_422(client, bad):
    gid = make_group(client)
    assert client.post(f"/api/groups/{gid}/expenses", json=bad).status_code == 422


def test_settlement_flow_clears_debt(client):
    gid = make_group(client)
    client.post(f"/api/groups/{gid}/expenses", json={"description": "x", "payer": "alice", "amount_cents": 3000})
    assert client.post(f"/api/groups/{gid}/settlements", json={"payer": "bob", "payee": "alice", "amount_cents": 1000}).status_code == 201
    assert client.post(f"/api/groups/{gid}/settlements", json={"payer": "carol", "payee": "alice", "amount_cents": 1000}).status_code == 201
    b = client.get(f"/api/groups/{gid}/balances").json()
    assert set(b["balances"].values()) == {0} and b["transfers"] == []


def test_settlement_validation(client):
    gid = make_group(client)
    assert client.post(f"/api/groups/{gid}/settlements", json={"payer": "bob", "payee": "bob", "amount_cents": 5}).status_code == 400
    assert client.post(f"/api/groups/{gid}/settlements", json={"payer": "bob", "payee": "zed", "amount_cents": 5}).status_code == 400


def test_delete_expense(client):
    gid = make_group(client)
    eid = client.post(f"/api/groups/{gid}/expenses", json={"description": "x", "payer": "alice", "amount_cents": 900}).json()["id"]
    assert client.delete(f"/api/groups/{gid}/expenses/{eid}").status_code == 204
    assert client.delete(f"/api/groups/{gid}/expenses/{eid}").status_code == 404
    assert client.get(f"/api/groups/{gid}/balances").json()["transfers"] == []


def test_cannot_touch_another_groups_expense(client):
    g1, g2 = make_group(client), make_group(client)
    eid = client.post(f"/api/groups/{g1}/expenses", json={"description": "x", "payer": "alice", "amount_cents": 900}).json()["id"]
    assert client.delete(f"/api/groups/{g2}/expenses/{eid}").status_code == 404
    assert len(client.get(f"/api/groups/{g1}").json()["expenses"]) == 1


def test_add_member_and_duplicates(client):
    gid = make_group(client, ("alice", "bob"))
    assert client.post(f"/api/groups/{gid}/members", json={"name": "dave"}).status_code == 201
    assert client.post(f"/api/groups/{gid}/members", json={"name": "DAVE"}).status_code == 409      # case-insensitive
    assert client.post("/api/groups", json={"name": "g", "members": ["a", "A"]}).status_code == 422


def test_sql_injection_attempt_is_inert(client):
    gid = make_group(client)
    evil = "x'); DROP TABLE expenses;--"
    assert client.post(f"/api/groups/{gid}/expenses", json={"description": evil, "payer": "alice", "amount_cents": 100}).status_code == 201
    g = client.get(f"/api/groups/{gid}").json()
    assert g["expenses"][0]["description"] == evil          # stored verbatim as data, tables intact


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "settleup" in r.text and "textContent" in r.text


def test_data_persists_across_app_instances(tmp_path):
    path = str(tmp_path / "p.db")
    c1 = TestClient(create_app(path))
    gid = make_group(c1)
    c1.post(f"/api/groups/{gid}/expenses", json={"description": "x", "payer": "alice", "amount_cents": 300})
    c2 = TestClient(create_app(path))                     # "restart"
    assert c2.get(f"/api/groups/{gid}/balances").json()["balances"]["alice"] == 200
