# Planificación de agendas

Este contexto define el lenguaje usado para generar y evaluar calendarios del equipo de radiología.

## Acceso y aislamiento

**Cuenta de acceso**:
Identidad con usuario, contraseña y clave de recuperación que permite entrar en un único entorno. No representa una persona planificable.
_Avoid_: Miembro, profesional

**Entorno**:
Conjunto privado e independiente de hospitales, agendas, personas, reglas, calendarios e histórico perteneciente a una cuenta de acceso. No se comparte entre cuentas.
_Avoid_: Equipo compartido, organización

**Clave de recuperación**:
Secreto de un solo uso lógico que permite cambiar la contraseña sin correo. Se muestra al generarlo; una cuenta autenticada puede rotarlo y la clave anterior deja de ser válida.
_Avoid_: Segunda contraseña, código 2FA

**Actividad de cuenta**:
Último acceso autenticado o uso de la plataforma. Se actualiza como máximo una vez por hora y reinicia el plazo de conservación.
_Avoid_: Actividad de una persona, último calendario

**Caducidad por inactividad**:
Eliminación irreversible de una cuenta y de todo su entorno cuando han transcurrido más de seis meses naturales sin actividad de cuenta. Las cuentas existentes empiezan a contar desde la activación de esta política.
_Avoid_: Archivo, desactivación, baja

## Personas

**Persona**:
Profesional del equipo cuyo perfil e histórico se conservan aunque esté temporalmente inactivo.
_Avoid_: Médico, recurso, miembro

**Estado de planificación**:
Situación activa o inactiva de una persona; cada cambio queda fechado y solo las personas activas pueden planificarse.
_Avoid_: Baja, eliminación

**Turno de agenda**:
Franja temporal obligatoria de una agenda; puede ser de mañana o tarde, pero solo una.
_Avoid_: horario, jornada

**Agenda telemática**:
Agenda que se realiza sin presencia física en el servicio.
_Avoid_: tele, remota

**Patrón de trabajo**:
Secuencia de una a cinco semanas. Cada semana define días trabajados y cuáles son telemáticos; en estos últimos solo se permiten agendas telemáticas. La posición se calcula con el número ISO de la semana natural y se repite tras la última.

**Persona planificable**:
Persona con estado activo que trabaja en una fecha laborable y no tiene vacaciones ni post-guardia.
_Avoid_: Persona disponible, persona libre

**Capacidad**:
Relación que habilita a una persona para cubrir una agenda concreta.
_Avoid_: Permiso, preferencia

**Preferencia de agenda**:
Reacción opcional de una persona ante una agenda: corazón (+1 happy point), pulgar abajo (−1) o ausencia de reacción (indiferente, 0). No modifica la capacidad.

**Índice de felicidad**:
Happy points acumulados divididos por la carga asignada acumulada. Permite comparar personas con jornadas distintas; el histórico se reevalúa con las preferencias actuales.

**Vacaciones**:
Conjunto de días elegidos en los que una persona activa no puede planificarse; los días pasados son inmutables.
_Avoid_: Ausencia, baja

**Ausencia de planificación**:
Impedimento para planificar a una persona cuyo origen es vacaciones o post-guardia.
_Avoid_: Baja, inactividad

**Post-guardia**:
Ausencia derivada que afecta al día natural siguiente a una guardia.
_Avoid_: Descanso, libranza

**Guardia**:
Responsabilidad correspondiente a una fecha asumida por una persona del equipo y que genera post-guardia. Si se cede al exterior deja de ser una guardia activa dentro del calendario, aunque se conserva su transferencia en el histórico.
_Avoid_: Turno, agenda, guardia cancelada

**Cesión de guardia**:
Cambio unilateral de responsable en una fecha. El origen o el destino puede ser el exterior, pero no ambos.
_Avoid_: Cancelación, eliminación

**Cobertura externa de guardia**:
Extremo exterior registrado únicamente como participante de una cesión o intercambio. No es una guardia activa ni aparece en el calendario del equipo.
_Avoid_: Persona del equipo, guardia externa activa

