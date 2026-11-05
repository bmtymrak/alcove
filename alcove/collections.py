from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Collection


def for_owner(user: AbstractBaseUser | AnonymousUser) -> Collection:
    if not user.is_authenticated:
        raise PermissionDenied("Sign in to access your Collection.")
    return get_object_or_404(Collection, owner_id=user.pk)
