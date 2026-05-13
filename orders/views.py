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
from .services.photo_processor import process_order_photo


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
    processed = process_order_photo(order.original_image)
    version = order.updated_at.strftime("%Y%m%d%H%M%S")
    order.processed_image.save(f"{order.id}-{version}-visa-photo-600.jpg", processed.final_jpeg, save=False)
    order.preview_image.save(f"{order.id}-{version}-preview.jpg", processed.preview_jpeg, save=False)
    order.print_template.save(f"{order.id}-{version}-4x6.jpg", processed.print_template_jpeg, save=False)
    order.s3_key = order.processed_image.name
    order.processing_notes = "\n".join(processed.notes)
    order.save(update_fields=["processed_image", "preview_image", "print_template", "s3_key", "processing_notes", "updated_at"])

    return render(request, "orders/_preview_card.html", {"order": order})


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
