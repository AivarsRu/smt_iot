from django.urls import path

from .views import healthz, root_view


app_name = "core"

urlpatterns = [
    path("", root_view, name="welcome"),
    path("healthz/", healthz, name="healthz"),
]