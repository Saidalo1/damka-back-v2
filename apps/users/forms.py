from django.forms.widgets import Input
from django.utils.translation import gettext_lazy as _
from django.forms import CharField
from unfold.forms import AuthenticationForm, UserCreationForm
from unfold.widgets import INPUT_CLASSES

from apps.users.models import User


class AdminLoginForm(AuthenticationForm):
    """Unfold-styled admin login form, relabelled only.

    Subclasses unfold's AuthenticationForm (which applies the input styling in
    __init__), then just changes the field label — the widget/styling is left
    untouched. Login accepts a username OR a phone; the auth backend resolves
    either (phone stays the model's USERNAME_FIELD).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Username or phone")


class CustomUserCreationForm(UserCreationForm):
    username = CharField(widget=Input(attrs={'class': ' '.join(INPUT_CLASSES)}), label=_('Username'),
                             required=False)

    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')
