"""User URL configuration — matching v1 URL paths exactly."""
from django.urls import path

from apps.users.views import (
    SMSRequestView,
    SMSVerificationView,
    LoginView,
    CheckExistingAccountByNumberOrEmail,
    CheckExistingAccountByUsername,
    AnonymousTokenView,
    UserUpdateView,
    UserDetailAPIView,
    ChangePasswordView,
    CheckPasswordView,
    CountriesView,
    PasswordResetRequestView,
    PasswordResetVerificationView,
    PasswordResetConfirmView,
)

urlpatterns = [
    # Registration (v1 parity)
    path('register/', SMSRequestView.as_view(), name='register-request'),
    path('sms/', SMSVerificationView.as_view(), name='register-verification'),

    # Login
    path('login/', LoginView.as_view(), name='login'),

    # Check
    path('check/', CheckExistingAccountByNumberOrEmail.as_view(), name='check-existing-number'),
    path('check/<str:username>/', CheckExistingAccountByUsername.as_view(), name='check-existing-username'),

    # Reset password
    path('reset/account/', PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('reset/sms/', PasswordResetVerificationView.as_view(), name='password_reset_verification'),
    path('reset/confirm/<uidb64>/<token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),

    # Generate token for anonymous users
    path('generate_token/', AnonymousTokenView.as_view(), name='token-anonymous'),

    # Update user
    path('user/update/', UserUpdateView.as_view(), name='user-update'),
    path('user/update/password/', ChangePasswordView.as_view(), name='update-password'),

    # Check current password
    path('check/password/mine/', CheckPasswordView.as_view(), name='check-password'),

    # Get all countries
    path('countries/', CountriesView.as_view(), name='countries'),

    # Get profile information
    path('get-profile/', UserDetailAPIView.as_view(), name='user_detail'),
]
