# Arquitectura

## Aplicación

- Frontend JavaScript mediante módulos ES, servido por FastAPI.
- API FastAPI/Pydantic con conflictos y validaciones autoritativos.
- Servicios de aplicación para comandos, consultas y generación.
- Dominio independiente con `Scheduler`, `ScheduleProblem` y `ScheduleResult`.
- SQLAlchemy y Alembic sobre SQLite relacional.

El frontend carga `GET /api/v1/bootstrap`, pero cada escritura utiliza un endpoint específico. Nunca envía el estado completo.

## Generación

`POST /api/v1/generation-jobs` valida el periodo, captura una instantánea versionada y crea un trabajo persistente. Un dispatcher ejecuta `CpSatScheduler` con OR-Tools en otro proceso. El resultado solo se aplica si no cambió `planning_revision` y supera una validación independiente.

Los estados son `queued`, `running`, `succeeded`, `failed` y `stale`. Una solución factible sustituye atómicamente solo los eventos y vacantes del rango solicitado. Si ya existen, la API exige `replaceExisting` tras confirmación. Inviabilidad, timeout, modelo inválido, cambio de revisión o resultado inconsistente no modifican el calendario.

El modelo permite una carga diaria del 0%, 50% o 100%. La jornada ordinaria es una agenda completa o dos agendas diferentes del 50%; una única media agenda es una jornada parcial excepcional. Optimiza lexicográficamente cobertura muy alta, reparto de Gestión por rondas, cobertura alta, moderada y baja, jornadas parciales, protección de la agenda más prioritaria en el desempate de parciales, personas-día sin actividad, equidad histórica y preferencia viernes–lunes.

Gestión es una asignación especial con `agenda_id` nulo y tipo propio. Ocupa el 100%, cuenta como telemática y no entra en demanda, vacantes, equidad clínica ni felicidad. Cada fase conserva únicamente su valor óptimo; todas las asignaciones, fechas y vacantes concretas continúan libres para permitir intercambios globales.

## Persistencia

Miembros y agendas se archivan. Su histórico se conserva; configuración y eventos futuros se eliminan desde la fecha de archivo. El catálogo hospitalario común sigue versionado como JSON y la base solo almacena sus referencias.

`auth.sqlite` conserva identidades, roles y solicitudes pendientes con credenciales Argon2id. Cada cuenta aprobada apunta a una SQLite independiente. El signup no crea sesión ni entorno hasta que el administrador lo aprueba.

`PlanningEvent` conserva persona, fecha, tipo, carga y banderas fija, extraordinaria y manual. Vacantes, guardias, ausencias e histórico de guardias son entidades separadas. `GenerationJob` solo audita ejecuciones mediante una relación opcional y nunca limita las consultas.

`GET /api/v1/bootstrap` entrega `calendar.events`, `calendar.vacancies`, `calendar.guards` y `calendar.absences`. Día, semana, mes, exportaciones y métricas proyectan todas estas entidades por fecha. No existen borradores, publicaciones ni una propuesta actual.

Las migraciones crean una copia SQLite previa. La migración al calendario por eventos conserva, para cada fecha solapada, la versión antigua generada más recientemente y valida los recuentos antes de retirar las tablas de propuestas.

## Operación

uv administra `pyproject.toml`, `uv.lock`, pruebas y herramientas. Docker usa una construcción multi-stage, ejecuta como usuario sin privilegios y persiste únicamente `/app/data`. Compose configura healthchecks, volumen, filesystem de solo lectura y parada controlada. TLS corresponde al proxy o plataforma de despliegue.

El panel administrador crea snapshots consistentes mediante la API de backup de SQLite y los empaqueta dentro de `/app/data/backups`. La descarga o réplica fuera del servidor sigue siendo necesaria para recuperación ante pérdida del host.
