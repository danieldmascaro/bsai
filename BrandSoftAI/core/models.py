import uuid
from decimal import Decimal
from django.db import models


class TimeStampedUUIDModel(models.Model):
    """
    Base seria para ecommerce: UUID + timestamps + indices temporales.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MerchantOwnedModel(TimeStampedUUIDModel):
    """
    Multi-tenant: todo cuelga de merchant (tienda).
    """
    merchant = models.ForeignKey(
        "accounts.Merchant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)ss",
    )

    class Meta:
        abstract = True


DECIMAL_ZERO = Decimal("0.00")
