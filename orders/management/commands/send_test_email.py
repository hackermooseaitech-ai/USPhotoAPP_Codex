from django.core.management.base import BaseCommand, CommandError

from orders.services.delivery import send_test_delivery_email


class Command(BaseCommand):
    help = "Send a test delivery email through the configured email provider."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Recipient email address.")

    def handle(self, *args, **options):
        email = options["email"]
        result = send_test_delivery_email(email)
        if not result:
            raise CommandError("Test email was not sent. Check the logs above for the provider error.")
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {email}."))
