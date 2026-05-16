from django.apps import AppConfig


class MqttIngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mqtt_ingestion"
