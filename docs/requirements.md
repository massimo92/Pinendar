# Planificador trimestral de radiología abdominal

## Objetivo

Generar automáticamente propuestas de un mes, revisarlas manualmente y conservar sus versiones anteriores. Cada cuenta tiene un entorno independiente; la aplicación comienza en catalán y puede cambiarse a español.

## Entidades

- **Persona**: nombre, correo, estado activo/inactivo auditado, archivo, patrón de trabajo de una a cinco semanas numeradas y repetibles, días telemáticos por semana, agendas habilitadas, preferencias opcionales por agenda, habilitación de gestión con uno a cinco días mensuales, reglas fijas y vacaciones. La semana aplicable se obtiene del número ISO de la semana natural.
- **Agenda**: nombre, hospital, modalidad, prioridad, cobertura semanal y reglas especiales de demanda recurrente. Son telemáticas TAC ambulatorio, resonancia y telemando.
- **Jornada de gestión**: actividad telemática especial de jornada completa. No es una agenda, no pertenece a ningún hospital y no crea demanda ni vacantes.
- **Guardia**: fecha y médico. Deriva automáticamente una ausencia `post-guardia` el día natural siguiente; en domingo bloquea el lunes.
- **Festivo**: fecha no laborable de Girona, importable desde fuente pública y editable manualmente.
- **Propuesta**: actual o histórica. Al generar correctamente una nueva se archiva la anterior para histórico y equidad.

## Cobertura ordinaria

| Día | Cobertura |
|---|---|
| Lunes | 3 TAC amb, 3 eco amb, 1 eco urg, 2 reso, 2 TAC urg |
| Martes | 2 TAC amb, 2 eco amb, 1 eco urg, 2 reso, 2 TAC urg, 1 telemando, 1 general |
| Miércoles | 3 TAC amb, 1 eco amb, 1 eco técnicos, 1 eco urg, 3 reso, 2 TAC urg |
| Jueves | 3 TAC amb, 1 eco amb, 1 eco técnicos, 1 eco urg, 2 reso, 2 TAC urg, 1 general, 1 intervencionismo |
| Viernes | 2 TAC amb, 1 eco amb, 1 eco técnicos, 1 eco urg, 2 reso, 2 TAC urg, 1 general |

La tabla es el valor inicial y puede editarse en cada agenda. Una regla especial añade una plaza recurrente indicando el ordinal laborable del mes y el día de la semana. El valor inicial de intervencionismo añade una plaza el tercer lunes laborable de cada mes.

## Reglas duras de generación

1. Solo se planifican días de lunes a viernes que no sean festivos.
2. Una persona es planificable si está activa, tiene habilitado ese día de la semana y no está de vacaciones ni en post-guardia. Las personas no planificables no aparecen como `Sense assignació`.
3. Cada persona planificable recibe un 100%, un 50% excepcional o ninguna actividad: una agenda completa, dos agendas diferentes del 50%, una única media agenda o `Sense assignació`. Una persona nunca puede cubrir dos plazas de la misma agenda el mismo día.
4. La jornada parcial del 50% solo se utiliza cuando reduce vacantes. Si dos medias agendas pueden completar una jornada sin empeorar la cobertura, el generador evita separarlas entre personas. Si varias distribuciones dejan el mismo mínimo de jornadas parciales, se completa primero a quien ya cubre la agenda más prioritaria.
5. Una persona solo puede cubrir agendas incluidas en sus capacidades.
6. Una guardia crea una ausencia `post-guardia` el día natural siguiente. La demanda de las agendas de ese día no desaparece, aunque una regla fija apuntara a la persona ausente.
7. Las vacaciones o una ausencia `post-guardia` impiden toda asignación durante el periodo afectado.
8. Una regla fija persona–día–agenda es obligatoria cuando la persona está planificable. Si está ausente, la plaza sigue existiendo y debe cubrirla excepcionalmente otra persona apta.
9. Las reglas fijas no pueden superar la demanda configurada para esa agenda y día.
10. La demanda de una fecha es la suma de la cobertura semanal de cada agenda y sus reglas especiales recurrentes coincidentes.
11. Cada agenda tiene una prioridad de cobertura: muy alta, alta, moderada o baja. El generador protege lexicográficamente cada nivel.
12. Si faltan personas o capacidades, las plazas que no puedan cubrirse quedan como vacantes; nunca se inventan agendas fuera de la configuración.
13. Cualquier incompatibilidad debe rechazarse en el backend con un error estructurado. Un fallo no altera la propuesta actual.
14. Los días personales de teletrabajo se registran en la semana concreta del patrón. En esos días solo se pueden asignar agendas marcadas como telemáticas.
15. La gestión solo puede habilitarse con un objetivo de uno a cinco días mensuales. Ocupa el 100% del día, cuenta como actividad telemática y no puede combinarse con agendas.

Una asignación manual bloqueada solo será una regla de generación cuando exista un flujo para regenerar o reparar un periodo ya creado. Hasta entonces no interviene en nuevas propuestas, porque no se permiten periodos solapados.

## Reglas blandas

