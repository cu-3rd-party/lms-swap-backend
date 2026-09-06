import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Настройки читаются на импорте app.db, поэтому подменяем URL до него.
_tmpdir = tempfile.mkdtemp(prefix="lms-swap-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmpdir, 'test.db').as_posix()}"
os.environ["MATCH_INTERVAL_SECONDS"] = "3600"  # фоновой цикл в тестах не нужен

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

# Слоты семинара 1 по курсу 1245 — тот же вид идентификаторов, что у LMS.
SLOT_A = "08df0286-568a-4c48-4c46-0d000105ac16"
SLOT_B = "08df0286-553e-0875-4c46-0d000105ac10"
SLOT_C = "08df02af-450f-b7fe-ee51-4e0001023914"


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class Student:
    """Зарегистрированный студент с готовыми заголовками."""

    def __init__(self, client, contact_type="telegram", contact_value="@tester"):
        self.id = str(uuid.uuid4())
        self.device_key = uuid.uuid4().hex + uuid.uuid4().hex
        r = client.post(
            "/api/v1/register",
            json={
                "student_id": self.id,
                "device_key": self.device_key,
                "contact_type": contact_type,
                "contact_value": contact_value,
            },
        )
        assert r.status_code == 201, r.text
        self.headers = {
            "Authorization": f"Bearer {self.device_key}",
            "X-Student-Id": self.id,
        }


@pytest.fixture
def make_student(client):
    def _make(**kwargs):
        return Student(client, **kwargs)

    return _make


def order_payload(offered: str, wanted: str, **overrides):
    payload = {
        "course_id": 1245,
        "course_name": "Машинное обучение (Machine Learning)",
        "event_type": "seminar",
        "event_row_number": 1,
        "offered_event_id": offered,
        "offered_label": "Пятница, 14:30 - 15:50, Хорец Даниил",
        "wanted_event_id": wanted,
        "wanted_label": "Пятница, 10:00 - 11:20, Хорец Даниил",
    }
    payload.update(overrides)
    return payload
