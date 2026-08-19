from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F, Value
from django.db.models.functions import Concat, Lower
from django.utils.translation import gettext_lazy as _
from rest_framework.generics import GenericAPIView, UpdateAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_200_OK
from rest_framework.views import APIView

from shared.django import (
    CustomTokenPermission, CustomTokenAuthentication, generate_sms_code,
    send_notification, send_verification_email, update_users_token,
)
from shared.django import validate_telegram_username
from apps.users.models import User, Countries
from apps.users.serializers import (
    CheckAccountByNumberOrEmailSerializer, UserUpdateModelSerializer,
    UserUpdateEmailOrPhoneNumberModelSerializer, UpdateSMSVerificationSerializer,
    ChangePasswordSerializer, CheckPasswordSerializer,
)


# Check existing by number
class CheckExistingAccountByNumberOrEmail(GenericAPIView):
    serializer_class = CheckAccountByNumberOrEmailSerializer

    def post(self, request, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            if phone_number is None:
                email = serializer.validated_data.get('email', None)
                once = email
            else:
                once = phone_number
            response = {
                'data': once,
            }

            try:
                user = User.objects.get(phone_number=once) if phone_number else User.objects.get(email=once)
                response.update({
                    'is_registered': True,
                    'full_name': user.username
                })
            except User.DoesNotExist:
                response.update({
                    'is_registered': False,
                    'full_name': None
                })

            return Response(response)


# Check existing by username
class CheckExistingAccountByUsername(APIView):
    @staticmethod
    def get(request, **kwargs) -> Response:
        username = kwargs.get('username')
        try:
            validate_telegram_username(username)
            try:
                User.objects.get(username=username)
                return Response({'is_taken': True})
            except User.DoesNotExist:
                return Response({'is_taken': False})
        except ValidationError as msg:
            return Response({'error': msg.message})


# Check existing by chat id
class CheckExistingAccountByChatId(APIView):
    @staticmethod
    def get(request, **kwargs) -> Response:
        chat_id = kwargs.get('chat_id')
        try:
            User.objects.get(chat_id=chat_id)
            return Response({'is_taken': True})
        except User.DoesNotExist:
            return Response({'is_taken': False})


# Update user profile
class UserUpdateView(UpdateAPIView):
    serializer_class = UserUpdateModelSerializer
    permission_classes = IsAuthenticated,
    parser_classes = MultiPartParser,

    def get_object(self):
        return self.request.user


class UserEmailOrPhoneNumberUpdateView(GenericAPIView):
    serializer_class = UserUpdateEmailOrPhoneNumberModelSerializer
    permission_classes = IsAuthenticated,

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_phone_number = request.data.get('phone', None)
        if new_phone_number:
            old_phone_number = request.user.phone_number
            if new_phone_number and new_phone_number != old_phone_number:
                phone_number_data = f'{new_phone_number}_{request.user.id}'
                if request.session.get(phone_number_data):
                    return Response({"error": _("This phone number is already in process!")}, HTTP_400_BAD_REQUEST)
                code = generate_sms_code()
                if settings.DEBUG:
                    code = '0000'
                    print(f"[DEBUG] Phone update code for {new_phone_number}: {code}")
                else:
                    status_code, *_ = send_notification(new_phone_number, code)
                    if status_code != 200:
                        return Response({"error": _("Could not send the SMS code. Please try again.")},
                                        HTTP_400_BAD_REQUEST)
                request.session[phone_number_data] = code
                request.data['phone_number'] = old_phone_number
        else:
            new_email = request.data.get('email', None)
            if new_email:
                email_data = f'{new_email}_{request.user.id}'
                if request.session.get(email_data):
                    return Response({"error": _("This email is already in process!")}, HTTP_400_BAD_REQUEST)
                code = generate_sms_code()
                if settings.DEBUG:
                    code = '0000'
                    print(f"[DEBUG] Email update code for {new_email}: {code}")
                else:
                    send_verification_email(new_email, code, request.user.get_full_name())
                request.session[email_data] = code
                request.data['email'] = request.user.email

        return Response({"message": _("SMS code sent successfully!")})

    def get_object(self):
        return self.request.user


class UpdateSMSVerificationView(GenericAPIView):
    serializer_class = UpdateSMSVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data,
                                         context={'session': request.session, 'user_id': self.request.user.id})
        if serializer.is_valid(raise_exception=True):
            user = request.user

            phone_number = serializer.validated_data.get('phone', None)
            email = serializer.validated_data.get('email', None)
            once = phone_number if phone_number is not None else email
            user_entered_code = serializer.validated_data['user_entered_code']

            saved_code = request.session.get(f'{once}_{user.id}')
            attempts = request.session.get(f'{once}_{user.id}_attempts', 0)

            if saved_code and user_entered_code == saved_code:
                if once == phone_number:
                    user.phone_number = once
                    user.save(update_fields=('phone_number',))
                    response = {
                        'message': _('Phone number changed successfully! Your new phone number is ') + f'{once}'}
                else:
                    user.email = once
                    user.save(update_fields=('email',))
                    response = {'message': _('Email changed successfully! Your new email is ') + f'{once}'}

                try:
                    del request.session[f'{once}_{user.id}']
                except KeyError:
                    pass
                try:
                    del request.session[f'{once}_{user.id}_attempts']
                except KeyError:
                    pass

                return Response(response, HTTP_200_OK)
            else:
                attempts += 1

                request.session[f'{once}_{user.id}_attempts'] = attempts
                if attempts >= 5:
                    try:
                        del request.session[f'{once}_{user.id}']
                    except KeyError:
                        pass
                    try:
                        del request.session[f'{once}_{user.id}_attempts']
                    except KeyError:
                        pass
                    return Response({'error': _('YOU_HAVE_NOT_OTHER_ATTEMPTS_TRY_AGAIN')}, HTTP_400_BAD_REQUEST)

                return Response({'error': _('INVALID_VERIFICATION_CODE')}, HTTP_400_BAD_REQUEST)
        else:
            return Response(serializer.errors, HTTP_400_BAD_REQUEST)


