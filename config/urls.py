"""URL configuration for Damka V2."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework.permissions import AllowAny

schema_view = get_schema_view(
    openapi.Info(
        title="Damka.uz API",
        default_version="v2",
        description="Damka.uz checkers game API",
    ),
    public=True,
    permission_classes=(AllowAny,),
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/game/", include("apps.game.urls")),
    path("api/", include("apps.users.urls")),
    path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
]

# Serve static and media files in development
# Daphne (ASGI) doesn't auto-serve static like runserver does
urlpatterns += staticfiles_urlpatterns()
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Django Debug Toolbar: local.py adds the middleware, but its namespace ('djdt')
# must be registered here or EVERY response raises NoReverseMatch (which was
# 500-ing the API, e.g. /api/game/types/). Guard on the app being installed.
if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
