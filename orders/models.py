import uuid

from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    stripe_session_id = models.CharField(max_length=255, blank=True)
    original_image = models.ImageField(upload_to="orders/original/")
    processed_image = models.ImageField(upload_to="orders/processed/", blank=True)
    preview_image = models.ImageField(upload_to="orders/previews/", blank=True)
    print_template = models.ImageField(upload_to="orders/print_templates/", blank=True)
    s3_key = models.CharField(max_length=512, blank=True)
    processing_notes = models.TextField(blank=True)
    crop_head_ratio = models.FloatField(default=0.60)
    crop_offset_x = models.FloatField(default=0)
    crop_offset_y = models.FloatField(default=0)
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
