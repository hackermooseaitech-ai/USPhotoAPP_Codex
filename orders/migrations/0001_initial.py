import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")], default="pending", max_length=16)),
                ("stripe_session_id", models.CharField(blank=True, max_length=255)),
                ("original_image", models.ImageField(upload_to="orders/original/")),
                ("processed_image", models.ImageField(blank=True, upload_to="orders/processed/")),
                ("preview_image", models.ImageField(blank=True, upload_to="orders/previews/")),
                ("print_template", models.ImageField(blank=True, upload_to="orders/print_templates/")),
                ("s3_key", models.CharField(blank=True, max_length=512)),
                ("processing_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
