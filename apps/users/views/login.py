from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST

from apps.users.serializers import LoginSerializer


class LoginView(GenericAPIView):
    serializer_class = LoginSerializer

    def post(self, request, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid(raise_exception=True):
            phone_number = serializer.validated_data.get('phone_number', None)
            password = serializer.validated_data.get('password')

            if phone_number:
                user = authenticate(phone_number=phone_number, password=password)
            else:
                email = serializer.validated_data.get('email')
                user = authenticate(email=email, password=password)

            if user:
                token, created = Token.objects.get_or_create(user=user)
                return Response({
                    "token": token.key,
                    "message": _("Successful")
                }, HTTP_200_OK)
            else:
                return Response({
                    "token": None,
                    "message": "Wrong password"
                }, HTTP_400_BAD_REQUEST)
