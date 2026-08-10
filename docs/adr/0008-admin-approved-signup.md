# ADR 0008: Registro aprobado y administración local

## Estado

Aceptado.

## Contexto

El despliegue público necesita admitir solicitudes de acceso sin crear cuentas utilizables automáticamente. También necesita gestionar cuentas y copias sin entrar por SSH.

## Decisión

- El registro público crea una solicitud pendiente con contraseña y clave de recuperación almacenadas únicamente como hashes Argon2id.
- La clave de recuperación se muestra una sola vez al solicitante. La aprobación reutiliza esos hashes y crea una SQLite aislada.
- La cuenta configurada como `PINENDAR_ADMIN_USERNAME` se promociona a administradora al arrancar.
- Solo una sesión administradora puede aprobar, rechazar, crear, editar, bloquear o eliminar cuentas y generar o descargar backups.
- La cuenta administradora no puede bloquearse ni eliminarse desde el panel y no caduca por inactividad.
- Cada backup usa la API de copia de SQLite y agrupa autenticación, entornos y metadatos en un ZIP dentro de `PINENDAR_BACKUPS_DIR`.

## Consecuencias

- Rechazar una solicitud elimina sus hashes y permite volver a solicitar el mismo usuario.
- El administrador que crea directamente una cuenta debe entregar al usuario la clave de recuperación mostrada.
- El almacenamiento local de backups no sustituye una copia externa del servidor.
