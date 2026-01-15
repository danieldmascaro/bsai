from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F

from core.models import MerchantOwnedModel, TimeStampedUUIDModel, DECIMAL_ZERO
from catalog.models import VariantKind


class CartStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CHECKOUT = "CHECKOUT", "Checkout"      # optional: when payment starts
    CONVERTED = "CONVERTED", "Converted"   # already created Order
    ABANDONED = "ABANDONED", "Abandoned"


class Cart(MerchantOwnedModel):
    """
    Carrito por merchant.
    - Soporta logged-in y guest (token).
    - customer es opcional (si quieres CRM), pero puedes manejarlo solo con email.
    """
    status = models.CharField(max_length=12, choices=CartStatus.choices, default=CartStatus.ACTIVE)

    # Identidad
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="carts"
    )
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="carts"
    )
    token = models.CharField(max_length=64, blank=True)  # guest cookie/localStorage token
    email = models.EmailField(blank=True)                # guest snapshot (useful for prefill)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    currency = models.CharField(max_length=3)

    # Coupon (preview; does not redeem yet)
    voucher = models.ForeignKey(
        "promotions.Voucher", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="carts"
    )
    voucher_code_snapshot = models.CharField(max_length=40, blank=True)

    # Totales (puedes calcular al vuelo; guardarlos ayuda a performance)
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)

    # Para enlazar con Order cuando conviertes:
    converted_order = models.OneToOneField(
        "orders.Order", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="source_cart"
    )

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "status", "created_at"]),
            models.Index(fields=["merchant", "user", "status"]),
            models.Index(fields=["merchant", "token", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(currency=""),
                name="chk_cart_currency_not_empty",
            ),
            models.CheckConstraint(
                condition=~(Q(user__isnull=True) & Q(customer__isnull=True) & Q(token="")),
                name="chk_cart_has_identity",
            ),
            # Token unico por merchant si se usa (guest carts)
            models.UniqueConstraint(
                fields=["merchant", "token"],
                condition=Q(token__gt=""),
                name="uniq_cart_token_per_merchant_when_present",
            ),
        ]

    def clean(self):
        if not self.currency:
            raise ValidationError({"currency": "currency es requerido."})
        # Asegura alguna forma de identificacion
        if not self.user and not self.customer and not self.token:
            # Permitimos carritos anonimos sin token? si no, fuerza token.
            raise ValidationError("Cart debe tener user, customer o token (guest).")

    def __str__(self) -> str:
        ident = self.user_id or self.customer_id or self.token or "anonymous"
        return f"{self.merchant.slug}:{ident}:{self.status}"


