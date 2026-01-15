from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F

from core.models import MerchantOwnedModel, TimeStampedUUIDModel, DECIMAL_ZERO
from catalog.models import VariantKind


class OrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FULFILLED = "FULFILLED", "Fulfilled"
    CANCELLED = "CANCELLED", "Cancelled"


class Order(MerchantOwnedModel):
    """
    Orden confirmada. Se crea al convertir el carrito.
    """
    status = models.CharField(max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING)

    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders"
    )

    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    currency = models.CharField(max_length=3)

    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "status", "created_at"]),
            models.Index(fields=["merchant", "customer", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(currency=""), name="chk_order_currency_not_empty"),
        ]

    def clean(self):
        if not self.currency:
            raise ValidationError({"currency": "currency es requerido."})
        if self.customer_id and self.customer.merchant_id != self.merchant_id:
            raise ValidationError("merchant de order y customer no coinciden.")

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.id}:{self.status}"


class OrderLine(TimeStampedUUIDModel):
    """
    Linea final de orden (snapshot de la venta).
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.PROTECT, related_name="order_lines"
    )

    kind = models.CharField(max_length=16, choices=VariantKind.choices)
    sku_snapshot = models.CharField(max_length=64, blank=True)
    product_name_snapshot = models.CharField(max_length=255, blank=True)
    variant_name_snapshot = models.CharField(max_length=255, blank=True)

    quantity_each = models.PositiveIntegerField(default=0)
    quantity_grams = models.PositiveBigIntegerField(default=0)

    scheduled_start_at = models.DateTimeField(null=True, blank=True)
    scheduled_end_at = models.DateTimeField(null=True, blank=True)
    resource = models.ForeignKey(
        "scheduling.Resource", null=True, blank=True,
        on_delete=models.PROTECT, related_name="order_lines"
    )

    unit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    unit_amount_per_gram = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0.000000"))
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["variant"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=VariantKind.DIRECT,
                        quantity_each__gt=0,
                        quantity_grams=0,
                        scheduled_start_at__isnull=True,
                        scheduled_end_at__isnull=True,
                        resource__isnull=True,
                    )
                    | Q(
                        kind=VariantKind.WEIGHT,
                        quantity_each=0,
                        quantity_grams__gt=0,
                        scheduled_start_at__isnull=True,
                        scheduled_end_at__isnull=True,
                        resource__isnull=True,
                    )
                    | Q(
                        kind=VariantKind.BOOKING,
                        quantity_each__gt=0,
                        quantity_grams=0,
                        scheduled_start_at__isnull=False,
                        scheduled_end_at__isnull=False,
                        resource__isnull=False,
                        scheduled_end_at__gt=F("scheduled_start_at"),
                    )
                ),
                name="chk_orderline_kind_quantities_and_times",
            ),
        ]

    def clean(self):
        if self.kind and self.variant and self.kind != self.variant.kind:
            raise ValidationError({"kind": "kind debe coincidir con variant.kind."})
        if self.order_id and self.variant_id and self.order.merchant_id != self.variant.merchant_id:
            raise ValidationError("merchant de order y variant no coinciden.")
        if self.resource_id and self.order_id and self.resource.merchant_id != self.order.merchant_id:
            raise ValidationError("merchant de order y resource no coinciden.")
        if self.kind == VariantKind.BOOKING and not self.resource_id:
            raise ValidationError({"resource": "BOOKING requiere resource."})

    def save(self, *args, **kwargs):
        if self.variant_id:
            self.kind = self.kind or self.variant.kind
            if not self.sku_snapshot:
                self.sku_snapshot = self.variant.sku
            if not self.variant_name_snapshot:
                self.variant_name_snapshot = self.variant.name
            if not self.product_name_snapshot and self.variant_id:
                self.product_name_snapshot = self.variant.product.name
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.order_id}:{self.kind}:{self.sku_snapshot or self.variant_id}"
