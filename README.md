# Pinendar

Planificador mensual de agendas para equipos de radiología. Configura hospitales, agendas, personas, guardias y ausencias; Pinendar genera un calendario que respeta las reglas duras, protege la cobertura y mejora la equidad.

El calendario es continuo: cada mes generado añade eventos por fecha y no reemplaza los meses anteriores. Regenerar un rango existente requiere confirmación y solo sustituye ese rango.

## Inicio rápido

1. Copia `.env.example` a `.env`.
2. Define un `PINENDAR_SESSION_SECRET` largo y aleatorio.
3. Ejecuta `docker compose up --build`.
4. Crea la cuenta administradora:

   ```bash
   docker compose exec pinendar pinendar account create --admin --username admin --password 'cámbiala' --environment /app/data/pinendar.sqlite
   ```

5. Abre `http://localhost:4173`.

Cada cuenta dispone de un entorno independiente. Las bases SQLite, copias, exportaciones, claves y archivos `.env` están excluidos de Git y del contexto Docker.

## Registro y administración

El registro público crea una solicitud pendiente y muestra al solicitante su clave de recuperación. La cuenta no puede iniciar sesión hasta que un administrador la acepte.

La sección **Administración** solo aparece para cuentas administradoras. Permite aceptar o rechazar solicitudes, crear, editar, bloquear o eliminar usuarios y generar copias ZIP descargables. Cada copia contiene `auth.sqlite`, todas las bases de datos de las cuentas y un manifiesto `metadata.json`.

Las copias guardadas en el mismo volumen protegen frente a errores lógicos, pero no frente a la pérdida del servidor. Deben descargarse o replicarse fuera del host.

## Conservación de datos

Cualquier acceso o uso autenticado actualiza la última actividad. Tras más de seis meses naturales sin actividad, una cuenta normal y todos sus datos se eliminan automática e irreversiblemente. Las cuentas administradoras quedan excluidas.

## Documentación

- [Guía funcional](docs/requirements.md)
- [Arquitectura](docs/architecture.md)
- [Decisiones técnicas](docs/adr)

## Licencia

[MIT](LICENSE) © 2026 Massimo Angelini.
