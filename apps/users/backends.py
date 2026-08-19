"""Authentication backend that accepts a username OR a phone number.

The app-wide ``USERNAME_FIELD`` is ``phone_number`` (used everywhere in the
product), but typing a phone number to log into ``/admin`` is awkward. This
backend — used for Django's session/admin login — also accepts the ``username``,
so admins can sign in with either identifier while ``phone_number`` stays the
default field. The app's own ``LoginView`` does its own lookup and is untouched.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None
        try:
            user = UserModel.objects.get(
                Q(username__iexact=username) | Q(phone_number=username)
            )
        except UserModel.DoesNotExist:
            # Run the hasher once to keep timing consistent (avoid user enumeration).
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = (
                UserModel.objects
                .filter(Q(username__iexact=username) | Q(phone_number=username))
                .order_by("pk")
                .first()
            )
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
