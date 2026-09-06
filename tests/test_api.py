import uuid

from tests.conftest import SLOT_A, SLOT_B, SLOT_C, order_payload


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_register_is_idempotent_for_same_device(client, make_student):
    s = make_student()
    r = client.post(
        "/api/v1/register",
        json={
            "student_id": s.id,
            "device_key": s.device_key,
            "contact_type": "cu_email",
            "contact_value": "student@edu.centraluniversity.ru",
        },
    )
    assert r.status_code == 201
    assert r.json()["contact_type"] == "cu_email"


def test_second_browser_gets_its_own_device_key(client, make_student):
    """Chrome и Firefox не делят storage.local — ключей у студента несколько."""
    s = make_student()
    second_key = uuid.uuid4().hex + uuid.uuid4().hex

    r = client.post(
        "/api/v1/register",
        json={
            "student_id": s.id,
            "device_key": second_key,
            "contact_type": "telegram",
            "contact_value": "@tester",
        },
    )
    assert r.status_code == 201

    second = {"Authorization": f"Bearer {second_key}", "X-Student-Id": s.id}
    assert client.get("/api/v1/orders", headers=second).status_code == 200
    # Первый браузер продолжает работать.
    assert client.get("/api/v1/orders", headers=s.headers).status_code == 200
    assert client.get("/api/v1/me/devices", headers=second).json() == {"devices": 2}


def test_orders_are_shared_between_devices(client, make_student):
    s = make_student()
    second_key = uuid.uuid4().hex + uuid.uuid4().hex
    client.post(
        "/api/v1/register",
        json={
            "student_id": s.id,
            "device_key": second_key,
            "contact_type": "telegram",
            "contact_value": "@tester",
        },
    )
    second = {"Authorization": f"Bearer {second_key}", "X-Student-Id": s.id}

    client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    assert len(client.get("/api/v1/orders", headers=second).json()["orders"]) == 1


def test_repeat_registration_does_not_duplicate_key(client, make_student):
    s = make_student()
    client.post(
        "/api/v1/register",
        json={
            "student_id": s.id,
            "device_key": s.device_key,
            "contact_type": "telegram",
            "contact_value": "@tester",
        },
    )
    assert client.get("/api/v1/me/devices", headers=s.headers).json() == {"devices": 1}


def test_device_keys_are_evicted_past_the_limit(client, make_student, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_device_keys_per_student", 2)

    s = make_student()
    keys = [uuid.uuid4().hex + uuid.uuid4().hex for _ in range(2)]
    for key in keys:
        client.post(
            "/api/v1/register",
            json={
                "student_id": s.id,
                "device_key": key,
                "contact_type": "telegram",
                "contact_value": "@tester",
            },
        )

    newest = {"Authorization": f"Bearer {keys[-1]}", "X-Student-Id": s.id}
    assert client.get("/api/v1/me/devices", headers=newest).json() == {"devices": 2}
    # Самый старый ключ вытеснен.
    assert client.get("/api/v1/orders", headers=s.headers).status_code == 401


def test_wrong_device_key_is_rejected(client, make_student):
    s = make_student()
    bad = {"Authorization": "Bearer " + "0" * 40, "X-Student-Id": s.id}
    assert client.get("/api/v1/orders", headers=bad).status_code == 401


def test_missing_headers_rejected(client):
    assert client.get("/api/v1/orders").status_code == 401


def test_update_contact(client, make_student):
    s = make_student()
    r = client.put(
        "/api/v1/me/contact",
        headers=s.headers,
        json={"contact_type": "custom", "contact_value": "vk.com/tester"},
    )
    assert r.status_code == 200
    assert r.json()["contact_value"] == "vk.com/tester"


def test_create_order_without_counterpart_stays_open(client, make_student):
    s = make_student()
    r = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["match"] is None


def test_duplicate_order_rejected(client, make_student):
    s = make_student()
    client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    r = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    assert r.status_code == 409


def test_cancelled_order_can_be_recreated(client, make_student):
    """Отменённый заказ не должен навсегда занимать слот из-за уникального индекса."""
    s = make_student()
    created = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    dropped = client.delete(f"/api/v1/orders/{created.json()['id']}", headers=s.headers)
    assert dropped.status_code == 204

    again = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    assert again.status_code == 201
    assert again.json()["status"] == "open"

    orders = client.get("/api/v1/orders", headers=s.headers).json()["orders"]
    assert len(orders) == 1


def test_recreated_order_matches_again(client, make_student):
    a = make_student()
    b = make_student()
    created = client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    client.delete(f"/api/v1/orders/{created.json()['id']}", headers=a.headers)

    client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))
    again = client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    assert again.json()["status"] == "matched"


def test_completed_order_can_be_recreated(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    created = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))
    client.post(f"/api/v1/matches/{created.json()['match']['id']}/confirm", headers=a.headers)

    again = client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    assert again.status_code == 201
    assert again.json()["status"] == "open"


def test_self_swap_rejected(client, make_student):
    s = make_student()
    r = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_A))
    assert r.status_code == 422


