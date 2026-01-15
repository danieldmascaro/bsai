# Ecommerce Backend (Django)

Backend para ecommerce multi-tenant con Django. El dominio cubre catalogo, carrito, promociones, inventario y agendamiento (booking).

## Estructura del proyecto

- `BrandSoftAI/`: proyecto Django y apps.
- `BrandSoftAI/catalog/`: productos y variantes.
- `BrandSoftAI/cart/`: carrito, lineas y descuentos aplicados.
- `BrandSoftAI/promotions/`: vouchers y promociones.
- `BrandSoftAI/inventory/`: bodegas y stock.
- `BrandSoftAI/scheduling/`: recursos, disponibilidad y reservas.

## Base de datos

El proyecto esta configurado para Postgres usando variables de entorno:

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_CONN_MAX_AGE`

Nota: las reglas de negocio usan CheckConstraint y `clean()`/servicios. Las FK solo garantizan integridad referencial.

## Documentacion tecnica

La descripcion detallada de la logica de BD y reglas por dominio esta en `bd_logic.md`.

## Licencia

MIT. Ver `LICENSE`.
