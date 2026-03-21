from django.forms.widgets import Input
from django.utils.translation import gettext_lazy as _
from django.forms import CharField
from unfold.forms import UserCreationForm
from unfold.widgets import INPUT_CLASSES

from apps.users.models import User


class CustomUserCreationForm(UserCreationForm):
    username = CharField(widget=Input(attrs={'class': ' '.join(INPUT_CLASSES)}), label=_('Username'),
                             required=False)

    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')
