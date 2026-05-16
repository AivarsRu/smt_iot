"""
Run the MQTT ingestion worker.

Examples:
    python manage.py run_mqtt_worker
    python manage.py run_mqtt_worker --once --timeout-seconds 60
    python manage.py run_mqtt_worker --topic "smt/+/+/+/+/telemetry" --client-id my-worker
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from apps.mqtt_ingestion.worker import MqttIngestionWorker, MqttWorkerConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Connect to Mosquitto and forward each received MQTT message to the ingestion service."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Exit after the first received message has been processed.",
        )
        parser.add_argument(
            "--timeout-seconds",
            type=float,
            default=30.0,
            help="Timeout for --once mode (seconds). Ignored in normal mode.",
        )
        parser.add_argument(
            "--topic",
            action="append",
            default=None,
            help=(
                "Override subscribe topic(s). Repeatable. Also accepts a single "
                "comma-separated value. Example: --topic 'smt/+/+/+/+/telemetry'."
            ),
        )
        parser.add_argument(
            "--client-id",
            type=str,
            default=None,
            help="Override the MQTT client ID.",
        )

    def handle(self, *args, **options):
        topics = self._resolve_topics(options.get("topic"))
        config = MqttWorkerConfig.from_settings(
            client_id=options.get("client_id"),
            topics=topics,
        )

        self.stdout.write(self.style.NOTICE(
            f"Starting MQTT worker with config: {config.redacted()}"
        ))

        worker = MqttIngestionWorker(config=config)

        try:
            if options["once"]:
                received = worker.run_once(timeout_seconds=options["timeout_seconds"])
                if not received:
                    raise CommandError(
                        f"--once: no MQTT message received within {options['timeout_seconds']}s"
                    )
                self.stdout.write(self.style.SUCCESS("--once: message processed successfully"))
            else:
                worker.run_forever()
                self.stdout.write(self.style.SUCCESS("MQTT worker stopped"))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Interrupted by user"))
        except OSError as exc:
            raise CommandError(
                f"MQTT connection failed to {config.host}:{config.port} — {exc}"
            ) from exc

    @staticmethod
    def _resolve_topics(raw):
        """
        --topic may be:
          - None         → use settings default
          - ['a', 'b']   → list (repeated --topic)
          - ['a,b,c']    → single comma-separated value
        Returns a flat list or None (meaning "use settings default").
        """
        if not raw:
            return None
        out: list = []
        for entry in raw:
            for item in str(entry).split(","):
                item = item.strip()
                if item:
                    out.append(item)
        return out or None
