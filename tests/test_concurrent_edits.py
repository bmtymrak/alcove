from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from conftest import document, json_request
from django.db import connections
from django.test import Client


@pytest.mark.django_db(transaction=True)
def test_simultaneous_edits_save_one_revision_and_report_conflicts(signed_in):
    original = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Original."),
        },
    ).json()
    path = f"/api/v1/notes/{original['id']}/"
    ready = Barrier(4)

    def save(number):
        client = Client(enforce_csrf_checks=True)
        for name, morsel in signed_in.cookies.items():
            client.cookies[name] = morsel.value
        try:
            ready.wait(timeout=10)
            return json_request(
                client,
                "patch",
                path,
                {
                    "content": document(f"Concurrent thought {number}."),
                    "revision": 1,
                },
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(save, range(4)))
    assert sorted(response.status_code for response in responses) == [
        200,
        409,
        409,
        409,
    ]
    winner = next(
        response.json() for response in responses if response.status_code == 200
    )
    assert signed_in.get(path).json() == winner
    assert winner["revision"] == 2
