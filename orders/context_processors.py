from django.conf import settings


def site_chrome(request):
    social_login = None
    if request.user.is_authenticated:
        account = request.user.socialaccount_set.order_by("-id").first()
        if account:
            social_login = {
                "provider": account.get_provider().name,
                "email": account.extra_data.get("email") or request.user.email or request.user.username,
            }

    providers = settings.SOCIALACCOUNT_PROVIDERS
    return {
        "google_oauth_ready": bool(providers.get("google", {}).get("APPS")),
        "social_login": social_login,
    }
