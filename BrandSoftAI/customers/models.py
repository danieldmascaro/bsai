from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import MerchantOwnedModel, TimeStampedUUIDModel


class Customer(MerchantOwnedModel):
    """
    Cliente asociado a un merchant (tienda).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customer_profiles"
    )
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "email"], name="uniq_customer_email_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "email"]),
            models.Index(fields=["merchant", "is_active"]),
        ]

    def clean(self):
        if not self.email:
            raise ValidationError({"email": "email es requerido."})

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.email}"


class CustomerAddress(TimeStampedUUIDModel):
    """
    Direccion del cliente (opcional).
    """
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=64, blank=True)

    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128)
    region = models.CharField(max_length=128, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=2)

    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["customer"],
                condition=Q(is_default=True),
                name="uniq_default_address_per_customer",
            ),
        ]

    def clean(self):
        if not self.line1:
            raise ValidationError({"line1": "line1 es requerido."})
        if not self.city:
            raise ValidationError({"city": "city es requerido."})
        if not self.country:
            raise ValidationError({"country": "country es requerido."})
