import base64
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from orders.models import Order

logger = logging.getLogger(__name__)


def send_test_delivery_email(to_email: str) -> bool:
    if not to_email:
        return False

    subject = "Hacker Moose email delivery test"
    text_body = "This is a Hacker Moose delivery email test. If you received this, the email provider is connected."
    html_body = "<p>This is a <strong>Hacker Moose</strong> delivery email test. If you received this, the email provider is connected.</p>"
    try:
        if settings.RESEND_API_KEY:
            logger.warning(
                "Test email using Resend from=%s to=%s",
                settings.RESEND_FROM_EMAIL,
                to_email,
            )
            _send_resend_email(to_email, subject, text_body, html_body, [])
        else:
            logger.warning(
                "Test email using SMTP host=%s user_set=%s to=%s",
                settings.EMAIL_HOST,
                bool(settings.EMAIL_HOST_USER),
                to_email,
            )
            _send_smtp_email(to_email, subject, text_body, html_body, [])
    except Exception:
        logger.exception("Test delivery email failed for %s", to_email)
        return False
    logger.warning("Test delivery email sent to %s", to_email)
    return True


def send_delivery_email(order: Order, request=None) -> bool:
    if not order.email or order.status != Order.Status.PAID or order.delivery_email_sent_at:
        return False
    if not settings.RESEND_API_KEY and not _smtp_is_configured():
        logger.error(
            "Delivery email is not configured. EMAIL_BACKEND=%s EMAIL_HOST_SET=%s EMAIL_HOST_USER_SET=%s EMAIL_HOST_PASSWORD_SET=%s",
            settings.EMAIL_BACKEND,
            bool(settings.EMAIL_HOST),
            bool(settings.EMAIL_HOST_USER),
            bool(settings.EMAIL_HOST_PASSWORD),
        )
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
        attachments = _build_delivery_attachments(order, context)
        if settings.RESEND_API_KEY:
            logger.warning(
                "Delivery email using Resend for order %s from=%s to=%s attachments=%s",
                order.id,
                settings.RESEND_FROM_EMAIL,
                order.email,
                len(attachments),
            )
            _send_resend_email(order.email, subject, text_body, html_body, attachments)
        else:
            logger.warning(
                "Delivery email using SMTP for order %s host=%s user_set=%s to=%s attachments=%s",
                order.id,
                settings.EMAIL_HOST,
                bool(settings.EMAIL_HOST_USER),
                order.email,
                len(attachments),
            )
            _send_smtp_email(order.email, subject, text_body, html_body, attachments)
    except Exception:
        logger.exception("Delivery email failed for order %s", order.id)
        return False
    try:
        order.delivery_email_sent_at = timezone.now()
        order.save(update_fields=["delivery_email_sent_at", "updated_at"])
        logger.warning("Delivery email marked sent for order %s", order.id)
    except Exception:
        logger.exception("Could not mark delivery email sent for order %s", order.id)
        return False
    return True


def _send_smtp_email(to_email, subject, text_body, html_body, attachments):
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    message.attach_alternative(html_body, "text/html")
    for attachment in attachments:
        message.attach(attachment["filename"], attachment["content"], "image/jpeg")
    message.send(fail_silently=False)


def _send_resend_email(to_email, subject, text_body, html_body, attachments):
    if "resend.dev" in settings.RESEND_FROM_EMAIL:
        logger.warning(
            "RESEND_FROM_EMAIL uses resend.dev test domain. Resend can only send this to the account email, not arbitrary customer emails. from=%s to=%s",
            settings.RESEND_FROM_EMAIL,
            to_email,
        )
    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
        "attachments": [
            {
                "filename": attachment["filename"],
                "content": base64.b64encode(attachment["content"]).decode("ascii"),
            }
            for attachment in attachments
        ],
    }
    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "hacker-moose-usphoto/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise RuntimeError(f"Resend returned HTTP {response.status}: {body}")
            logger.warning("Resend email accepted with HTTP %s: %s", response.status, body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Resend email failed with HTTP %s: %s", exc.code, body)
        raise
    except URLError:
        logger.exception("Resend email network request failed")
        raise


def _build_delivery_attachments(order, context):
    attachments = []
    if context["include_photo"] and order.processed_image:
        attachment = _read_order_file(order.processed_image, f"hacker-moose-{order.id}-600x600.jpg")
        if attachment:
            attachments.append(attachment)
    if context["include_print"] and order.print_template:
        attachment = _read_order_file(order.print_template, f"hacker-moose-{order.id}-4x6.jpg")
        if attachment:
            attachments.append(attachment)
    return attachments


def _read_order_file(field, filename):
    try:
        with field.open("rb") as file_obj:
            return {"filename": filename, "content": file_obj.read()}
    except Exception:
        logger.exception("Could not attach delivery file %s", filename)
        return None


def _smtp_is_configured():
    if settings.EMAIL_BACKEND.endswith(".console.EmailBackend") or settings.EMAIL_BACKEND.endswith(".locmem.EmailBackend"):
        return True
    return bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD)