**Intercambio de guardias**:
Permuta recíproca de responsables entre dos fechas. Uno de los participantes puede ser el exterior, lo que desplaza una guardia interna de una fecha a otra.
_Avoid_: Movimiento de guardia, edición de fecha

## Demanda y asignación

**Agenda**:
Tipo de actividad diaria que una persona capacitada puede cubrir en un hospital.
_Avoid_: Calendario, turno, tarea

**Carga de agenda**:
Porcentaje de jornada que ocupa una plaza: completa (100%) o media agenda (50%).
_Avoid_: Duración, prioridad

**Plaza**:
Unidad de demanda de una agenda en una fecha concreta.
_Avoid_: Hueco, puesto, agenda base

**Cobertura ordinaria**:
Número base de plazas de una agenda para cada día de la semana.
_Avoid_: Horario habitual

**Regla especial**:
Recurrencia mensual que añade una plaza de una agenda en un ordinal y día de la semana concretos.
_Avoid_: Excepción, cobertura extra

**Demanda diaria**:
Conjunto de plazas resultante de la cobertura ordinaria y las reglas especiales de una fecha.
_Avoid_: Carga, necesidades

**Asignación**:
Vínculo entre una persona planificable y una agenda en una fecha. La carga clínica ordinaria completa el 100% mediante una agenda completa o dos agendas diferentes del 50%.
_Avoid_: No asignación

**Intercambio de asignaciones**:
Sustitución simultánea y voluntaria de dos asignaciones clínicas de una misma fecha que conserva cubiertas ambas plazas y respeta todas las reglas duras.
_Avoid_: Edición de agenda, reasignación unilateral

**Cesión de asignación**:
Traslado manual de una asignación clínica a otra persona sin mover las asignaciones que esta ya tiene. Solo se ofrece cuando quien cede conserva al menos otra agenda ese día. Después se recalculan desde cero las peonadas de ambas personas.
_Avoid_: Intercambio, plaza extraordinaria

**Plaza extraordinaria**:
Actividad clínica añadida manualmente fuera de la demanda diaria ordinaria. Puede asignarse a una persona con o sin carga previa, cuenta en carga, histórico y equidad, pero no en cobertura ordinaria ni genera una vacante. Si eleva la carga por encima del 100%, debe clasificarse qué parte es peonada.
_Avoid_: Nueva agenda, cobertura extra, peonada

**Peonada**:
Marca de una asignación clínica demandada que identifica trabajo extraordinario por encima de la jornada ordinaria del 100%. Solo se aplica mediante edición manual posterior al generador y no convierte la asignación en una plaza extraordinaria. Si una reasignación cambia el reparto diario, las marcas afectadas se eliminan y se definen de nuevo solo para las personas que continúan por encima del 100%.
_Avoid_: Plaza extraordinaria, agenda extra, sobrecarga

**Asignación diferida**:
Asignación de una plaza telemática que no pudo cubrirse en su fecha de origen y se realiza dentro de los seis días naturales posteriores usando capacidad que habría quedado sin asignar. Conserva su fecha de origen y cubre la vacante original.
_Avoid_: Agenda nueva, peonada, cambio de fecha

**Jornada parcial excepcional**:
Día en que una persona cubre una única agenda del 50% porque la mejor cobertura requiere alguna jornada parcial. En empates, se completa antes la jornada de quien ya cubre la agenda más prioritaria.
_Avoid_: Media persona, sin asignación parcial

**Carga sin asignar**:
Jornada completa de una persona planificable que no ocupa ninguna agenda. No es una vacante porque no representa demanda.
_Avoid_: Vacante, agenda vacía

**Vacante**:
Plaza demandada que no puede cubrir ninguna persona planificable.
_Avoid_: No asignación, ausencia

**Regla fija**:
Restricción recurrente personal para un día semanal. Puede exigir todas o una de varias agendas con demanda y prohibir otras; solo se aplica cuando la persona es planificable y nunca crea demanda.
Si varias garantías personales reclaman la misma agenda, todas deben poder cumplirse: el sistema no elige una persona silenciosamente.
Puede sobreescribirse manualmente en un evento tras una confirmación explícita. La asignación fija nunca aparece como destino de un intercambio iniciado desde otra persona y la regla recurrente permanece intacta.
_Avoid_: Asignación individual obligatoria, preferencia