def test_mutual_orders_match_and_reveal_contacts(client, make_student):
    a = make_student(contact_type="telegram", contact_value="@alpha")
    b = make_student(contact_type="cu_email", contact_value="b@edu.centraluniversity.ru")

    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    second = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))

    # Второй заказ сватается сразу же, в том же ответе.
    assert second.json()["status"] == "matched"
    assert second.json()["match"]["counterpart_contact_value"] == "@alpha"

    mine = client.get("/api/v1/orders", headers=a.headers).json()["orders"][0]
    assert mine["status"] == "matched"
    assert mine["match"]["counterpart_contact_type"] == "cu_email"
    assert mine["match"]["counterpart_contact_value"] == "b@edu.centraluniversity.ru"


def test_no_match_across_different_rows(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    r = client.post(
        "/api/v1/orders",
        headers=b.headers,
        json=order_payload(SLOT_B, SLOT_A, event_row_number=2),
    )
    assert r.json()["status"] == "open"


def test_no_match_when_wanted_slots_do_not_mirror(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    r = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_C, SLOT_A))
    assert r.json()["status"] == "open"


def test_contacts_hidden_until_match(client, make_student):
    a = make_student(contact_value="@alpha")
    make_student(contact_value="@beta")
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    orders = client.get("/api/v1/orders", headers=a.headers).json()["orders"]
    assert orders[0]["match"] is None


def test_confirm_closes_both_orders(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    created = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))
    match_id = created.json()["match"]["id"]

    assert client.post(f"/api/v1/matches/{match_id}/confirm", headers=a.headers).status_code == 204
    for s in (a, b):
        orders = client.get("/api/v1/orders", headers=s.headers).json()["orders"]
        assert orders[0]["status"] == "completed"


def test_decline_returns_both_to_search_and_does_not_rematch(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    created = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))
    match_id = created.json()["match"]["id"]

    assert client.post(f"/api/v1/matches/{match_id}/decline", headers=b.headers).status_code == 204

    for s in (a, b):
        order = client.get("/api/v1/orders", headers=s.headers).json()["orders"][0]
        assert order["status"] == "open"
        assert order["match"] is None

    # Фоновой проход не должен свести ту же пару повторно.
    from app.db import SessionLocal
    from app.matching import run_sweep

    db = SessionLocal()
    try:
        assert run_sweep(db) == 0
    finally:
        db.close()


def test_cancel_matched_order_frees_counterpart(client, make_student):
    a = make_student()
    b = make_student()
    first = client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))

    deleted = client.delete(f"/api/v1/orders/{first.json()['id']}", headers=a.headers)
    assert deleted.status_code == 204

    b_orders = client.get("/api/v1/orders", headers=b.headers).json()["orders"]
    assert b_orders[0]["status"] == "open"
    assert b_orders[0]["match"] is None

    # Отменённый заказ из выдачи пропадает.
    assert client.get("/api/v1/orders", headers=a.headers).json()["orders"] == []


def test_cannot_cancel_someone_elses_order(client, make_student):
    a = make_student()
    b = make_student()
    created = client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    r = client.delete(f"/api/v1/orders/{created.json()['id']}", headers=b.headers)
    assert r.status_code == 404


def test_sweep_matches_pair_left_open(client, make_student):
    """Пара, которую матчер должен найти фоновым проходом, а не при создании."""
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_B))
    created = client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_A))

    # Разводим пару так, будто обмен сорвался, и возвращаем оба заказа в поиск
    # вручную — declined-матч помешал бы повторному сватовству.
    from app.db import SessionLocal
    from app.matching import run_sweep
    from app.models import ORDER_OPEN, Match, Order

    db = SessionLocal()
    try:
        match = db.get(Match, created.json()["match"]["id"])
        for order_id in (match.order_a_id, match.order_b_id):
            db.get(Order, order_id).status = ORDER_OPEN
        db.delete(match)
        db.commit()

        assert run_sweep(db) == 1
    finally:
        db.close()

    a_orders = client.get("/api/v1/orders", headers=a.headers).json()["orders"]
    assert a_orders[0]["status"] == "matched"


def test_sweep_leaves_non_mirrored_orders_alone(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_C))
    client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_B, SLOT_C))

    from app.db import SessionLocal
    from app.matching import run_sweep

    db = SessionLocal()
    try:
        assert run_sweep(db) == 0
    finally:
        db.close()


def test_demand_counts_open_offers(client, make_student):
    a = make_student()
    b = make_student()
    client.post("/api/v1/orders", headers=a.headers, json=order_payload(SLOT_A, SLOT_C))
    client.post("/api/v1/orders", headers=b.headers, json=order_payload(SLOT_A, SLOT_B))

    r = client.get(
        "/api/v1/demand",
        headers=a.headers,
        params={"wanted_event_id": [SLOT_A, SLOT_B]},
    )
    counts = {d["wanted_event_id"]: d["offers"] for d in r.json()}
    assert counts[SLOT_A] == 2  # оба готовы отдать SLOT_A
    assert counts[SLOT_B] == 0


def test_open_order_limit(client, make_student, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_open_orders_per_student", 1)

    s = make_student()
    client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_B))
    r = client.post("/api/v1/orders", headers=s.headers, json=order_payload(SLOT_A, SLOT_C))
    assert r.status_code == 429
