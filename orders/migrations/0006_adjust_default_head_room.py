from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_order_prepared_image_face_cache"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="crop_offset_y",
            field=models.FloatField(default=24),
        ),
    ]
