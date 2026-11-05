import getpass
import os
from typing import Any

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from alcove.models import Collection


class Command(BaseCommand):
    help = "Provision the single owner. Repeating the same username is a no-op."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("username")
        parser.add_argument("--no-input", action="store_true")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"]
        owner = Collection.objects.select_related("owner").first()
        if owner:
            if owner.owner.username != username:
                raise CommandError(
                    "An owner already exists; extra accounts are disabled."
                )
            self.stdout.write("Owner already provisioned; password unchanged.")
            return
        if User.objects.exists():
            raise CommandError(
                "Existing accounts found; refusing to replace ownership."
            )
        user = User(username=username)
        password = os.environ.get("ALCOVE_OWNER_PASSWORD")
        if password is None:
            if options["no_input"]:
                raise CommandError("Set ALCOVE_OWNER_PASSWORD for --no-input.")
            password = getpass.getpass("Owner password: ")
            if password != getpass.getpass("Repeat password: "):
                raise CommandError("Passwords did not match.")
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        Collection.objects.create(owner=user)
        self.stdout.write("Owner provisioned.")
