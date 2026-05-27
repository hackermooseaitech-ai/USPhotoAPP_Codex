from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import UserLoginRecord


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR")


def _login_provider(user):
    account = user.socialaccount_set.order_by("-id").first()
    return account.provider if account else "email"


@receiver(user_logged_in)
def record_user_login(sender, request, user, **kwargs):
    UserLoginRecord.objects.create(
        user=user,
        email=user.email or "",
        provider=_login_provider(user),
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
