from json import dumps, loads

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_200_OK, HTTP_201_CREATED

from shared.django import generate_sms_code, UniqueNumberOrEmailPermission, CustomTokenAuthentication
from apps.users.models import User
from apps.users.serializers import SMSVerificationSerializer, AuthEmailPhoneNumberSerializer


class SMSRequestView(CreateAPIView):
    """
    View for registering an account with verification.

    Fields:
        - phone_number (str): The phone number to be registered.
        - email (str): The email address to be registered
    """
    serializer_class = AuthEmailPhoneNumberSerializer
    permission_classes = UniqueNumberOrEmailPermission,
    authentication_classes = CustomTokenAuthentication,

    def create(self, request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data, context={'session': request.session})

        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)

            code = generate_sms_code()

            # In DEBUG mode, skip real SMS sending and use fixed code 0000
            if settings.DEBUG:
                code = '0000'
                print(f"[DEBUG] Registration code for {phone_number or email}: {code}")
            # else:
            #     send_notification.apply_async(kwargs={"phone": phone_number, "code": code})

            # Store in session
            key = phone_number or email
            request.session[key] = dumps({
                'code': code,
                'password': serializer.validated_data['password'],
            })

            return Response({'message': _('SMS code sent successfully')}, HTTP_201_CREATED)
        else:
            return Response(serializer.errors, HTTP_400_BAD_REQUEST)


class SMSVerificationView(CreateAPIView):
    """
    View for verifying an SMS code.

    Fields:
        - phone_number (str): The phone number for which verification is requested.
        - user_entered_code (str): The verification code entered by the user.
    """
    serializer_class = SMSVerificationSerializer
    permission_classes = UniqueNumberOrEmailPermission,
    authentication_classes = CustomTokenAuthentication,

    def create(self, request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data, context={'session': request.session})
        if serializer.is_valid(raise_exception=True):

            phone_number = serializer.validated_data.get('phone_number', None)
            email = serializer.validated_data.get('email', None)
            once = phone_number if phone_number else email
            user_entered_code = serializer.validated_data['user_entered_code']

            current_session_data = loads(request.session.get(once, '{}'))
            attempts = request.session.get(f'{once}_attempts', 0)
            saved_code = current_session_data.get('code')

            if saved_code and user_entered_code == saved_code:
                # Generate unique username
                user_count = User.objects.count()
                unique_username = f"User{user_count}"
                while User.objects.filter(username=unique_username).exists():
                    user_count += 1
                    unique_username = f"User{user_count}"

                if phone_number:
                    user = User(phone_number=phone_number, username=unique_username)
                else:
                    user = User(email=email, username=unique_username)
                user.set_password(current_session_data.get('password'))
                user.save()
                token, created = Token.objects.get_or_create(user=user)

                # Clean up session
                try:
                    del request.session[once]
                except KeyError:
                    pass
                try:
                    del request.session[f'{once}_attempts']
                except KeyError:
                    pass

                return Response({
                    'message': _('Successful'),
                    'token': token.key,
                    'username': unique_username,
                }, HTTP_200_OK)
            else:
                attempts += 1
                request.session[f'{once}_attempts'] = attempts
                if attempts >= 5:
                    try:
                        del request.session[once]
                    except KeyError:
                        pass
                    try:
                        del request.session[f'{once}_attempts']
                    except KeyError:
                        pass
                    return Response({'error': _('You have not other attempts, try again!')}, HTTP_400_BAD_REQUEST)

                return Response({'error': _('Wrong SMS Code')}, HTTP_400_BAD_REQUEST)
        else:
            return Response(serializer.errors, HTTP_400_BAD_REQUEST)
