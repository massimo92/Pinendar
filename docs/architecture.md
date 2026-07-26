# Arquitectura

## Aplicación

- Frontend JavaScript mediante módulos ES, servido por FastAPI.
- API FastAPI/Pydantic con conflictos y validaciones autoritativos.
- Servicios de aplicación para comandos, consultas y generación.
- Dominio independiente con `Scheduler`, `ScheduleProblem` y `ScheduleResult`.
- SQLAlchemy y Alembic sobre SQLite relacional.

El frontend carga `GET /api/v1/bootstrap`, pero cada escritura utiliza un endpoint específico. Nunca envía el estado completo.

## Generación

`POST /api/v1/generation-jobs` valida el periodo, captura una instantánea versionada y crea un trabajo persistente. Un dispatcher ejecuta `CpSatScheduler` con OR-Tools en otro proceso. El resultado solo se aplica si no cambió `planning_revision`, el periodo continúa libre y el calendario supera una validación independiente.

Los estados son `queued`, `running`, `succeeded`, `failed` y `stale`. Solo una solución factible crea una propuesta y archiva la anterior. Inviabilidad, límite sin solución, modelo inválido, cambio de revisión o resultado inconsistente no modifican calendarios.

El modelo permite una carga diaria del 0%, 50% o 100%. La jornada ordinaria es una agenda completa o dos agendas diferentes del 50%; una única media agenda es una jornada parcial excepcional. Optimiza lexicográficamente cobertura muy alta, reparto de Gestión por rondas, cobertura alta, moderada y baja, jornadas parciales, protección de la agenda más prioritaria en el desempate de parciales, personas-día sin actividad, equidad histórica y preferencia viernes–lunes.

Gestión es una asignación especial con `agenda_id` nulo y tipo propio. Ocupa el 100%, cuenta como telemática y no entra en demanda, vacantes, equidad clínica ni felicidad. Cada fase conserva únicamente su valor óptimo; todas las asignaciones, fechas y vacantes concretas continúan libres para permitir intercambios globales.

## Persistencia

Miembros y agendas se archivan. Su histórico se conserva; configuración y eventos futuros se eliminan desde la fecha de archivo. El catálogo hospitalario común sigue versionado como JSON y la base solo almacena sus referencias.

La primera migración importa `app_state`, conserva la tabla original y crea una copia SQLite previa.

## Operación

uv administra `pyproject.toml`, `uv.lock`, pruebas y herramientas. Docker usa una construcción multi-stage, ejecuta como usuario sin privilegios y persiste únicamente `/app/data`. Compose configura healthchecks, volumen, filesystem de solo lectura y parada controlada. TLS corresponde al proxy o plataforma de despliegue.
