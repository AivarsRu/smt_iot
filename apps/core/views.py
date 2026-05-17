from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
        db_status = "ok"
        status_code = 200
    except Exception as exc:
        db_status = f"error: {exc}"
        status_code = 503

    return JsonResponse(
        {
            "service": "smt_digital_solution",
            "status": "ok" if status_code == 200 else "degraded",
            "database": db_status,
        },
        status=status_code,
    )


def root_view(request):
    """
    Project root.

    Authenticated operators are redirected to the dashboard overview;
    anonymous visitors get a small public welcome page with a login link.
    The dashboard URL is reversed (not hardcoded) so a future route rename
    does not silently break the redirect.
    """
    if request.user.is_authenticated:
        return redirect(reverse("dashboard:overview"))
    return render(request, "core/welcome.html")