# Plan revisado: reglas `Debe hacer todas` con peonadas

## Objetivo

Permitir que una regla personal de tipo **Debe hacer todas** obligue a realizar agendas cuya carga simultánea alcance hasta el 200%. Cuando la carga aplicable en una fecha supere el 100%, deben definirse explícitamente las agendas que serán peonada.

La mejora amplía la carga admitida por la regla. No cambia qué significa `Debe hacer todas`, no crea demanda y no introduce una elección nueva para el optimizador.

## Comportamiento existente que debe conservarse

- Solo puede existir una regla fija por persona y día de la semana.
- La mejora solo afecta a `Debe hacer todas`. `Debe hacer una` y `No puede hacer` conservan exactamente su comportamiento actual.
- La regla solo se aplica cuando la persona es planificable.
- En cada fecha se consideran únicamente las agendas seleccionadas que tienen demanda ese día.
- Si la regla aplica, todas esas agendas son obligatorias y quedan marcadas como fijas.
- Si no pueden asignarse todas, la generación completa resulta no factible; nunca se cumple parcialmente ni se ignora silenciosamente.
- Una regla fija no crea plazas: cada agenda asignada sigue cubriendo una plaza de la demanda ordinaria.
- Una asignación fija puede modificarse manualmente únicamente tras la confirmación existente. La modificación no cambia la regla recurrente.

## Carga efectiva de la regla

La carga no se calcula sumando sin más todas las agendas configuradas. Se calcula para cada fecha en que la regla puede aplicarse, respetando cobertura semanal y reglas especiales.

Ejemplos:

- Una agenda semanal del 100% y otra del 50% que coinciden ese lunes generan 150%.
- Dos agendas del 100% que se realizan en ordinales distintos del mes no generan 200% porque no coinciden en la misma fecha.
- Una agenda semanal del 100% y dos agendas especiales del 50% en ordinales distintos generan 150% en cada fecha especial, no 200%.

Para todas las fechas posibles:

- la carga aplicable no puede superar el 200%;
- hasta el 100% es carga ordinaria;
- solo el exceso exacto sobre el 100% es peonada;
- las agendas son indivisibles: una agenda del 50% o del 100% se marca completa como ordinaria o como peonada.

Por tanto:

- 150% total = 100% ordinario + 50% de peonada;
- 200% total = 100% ordinario + 100% de peonada;
- nunca puede quedar menos o más de un 100% ordinario cuando existe peonada.

## Selección de agendas peonada

La regla guarda qué agendas requeridas forman la parte peonada. La selección debe cumplir, en cada fecha con sobrecarga:

```text
carga de agendas peonada activas = carga total activa - 100%
```

Las agendas configuradas como peonada solo llevan la marca en las fechas donde existe sobrecarga. Si una de ellas aparece sola en otra fecha con carga total igual o inferior al 100%, esa asignación es ordinaria.

Si una única selección por agenda no puede producir exactamente un 100% ordinario en todas las combinaciones recurrentes, la regla debe rechazarse con un mensaje que identifique la combinación incompatible. No se debe escoger una peonada automáticamente.

## Arquitectura: peonadas fijas preasignadas

La capacidad ordinaria interna del optimizador permanece en el 100%. Las agendas peonada de la regla no se convierten en nuevas variables de reparto: son asignaciones deterministas que se reservan antes de optimizar y se materializan al construir el resultado.

Para cada persona y fecha:

1. Se determinan las agendas obligatorias activas de `Debe hacer todas`.
2. Se separan según la configuración de la regla en agendas ordinarias y agendas peonada.
3. Se comprueba que las ordinarias suman exactamente el 100% cuando existe sobrecarga y que el total no supera el 200%.
4. Las agendas ordinarias fijas siguen entrando en el modelo como variables obligatorias, exactamente como ahora.
5. Solo las agendas peonada se reservan fuera de la capacidad ordinaria y se incorporan como constantes a la ecuación de cobertura, evitando que su plaza pueda asignarse de nuevo.
6. Esas reservas también se incorporan como constantes a los cálculos de equidad, teletrabajo y presencialidad.
7. El optimizador reparte únicamente la demanda y la capacidad ordinarias restantes.
8. Al construir el resultado se materializan las reservas como eventos `fixed = true` y `peonada = true`.

