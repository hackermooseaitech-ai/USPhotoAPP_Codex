from django import forms

from .models import Order


class PhotoUploadForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["email", "original_image"]
        widgets = {
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "email@example.com",
                    "class": "input",
                    "autocomplete": "email",
                }
            ),
            "original_image": forms.ClearableFileInput(
                attrs={
                    "accept": "image/*",
                    "class": "file-input",
                }
            ),
        }

    def clean_original_image(self):
        image = self.cleaned_data["original_image"]
        if image.size > 12 * 1024 * 1024:
            raise forms.ValidationError("Please upload an image smaller than 12 MB.")
        return image
