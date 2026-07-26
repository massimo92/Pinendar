# Pinendar

Planificador mensual de agendas para equipos de radiología. Configura hospitales, agendas, personas, guardias y ausencias; Pinendar propone un calendario que respeta las reglas duras, protege la cobertura y mejora la equidad.

## Inicio rápido

1. Copia `.env.example` a `.env`.
2. Define un `PINENDAR_SESSION_SECRET` largo y aleatorio.
3. Ejecuta `docker compose up --build`.
4. Abre `http://localhost:4173` y crea la primera cuenta.

Cada cuenta dispone de un entorno independiente. Las bases SQLite, copias, exportaciones, claves y archivos `.env` están excluidos de Git y del contexto Docker.

## Conservación de datos

Cualquier acceso o uso autenticado actualiza la última actividad. Tras más de seis meses naturales sin actividad, la cuenta y todos sus datos se eliminan automática e irreversiblemente.

## Documentación

- [Guía funcional](docs/requirements.md)
- [Arquitectura](docs/architecture.md)
- [Decisiones técnicas](docs/adr)

## Licencia

[MIT](LICENSE) © 2026 Massimo Angelini.
