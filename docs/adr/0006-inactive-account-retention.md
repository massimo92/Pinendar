# ADR 0006: eliminar cuentas tras seis meses sin actividad

## Estado

Aceptado.

## Contexto

Cada cuenta conserva un entorno SQLite privado. Mantener indefinidamente cuentas abandonadas aumenta la exposición de datos personales y el almacenamiento sin aportar valor. No existe correo ni un canal externo fiable para avisar o recuperar una cuenta eliminada.

## Decisión

- Registrar por separado la última actividad de cada cuenta.
- Considerar actividad cualquier inicio de sesión, recuperación o petición autenticada.
- Escribir como máximo una actualización por hora para evitar carga innecesaria.
- Ejecutar la limpieza al arrancar y una vez al día.
- Eliminar cuenta, metadatos de acceso y SQLite cuando hayan pasado más de seis meses naturales completos.
- Inicializar con la fecha de despliegue las cuentas anteriores a esta función.
- Limitar el borrado de archivos al SQLite legado configurado o al directorio de entornos.

## Consecuencias

- Volver a usar Pinendar reinicia automáticamente el plazo.
- La eliminación es irreversible, incluida la clave de recuperación.
- Un servidor que permanezca apagado ejecutará la limpieza al volver a arrancar.
- Una ruta de entorno inesperada no se borra del disco y genera un aviso operativo.
