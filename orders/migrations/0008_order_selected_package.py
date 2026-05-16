from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0007_lower_default_eye_line"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="selected_package",
            field=models.CharField(blank=True, choices=[("photo", "2x2 Photo"), ("print", "4x6 Print"), ("bundle", "2x2 + 4x6")], max_length=16),
        ),
    ]
