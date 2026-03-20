"""User URL configuration — matching v1 API paths."""
from django.urls import path

from apps.users.views import (
    RegisterView,
    SMSVerifyView,
    LoginView,
    ProfileView,
    ChangePasswordView,
    CheckAccountView,
    CheckUsernameView,
    CountriesView,
    GuestTokenView,
    PasswordResetRequestView,
    PasswordResetVerifyView,
    PasswordResetConfirmView,
)

urlpatterns = [
    # Registration (v1 parity: /register/ + /sms/)
    path("register/", RegisterView.as_view(), name="register"),
    path("sms/", SMSVerifyView.as_view(), name="sms-verify"),

    # Login
    path("login/", LoginView.as_view(), name="login"),

    # Profile
    path("profile/", ProfileView.as_view(), name="profile"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),

    # Check account existence
    path("check/", CheckAccountView.as_view(), name="check-account"),
    path("check/<str:username>/", CheckUsernameView.as_view(), name="check-username"),

    # Password reset
    path("reset/account/", PasswordResetRequestView.as_view(), name="reset-request"),
    path("reset/sms/", PasswordResetVerifyView.as_view(), name="reset-verify"),
    path("reset/confirm/<uidb64>/<token>/", PasswordResetConfirmView.as_view(), name="reset-confirm"),

    # Countries
    path("countries/", CountriesView.as_view(), name="countries"),

    # Anonymous token
    path("guest/", GuestTokenView.as_view(), name="guest-token"),
]
