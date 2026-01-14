from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import MerchantOwnedModel, TimeStampedUUIDModel, DECIMAL_ZERO


class DiscountType(models.TextChoices):
    PERCENT = "PERCENT", "Percent"
    FIXED = "FIXED", "Fixed"


class VoucherAppliesTo(models.TextChoices):
    ORDER_SUBTOTAL = "ORDER_SUBTOTAL", "Order subtotal"
    SHIPPING = "SHIPPING", "Shipping"


class Voucher(MerchantOwnedModel):
    """
    Cupon por merchant.
    """
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=255, blank=True)

    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)  # % o monto
    currency = models.CharField(max_length=3, blank=True)  # requerido si FIXED
    applies_to = models.CharField(max_length=20, choices=VoucherAppliesTo.choices, default=VoucherAppliesTo.ORDER_SUBTOTAL)

    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    min_subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    max_uses = models.PositiveIntegerField(null=True, blank=True)
    max_uses_per_customer = models.PositiveIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "code"], name="uniq_voucher_code_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
            models.Index(fields=["merchant", "code"]),
        ]

    def clean(self):
        if self.discount_type == DiscountType.PERCENT:
            if self.value <= 0 or self.value > Decimal("100"):
                raise ValidationError({"value": "Para PERCENT, value debe estar entre (0, 100]."})
        if self.discount_type == DiscountType.FIXED:
            if not self.currency:
                raise ValidationError({"currency": "currency es requerido para FIXED."})
            if self.value < Decimal("0.00"):
                raise ValidationError({"value": "Para FIXED, value debe ser >= 0."})
        if self.min_subtotal_amount is not None and self.min_subtotal_amount < DECIMAL_ZERO:
            raise ValidationError({"min_subtotal_amount": "min_subtotal_amount debe ser >= 0."})
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "end_at debe ser > start_at."})

    def is_currently_valid(self, now=None) -> bool:
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True

    def compute_discount_amount(
        self,
        *,
        subtotal_amount: Decimal,
        shipping_amount: Decimal,
        currency: str,
    ) -> Decimal:
        """
        Calculo puro (sin DB):
        - Aplica sobre subtotal o shipping segun applies_to
        - No excede la base
        """
        if not self.is_currently_valid():
            return DECIMAL_ZERO

        base = subtotal_amount if self.applies_to == VoucherAppliesTo.ORDER_SUBTOTAL else shipping_amount
        if base <= DECIMAL_ZERO:
            return DECIMAL_ZERO

        if self.min_subtotal_amount is not None and subtotal_amount < self.min_subtotal_amount:
            return DECIMAL_ZERO

        if self.discount_type == DiscountType.PERCENT:
            disc = (base * (self.value / Decimal("100.0"))).quantize(Decimal("0.01"))
            return min(disc, base)

        # FIXED
        if self.currency and self.currency != currency:
            return DECIMAL_ZERO

        disc = min(self.value, base)
        return disc.quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.code}"


class VoucherRedemption(TimeStampedUUIDModel):
    """
    Registro de uso (para limites / auditoria).
    """
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="redemptions")
    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="voucher_redemption")

    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="voucher_redemptions"
    )

    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["voucher", "redeemed_at"]),
            models.Index(fields=["customer", "redeemed_at"]),
        ]


class PromotionActionType(models.TextChoices):
    PERCENT = "PERCENT", "Percent"
    FIXED = "FIXED", "Fixed"


class Promotion(MerchantOwnedModel):
    """
    Promocion automatica.
    - predicate: JSON con reglas (ej: minimo, categorias, kind, etc.)
    - action_*: define el descuento
    La evaluacion se implementa en un servicio (rule engine simple).
    """
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    predicate = models.JSONField(default=dict, blank=True)  # reglas
    action_type = models.CharField(max_length=10, choices=PromotionActionType.choices)
    action_value = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, blank=True)  # para FIXED

    stackable = models.BooleanField(default=True)  # si se puede combinar

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
        ]

    def clean(self):
        if self.action_type == PromotionActionType.PERCENT:
            if self.action_value <= 0 or self.action_value > Decimal("100"):
                raise ValidationError({"action_value": "Para PERCENT, action_value debe estar entre (0, 100]."})
        if self.action_type == PromotionActionType.FIXED:
            if not self.currency:
                raise ValidationError({"currency": "currency es requerido para FIXED."})
            if self.action_value < Decimal("0.00"):
                raise ValidationError({"action_value": "Para FIXED, action_value debe ser >= 0."})
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "end_at debe ser > start_at."})

    def is_currently_valid(self, now=None) -> bool:
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True
