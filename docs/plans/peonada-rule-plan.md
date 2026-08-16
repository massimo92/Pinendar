# Plan en espera: reglas `Debe hacer todas` con peonadas

## Objetivo

Permitir que una regla de tipo **Debe hacer todas** agrupe agendas con una carga total de hasta el 200%. La parte que supera el 100% debe quedar identificada explícitamente como peonada.

La regla expresa una obligación recurrente de la persona: no es una asignación extraordinaria aislada, sino una pauta que el generador debe respetar en cada periodo compatible.

## Modelo funcional

- El límite actual de la regla pasa de 100% a 200%.
- La selección sigue siendo una lista de agendas con su porcentaje de carga.
- La suma total debe estar entre 0% y 200% y no puede superar el 200%.
- La carga ordinaria se considera hasta el 100%.
- La carga que excede el 100% se marca como peonada.
- La persona puede tener, por ejemplo, 100% ordinario + 100% de peonada, o 75% ordinario + 50% de peonada.
- La peonada no cambia la naturaleza de la agenda: una agenda telemática sigue siendo telemática y una presencial sigue siendo presencial.
- Se mantienen las capacidades, vacaciones, festivos, guardias, límites diarios y demás restricciones existentes.
- La regla no permite superar el límite diario global del sistema.

## Reparto de la carga

Para cada fecha candidata, el generador debe calcular la carga acumulada de la persona y aplicar la regla:

1. Comprueba que todas las agendas seleccionadas por la regla pueden asignarse.
2. Asigna la parte necesaria hasta completar el 100% ordinario.
3. Si queda carga adicional y hay capacidad diaria, asigna el exceso como peonada.
4. Si no puede cumplir la regla completa, la fecha no se considera válida para esa regla; no se asigna una parte arbitraria que deje una obligación incoherente.

La clasificación como peonada debe persistir en el evento generado y recalcularse si posteriormente cambia la composición de la asignación.

## Momento dentro del generador

La restricción se incorpora al construir el modelo de asignación, junto con las demás reglas fijas, antes de las fases de cobertura y equidad.

Orden conceptual:

1. Validar reglas y detectar combinaciones imposibles.
2. Fijar guardias y la obligación de agenda presencial cuando corresponda.
3. Aplicar las reglas `Debe hacer todas`, incluyendo la carga superior al 100% como peonada.
4. Maximizar la cobertura ordinaria por prioridad.
5. Asignar y equilibrar diferidos automáticos.
6. Optimizar equidad y equilibrio telemático.
7. Ejecutar el pulido permitido, sin mover asignaciones fijadas por reglas salvo que se mantenga exactamente la obligación.

Las asignaciones derivadas de esta regla deben tratarse como fijas durante las fases posteriores: el optimizador puede completar otros huecos, pero no romper la obligación ni convertir una parte peonada en ordinaria sin recalcularla correctamente.

## UI de creación

- Sustituir el texto que indica que la suma máxima es 100% por una explicación de máximo 200%.
- Mostrar en todo momento la carga total seleccionada.
- Separar visualmente:
  - **Carga ordinaria**: hasta 100%.
  - **Carga peonada**: exceso sobre 100%.
- Mostrar una advertencia clara cuando la selección supere el 100%:
  “La càrrega per sobre del 100% es generarà com a peonada.”
- Bloquear el guardado por encima del 200% o si falta una agenda/carga válida.
- Indicar que la regla es recurrente y puede producir una peonada en cada fecha en la que se cumplan las condiciones.

## UI de lectura y edición

En el perfil de la persona, la regla debe mostrar:

- nombre de la regla;
- agendas incluidas y porcentaje de cada una;
- carga total;
- carga ordinaria;
- carga peonada;
- una etiqueta visible `Incluye peonada` cuando el total supera el 100%.

Ejemplo:

> Debe hacer todas · 150% total  
> RM matí 100% · Consultes 50%  
> Ordinaria 100% · Peonada 50%

La edición debe reutilizar la misma validación y recalcular inmediatamente estos tres valores.

## Persistencia y compatibilidad

- Añadir a la regla la información necesaria para conservar la carga total y la parte peonada de forma determinista.
- Las reglas existentes de hasta 100% deben seguir funcionando sin migración manual.
- La migración debe ser aditiva y conservar todas las reglas actuales.
- Los eventos generados deben persistir la marca de peonada que ya utiliza el calendario y las exportaciones.

## Validaciones y conflictos

Validar antes de lanzar el solver:

- suma superior a 200%;
- agenda repetida en la misma regla;
- agenda no activa o persona no capacitada;
- combinación incompatible con una guardia o una restricción fija;
- exceso sobre el límite diario permitido;
- obligación imposible por falta de fechas compatibles.

Los errores deben explicar qué agenda, fecha o límite provoca el conflicto.

## Pruebas necesarias

- Crear y editar reglas del 100%, 150% y 200%.
- Rechazar 200% + cualquier exceso.
- Generar una fecha con 100% ordinario + 50% peonada.
- Verificar que la peonada aparece en calendario, histórico, métricas, CSV e ICS.
- Confirmar que guardias, vacaciones, capacidades y límites diarios siguen prevaleciendo.
- Confirmar que el pulido no elimina ni degrada la obligación de la regla.
- Mantener compatibilidad con reglas antiguas del 100%.
- Probar conflictos y mensajes de validación en backend y frontend.

## Decisiones pendientes antes de implementar

1. Confirmar si una regla de 150% debe exigir siempre exactamente 150% o si puede cumplirse con cualquier carga entre 100% y 150% cuando no exista una solución completa.
2. Confirmar si varias reglas `Debe hacer todas` de la misma persona pueden coexistir y cómo se combinan.
3. Confirmar si la peonada resultante debe contar para los objetivos de equidad con el mismo peso que una peonada manual.
4. Confirmar el texto final de las etiquetas y mensajes en catalán.

