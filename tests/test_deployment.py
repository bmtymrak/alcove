"""Rehearse a clean deployment with the production launcher and real HTTP."""

import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from conftest import PASSWORD
from playwright.sync_api import Error, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def serve(package, env, certificate, key, playwright):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    with (
        (package / "server.log").open("w+") as log,
        subprocess.Popen(
            [
                "sh",
                "deploy/entrypoint.sh",
                "serve",
                "--certfile",
                str(certificate),
                "--keyfile",
                str(key),
            ],
            cwd=package,
            env={**env, "ALCOVE_BIND": f"127.0.0.1:{port}"},
            stdout=log,
            stderr=log,
        ) as process,
    ):
        probe = playwright.request.new_context(ignore_https_errors=True)
        try:
            deadline = time.monotonic() + 15
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    ready = probe.get(origin + "/healthz", timeout=1000).ok
                except Error:
                    ready = False
                if ready:
                    break
                time.sleep(0.1)
            else:
                log.seek(0)
                raise AssertionError(log.read())
            yield origin
        finally:
            probe.dispose()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


def sign_in(context, origin):
    page = context.new_page()
    page.goto(origin)
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page).to_have_url(origin + "/")
    return page


def assert_notes(page, origin, saved):
    for note_id, body in saved.items():
        response = page.request.get(f"{origin}/api/v1/notes/{note_id}/")
        assert response.ok and response.json()["plain_text"] == body
        page.goto(f"{origin}/notes/{note_id}/")
        expect(page.get_by_text(body, exact=True)).to_be_visible()


def open_trash(page, origin, note_id, body):
    assert page.request.get(f"{origin}/api/v1/notes/{note_id}/").status == 404
    page.get_by_role("link", name="Trash", exact=True).click()
    expect(page.get_by_text(body, exact=True)).to_be_visible()


@pytest.fixture
def production_browser():
    with sync_playwright() as playwright, playwright.chromium.launch() as browser:
        yield browser, playwright


def test_production_notes_survive_restart_and_isolated_recovery(
    tmp_path, production_browser
):
    browser, playwright = production_browser
    package = tmp_path / "package"
    package.mkdir()
    for directory in ("alcove", "config", "deploy"):
        shutil.copytree(
            ROOT / directory,
            package / directory,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    shutil.copyfile(ROOT / "manage.py", package / "manage.py")
    storage = tmp_path / "storage"
    storage.mkdir()
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    backup = tmp_path / "backup.sqlite3"
    env = {
        **os.environ,
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
        "ALCOVE_DEBUG": "0",
        "ALCOVE_SECRET_KEY": secrets.token_hex(48),
        "ALCOVE_ALLOWED_HOSTS": "127.0.0.1",
        "ALCOVE_DATABASE": str(storage / "alcove.sqlite3"),
        "ALCOVE_TRUST_PROXY_HTTPS": "0",
    }

    def manage(*args, settings=env, check=True):
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=package,
            env=settings,
            capture_output=True,
            text=True,
            check=check,
            timeout=15,
        )

    certificate, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-out",
            str(certificate),
            "-keyout",
            str(key),
        ],
        check=True,
        capture_output=True,
    )
    manage("collectstatic", "--noinput")
    with serve(package, env, certificate, key, playwright) as origin:
        manage(
            "provision_owner",
            "reader",
            "--no-input",
            settings={**env, "ALCOVE_OWNER_PASSWORD": PASSWORD},
        )
        context = browser.new_context(ignore_https_errors=True)
        assert context.request.get(origin + "/api/v1/notes/").status == 403
        page = sign_in(context, origin)
        page.get_by_role("link", name="Capture a note", exact=True).click()
        body = "Captured with the packaged browser editor."
        page.get_by_label("Your note").fill(body)
        page.get_by_role("button", name="Save note", exact=True).click()
        expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
        saved = {page.url.rstrip("/").split("/")[-1]: body}

        csrf = next(c["value"] for c in context.cookies() if c["name"] == "csrftoken")
        body = "Captured directly through the JSON API."
        response = page.request.post(
            origin + "/api/v1/notes/",
            headers={"Origin": origin, "X-CSRFToken": csrf},
            data={"content": {"version": 1, "format": "plain-text", "text": body}},
        )
        assert response.status == 201
        trashed_id = response.json()["id"]
        saved[trashed_id] = body
        with browser.new_context(
            ignore_https_errors=True, java_script_enabled=False
        ) as html_context:
            html_page = sign_in(html_context, origin)
            html_page.get_by_role("link", name="Capture a note", exact=True).click()
            body = "Captured through the HTML form."
            html_page.get_by_label("Plain text", exact=True).fill(body)
            html_page.get_by_role("button", name="Save note", exact=True).click()
            expect(html_page.get_by_text(body, exact=True)).to_be_visible()
            saved[html_page.url.rstrip("/").split("/")[-1]] = body

        assert_notes(page, origin, saved)
        trashed_body = saved.pop(trashed_id)
        page.goto(f"{origin}/notes/{trashed_id}/")
        page.get_by_role("button", name="Move to trash").click()
        expect(page.get_by_text(trashed_body, exact=True)).to_be_visible()
        manage("backup_database", str(backup))
        assert manage("backup_database", str(backup), check=False).returncode == 1
        context.close()

    with serve(package, env, certificate, key, playwright) as origin:
        context = browser.new_context(ignore_https_errors=True)
        page = sign_in(context, origin)
        assert_notes(page, origin, saved)
        open_trash(page, origin, trashed_id, trashed_body)
        context.close()

    blocked_backup = tmp_path / "blocked.sqlite3"
    with closing(sqlite3.connect(env["ALCOVE_DATABASE"])) as locked:
        locked.execute("BEGIN EXCLUSIVE")
        failure = manage("backup_database", str(blocked_backup), check=False)
        assert failure.returncode == 1
        assert "locked" in failure.stderr
    assert not blocked_backup.exists()

    recovery_env = {
        **env,
        "ALCOVE_DATABASE": str(recovery / "alcove.sqlite3"),
        "ALCOVE_SECRET_KEY": secrets.token_hex(48),
    }
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"invalid backup")
    assert (
        manage(
            "restore_database", str(corrupt), settings=recovery_env, check=False
        ).returncode
        == 1
    )
    assert not Path(recovery_env["ALCOVE_DATABASE"]).exists()
    manage("restore_database", str(backup), settings=recovery_env)
    assert (
        manage(
            "restore_database", str(backup), settings=recovery_env, check=False
        ).returncode
        == 1
    )
    with serve(package, recovery_env, certificate, key, playwright) as origin:
        context = browser.new_context(ignore_https_errors=True)
        page = sign_in(context, origin)
        assert_notes(page, origin, saved)
        open_trash(page, origin, trashed_id, trashed_body)
        page.get_by_role("button", name="Restore note").click()
        assert_notes(page, origin, {trashed_id: trashed_body})
        context.close()
