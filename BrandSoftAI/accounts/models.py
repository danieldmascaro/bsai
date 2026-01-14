from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import TimeStampedUUIDModel


class Merchant(TimeStampedUUIDModel):
    """
    Tenant (tienda). Un usuario puede tener varios merchants.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_merchants",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64, unique=True)

    default_currency = models.CharField(max_length=3, default="USD")
    timezone = models.CharField(max_length=64, default="UTC")  # ej: "America/Santiago"

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class MerchantRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    STAFF = "STAFF", "Staff"


class MerchantMember(TimeStampedUUIDModel):
    """
    Opcional pero recomendable: permite equipo.
    """
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="merchant_memberships"
    )
    role = models.CharField(max_length=16, choices=MerchantRole.choices, default=MerchantRole.STAFF)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "user"], name="uniq_member_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.user_id}:{self.role}"