Por tanto, “añadirlas al final” describe cuándo se crean los eventos, pero no cuándo se conocen: deben reservarse y contabilizarse antes de optimizar.

Si la regla obliga solo a un 50% ordinario y no contiene peonada, se conserva el comportamiento actual y el optimizador puede completar el otro 50%. Si la regla obliga a más del 100%, el 100% ordinario ya está completo y no se añade ninguna agenda opcional hasta el 200%.

Una fecha con peonada fija preasignada no ofrece capacidad ordinaria libre para diferidos automáticos ni para gestión generada.

## Una única fuente de verdad

La expansión de una regla por fecha debe implementarse en una función de dominio compartida. Recibe persona, regla, fecha y demanda, y devuelve:

- agendas fijas ordinarias activas;
- agendas fijas peonada activas;
- carga ordinaria, carga peonada y carga combinada;
- errores de demanda, capacidad o clasificación.

El generador mensual, el reparador diario de guardias, la validación al guardar y la validación final deben consumir la misma semántica. No deben mantener cuatro versiones independientes del cálculo.

## Orden y prioridades

Orden conceptual corregido:

1. Validar disponibilidad, capacidades, demanda y reglas fijas.
2. Expandir las reglas por fecha: fijar las agendas ordinarias como ahora y reservar aparte las peonadas.
3. Incorporar esas reservas como constantes en los objetivos afectados.
4. Ejecutar sin cambios la jerarquía existente sobre la demanda ordinaria restante.
5. Materializar las peonadas reservadas al construir el resultado.
6. Ejecutar el pulido sin permitir que mueva asignaciones fijas o peonadas.

La presencialidad de guardia sigue siendo un objetivo, no una restricción dura. Si una regla fija obliga exclusivamente a agendas telemáticas y no deja capacidad para añadir una presencial, la regla fija prevalece y se registra el fallback telemático de la guardia, igual que con cualquier otro conflicto inevitable.

El pulido no puede mover estas asignaciones porque son fijas y, cuando corresponda, peonadas. Esto coincide con las protecciones actuales.

## Asignaciones bloqueadas y ediciones manuales

Al preparar las reservas pueden coexistir una regla fija y eventos manuales bloqueados. Deben mantenerse las garantías existentes:

- las asignaciones bloqueadas no se cambian silenciosamente;
- la suma diaria nunca supera el 200%;
- si hay sobrecarga, las marcas combinadas deben dejar exactamente un 100% ordinario;
- si la regla y los eventos bloqueados reclaman la misma plaza, superan el 200% o dejan una clasificación incoherente, la generación falla con un conflicto explícito;
- no se reclasifica automáticamente una asignación manual ni una agenda de la regla.

Al modificar manualmente una asignación fija generada por esta regla se mantiene el flujo actual: confirmación de sobrescritura, eliminación de la marca fija del evento y revisión de todas las peonadas afectadas. La regla recurrente permanece intacta.

## Otros caminos que recalculan un día

La lógica no vive únicamente en la generación mensual. El reparador diario utilizado al ceder, intercambiar o modificar guardias también reconstruye asignaciones. Debe tratar las peonadas de regla como reservas fijas fuera de la capacidad ordinaria que vuelve a optimizar.

Todos los caminos que creen o reconstruyan un día deben compartir estas invariantes:

- obligación completa de `Debe hacer todas`;
- reserva de demanda antes de repartir el resto;
- optimización limitada al 100% ordinario;
- máximo combinado del 200%;
- exactamente un 100% ordinario cuando haya sobrecarga;
- persistencia explícita de `fixed` y `peonada` al materializar el resultado;
- ningún valor antiguo de peonada puede sobrevivir por accidente al reutilizar un evento.

