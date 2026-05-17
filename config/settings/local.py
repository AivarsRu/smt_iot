from .base import *

DEBUG = True

# WhiteNoise is enabled in MIDDLEWARE for production (where collectstatic
# populates STATIC_ROOT). In local development we don't want to run
# collectstatic on every change, so tell WhiteNoise to consult the same
# staticfiles finders that Django's runserver uses. Without this, requests
# to /static/<app>/... hit WhiteNoise first and 404 because STATIC_ROOT
# is empty. See https://whitenoise.readthedocs.io/en/stable/django.html
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
