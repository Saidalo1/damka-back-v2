"""User URL configuration."""
from django.urls import path

from apps.users.views import (
    RegisterView,
    SMSVerifyView,
    LoginView,
    ProfileView,
    ChangePasswordView,
    CheckAccountView,
    CountriesView,
    GuestTokenView,
)

urlpatterns = [
    # Registration
    path("register/", RegisterView.as_view(), name="register"),
    path("verify/", SMSVerifyView.as_view(), name="sms-verify"),

    # Login
    path("login/", LoginView.as_view(), name="login"),

    # Profile
    path("profile/", ProfileView.as_view(), name="profile"),
    path("password/", ChangePasswordView.as_view(), name="change-password"),

    # Check account existence
    path("check/", CheckAccountView.as_view(), name="check-account"),

    # Countries
    path("countries/", CountriesView.as_view(), name="countries"),

    # Anonymous token
    path("guest-token/", GuestTokenView.as_view(), name="guest-token"),
]
