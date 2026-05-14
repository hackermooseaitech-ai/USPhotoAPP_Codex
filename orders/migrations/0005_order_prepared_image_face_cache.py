from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0004_order_crop_adjustments"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="prepared_image",
            field=models.ImageField(blank=True, upload_to="orders/prepared/"),
        ),
        migrations.AddField(
            model_name="order",
            name="face_center_x",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="face_eye_y",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="face_head_top_y",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="face_chin_y",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
