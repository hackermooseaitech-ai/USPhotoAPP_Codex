from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_order_delivery_email_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="crop_head_ratio",
            field=models.FloatField(default=0.6),
        ),
        migrations.AddField(
            model_name="order",
            name="crop_offset_x",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="order",
            name="crop_offset_y",
            field=models.FloatField(default=0),
        ),
    ]
