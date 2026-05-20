from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0008_order_selected_package"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="background",
            field=models.CharField(
                choices=[
                    ("white", "White"),
                    ("soft_white", "Soft white gray"),
                    ("light_gray", "Light off-white gray"),
                ],
                default="white",
                max_length=16,
            ),
        ),
    ]
