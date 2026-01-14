from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models

from core.models import MerchantOwnedModel, TimeStampedUUIDModel, DECIMAL_ZERO


class VariantKind(models.TextChoices):
    DIRECT = "DIRECT", "Direct"
    BOOKING = "BOOKING", "Booking"
    WEIGHT = "WEIGHT", "Weight"


class Product(MerchantOwnedModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "slug"], name="uniq_product_slug_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
            models.Index(fields=["merchant", "slug"]),
        ]

    def __str__(self) -> str:
        return self.name


class ProductVariant(MerchantOwnedModel):
    """
    Lo vendible = variante (SKU).
    - DIRECT: precio por unidad
    - BOOKING: precio por reserva
    - WEIGHT: precio se calcula con WeightSettings.price_per_gram
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")

    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True)

    kind = models.CharField(max_length=16, choices=VariantKind.choices)

    # Para DIRECT/BOOKING:
    unit_price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)

    currency = models.CharField(max_length=3)  # si el merchant usa una sola, puedes moverlo a Merchant

    track_inventory = models.BooleanField(default=True)  # normalmente False para BOOKING
    is_active = models.BooleanField(default=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "sku"], name="uniq_sku_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "sku"]),
            models.Index(fields=["merchant", "kind"]),
            models.Index(fields=["merchant", "is_active"]),
        ]

    def clean(self):
        if self.product_id and self.product.merchant_id != self.merchant_id:
            raise ValidationError("merchant de variant y product no coinciden.")
        if self.kind in (VariantKind.DIRECT, VariantKind.BOOKING):
            if self.unit_price_amount is None or self.unit_price_amount < Decimal("0.00"):
                raise ValidationError({"unit_price_amount": "unit_price_amount debe ser >= 0."})
        if self.kind == VariantKind.WEIGHT:
            # unit_price_amount puede quedar en 0 para WEIGHT (precio se obtiene de WeightSettings)
            if self.unit_price_amount is None:
                self.unit_price_amount = DECIMAL_ZERO
        if not self.currency:
            raise ValidationError({"currency": "currency es requerido."})

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.sku}"


class ProductMedia(TimeStampedUUIDModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="media")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE, related_name="media")

    file = models.FileField(upload_to="products/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["product", "sort_order"]),
            models.Index(fields=["variant", "sort_order"]),
        ]

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError("variant no pertenece a product.")


class BookingSettings(TimeStampedUUIDModel):
    """
    Config para variantes BOOKING.
    """
    variant = models.OneToOneField(ProductVariant, on_delete=models.CASCADE, related_name="booking_settings")

    duration_minutes = models.PositiveIntegerField(default=60)
    slot_step_minutes = models.PositiveIntegerField(default=30)  # grilla para UI

    capacity_per_slot = models.PositiveIntegerField(default=1)  # 1 = cita individual

    buffer_before_minutes = models.PositiveIntegerField(default=0)
    buffer_after_minutes = models.PositiveIntegerField(default=0)

    # Ej: direccion/meet link:
    location = models.CharField(max_length=255, blank=True)

    def clean(self):
        if self.slot_step_minutes <= 0:
            raise ValidationError({"slot_step_minutes": "Debe ser > 0."})
        if self.duration_minutes <= 0:
            raise ValidationError({"duration_minutes": "Debe ser > 0."})
        if self.capacity_per_slot <= 0:
            raise ValidationError({"capacity_per_slot": "Debe ser > 0."})


class WeightSettings(TimeStampedUUIDModel):
    """
    Config para variantes WEIGHT.
    Recomendacion: trabajar internamente en gramos (int).
    """
    variant = models.OneToOneField(ProductVariant, on_delete=models.CASCADE, related_name="weight_settings")

    # Control de compra:
    step_grams = models.PositiveIntegerField(default=50)
    min_grams = models.PositiveIntegerField(default=50)
    max_grams = models.PositiveIntegerField(null=True, blank=True)

    # Precio por gramo:
    price_per_gram_amount = models.DecimalField(max_digits=12, decimal_places=6)

    def clean(self):
        if self.step_grams <= 0:
            raise ValidationError({"step_grams": "Debe ser > 0."})
        if self.min_grams <= 0:
            raise ValidationError({"min_grams": "Debe ser > 0."})
        if self.max_grams is not None and self.max_grams < self.min_grams:
            raise ValidationError({"max_grams": "max_grams debe ser >= min_grams."})
        if self.price_per_gram_amount is None or self.price_per_gram_amount < Decimal("0"):
            raise ValidationError({"price_per_gram_amount": "Debe ser >= 0."})

    def normalize_grams(self, grams: int) -> int:
        """
        Ajusta a step, y respeta min/max.
        Ej: si step=50 y piden 230g -> 250g (redondeo hacia arriba).
        """
        if grams <= 0:
            raise ValidationError("grams debe ser > 0")

        # redondeo hacia arriba al step:
        step = int(self.step_grams)
        normalized = ((grams + step - 1) // step) * step

        if normalized < self.min_grams:
            normalized = self.min_grams
        if self.max_grams is not None and normalized > self.max_grams:
            normalized = self.max_grams
        return normalized

    def price_for_grams(self, grams: int) -> Decimal:
        grams = self.normalize_grams(grams)
        return (Decimal(grams) * self.price_per_gram_amount).quantize(Decimal("0.01"))
