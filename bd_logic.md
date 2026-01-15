# DB logic overview

Este documento describe la logica de base de datos para el backend ecommerce, con foco en integridad, multi-tenant y reglas de negocio.

## Convenciones generales

- Todos los modelos principales usan UUID como PK, mas `created_at` y `updated_at`.
- Multi-tenant: el campo `merchant` identifica la tienda y se usa como particion logica.
- Cuando una tabla no incluye `merchant` (p. ej. `CartLine`), la coherencia se valida a nivel de modelo (`clean`).
- La persistencia se orienta a Postgres; se usan constraints nativas para unicidad/exclusion y CheckConstraint para reglas de negocio.

## Estructura por dominio

### Catalogo

- `Product` y `ProductVariant` son entidades centrales del catalogo. `ProductVariant` es el SKU vendible.
- `ProductVariant` define `kind` (DIRECT, BOOKING, WEIGHT) y el precio base.
- `WeightSettings` y `BookingSettings` guardan configuracion especifica para WEIGHT/BOOKING.

Constraints relevantes:
- `ProductVariant`: unicidad de `sku` por `merchant`.
- CheckConstraint: `ProductVariant`, `BookingSettings` y `WeightSettings` validan precios, currency y limites.

Validaciones de consistencia (modelo):
- Se mantiene `clean()` como respaldo de aplicacion.

### Carrito

- `Cart` representa el carrito por merchant y puede ser de usuario logueado o invitado.
- `CartLine` almacena items del carrito con snapshot para UI.

Constraints relevantes:
- `Cart`: token unico por `merchant` cuando existe (guest carts).
- `CartLine`: constraint unico por variante para DIRECT/WEIGHT, y por rango horario para BOOKING.
- CheckConstraint: `Cart`, `CartLine` y `CartAppliedDiscount` validan identidad, cantidades, horarios y montos.

Validaciones de consistencia (modelo):
- Se mantiene `clean()` como respaldo de aplicacion.

### Promociones y cupones

- `Voucher` es un cupon manual con reglas de validez por fechas, monto minimo y tipo de descuento.
- `Promotion` es una promocion automatica basada en reglas (`predicate`).
- `VoucherRedemption` registra usos para limites y auditoria.

Constraints relevantes:
- `Voucher`: unicidad de `code` por `merchant`.
- CheckConstraint: `Voucher` y `Promotion` validan rangos de descuentos, currency y fechas.

Validaciones de consistencia (modelo):
- Se mantiene `clean()` como respaldo de aplicacion.

### Scheduling (booking)

- `Resource` es un recurso agendable.
- `AvailabilityRule` define regla semanal, `AvailabilityOverride` define excepciones.
- `Booking` representa una reserva y se protege contra solapamientos con `ExclusionConstraint` (Postgres).

Constraints relevantes:
- `Booking`: exclusion constraint evita reservas solapadas por `resource` cuando estan en HOLD/CONFIRMED.
- CheckConstraint: `AvailabilityRule` y `AvailabilityOverride` validan rangos.

Validaciones de consistencia (modelo):
- Se mantiene `clean()` como respaldo de aplicacion.

### Inventario

- `Warehouse` representa un deposito por merchant.
- `Stock` guarda cantidad y asignado por `variant` y `warehouse`.

Constraints relevantes:
- `Stock`: unicidad `warehouse` + `variant`.
- CheckConstraint: `Stock` valida allocated <= quantity.

Validaciones de consistencia (modelo):
- Se mantiene `clean()` como respaldo de aplicacion.

## Notas sobre integridad multi-tenant

Django no soporta constraints con subqueries en CHECK, por lo que la consistencia de `merchant` entre tablas relacionadas se valida en `clean()` y en servicios de dominio. Si necesitas enforcement 100% en la DB, se recomienda:

- Disenar PK compuestas (merchant, id) y usar FK compuestas.
- O usar triggers en Postgres para validar merchant entre tablas.

## Settings para Postgres

El proyecto esta configurado para Postgres con variables de entorno:

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_CONN_MAX_AGE`

Tambien se incluye `django.contrib.postgres` en `INSTALLED_APPS` para rangos y exclusion constraints.
