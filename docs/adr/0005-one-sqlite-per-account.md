# ADR 0005: Un SQLite de datos por cuenta

## Estado

Aceptado.

## Contexto

Pinendar necesita varias cuentas sin compartir hospitales, agendas, personas ni calendarios. La recuperación no puede depender de correo.

## Decisión

- Un SQLite central guarda cuentas, hashes Argon2id, claves de recuperación cifradas por hash y la ruta de cada entorno.
- Cada cuenta apunta a un SQLite de datos independiente.
- La sesión firmada contiene la identidad y una versión revocable.
- La recuperación usa una clave mostrada al generarla. Una sesión autenticada puede rotarla; recuperar la contraseña también la rota y revoca sesiones anteriores.
- La base `data/pinendar.sqlite` existente pertenece a la cuenta inicial `admin`.

## Consecuencias

- El aislamiento y las copias de seguridad son simples.
- No hay colaboración entre cuentas ni consultas cruzadas.
- Una instalación con muchas cuentas tendrá varios archivos y procesos de generación aislados.
- Perder contraseña y clave de recuperación exige una intervención local del administrador.