1. Se minimizan primero las vacantes de prioridad muy alta y después sus combinaciones agenda–fecha completamente vacías.
2. Gestión se reparte por rondas mensuales: se intenta dar el primer día a todas las personas habilitadas antes de conceder segundos días, y así sucesivamente hasta cinco.
3. Después se minimizan, por orden, las vacantes y agendas–fecha completamente vacías de prioridad alta, moderada y baja.
4. Cada fase congela únicamente su valor óptimo. Personas, fechas y vacantes concretas siguen libres para permitir intercambios globales.
5. Conservando la mejor cobertura, se minimizan las jornadas parciales excepcionales.
6. Conservando ese mínimo, se evita dejar al 50% a quien cubre una agenda más prioritaria.
7. Después se minimizan las personas planificables completamente sin actividad.
8. La equidad clínica minimiza primero la peor distancia personal y después la distancia total, pudiendo reorganizar todo el mes.
9. Finalmente se prefiere Gestión en viernes, después lunes y después el resto de días.
10. La equidad compara el perfil porcentual por agenda de cada persona con la media no ponderada de los perfiles comparables. Usa todo el histórico conservado, sin reinicio anual.

## Prioridades y equidad

La prioridad interviene en la generación con este orden:

1. Muy alta: urgencias (TAC y eco)
2. Alta: TAC ambulatorio, resonancia e intervencionismo
3. Moderada: general y telemando
4. Baja: eco ambulatoria y eco de técnicos

Gestión se sitúa entre la prioridad muy alta y la alta. Por tanto, nunca desplaza cobertura muy alta, pero puede dejar vacante una agenda alta, moderada o baja si no existe otra forma de completar su cuota. Antes de aceptar ese cierre, el optimizador puede mover Gestión a otra fecha y reasignar las agendas del mes completo.

El generador compara, por agenda, el porcentaje del perfil de cada persona con la media no ponderada de las personas comparables. Primero minimiza la peor distancia personal y después la distancia conjunta. Usa todo el histórico conservado. Los miembros archivados no entran en nuevas asignaciones ni en la equidad actual, pero conservan sus registros pasados.

Las preferencias por agenda usan +1 para corazón, −1 para pulgar abajo y 0 cuando no hay reacción. Pueden conservarse para análisis, pero no intervienen en la generación. Gestión tampoco forma parte del perfil de equidad ni del índice de felicidad.

## Flujo de uso

1. Configurar equipo, cobertura, festivos, guardias, vacaciones y reglas.
2. Generar una propuesta de un mes y revisar cobertura, vacantes resaltadas en rojo, personas sin agenda en violeta, agendas parciales en naranja y estadísticas de equidad. Las vistas de día, semana y mes muestran indicadores diarios; los KPIs del periodo visible cuentan vacantes y días-persona sin agenda. Día y semana agrupan los eventos por hospital y muestran turno y carga, también en las vacantes, sin repetir el hospital dentro de cada tarjeta. En el mes, las asignaciones muestran solo el nombre de la persona y se identifican por el color de agenda. Las tarjetas de día y semana colocan turno y carga junto al nombre de la agenda. El desplegable de edición agrupa las opciones por hospital y no repite el hospital dentro de cada opción.
3. Ajustar manualmente la propuesta:
   - Si la persona ya tiene una agenda, intercambiar de forma atómica su asignación con otra persona compatible del mismo día y carga. Las opciones se ordenan por mejora de equidad. Una asignación fija solo puede cambiarse entrando directamente en ella y confirmando un aviso previo; nunca aparece como destino desde otra persona. La excepción afecta únicamente a la propuesta actual y conserva la regla recurrente del perfil.
   - Si la persona no tiene actividad, abrir y asignarle una plaza extraordinaria compatible con su perfil y las reglas duras. Esta plaza cuenta en carga, histórico y equidad, pero no altera la demanda ordinaria ni sus vacantes.
   Ambos cambios quedan bloqueados en la propuesta actual.
4. Generar el periodo siguiente. La propuesta anterior pasa al histórico.
5. Exportar el periodo completo o filtrado por médico como XLSX, CSV e ICS de día completo, con el correo del médico como asistente.

## Pantallas

- **Calendario**: vistas de día, semana y mes; filtros por persona y agenda; generar, editar y borrar por rango el contenido de la propuesta actual con confirmación escrita, sin alterar históricos ni configuración, y exportar.
- **Equipo**: perfiles, estado activo auditado, patrones de trabajo semanales o alternantes, capacidades, gestión, reglas, vacaciones y archivo.
- **Agendas**: hospital, modalidad, prioridad, cobertura semanal y reglas especiales recurrentes.
- **Guardias y festivos**: formularios simples y listado.
- **Equidad e histórico**: composición histórica por actividad planificada, equilibrio clínico por persona y agenda, métrica propia de Gestión, evolución y propuestas registradas.
- **Ajustes**: idioma, hospitales y festivos.
- **Guía de uso**: explicación no técnica del flujo, las reglas, los criterios de reparto, los avisos y los cambios manuales.

## Persistencia y operación

- Cuentas locales independientes con inicio de sesión y recuperación mediante una clave rotatoria.
- El último acceso o uso autenticado actualiza la actividad de la cuenta. Una limpieza diaria elimina de forma irreversible la cuenta y todo su entorno tras más de seis meses naturales sin actividad. Al activar la política, las cuentas existentes empiezan a contar desde ese momento.
- SQLite relacional, con copia automática antes de migraciones.
- Despliegue en contenedores Docker sobre un servidor Linux, como un Droplet de DigitalOcean.
