import json
import logging
import secrets
from pathlib import Path

import stripe
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import PhotoUploadForm
from .models import Order
from .services.delivery import delivery_attachment_summary, send_delivery_email, send_test_delivery_email
from .services.photo_processor import FaceGeometry, prepare_photo_source, process_order_photo, render_visa_photo
from .services.users import mark_user_paid

logger = logging.getLogger(__name__)

MIN_HEAD_RATIO = 0.53
MAX_HEAD_RATIO = 0.62
RATIO_STEP = 0.01
OFFSET_STEP = 18
MAX_OFFSET = 96
DEFAULT_OFFSET_Y = 54
BACKGROUND_OPTIONS = {
    Order.Background.WHITE: {"key": Order.Background.WHITE, "label": "白色", "color": "#FFFFFF"},
}
PACKAGE_OPTIONS = {
    Order.Package.PHOTO: {
        "key": Order.Package.PHOTO,
        "name": "Square 2x2 digital photo",
        "short_name": "2x2 Photo",
        "price": "$5.99",
        "cents": 599,
        "description": "One clean 600x600 JPEG for online forms and digital upload.",
    },
    Order.Package.PRINT: {
        "key": Order.Package.PRINT,
        "name": "4x6 print sheet",
        "short_name": "4x6 Sheet",
        "price": "$5.99",
        "cents": 599,
        "description": "Six 2x2 photos arranged on one 4x6 inch print-ready sheet.",
    },
    Order.Package.BUNDLE: {
        "key": Order.Package.BUNDLE,
        "name": "Digital + print bundle",
        "short_name": "Bundle",
        "price": "$9.99",
        "cents": 999,
        "description": "Both the 600x600 JPEG and the 4x6 six-photo print sheet.",
    },
}


def index(request):
    providers = settings.SOCIALACCOUNT_PROVIDERS
    social_login = None
    delivery_email = _user_delivery_email(request.user)
    if request.user.is_authenticated:
        account = request.user.socialaccount_set.order_by("-id").first()
        if account:
            social_login = {
                "provider": account.get_provider().name,
                "email": delivery_email or request.user.username,
            }
    return render(
        request,
        "orders/index.html",
        {
            "form": PhotoUploadForm(initial={"email": delivery_email} if delivery_email else None),
            "google_oauth_ready": bool(providers.get("google", {}).get("APPS")),
            "social_login": social_login,
        },
    )


def _user_delivery_email(user):
    if not user.is_authenticated:
        return ""
    if user.email:
        return user.email
    account = user.socialaccount_set.filter(provider="google").order_by("-id").first()
    if account:
        return account.extra_data.get("email", "")
    return ""


@require_POST
def upload_photo(request):
    form = PhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "orders/_upload_form.html", {"form": form}, status=422)

    order = form.save()
    prepared = _prepare_order_source(order)
    _regenerate_order_images(order, base_notes=prepared.notes)

    edit_url = reverse("orders:edit", args=[order.id])
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = edit_url
        return response
    return redirect(edit_url)


