from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import Profile
from apps.mcp_server.oauth import (
    approve_authorization_request,
    client_display_name,
    deny_authorization_request,
    get_authorization_request,
    get_client_for_authorization_request,
)


@login_required
@require_http_methods(["GET", "POST"])
def authorize(request: HttpRequest):
    transaction_id = request.GET.get("transaction") or request.POST.get("transaction")
    if not transaction_id:
        return HttpResponseBadRequest("Missing authorization transaction.")

    authorization_request = get_authorization_request(transaction_id)
    if authorization_request is None:
        return HttpResponseBadRequest("Authorization request has expired or does not exist.")

    client = get_client_for_authorization_request(authorization_request)
    if client is None:
        return HttpResponseBadRequest("OAuth client no longer exists.")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "deny":
            return redirect(deny_authorization_request(transaction_id))

        if action != "approve":
            return HttpResponseBadRequest("Invalid authorization action.")

        profile, _created = Profile.objects.get_or_create(user=request.user)
        return redirect(approve_authorization_request(transaction_id, profile))

    return render(
        request,
        "mcp_server/authorize.html",
        {
            "authorization_request": authorization_request,
            "client_name": client_display_name(client),
        },
    )
