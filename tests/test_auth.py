import pytest
from conftest import document, json_request
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client


def test_provisioned_owner_can_sign_in_and_sign_out(db, monkeypatch):
    monkeypatch.setenv("ALCOVE_OWNER_PASSWORD", "Secluded-reading-472!")
    call_command("provision_owner", "reader", no_input=True)
    client = Client(enforce_csrf_checks=True)
    assert client.get("/").status_code == 302
    login = client.get("/login/")
    assert login.status_code == 200
    csrf = client.cookies["csrftoken"].value
    response = client.post(
        "/login/",
        {
            "username": "reader",
            "password": "Secluded-reading-472!",
            "csrfmiddlewaretoken": csrf,
        },
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/notes/").json()["count"] == 0
    logout = client.post(
        "/logout/",
        {"csrfmiddlewaretoken": client.cookies["csrftoken"].value},
    )
    assert logout.status_code == 302
    assert logout["Clear-Site-Data"] == '"storage"'
    assert client.get("/").status_code == 302
    assert client.get("/api/v1/notes/").status_code == 403


def test_login_requires_csrf_and_bad_credentials_do_not_authenticate(db):
    client = Client(enforce_csrf_checks=True)
    assert (
        client.post(
            "/login/",
            {
                "username": "reader",
                "password": "wrong",
            },
        ).status_code
        == 403
    )
    client.get("/login/")
    response = client.post(
        "/login/",
        {
            "username": "reader",
            "password": "wrong",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 200
    assert "Please enter a correct username and password" in response.content.decode()
    assert client.get("/").status_code == 302


def test_every_content_route_and_the_schema_require_authentication(signed_in):
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Private."),
        },
    ).json()
    anonymous = Client()
    for path in [
        "/",
        "/notes/new/",
        f"/notes/{note['id']}/",
        f"/notes/{note['id']}/edit/",
    ]:
        assert anonymous.get(path).status_code == 302
    for path in ["/api/v1/schema/", "/api/v1/notes/", f"/api/v1/notes/{note['id']}/"]:
        assert anonymous.get(path).status_code == 403
    assert (
        json_request(
            anonymous_with_csrf(),
            "post",
            "/api/v1/notes/",
            {
                "content": document("Intrusion."),
            },
        ).status_code
        == 403
    )
    assert (
        anonymous.patch(
            f"/api/v1/notes/{note['id']}/",
            {"content": document("Intrusion."), "revision": 1},
            content_type="application/json",
        ).status_code
        == 403
    )
    assert signed_in.get("/api/v1/notes/").json()["results"] == [note]
    assert anonymous.get("/register/").status_code == 404


def anonymous_with_csrf():
    client = Client(enforce_csrf_checks=True)
    client.get("/login/")
    return client


def test_csrf_protects_every_unsafe_authenticated_path(signed_in):
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Keep private."),
        },
    ).json()
    assert signed_in.post("/notes/new/", {"content": "Intrusion."}).status_code == 403
    assert (
        signed_in.post(
            f"/notes/{note['id']}/edit/",
            {
                "content": "Intrusion.",
                "revision": 1,
            },
        ).status_code
        == 403
    )
    assert (
        signed_in.post(
            "/api/v1/notes/",
            {
                "content": document("Intrusion."),
            },
            content_type="application/json",
        ).status_code
        == 403
    )
    response = signed_in.patch(
        f"/api/v1/notes/{note['id']}/",
        {
            "content": document("Intrusion."),
            "revision": 1,
        },
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert signed_in.post("/logout/").status_code == 403
    assert signed_in.get("/logout/").status_code == 405
    assert signed_in.get("/api/v1/notes/").json()["results"] == [note]


def test_logout_revokes_the_old_session_and_private_responses_are_not_cached(signed_in):
    stolen_cookie = signed_in.cookies["sessionid"].value
    for path in ["/", "/notes/new/", "/api/v1/notes/"]:
        response = signed_in.get(path)
        assert "no-store" in response["Cache-Control"]
    assert (
        signed_in.post(
            "/logout/",
            {
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        ).status_code
        == 302
    )
    replay = Client()
    replay.cookies["sessionid"] = stolen_cookie
    assert replay.get("/").status_code == 302
    assert replay.get("/api/v1/notes/").status_code == 403


def test_login_cannot_redirect_the_owner_to_another_origin(owner):
    client = anonymous_with_csrf()
    response = client.post(
        "/login/",
        {
            "username": "reader",
            "password": "Secluded-reading-472!",
            "next": "https://untrusted.example/",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    assert response["Location"] == "/"


def test_owner_provisioning_is_repeatable_without_resetting_the_password(
    db, monkeypatch
):
    monkeypatch.setenv("ALCOVE_OWNER_PASSWORD", "Secluded-reading-472!")
    call_command("provision_owner", "reader", no_input=True)
    monkeypatch.setenv("ALCOVE_OWNER_PASSWORD", "Changed-password-359!")
    call_command("provision_owner", "reader", no_input=True)
    client = Client()
    assert client.login(username="reader", password="Secluded-reading-472!")
    assert client.get("/").status_code == 200
    with pytest.raises(CommandError, match="owner already exists"):
        call_command("provision_owner", "another", no_input=True)


def test_weak_owner_password_does_not_leave_a_partly_provisioned_account(
    db, monkeypatch
):
    monkeypatch.setenv("ALCOVE_OWNER_PASSWORD", "password")
    with pytest.raises(CommandError):
        call_command("provision_owner", "reader", no_input=True)
    monkeypatch.setenv("ALCOVE_OWNER_PASSWORD", "Secluded-reading-472!")
    call_command("provision_owner", "reader", no_input=True)
    client = Client()
    assert client.login(username="reader", password="Secluded-reading-472!")
    assert client.get("/").status_code == 200


def test_an_account_without_a_collection_is_not_given_access(owner):
    User.objects.create_user("unprovisioned", password="Different-reading-782!")
    client = Client()
    assert client.login(username="unprovisioned", password="Different-reading-782!")
    assert client.get("/").status_code == 404
    assert client.get("/api/v1/notes/").status_code == 404
