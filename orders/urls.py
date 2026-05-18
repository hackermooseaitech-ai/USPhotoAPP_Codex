from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload_photo, name="upload"),
    path("edit/<uuid:order_id>/", views.edit_photo, name="edit"),
    path("adjust/<uuid:order_id>/", views.adjust_photo, name="adjust"),
    path("packages/<uuid:order_id>/", views.packages, name="packages"),
    path("checkout/<uuid:order_id>/<str:package>/", views.create_checkout_session, name="checkout"),
    path("preview/<uuid:order_id>/", views.preview_file, name="preview"),
    path("final/<uuid:order_id>/", views.final_photo_file, name="final_photo"),
    path("success/<uuid:order_id>/", views.success, name="success"),
    path("download/<uuid:order_id>/<str:kind>/", views.download_file, name="download"),
    path("admin-tools/test-email/", views.test_email, name="test_email"),
    path("admin-tools/resend-order/<uuid:order_id>/", views.resend_order_email, name="resend_order_email"),
    path("admin-tools/order-status/<uuid:order_id>/", views.order_delivery_status, name="order_delivery_status"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
