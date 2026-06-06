from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download and validate the configured rembg model during deployment."

    def handle(self, *args, **options):
        from rembg import new_session

        self.stdout.write(f"Preloading rembg model: {settings.REMBG_MODEL}")
        new_session(settings.REMBG_MODEL)
        self.stdout.write(self.style.SUCCESS("rembg model is ready."))
