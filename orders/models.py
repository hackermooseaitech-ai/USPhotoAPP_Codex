import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    class Package(models.TextChoices):
        PHOTO = "photo", "2x2 Photo"
        PRINT = "print", "4x6 Print"
        BUNDLE = "bundle", "2x2 + 4x6"

    class Background(models.TextChoices):
        WHITE = "white", "White"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    selected_package = models.CharField(max_length=16, choices=Package.choices, blank=True)
    stripe_session_id = models.CharField(max_length=255, blank=True)
    original_image = models.ImageField(upload_to="orders/original/")
    prepared_image = models.ImageField(upload_to="orders/prepared/", blank=True)
    processed_image = models.ImageField(upload_to="orders/processed/", blank=True)
    preview_image = models.ImageField(upload_to="orders/previews/", blank=True)
    print_template = models.ImageField(upload_to="orders/print_templates/", blank=True)
    s3_key = models.CharField(max_length=512, blank=True)
    processing_notes = models.TextField(blank=True)
    crop_head_ratio = models.FloatField(default=0.55)
    crop_offset_x = models.FloatField(default=0)
    crop_offset_y = models.FloatField(default=54)
    background = models.CharField(max_length=16, choices=Background.choices, default=Background.WHITE)
    face_center_x = models.FloatField(null=True, blank=True)
    face_eye_y = models.FloatField(null=True, blank=True)
    face_head_top_y = models.FloatField(null=True, blank=True)
    face_chin_y = models.FloatField(null=True, blank=True)
    delivery_email_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id} ({self.status})"

    @property
    def crop_head_percent(self):
        return round(self.crop_head_ratio * 100)

    @property
    def crop_head_progress_percent(self):
        return round(((self.crop_head_ratio - 0.53) / 0.09) * 100)


class UserLoginRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_records")
    email = models.EmailField(blank=True)
    provider = models.CharField(max_length=64, default="email")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email or self.user_id} via {self.provider} at {self.created_at:%Y-%m-%d %H:%M:%S}"
