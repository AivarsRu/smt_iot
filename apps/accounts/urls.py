"""
Authentication routes for the operator UI.

We delegate to Django's built-in ``LoginView`` and ``LogoutView`` so we
inherit the standard session, CSRF, ``?next=`` redirect, and password
hashing behaviour without re-implementing it. Only the login template
is customised (Latvian copy + dashboard styling).

Routes are mounted under ``/accounts/`` from ``config/urls.py`` and use
the ``accounts:`` namespace.
"""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path


app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]
