from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from orders.models import Order


def send_delivery_email(order: Order, request=None) -> bool:
    if not order.email or order.status != Order.Status.PAID or order.delivery_email_sent_at:
        return False

    site_url = settings.SITE_URL
    if request is not None:
        site_url = request.build_absolute_uri("/").rstrip("/")

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

    send_mail(
        subject=subject,
        message=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[order.email],
        html_message=html_body,
        fail_silently=False,
    )
    order.delivery_email_sent_at = timezone.now()
    order.save(update_fields=["delivery_email_sent_at", "updated_at"])
    return True
