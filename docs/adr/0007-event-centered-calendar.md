# ADR 0007: calendario centrado en eventos

## Estado

Aceptado.

## Contexto

El calendario se guardaba dentro de propuestas con estados actual e histórico. Generar un mes nuevo podía archivar el anterior y hacer que sus asignaciones y guardias dejaran de aparecer, aunque ambos meses debían seguir vigentes.

## Decisión

El calendario es la proyección por fecha de cuatro entidades vigentes:

- `PlanningEvent`: actividad de una persona, con carga y banderas fija, extraordinaria y manual.
- `Vacancy`: plaza demandada sin persona.
- `Guard`: guardia interna activa.
- `Absence`: vacaciones o postguardia.

`GenerationJob` es solo auditoría técnica. Su relación opcional permite saber qué ejecución creó un evento, pero nunca filtra el calendario.

Una generación escribe únicamente dentro de su rango y lo hace en una transacción. Si el rango contiene eventos o vacantes, requiere confirmación explícita. Los cambios manuales bloqueados se incorporan como restricciones duras. Guardias y ausencias se leen, pero no se eliminan al regenerar.

No se adopta *event sourcing*: se conserva el estado vigente y un histórico específico de operaciones de guardia, no una secuencia inmutable capaz de reconstruir todo el sistema.

## Consecuencias

- Generar septiembre no cambia agosto.
- Las métricas cuentan una sola vez todos los eventos vigentes.
- No existen borrador, publicado ni propuesta actual.
- Fallos, timeouts y resultados obsoletos dejan el calendario intacto.
- Borrar un rango elimina eventos y vacantes, pero conserva guardias y ausencias.
