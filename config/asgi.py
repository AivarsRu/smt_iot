"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

Phase 7, Task 3A wires Django Channels in. HTTP requests still go through
the standard Django HTTP stack; WebSocket requests are routed to the
``apps.dashboard`` consumers via the protocol type router.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

# IMPORTANT: ``get_asgi_application`` must be called *before* importing any
# Channels routing/AuthMiddlewareStack, because those imports trigger the
# Django app registry — which in turn must be ready before our consumers
# are loaded.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.dashboard.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