# Get all countries
class CountriesView(APIView):
    @staticmethod
    def get(request, *args, **kwargs):
        from config.settings.base import STATIC_URL as STATIC
        countries = Countries.objects.annotate(
            flag=Concat(Value(request.build_absolute_uri('/')), Value(f"{STATIC}flag/"), Lower(F('code')),
                        Value('.gif'))
        ).values('title', 'flag', 'code')
        return Response(list(countries))


# Get personal information
class UserDetailAPIView(APIView):
    """API view to retrieve the details of the authenticated user."""
    permission_classes = CustomTokenPermission,
    authentication_classes = [CustomTokenAuthentication]

    @staticmethod
    def get(request, *args, **kwargs):
        user = request.user
        result = {'is_guest': True}

        if user.is_authenticated:
            result = {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'country': {
                    'title': user.country.title,
                    'flag': {
                        'flag_url': user.country.flag,
                        'code': user.country.code
                    }
                },
                'ratings': {
                    'bullet': user.bullet_rating,
                    'blitz': user.blitz_rating,
                    'rapid': user.rapid_rating
                },
                'avatar': f"{user.avatar.url}" if user.avatar else None,
                'avatar_sm': f"{user.avatar_sm}" if user.avatar_sm else None,
                'avatar_md': f"{user.avatar_md}" if user.avatar_md else None,
                'avatar_lg': f"{user.avatar_lg}" if user.avatar_lg else None,
                'date_joined': user.date_joined,
                'is_guest': False,
            }

            if user.phone_number:
                result['phone_number'] = user.phone_number
            elif user.email:
                result['email'] = user.email

        return Response(result)


class ChangePasswordView(GenericAPIView):
    """An endpoint for changing password."""
    serializer_class = ChangePasswordSerializer
    permission_classes = IsAuthenticated,

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.data.get("old_password")):
                return Response({"error": _("Wrong password.")}, HTTP_400_BAD_REQUEST)
            user.set_password(serializer.data.get("new_password"))
            user.save(update_fields=('password',))
            new_token = update_users_token(user.pk)
            return Response({'message': _('Your password updated successfully!'), 'new_token': new_token}, HTTP_200_OK)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)


class CheckPasswordView(GenericAPIView):
    """An endpoint to check current password."""
    serializer_class = CheckPasswordSerializer
    permission_classes = IsAuthenticated,

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.data.get("password")):
                return Response({"error": _("Wrong password!")}, HTTP_400_BAD_REQUEST)
            return Response({'message': _('Correct password!')}, HTTP_200_OK)
        return Response(serializer.errors, HTTP_400_BAD_REQUEST)