## Decisiones de reparto

**Prioridad de agenda**:
Nivel de importancia de cobertura: muy alta, alta, moderada o baja.
_Avoid_: Peso, orden manual

**Jornada de gestión**:
Actividad no asistencial de jornada completa (100%) asignada a una persona habilitada. Puede coexistir con actividad clínica manual hasta el límite diario del 200%, pero nunca puede clasificarse como peonada; cuenta como día telemático, no es una agenda ni crea una plaza.
_Avoid_: Agenda de gestión

**Actividad planificada**:
Trabajo visible en calendario e histórico. Puede ser una asignación de agenda clínica o una jornada de gestión; cada tipo conserva sus propias reglas y métricas.
_Avoid_: Agenda, cuando también se incluye gestión

**Cuota mensual de gestión**:
Objetivo protegido, entre uno y cinco días, declarado únicamente para una persona habilitada para gestión. Se reparte equitativamente y solo queda subordinado a la cobertura de prioridad muy alta.
_Avoid_: Agenda de gestión

**Perfil estadístico**:
Vector de porcentajes de las asignaciones de una persona entre las agendas activas, calculado dentro de su propia ventana histórica.
_Avoid_: Conteos por agenda, carga total

**Ventana histórica personal**:
Periodo acumulado comprendido entre el primer evento clínico conservado de una persona y el final del histórico disponible. Permite comparar perfiles normalizados con distinta antigüedad sin atribuir a una persona periodos anteriores a su incorporación.
_Avoid_: Histórico global, antigüedad del sistema

**Peso histórico de agenda**:
Proporción de la carga clínica realizada por el equipo que pertenece a una agenda dentro de la ventana histórica de la persona evaluada. Refleja su presencia real durante ese periodo, incluida su creación posterior, y no su cobertura semanal actual.
_Avoid_: Peso configurado, frecuencia semanal

**Perfil medio**:
Media aritmética no ponderada de los perfiles estadísticos comparables; cada persona aporta el mismo peso con independencia de su antigüedad.
_Avoid_: Perfil agregado, media ponderada por asignaciones

**Equidad histórica**:
Proximidad del perfil estadístico de cada persona al perfil medio del equipo durante su ventana histórica. Mide el resultado recibido: las capacidades y reglas fijas no excusan la concentración en una agenda.
_Avoid_: Igualdad de conteos, equidad anual, equidad corregible

**Señal de capacidad de plantilla**:
Clasificación prudente de las últimas ocho semanas planificadas que combina porcentaje de vacantes, persistencia semanal, concentración de la sobrecarga y días-persona sin asignar. Requiere al menos cuatro semanas. Solo indica déficit estructural probable cuando las vacantes superan el 5% de la demanda, aparecen en al menos tres semanas y en la mitad del periodo, sin concentrar el 60% en una única semana. Solo indica holgura estructural probable cuando no hay vacantes y la carga sin asignar supera el 10% de los días-persona en al menos la mitad de las semanas. Holgura no significa que sobren personas: también puede revelar un desajuste de capacidades.
_Avoid_: Exceso de plantilla, contar vacantes sin contexto, diagnóstico con una sola semana

**Evento de planificación**:
Actividad vigente de una persona en una fecha. Puede ser una agenda clínica, Gestión o una jornada sin asignación. Conserva su carga y si fue fija, extraordinaria o modificada manualmente.
_Avoid_: Propuesta, versión, evento de dominio

**Calendario vigente**:
Proyección por fechas de todos los eventos de planificación, vacantes, guardias y ausencias conservados. No tiene estados de borrador o publicación.
_Avoid_: Propuesta actual, calendario definitivo

**Ejecución de generación**:
Registro técnico de una ejecución del optimizador: entrada, estado, diagnóstico y resultado. Sirve para auditoría y nunca decide qué eventos están vigentes.
_Avoid_: Calendario, propuesta, versión
