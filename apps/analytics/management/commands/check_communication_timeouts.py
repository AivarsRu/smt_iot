"""
Detect IoT devices that have not communicated within their expected interval
and create / close ``communication_timeout`` Event records accordingly.

Cron-friendly examples:
    python manage.py check_communication_timeouts
    python manage.py check_communication_timeouts --dry-run --verbosity 2
    python manage.py check_communication_timeouts --site default_demo
    python manage.py check_communication_timeouts --device charger-001
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.communication_timeouts import (
    DEVICE_STATUS_NEVER_SEEN,
    DEVICE_STATUS_OK,
    DEVICE_STATUS_SKIPPED,
    DEVICE_STATUS_TIMED_OUT,
    check_all_device_communication_timeouts,
)
from apps.assets.models import Device, Site


class Command(BaseCommand):
    help = (
        "Check active devices for communication timeouts. Creates or closes "
        "communication_timeout events; recalculates AssetState anomaly counters."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--site",
            dest="site_code",
            default=None,
            help="Restrict the check to a single Site (matched by Site.code).",
        )
        parser.add_argument(
            "--device",
            dest="device_uid",
            default=None,
            help="Restrict the check to a single Device (matched by device_uid).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute and print results without creating, updating, or closing records.",
        )

    def handle(self, *args, **options):
        verbosity = int(options.get("verbosity") or 1)
        dry_run = bool(options.get("dry_run"))

        site = self._resolve_site(options.get("site_code"))
        device = self._resolve_device(options.get("device_uid"))

        result = check_all_device_communication_timeouts(
            site=site, device=device, dry_run=dry_run,
        )

        self._print_summary(result, dry_run=dry_run, verbosity=verbosity)

        if result.errors:
            self.stdout.write(
                self.style.WARNING(
                    f"  errors: {len(result.errors)} (first: {result.errors[0]})"
                )
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_site(site_code: str | None):
        if not site_code:
            return None
        try:
            return Site.objects.get(code=site_code)
        except Site.DoesNotExist as exc:
            raise CommandError(f"Site with code='{site_code}' not found.") from exc

    @staticmethod
    def _resolve_device(device_uid: str | None):
        if not device_uid:
            return None
        try:
            return Device.objects.get(device_uid=device_uid)
        except Device.DoesNotExist as exc:
            raise CommandError(
                f"Device with device_uid='{device_uid}' not found."
            ) from exc

    def _print_summary(self, result, *, dry_run: bool, verbosity: int) -> None:
        header = "DRY RUN — no records modified" if dry_run else "Check complete"
        self.stdout.write(self.style.SUCCESS(header))
        self.stdout.write(
            f"  devices_checked = {result.devices_checked}\n"
            f"  timeouts_created = {result.timeouts_created}\n"
            f"  timeouts_updated = {result.timeouts_updated}\n"
            f"  timeouts_closed  = {result.timeouts_closed}\n"
            f"  devices_ok       = {result.devices_ok}\n"
            f"  devices_skipped  = {result.devices_skipped}"
        )

        if verbosity < 2:
            return

        if not result.device_records:
            self.stdout.write("  (no devices evaluated)")
            return

        self.stdout.write("  per-device details:")
        for rec in result.device_records:
            line = (
                f"    device_uid={rec.device_uid:<24} "
                f"asset={rec.asset_code or '-':<16} "
                f"site={rec.site_code or '-':<16} "
                f"status={rec.status}"
            )
            if rec.last_seen_at is not None:
                line += f" last_seen_at={rec.last_seen_at.isoformat()}"
            else:
                line += " last_seen_at=<none>"
            if rec.expected_interval_seconds is not None:
                line += f" expected={rec.expected_interval_seconds}s"
            if rec.timeout_seconds is not None:
                line += f" threshold={rec.timeout_seconds:.0f}s"
            if rec.event_action:
                line += f" event_action={rec.event_action}"
            if rec.skip_reason:
                line += f" skip_reason={rec.skip_reason}"
            self.stdout.write(line)

        # Highlight known status counts in verbose mode.
        counts = {
            DEVICE_STATUS_OK: 0,
            DEVICE_STATUS_TIMED_OUT: 0,
            DEVICE_STATUS_NEVER_SEEN: 0,
            DEVICE_STATUS_SKIPPED: 0,
        }
        for rec in result.device_records:
            if rec.status in counts:
                counts[rec.status] += 1
        self.stdout.write(
            f"  status_counts: ok={counts[DEVICE_STATUS_OK]}, "
            f"timed_out={counts[DEVICE_STATUS_TIMED_OUT]}, "
            f"never_seen={counts[DEVICE_STATUS_NEVER_SEEN]}, "
            f"skipped={counts[DEVICE_STATUS_SKIPPED]}"
        )
