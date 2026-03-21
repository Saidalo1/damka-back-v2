from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.django import CustomTokenAuthentication
from apps.game.models import Game
from apps.users.models import User
from apps.users.serializers import RemoveUserSerializer


class RemoveUserAPIView(APIView):
    authentication_classes = (CustomTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def delete(self, request, *args, **kwargs):
        serializer = RemoveUserSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user: User = request.user
        exists_games = Game.objects.filter(
            Q(has_ended=False) & Q(Q(black_id=user.id) | Q(white_id=user.id))
        )
        if exists_games:
            game = exists_games[0]
            data = {
                'error': f'You have unfinished game id {game.id}',
            }
            return Response(data, status=status.HTTP_400_BAD_REQUEST)
        else:
            user.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
