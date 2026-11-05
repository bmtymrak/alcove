import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

from alcove.models import Collection

PASSWORD = "Secluded-reading-472!"


@pytest.fixture(scope="session")
def django_db_modify_db_settings(tmp_path_factory):
    settings.DATABASES["default"]["TEST"]["NAME"] = str(
        tmp_path_factory.mktemp("sqlite") / "test.sqlite3"
    )


@pytest.fixture
def owner(db):
    user = User.objects.create_user(username="reader", password=PASSWORD)
    Collection.objects.create(owner=user)
    return user


@pytest.fixture
def signed_in(owner):
    client = Client(enforce_csrf_checks=True)
    client.get("/login/")
    response = client.post(
        "/login/",
        {
            "username": owner.username,
            "password": PASSWORD,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    return client


def document(text):
    return {"version": 1, "format": "plain-text", "text": text}


def json_request(client, method, path, payload):
    return getattr(client, method)(
        path,
        payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
