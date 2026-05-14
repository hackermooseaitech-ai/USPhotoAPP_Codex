from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.index, name="index"),
    path("upload/", views.upload_photo, name="upload"),
    path("edit/<uuid:order_id>/", views.edit_photo, name="edit"),
    path("adjust/<uuid:order_id>/", views.adjust_photo, name="adjust"),
    path("checkout/<uuid:order_id>/", views.create_checkout_session, name="checkout"),
    path("preview/<uuid:order_id>/", views.preview_file, name="preview"),
    path("success/<uuid:order_id>/", views.success, name="success"),
    path("download/<uuid:order_id>/<str:kind>/", views.download_file, name="download"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
