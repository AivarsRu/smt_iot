import uuid

from django.db import models


class OperationalStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    OFFLINE = "offline", "Offline"


class DataType(models.TextChoices):
    FLOAT = "float", "Float"
    INTEGER = "integer", "Integer"
    BOOLEAN = "boolean", "Boolean"
    STRING = "string", "String"


class MqttTopicType(models.TextChoices):
    TELEMETRY = "telemetry", "Telemetry"
    STATUS = "status", "Status"
    EVENT = "event", "Event"
    COMMAND = "command", "Command"
    COMMAND_ACK = "command_ack", "Command Ack"


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
