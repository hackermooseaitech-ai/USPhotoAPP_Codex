from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("id", "email", "stripe_session_id")
    readonly_fields = ("id", "created_at", "updated_at")