class CartLine(TimeStampedUUIDModel):
    """
    Linea de carrito.
    - Guarda cantidades (each o grams) y, si es BOOKING, el horario elegido.
    - NO congela precio definitivo (eso ocurre al crear OrderLine), pero puede guardar
      un snapshot para UI si quieres.
    """
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.PROTECT, related_name="+"
    )

    # Snapshot ligero para UI / estabilidad si cambian cosas:
    kind = models.CharField(max_length=16, choices=VariantKind.choices)
    sku_snapshot = models.CharField(max_length=64, blank=True)
    product_name_snapshot = models.CharField(max_length=255, blank=True)
    variant_name_snapshot = models.CharField(max_length=255, blank=True)

    # Cantidades:
    quantity_each = models.PositiveIntegerField(default=0)
    quantity_grams = models.PositiveBigIntegerField(default=0)

    # Booking:
    scheduled_start_at = models.DateTimeField(null=True, blank=True)
    scheduled_end_at = models.DateTimeField(null=True, blank=True)
    resource = models.ForeignKey(
        "scheduling.Resource", null=True, blank=True,
        on_delete=models.PROTECT, related_name="cart_lines"
    )

    # Preview price (optional): if saved, recompute on each cart change.
    unit_amount_preview = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    unit_amount_per_gram_preview = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0.000000"))
    line_subtotal_preview = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["cart"]),
            models.Index(fields=["variant"]),
        ]
        constraints = [
            # Evita duplicar la misma variante en el carrito para DIRECT/WEIGHT
            # (booking se maneja distinto porque misma variante puede repetirse con horas distintas)
            models.UniqueConstraint(
                fields=["cart", "variant"],
                condition=Q(kind__in=[VariantKind.DIRECT, VariantKind.WEIGHT]),
                name="uniq_cart_variant_for_direct_weight",
            ),
            # Para BOOKING, evitamos duplicados exactos de la misma hora:
            models.UniqueConstraint(
                fields=["cart", "variant", "scheduled_start_at", "scheduled_end_at", "resource"],
                condition=Q(kind=VariantKind.BOOKING),
                name="uniq_cart_booking_same_timespan",
            ),
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
                name="chk_cartline_kind_quantities_and_times",
            ),
        ]

    def clean(self):
        # Mantener coherencia kind con variant.kind (en servicios lo seteas)
        if self.kind and self.variant and self.kind != self.variant.kind:
            raise ValidationError({"kind": "kind debe coincidir con variant.kind."})

        if self.cart_id and self.variant_id and self.cart.merchant_id != self.variant.merchant_id:
            raise ValidationError("merchant del cart y variant no coinciden.")
        if self.resource_id and self.cart_id and self.resource.merchant_id != self.cart.merchant_id:
            raise ValidationError("merchant del cart y resource no coinciden.")

        if self.kind == VariantKind.DIRECT:
            if self.quantity_each <= 0:
                raise ValidationError({"quantity_each": "Debe ser > 0 para DIRECT."})
            if self.quantity_grams != 0:
                raise ValidationError({"quantity_grams": "Debe ser 0 para DIRECT."})
            if self.scheduled_start_at or self.scheduled_end_at:
                raise ValidationError("DIRECT no puede tener horario.")

        if self.kind == VariantKind.WEIGHT:
            if self.quantity_grams <= 0:
                raise ValidationError({"quantity_grams": "Debe ser > 0 para WEIGHT."})
            if self.quantity_each != 0:
                raise ValidationError({"quantity_each": "Debe ser 0 para WEIGHT."})
            if self.scheduled_start_at or self.scheduled_end_at:
                raise ValidationError("WEIGHT no puede tener horario.")

        if self.kind == VariantKind.BOOKING:
            if not self.scheduled_start_at or not self.scheduled_end_at:
                raise ValidationError("BOOKING requiere scheduled_start_at y scheduled_end_at.")
            if self.scheduled_end_at <= self.scheduled_start_at:
                raise ValidationError("scheduled_end_at debe ser > scheduled_start_at.")
            if not self.resource_id:
                raise ValidationError({"resource": "BOOKING requiere resource."})
            # Normalmente quantity_each=1, pero puedes usarlo como "cupos"
            if self.quantity_each <= 0:
                raise ValidationError({"quantity_each": "Debe ser > 0 para BOOKING."})

    def save(self, *args, **kwargs):
        """
        Auto-populates basic snapshots when empty.
        (Esto ayuda a que la UI no dependa de joins para mostrar el carrito.)
        """
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
        return f"{self.cart_id}:{self.kind}:{self.sku_snapshot or self.variant_id}"


class CartAppliedDiscount(TimeStampedUUIDModel):
    """
    Descuento aplicado al carrito (preview / UI).
    El definitivo se registra en OrderAppliedDiscount / OrderLineAppliedDiscount.
    """
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="applied_discounts")

    source_type = models.CharField(max_length=16)  # "VOUCHER" / "PROMOTION" / "MANUAL"
    source_ref = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=255, blank=True)
    code = models.CharField(max_length=40, blank=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=DECIMAL_ZERO)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["cart"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=DECIMAL_ZERO),
                name="chk_cart_applied_discount_amount_nonnegative",
            ),
        ]