## UI de creación y edición

La interacción mantiene el selector actual de agendas y añade la clasificación de peonada solo cuando la acción es `Debe hacer todas` y alguna combinación diaria supera el 100%.

Flujo:

1. La persona selecciona las agendas como ahora.
2. La UI calcula la carga simultánea máxima según cobertura y recurrencias.
3. Si ninguna fecha supera el 100%, no se muestra ningún selector de peonada.
4. Si existe sobrecarga, se muestra la carga total aplicable y se pide marcar las agendas que forman exactamente el exceso.
5. La UI impide seleccionar una combinación que deje una carga ordinaria distinta del 100%.
6. El backend repite toda la validación; la UI no es la fuente de verdad.

Se reutiliza el lenguaje visual del modal manual de peonadas:

- `Ha de quedar exactament un 100% de feina ordinària.`
- carga total;
- carga peonada requerida;
- agenda y porcentaje de carga;
- estado de selección, por ejemplo `50% de 50% com a peonada`.

Si las recurrencias producen cargas distintas, la UI debe indicar las combinaciones relevantes, por ejemplo `Primer dilluns: 150%` y `Tercer dilluns: 100%`, para evitar que el usuario interprete la suma de agendas como carga diaria.

## UI de lectura

En el perfil de la persona se conserva el resumen actual de la regla y se amplía con:

- carga simultánea máxima;
- etiqueta `Inclou peonada` cuando corresponda;
- marca `P` junto a las agendas configuradas como peonada;
- detalle de las combinaciones recurrentes si no todas tienen la misma carga.

Ejemplo:

> Ha de fer totes · màxim 150%<br>
> RM matí 100% · Consultes 50% (P)<br>
> 100% ordinari · fins a 50% de peonada

Las reglas antiguas de hasta el 100% deben conservar su aspecto actual, sin controles ni etiquetas nuevas innecesarias.

## Persistencia y contrato API

Cambio aditivo propuesto:

- añadir `peonada BOOLEAN NOT NULL DEFAULT FALSE` a `fixed_rule_agendas`;
- permitir `peonada = TRUE` únicamente en enlaces con efecto `required`;
- exponer en cada regla `peonadaAgendaIds`, con valor `[]` para reglas antiguas;
- aceptar el nuevo campo únicamente para `requiredMode = all`;
- exigir que `peonadaAgendaIds` sea un subconjunto de `requiredAgendaIds`.

No se debe ampliar el enum `effect`: `required` y `forbidden` siguen describiendo la obligación, mientras que `peonada` es una clasificación independiente.

La migración conserva todas las reglas actuales con `peonada = FALSE`. No elimina ni transforma agendas, reglas ni eventos existentes.

El snapshot del planificador y la versión del modelo deben incrementarse. Los snapshots antiguos deben seguir deserializándose con `peonadaAgendaIds = []`.

Cuando se implemente la funcionalidad, la definición de `Peonada` en `CONTEXT.md` debe ampliarse para admitir dos orígenes: revisión manual y regla fija. Hasta entonces, el glosario debe seguir describiendo el comportamiento actualmente desplegado.

## Validación

Validar tanto al guardar una persona como al modificar una agenda utilizada por reglas:

- solo una regla por persona y día, como ahora;
- agendas requeridas existentes, activas y habilitadas para la persona;
- demanda disponible en cobertura semanal o recurrencia, como ahora;
- compatibilidad con el patrón telemático, como ahora;
- carga simultánea máxima no superior al 200%;
- peonadas permitidas solo en `Debe hacer todas`;
- agendas peonada incluidas también entre las requeridas;
- en cada combinación con sobrecarga, carga peonada exacta igual al exceso;
- ninguna asignación marcada como peonada cuando la carga diaria no supera el 100%;
- compatibilidad entre reglas, eventos bloqueados y límite diario al generar.

