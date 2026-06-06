"""
Generate and publish simulator telemetry cycles.

Modes:
    --once                   Run exactly one cycle and exit (default if no
                             repetition mode is given; a warning is printed).
    --iterations N           Run exactly N cycles and exit.
    --duration-seconds N     Run cycles until N seconds have elapsed.

Examples:
    python manage.py run_simulator --scenario default_demo --once
    python manage.py run_simulator --scenario default_demo --iterations 5 --sleep-seconds 10
    python manage.py run_simulator --scenario default_demo --duration-seconds 60 --sleep-seconds 5
    python manage.py run_simulator --scenario default_demo --once --dry-run
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.dashboard import live_updates
from apps.simulator.services.mqtt_publisher import publish_message

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Number of payloads generated and published in a single cycle."""

    generated: int = 0
    published: int = 0


class Command(BaseCommand):
    help = (
        "Generate and publish simulator telemetry. Supports a single cycle "
        "(--once), a fixed number of cycles (--iterations N), or a fixed "
        "duration (--duration-seconds N). Persistence happens only via the "
        "MQTT ingestion chain — never written directly here."
    )

    # ── Argument parsing ─────────────────────────────────────────────────────

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario",
            default="default_demo",
            help="Scenario code to run (default: default_demo).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Generate payloads and print them to stdout WITHOUT publishing to MQTT.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=None,
            help=(
                "Sleep interval between cycles (seconds). "
                "When omitted, SimulatorScenario.interval_seconds is used."
            ),
        )

        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument(
            "--once",
            action="store_true",
            help="Run exactly one generation/publish cycle and exit.",
        )
        mode_group.add_argument(
            "--iterations",
            type=int,
            default=None,
            help="Run exactly N (>= 1) generation/publish cycles and exit.",
        )
        mode_group.add_argument(
            "--duration-seconds",
            type=int,
            default=None,
            help=(
                "Run repeated cycles until the given duration has elapsed (>= 1). "
                "The final cycle may slightly overshoot if it was already running "
                "when the deadline arrived."
            ),
        )

    # ── Entry point ──────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        from apps.simulator.models import SimulatorRun, SimulatorScenario

        verbosity = int(options.get("verbosity", 1))
        code = options["scenario"]
        dry_run: bool = options["dry_run"]
        once: bool = options["once"]
        iterations = options["iterations"]
        duration_seconds = options["duration_seconds"]
        sleep_override = options["sleep_seconds"]

        # Mode flags are mutually exclusive in argparse, but call_command()
        # bypasses argparse, so re-check here for parity.
        active_modes = [
            name
            for name, value in (
                ("--once", once),
                ("--iterations", iterations is not None),
                ("--duration-seconds", duration_seconds is not None),
            )
            if value
        ]
        if len(active_modes) > 1:
            raise CommandError(
                f"Mutually exclusive mode flags: {', '.join(active_modes)}. "
                "Pick exactly one of --once, --iterations, or --duration-seconds."
            )

        if iterations is not None and iterations < 1:
            raise CommandError("--iterations must be a positive integer (>= 1).")
        if duration_seconds is not None and duration_seconds < 1:
            raise CommandError("--duration-seconds must be a positive integer (>= 1).")
        if sleep_override is not None and sleep_override < 0:
            raise CommandError("--sleep-seconds must be zero or positive.")

        try:
            scenario = SimulatorScenario.objects.select_related("site").get(code=code)
        except SimulatorScenario.DoesNotExist:
            raise CommandError(f"SimulatorScenario '{code}' not found.")

        sleep_seconds = (
            float(sleep_override)
            if sleep_override is not None
            else float(scenario.interval_seconds)
        )

        if not (once or iterations or duration_seconds):
            self.stdout.write(self.style.WARNING(
                "No --once / --iterations / --duration-seconds specified — "
                "running a single cycle. Use --iterations N or "
                "--duration-seconds N for repeated execution."
            ))
            once = True

        run = SimulatorRun.objects.create(scenario=scenario, status="running")
        # Running totals live on ``self`` so that mid-cycle exceptions can
        # still surface the partial counts in SimulatorRun.messages_published.
        self._cycles_completed = 0
        self._total_generated = 0
        self._total_published = 0

        try:
            if iterations is not None:
                self._run_iterations(
                    scenario,
                    iterations=iterations,
                    sleep_seconds=sleep_seconds,
                    dry_run=dry_run,
                    verbosity=verbosity,
                )
            elif duration_seconds is not None:
                self._run_for_duration(
                    scenario,
                    duration_seconds=duration_seconds,
                    sleep_seconds=sleep_seconds,
                    dry_run=dry_run,
                    verbosity=verbosity,
                )
            else:
                # --once (explicit or default-with-warning): exactly one cycle, no sleep
                self._tally_cycle(self._run_one_cycle(
                    scenario, dry_run, verbosity, cycle_number=1,
                ))

            now = timezone.now()
            run.status = "completed"
            run.finished_at = now
            run.messages_published = self._total_published
            run.save(update_fields=["status", "finished_at", "messages_published"])

            scenario.last_run_at = now
            scenario.save(update_fields=["last_run_at"])

            self._print_summary(
                code=code,
                cycles=self._cycles_completed,
                generated=self._total_generated,
                published=self._total_published,
                dry_run=dry_run,
            )

        except CommandError:
            raise
        except Exception as exc:
            run.status = "failed"
            run.finished_at = timezone.now()
            run.error_message = str(exc)
            # Preserve partial publish count for diagnostics.
            run.messages_published = self._total_published
            run.save(update_fields=[
                "status", "finished_at", "error_message", "messages_published",
            ])
            raise CommandError(f"Simulator failed: {exc}") from exc

    def _tally_cycle(self, result: "CycleResult") -> None:
        self._cycles_completed += 1
        self._total_generated += result.generated
        self._total_published += result.published

    # ── Mode runners ─────────────────────────────────────────────────────────

    def _run_iterations(
        self,
        scenario,
        *,
        iterations: int,
        sleep_seconds: float,
        dry_run: bool,
        verbosity: int,
    ) -> None:
        for cycle_idx in range(iterations):
            self._tally_cycle(self._run_one_cycle(
                scenario, dry_run, verbosity, cycle_number=cycle_idx + 1,
            ))
            if cycle_idx < iterations - 1:
                self._sleep_between_cycles(sleep_seconds, verbosity)

    def _run_for_duration(
        self,
        scenario,
        *,
        duration_seconds: int,
        sleep_seconds: float,
        dry_run: bool,
        verbosity: int,
    ) -> None:
        # time.monotonic / time.sleep are referenced via the module-level
        # ``time`` import so tests can patch them.
        #
        # Phase 7 Task 4 follow-up: long-running mode honors
        # ``SimulatorScenario.is_active`` so the dashboard "Sākt"/"Apturēt"
        # buttons actually pause/resume emission for an externally-managed
        # simulator service. We refresh ``is_active`` from the database
        # *before* every cycle so a UI flip takes effect on the next tick
        # without needing a process restart.
        deadline = time.monotonic() + duration_seconds
        cycle_number = 0
        while True:
            scenario.refresh_from_db(fields=["is_active", "interval_seconds"])
            if scenario.is_active:
                cycle_number += 1
                self._tally_cycle(self._run_one_cycle(
                    scenario, dry_run, verbosity, cycle_number=cycle_number,
                ))
                # Bump ``last_run_at`` after every successful emit so the
                # dashboard's "Pēdējais palaidiens" pill stays fresh during
                # a long-running ``--duration-seconds`` sweep instead of
                # only updating when ``handle()`` finalises the run.
                if not dry_run:
                    type(scenario).objects.filter(pk=scenario.pk).update(
                        last_run_at=timezone.now(),
                    )
            elif verbosity >= 2:
                self.stdout.write(
                    f"scenario '{scenario.code}' is paused "
                    f"(is_active=False); skipping cycle"
                )

            # Do not start a new cycle if the duration has already elapsed.
            if time.monotonic() >= deadline:
                break
            self._sleep_between_cycles(sleep_seconds, verbosity)
            if time.monotonic() >= deadline:
                break

    # ── Per-cycle execution ──────────────────────────────────────────────────

    def _run_one_cycle(
        self,
        scenario,
        dry_run: bool,
        verbosity: int,
        *,
        cycle_number: int,
    ) -> CycleResult:
        """
        Generate one payload per enabled SimulatorScenarioDevice and either
        publish it (normal mode) or print it (dry-run). Returns a CycleResult
        with generated/published counts. Raises on publish failure so the
        caller can mark the SimulatorRun as failed.

        Phase 7 Task 4 follow-up: every successful or failed publish (and
        every dry-run cycle) is also fanned out as a
        ``simulator_mqtt_message_sent`` live update so the
        ``/dashboard/simulator/`` workspace charts and MQTT stream table
        update in real time when this long-running command is the source
        of truth (i.e. the standalone simulator service in
        ``docker-compose.local.yml``). Live-update publishing is
        best-effort: a websocket / channel-layer failure must NEVER
        abort the underlying MQTT publish.
        """
        from apps.simulator.services.payload_generator import generate_payload

        result = CycleResult()
        devices_qs = scenario.scenario_devices.filter(is_enabled=True).select_related(
            "device__site", "device__asset", "device_profile"
        )
        for sd in devices_qs:
            topic, payload = generate_payload(sd)
            result.generated += 1

            if dry_run:
                self.stdout.write(f"[dry-run] cycle={cycle_number} topic={topic}")
                self.stdout.write(json.dumps(payload, indent=2))
                self._publish_live_message(
                    scenario=scenario, scenario_device=sd, topic=topic,
                    payload=payload, publish_status="dry_run", error="",
                )
                continue

            try:
                publish_message(topic, payload)
            except Exception as exc:  # noqa: BLE001 — best-effort live update on failure
                self._publish_live_message(
                    scenario=scenario, scenario_device=sd, topic=topic,
                    payload=payload, publish_status="failed", error=str(exc),
                )
                raise
            result.published += 1
            self._publish_live_message(
                scenario=scenario, scenario_device=sd, topic=topic,
                payload=payload, publish_status="ok", error="",
            )

            if verbosity >= 2:
                self.stdout.write(
                    f"cycle={cycle_number} topic={topic} "
                    f"message_id={payload['message_id']}"
                )

        return result

    @staticmethod
    def _publish_live_message(
        *, scenario, scenario_device, topic, payload, publish_status, error,
    ) -> None:
        """
        Best-effort wrapper around
        :func:`apps.dashboard.live_updates.publish_simulator_mqtt_message`.
        Mirrors the helper in :mod:`apps.simulator.services.control` so
        the standalone runner emits the same workspace events as the
        synchronous "Run once" API path.
        """
        try:
            device = getattr(scenario_device, "device", None)
            asset = getattr(device, "asset", None) if device else None
            live_updates.publish_simulator_mqtt_message(
                scenario=scenario,
                device=device,
                asset=asset,
                topic=topic,
                payload_dict=payload,
                publish_status=publish_status,
                error=error,
                message_id=(payload or {}).get("message_id", ""),
            )
        except Exception:  # noqa: BLE001 — never raise from a live update
            logger.exception(
                "publish_simulator_mqtt_message failed (best-effort, ignored).",
            )

    # ── Output helpers ───────────────────────────────────────────────────────

    def _sleep_between_cycles(self, sleep_seconds: float, verbosity: int) -> None:
        if sleep_seconds <= 0:
            return
        if verbosity >= 2:
            self.stdout.write(
                f"sleeping {sleep_seconds:.1f}s before next cycle..."
            )
        time.sleep(sleep_seconds)

    def _print_summary(
        self,
        *,
        code: str,
        cycles: int,
        generated: int,
        published: int,
        dry_run: bool,
    ) -> None:
        if dry_run:
            msg = (
                f"run_simulator: generated {generated} message(s) "
                f"across {cycles} cycle(s) for scenario '{code}' "
                f"[dry-run, not published]"
            )
        else:
            msg = (
                f"run_simulator: published {published} message(s) "
                f"across {cycles} cycle(s) for scenario '{code}'"
            )
        self.stdout.write(self.style.SUCCESS(msg))