def edit_photo(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    prepared = _prepare_order_source(order)
    _regenerate_order_images(order, base_notes=prepared.notes)
    order.refresh_from_db()
    return render(request, "orders/edit.html", {"order": order, "background_options": BACKGROUND_OPTIONS.values()})


def packages(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, "orders/packages.html", {"order": order, "packages": PACKAGE_OPTIONS.values()})


@require_POST
def adjust_photo(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    action = request.POST.get("action")

    if action == "ratio_down":
        order.crop_head_ratio = max(MIN_HEAD_RATIO, order.crop_head_ratio - RATIO_STEP)
    elif action == "ratio_up":
        order.crop_head_ratio = min(MAX_HEAD_RATIO, order.crop_head_ratio + RATIO_STEP)
    elif action == "set_ratio":
        try:
            head_percent = float(request.POST.get("head_percent", "60"))
        except ValueError:
            return HttpResponseBadRequest("Invalid head ratio.")
        order.crop_head_ratio = min(max(head_percent / 100, MIN_HEAD_RATIO), MAX_HEAD_RATIO)
    elif action == "move_left":
        order.crop_offset_x = max(-MAX_OFFSET, order.crop_offset_x - OFFSET_STEP)
    elif action == "move_right":
        order.crop_offset_x = min(MAX_OFFSET, order.crop_offset_x + OFFSET_STEP)
    elif action == "move_up":
        order.crop_offset_y = max(-MAX_OFFSET, order.crop_offset_y - OFFSET_STEP)
    elif action == "move_down":
        order.crop_offset_y = min(MAX_OFFSET, order.crop_offset_y + OFFSET_STEP)
    elif action == "reset":
        order.crop_head_ratio = 0.60
        order.crop_offset_x = 0
        order.crop_offset_y = DEFAULT_OFFSET_Y
    else:
        return HttpResponseBadRequest("Unknown adjustment.")

    _regenerate_order_images(order)
    return render(request, "orders/_preview_card.html", {"order": order, "background_options": BACKGROUND_OPTIONS.values()})


def _prepare_order_source(order):
    if order.background != Order.Background.WHITE:
        order.background = Order.Background.WHITE
    prepared = prepare_photo_source(order.original_image, background_color=_order_background_color(order))
    version = order.updated_at.strftime("%Y%m%d%H%M%S")
    order.prepared_image.save(f"{order.id}-{version}-prepared.jpg", prepared.prepared_jpeg, save=False)
    _set_order_face(order, prepared.face)
    order.save(update_fields=["background", "prepared_image", "face_center_x", "face_eye_y", "face_head_top_y", "face_chin_y", "updated_at"])
    return prepared


def _regenerate_order_images(order, base_notes=None):
    if order.prepared_image and _order_face(order) is None:
        prepared = prepare_photo_source(order.prepared_image, background_color=_order_background_color(order))
        _set_order_face(order, prepared.face)
        if base_notes is None:
            base_notes = prepared.notes

    if order.prepared_image:
        processed = render_visa_photo(
            order.prepared_image,
            _order_face(order),
            notes=base_notes,
            head_ratio=order.crop_head_ratio,
            offset_x=order.crop_offset_x,
            offset_y=order.crop_offset_y,
            background_color=_order_background_color(order),
        )
    else:
        processed = process_order_photo(
            order.original_image,
            head_ratio=order.crop_head_ratio,
            offset_x=order.crop_offset_x,
            offset_y=order.crop_offset_y,
            background_color=_order_background_color(order),
        )
    version = order.updated_at.strftime("%Y%m%d%H%M%S")
    order.processed_image.save(f"{order.id}-{version}-visa-photo-600.jpg", processed.final_jpeg, save=False)
    order.preview_image.save(f"{order.id}-{version}-preview.jpg", processed.preview_jpeg, save=False)
    order.print_template.save(f"{order.id}-{version}-4x6.jpg", processed.print_template_jpeg, save=False)
    order.s3_key = order.processed_image.name
    order.processing_notes = "\n".join(processed.notes)
    order.save(
        update_fields=[
            "processed_image",
            "preview_image",
            "print_template",
            "s3_key",
            "processing_notes",
            "prepared_image",
            "crop_head_ratio",
            "crop_offset_x",
            "crop_offset_y",
            "background",
            "face_center_x",
            "face_eye_y",
            "face_head_top_y",
            "face_chin_y",
            "updated_at",
        ]
    )


def _set_order_face(order, face):
    if face is None:
        order.face_center_x = None
        order.face_eye_y = None
        order.face_head_top_y = None
        order.face_chin_y = None
        return

    order.face_center_x = face.center_x
    order.face_eye_y = face.eye_y
    order.face_head_top_y = face.head_top_y
    order.face_chin_y = face.chin_y


def _order_face(order):
    if None in (order.face_center_x, order.face_eye_y, order.face_head_top_y, order.face_chin_y):
        return None
    return FaceGeometry(
        center_x=order.face_center_x,
        eye_y=order.face_eye_y,
        head_top_y=order.face_head_top_y,
        chin_y=order.face_chin_y,
    )


def _order_background_color(order):
    return BACKGROUND_OPTIONS.get(order.background, BACKGROUND_OPTIONS[Order.Background.WHITE])["color"]


@require_POST
def create_checkout_session(request, order_id, package):
    order = get_object_or_404(Order, id=order_id)
    if order.status == Order.Status.PAID:
        return redirect("orders:success", order_id=order.id)

    package_option = PACKAGE_OPTIONS.get(package)
    if not package_option:
        raise Http404("Unknown package.")

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe is not configured yet. Add STRIPE_SECRET_KEY to .env.")
        return redirect("orders:packages", order_id=order.id)

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=order.email or None,
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"Hacker Moose US Visa Photo - {package_option['short_name']}"},
                        "unit_amount": package_option["cents"],
                    },
                    "quantity": 1,
                }
            ],
            wallet_options={"link": {"display": "never"}},
            metadata={"order_id": str(order.id), "package": package},
            success_url=f"{settings.SITE_URL}{reverse('orders:success', args=[order.id])}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.SITE_URL}{reverse('orders:packages', args=[order.id])}",
        )
    except stripe.StripeError as exc:
        messages.error(request, f"Stripe checkout could not be created: {exc.user_message or str(exc)}")
        return redirect("orders:packages", order_id=order.id)

    order.selected_package = package
    order.stripe_session_id = session.id
    order.save(update_fields=["selected_package", "stripe_session_id", "updated_at"])
    return redirect(session.url)


