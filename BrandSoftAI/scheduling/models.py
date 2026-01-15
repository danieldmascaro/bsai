from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.utils import timezone

from core.models import MerchantOwnedModel, TimeStampedUUIDModel

# Recomendado para Postgres:
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField
from django.contrib.postgres.fields.ranges import RangeOperators


class Resource(MerchantOwnedModel):
    """
    Un recurso agendable: staff, box, sala, etc.
    """
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "name"], name="uniq_resource_name_per_merchant"),
        ]
        indexes = [
            models.Index(fields=["merchant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.slug}:{self.name}"


class VariantResource(TimeStampedUUIDModel):
    """
    Relacion N-M: que variantes BOOKING pueden usar que recursos.
    """
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="resource_links")
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="variant_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["variant", "resource"], name="uniq_variant_resource"),
        ]
        indexes = [
            models.Index(fields=["resource", "variant"]),
        ]

    def clean(self):
        if self.variant_id and self.resource_id and self.variant.merchant_id != self.resource.merchant_id:
            raise ValidationError("merchant de variant y resource no coinciden.")


class Weekday(models.IntegerChoices):
    MON = 0, "Mon"
    TUE = 1, "Tue"
    WED = 2, "Wed"
    THU = 3, "Thu"
    FRI = 4, "Fri"
    SAT = 5, "Sat"
    SUN = 6, "Sun"


class AvailabilityRule(MerchantOwnedModel):
    """
    Regla semanal: (weekday, start_time - end_time).
    La logica de "generar slots" se hace en servicios.
    """
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="availability_rules")

    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "resource", "weekday"]),
            models.Index(fields=["merchant", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="chk_availability_rule_time_range",
            ),
        ]

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError("end_time debe ser > start_time")
        if self.resource_id and self.resource.merchant_id != self.merchant_id:
            raise ValidationError("merchant de rule y resource no coinciden.")


class OverrideKind(models.TextChoices):
    BLOCK = "BLOCK", "Block"
    ADD = "ADD", "Add"


class AvailabilityOverride(MerchantOwnedModel):
    """
    Excepcion: bloquear o agregar disponibilidad en un rango datetime.
    """
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="availability_overrides")

    kind = models.CharField(max_length=8, choices=OverrideKind.choices, default=OverrideKind.BLOCK)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    note = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "resource", "start_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")),
                name="chk_availability_override_range",
            ),
        ]

    def clean(self):
        if self.end_at <= self.start_at:
            raise ValidationError("end_at debe ser > start_at")
        if self.resource_id and self.resource.merchant_id != self.merchant_id:
            raise ValidationError("merchant de override y resource no coinciden.")


class BookingStatus(models.TextChoices):
    HOLD = "HOLD", "Hold"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


class Booking(MerchantOwnedModel):
    """
    Reserva real.
    - Se crea en HOLD durante checkout y luego pasa a CONFIRMED en webhook de pago.
    - Protegida por ExclusionConstraint anti solapamiento (Postgres).
    """
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="bookings")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="bookings")

    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings"
    )

    # link a order/line cuando se confirma:
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings")
    order_line = models.OneToOneField(
        "orders.OrderLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="booking"
    )

    timespan = DateTimeRangeField()  # [start, end)
    status = models.CharField(max_length=16, choices=BookingStatus.choices, default=BookingStatus.HOLD)
    expires_at = models.DateTimeField(null=True, blank=True)  # solo relevante para HOLD

    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="exclude_overlapping_bookings_per_resource",
                expressions=[
                    ("resource", RangeOperators.EQUAL),
                    ("timespan", RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=[BookingStatus.HOLD, BookingStatus.CONFIRMED]),
            ),
        ]
        indexes = [
            models.Index(fields=["merchant", "resource", "status"]),
            models.Index(fields=["merchant", "variant", "status"]),
        ]

    @property
    def start_at(self):
        return self.timespan.lower

    @property
    def end_at(self):
        return self.timespan.upper

    def clean(self):
        if self.resource_id and self.resource.merchant_id != self.merchant_id:
            raise ValidationError("merchant de booking y resource no coinciden.")
        if self.variant_id and self.variant.merchant_id != self.merchant_id:
            raise ValidationError("merchant de booking y variant no coinciden.")
        if self.customer_id and self.customer.merchant_id != self.merchant_id:
            raise ValidationError("merchant de booking y customer no coinciden.")

    def mark_expired_if_needed(self) -> bool:
        if self.status == BookingStatus.HOLD and self.expires_at and timezone.now() >= self.expires_at:
            self.status = BookingStatus.EXPIRED
            return True
        return False
