import json
from pathlib import Path

import stripe
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import PhotoUploadForm
from .models import Order
from .services.delivery import send_delivery_email
from .services.photo_processor import FaceGeometry, prepare_photo_source, process_order_photo, render_visa_photo

MIN_HEAD_RATIO = 0.53
MAX_HEAD_RATIO = 0.62
RATIO_STEP = 0.01
OFFSET_STEP = 18
MAX_OFFSET = 96


def index(request):
    providers = settings.SOCIALACCOUNT_PROVIDERS
    social_login = None
    if request.user.is_authenticated:
        account = request.user.socialaccount_set.order_by("-id").first()
        if account:
            social_login = {
                "provider": account.get_provider().name,
                "email": account.extra_data.get("email") or request.user.email or request.user.username,
            }
    return render(
        request,
        "orders/index.html",
        {
            "form": PhotoUploadForm(),
            "google_oauth_ready": bool(providers.get("google", {}).get("APPS")),
            "social_login": social_login,
        },
    )


@require_POST
def upload_photo(request):
    form = PhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "orders/_upload_form.html", {"form": form}, status=422)

    order = form.save()
    prepared = prepare_photo_source(order.original_image)
    version = order.updated_at.strftime("%Y%m%d%H%M%S")
    order.prepared_image.save(f"{order.id}-{version}-prepared.jpg", prepared.prepared_jpeg, save=False)
    _set_order_face(order, prepared.face)
    _regenerate_order_images(order, base_notes=prepared.notes)

    return render(request, "orders/_preview_card.html", {"order": order})


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
        order.crop_offset_y = 0
    else:
        return HttpResponseBadRequest("Unknown adjustment.")

    _regenerate_order_images(order)
    return render(request, "orders/_preview_card.html", {"order": order})


def _regenerate_order_images(order, base_notes=None):
    if order.prepared_image:
        processed = render_visa_photo(
            order.prepared_image,
            _order_face(order),
            notes=base_notes,
            head_ratio=order.crop_head_ratio,
            offset_x=order.crop_offset_x,
            offset_y=order.crop_offset_y,
        )
    else:
        processed = process_order_photo(
            order.original_image,
            head_ratio=order.crop_head_ratio,
            offset_x=order.crop_offset_x,
            offset_y=order.crop_offset_y,
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


@require_POST
def create_checkout_session(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if order.status == Order.Status.PAID:
        return redirect("orders:success", order_id=order.id)

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe is not configured yet. Add STRIPE_SECRET_KEY to .env.")
        return redirect("orders:index")

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
                        "product_data": {"name": "Hacker Moose US Visa Photo"},
                        "unit_amount": settings.STRIPE_PRICE_CENTS,
                    },
                    "quantity": 1,
                }
            ],
            metadata={"order_id": str(order.id)},
            success_url=f"{settings.SITE_URL}{reverse('orders:success', args=[order.id])}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.SITE_URL}{reverse('orders:index')}",
        )
    except stripe.StripeError as exc:
        messages.error(request, f"Stripe checkout could not be created: {exc.user_message or str(exc)}")
        return redirect("orders:index")

    order.stripe_session_id = session.id
    order.save(update_fields=["stripe_session_id", "updated_at"])
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
        else:
            if session.get("metadata", {}).get("order_id") == str(order.id) and session.get("payment_status") == "paid":
                order.status = Order.Status.PAID
                order.stripe_session_id = session.id
                order.save(update_fields=["status", "stripe_session_id", "updated_at"])

    if order.status == Order.Status.PAID and order.email and not order.delivery_email_sent_at:
        send_delivery_email(order, request=request)
    return render(request, "orders/success.html", {"order": order})


def preview_file(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not order.preview_image:
        raise Http404("Preview is not available.")

    filename = Path(order.preview_image.name).name
    response = FileResponse(order.preview_image.open("rb"), filename=filename)
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

    filename = Path(field.name).name
    return FileResponse(field.open("rb"), as_attachment=True, filename=filename)


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
                stripe_session_id=session.get("id", ""),
            )
            order = Order.objects.filter(id=order_id).first()
            if order:
                send_delivery_email(order)
    elif event["type"] == "checkout.session.async_payment_failed":
        session = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id:
            Order.objects.filter(id=order_id).update(status=Order.Status.FAILED)

    return HttpResponse(status=200)
