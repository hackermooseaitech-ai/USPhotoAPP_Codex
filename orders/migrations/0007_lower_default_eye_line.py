from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_adjust_default_head_room"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="crop_offset_y",
            field=models.FloatField(default=54),
        ),
    ]