Los cambios de carga, cobertura, recurrencia, modalidad o archivado de una agenda deben volver a validar las reglas relacionadas. Si una modificación las invalida, debe utilizar el flujo actual de advertencia y confirmación para eliminar reglas conflictivas; nunca debe corregir sus peonadas silenciosamente.

## Efecto en métricas y exportaciones

Se preserva la lógica existente:

- la asignación peonada cubre demanda ordinaria; no es una plaza extraordinaria;
- toda su carga cuenta en el histórico y en la equidad como ya ocurre con una peonada manual;
- conserva `fixed = true`, por lo que toda su carga cuenta en el KPI de actividad por reglas fijas;
- el porcentaje telemático continúa calculándose por días: cualquier agenda presencial hace el día presencial, con independencia de que sea peonada;
- calendario, histórico, filtros, CSV e ICS reutilizan la marca `peonada` existente.

No se introduce una ponderación distinta para peonadas generadas por regla y peonadas manuales.

## Pruebas necesarias

### Compatibilidad

- Reglas antiguas `Debe hacer todas`, `Debe hacer una` y `No puede hacer` producen el mismo resultado.
- Regla fija de una agenda del 50% sigue completándose con otra agenda del 50%.
- Persona no planificable y agenda sin demanda conservan las excepciones actuales.
- Dos reglas para la misma persona y día siguen rechazándose.

### Carga y recurrencias

- 100% ordinario sin peonada.
- 150% con una agenda completa y una parcial marcada como peonada.
- 150% con tres agendas parciales y elección explícita de una como peonada.
- 200% con elección exacta de la parte peonada.
- Agendas en ordinales distintos no se suman como si coincidieran.
- Una agenda configurada como peonada se guarda como ordinaria en fechas sin sobrecarga.
- Rechazo de 250%, exceso mal seleccionado y combinación recurrente imposible de clasificar.
- Una regla de 150% no recibe otra agenda opcional para alcanzar 200%.

### Generación y reparación diaria

- El optimizador conserva su límite interno ordinario del 100%.
- Una plaza reservada como peonada no puede asignarse también a otra persona ni aparecer como vacante.
- Cobertura, equidad, teletrabajo y presencialidad incluyen las peonadas reservadas antes de optimizar.
- Generación mensual persiste correctamente `fixed` y `peonada`.
- Cambio, cesión e intercambio de guardias tratan las peonadas fijas como reservas y conservan correctamente sus marcas.
- El pulido no mueve la asignación fija peonada.
- Los diferidos automáticos no utilizan días ya sobrecargados.
- Una guardia con regla telemática registra fallback si no cabe ninguna presencial.
- Eventos manuales bloqueados compatibles se preservan; los incompatibles producen un error explícito.
- Sobrescribir manualmente una agenda fija peonada conserva el flujo actual de confirmación y revisión.

### Persistencia, UI y métricas

- Migración desde reglas existentes sin pérdida de datos.
- Contratos API antiguos funcionan sin enviar `peonadaAgendaIds`.
- Creación, lectura y edición muestran la misma clasificación.
- Modificar carga, cobertura o recurrencia de una agenda revalida las reglas afectadas.
- Calendario, histórico, KPI de reglas fijas, equidad, teletrabajo, CSV e ICS reflejan la peonada sin cambiar sus fórmulas.

## Fuera de alcance

- Permitir varias reglas fijas para la misma persona y día.
- Añadir peonadas a `Debe hacer una` o `No puede hacer`.
- Crear demanda adicional mediante una regla personal.
- Rellenar automáticamente hasta el 200%.
- Ampliar al 200% la capacidad ordinaria interna del optimizador.
- Cambiar la prioridad de las reglas fijas frente a guardias, cobertura, equidad o pulido.
- Dar un peso estadístico diferente a la peonada generada por regla.
