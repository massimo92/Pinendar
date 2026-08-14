# Planificador trimestral de radiología abdominal

## Objetivo

Generar automáticamente un mes de calendario, revisarlo manualmente y conservar simultáneamente todos los meses anteriores. Cada cuenta tiene un entorno independiente; la aplicación comienza en catalán y puede cambiarse a español.

## Entidades

- **Persona**: nombre, correo, estado activo/inactivo auditado, archivo, patrón de trabajo de una a cinco semanas numeradas y repetibles, días telemáticos por semana, agendas habilitadas, preferencias opcionales por agenda, habilitación de gestión con uno a cinco días mensuales, reglas fijas personales y vacaciones. La semana aplicable se obtiene del número ISO de la semana natural.
- **Agenda**: nombre, hospital, modalidad, prioridad, cobertura semanal y reglas especiales de demanda recurrente. Son telemáticas TAC ambulatorio, resonancia y telemando.
- **Jornada de gestión**: actividad telemática especial de jornada completa. No es una agenda, no pertenece a ningún hospital y no crea demanda ni vacantes.
- **Guardia**: fecha y persona. Una fecha admite cualquier número de personas de guardia, pero una persona solo puede tener una guardia en esa fecha. Cada guardia deriva automáticamente una ausencia `post-guardia` el día natural siguiente; en domingo bloquea el lunes.
- **Festivo**: fecha no laborable de Girona, importable desde fuente pública y editable manualmente.
- **Evento de planificación**: actividad vigente de una persona en una fecha: agenda, Gestión o sin asignación. Conserva su carga y si es fijo, extraordinario o manual.
- **Ejecución de generación**: registro técnico del optimizador. No es un calendario ni determina qué eventos se muestran.

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
7. Las cesiones e intercambios actúan sobre guardias individuales y no alteran las demás guardias de sus fechas. La operación completa se rechaza sin cambios si dejaría a una persona con dos guardias el mismo día.
8. Las vacaciones o una ausencia `post-guardia` impiden toda asignación durante el periodo afectado.
9. Una regla fija personal puede exigir todas o exactamente una de varias agendas con demanda para un día semanal y puede prohibir otras. Todas sus condiciones se aplican cuando la persona está planificable; si está ausente, la demanda permanece abierta para otra persona apta.
10. Las reglas fijas no crean demanda. Las agendas obligatorias deben disponer de cobertura ordinaria o recurrente, y las combinaciones simultáneas no pueden superar el 100% de carga.
11. Varias garantías personales sobre la misma agenda deben satisfacerse todas; no forman un grupo compartido. La configuración rechaza los conflictos directos conocidos y el planificador detecta los que dependen del periodo.
12. La demanda de una fecha es la suma de la cobertura semanal de cada agenda y sus reglas especiales recurrentes coincidentes.
13. Cada agenda tiene una prioridad de cobertura: muy alta, alta, moderada o baja. El generador protege lexicográficamente cada nivel.
14. Si faltan personas o capacidades, las plazas que no puedan cubrirse quedan como vacantes; nunca se inventan agendas fuera de la configuración.
15. Cualquier incompatibilidad debe rechazarse en el backend con un error estructurado. Un fallo no altera ningún evento vigente.
16. Los días personales de teletrabajo se registran en la semana concreta del patrón. En esos días solo se pueden asignar agendas marcadas como telemáticas.
17. La gestión solo puede habilitarse con un objetivo de uno a cinco días mensuales. Ocupa el 100% del día, cuenta como actividad telemática y no puede combinarse con agendas. Se limita a un día por semana natural; si la cuota supera el número de semanas naturales del mes, el límite semanal aumenta solo hasta lo necesario para que la cuota sea alcanzable.

Una asignación manual bloqueada se conserva como regla dura al regenerar su periodo. Si vuelve imposible el cálculo, la regeneración falla sin cambiar el calendario.

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
2. Generar un mes y revisar cobertura, vacantes resaltadas en rojo, personas sin agenda en violeta, agendas parciales en naranja y estadísticas de equidad. Las vistas de día, semana y mes muestran indicadores diarios; los KPIs del periodo visible cuentan vacantes y días-persona sin agenda. Día y semana agrupan los eventos por hospital y muestran turno y carga, también en las vacantes, sin repetir el hospital dentro de cada tarjeta. En el mes, las asignaciones muestran solo el nombre de la persona y se identifican por el color de agenda. Las tarjetas de día y semana colocan turno y carga junto al nombre de la agenda. El desplegable de edición agrupa las opciones por hospital y no repite el hospital dentro de cada opción. Estadísticas añade una señal de capacidad sobre las últimas ocho semanas: exige al menos cuatro, distingue presión puntual de déficit estructural probable por volumen, persistencia y concentración, y solo habla de holgura probable cuando no hay vacantes y persisten días-persona sin asignar.
3. Ajustar manualmente el calendario:
   - Si la persona ya tiene una agenda, intercambiar de forma atómica su asignación con otra persona compatible del mismo día y carga. Las opciones se ordenan por mejora de equidad. Una asignación fija solo puede cambiarse entrando directamente en ella y confirmando un aviso previo; nunca aparece como destino desde otra persona. La excepción afecta únicamente al evento y conserva la regla recurrente del perfil.
   - Si la persona no tiene actividad, abrir y asignarle una plaza extraordinaria compatible con su perfil y las reglas duras. Esta plaza cuenta en carga, histórico y equidad, pero no altera la demanda ordinaria ni sus vacantes.
   Ambos cambios quedan bloqueados y se conservan si se regenera ese periodo.
4. Generar el periodo siguiente. Los eventos anteriores siguen vigentes y visibles.
5. Exportar el periodo completo o filtrado por médico como XLSX, CSV e ICS de día completo, con el correo del médico como asistente.

Si un periodo ya contiene eventos o vacantes, la aplicación muestra las cantidades afectadas y pide confirmación. Confirmar sustituye atómicamente solo ese rango; cancelar no modifica nada. Guardias y ausencias nunca se borran al regenerar o limpiar un rango.

## Pantallas

- **Calendario**: vistas de día, semana y mes; filtros por persona y agenda; generar, editar y borrar eventos y vacantes por rango, sin alterar otros meses, guardias, ausencias ni configuración, y exportar.
- **Equipo**: perfiles, estado activo auditado, patrones de trabajo semanales o alternantes, capacidades, gestión, reglas, vacaciones y archivo.
- **Agendas**: hospital, modalidad, prioridad, cobertura semanal y reglas especiales recurrentes.
- **Guardias y festivos**: formularios simples y listado.
- **Equidad e histórico**: composición de todos los eventos vigentes por actividad planificada, equilibrio clínico por persona y agenda, señal prudente de capacidad de plantilla y gráfico acumulado con selector entre equidad/felicidad y resolución diaria/mensual.
- **Ajustes**: idioma, hospitales y festivos.
- **Guía de uso**: explicación no técnica del flujo, las reglas, los criterios de reparto, los avisos y los cambios manuales.

## Persistencia y operación

- Cuentas locales independientes con inicio de sesión y recuperación mediante una clave rotatoria.
- El último acceso o uso autenticado actualiza la actividad de la cuenta. Una limpieza diaria elimina de forma irreversible la cuenta y todo su entorno tras más de seis meses naturales sin actividad. Al activar la política, las cuentas existentes empiezan a contar desde ese momento.
- SQLite relacional, con copia automática antes de migraciones.
- Despliegue en contenedores Docker sobre un servidor Linux, como un Droplet de DigitalOcean.
