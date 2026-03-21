from secrets import token_urlsafe

from django.http import JsonResponse
from rest_framework.views import APIView

from apps.game.models import ConnectionHistory


class AnonymousTokenView(APIView):
    """Generates a unique token for anonymous users."""
    def get(self, request, *args, **kwargs):
        token = self.generate_token()
        while ConnectionHistory.objects.filter(anonym_token=token).exists():
            token = self.generate_token()
        return JsonResponse({'token': token})

    @staticmethod
    def generate_token():
        return token_urlsafe(32)
