from django.conf import settings
import logging

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from orders.models import Order

logger = logging.getLogger(__name__)


def send_delivery_email(order: Order, request=None) -> bool:
    if not order.email or order.status != Order.Status.PAID or order.delivery_email_sent_at:
        return False

    site_url = settings.SITE_URL
    if request is not None:
        site_url = request.build_absolute_uri("/").rstrip("/")

    try:
        context = {
            "order": order,
            "photo_url": f"{site_url}/download/{order.id}/photo/",
            "print_url": f"{site_url}/download/{order.id}/print/",
            "include_photo": order.selected_package != Order.Package.PRINT,
            "include_print": order.selected_package != Order.Package.PHOTO,
            "site_url": site_url,
        }
        subject = "Your Hacker Moose US visa photo is ready"
        text_body = render_to_string("orders/email_delivery.txt", context)
        html_body = render_to_string("orders/email_delivery.html", context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[order.email],
        )
        message.attach_alternative(html_body, "text/html")
        if context["include_photo"] and order.processed_image:
            _attach_order_file(message, order.processed_image, f"hacker-moose-{order.id}-600x600.jpg")
        if context["include_print"] and order.print_template:
            _attach_order_file(message, order.print_template, f"hacker-moose-{order.id}-4x6.jpg")
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Delivery email failed for order %s", order.id)
        return False
    try:
        order.delivery_email_sent_at = timezone.now()
        order.save(update_fields=["delivery_email_sent_at", "updated_at"])
    except Exception:
        logger.exception("Could not mark delivery email sent for order %s", order.id)
        return False
    return True


def _attach_order_file(message, field, filename):
    try:
        with field.open("rb") as file_obj:
            message.attach(filename, file_obj.read(), "image/jpeg")
    except Exception:
        logger.exception("Could not attach delivery file %s", filename)
