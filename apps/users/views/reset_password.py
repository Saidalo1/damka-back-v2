from django.conf import settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.translation import gettext_lazy as _
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from shared.django import generate_sms_code, update_users_token, send_verification_email
from apps.users.models import User
from apps.users.serializers import (
    PasswordResetConfirmSerializer, PasswordResetRequestSerializer,
    PasswordResetVerificationSerializer,
)
from apps.users.tokens import account_activation_token

VERIFICATION_ATTEMPTS_LIMIT = 5
PASSWORD_RESET_CODE_TTL = 300  # 5 minutes


class PasswordResetRequestView(GenericAPIView):
    """API view to handle password reset requests."""
    serializer_class = PasswordResetRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            if not phone_number:
                email = serializer.validated_data.get('email', None)
                once = email
            else:
                once = phone_number

            if request.session.get(f'password_reset:{once}'):
                return Response({'error': _('A verification code has already been sent to this data.')},
                                HTTP_400_BAD_REQUEST)

            try:
                if phone_number:
                    user = User.objects.get(phone_number=once)
                else:
                    user = User.objects.get(email=once)
            except User.DoesNotExist:
                return Response({'message': _('User with this data does not exist!')}, HTTP_404_NOT_FOUND)

            verification_code = generate_sms_code()
            if settings.DEBUG:
                verification_code = '0000'
                print(f"[DEBUG] Password reset code for {once}: {verification_code}")
            elif not phone_number:
                send_verification_email(once, verification_code, user.username)

            request.session[f'password_reset:{once}'] = verification_code
            request.session[f'verification_attempts:{once}'] = 0

            return Response({'message': _('Verification code sent successfully!')}, HTTP_200_OK)
        return


class PasswordResetVerificationView(GenericAPIView):
    """API view to handle password reset verification."""
    serializer_class = PasswordResetVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            if not phone_number:
                email = serializer.validated_data.get('email', None)
                once = email
            else:
                once = phone_number
            user_entered_code = serializer.validated_data['verification_code']

            saved_code = request.session.get(f'password_reset:{once}')
            if saved_code:
                attempts = int(request.session.get(f'verification_attempts:{once}', 0))
                if attempts >= VERIFICATION_ATTEMPTS_LIMIT:
                    try:
                        del request.session[f'password_reset:{once}']
                        del request.session[f'verification_attempts:{once}']
                    except KeyError:
                        pass
                    return Response({'error': _('Too many attempts! Verification code expired.')}, HTTP_400_BAD_REQUEST)
                if user_entered_code == saved_code:
                    request.session[f'password_reset_verified:{once}'] = 'verified'
                    try:
                        del request.session[f'password_reset:{once}']
                    except KeyError:
                        pass

                    user = User.objects.get(phone_number=once) if phone_number else User.objects.get(email=once)
                    current_site = request.build_absolute_uri('/')[:-1]
                    uid = urlsafe_base64_encode(force_bytes(user.pk))
                    token = account_activation_token.make_token(user)
                    reset_link = current_site + reverse('password_reset_confirm', args=(uid, token))
                    return Response({'message': _('Successfully verified!'), 'reset_link': reset_link}, HTTP_200_OK)
                else:
                    attempts += 1
                    request.session[f'verification_attempts:{once}'] = attempts
                    return Response({'error': _('Invalid verification code!')}, HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': _('This number is not waiting for verification reset password!')})
        return


class PasswordResetConfirmView(GenericAPIView):
    """API view to handle password reset confirmation."""
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request, uidb64=None, token=None, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            try:
                uid = urlsafe_base64_decode(uidb64).decode()
                user = User.objects.get(pk=uid)
            except (TypeError, ValueError, OverflowError, User.DoesNotExist):
                user = None

            if user is not None and account_activation_token.check_token(user, token):
                phone_number, email = user.phone_number, user.email
                if (request.session.get(f'password_reset_verified:{phone_number}') or
                        request.session.get(f'password_reset_verified:{email}')):
                    new_password = serializer.validated_data['new_password']
                    user.set_password(new_password)
                    user.save()
                    try:
                        del request.session[f'password_reset_verified:{phone_number}']
                    except KeyError:
                        pass
                    try:
                        del request.session[f'password_reset_verified:{email}']
                    except KeyError:
                        pass
                    new_token = update_users_token(user.pk)
                    return Response({'message': _('Password has been reset successfully!'), 'new_token': new_token},
                                    HTTP_200_OK)
                else:
                    return Response({'error': _('Verification limit expired!')}, HTTP_400_BAD_REQUEST)
            else:
                return Response({'error': _('Invalid reset link!')}, HTTP_400_BAD_REQUEST)
        return
