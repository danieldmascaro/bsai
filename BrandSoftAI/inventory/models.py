from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from core.models import MerchantOwnedModel


class Warehouse(MerchantOwnedModel):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "name"], name="uniq_warehouse_name_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.name}"


class Stock(MerchantOwnedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stocks")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="stocks")

    # DIRECT: unidades; WEIGHT: gramos
    quantity = models.PositiveBigIntegerField(default=0)
    allocated = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "variant"], name="uniq_stock_warehouse_variant"),
            models.CheckConstraint(condition=Q(allocated__lte=F("quantity")), name="chk_allocated_lte_quantity"),
        ]
        indexes = [
            models.Index(fields=["merchant", "variant"]),
            models.Index(fields=["merchant", "warehouse"]),
        ]

    def clean(self):
        if self.warehouse_id and self.warehouse.merchant_id != self.merchant_id:
            raise ValidationError("merchant de stock y warehouse no coinciden.")
        if self.variant_id and self.variant.merchant_id != self.merchant_id:
            raise ValidationError("merchant de stock y variant no coinciden.")

    @property
    def available(self) -> int:
        return int(self.quantity - self.allocated)