def success(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    session_id = request.GET.get("session_id")
    if session_id and settings.STRIPE_SECRET_KEY and order.status != Order.Status.PAID:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as exc:
            messages.warning(request, f"Stripe payment status could not be verified yet: {exc.user_message or str(exc)}")
        except Exception:
            logger.exception("Unexpected Stripe verification failure for order %s", order.id)
            messages.warning(request, "Stripe payment status could not be verified yet. Please refresh this page in a moment.")
        else:
            metadata = _stripe_session_metadata(session)
            session_order_id = str(metadata.get("order_id") or "")
            session_package = metadata.get("package") or order.selected_package
            session_is_paid = _stripe_session_value(session, "payment_status") == "paid"
            session_matches_order = session_order_id == str(order.id) or order.stripe_session_id == session_id
            try:
                if session_is_paid and session_matches_order:
                    updates = {
                        "status": Order.Status.PAID,
                        "stripe_session_id": _stripe_session_value(session, "id", session_id),
                    }
                    if session_package in PACKAGE_OPTIONS:
                        updates["selected_package"] = session_package
                    Order.objects.filter(id=order.id).update(**updates)
                    order.refresh_from_db()
                    mark_user_paid(order.email)
            except Exception:
                logger.exception("Could not update paid order from Stripe session for order %s", order.id)
                if session_is_paid and session_matches_order:
                    order.status = Order.Status.PAID
                    order.stripe_session_id = _stripe_session_value(session, "id", session_id)
                    if session_package in PACKAGE_OPTIONS:
                        order.selected_package = session_package
                    messages.warning(request, "The payment succeeded, but the order record could not be saved yet. You can still download your files below.")
                else:
                    messages.warning(request, "The payment succeeded, but the order update needs a moment. Please refresh this page.")

    if order.status == Order.Status.PAID:
        try:
            _ensure_order_images(order)
        except Exception:
            logger.exception("Paid order image preparation failed for order %s", order.id)
            messages.warning(request, "The payment succeeded, but the photo files are still being prepared. Please refresh this page.")

    email_sent = bool(order.delivery_email_sent_at)
    force_email = request.GET.get("send_email") == "1"
    if order.status == Order.Status.PAID and order.email and (force_email or not order.delivery_email_sent_at):
        try:
            email_sent = send_delivery_email(order, request=request, force=force_email)
        except Exception:
            logger.exception("Unexpected delivery email failure for order %s", order.id)
            email_sent = False
        if email_sent:
            order.refresh_from_db(fields=["delivery_email_sent_at", "updated_at"])
        else:
            messages.warning(request, "The payment succeeded, but email delivery is not configured yet. You can download your files below.")
    return render(
        request,
        "orders/success.html",
        {
            "order": order,
            "package": PACKAGE_OPTIONS.get(order.selected_package),
            "email_sent": email_sent,
        },
    )


def _stripe_session_value(session, key, default=None):
    try:
        value = session.get(key, default)
    except AttributeError:
        value = getattr(session, key, default)
    return default if value is None else value


def _stripe_session_metadata(session):
    metadata = _stripe_session_value(session, "metadata", {}) or {}
    if hasattr(metadata, "to_dict"):
        metadata = metadata.to_dict()
    try:
        return dict(metadata)
    except (TypeError, ValueError):
        return {}


def preview_file(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not order.preview_image:
        raise Http404("Preview is not available.")

    filename = Path(order.preview_image.name).name
    response = FileResponse(order.preview_image.open("rb"), filename=filename)
    response["Cache-Control"] = "no-store"
    return response


def final_photo_file(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if order.status != Order.Status.PAID or not order.processed_image:
        raise Http404("Final photo is not available.")

    filename = Path(order.processed_image.name).name
    try:
        response = FileResponse(order.processed_image.open("rb"), filename=filename)
    except FileNotFoundError:
        raise Http404("Final photo file is no longer available.")
    response["Cache-Control"] = "no-store"
    return response


def print_template_file(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if order.status != Order.Status.PAID or not order.print_template:
        raise Http404("Print template is not available.")
    if order.selected_package == Order.Package.PHOTO:
        raise Http404("This package does not include the 4x6 print sheet.")

    filename = Path(order.print_template.name).name
    try:
        response = FileResponse(order.print_template.open("rb"), filename=filename)
    except FileNotFoundError:
        raise Http404("Print template file is no longer available.")
    response["Cache-Control"] = "no-store"
    return response


def download_file(request, order_id, kind):
    order = get_object_or_404(Order, id=order_id)
    if order.status != Order.Status.PAID:
        raise Http404("This order is not paid yet.")

    field = {
        "photo": order.processed_image,
        "print": order.print_template,
    }.get(kind)
    if not field:
        raise Http404("Unknown download type.")
    if order.selected_package == Order.Package.PHOTO and kind != "photo":
        raise Http404("This package does not include the 4x6 print sheet.")
    if order.selected_package == Order.Package.PRINT and kind != "print":
        raise Http404("This package does not include the 2x2 digital photo.")

    filename = Path(field.name).name
    try:
        return FileResponse(field.open("rb"), as_attachment=True, filename=filename)
    except FileNotFoundError:
        raise Http404("Download file is no longer available.")


def test_email(request):
    configured_token = settings.ADMIN_TEST_TOKEN
    supplied_token = request.GET.get("token", "")
    to_email = request.GET.get("to", "").strip()
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        return JsonResponse({"ok": False, "error": "Invalid token."}, status=403)
    if not to_email:
        return JsonResponse({"ok": False, "error": "Missing to email."}, status=400)

    sent = send_test_delivery_email(to_email)
    return JsonResponse(
        {
            "ok": sent,
            "to": to_email,
            "provider": "resend" if settings.RESEND_API_KEY else "smtp",
            "from": settings.RESEND_FROM_EMAIL if settings.RESEND_API_KEY else settings.DEFAULT_FROM_EMAIL,
        },
        status=200 if sent else 502,
    )


def resend_order_email(request, order_id):
    configured_token = settings.ADMIN_TEST_TOKEN
    supplied_token = request.GET.get("token", "")
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        return JsonResponse({"ok": False, "error": "Invalid token."}, status=403)

    order = get_object_or_404(Order, id=order_id)
    if order.status != Order.Status.PAID:
        return JsonResponse({"ok": False, "error": "Order is not paid.", "status": order.status}, status=400)
    if not order.email:
        return JsonResponse({"ok": False, "error": "Order has no delivery email."}, status=400)

    _ensure_order_images(order)
    order.delivery_email_sent_at = None
    order.save(update_fields=["delivery_email_sent_at", "updated_at"])
    sent = send_delivery_email(order, request=request, force=True)
    order.refresh_from_db()
    return JsonResponse(
        {
            "ok": sent,
            "order_id": str(order.id),
            "to": order.email,
            "provider": "resend" if settings.RESEND_API_KEY else "smtp",
            "from": settings.RESEND_FROM_EMAIL if settings.RESEND_API_KEY else settings.DEFAULT_FROM_EMAIL,
            "selected_package": order.selected_package,
            "has_photo": bool(order.processed_image),
            "has_print": bool(order.print_template),
            "email_sent_at": order.delivery_email_sent_at.isoformat() if order.delivery_email_sent_at else None,
        },
        status=200 if sent else 502,
    )


def order_delivery_status(request, order_id):
    configured_token = settings.ADMIN_TEST_TOKEN
    supplied_token = request.GET.get("token", "")
    if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
        return JsonResponse({"ok": False, "error": "Invalid token."}, status=403)

    order = get_object_or_404(Order, id=order_id)
    summary = delivery_attachment_summary(order)
    return JsonResponse(
        {
            "ok": True,
            "order_id": str(order.id),
            "status": order.status,
            "to": order.email,
            "selected_package": order.selected_package,
            "delivery_email_sent_at": order.delivery_email_sent_at.isoformat() if order.delivery_email_sent_at else None,
            "provider": "resend" if settings.RESEND_API_KEY else "smtp",
            "from": settings.RESEND_FROM_EMAIL if settings.RESEND_API_KEY else settings.DEFAULT_FROM_EMAIL,
            **summary,
        }
    )


def _ensure_order_images(order):
    required_fields = [order.processed_image, order.print_template, order.preview_image]
    if all(_field_exists(field) for field in required_fields):
        return

    try:
        _regenerate_order_images(order)
        order.refresh_from_db()
    except Exception:
        logger.exception("Could not regenerate paid order image files for order %s", order.id)


def _field_exists(field):
    return bool(field and field.name and field.storage.exists(field.name))


@csrf_exempt
@require_POST
def stripe_webhook(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    if settings.STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        except (ValueError, stripe.SignatureVerificationError):
            return HttpResponseBadRequest("Invalid Stripe webhook payload.")
    else:
        try:
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
        except Exception:
            return HttpResponseBadRequest("Stripe webhook secret is missing.")

    if event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id and session.get("payment_status") == "paid":
            Order.objects.filter(id=order_id).update(
                status=Order.Status.PAID,
                selected_package=session.get("metadata", {}).get("package", ""),
                stripe_session_id=session.get("id", ""),
            )
            order = Order.objects.filter(id=order_id).first()
            if order:
                mark_user_paid(order.email)
                send_delivery_email(order)
    elif event["type"] == "checkout.session.async_payment_failed":
        session = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id:
            Order.objects.filter(id=order_id).update(status=Order.Status.FAILED)

    return HttpResponse(status=200)
