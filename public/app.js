import { api, waitForGeneration } from './api.js?v=7';
import { LEGACY_AGENDAS, normalizeBootstrapState } from './state.js?v=2';
import { MANAGEMENT_ACTIVITY, compactActivityMeta, compactHospitalName, historicalActivityCounts, planningActivities, planningActivityGroups, sortByName } from './activity-utils.mjs?v=4';
import { calendarIncidentsForDate, dailyAssignmentLoad, eligibleUnassignedMemberIds, vacanciesForDate } from './calendar-utils.mjs?v=2';
import { headerTemplate, loginTemplate, navTemplate, shellTemplate } from './views.js?v=5';
const DAYS = ['Dilluns', 'Dimarts', 'Dimecres', 'Dijous', 'Divendres'];
const DAYS_SHORT = ['Dl', 'Dt', 'Dc', 'Dj', 'Dv'];
const WEEK_SHORT = ['Dl', 'Dt', 'Dc', 'Dj', 'Dv', 'Ds', 'Dg'];
const SHIFT_LABELS = { morning: 'Matí', afternoon: 'Tarda' };
const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const app = $('#app');
let state = null;
let page = 'calendar';
let quarter = currentQuarter();
let selectedMemberFilters = new Set();
let selectedAgendaFilters = new Set();
let selectedCalendarIssueFilters = new Set();
let openCalendarFilter = '';
let calendarView = 'month';
let calendarDate = dateKey(new Date());
let modal = null;
let historyMemberFilter = '';
let hospitalMap = null;
let pendingHospitalLocation = null;
let hospitalSearchResults = [];
let hospitalSearchStatus = '';
let hospitalSearchBusy = false;
let hospitalSearchQuery = '';
let hospitalSearchTimer = null;
let hospitalSearchSequence = 0;
const hospitalSearchCache = new Map();
const hospitalDetailsCache = new Map();
const ES_TEXT = {
  'Calendari': 'Calendario', 'CALENDARI': 'CALENDARIO', 'Equip': 'Equipo', 'Configuració': 'Configuración', 'Equitat i històric': 'Equidad e histórico', 'Surt': 'Salir',
  'Genera un altre període': 'Generar otro período', 'Prepara el calendari': 'Prepara el calendario', 'Genera calendari': 'Generar calendario', 'Exporta': 'Exportar',
  'Respecta els filtres actius': 'Respeta los filtros activos', 'Avui': 'Hoy', 'Anterior': 'Anterior', 'Següent': 'Siguiente', 'Persones': 'Personas', 'Tothom': 'Todos',
  'Agendes': 'Agendas', 'Totes': 'Todas', 'Dia': 'Día', 'Setmana': 'Semana', 'Mes': 'Mes', 'Festiu': 'Festivo', 'No assignació': 'Sin asignación', 'Sense assignació': 'Sin asignación',
  'Guàrdia': 'Guardia', 'Vacances': 'Vacaciones', 'Afegeix membre': 'Añadir miembro', 'Perfil actiu': 'Perfil activo', 'Inactiu': 'Inactivo',
  'Persones': 'Personas', 'Gestiona perfils, disponibilitat i regles fixes.': 'Gestiona perfiles, disponibilidad y reglas fijas.', 'Absències': 'Ausencias',
  'Vacances, baixes i altres indisponibilitats.': 'Vacaciones, bajas y otras indisponibilidades.', 'Sense absències registrades.': 'Sin ausencias registradas.',
  'Catàleg d’agendes': 'Catálogo de agendas', 'Cada perfil defineix hospital, torn, modalitat, cobertura setmanal i color automàtic.': 'Cada perfil define hospital, turno, modalidad, cobertura semanal y color automático.',
  'Telemàtica': 'Telemática', 'Presencial': 'Presencial', 'Edita': 'Editar', 'Elimina': 'Eliminar', 'Hospital no assignat': 'Hospital no asignado',
  'Servei de Radiologia Abdominal': 'Servicio de Radiología Abdominal', 'Hospitals coberts i festius': 'Hospitales cubiertos y festivos', 'Cerca hospitals': 'Buscar hospitales', 'Hospital o municipi': 'Hospital o municipio',
  'COBERTURA TERRITORIAL': 'COBERTURA TERRITORIAL', 'Catàleg oficial local d’institucions públiques i mixtes. Cerca per hospital, municipi o província.': 'Catálogo oficial local de instituciones públicas y mixtas. Busca por hospital, municipio o provincia.',
  'Cerca hospital': 'Buscar hospital', 'Hospitals públics i de xarxa pública precarregats.': 'Hospitales públicos y de red pública precargados.', 'Mapa d’hospitals coberts': 'Mapa de hospitales cubiertos',
  'HOSPITALS AFEGITS': 'HOSPITALES AÑADIDOS', 'Festius': 'Festivos',
  'Selecciona un hospital dels resultats': 'Selecciona un hospital de los resultados', 'Afegeix hospital': 'Añadir hospital', 'Hospitals coberts': 'Hospitales cubiertos',
  'Centre amb localització desconeguda': 'Centro con ubicación desconocida', 'Localització desconeguda': 'Ubicación desconocida', 'Afegeix centre': 'Añadir centro', 'CENTRE MANUAL': 'CENTRO MANUAL',
  'Clica un hospital per centrar-ne l’àrea al mapa.': 'Pulsa un hospital para centrar su área en el mapa.', 'Data festiva': 'Fecha festiva', 'Afegeix festiu': 'Añadir festivo',
  'Sense festius afegits.': 'Sin festivos añadidos.', 'Es mostraran directament al calendari principal.': 'Se mostrarán directamente en el calendario principal.',
  'Índex global d’equilibri': 'Índice global de equilibrio', 'Agenda més desviada': 'Agenda más desviada', 'Dins del marge ±20%': 'Dentro del margen ±20%',
  'Equilibri d’una persona': 'Equilibrio de una persona', 'Equilibri entre persones': 'Equilibrio entre personas', 'Per sota': 'Por debajo', 'Esperat': 'Esperado', 'Per sobre': 'Por encima',
  'Teletreball': 'Teletrabajo', 'Equip = mitjana real de les persones.': 'Equipo = media real de las personas.', 'Sense activitat per calcular-ho.': 'Sin actividad para calcularlo.',
  'Períodes registrats': 'Períodos registrados', 'Calendari': 'Calendario', 'Històric': 'Histórico', 'Còpia JSON': 'Copia JSON',
  'Color automàtic': 'Color automático', 'Pastel per distingir persones': 'Pastel para distinguir personas', 'Saturat per distingir agendes': 'Saturado para distinguir agendas',
  'Nou color aleatori': 'Nuevo color aleatorio', 'Nom i cognoms': 'Nombre y apellidos', 'Correu': 'Correo', 'Dies disponibles': 'Días disponibles',
  'Patró de treball': 'Patrón de trabajo', 'Quins dies s’ha de planificar aquesta persona?': '¿Qué días debe planificarse esta persona?', 'Sempre igual': 'Siempre igual', 'Alterna setmanes': 'Alterna semanas', 'Treball': 'Trabajo',
  'Les setmanes segueixen el número ISO i tornen a començar després de l’última.': 'Las semanas siguen el número ISO y vuelven a empezar después de la última.', 'Afegeix setmana': 'Añadir semana', 'Elimina setmana': 'Eliminar semana',
  'Càrrega': 'Carga', 'Completa': 'Completa', 'Parcial': 'Parcial', 'Perfil desat': 'Perfil guardado', 'Els canvis s’han guardat correctament.': 'Los cambios se han guardado correctamente.',
  'EQUIP': 'EQUIPO', 'Nou membre': 'Nuevo miembro', 'Edita membre': 'Editar miembro', 'AGENDES': 'AGENDAS',
  'Les persones inactives no entren en la generació del calendari.': 'Las personas inactivas no entran en la generación del calendario.', 'Gestió': 'Gestión', 'Sense hospital': 'Sin hospital', 'Altres activitats': 'Otras actividades', 'Fa gestió': 'Hace Gestión', 'Dies de gestió al mes': 'Días de Gestión al mes', 'Gestió al calendari': 'Gestión en el calendario', 'persones habilitades': 'personas habilitadas', 'Cap persona habilitada': 'Ninguna persona habilitada',
  'Dies obligatoris de treball telemàtic': 'Días obligatorios de trabajo telemático', 'Agendes habilitades': 'Agendas habilitadas', 'Quota mensual de gestió': 'Cuota mensual de gestión',
  'Afegeix ♥ o 👎 per indicar preferències. Sense reacció significa indiferent.': 'Añade ♥ o 👎 para indicar preferencias. Sin reacción significa indiferente.', 'Agrada': 'Le gusta', 'Desagrada': 'Le disgusta', 'Afegeix reacció': 'Añadir reacción', 'Treu la reacció': 'Quitar la reacción',
  'Perfil general': 'Perfil general', 'Regles fixes': 'Reglas fijas', 'Afegeix regla': 'Añadir regla', 'Encara no hi ha regles fixes.': 'Todavía no hay reglas fijas.',
  'Reserva una agenda recurrente per dia de la setmana.': 'Reserva una agenda recurrente por día de la semana.',
  'Desa membre': 'Guardar miembro', 'Cancel·la': 'Cancelar', 'Categoria': 'Categoría', 'Data d’inici': 'Fecha de inicio', 'Data final': 'Fecha final',
  'Explicació': 'Explicación', 'Desa absència': 'Guardar ausencia', 'Nova agenda': 'Nueva agenda', 'Edita agenda': 'Editar agenda', 'Hospital': 'Hospital', 'Torn': 'Turno', 'Matí': 'Mañana', 'Tarda': 'Tarde',
  'Selecciona un hospital': 'Selecciona un hospital', 'Telemàtic': 'Telemático', 'Cobertura ordinària': 'Cobertura ordinaria', 'Places necessàries per dia': 'Plazas necesarias por día',
  'Prioritat': 'Prioridad', '1 és la prioritat més alta': '1 es la prioridad más alta', 'Regles especials': 'Reglas especiales', 'Demanda addicional recurrent': 'Demanda adicional recurrent',
  'Afegeix opció': 'Añadir opción', 'Encara no hi ha regles especials.': 'Todavía no hay reglas especiales.', 'del mes': 'del mes', 'places': 'plazas',
  'Desa agenda': 'Guardar agenda', 'Elimina agenda': 'Eliminar agenda', 'Es conservarà l’històric': 'Se conservará el histórico',
  'REGLES AFECTADES': 'REGLAS AFECTADAS', 'No es pot aplicar directament': 'No se puede aplicar directamente', 'Torna a editar': 'Volver a editar', 'Esborra regles i desa': 'Borrar reglas y guardar',
  'Revisa-les abans de continuar. Si confirmes, l’agenda i les regles s’actualitzaran alhora.': 'Revísalas antes de continuar. Si confirmas, la agenda y las reglas se actualizarán a la vez.',
  'REGLA COMPARTIDA': 'REGLA COMPARTIDA', 'Aquesta regla ja existeix': 'Esta regla ya existe', 'La nova regla es compartirà': 'La nueva regla será compartida', 'Quan hi hagi menys places que persones disponibles, el planificador escollirà entre elles.': 'Cuando haya menos plazas que personas disponibles, el planificador elegirá entre ellas.',
  'Confirma i desa': 'Confirmar y guardar', 'REGLES RELACIONADES': 'REGLAS RELACIONADAS', 'Torna a l’agenda': 'Volver a la agenda', 'Perfil inactiu': 'Perfil inactivo', 'Aquesta agenda no té cap regla relacionada.': 'Esta agenda no tiene ninguna regla relacionada.', 'Consulta les persones i dies vinculats a aquesta agenda.': 'Consulta las personas y días vinculados a esta agenda.',
  'Dilluns': 'Lunes', 'Dimarts': 'Martes', 'Dimecres': 'Miércoles', 'Dijous': 'Jueves', 'Divendres': 'Viernes',
  'Es conservaran els esdeveniments passats': 'Se conservarán los eventos pasados', 'Paraula de confirmació': 'Palabra de confirmación', 'Elimina definitivament': 'Eliminar definitivamente',
  'Assignació': 'Asignación', 'Agenda': 'Agenda', 'Desa canvi': 'Guardar cambio', 'NOU PERÍODE': 'NUEVO PERÍODO', 'Genera el calendari': 'Generar el calendario', 'Mes complet': 'Mes completo', 'Selecciona directament un mes i un any.': 'Selecciona directamente un mes y un año.', 'Període personalitzat': 'Período personalizado', 'Escull manualment les dates dins d’un únic mes.': 'Escoge manualmente las fechas dentro de un único mes.', 'Mes a generar': 'Mes a generar', 'Data inicial': 'Fecha inicial', 'Data final': 'Fecha final', 'Es generarà únicament el mes seleccionat.': 'Se generará únicamente el mes seleccionado.', 'Les dues dates han de pertànyer al mateix mes natural.': 'Las dos fechas deben pertenecer al mismo mes natural.',
  'Esborra període': 'Borrar período', 'ESBORRA PERÍODE': 'BORRAR PERÍODO', 'Contingut del calendari': 'Contenido del calendario',
  'Contingut del calendari eliminat dins del període seleccionat': 'Contenido del calendario eliminado dentro del período seleccionado',
  'El canvi quedarà fixat al calendari.': 'El cambio quedará fijado en el calendario.', 'Defineix el període i les incidències noves.': 'Define el período y las incidencias nuevas.',
  'Tria un període d’entre 1 i 3 mesos. El mes final mai pot ser anterior a l’inicial.': 'Selecciona un período de entre 1 y 3 meses. El mes final nunca puede ser anterior al inicial.',
  'Comencen buits i només afecten el període. Les absències permanents i els festius ja s’apliquen automàticament.': 'Empiezan vacíos y sólo afectan al período. Las ausencias permanentes y los festivos ya se aplican automáticamente.',
  'Mes d’inici': 'Mes inicial', 'Mes final': 'Mes final', 'Condicionants variables': 'Condicionantes variables', 'Guàrdies': 'Guardias', 'Exporta plantilla': 'Exportar plantilla',
  'Importa XLS': 'Importar XLS', 'Persona': 'Persona', 'Data': 'Fecha', 'Afegeix': 'Añadir', 'Sense guàrdies.': 'Sin guardias.', 'Tipus': 'Tipo', 'Inici': 'Inicio', 'Final': 'Final',
  'Sense vacances puntuals.': 'Sin vacaciones puntuales.', 'Vacances puntuals': 'Vacaciones puntuales', 'Tanca': 'Cerrar', 'Dades locals · SQLite': 'Datos locales · SQLite', 'Àrea no disponible': 'Área no disponible',
  'Evolució de la felicitat': 'Evolución de la felicidad', 'Índex acumulat ponderat per càrrega: ♥ suma, 👎 resta i sense reacció no modifica el resultat.': 'Índice acumulado ponderado por carga: ♥ suma, 👎 resta y sin reacción no modifica el resultado.', 'Mitjana de l’equip': 'Media del equipo', 'La sèrie històrica es recalcula amb les preferències actuals. La mitjana de l’equip està ressaltada.': 'La serie histórica se recalcula con las preferencias actuales. La media del equipo está resaltada.', 'Sense assignacions per calcular la felicitat.': 'Sin asignaciones para calcular la felicidad.',
  'Any de mes d’inici': 'Año del mes inicial', 'Any de mes final': 'Año del mes final', 'Selecciona una persona': 'Selecciona una persona', 'i': 'y',
  'Ex. Bellvitge o Barcelona': 'Ej. Bellvitge o Barcelona', 'Ex. Núria Prat': 'Ej. Nuria Prat', 'nom@hospital.cat': 'nombre@hospital.es', 'Ex. Ecografia avançada': 'Ej. Ecografía avanzada', 'Afegeix un detall breu': 'Añade un detalle breve',
  'Totes les agendes han de tenir un hospital vàlid': 'Todas las agendas deben tener un hospital válido', 'Les regles fixes superen la cobertura disponible': 'Las reglas fijas superan la cobertura disponible',
  'El període del calendari ha de ser d’un màxim d’un mes': 'El período del calendario debe ser de un máximo de un mes', 'Ja hi ha esdeveniments dins del període seleccionat': 'Ya hay eventos dentro del período seleccionado',
  'Una persona no pot tenir dues assignacions el mateix dia': 'Una persona no puede tener dos asignaciones el mismo día', 'Les guàrdies han d’estar dins del període del calendari': 'Las guardias deben estar dentro del período del calendario', 'Les absències han d’estar dins del període del calendari': 'Las ausencias deben estar dentro del período del calendario',
  'Hi ha una absència amb dates invàlides': 'Hay una ausencia con fechas no válidas', 'Hi ha una guàrdia associada a una persona inexistent': 'Hay una guardia asociada a una persona inexistente',
  'TAC ambulatori': 'TAC ambulatorio', 'Eco ambulatòria': 'Ecografía ambulatoria', 'TAC urgent': 'TAC urgente', 'Eco urgent': 'Ecografía urgente',
  'Eco tècnics': 'Ecografía técnicos', 'Ressonància': 'Resonancia', 'Intervencionisme': 'Intervencionismo', 'Gestió': 'Gestión', 'Telecomandament': 'Telemando',
  'Guàrdies actives': 'Guardias activas', 'Entrada des de l’exterior': 'Entrada desde el exterior', 'COM FUNCIONA': 'CÓMO FUNCIONA', 'Dos moviments clars': 'Dos movimientos claros',
  'Cessió': 'Cesión', 'Canvia el responsable d’una data. Una part pot ser exterior.': 'Cambia el responsable de una fecha. Una parte puede ser exterior.', 'Intercanvi': 'Intercambio',
  'Permuta dues guàrdies. Amb Exterior, la guàrdia surt del calendari intern.': 'Permuta dos guardias. Con Exterior, la guardia sale del calendario interno.', 'Abans d’aplicar, Pinendar ensenya els canvis mínims al calendari.': 'Antes de aplicar, Pinendar muestra los cambios mínimos en el calendario.',
  'Històric de canvis': 'Histórico de cambios', 'Les cobertures exteriors només consten aquí.': 'Las coberturas exteriores sólo constan aquí.', 'Encara no s’ha modificat cap guàrdia.': 'Todavía no se ha modificado ninguna guardia.',
  'Cedeix': 'Ceder', 'Intercanvia': 'Intercambiar', 'GUÀRDIA': 'GUARDIA', 'Gestiona la guàrdia': 'Gestiona la guardia', 'Canvia el responsable d’aquesta guàrdia.': 'Cambia el responsable de esta guardia.', 'Permuta-la amb una altra guàrdia.': 'Intercámbiala con otra guardia.', 'CESSIÓ DE GUÀRDIA': 'CESIÓN DE GUARDIA', 'Canvia el responsable': 'Cambia el responsable', 'Origen': 'Origen',
  'Data de la guàrdia': 'Fecha de la guardia', 'Nou responsable': 'Nuevo responsable', 'Nota opcional': 'Nota opcional', 'Motiu o referència del canvi': 'Motivo o referencia del cambio',
  'El calendari no canviarà fins que revisis i confirmis l’impacte.': 'El calendario no cambiará hasta que revises y confirmes el impacto.', 'Revisa l’impacte': 'Revisar el impacto',
  'INTERCANVI DE GUÀRDIES': 'INTERCAMBIO DE GUARDIAS', 'Permuta dues guàrdies': 'Permuta dos guardias', 'Intercanvia amb': 'Intercambia con', 'Nova data': 'Nueva fecha', 'La guàrdia sortirà del calendari intern. El canvi quedarà registrat a l’històric.': 'La guardia saldrá del calendario interno. El cambio quedará registrado en el histórico.',
  'IMPACTE AL CALENDARI': 'IMPACTO EN EL CALENDARIO', 'Revisa abans d’aplicar': 'Revisa antes de aplicar', 'Aplica el canvi': 'Aplicar el cambio', 'Calculant impacte…': 'Calculando impacto…', 'Selecciona una persona per veure l’impacte.': 'Selecciona una persona para ver el impacto.',
  'Les places ordinàries tenen prioritat sobre les extraordinàries. L’operació i el seu impacte quedaran a l’històric.': 'Las plazas ordinarias tienen prioridad sobre las extraordinarias. La operación y su impacto quedarán en el histórico.'
};

function currentQuarter() {
  const d = new Date(); const month = Math.floor(d.getMonth() / 3) * 3 + 1;
  return `${d.getFullYear()}-${String(month).padStart(2, '0')}`;
}
function uid() { return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(16).slice(2); }
function esc(value = '') { return String(value).replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c])); }
function dateKey(d) { return d.toISOString().slice(0, 10); }
function fromKey(key) { return new Date(`${key}T12:00:00Z`); }
function isValidDateKey(value) { return /^\d{4}-\d{2}-\d{2}$/.test(value || '') && dateKey(fromKey(value)) === value; }
function addDays(key, n) { const d = fromKey(key); d.setUTCDate(d.getUTCDate() + n); return dateKey(d); }
function weekday(key) { return fromKey(key).getUTCDay(); }
function isoWeekNumber(key) { const value = fromKey(key); const target = new Date(value); target.setUTCDate(target.getUTCDate() + 4 - (target.getUTCDay() || 7)); const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1, 12)); return Math.ceil((((target - yearStart) / 86400000) + 1) / 7); }
function monthKey(key) { return key.slice(0, 7); }
function startOfWeek(key) { return addDays(key, -((weekday(key) + 6) % 7)); }
function endOfMonth(key) { const d = fromKey(`${monthKey(key)}-01`); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(0); return dateKey(d); }
function calendarEvents() { return state?.calendar?.events || []; }
function calendarVacancies() { return state?.calendar?.vacancies || []; }
function calendarGuards() { return state?.calendar?.guards || []; }
function calendarAbsences() { return state?.calendar?.absences || []; }
function calendarBounds() {
  const dates = [
    ...calendarEvents().map((item) => item.date),
    ...calendarVacancies().map((item) => item.date),
  ].filter(Boolean).sort();
  const fallback = `${monthKey(calendarDate)}-01`;
  return { start: dates[0] || fallback, end: dates.at(-1) || endOfMonth(fallback) };
}
function calendarProjection() {
  const bounds = calendarBounds();
  return {
    startMonth: monthKey(bounds.start),
    endMonth: monthKey(bounds.end),
    startDate: bounds.start,
    endDate: bounds.end,
    assignments: calendarEvents(),
    unfilled: calendarVacancies(),
    conditions: {
      guards: calendarGuards(),
      guardTransfers: state?.calendar?.guardTransfers || [],
      absences: calendarAbsences(),
    },
  };
}
function hasCalendarContent() { return calendarEvents().length > 0 || calendarVacancies().length > 0; }
function nextGenerationMonth() {
  const latestEventDate = calendarEvents().map((item) => item.date).sort().at(-1);
  return latestEventDate ? monthKey(addMonths(`${monthKey(latestEventDate)}-01`, 1)) : monthKey(calendarDate);
}
function fmtDate(key, options = { weekday: 'short', day: 'numeric', month: 'short' }) { return new Intl.DateTimeFormat(state?.language === 'es' ? 'es-ES' : 'ca-ES', options).format(fromKey(key)); }
function ordinalLabel(value) { return (state?.language === 'es' ? ['', '1.º', '2.º', '3.º', '4.º', '5.º'] : ['', '1r', '2n', '3r', '4t', '5è'])[Number(value)] || String(value); }
function priorityLabel(value) { return (state?.language === 'es' ? ['', 'Muy alta', 'Alta', 'Moderada', 'Baja'] : ['', 'Molt alta', 'Alta', 'Moderada', 'Baixa'])[Number(value)] || 'Moderada'; }
function shiftLabel(value) { if (state?.language !== 'es') return SHIFT_LABELS[value] || SHIFT_LABELS.morning; return { morning: 'Mañana', afternoon: 'Tarde' }[value] || 'Mañana'; }
function loadLabel(value) { return Number(value) === 50 ? 'Parcial' : 'Completa'; }
function priorityOptions(selected = 3) { return [1, 2, 3, 4].map((value) => `<option value="${value}" ${Number(selected) === value ? 'selected' : ''}>${priorityLabel(value)}</option>`).join(''); }
function activeAgendas() { return state.agendas || []; }
function activeActivities() { return planningActivities(activeAgendas()); }
function agenda(id) { return id === 'management' ? MANAGEMENT_ACTIVITY : state?.agendas?.find((item) => item.id === id) || state?.archivedAgendas?.find((item) => item.id === id) || LEGACY_AGENDAS.find((item) => item.id === id) || { id, name: 'Agenda eliminada', telematic: false, color: '#75817e' }; }
function agendaHospital(item) { return state?.hospitals?.find((hospital) => hospital.catalogId === item?.hospitalId); }
function agendaGroups(items = activeAgendas()) {
  const groups = state.hospitals.map((hospital) => ({ hospital, items: items.filter((item) => item.hospitalId === hospital.catalogId) })).filter((group) => group.items.length);
  const known = new Set(state.hospitals.map((hospital) => hospital.catalogId)); const unassigned = items.filter((item) => !known.has(item.hospitalId));
  if (unassigned.length) groups.push({ hospital: { catalogId: '', name: 'Hospital no assignat' }, items: unassigned });
  groups.forEach((group) => group.items.sort((left, right) => left.name.localeCompare(right.name, state.language === 'es' ? 'es' : 'ca')));
  return groups;
}
function hospitalOptions(selected = '') { return state.hospitals.map((hospital) => `<option value="${esc(hospital.catalogId)}" ${hospital.catalogId === selected ? 'selected' : ''}>${esc(hospital.name)}</option>`).join(''); }
function isTele(type) { return Boolean(agenda(type).telematic); }
function t(key) { return ({ calendar: state?.language === 'es' ? 'Calendario' : 'Calendari', guards: state?.language === 'es' ? 'Guardias' : 'Guàrdies', team: state?.language === 'es' ? 'Equipo' : 'Equip', agendas: 'Agendas', setup: state?.language === 'es' ? 'Configuración' : 'Configuració', history: state?.language === 'es' ? 'Equidad e histórico' : 'Històric', guide: state?.language === 'es' ? 'Guía de uso' : 'Guia d’ús' }[key] || key); }
function localize(value = '') {
  if (state?.language !== 'es') return String(value);
  const text = String(value); const core = text.trim(); if (!core) return text;
  if (ES_TEXT[core]) return text.replace(core, ES_TEXT[core]);
  let translated = core;
  translated = translated
    .replace(/(\d+) assignacions/g, '$1 asignaciones').replace(/(\d+) vacants/g, '$1 vacantes')
    .replace(/(\d+) membres actius/g, '$1 miembros activos').replace(/(\d+) tipus d’agenda/g, '$1 tipos de agenda')
    .replace(/(\d+) membres habilitats/g, '$1 miembros habilitados').replace(/(\d+) places\/setmana/g, '$1 plazas/semana')
    .replace(/(\d+) agendes/g, '$1 agendas').replace(/(\d+) regles fixes/g, '$1 reglas fijas').replace(/(\d+) absències previstes/g, '$1 ausencias previstas')
    .replace(/(\d+) guàrdies internes/g, '$1 guardias internas').replace(/(\d+) canvis/g, '$1 cambios').replace(/Postguàrdia/g, 'Postguardia')
    .replace(/Sense calendari generat/g, 'Sin calendario generado')
    .replace(/^Dates entre (.+) i (.+)\. XLS: columnes Persona i Data\.$/, 'Fechas entre $1 y $2. XLS: columnas Persona y Fecha.')
    .replace(/^Dates entre (.+) i (.+)\. XLS: Persona, Tipus, Inici i Final\.$/, 'Fechas entre $1 y $2. XLS: Persona, Tipo, Inicio y Final.')
    .replace(/^(.+) té més d’una regla fixa el mateix dia$/, '$1 tiene más de una regla fija el mismo día')
    .replace(/^Ja existeix una persona amb el nom (.+)$/, 'Ya existe una persona con el nombre $1').replace(/^Ja existeix una persona amb el correu (.+)$/, 'Ya existe una persona con el correo $1')
    .replace(/^L’hospital (.+) no existeix al catàleg$/, 'El hospital $1 no existe en el catálogo').replace(/^L’hospital (.+) no té una àrea disponible al mapa$/, 'El hospital $1 no tiene un área disponible en el mapa')
    .replace(/^La nova cobertura de (.+) elimina aquestes regles fixes$/, 'La nueva cobertura de $1 elimina estas reglas fijas')
    .replace(/^⚠ També s’aplica a (.+)$/, '⚠ También se aplica a $1').replace(/^També s’aplica a (.+)$/, 'También se aplica a $1')
    .replace(/^Setmana (\d+)$/, 'Semana $1')
    .replace(/^Regles relacionades · (\d+)$/, 'Reglas relacionadas · $1')
    .replace(/(\d+) p\. p\. per sobre de l’esperat/g, '$1 p. p. por encima de lo esperado').replace(/(\d+) p\. p\. per sota de l’esperat/g, '$1 p. p. por debajo de lo esperado')
    .replace(/Esperat (\d+)%/g, 'Esperado $1%').replace(/En línia amb el repartiment esperat/g, 'En línea con el reparto esperado')
    .replace(/Sense activitat per calcular-ho\./g, 'Sin actividad para calcularlo.').replace(/Esperat segons la proporció global d’agendes telemàtiques\./g, 'Esperado según la proporción global de agendas telemáticas.')
    .replace(/\bequip (\d+)%/g, 'equipo $1%')
    .replace(/Equip = mitjana real de les persones\./g, 'Equipo = media real de las personas.')
    .replace(/Obre /g, 'Abrir ').replace(/Mostra /g, 'Mostrar ').replace(/Elimina /g, 'Eliminar ').replace(/disponible /g, 'disponible ')
    .replace(/ seleccionada$/g, ' seleccionada').replace(/ seleccionades$/g, ' seleccionadas').replace(/ més$/g, ' más')
    .replace(/TAC ambulatori/g, 'TAC ambulatorio').replace(/Eco ambulatòria/g, 'Ecografía ambulatoria').replace(/TAC urgent/g, 'TAC urgente').replace(/Eco urgent/g, 'Ecografía urgente')
    .replace(/Eco tècnics/g, 'Ecografía técnicos').replace(/Ressonància/g, 'Resonancia').replace(/Intervencionisme/g, 'Intervencionismo').replace(/Telecomandament/g, 'Telemando').replace(/gestió/g, 'gestión')
    .replace(/\bDl\b/g, 'L').replace(/\bDt\b/g, 'M').replace(/\bDc\b/g, 'X').replace(/\bDj\b/g, 'J').replace(/\bDv\b/g, 'V').replace(/\bDs\b/g, 'S').replace(/\bDg\b/g, 'D');
  return text.replace(core, translated);
}
function translateDom(root) {
  if (state?.language !== 'es' || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => { node.nodeValue = localize(node.nodeValue); });
  root.querySelectorAll('[placeholder],[aria-label],[title]').forEach((element) => ['placeholder', 'aria-label', 'title'].forEach((attribute) => { if (element.hasAttribute(attribute)) element.setAttribute(attribute, localize(element.getAttribute(attribute))); }));
}
function rebuildEnhancedSelect(select) {
  const wrapper = select.closest('.enhanced-select'); if (!wrapper) return;
  const trigger = $('.enhanced-select-trigger', wrapper); const menu = select._enhancedMenu; const selected = select.selectedOptions[0];
  trigger.querySelector('span').textContent = selected?.textContent || '—';
  trigger.disabled = select.disabled; closeEnhancedSelect(wrapper); menu.innerHTML = '';
  [...select.children].forEach((child) => {
    if (child.tagName === 'OPTGROUP') {
      const heading = document.createElement('div'); heading.className = 'enhanced-select-group'; heading.textContent = child.label; menu.appendChild(heading);
      [...child.children].forEach((option) => menu.appendChild(enhancedSelectOption(option, select)));
    } else if (child.tagName === 'OPTION') menu.appendChild(enhancedSelectOption(child, select));
  });
}
function enhancedSelectOption(option, select) {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'enhanced-select-option'; button.dataset.enhancedSelectOption = option.value; button.textContent = option.textContent; button.disabled = option.disabled;
  button._enhancedSelect = select;
  button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(option.value === select.value));
  return button;
}
function closeEnhancedSelect(wrapper) {
  if (!wrapper) return;
  const select = $('.enhanced-select-native', wrapper); const menu = select?._enhancedMenu;
  wrapper.classList.remove('open'); $('.enhanced-select-trigger', wrapper)?.setAttribute('aria-expanded', 'false');
  if (menu) { menu.classList.remove('open'); menu.removeAttribute('style'); }
}
function closeEnhancedSelects(except = null) { $$('.enhanced-select.open').forEach((wrapper) => { if (wrapper !== except) closeEnhancedSelect(wrapper); }); }
function positionEnhancedSelect(wrapper) {
  const trigger = $('.enhanced-select-trigger', wrapper); const select = $('.enhanced-select-native', wrapper); const menu = select?._enhancedMenu;
  if (!trigger || !menu) return;
  const rect = trigger.getBoundingClientRect(); const margin = 8; const gap = 6;
  const width = Math.min(Math.max(rect.width, 280), window.innerWidth - margin * 2);
  const left = Math.min(Math.max(rect.left, margin), window.innerWidth - width - margin);
  menu.classList.add('open'); menu.style.visibility = 'hidden'; menu.style.width = `${width}px`; menu.style.maxHeight = '320px';
  const desiredHeight = Math.min(menu.scrollHeight, 320); const below = window.innerHeight - rect.bottom - margin; const above = rect.top - margin;
  const opensAbove = below < desiredHeight && above > below; const available = Math.max(opensAbove ? above - gap : below - gap, 96);
  menu.style.left = `${left}px`; menu.style.maxHeight = `${Math.min(desiredHeight, available)}px`;
  if (opensAbove) { menu.style.top = 'auto'; menu.style.bottom = `${window.innerHeight - rect.top + gap}px`; }
  else { menu.style.top = `${rect.bottom + gap}px`; menu.style.bottom = 'auto'; }
  menu.style.visibility = '';
}
function enhanceSelects(root = document) {
  $$('select:not(.enhanced-select-native)', root).forEach((select) => {
    const wrapper = document.createElement('div'); wrapper.className = 'enhanced-select';
    const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'enhanced-select-trigger'; trigger.dataset.enhancedSelectTrigger = ''; trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-label', select.getAttribute('aria-label') || select.closest('.field')?.querySelector('label')?.textContent?.trim() || 'Selecciona'); trigger.innerHTML = '<span></span><i></i>';
    const menu = document.createElement('div'); menu.className = 'enhanced-select-menu enhanced-select-portal'; menu.setAttribute('role', 'listbox'); menu.dataset.enhancedSelectPortal = '';
    select.parentNode.insertBefore(wrapper, select); wrapper.append(select, trigger); document.body.appendChild(menu); select._enhancedMenu = menu; menu._enhancedSelect = select; select.classList.add('enhanced-select-native'); select.setAttribute('aria-hidden', 'true'); select.tabIndex = -1;
    rebuildEnhancedSelect(select);
  });
}
function activeTeam() { return state.team.filter((member) => member.active !== false); }
function person(id) { return state.team.find((member) => member.id === id) || state.archivedTeam?.find((member) => member.id === id); }
function agendaOptionLabel(item) { return `${item.name} · ${shiftLabel(item.shift)} · ${loadLabel(item.loadPercentage)}`; }

function activityMetaTitle(item) {
  const load = loadLabel(item.loadPercentage);
  return item.id === MANAGEMENT_ACTIVITY.id ? load : `${shiftLabel(item.shift)} · ${load}`;
}
function typeOptions(selected = '', allowed = activeAgendas().map((item) => item.id)) {
  const enabled = new Set(allowed);
  return agendaGroups(activeAgendas().filter((item) => enabled.has(item.id)))
    .map((group) => `<optgroup label="${esc(group.hospital.name)}">${group.items.map((item) => `<option value="${esc(item.id)}" ${selected === item.id ? 'selected' : ''}>${esc(agendaOptionLabel(item))}</option>`).join('')}</optgroup>`)
    .join('');
}
function badges(types) { return types.filter((type) => activeAgendas().some((item) => item.id === type)).map((type) => `<span class="badge">${esc(agenda(type).name)}</span>`).join(''); }
function toast(message, kind = 'info') {
  const el = $('.toast') || document.body.appendChild(Object.assign(document.createElement('div'), { className: 'toast' }));
  el.textContent = localize(message);
  el.classList.toggle('error', kind === 'error');
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');
  el.classList.add('show');
  clearTimeout(el.hideTimer);
  el.hideTimer = setTimeout(() => el.classList.remove('show'), 4200);
}

function showError(error) {
  const fallback = state?.language === 'es' ? 'No se ha podido completar la operación' : 'No s’ha pogut completar l’operació';
  toast(error?.message || fallback, 'error');
}

async function reloadState(message = '') {
  try {
    state = normalizeBootstrapState(await api.bootstrap());
    if (message) toast(message);
    return true;
  } catch (error) {
    render(); setTimeout(() => showError(error), 0);
    return false;
  }
}

function loginView(error = '', mode = 'login', recoveryCode = '', username = '') {
  app.innerHTML = loginTemplate({ mode, error, recoveryCode, username }, esc);
  app.querySelectorAll('[data-auth-mode]').forEach((button) => button.addEventListener('click', () => loginView('', button.dataset.authMode)));
  app.querySelector('[data-auth-action="continue"]')?.addEventListener('click', () => load());
  app.querySelector('[data-auth-action="copy-recovery"]')?.addEventListener('click', async () => {
    await navigator.clipboard.writeText($('#recovery-code').textContent);
  });
  app.querySelector('[data-auth-action="download-recovery"]')?.addEventListener('click', (event) => {
    const content = `Pinendar · ${event.currentTarget.dataset.username}\nClau de recuperació: ${$('#recovery-code').textContent}\n`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type: 'text/plain' }));
    link.download = `pinendar-${event.currentTarget.dataset.username}-recuperacio.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
  });
  $('#login-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(event.target);
    const selectedMode = event.target.dataset.mode;
    const enteredUsername = data.get('username');
    const password = data.get('password');
    if (selectedMode !== 'login' && password !== data.get('confirmation')) {
      loginView('Les contrasenyes no coincideixen', selectedMode, '', enteredUsername);
      return;
    }
    try {
      if (selectedMode === 'signup') {
        const result = await api.signup(enteredUsername, password);
        loginView('', selectedMode, result.recoveryCode, result.username);
      } else if (selectedMode === 'recover') {
        const result = await api.recover(enteredUsername, data.get('recoveryCode'), password);
        loginView('', selectedMode, result.recoveryCode, result.username);
      } else {
        await api.login(enteredUsername, password);
        await load();
      }
    } catch (submitError) {
      loginView(submitError.message, selectedMode, '', enteredUsername);
    }
  });
}

function nav() {
  return navTemplate({ page, language: state.language, labelFor: t });
}
function header(title, subtitle, actions = '') {
  return headerTemplate({ title, subtitle, actions, language: state.language, account: state.account });
}

const NAV_PAGES = new Set(['calendar', 'guards', 'team', 'agendas', 'setup', 'history', 'guide']);
const CALENDAR_VIEWS = new Set(['day', 'week', 'month']);
const CALENDAR_ISSUE_FILTERS = new Set(['vacancy', 'unassigned', 'partial']);
function syncNavigationUrl(method = 'replace') {
  if (!window.history?.[`${method}State`]) return;
  const url = new URL(window.location.href);
  url.searchParams.set('page', page);
  url.searchParams.set('view', calendarView);
  url.searchParams.set('date', calendarDate);
  if (selectedMemberFilters.size) url.searchParams.set('members', [...selectedMemberFilters].join(','));
  else url.searchParams.delete('members');
  if (selectedAgendaFilters.size) url.searchParams.set('agendas', [...selectedAgendaFilters].join(','));
  else url.searchParams.delete('agendas');
  if (selectedCalendarIssueFilters.size) url.searchParams.set('issues', [...selectedCalendarIssueFilters].join(','));
  else url.searchParams.delete('issues');
  if (url.href === window.location.href) return;
  window.history[`${method}State`]({ pinendar: true, page, calendarView, calendarDate }, '', url);
}
function restoreNavigation() {
  const params = new URLSearchParams(window.location.search);
  if (NAV_PAGES.has(params.get('page'))) page = params.get('page');
  if (CALENDAR_VIEWS.has(params.get('view'))) calendarView = params.get('view');
  if (isValidDateKey(params.get('date'))) calendarDate = params.get('date');
  const memberIds = new Set(activeTeam().map((member) => member.id));
  const agendaIds = new Set(activeActivities().map((item) => item.id));
  selectedMemberFilters = new Set((params.get('members') || '').split(',').filter((id) => memberIds.has(id)));
  selectedAgendaFilters = new Set((params.get('agendas') || '').split(',').filter((id) => agendaIds.has(id)));
  selectedCalendarIssueFilters = new Set((params.get('issues') || '').split(',').filter((issue) => CALENDAR_ISSUE_FILTERS.has(issue)));
}

function calendarRange() {
  if (calendarView === 'day') return [calendarDate];
  if (calendarView === 'week') { const start = startOfWeek(calendarDate); return Array.from({ length: 7 }, (_, index) => addDays(start, index)); }
  const start = startOfWeek(`${monthKey(calendarDate)}-01`);
  const end = addDays(startOfWeek(endOfMonth(calendarDate)), 6);
  const dates = []; for (let key = start; key <= end; key = addDays(key, 1)) dates.push(key);
  return dates;
}


function calendarIncidents(key) {
  return calendarIncidentsForDate({
    assignments: calendarEvents(),
    agendas: planningActivities([...(state.agendas || []), ...(state.archivedAgendas || [])]),
    unfilled: calendarVacancies(),
    members: activeTeam(),
    date: key,
    memberWorksOnDate,
    isMemberAbsentOnDate,
  });
}

function calendarIssueRange() {
  const dates = calendarRange();
  return calendarView === 'month'
    ? dates.filter((key) => monthKey(key) === monthKey(calendarDate))
    : dates;
}

function calendarIssueSummary() {
  const summary = { vacancies: 0, unassigned: 0, people: new Set() };
  calendarIssueRange().forEach((key) => {
    const incidents = calendarIncidents(key);
    summary.vacancies += incidents.vacancies.length;
    summary.unassigned += incidents.unassignedMemberIds.size;
    incidents.unassignedMemberIds.forEach((memberId) => summary.people.add(memberId));
  });
  return { ...summary, people: summary.people.size };
}

function calendarKpis() {
  const summary = calendarIssueSummary();
  const vacancyLabel = summary.vacancies === 1
    ? (state.language === 'es' ? 'agenda sin cubrir' : 'agenda sense cobrir')
    : (state.language === 'es' ? 'agendas sin cubrir' : 'agendes sense cobrir');
  const unassignedLabel = summary.unassigned === 1
    ? (state.language === 'es' ? 'día-persona sin agenda' : 'dia-persona sense agenda')
    : (state.language === 'es' ? 'días-persona sin agenda' : 'dies-persona sense agenda');
  const peopleLabel = summary.people === 1 ? 'persona' : (state.language === 'es' ? 'personas' : 'persones');
  return `<section class="calendar-kpis" aria-label="${state.language === 'es' ? 'Incidencias del periodo visible' : 'Incidències del període visible'}">
    <button type="button" class="calendar-kpi vacancy ${selectedCalendarIssueFilters.has('vacancy') ? 'active' : ''}" data-calendar-issue-filter="vacancy" aria-pressed="${selectedCalendarIssueFilters.has('vacancy')}"><i aria-hidden="true">!</i><span><b>${summary.vacancies}</b><small>${vacancyLabel}</small></span></button>
    <button type="button" class="calendar-kpi unassigned ${selectedCalendarIssueFilters.has('unassigned') ? 'active' : ''}" data-calendar-issue-filter="unassigned" aria-pressed="${selectedCalendarIssueFilters.has('unassigned')}"><i aria-hidden="true">−</i><span><b>${summary.unassigned}</b><small>${unassignedLabel} · ${summary.people} ${peopleLabel}</small></span></button>
  </section>`;
}
function calendarTitle() {
  if (calendarView === 'day') return fmtDate(calendarDate, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  if (calendarView === 'week') { const days = calendarRange(); return `${fmtDate(days[0], { day: 'numeric', month: 'short' })} — ${fmtDate(days[6], { day: 'numeric', month: 'short', year: 'numeric' })}`; }
  return fmtDate(`${monthKey(calendarDate)}-01`, { month: 'long', year: 'numeric' });
}
function eventsForDate(key) {
  const matchesMember = (memberId) => !selectedMemberFilters.size || selectedMemberFilters.has(memberId);
  const matchesAgenda = (type) => !selectedAgendaFilters.size || selectedAgendaFilters.has(type);
  const assignments = calendarEvents().filter((item) => item.date === key && matchesMember(item.memberId) && matchesAgenda(item.type));
  const showUncategorised = !selectedAgendaFilters.size;
  const guards = calendarGuards().filter((item) => item.date === key && matchesMember(item.memberId));
  const savedAbsences = showUncategorised ? [...state.team, ...(state.archivedTeam || [])].flatMap((member) => member.vacations.filter((item) => key >= item.start && key <= item.end && matchesMember(member.id)).map((item) => ({ ...item, memberId: member.id }))) : [];
  const calendarDateAbsences = showUncategorised ? calendarAbsences().filter((item) => key >= item.start && key <= item.end && matchesMember(item.memberId)) : [];
  const absences = [...savedAbsences, ...calendarDateAbsences];
  const vacancies = vacanciesForDate({
    unfilled: calendarVacancies(),
    date: key,
    selectedAgendaIds: selectedAgendaFilters,
  });
  return { assignments, guards, absences, vacancies };
}
function isMemberAbsentOnDate(member, key) {
  const activeAbsences = calendarAbsences().filter((item) => item.memberId === member.id);
  const explicitlyAbsent = [...member.vacations, ...activeAbsences].some((item) => key >= item.start && key <= item.end);
  if (explicitlyAbsent) return true;
  return calendarGuards().some((item) => item.memberId === member.id && addDays(item.date, 1) === key);
}
function memberWorksOnDate(member, key) {
  const pattern = member.workPattern; const weeks = pattern?.weeks || [];
  if (!weeks.length) return member.availableDays.includes(weekday(key));
  const week = weeks[(isoWeekNumber(key) - 1) % weeks.length];
  const workingDays = Array.isArray(week) ? week : week.workingDays;
  return workingDays.includes(weekday(key));
}
function unassignedMembersForDate(key) {
  const assignments = calendarEvents();
  if (!hasCalendarContent() || selectedAgendaFilters.size) return [];
  const bounds = calendarBounds();
  if (key < bounds.start || key > bounds.end || [0, 6].includes(weekday(key)) || isHoliday(key)) return [];
  const eligibleIds = eligibleUnassignedMemberIds({
    members: state.team,
    assignments,
    date: key,
    selectedMemberIds: selectedMemberFilters,
    memberWorksOnDate,
    isMemberAbsentOnDate,
  });
  return activeTeam().filter((member) => eligibleIds.has(member.id));
}
function renderCalendarEventGroups(entries) {
  if (calendarView === 'month') return entries.map((entry) => entry.html).join('');
  const groups = new Map();
  entries.forEach((entry) => {
    const key = entry.hospitalKey || '__none';
    if (!groups.has(key)) groups.set(key, { key, name: entry.hospitalName, entries: [] });
    groups.get(key).entries.push(entry);
  });
  return [...groups.values()]
    .sort((left, right) => {
      if (left.key === '__none') return 1;
      if (right.key === '__none') return -1;
      return left.name.localeCompare(right.name, state.language === 'es' ? 'es' : 'ca');
    })
    .map((group) => {
      const hospital = (state.hospitals || []).find((item) => String(item.id) === group.key);
      const heading = calendarView === 'week' && hospital ? compactHospitalName(hospital) : group.name;
      return `<section class="calendar-hospital-block"><h3 title="${esc(group.name)}">${esc(heading)}</h3><div class="calendar-hospital-events">${group.entries.map((entry) => entry.html).join('')}</div></section>`;
    })
    .join('');
}

function calendarCell(key) {
  const events = eventsForDate(key);
  const incidents = calendarIncidents(key);
  const weekend = [0, 6].includes(weekday(key));
  const holiday = isHoliday(key);
  const activeEvents = calendarEvents();
  const activeAgendas = planningActivities([...(state.agendas || []), ...(state.archivedAgendas || [])]);
  const rawDateAssignments = activeEvents.filter((item) => item.date === key);
  const noHospitalName = state.language === 'es' ? 'Sin hospital' : 'Sense hospital';
  const eventEntry = (html, hospital) => ({
    html,
    hospitalKey: hospital?.id != null ? String(hospital.id) : '__none',
    hospitalName: hospital?.name || noHospitalName,
  });
  const assignmentEvent = (item) => {
    const member = person(item.memberId);
    const storedMeta = agenda(item.type);
    const meta = {
      ...storedMeta,
      loadPercentage: item.loadPercentage ?? storedMeta.loadPercentage,
    };
    const hospital = agendaHospital(meta);
    const unassigned = item.type === 'no_assignment';
    const dailyLoad = unassigned ? 0 : dailyAssignmentLoad({
      assignments: activeEvents,
      agendas: activeAgendas,
      memberId: item.memberId,
      date: key,
    });
    const partial = !unassigned && item.type !== 'management' && dailyLoad === 50;
    const activityName = unassigned ? 'Sense assignació' : meta.name;
    const hospitalName = hospital?.name || noHospitalName;
    const partialLabel = partial ? (state.language === 'es' ? 'Agenda parcial' : 'Agenda parcial') : '';
    const activityDetails = unassigned ? '' : `${hospitalName} · ${activityMetaTitle(meta)}${partialLabel ? ` · ${partialLabel}` : ''}`;
    const partialBadge = partial ? `<i class="calendar-partial-badge">${state.language === 'es' ? 'Parcial' : 'Parcial'}</i>` : '';
    const compactMeta = unassigned ? '' : `<i class="calendar-event-compact-meta">${compactActivityMeta(meta)}</i>`;
    const html = `<button class="calendar-event assignment ${unassigned ? 'unassigned' : ''} ${partial ? 'partial-day' : ''}" style="--agenda-color:${meta.color};--member-color:${member?.color || '#b9c4c0'}" data-edit-assignment="${item.id}" title="${esc(member?.name || '—')} · ${esc(activityName)}${activityDetails ? ` · ${esc(activityDetails)}` : ''}"><b>${esc(member?.name || '—')}</b><span class="calendar-event-activity"><em>${esc(activityName)}</em>${partialBadge}${compactMeta}</span></button>`;
    return eventEntry(html, hospital);
  };
  const vacancyItems = selectedCalendarIssueFilters.has('vacancy')
    ? incidents.vacancies
    : events.vacancies;
  const vacancyCounts = new Map();
  vacancyItems.forEach((item) => vacancyCounts.set(item.type, (vacancyCounts.get(item.type) || 0) + 1));
  const vacancyEvents = [...vacancyCounts.entries()].map(([type, count]) => {
    const meta = agenda(type);
    const hospital = agendaHospital(meta);
    const vacancyLabel = state.language === 'es' ? 'Vacante' : 'Vacant';
    const hospitalName = hospital?.name || noHospitalName;
    const details = `${hospitalName} · ${activityMetaTitle(meta)}`;
    const countLabel = count > 1 ? ` ×${count}` : '';
    const html = `<div class="calendar-event vacancy" style="--agenda-color:${meta.color};--member-color:#ff5f69" title="${esc(vacancyLabel)} · ${esc(meta.name)}${countLabel} · ${esc(details)}"><b>${vacancyLabel}${countLabel}</b><span class="calendar-event-activity"><em>${esc(meta.name)}</em><i class="calendar-event-compact-meta">${compactActivityMeta(meta)}</i></span></div>`;
    return eventEntry(html, hospital);
  });
  const unassignedMembers = selectedCalendarIssueFilters.has('unassigned')
    ? activeTeam().filter((member) => incidents.unassignedMemberIds.has(member.id))
    : unassignedMembersForDate(key);
  const eligibleUnassignedIds = new Set(unassignedMembers.map((member) => member.id));
  const unassignedAssignmentSource = selectedCalendarIssueFilters.has('unassigned')
    ? rawDateAssignments
    : events.assignments;
  const persistedUnassignedItems = unassignedAssignmentSource.filter(
    (item) => item.type === 'no_assignment' && eligibleUnassignedIds.has(item.memberId),
  );
  const persistedUnassignedIds = new Set(persistedUnassignedItems.map((item) => item.memberId));
  const persistedUnassignedEvents = persistedUnassignedItems.map(assignmentEvent);
  const inferredUnassignedEvents = unassignedMembers
    .filter((member) => !persistedUnassignedIds.has(member.id))
    .map((member) => eventEntry(`<button class="calendar-event unassigned" style="--member-color:${member.color}" data-open-extra-member="${member.id}" data-extra-date="${key}" title="${esc(member.name)} · Sense assignació"><b>${esc(member.name)}</b><span>Sense assignació</span></button>`, null));
  const filteredClinicalItems = events.assignments.filter((item) => item.type !== 'no_assignment');
  const rawPartialItems = rawDateAssignments.filter(
    (item) => item.type !== 'no_assignment' && incidents.partialMemberIds.has(item.memberId),
  );
  const partialItems = selectedCalendarIssueFilters.has('partial')
    ? rawPartialItems
    : filteredClinicalItems.filter((item) => incidents.partialMemberIds.has(item.memberId));
  const partialIds = new Set(partialItems.map((item) => item.id));
  const partialEvents = partialItems.map(assignmentEvent);
  const assignmentEvents = filteredClinicalItems
    .filter((item) => !partialIds.has(item.id))
    .map(assignmentEvent);
  const guardNames = events.guards.map((item) => person(item.memberId)?.name || '—');
  const guardLabel = guardNames.length ? `Guàrdia: ${guardNames.join(', ')}` : '';
  const guardColor = person(events.guards[0]?.memberId)?.color || '#f1c75b';
  const calendarGuard = events.guards[0];
  const storedGuard = activeGuards().find((item) => item.id === calendarGuard?.id)
    || activeGuards().find((item) => item.date === key && item.memberId === calendarGuard?.memberId);
  const guardAction = storedGuard ? `data-action="open-calendar-guard" data-guard-id="${storedGuard.id}"` : `data-calendar-open="${key}"`;
  const guardSummary = calendarView === 'month' && guardNames.length
    ? `<button type="button" class="calendar-guard-hover" style="--member-color:${guardColor}" ${guardAction} aria-label="${esc(guardLabel)} · Gestiona la guàrdia"><span aria-hidden="true">G</span><span class="calendar-guard-tooltip" role="tooltip">${esc(guardLabel)}</span></button>`
    : '';
  const guardBanner = calendarView !== 'month' && guardNames.length
    ? `<button type="button" class="calendar-guard-banner" style="--member-color:${guardColor}" ${guardAction}><span>Guàrdia</span><b>${esc(guardNames.join(', '))}</b></button>`
    : '';
  const absenceEvents = events.absences.map((item) => {
    const member = person(item.memberId);
    return eventEntry(`<div class="calendar-event absence" style="--member-color:${member?.color || '#f077b5'}"><b>Vacances</b><span>${esc(member?.name || '—')}</span></div>`, null);
  });
  const badge = (kind, count, shortLabel, longLabel) => count
    ? `<button type="button" class="calendar-incident-badge ${kind} ${selectedCalendarIssueFilters.has(kind) ? 'active' : ''}" data-calendar-issue-filter="${kind}" title="${count} ${longLabel}" aria-label="${count} ${longLabel}" aria-pressed="${selectedCalendarIssueFilters.has(kind)}"><span>${shortLabel}</span><b>${count}</b></button>`
    : '';
  const vacancyNoun = incidents.vacancies.length === 1
    ? (state.language === 'es' ? 'agenda sin cubrir' : 'agenda sense cobrir')
    : (state.language === 'es' ? 'agendas sin cubrir' : 'agendes sense cobrir');
  const unassignedNoun = incidents.unassignedMemberIds.size === 1
    ? (state.language === 'es' ? 'persona sin agenda' : 'persona sense agenda')
    : (state.language === 'es' ? 'personas sin agenda' : 'persones sense agenda');
  const partialNoun = incidents.partialMemberIds.size === 1
    ? (state.language === 'es' ? 'persona con agenda parcial' : 'persona amb agenda parcial')
    : (state.language === 'es' ? 'personas con agenda parcial' : 'persones amb agenda parcial');
  const incidentBadges = [
    badge('vacancy', incidents.vacancies.length, 'A!', vacancyNoun),
    badge('unassigned', incidents.unassignedMemberIds.size, 'P−', unassignedNoun),
    badge('partial', incidents.partialMemberIds.size, '~', partialNoun),
  ].join('');
  const unassignedEvents = [...inferredUnassignedEvents, ...persistedUnassignedEvents];
  const issueEvents = [...vacancyEvents, ...unassignedEvents, ...partialEvents];
  const allEvents = selectedCalendarIssueFilters.size
    ? [
      ...(selectedCalendarIssueFilters.has('vacancy') ? vacancyEvents : []),
      ...(selectedCalendarIssueFilters.has('unassigned') ? unassignedEvents : []),
      ...(selectedCalendarIssueFilters.has('partial') ? partialEvents : []),
    ]
    : [...issueEvents, ...absenceEvents, ...assignmentEvents];
  const baseLimit = calendarView === 'month' ? 5 : allEvents.length;
  const limit = calendarView === 'month' && !selectedCalendarIssueFilters.size
    ? Math.max(baseLimit, issueEvents.length)
    : baseLimit;
  const hidden = Math.max(allEvents.length - limit, 0);
  const visibleEvents = allEvents.slice(0, limit);
  const dayClasses = [
    'calendar-day',
    incidents.vacancies.length ? 'has-vacancies' : '',
    incidents.unassignedMemberIds.size ? 'has-unassigned' : '',
    incidents.partialMemberIds.size ? 'has-partials' : '',
    weekend ? 'weekend' : '',
    holiday ? 'holiday' : '',
    monthKey(key) !== monthKey(calendarDate) && calendarView === 'month' ? 'outside' : '',
    key === dateKey(new Date()) ? 'today' : '',
  ].filter(Boolean).join(' ');
  return `<div class="${dayClasses}" data-calendar-date="${key}"><div class="calendar-day-header ${guardNames.length ? 'has-guard' : ''}">${guardSummary}<div class="calendar-incident-badges">${incidentBadges}</div><button class="calendar-day-number" data-calendar-open="${key}" aria-label="Obre ${fmtDate(key, { day: 'numeric', month: 'long', year: 'numeric' })}"><span>${fmtDate(key, { weekday: calendarView === 'day' ? 'long' : 'short' })}</span><b>${fromKey(key).getUTCDate()}</b></button></div>${holiday ? '<div class="calendar-holiday">Festiu</div>' : ''}${guardBanner}<div class="calendar-events">${renderCalendarEventGroups(visibleEvents)}${hidden ? `<button class="calendar-more" data-calendar-open="${key}">+${hidden} més</button>` : ''}</div></div>`;
}
function alphabetically(items) {
  return sortByName(items, state.language === 'es' ? 'es' : 'ca');
}

function calendarMemberFilterGroups() {
  return [{ label: '', items: alphabetically(activeTeam()) }];
}

function calendarAgendaFilterGroups() {
  return planningActivityGroups({
    agendas: activeAgendas(),
    hospitals: state.hospitals,
    locale: state.language === 'es' ? 'es' : 'ca',
  });
}

function calendarPage() {
  const assignments = calendarEvents();
  const unfilled = calendarVacancies().length;
  const hasContent = hasCalendarContent();
  return `${header('Calendari', hasContent ? `${projectionPeriodLabel(calendarProjection())} · esdeveniments vigents` : 'Sense esdeveniments generats')}
    <div class="calendar-actions"><section class="calendar-generate card"><div><b>${hasContent ? 'Genera un altre període' : 'Prepara el calendari'}</b><span class="calendar-status">${assignments.length ? `${assignments.length} assignacions · ${unfilled} vacants` : 'Tria període i condicionants'}</span></div><div class="export-row"><button class="button" data-action="open-generation">Genera calendari</button></div></section><section class="calendar-export card"><div><b>Exporta</b><span>Respecta els filtres actius</span></div><div class="export-row"><button class="button ghost small" data-action="export-csv" ${hasContent ? '' : 'disabled'}>CSV</button><button class="button ghost small" data-action="export-excel" ${hasContent ? '' : 'disabled'}>Excel</button><button class="button ghost small" data-action="export-ics" ${hasContent ? '' : 'disabled'}>ICS</button></div></section></div>
    ${hasContent ? calendarKpis() : ''}
    <section class="calendar-toolbar card"><div class="calendar-nav"><button class="button ghost small" data-action="calendar-today">Avui</button><button class="icon-button" data-action="calendar-prev" aria-label="Anterior">‹</button><button class="icon-button" data-action="calendar-next" aria-label="Següent">›</button><h2>${calendarTitle()}</h2></div><div class="calendar-controls"><div class="calendar-filters">${calendarMultiFilter('member', 'Persones', selectedMemberFilters, calendarMemberFilterGroups(), 'Tothom')}${calendarMultiFilter('agenda', 'Agendes', selectedAgendaFilters, calendarAgendaFilterGroups(), 'Totes')}</div><div class="view-switch">${[['day', 'Dia'], ['week', 'Setmana'], ['month', 'Mes']].map(([id, label]) => `<button data-calendar-view="${id}" class="${calendarView === id ? 'active' : ''}">${label}</button>`).join('')}</div></div></section>
    <section class="calendar-shell card view-${calendarView}">${calendarView !== 'day' ? `<div class="calendar-weekdays">${WEEK_SHORT.map((day) => `<div>${day}</div>`).join('')}</div>` : ''}<div class="calendar-grid">${calendarRange().map(calendarCell).join('')}</div></section><div class="calendar-destructive-actions"><button class="button danger small" data-action="open-clear-calendar">Esborra període</button></div>`;
}

function calendarMultiFilter(kind, label, selected, groups, allLabel) {
  const summary = selected.size === 1 ? '1 seleccionada' : selected.size ? `${selected.size} seleccionades` : allLabel;
  const option = (item) => { const meta = kind === 'agenda' ? `<small class="calendar-filter-meta" title="${esc(activityMetaTitle(item))}">${compactActivityMeta(item)}</small>` : ''; return `<label><input type="checkbox" data-calendar-filter-option="${kind}" value="${esc(item.id)}" ${selected.has(item.id) ? 'checked' : ''} /><i style="--filter-color:${item.color}"></i><span>${esc(item.name)}</span>${meta}</label>`; };
  const groupedOptions = groups.map((group) => `<div class="calendar-filter-group">${group.label ? `<div class="calendar-filter-group-title">${esc(group.label)}</div>` : ''}${group.items.map(option).join('')}</div>`).join('');
  return `<details class="calendar-filter" data-filter-kind="${kind}" ${openCalendarFilter === kind ? 'open' : ''}><summary><span>${label}</span><b>${summary}</b></summary><div class="calendar-filter-menu"><label class="calendar-filter-all"><input type="checkbox" data-calendar-filter-all="${kind}" ${selected.size ? '' : 'checked'} />${allLabel}</label>${groupedOptions}</div></details>`;
}

function memberOptions(selected = '', includeAll = false) { return `${includeAll ? '<option value="">Tothom</option>' : ''}${activeTeam().map((member) => `<option value="${member.id}" ${member.id === selected ? 'selected' : ''}>${esc(member.name)}</option>`).join('')}`; }
function dayChecks(name, selected) { return DAYS.map((day, index) => `<label class="check"><input type="checkbox" name="${name}" value="${index + 1}" ${selected.includes(index + 1) ? 'checked' : ''}>${DAYS_SHORT[index]}</label>`).join(''); }
function memberWorkPattern(member) { const rawWeeks = member?.workPattern?.weeks?.length ? member.workPattern.weeks : [member?.availableDays || [1, 2, 3, 4, 5]]; const legacyTele = new Set(member?.teleDays || []); return { weeks: rawWeeks.map((week) => Array.isArray(week) ? { workingDays: [...week], teleDays: week.filter((day) => legacyTele.has(day)) } : { workingDays: [...(week.workingDays || [])], teleDays: [...(week.teleDays || [])] }) }; }
function patternDayChecks(kind, index, selected, workingDays) { return DAYS.map((day, dayIndex) => { const value = dayIndex + 1; const disabled = kind === 'tele' && !workingDays.includes(value); return `<label class="work-pattern-day ${kind}"><input type="checkbox" name="work-${kind}-${index}" value="${value}" data-pattern-${kind} ${selected.includes(value) ? 'checked' : ''} ${disabled ? 'disabled' : ''}><span>${DAYS_SHORT[dayIndex]}</span></label>`; }).join(''); }
function workPatternWeekRow(week, index, multiple) { return `<section class="work-pattern-week" data-work-pattern-week="${index}"><div class="work-pattern-week-head"><b>Setmana ${index + 1}</b><button type="button" class="work-pattern-remove ${multiple ? '' : 'is-hidden'}" data-action="remove-work-pattern-week" aria-label="Elimina setmana"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 4.5h9M6 4.5V3h4v1.5m-5 0 .6 8.5h4.8l.6-8.5M7 6.5v4m2-4v4"/></svg><span>Elimina</span></button></div><div class="work-pattern-line"><span>Treball</span><div>${patternDayChecks('working', index, week.workingDays, week.workingDays)}</div></div><div class="work-pattern-line tele"><span>Telemàtic</span><div>${patternDayChecks('tele', index, week.teleDays, week.workingDays)}</div></div></section>`; }
function workPatternFields(member) { const pattern = memberWorkPattern(member); const multiple = pattern.weeks.length > 1; return `<section class="work-pattern-editor"><div class="work-pattern-title"><div><span class="label">Patró de treball</span><small>Quins dies s’ha de planificar aquesta persona?</small></div><div class="work-pattern-mode"><label><input type="radio" name="work-pattern-mode" value="same" ${multiple ? '' : 'checked'}><span>Sempre igual</span></label><label><input type="radio" name="work-pattern-mode" value="alternating" ${multiple ? 'checked' : ''}><span>Alterna setmanes</span></label></div></div><div class="work-pattern-weeks ${multiple ? '' : 'single'}" data-work-pattern-weeks>${pattern.weeks.map((week, index) => workPatternWeekRow(week, index, multiple)).join('')}</div><button type="button" class="button secondary small work-pattern-add ${multiple ? '' : 'is-hidden'}" data-action="add-work-pattern-week" ${pattern.weeks.length >= 5 ? 'disabled' : ''}>+ Afegeix setmana</button><small class="work-pattern-help ${multiple ? '' : 'is-hidden'}" data-work-pattern-help>Les setmanes segueixen el número ISO i tornen a començar després de l’última.</small></section>`; }
function activeWorkPatternRows(formElement) { const rows = $$('[data-work-pattern-week]', formElement); return $('[name="work-pattern-mode"]:checked', formElement)?.value === 'alternating' ? rows : rows.slice(0, 1); }
function workPatternAvailableDays(formElement) { return [...new Set(activeWorkPatternRows(formElement).flatMap((row) => $$('[data-pattern-working]:checked', row).map((item) => Number(item.value))))].sort((a, b) => a - b); }
function collectWorkPattern(formElement) { return { weeks: activeWorkPatternRows(formElement).map((row) => ({ workingDays: $$('[data-pattern-working]:checked', row).map((item) => Number(item.value)), teleDays: $$('[data-pattern-tele]:checked', row).map((item) => Number(item.value)) })) }; }
function renumberWorkPatternWeeks(formElement) { const rows = $$('[data-work-pattern-week]', formElement); rows.forEach((row, index) => { row.dataset.workPatternWeek = index; $('.work-pattern-week-head b', row).textContent = `Setmana ${index + 1}`; $$('[data-pattern-working]', row).forEach((input) => { input.name = `work-working-${index}`; }); $$('[data-pattern-tele]', row).forEach((input) => { input.name = `work-tele-${index}`; }); $('[data-action="remove-work-pattern-week"]', row).classList.toggle('is-hidden', rows.length === 1); }); const add = $('[data-action="add-work-pattern-week"]', formElement); if (add) add.disabled = rows.length >= 5; }
function refreshPatternDependentFields(formElement) { activeWorkPatternRows(formElement).forEach((row) => { const working = new Set($$('[data-pattern-working]:checked', row).map((item) => Number(item.value))); $$('[data-pattern-tele]', row).forEach((input) => { input.disabled = !working.has(Number(input.value)); if (input.disabled) input.checked = false; }); }); const available = workPatternAvailableDays(formElement); $$('.fixed-rule-row', formElement).forEach((row) => { const select = $('[name="rule-weekday"]', row); const previous = Number(select.value); select.innerHTML = available.map((day) => `<option value="${day}" ${day === previous ? 'selected' : ''}>${DAYS[day - 1]}</option>`).join(''); select.disabled = !available.length; rebuildEnhancedSelect(select); refreshFixedRuleType(row, formElement); }); }
function syncWorkPatternMode(formElement) { const alternating = $('[name="work-pattern-mode"]:checked', formElement)?.value === 'alternating'; const container = $('[data-work-pattern-weeks]', formElement); if (alternating && $$('[data-work-pattern-week]', container).length === 1) { const week = collectWorkPattern(formElement).weeks[0]; container.insertAdjacentHTML('beforeend', workPatternWeekRow(week, 1, true)); } container.classList.toggle('single', !alternating); $('[data-action="add-work-pattern-week"]', formElement).classList.toggle('is-hidden', !alternating); $('[data-work-pattern-help]', formElement).classList.toggle('is-hidden', !alternating); renumberWorkPatternWeeks(formElement); refreshPatternDependentFields(formElement); }
function memberVacationCalendar() {
  const month = modal.vacationMonth || monthKey(dateKey(new Date()));
  const selected = new Set(modal.vacationDates || []); const today = dateKey(new Date());
  const first = `${month}-01`; const start = startOfWeek(first); const days = Array.from({ length: 42 }, (_, index) => addDays(start, index));
  const title = fmtDate(first, { month: 'long', year: 'numeric' });
  return `<section class="vacation-calendar"><div class="vacation-calendar-head"><button type="button" class="icon-button" data-action="vacation-prev" aria-label="Mes anterior">‹</button><h3>${title}</h3><button type="button" class="icon-button" data-action="vacation-next" aria-label="Mes següent">›</button></div><div class="vacation-weekdays">${WEEK_SHORT.map((day) => `<span>${day}</span>`).join('')}</div><div class="vacation-days">${days.map((key) => { const past = key < today; const chosen = selected.has(key); return `<button type="button" data-action="toggle-vacation" data-vacation-date="${key}" class="${monthKey(key) === month ? '' : 'outside'} ${chosen ? 'selected' : ''} ${past ? 'past' : ''}" ${past ? 'disabled' : ''} aria-pressed="${chosen}">${fromKey(key).getUTCDate()}</button>`; }).join('')}</div><p>${selected.size} dies de vacances seleccionats. Els dies passats es conserven i no es poden editar.</p></section>`;
}
function agendaReaction(item, value = 0) {
  const reaction = Number(value); const symbol = reaction === 1 ? '♥' : reaction === -1 ? '👎' : '+'; const label = reaction === 1 ? 'Agrada' : reaction === -1 ? 'Desagrada' : 'Afegeix reacció';
  return `<div class="agenda-reaction ${reaction === 1 ? 'liked' : reaction === -1 ? 'disliked' : ''}" data-agenda-reaction data-agenda-name="${esc(item.name)}"><input type="hidden" data-agenda-preference value="${reaction}"><button type="button" class="agenda-reaction-trigger" data-action="toggle-agenda-reaction" aria-label="${label}: ${esc(item.name)}" aria-expanded="false"><span>${symbol}</span></button><div class="agenda-reaction-menu" role="menu" aria-label="Preferència per ${esc(item.name)}"><button type="button" data-action="set-agenda-preference" data-preference="1" title="Agrada" aria-label="Agrada">♥</button><button type="button" data-action="set-agenda-preference" data-preference="-1" title="Desagrada" aria-label="Desagrada">👎</button><button type="button" data-action="set-agenda-preference" data-preference="0" title="Indiferent" aria-label="Treu la reacció">×</button></div></div>`;
}
function typeChecks(name, selected, preferences = {}) {
  return `<div class="agenda-capability-groups">${agendaGroups().map((group) => `<section class="agenda-capability-group"><div class="agenda-capability-head"><b>${esc(group.hospital.name)}</b><span>${group.items.length} agendes</span></div><div class="check-grid">${group.items.map((item) => `<div class="check agenda-capability"><label class="agenda-capability-main"><input type="checkbox" name="${name}" value="${item.id}" ${selected.includes(item.id) ? 'checked' : ''}><span>${esc(item.name)}</span><small>${esc(shiftLabel(item.shift))} · ${loadLabel(item.loadPercentage)}</small></label>${agendaReaction(item, preferences[item.id])}</div>`).join('')}</div></section>`).join('')}</div>`;
}
function memberCard(member) {
  const weeks = member.workPattern?.weeks?.length ? member.workPattern.weeks : [member.availableDays];
  const availability = Math.round(weeks.reduce((total, week) => total + new Set(Array.isArray(week) ? week : week.workingDays).size, 0) / (weeks.length * DAYS.length) * 100);
  return `<article class="member-card ${member.active ? '' : 'inactive'}" style="--member-color:${member.color}"><div class="member-avatar">${esc(member.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join(''))}</div><div class="member-main"><div class="member-identity"><span class="member-name">${esc(member.name)}</span><span class="member-email">${esc(member.email)}</span>${member.active ? '' : '<span class="member-status">Inactiu</span>'}</div><div class="member-detail">${availability}% disponible</div><div class="rules">${member.managementQuota ? `<span class="rule">gestió ${member.managementQuota}/mes</span>` : ''}${member.fixedRules.map((rule) => `<span class="rule">${DAYS_SHORT[rule.weekday - 1]} · ${esc(agenda(rule.type).name)}</span>`).join('')}</div></div><div class="row-actions"><button class="button ghost small" data-edit-member="${member.id}">Edita</button><button class="button danger small" data-delete-member="${member.id}">Elimina</button></div></article>`;
}
function teamPage() {
  return `${header('Equip', `${activeTeam().length} membres actius`, `<button class="button" data-action="open-member">Afegeix membre</button>`)}
    <section class="section flush"><div class="section-head"><div><h2>Persones</h2><div class="muted">Gestiona perfils, disponibilitat i regles fixes.</div></div></div><div class="team-list">${state.team.map(memberCard).join('') || '<div class="card empty-state">No hi ha membres a l’equip.</div>'}</div></section>`;
}

function agendasPage() {
  const groups = agendaGroups(state.agendas);
  return `${header('Agendes', `${state.agendas.length} tipus d’agenda`, '<button class="button" data-action="open-agenda">Afegeix agenda</button>')}
    <section class="section flush"><div class="section-head"><div><h2>Catàleg d’agendes</h2><div class="muted">Cada perfil defineix hospital, torn, modalitat, cobertura setmanal i color automàtic.</div></div></div><div class="agenda-hospital-groups">${groups.map((group) => `<section class="agenda-hospital-group"><div class="agenda-group-head"><div><span class="agenda-group-mark"></span><h3>${esc(group.hospital.name)}</h3></div><span>${group.items.length} agendes</span></div><div class="agenda-list">${group.items.map(agendaCard).join('')}</div></section>`).join('') || '<div class="card empty-state">No hi ha agendes creades.</div>'}</div></section>`;
}

function agendaCard(item) {
  const enabled = state.team.filter((member) => member.allowedTypes.includes(item.id)).length; const coverage = Object.values(state.coverage).reduce((total, day) => total + Number(day[item.id] || 0), 0); const recurring = (item.recurrences || []).map((rule) => `${ordinalLabel(rule.ordinal)} ${DAYS_SHORT[rule.weekday - 1]} de cada mes`).join(' · ');
  return `<article class="agenda-card card"><span class="agenda-color" style="--agenda-color:${item.color}"></span><div><div class="agenda-title-row"><h3>${esc(item.name)}</h3><span class="agenda-shift">${shiftLabel(item.shift)}</span><span class="agenda-load">${loadLabel(item.loadPercentage)}</span>${item.telematic ? '<span class="agenda-telematic"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 6.5a7.1 7.1 0 0 1 10 0M5.2 8.8a4 4 0 0 1 5.6 0M7.2 11a1.1 1.1 0 1 1 1.6 1.6A1.1 1.1 0 0 1 7.2 11Z"/></svg>Telemàtica</span>' : ''}</div><div class="muted">${item.telematic ? 'Telemàtica' : 'Presencial'} · ${state.language === 'es' ? 'prioridad' : 'prioritat'} ${priorityLabel(item.priority)} · ${enabled} membres habilitats · ${coverage} places/setmana</div><div class="coverage-preview">${[1, 2, 3, 4, 5].map((day) => `<span>${DAYS_SHORT[day - 1]} <b>${state.coverage[day]?.[item.id] || 0}</b></span>`).join('')}</div>${recurring ? `<div class="agenda-recurrence-summary">${esc(recurring)}</div>` : ''}</div><div class="row-actions"><button class="button ghost small" data-edit-agenda="${item.id}">Edita</button><button class="button danger small" data-delete-agenda="${item.id}">Elimina</button></div></article>`;
}

function hospitalSearchResultsView() {
  const results = hospitalSearchResults.map((item, index) => `<button data-hospital-result="${index}" class="hospital-result ${pendingHospitalLocation?.id === item.id ? 'selected' : ''}"><b>${esc(item.name)}</b><span>${esc(item.municipality)} · ${esc(item.province)}</span><small>${esc(item.streetAddress)}${item.areaAvailable ? '' : ' · Àrea no disponible'}</small></button>`).join('');
  const status = hospitalSearchBusy ? 'Cercant al catàleg local…' : hospitalSearchStatus || 'Hospitals públics i de xarxa pública precarregats.';
  const manual = !hospitalSearchBusy && hospitalSearchQuery.trim().length >= 2 ? `<button type="button" class="hospital-manual-result" data-action="add-manual-hospital"><b>No hi és? Afegeix “${esc(hospitalSearchQuery.trim())}”</b><span>Centre amb localització desconeguda</span></button>` : '';
  return `${results}${manual}<div class="search-status">${esc(status)}</div>`;
}

function hospitalSelectionView() {
  if (!pendingHospitalLocation) return 'Selecciona un hospital dels resultats';
  return `<b>${esc(pendingHospitalLocation.name)}</b><span>${esc(pendingHospitalLocation.address)}</span><small>${pendingHospitalLocation.areaAvailable ? hospitalAreaLabel(pendingHospitalLocation) : 'No es pot afegir perquè no té una àrea disponible'}</small>`;
}

function setupPage() {
  return `${header('Configuració', 'Hospitals coberts i festius')}
    <section class="hospital-layout"><div class="card hospital-panel"><div><div class="card-kicker">COBERTURA TERRITORIAL</div><h2>Cerca hospitals</h2><p class="muted">Catàleg oficial local d’institucions públiques i mixtes. Cerca per hospital, municipi o província.</p></div><div class="hospital-search-form"><div class="field"><label>Hospital o municipi</label><div class="hospital-search-row"><input data-hospital-search value="${esc(hospitalSearchQuery)}" placeholder="Ex. Bellvitge o Barcelona" autocomplete="off" aria-label="Cerca hospital" /></div></div></div><div class="hospital-search-results">${hospitalSearchResultsView()}</div><form id="hospital-form"><input type="hidden" name="catalogId" value="${esc(pendingHospitalLocation?.id || '')}" /><input type="hidden" name="name" value="${esc(pendingHospitalLocation?.name || '')}" /><input type="hidden" name="address" value="${esc(pendingHospitalLocation?.address || '')}" /><input type="hidden" name="latitude" value="${pendingHospitalLocation?.latitude ?? ''}" /><input type="hidden" name="longitude" value="${pendingHospitalLocation?.longitude ?? ''}" /><input type="hidden" name="areaM2" value="${pendingHospitalLocation?.areaM2 ?? ''}" /><input type="hidden" name="cadastralReference" value="${esc(pendingHospitalLocation?.cadastralReference || '')}" /><div class="map-selection ${pendingHospitalLocation ? 'selected' : ''}" data-map-selection>${hospitalSelectionView()}</div><button class="button" data-hospital-submit ${pendingHospitalLocation?.areaAvailable ? '' : 'disabled'}>Afegeix hospital</button></form></div><div class="card hospital-map-card"><div id="hospital-map" aria-label="Mapa d’hospitals coberts"></div><div class="map-help">OpenFreeMap · Ministerio de Sanidad · IGN-CNIG · Catastro</div></div><div class="card selected-hospitals"><div><div class="card-kicker">HOSPITALS AFEGITS</div><h2>Hospitals coberts</h2><p class="muted">Els centres localitzats es poden clicar per centrar-ne l’àrea.</p></div><div class="hospital-list">${state.hospitals.map((item) => `<div class="hospital-item">${item.locationKnown ? `<button type="button" class="hospital-item-focus" data-focus-hospital="${esc(item.catalogId)}" aria-label="Mostra ${esc(item.name)} al mapa"><i></i><span><b>${esc(item.name)}</b><small>${esc(item.address || 'Adreça no disponible')}</small></span></button>` : `<div class="hospital-item-focus hospital-item-static"><i></i><span><b>${esc(item.name)}</b><small>Localització desconeguda</small></span></div>`}<button class="icon-button danger-icon" data-remove-hospital="${item.id}" aria-label="Elimina ${esc(item.name)}">×</button></div>`).join('') || '<div class="muted">Encara no hi ha hospitals afegits.</div>'}</div></div></section>
    <section class="section"><div class="card panel holidays-panel"><div><div class="card-kicker">CALENDARI</div><h2>Festius</h2><p class="muted">Es mostraran directament al calendari principal.</p></div><form id="holiday-form"><div class="field"><label>Data festiva</label><input type="date" name="date" required /></div><button class="button secondary">Afegeix festiu</button></form><div class="holiday-list">${state.holidays.sort().map((date) => `<div class="holiday-chip"><span>Festiu · ${fmtDate(date, { day: 'numeric', month: 'long', year: 'numeric' })}</span><button class="icon-button danger-icon" data-remove-time="h:${date}" aria-label="Elimina festiu">×</button></div>`).join('') || '<div class="muted">Sense festius afegits.</div>'}</div></div></section>`;
}

function hospitalAreaLabel(item) {
  if (!item?.areaM2) return 'Àrea cadastral no disponible';
  return `Parcel·la cadastral · ${new Intl.NumberFormat('ca-ES').format(item.areaM2)} m²${item.cadastralReference ? ` · ${esc(item.cadastralReference)}` : ''}`;
}

function fairnessAnalysis() {
  const counts = fairnessCounts(); const members = activeTeam(); const cells = []; const agendas = [];
  const totals = Object.fromEntries(members.map((member) => [member.id, state.agendas.reduce((sum, item) => sum + (counts[member.id]?.[item.id] || 0), 0)]));
  for (const item of state.agendas) {
    const eligible = members.filter((member) => member.allowedTypes.includes(item.id) && totals[member.id]);
    const meanShare = eligible.length ? eligible.reduce((sum, member) => sum + (counts[member.id]?.[item.id] || 0) / totals[member.id], 0) / eligible.length : null;
    const agendaCells = eligible.map((member) => {
      const expectedShare = meanShare; const actualShare = (counts[member.id]?.[item.id] || 0) / totals[member.id];
      const deviation = meanShare === null ? null : actualShare - meanShare;
      const cell = { member, agenda: item, expectedShare, actualShare, deviation, value: counts[member.id]?.[item.id] || 0 }; cells.push(cell); return cell;
    });
    const measured = agendaCells.filter((cell) => cell.deviation !== null);
    agendas.push({ agenda: item, averageDeviation: measured.length ? measured.reduce((sum, cell) => sum + Math.abs(cell.deviation), 0) / measured.length : null });
  }
  const measured = cells.filter((cell) => cell.deviation !== null);
  const globalScore = measured.length ? Math.round(measured.reduce((sum, cell) => sum + Math.max(0, 1 - Math.min(Math.abs(cell.deviation), 1)), 0) / measured.length * 100) : null;
  const memberScores = Object.fromEntries(members.map((member) => { const own = measured.filter((cell) => cell.member.id === member.id); return [member.id, own.length ? Math.round(own.reduce((sum, cell) => sum + Math.max(0, 1 - Math.min(Math.abs(cell.deviation), 1)), 0) / own.length * 100) : null]; }));
  return { counts, cells, agendas, globalScore, memberScores, measured };
}
function deviationLabel(value) { if (value === null) return '—'; const rounded = Math.round(value * 100); return `${rounded > 0 ? '+' : ''}${rounded}%`; }
function shortAgendaName(name) { return name.replace('ambulatori', 'amb.').replace('ambulatòria', 'amb.').replace('urgent', 'urg.').replace('tècnics', 'tèc.').replace('Intervencionisme', 'Interv.').replace('Telecomandament', 'Telecom.').replace('Ressonància', 'Resson.'); }
function deviationRow(cell) { const magnitude = cell.deviation === null ? 0 : Math.min(Math.abs(cell.deviation), 1) * 50; const side = cell.deviation === null ? 'none' : cell.deviation >= 0 ? 'over' : 'under'; return `<div class="deviation-row"><span><i style="--agenda-color:${cell.agenda.color}"></i>${esc(cell.agenda.name)}</span><div class="deviation-track"><b></b><i class="${side}" style="--deviation-width:${magnitude}%"></i></div><strong>${deviationLabel(cell.deviation)}</strong></div>`; }
function heatCell(cell) {
  if (!cell || cell.deviation === null) return '<div class="heat-cell empty" title="Sense dades">—</div>';
  const roundedDeviation = Math.round(cell.deviation * 100);
  const magnitude = Math.abs(cell.deviation);
  const direction = Math.abs(roundedDeviation) <= 5 ? 'balanced' : roundedDeviation < 0 ? 'below' : 'above';
  const strength = magnitude >= 0.25 ? 'strong' : magnitude >= 0.1 ? 'medium' : 'soft';
  const actual = Math.round(cell.actualShare * 100);
  const expected = Math.round(cell.expectedShare * 100);
  const detail = state.language === 'es'
    ? `Real ${actual}% · esperado ${expected}%`
    : `Real ${actual}% · esperat ${expected}%`;
  return `<div class="heat-cell ${direction} ${strength}" title="${detail}" aria-label="${detail}">${direction === 'balanced' ? '≈' : deviationLabel(cell.deviation)}</div>`;
}

function orderedFairnessAgendas(analysis, members) {
  return state.agendas
    .map((agenda) => ({
      agenda,
      valueCount: members.reduce((total, member) => total + Number(analysis.cells.some((cell) => cell.member.id === member.id && cell.agenda.id === agenda.id && cell.deviation !== null)), 0),
    }))
    .sort((left, right) => right.valueCount - left.valueCount || left.agenda.name.localeCompare(right.agenda.name, state.language === 'es' ? 'es' : 'ca', { sensitivity: 'base' }))
    .map((entry) => entry.agenda);
}
function teleworkBalance(selected, analysis) {
  const activities = activeActivities();
  const telematicIds = new Set(activities.filter((item) => item.telematic).map((item) => item.id));
  const summaryFor = (member) => activities.reduce((summary, item) => { const value = analysis.counts[member.id]?.[item.id] || 0; summary.total += value; if (telematicIds.has(item.id)) summary.telematic += value; return summary; }, { total: 0, telematic: 0 });
  const teamShares = activeTeam().map(summaryFor).filter((summary) => summary.total).map((summary) => summary.telematic / summary.total);
  const own = selected ? summaryFor(selected) : { total: 0, telematic: 0 };
  return { person: own.total ? own.telematic / own.total : null, team: teamShares.length ? teamShares.reduce((sum, value) => sum + value, 0) / teamShares.length : null };
}

function managementSummary() {
  const eligible = activeTeam().filter((member) => Number(member.managementQuota || 0) > 0);
  const assignments = calendarEvents().filter((item) => item.type === MANAGEMENT_ACTIVITY.id);
  const months = hasCalendarContent() ? periodMonthCount(projectionStartMonth(calendarProjection()), projectionEndMonth(calendarProjection())) : 0;
  const target = months * eligible.reduce((sum, member) => sum + Number(member.managementQuota || 0), 0);
  return {
    assigned: assignments.length,
    target,
    recipients: new Set(assignments.map((item) => item.memberId)).size,
    eligible: eligible.length,
  };
}

function managementRecipientLabel(summary) {
  if (!summary.eligible) return state.language === 'es' ? 'Ninguna persona habilitada' : 'Cap persona habilitada';
  return state.language === 'es'
    ? `${summary.recipients} de ${summary.eligible} personas habilitadas`
    : `${summary.recipients} de ${summary.eligible} persones habilitades`;
}
function teleworkBar(balance) {
  const personValue = balance.person === null ? null : Math.round(balance.person * 100); const teamValue = balance.team === null ? null : Math.round(balance.team * 100);
  return `<section class="telework-balance"><div class="telework-head"><b>Teletreball</b></div><div class="telework-track" aria-label="Persona ${personValue ?? 0}%, equip ${teamValue ?? 0}%"><i style="width:${personValue ?? 0}%"></i>${teamValue === null ? '' : `<b class="team" style="left:${teamValue}%" title="Equip ${teamValue}%"></b>`}</div><div class="telework-legend"><span class="person">Persona <b>${personValue === null ? '—' : `${personValue}%`}</b></span><span class="team">Equip <b>${teamValue === null ? '—' : `${teamValue}%`}</b></span></div><small>${personValue === null ? 'Sense activitat per calcular-ho. ' : ''}Equip = mitjana real de les persones.</small></section>`;
}
function happinessTimeline() {
  const people = [...state.team, ...(state.archivedTeam || [])]; const byId = Object.fromEntries(people.map((member) => [member.id, member])); const records = hasCalendarContent() ? [calendarProjection()] : [];
  const assignments = records.flatMap((record) => record.assignments || []).filter((item) => !['no_assignment', 'management'].includes(item.type) && byId[item.memberId]).sort((left, right) => left.date.localeCompare(right.date)); const dates = [...new Set(assignments.map((item) => item.date))]; const cumulative = Object.fromEntries(people.map((member) => [member.id, { points: 0, load: 0, started: false }])); const series = Object.fromEntries(people.map((member) => [member.id, []]));
  for (const date of dates) { for (const item of assignments.filter((assignment) => assignment.date === date)) { const summary = cumulative[item.memberId]; const load = Number(item.loadPercentage ?? agenda(item.type).loadPercentage ?? 100) / 100; summary.points += Number(byId[item.memberId].agendaPreferences?.[item.type] || 0) * load; summary.load += load; summary.started = true; } for (const member of people) { const summary = cumulative[member.id]; if (summary.started && summary.load) series[member.id].push({ date, value: summary.points / summary.load }); } }
  const average = dates.map((date) => { const values = people.map((member) => series[member.id].find((point) => point.date === date)?.value).filter((value) => value !== undefined); return values.length ? { date, value: values.reduce((sum, value) => sum + value, 0) / values.length } : null; }).filter(Boolean);
  return { people: people.filter((member) => series[member.id].length), dates, series, average };
}
function happinessChart() {
  const timeline = happinessTimeline();
  if (!timeline.dates.length) return '<div class="empty-state">Sense assignacions per calcular la felicitat.</div>';
  const width = 1000; const height = 340; const left = 58; const right = 20; const top = 22; const bottom = 42;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const start = fromKey(timeline.dates[0]).getTime(); const end = fromKey(timeline.dates.at(-1)).getTime();
  const x = (date) => end === start ? left + plotWidth / 2 : left + (fromKey(date).getTime() - start) / (end - start) * plotWidth;
  const y = (value) => top + (1 - (value + 1) / 2) * plotHeight;
  const line = (points) => points.map((point) => `${x(point.date).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');
  const yTicks = [-1, -.5, 0, .5, 1];
  const xStep = Math.max(1, Math.ceil(timeline.dates.length / 6));
  const xTicks = timeline.dates.filter((_, index) => index % xStep === 0 || index === timeline.dates.length - 1);
  const shortRange = end - start < 366 * 86400000;
  const axisDateOptions = shortRange ? { day: 'numeric', month: 'short' } : { month: 'short', year: '2-digit' };
  const seriesMarkup = (name, points, color, average = false) => {
    const seriesClass = average ? 'happiness-average-series' : 'happiness-person-series';
    const circles = points.map((point) => {
      const valueLabel = `${Math.round(point.value * 100)}%`;
      return `<circle data-happiness-point data-date="${point.date}" data-value="${valueLabel}" cx="${x(point.date).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="${average ? '3.2' : '2.4'}"><title>${esc(name)} · ${fmtDate(point.date, { day: 'numeric', month: 'short', year: 'numeric' })} · ${valueLabel}</title></circle>`;
    }).join('');
    return `<g class="happiness-series ${seriesClass}" data-happiness-series data-series-name="${esc(name)}" style="--series-color:${color}"><polyline class="happiness-series-line" points="${line(points)}"></polyline><polyline class="happiness-series-hit" points="${line(points)}"></polyline>${circles}</g>`;
  };
  const peopleLines = timeline.people.map((member) => seriesMarkup(member.name, timeline.series[member.id], member.color)).join('');
  const averageName = state.language === 'es' ? 'Media del equipo' : 'Mitjana de l’equip';
  const averageLine = seriesMarkup(averageName, timeline.average, 'var(--brand)', true);
  const legendButton = (name, color, average = false) => `<button type="button" class="${average ? 'is-average' : ''}" data-happiness-legend-name="${esc(name)}" aria-pressed="true" style="--member-color:${color}" title="${state.language === 'es' ? 'Mostrar u ocultar' : 'Mostra o amaga'} ${esc(name)}"><i></i>${esc(name)}</button>`;
  return `<div class="happiness-chart-shell"><div class="happiness-chart-wrap"><svg class="happiness-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Evolució de l’índex acumulat de felicitat">${yTicks.map((value) => `<g class="happiness-grid"><line x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}"></line><text x="${left - 10}" y="${y(value) + 4}">${Math.round(value * 100)}%</text></g>`).join('')}${xTicks.map((date) => `<g class="happiness-axis"><line x1="${x(date)}" y1="${top}" x2="${x(date)}" y2="${height - bottom}"></line><text x="${x(date)}" y="${height - 15}">${fmtDate(date, axisDateOptions)}</text></g>`).join('')}${peopleLines}${averageLine}</svg></div><div class="happiness-chart-tooltip" hidden><b data-happiness-tooltip-name></b><span data-happiness-tooltip-date></span><strong data-happiness-tooltip-value></strong></div></div><div class="happiness-legend">${legendButton(averageName, 'var(--brand)', true)}${timeline.people.map((member) => legendButton(member.name, member.color)).join('')}</div>`;
}

function clearHappinessChartHover(shell) {
  shell.querySelector('.happiness-chart')?.classList.remove('has-hover');
  shell.querySelectorAll('.happiness-series.is-hovered').forEach((series) => series.classList.remove('is-hovered'));
  shell.querySelectorAll('[data-happiness-point].is-active').forEach((point) => point.classList.remove('is-active'));
  const tooltip = shell.querySelector('.happiness-chart-tooltip');
  if (tooltip) tooltip.hidden = true;
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-happiness-legend-name]');
  if (!button) return;
  const card = button.closest('.happiness-card');
  const chart = card?.querySelector('.happiness-chart');
  const shell = card?.querySelector('.happiness-chart-shell');
  const series = [...(chart?.querySelectorAll('[data-happiness-series]') || [])].find((item) => item.dataset.seriesName === button.dataset.happinessLegendName);
  if (!series) return;
  const selected = button.getAttribute('aria-pressed') !== 'true';
  button.setAttribute('aria-pressed', String(selected));
  series.classList.toggle('is-filtered-out', !selected);
  if (shell) clearHappinessChartHover(shell);
});

document.addEventListener('pointermove', (event) => {
  const shell = event.target.closest('.happiness-chart-shell');
  if (!shell) return;
  const series = event.target.closest('[data-happiness-series]');
  if (!series) { clearHappinessChartHover(shell); return; }
  const svg = series.closest('svg');
  const points = [...series.querySelectorAll('[data-happiness-point]')];
  if (!svg || !points.length) return;
  const svgRect = svg.getBoundingClientRect();
  const viewBox = svg.viewBox.baseVal;
  const pointerX = viewBox.x + (event.clientX - svgRect.left) / svgRect.width * viewBox.width;
  const point = points.reduce((nearest, candidate) => Math.abs(Number(candidate.getAttribute('cx')) - pointerX) < Math.abs(Number(nearest.getAttribute('cx')) - pointerX) ? candidate : nearest);
  svg.classList.add('has-hover');
  svg.querySelectorAll('[data-happiness-series]').forEach((item) => item.classList.toggle('is-hovered', item === series));
  svg.querySelectorAll('[data-happiness-point]').forEach((item) => item.classList.toggle('is-active', item === point));
  const tooltip = shell.querySelector('.happiness-chart-tooltip');
  const shellRect = shell.getBoundingClientRect();
  const pointX = Number(point.getAttribute('cx'));
  const pointY = Number(point.getAttribute('cy'));
  tooltip.querySelector('[data-happiness-tooltip-name]').textContent = series.dataset.seriesName;
  tooltip.querySelector('[data-happiness-tooltip-date]').textContent = fmtDate(point.dataset.date, { day: 'numeric', month: 'short', year: 'numeric' });
  tooltip.querySelector('[data-happiness-tooltip-value]').textContent = point.dataset.value;
  tooltip.style.left = `${svgRect.left - shellRect.left + (pointX - viewBox.x) / viewBox.width * svgRect.width}px`;
  tooltip.style.top = `${svgRect.top - shellRect.top + (pointY - viewBox.y) / viewBox.height * svgRect.height}px`;
  tooltip.hidden = false;
});

document.addEventListener('pointerout', (event) => {
  const shell = event.target.closest('.happiness-chart-shell');
  if (shell && !shell.contains(event.relatedTarget)) clearHappinessChartHover(shell);
});
function historyPage() {
  const analysis = fairnessAnalysis(); const activities = activeActivities(); const members = activeTeam(); const selected = members.find((member) => member.id === historyMemberFilter) || members[0]; if (selected) historyMemberFilter = selected.id;
  const selectedCells = selected ? state.agendas.map((item) => analysis.cells.find((cell) => cell.member.id === selected.id && cell.agenda.id === item.id)).filter(Boolean) : [];
  const memberTotal = selected ? activities.reduce((sum, item) => sum + (analysis.counts[selected.id]?.[item.id] || 0), 0) : 0;
  const composition = selected && memberTotal ? activities.map((item) => ({ item, share: (analysis.counts[selected.id]?.[item.id] || 0) / memberTotal })).filter((entry) => entry.share > 0).sort((left, right) => right.share - left.share || left.item.name.localeCompare(right.item.name, 'ca')) : [];
  const telework = teleworkBalance(selected, analysis);
  const heatmapAgendas = orderedFairnessAgendas(analysis, members);
  return `${header('Equitat i històric', 'Desviació respecte al perfil mitjà de les persones comparables', '<button class="button ghost small" data-action="backup">Còpia JSON</button>')}
    <section class="fairness-stats fairness-stats-single"><div class="insight-card card"><span>Índex global d’equilibri</span><strong>${analysis.globalScore === null ? '—' : `${analysis.globalScore}/100`}</strong><small>${analysis.globalScore === null ? 'Genera un període per començar' : analysis.globalScore >= 80 ? 'Repartiment molt equilibrat' : analysis.globalScore >= 60 ? 'Equilibri millorable' : 'Cal revisar el repartiment'}</small></div></section>
    <section class="section"><div class="section-head"><div><h2>Evolució de la felicitat</h2><div class="muted">Índex acumulat ponderat per càrrega: ♥ suma, 👎 resta i sense reacció no modifica el resultat.</div></div></div><div class="card happiness-card">${happinessChart()}<p>La sèrie històrica es recalcula amb les preferències actuals. La mitjana de l’equip està ressaltada.</p></div></section>
    <section class="section"><div class="section-head"><div><h2>Equilibri d’una persona</h2><div class="muted">La composició mostra què ha fet; les barres indiquen desviació respecte al seu repartiment esperat.</div></div><select data-action="history-member">${memberOptions(selected?.id || '')}</select></div><div class="person-balance-grid"><section class="card balance-profile" style="--member-color:${selected?.color || '#b9c4c0'}"><div class="balance-person"><span class="member-avatar">${selected ? esc(selected.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('')) : '—'}</span><div><h3>${esc(selected?.name || 'Sense membres')}</h3><span>Índex personal ${selected && analysis.memberScores[selected.id] !== null ? `${analysis.memberScores[selected.id]}/100` : '—'}</span></div></div><div class="composition-bar">${composition.map((entry) => `<i style="width:${entry.share * 100}%;--agenda-color:${entry.item.color}" title="${esc(entry.item.name)} · ${Math.round(entry.share * 100)}%"></i>`).join('') || '<span>Sense activitat registrada</span>'}</div><div class="composition-legend" style="--legend-rows:${Math.ceil(composition.length / 2) || 1}">${composition.map((entry) => `<span><i style="--agenda-color:${entry.item.color}"></i>${esc(entry.item.name)} <b>${Math.round(entry.share * 100)}%</b></span>`).join('')}</div>${teleworkBar(telework)}</section><section class="card deviation-card"><div class="deviation-head"><span>Per sota</span><b>Esperat</b><span>Per sobre</span></div>${selectedCells.map(deviationRow).join('') || '<div class="empty-state">Sense dades per comparar.</div>'}</section></div></section>
    <section class="section"><div class="section-head"><div><h2>Equilibri entre persones</h2><div class="muted">Mapa de calor: blau = menys del repartiment esperat; corall = més. Clica una persona per veure’n el detall.</div></div><div class="heat-legend"><span>Per sota</span><i></i><span>Equilibri</span><i></i><span>Per sobre</span></div></div><div class="card heatmap-wrap"><div class="fairness-heatmap" style="--agenda-columns:${heatmapAgendas.length}"><div class="heat-corner">Persona</div>${heatmapAgendas.map((item) => `<div class="heat-head" title="${esc(item.name)}"><i style="--agenda-color:${item.color}"></i><span>${esc(shortAgendaName(item.name))}</span></div>`).join('')}${members.flatMap((member) => [`<button class="heat-person" data-history-member="${member.id}" style="--member-color:${member.color}"><i></i>${esc(member.name)}</button>`, ...heatmapAgendas.map((item) => heatCell(analysis.cells.find((cell) => cell.member.id === member.id && cell.agenda.id === item.id)))]).join('')}</div></div></section>`;
}

function guidePage() {
  const es = state.language === 'es';
  const g = (ca, translated) => es ? translated : ca;
  const hardRules = [
    g('La persona ha d’estar activa, treballar aquell dia i no estar de vacances ni de postguàrdia.', 'La persona debe estar activa, trabajar ese día y no estar de vacaciones ni de postguardia.'),
    g('Només pot cobrir agendes habilitades al seu perfil.', 'Sólo puede cubrir agendas habilitadas en su perfil.'),
    g('En un dia telemàtic només pot rebre activitat telemàtica.', 'En un día telemático sólo puede recibir actividad telemática.'),
    g('Les regles fixes es respecten mentre la persona estigui disponible.', 'Las reglas fijas se respetan mientras la persona esté disponible.'),
    g('No se supera la càrrega diària: una agenda completa o dues agendes parcials diferents.', 'No se supera la carga diaria: una agenda completa o dos agendas parciales diferentes.'),
  ];
  const preparation = [
    [g('Hospitals', 'Hospitales'), g('Afegeix els centres on es treballa.', 'Añade los centros donde se trabaja.')],
    [g('Agendes', 'Agendas'), g('Indica hospital, matí o tarda, completa o parcial, presencial o telemàtica, cobertura i prioritat.', 'Indica hospital, mañana o tarde, completa o parcial, presencial o telemática, cobertura y prioridad.')],
    [g('Equip', 'Equipo'), g('Revisa dies de treball, setmanes alternes, capacitats, dies telemàtics, vacances, regles fixes i dies de Gestió.', 'Revisa días de trabajo, semanas alternas, capacidades, días telemáticos, vacaciones, reglas fijas y días de Gestión.')],
    [g('Guàrdies', 'Guardias'), g('Mantén les guàrdies al dia. La postguàrdia del dia següent es calcula automàticament.', 'Mantén las guardias al día. La postguardia del día siguiente se calcula automáticamente.')],
    [g('Calendari', 'Calendario'), g('Genera un únic mes i revisa el resultat abans de fer canvis manuals.', 'Genera un único mes y revisa el resultado antes de hacer cambios manuales.')],
  ];
  return `<section class="guide-page">
    ${header(g('Guia d’ús', 'Guía de uso'), g('Tot Pinendar explicat sense tecnicismes.', 'Todo Pinendar explicado sin tecnicismos.'))}
    <section class="guide-hero card">
      <div><div class="eyebrow">${g('IDEA PRINCIPAL', 'IDEA PRINCIPAL')}</div><h2>${g('Pinendar proposa. Tu decideixes.', 'Pinendar propone. Tú decides.')}</h2><p>${g('La plataforma prepara el calendari mensual, assenyala els problemes i permet revisar o canviar el resultat. Si una generació falla, el calendari actual no es modifica.', 'La plataforma prepara el calendario mensual, señala los problemas y permite revisar o cambiar el resultado. Si una generación falla, el calendario actual no se modifica.')}</p></div>
      <div class="guide-quick"><b>${g('En 30 segons', 'En 30 segundos')}</b><span>1. ${g('Actualitza equip i guàrdies', 'Actualiza equipo y guardias')}</span><span>2. ${g('Genera el mes', 'Genera el mes')}</span><span>3. ${g('Revisa avisos', 'Revisa los avisos')}</span><span>4. ${g('Ajusta i exporta', 'Ajusta y exporta')}</span></div>
    </section>

    <section class="guide-section card"><div class="guide-section-head"><span>1</span><div><h2>${g('Abans de generar', 'Antes de generar')}</h2><p>${g('Un bon calendari depèn de tenir aquestes dades actualitzades.', 'Un buen calendario depende de tener estos datos actualizados.')}</p></div></div><div class="guide-step-list">${preparation.map(([title, description], index) => `<article><i>${index + 1}</i><div><b>${title}</b><p>${description}</p></div></article>`).join('')}</div></section>

    <section class="guide-section card"><div class="guide-section-head"><span>2</span><div><h2>${g('Regles que mai no es trenquen', 'Reglas que nunca se rompen')}</h2><p>${g('Si una assignació incompleix una d’aquestes regles, Pinendar no la farà.', 'Si una asignación incumple una de estas reglas, Pinendar no la hará.')}</p></div></div><ul class="guide-check-list">${hardRules.map((rule) => `<li><span>✓</span>${rule}</li>`).join('')}</ul></section>

    <section class="guide-section card"><div class="guide-section-head"><span>3</span><div><h2>${g('Com tria el millor repartiment', 'Cómo elige el mejor reparto')}</h2><p>${g('No barreja tots els criteris. Assegura cada objectiu abans de passar al següent.', 'No mezcla todos los criterios. Asegura cada objetivo antes de pasar al siguiente.')}</p></div></div>
      <ol class="guide-priority-list">
        <li><b>${g('Protegeix les agendes de prioritat molt alta.', 'Protege las agendas de prioridad muy alta.')}</b><span>${g('Són les primeres que intenta cobrir.', 'Son las primeras que intenta cubrir.')}</span></li>
        <li><b>${g('Reparteix Gestió per rondes.', 'Reparte Gestión por rondas.')}</b><span>${g('Intenta donar un primer dia a tothom abans de donar-ne un segon. Gestió pot desplaçar prioritats alta, moderada o baixa, però no la molt alta.', 'Intenta dar un primer día a todos antes de dar un segundo. Gestión puede desplazar prioridades alta, moderada o baja, pero no la muy alta.')}</span></li>
        <li><b>${g('Cobreix la resta per prioritat.', 'Cubre el resto por prioridad.')}</b><span>${g('Primer alta, després moderada i finalment baixa.', 'Primero alta, después moderada y finalmente baja.')}</span></li>
        <li><b>${g('Redueix jornades parcials i persones sense activitat.', 'Reduce jornadas parciales y personas sin actividad.')}</b><span>${g('Si dues agendes parcials poden completar una persona, evita repartir-les innecessàriament.', 'Si dos agendas parciales pueden completar una persona, evita repartirlas innecesariamente.')}</span></li>
        <li><b>${g('Millora l’equitat.', 'Mejora la equidad.')}</b><span>${g('Entre repartiments igual de bons en tot l’anterior, distribueix les agendes per acostar cada perfil al repartiment històric de l’equip.', 'Entre repartos igual de buenos en todo lo anterior, distribuye las agendas para acercar cada perfil al reparto histórico del equipo.')}</span></li>
        <li><b>${g('Col·loca Gestió preferentment en divendres i després en dilluns.', 'Coloca Gestión preferentemente en viernes y después en lunes.')}</b><span>${g('Només ho fa si no empitjora cap criteri anterior.', 'Sólo lo hace si no empeora ningún criterio anterior.')}</span></li>
      </ol>
      <div class="guide-note"><b>${g('I els cors i polzes?', '¿Y los corazones y pulgares?')}</b> ${g('Les preferències es guarden i apareixen a les mètriques de felicitat, però de moment no influeixen en la generació.', 'Las preferencias se guardan y aparecen en las métricas de felicidad, pero por ahora no influyen en la generación.')}</div>
    </section>

    <section class="guide-section card"><div class="guide-section-head"><span>4</span><div><h2>${g('Com llegir el calendari', 'Cómo leer el calendario')}</h2><p>${g('Els tres avisos principals es veuen en dia, setmana i mes.', 'Los tres avisos principales se ven en día, semana y mes.')}</p></div></div><div class="guide-signal-grid">
      <article class="vacancy"><i>!</i><div><b>${g('Agenda sense cobrir', 'Agenda sin cubrir')}</b><p>${g('Hi havia una plaça necessària i ningú l’ha pogut cobrir.', 'Había una plaza necesaria y nadie ha podido cubrirla.')}</p></div></article>
      <article class="unassigned"><i>−</i><div><b>${g('Persona sense agenda', 'Persona sin agenda')}</b><p>${g('La persona podia treballar, però no ha rebut activitat.', 'La persona podía trabajar, pero no ha recibido actividad.')}</p></div></article>
      <article class="partial"><i>~</i><div><b>${g('Agenda parcial', 'Agenda parcial')}</b><p>${g('La persona només té coberta una part de la jornada o té una agenda menys demandant.', 'La persona sólo tiene cubierta una parte de la jornada o tiene una agenda menos exigente.')}</p></div></article>
    </div><p class="guide-footnote">${g('En dia i setmana, les targetes s’agrupen per hospital i indiquen matí/tarda i completa/parcial. En mes es mostra només el nom; el color identifica l’agenda.', 'En día y semana, las tarjetas se agrupan por hospital e indican mañana/tarde y completa/parcial. En mes se muestra sólo el nombre; el color identifica la agenda.')}</p></section>

    <section class="guide-section card"><div class="guide-section-head"><span>5</span><div><h2>${g('Canvis després de generar', 'Cambios después de generar')}</h2><p>${g('El calendari continua sent editable, però cada acció té un significat diferent.', 'El calendario sigue siendo editable, pero cada acción tiene un significado diferente.')}</p></div></div><div class="guide-action-grid">
      <article><b>${g('Intercanviar agendes', 'Intercambiar agendas')}</b><p>${g('Clica una persona assignada. Pinendar mostra els intercanvis possibles, ordenats segons l’impacte en equitat, i canvia les dues persones alhora.', 'Haz clic en una persona asignada. Pinendar muestra los intercambios posibles, ordenados según el impacto en equidad, y cambia las dos personas a la vez.')}</p></article>
      <article><b>${g('Obrir activitat extra', 'Abrir actividad extra')}</b><p>${g('Clica una persona sense activitat per afegir una agenda compatible fora de la demanda habitual. No elimina una vacant ordinària.', 'Haz clic en una persona sin actividad para añadir una agenda compatible fuera de la demanda habitual. No elimina una vacante ordinaria.')}</p></article>
      <article><b>${g('Canviar una regla fixa', 'Cambiar una regla fija')}</b><p>${g('Només es pot iniciar des de la persona que la té. Apareix un avís i el canvi afecta aquest calendari, no la regla futura del perfil.', 'Sólo puede iniciarse desde la persona que la tiene. Aparece un aviso y el cambio afecta este calendario, no la regla futura del perfil.')}</p></article>
      <article><b>${g('Cedir o intercanviar guàrdies', 'Ceder o intercambiar guardias')}</b><p>${g('Pinendar recalcula les postguàrdies i intenta mantenir cobertes les agendes base amb el mínim de moviments.', 'Pinendar recalcula las postguardias e intenta mantener cubiertas las agendas base con el mínimo de movimientos.')}</p></article>
    </div></section>

    <section class="guide-section card"><div class="guide-section-head"><span>6</span><div><h2>${g('Històric, mètriques i exportació', 'Histórico, métricas y exportación')}</h2><p>${g('Cada període generat s’afegeix al calendari. Els mesos anteriors es conserven.', 'Cada período generado se añade al calendario. Los meses anteriores se conservan.')}</p></div></div><div class="guide-action-grid">
      <article><b>${g('Equitat', 'Equidad')}</b><p>${g('Compara el percentatge d’agendes de cada persona amb el perfil mitjà de persones que poden fer-les.', 'Compara el porcentaje de agendas de cada persona con el perfil medio de personas que pueden hacerlas.')}</p></article>
      <article><b>${g('Felicitat', 'Felicidad')}</b><p>${g('Mostra l’evolució de cors i polzes. És informativa.', 'Muestra la evolución de corazones y pulgares. Es informativa.')}</p></article>
      <article><b>${g('Exportació', 'Exportación')}</b><p>${g('CSV, Excel i ICS respecten el període i els filtres actius del calendari.', 'CSV, Excel e ICS respetan el período y los filtros activos del calendario.')}</p></article>
      <article><b>${g('Compte i dades', 'Cuenta y datos')}</b><p>${g('Cada compte té un entorn independent. Desa la clau de recuperació; quan s’utilitza, se’n genera una de nova. Qualsevol accés o ús autenticat reinicia el termini d’activitat. Després de més de sis mesos naturals sense activitat, el compte i totes les seves dades s’eliminen automàticament i de manera irreversible.', 'Cada cuenta tiene un entorno independiente. Guarda la clave de recuperación; al utilizarla, se genera una nueva. Cualquier acceso o uso autenticado reinicia el plazo de actividad. Tras más de seis meses naturales sin actividad, la cuenta y todos sus datos se eliminan automática e irreversiblemente.')}</p></article>
    </div></section>

    <section class="guide-section card"><div class="guide-section-head"><span>7</span><div><h2>${g('Projecte obert', 'Proyecto abierto')}</h2><p>${g('Pinendar és programari lliure publicat amb llicència MIT.', 'Pinendar es software libre publicado con licencia MIT.')}</p></div></div><div class="guide-note">${g('Pots consultar el codi, la documentació i la llicència completa a', 'Puedes consultar el código, la documentación y la licencia completa en')} <a href="https://github.com/massimo92/Pinendar" target="_blank" rel="noopener noreferrer">GitHub · massimo92/Pinendar</a>.</div></section>

    <section class="guide-section guide-faq card"><div class="guide-section-head"><span>?</span><div><h2>${g('Preguntes freqüents', 'Preguntas frecuentes')}</h2></div></div>
      <details><summary>${g('Per què hi pot haver una vacant i una persona sense agenda el mateix dia?', '¿Por qué puede haber una vacante y una persona sin agenda el mismo día?')}</summary><p>${g('Perquè aquella persona pot no tenir capacitat per fer l’agenda, estar en dia telemàtic o no poder completar una combinació parcial vàlida.', 'Porque esa persona puede no estar habilitada para esa agenda, estar en día telemático o no poder completar una combinación parcial válida.')}</p></details>
      <details><summary>${g('Per què l’equitat no canvia una agenda prioritària?', '¿Por qué la equidad no cambia una agenda prioritaria?')}</summary><p>${g('Perquè l’equitat només tria entre resultats que ja tenen la mateixa cobertura, Gestió i nombre mínim d’incidències.', 'Porque la equidad sólo elige entre resultados que ya tienen la misma cobertura, Gestión y número mínimo de incidencias.')}</p></details>
      <details><summary>${g('Es pot ajustar el calendari generat?', '¿Se puede ajustar el calendario generado?')}</summary><p>${g('Sí. Els avisos, intercanvis i canvis de guàrdia permeten revisar-lo i mantenen la decisió final en mans de l’equip.', 'Sí. Los avisos, intercambios y cambios de guardia permiten revisarlo y mantienen la decisión final en manos del equipo.')}</p></details>
    </section>
  </section>`;
}

function activeGuards() {
  return [...calendarGuards()].sort((left, right) => left.date.localeCompare(right.date) || person(left.memberId)?.name.localeCompare(person(right.memberId)?.name || '') || 0);
}
function guardTransferOperations() {
  const groups = new Map();
  for (const leg of state.calendar?.guardTransfers || []) {
    if (!groups.has(leg.operationId)) groups.set(leg.operationId, { ...leg, legs: [] });
    groups.get(leg.operationId).legs.push(leg);
  }
  return [...groups.values()].sort((left, right) => right.createdAt.localeCompare(left.createdAt));
}
function guardPartyName(memberId) { return memberId ? esc(person(memberId)?.name || '—') : '<span class="guard-external">Exterior</span>'; }
function guardMemberOptions(selected = '', includeExternal = true, excludedMemberId = '') {
  return `<option value="" disabled ${selected ? '' : 'selected'}>Selecciona una persona</option>${includeExternal ? `<option value="external" ${selected === 'external' ? 'selected' : ''}>Exterior</option>` : ''}${alphabetically(activeTeam()).filter((member) => member.id !== excludedMemberId).map((member) => `<option value="${member.id}" ${selected === member.id ? 'selected' : ''}>${esc(member.name)}</option>`).join('')}`;
}
function guardsPage() {
  const guards = activeGuards();
  const operations = guardTransferOperations();
  const guardRows = guards.map((item) => `<article class="guard-row"><div class="guard-date"><strong>${fmtDate(item.date, { day: 'numeric', month: 'short' })}</strong><span>${fmtDate(item.date, { weekday: 'long' })}</span></div><div class="guard-owner"><span class="member-avatar" style="--member-color:${person(item.memberId)?.color || '#cbd5d0'}">${esc(person(item.memberId)?.name?.split(/\s+/).slice(0, 2).map((part) => part[0]).join('') || '—')}</span><div><b>${esc(person(item.memberId)?.name || '—')}</b><small>Postguàrdia · ${fmtDate(addDays(item.date, 1), { day: 'numeric', month: 'short' })}</small></div></div><div class="guard-row-actions"><button class="button ghost small" data-action="open-guard-cession" data-guard-id="${item.id}">Cedeix</button><button class="button secondary small" data-action="open-guard-exchange" data-guard-id="${item.id}">Intercanvia</button></div></article>`).join('');
  const historyRows = operations.map((operation) => `<article class="guard-history-row"><div><b>${operation.operationKind === 'exchange' ? 'Intercanvi' : 'Cessió'}</b><span>${fmtDate(operation.createdAt.slice(0, 10), { day: 'numeric', month: 'short', year: 'numeric' })}</span></div><div class="guard-history-legs">${operation.legs.sort((left, right) => left.date.localeCompare(right.date)).map((leg) => `<span><time>${fmtDate(leg.date, { day: 'numeric', month: 'short' })}</time>${guardPartyName(leg.fromMemberId)} <i>→</i> ${guardPartyName(leg.toMemberId)}</span>`).join('')}</div><small>${operation.impact?.moves || 0} canvis al calendari${operation.note ? ` · ${esc(operation.note)}` : ''}</small></article>`).join('');
  return `${header('Guàrdies', `${guards.length} guàrdies internes`, '<button class="button" data-action="open-incoming-guard">Afegeix guàrdia</button>')}<section class="guard-page-grid"><div><section class="card guard-panel"><div class="guard-list">${guardRows || '<div class="empty-state">No hi ha guàrdies internes.</div>'}</div></section></div><aside><section class="card guard-help"><div class="card-kicker">COM FUNCIONA</div><h3>Dos moviments clars</h3><dl><div><dt>Cessió</dt><dd>Canvia el responsable d’una data. Una part pot ser exterior.</dd></div><div><dt>Intercanvi</dt><dd>Permuta dues guàrdies. Amb Exterior, la guàrdia surt del calendari intern.</dd></div></dl><p>Abans d’aplicar, Pinendar ensenya els canvis mínims al calendari.</p></section></aside></section><section class="section guard-history"><div class="section-head"><div><h2>Històric de canvis</h2><p class="muted">Les cobertures exteriors només consten aquí.</p></div></div><div class="card guard-history-list">${historyRows || '<div class="empty-state">Encara no s’ha modificat cap guàrdia.</div>'}</div></section>`;
}
function guardOperationPayload(formElement, operation) {
  const form = new FormData(formElement);
  if (operation === 'cession') {
    const target = form.get('toMemberId');
    const date = form.get('date');
    if (!target || !date) return null;
    return {
      guardId: form.get('guardId') || null,
      date,
      toMemberId: target === 'external' ? null : target,
      note: form.get('note')?.trim() || '',
      expectedRevision: state.planningRevision,
    };
  }
  const secondRef = form.get('secondRef');
  if (!secondRef) return null;
  const second = activeGuards().find((item) => item.id === secondRef);
  return {
    firstGuardId: form.get('firstGuardId'),
    firstDate: form.get('firstDate'),
    secondGuardId: second?.id || null,
    secondDate: second?.date || null,
    note: form.get('note')?.trim() || '',
    expectedRevision: state.planningRevision,
  };
}

async function refreshGuardOperationPreview(formElement) {
  const operation = modal?.type === 'guard-cession' ? 'cession' : modal?.type === 'guard-exchange' ? 'exchange' : '';
  if (!operation) return;
  const form = new FormData(formElement);
  if (operation === 'cession') {
    const target = form.get('toMemberId');
    modal.date = form.get('date') || '';
    modal.toMemberId = target === 'external' ? null : target || undefined;
  } else {
    modal.secondRef = form.get('secondRef') || '';
  }
  modal.note = form.get('note') || '';
  modal.preview = null;
  modal.previewError = '';
  const payload = guardOperationPayload(formElement, operation);
  if (!payload) { modal.previewLoading = false; render(); return; }
  const requestKey = uid();
  const currentModal = modal;
  currentModal.previewRequestKey = requestKey;
  currentModal.previewLoading = true;
  render();
  try {
    const preview = operation === 'cession' ? await api.previewGuardCession(payload) : await api.previewGuardExchange(payload);
    if (modal !== currentModal || modal.previewRequestKey !== requestKey) return;
    modal.preview = preview;
    modal.previewLoading = false;
    render();
  } catch (error) {
    if (modal !== currentModal || modal.previewRequestKey !== requestKey) return;
    modal.previewError = error.message;
    modal.previewLoading = false;
    render();
  }
}

function guardImpactActivityName(type) {
  if (!type || type === 'no_assignment') return 'Sense assignació';
  if (type === 'management') return 'Gestió';
  return agenda(type)?.name || 'Agenda eliminada';
}

function guardInlineImpact(preview, loading = false, error = '') {
  if (loading) return '<section class="guard-inline-impact guard-inline-placeholder">Calculant impacte…</section>';
  if (error) return `<section class="guard-inline-impact guard-inline-error">${esc(error)}</section>`;
  if (!preview) return '<section class="guard-inline-impact guard-inline-placeholder">Selecciona una persona per veure l’impacte.</section>';
  const impact = preview.impact;
  const changed = impact.changedDates.map((item) => `<article><b>${fmtDate(item.date, { weekday: 'short', day: 'numeric', month: 'short' })}</b><div>${item.removed.map((change) => `<span class="removed">− ${guardPartyName(change.memberId)} · ${esc(guardImpactActivityName(change.type))}</span>`).join('')}${item.added.map((change) => `<span class="added">+ ${guardPartyName(change.memberId)} · ${esc(guardImpactActivityName(change.type))}</span>`).join('')}${item.vacanciesBefore.join('|') !== item.vacanciesAfter.join('|') ? `<span class="vacancy">Vacants: ${item.vacanciesBefore.length} → ${item.vacanciesAfter.length}</span>` : ''}</div></article>`).join('');
  return `<section class="guard-inline-impact"><div class="guard-impact-kpis"><span><b>${impact.moves}</b> canvis</span><span><b>${impact.vacanciesBefore}</b> → <b>${impact.vacanciesAfter}</b> vacants</span></div><div class="guard-impact-list">${changed || '<div class="empty-state">No cal modificar cap assignació.</div>'}</div></section>`;
}

function guardActionModal() {
  const guard = activeGuards().find((item) => item.id === modal.guardId);
  if (!guard) return '';
  const member = person(guard.memberId);
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small guard-action-modal" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">GUÀRDIA</div><h2>Gestiona la guàrdia</h2><div class="muted">${esc(member?.name || '—')} · ${fmtDate(guard.date, { weekday: 'long', day: 'numeric', month: 'long' })}</div></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body guard-action-options"><button type="button" class="guard-action-option" data-action="open-guard-cession" data-guard-id="${guard.id}"><b>Cedeix</b><span>Canvia el responsable d’aquesta guàrdia.</span></button><button type="button" class="guard-action-option" data-action="open-guard-exchange" data-guard-id="${guard.id}"><b>Intercanvia</b><span>Permuta-la amb una altra guàrdia.</span></button></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button></div></section></div>`;
}

function guardCessionModal() {
  const guard = modal.guardId ? activeGuards().find((item) => item.id === modal.guardId) : null;
  const sourceName = guard ? person(guard.memberId)?.name || '—' : 'Exterior';
  const dateValue = guard?.date || modal.date || '';
  const selectedTarget = Object.hasOwn(modal, 'toMemberId') ? (modal.toMemberId ?? 'external') : '';
  const dateField = guard
    ? `<div class="field"><label>Data de la guàrdia</label><div class="guard-fixed-date">${fmtDate(guard.date, { weekday: 'long', day: 'numeric', month: 'long' })}</div><input type="hidden" name="date" value="${guard.date}"></div>`
    : `<div class="field"><label>Data de la guàrdia</label><input type="date" name="date" required value="${dateValue}"></div>`;
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small guard-operation-modal" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">CESSIÓ DE GUÀRDIA</div><h2>${guard ? 'Canvia el responsable' : 'Entrada des de l’exterior'}</h2><div class="muted">Origen: ${esc(sourceName)}</div></div><button class="icon-button" data-action="close-modal">×</button></div><form id="guard-cession-form"><input type="hidden" name="guardId" value="${guard?.id || ''}"><div class="modal-body"><div class="form-grid">${dateField}<div class="field"><label>Nou responsable</label><select name="toMemberId" required>${guardMemberOptions(selectedTarget, Boolean(guard), guard?.memberId || '')}</select></div></div>${guardInlineImpact(modal.preview, modal.previewLoading, modal.previewError)}<div class="field"><label>Nota <span class="muted">opcional</span></label><textarea name="note" maxlength="500" rows="2" placeholder="Motiu o referència del canvi">${esc(modal.note || '')}</textarea></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal" ${modal.preview && !modal.previewLoading ? '' : 'disabled'}>Aplica el canvi</button></div></form></section></div>`;
}
function guardExchangeModal() {
  const first = activeGuards().find((item) => item.id === modal.guardId);
  const others = activeGuards().filter((item) => item.id !== first?.id);
  const selected = modal.secondRef || '';
  const second = others.find((item) => item.id === selected);
  const exchangeSummary = second ? `<div class="guard-exchange-summary"><span>${fmtDate(first?.date, { day: 'numeric', month: 'short' })}</span><b>${esc(person(first?.memberId)?.name || '—')}</b><i>⇄</i><span>${fmtDate(second.date, { day: 'numeric', month: 'short' })}</span><b>${esc(person(second.memberId)?.name || '—')}</b></div>` : '';
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small guard-operation-modal" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">INTERCANVI DE GUÀRDIES</div><h2>Permuta dues guàrdies</h2><div class="muted">${esc(person(first?.memberId)?.name || '—')} · ${first ? fmtDate(first.date, { day: 'numeric', month: 'long' }) : '—'}</div></div><button class="icon-button" data-action="close-modal">×</button></div><form id="guard-exchange-form"><input type="hidden" name="firstGuardId" value="${first?.id || ''}"><input type="hidden" name="firstDate" value="${first?.date || ''}"><div class="modal-body"><div class="field"><label>Intercanvia amb</label><select name="secondRef" required><option value="" disabled ${selected ? '' : 'selected'}>Selecciona una persona</option><option value="external" ${selected === 'external' ? 'selected' : ''}>Exterior</option>${others.map((item) => `<option value="${item.id}" ${selected === item.id ? 'selected' : ''}>${fmtDate(item.date, { day: 'numeric', month: 'short' })} · ${esc(person(item.memberId)?.name || '—')}</option>`).join('')}</select></div>${exchangeSummary}${guardInlineImpact(modal.preview, modal.previewLoading, modal.previewError)}${selected === 'external' ? '<div class="guard-operation-note">La guàrdia sortirà del calendari intern. El canvi quedarà registrat a l’històric.</div>' : ''}<div class="field"><label>Nota <span class="muted">opcional</span></label><textarea name="note" maxlength="500" rows="2">${esc(modal.note || '')}</textarea></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal" ${modal.preview && !modal.previewLoading ? '' : 'disabled'}>Aplica el canvi</button></div></form></section></div>`;
}
function colorControl(kind, color) { const assigned = Boolean(color); return `<div class="automatic-color"><span class="color-swatch" data-color-swatch style="--automatic-color:${color || '#39413c'}"></span><div><b>Color automàtic</b><span>${assigned ? (kind === 'member' ? 'Pastel per distingir persones' : 'Saturat per distingir agendes') : 'El backend l’assignarà en desar'}</span></div>${assigned ? `<button type="button" class="button ghost small" data-action="random-color" data-color-kind="${kind}">Nou color aleatori</button>` : ''}</div>`; }
function coverageFields(item) { return `<div class="coverage-block"><div><span class="label">Cobertura ordinària</span><span class="muted">Places necessàries per dia</span></div><div class="coverage-fields">${[1, 2, 3, 4, 5].map((day) => `<label><span>${DAYS_SHORT[day - 1]}</span><input type="number" name="coverage-${day}" min="0" max="30" value="${item?.coverage ? Number(item.coverage[String(day)] || 0) : item ? state.coverage[day]?.[item.id] || 0 : 0}" /></label>`).join('')}</div></div>`; }
function agendaRecurrenceRow(rule = { ordinal: 1, weekday: 1, slots: 1 }) {
  return `<div class="agenda-recurrence-row"><select name="recurrence-ordinal" aria-label="Ordre del dia">${[1, 2, 3, 4, 5].map((ordinal) => `<option value="${ordinal}" ${Number(rule.ordinal) === ordinal ? 'selected' : ''}>${ordinalLabel(ordinal)}</option>`).join('')}</select><select name="recurrence-weekday" aria-label="Dia de la setmana">${DAYS.map((day, index) => `<option value="${index + 1}" ${Number(rule.weekday) === index + 1 ? 'selected' : ''}>${day}</option>`).join('')}</select><span>de cada mes</span><button type="button" class="icon-button danger-icon" data-action="remove-agenda-recurrence" aria-label="Elimina regla">×</button></div>`;
}
function agendaRecurrencesFields(item) {
  const rules = item?.recurrences || [];
  return `<div class="agenda-recurrences-block"><div class="agenda-recurrences-head"><div><span class="label">Regles especials</span><span class="muted">Demanda addicional recurrent</span></div><button type="button" class="button secondary small" data-action="add-agenda-recurrence">+ Afegeix opció</button></div><div id="agenda-recurrences">${rules.map(agendaRecurrenceRow).join('') || '<div class="empty-agenda-recurrences muted">Encara no hi ha regles especials.</div>'}</div></div>`;
}
function fixedRuleAgendaIds(allowed, weekdayValue) {
  return allowed.filter((id) => {
    const item = agenda(id);
    return Number(state.coverage[weekdayValue]?.[id] || 0) > 0
      || item?.recurrences?.some((rule) => Number(rule.weekday) === Number(weekdayValue));
  });
}
function defaultFixedRule(allowed, available) { for (const weekdayValue of available) { const agendas = fixedRuleAgendaIds(allowed, weekdayValue); if (agendas.length) return { weekday: weekdayValue, type: agendas[0] }; } return { weekday: available[0] || 1, type: '' }; }
function sharedRulePeers(memberId, agendaId, weekdayValue) { return state.team.filter((member) => member.id !== memberId && member.fixedRules.some((rule) => rule.type === agendaId && Number(rule.weekday) === Number(weekdayValue))); }
function fixedRuleSharedIndicator(memberId, agendaId, weekdayValue) { const peers = sharedRulePeers(memberId, agendaId, weekdayValue); if (!peers.length) return ''; const prefix = state.language === 'es' ? 'También se aplica a' : 'També s’aplica a'; const label = `${prefix} ${peers.map((peer) => peer.name).join(', ')}`; return `<span class="fixed-rule-shared-indicator" role="img" tabindex="0" aria-label="${esc(label)}"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="7" cy="7" r="2.5"/><circle cx="14" cy="8" r="2"/><path d="M2.8 16c.3-3 1.8-4.6 4.3-4.6s4 1.6 4.3 4.6M11.4 12.2c.7-.7 1.6-1 2.7-1 2 0 3.1 1.3 3.3 3.7"/></svg><span class="fixed-rule-shared-tooltip" aria-hidden="true">${esc(label)}</span></span>`; }
function fixedRuleRow(rule, allowed, available) { const value = rule || defaultFixedRule(allowed, available); const agendaIds = fixedRuleAgendaIds(allowed, value.weekday); return `<div class="fixed-rule-row"><select name="rule-weekday">${available.map((weekdayValue) => `<option value="${weekdayValue}" ${value.weekday === weekdayValue ? 'selected' : ''}>${DAYS[weekdayValue - 1]}</option>`).join('')}</select><select name="rule-type" ${agendaIds.length ? '' : 'disabled'}>${typeOptions(value.type, agendaIds)}</select><span class="fixed-rule-shared-slot">${fixedRuleSharedIndicator(modal?.id, value.type, value.weekday)}</span><button type="button" class="icon-button danger-icon" data-action="remove-fixed-rule" aria-label="Elimina regla">×</button></div>`; }
function refreshFixedRulePeers(row) { const agendaId = $('[name="rule-type"]', row).value; const weekdayValue = Number($('[name="rule-weekday"]', row).value); $('.fixed-rule-shared-slot', row).innerHTML = fixedRuleSharedIndicator(modal?.id, agendaId, weekdayValue); }
function refreshFixedRuleType(row, formElement) { const selected = $('[name="rule-type"]', row); const allowed = $$('[name="allowed"]:checked', formElement).map((item) => item.value); const agendaIds = fixedRuleAgendaIds(allowed, Number($('[name="rule-weekday"]', row).value)); const previous = selected.value; selected.innerHTML = typeOptions(previous, agendaIds); selected.disabled = !agendaIds.length; rebuildEnhancedSelect(selected); refreshFixedRulePeers(row); }
function generationCondition(item, kind) {
  const member = person(item.memberId); const label = kind === 'guard' ? `Guàrdia · ${item.date}` : `Vacances · ${item.start}${item.end !== item.start ? ` — ${item.end}` : ''}`;
  return `<div class="generation-condition"><span><b>${esc(member?.name || '—')}</b><small>${esc(label)}</small></span><button type="button" class="icon-button danger-icon" data-remove-generation-condition="${kind}:${item.id}" aria-label="Elimina condicionant">×</button></div>`;
}
function emptyMemberOptions() { return `<option value="">Selecciona una persona</option>${memberOptions()}`; }
function generationDateBounds() {
  if (modal?.type === 'generation') {
    if (modal.periodMode === 'custom') return { start: modal.startDate || '', end: modal.endDate || '' };
    return { start: `${modal.startMonth}-01`, end: endOfMonth(`${modal.startMonth}-01`) };
  }
  if (modal?.startDate && modal?.endDate) return { start: modal.startDate, end: modal.endDate };
  return { start: `${modal.startMonth}-01`, end: endOfMonth(`${modal.endMonth}-01`) };
}

function generationPeriodError(bounds = generationDateBounds()) {
  if (!bounds.start || !bounds.end) return 'Completa la data inicial i la final.';
  if (bounds.end < bounds.start) return 'La data final no pot ser anterior a la inicial.';
  return monthKey(bounds.start) !== monthKey(bounds.end) ? 'Les dues dates han de pertànyer al mateix mes.' : '';
}

function generationPeriodPayload() {
  const bounds = generationDateBounds();
  return { startMonth: monthKey(bounds.start), endMonth: monthKey(bounds.end), startDate: bounds.start, endDate: bounds.end };
}
function conditionDateHint() { const bounds = generationDateBounds(); return `${state.language === 'es' ? 'Fechas entre' : 'Dates entre'} ${fmtDate(bounds.start, { day: 'numeric', month: 'short', year: 'numeric' })} ${state.language === 'es' ? 'y' : 'i'} ${fmtDate(bounds.end, { day: 'numeric', month: 'short', year: 'numeric' })}.`; }
function monthYearPicker(field, value, label) {
  const [selectedYear, selectedMonth] = value.split('-').map(Number); const currentYear = new Date().getFullYear(); const years = [...new Set([...Array.from({ length: 8 }, (_, index) => currentYear - 1 + index), selectedYear, Number(modal.startMonth.slice(0, 4)), Number(modal.endMonth.slice(0, 4))])].sort((a, b) => a - b);
  const months = Array.from({ length: 12 }, (_, index) => { const month = index + 1; const name = new Intl.DateTimeFormat(state.language === 'es' ? 'es-ES' : 'ca-ES', { month: 'long' }).format(new Date(Date.UTC(2026, index, 1))); return `<option value="${String(month).padStart(2, '0')}" ${month === selectedMonth ? 'selected' : ''}>${name.charAt(0).toUpperCase()}${name.slice(1)}</option>`; }).join('');
  return `<div class="field"><label>${label}</label><div class="month-year-picker" data-month-picker="${field}"><select data-month-part="month" aria-label="${label}">${months}</select><select data-month-part="year" aria-label="Any de ${label.toLowerCase()}">${years.map((year) => `<option value="${year}" ${year === selectedYear ? 'selected' : ''}>${year}</option>`).join('')}</select><input type="hidden" name="${field}" value="${value}" /></div></div>`;
}
const GENERATION_LOADING_PHRASES = {
  ca: [
    'Negociant amb {name}',
    'Batallant amb el calendari de {name}',
    'Suplicant una mica de flexibilitat a {name}',
    'Convencent {name} que tot acabarà encaixant',
    'Prometent un cafè a {name}',
    'Fent Tetris amb les agendes de {name}',
    'Quadrant el sudoku de {name}',
    'Consultant l’oracle amb {name}',
    'Revisant la lletra petita de {name}',
    'Demanant una última concessió a {name}',
    'Comptant mitges agendes amb {name}',
    'Buscant un divendres amable per a {name}',
    'Protegint els dies telemàtics de {name}',
    'Desfent un nus impossible amb {name}',
    'Comparant calendaris amb {name}',
    'Intentant que tot encaixi per a {name}',
    'Repartint dilluns amb {name}',
    'Evitant una reunió infinita amb {name}',
    'Buscant la combinació més justa per a {name}',
    'Recalculant el pla mestre de {name}',
    'Movent peces amb molta cura per a {name}',
    'Comprovant que {name} no tingui dos llocs alhora',
    'Reservant una mica de paciència per a {name}',
    'Preguntant a {name} si aquest dimecres li va bé',
  ],
  es: [
    'Negociando con {name}',
    'Peleando con el calendario de {name}',
    'Suplicándole un poco de flexibilidad a {name}',
    'Convenciendo a {name} de que todo acabará encajando',
    'Prometiéndole un café a {name}',
    'Haciendo Tetris con las agendas de {name}',
    'Cuadrando el sudoku de {name}',
    'Consultando el oráculo con {name}',
    'Revisando la letra pequeña de {name}',
    'Pidiendo una última concesión a {name}',
    'Contando agendas parciales con {name}',
    'Buscando un viernes amable para {name}',
    'Protegiendo los días telemáticos de {name}',
    'Deshaciendo un nudo imposible con {name}',
    'Comparando calendarios con {name}',
    'Intentando que todo encaje para {name}',
    'Repartiendo lunes con {name}',
    'Evitando una reunión infinita con {name}',
    'Buscando la combinación más justa para {name}',
    'Recalculando el plan maestro de {name}',
    'Moviendo piezas con mucho cuidado para {name}',
    'Comprobando que {name} no esté en dos sitios a la vez',
    'Reservando un poco de paciencia para {name}',
    'Preguntándole a {name} si ese miércoles le va bien',
  ],
};

function nextGenerationLoadingMessage() {
  const phrases = GENERATION_LOADING_PHRASES[state.language === 'es' ? 'es' : 'ca'];
  let phraseIndex = Math.floor(Math.random() * phrases.length);
  if (phrases.length > 1 && phraseIndex === modal.loadingPhraseIndex) phraseIndex = (phraseIndex + 1) % phrases.length;
  const names = activeTeam().map((member) => member.name).filter(Boolean);
  const candidates = names.length > 1 ? names.filter((name) => name !== modal.loadingMember) : names;
  const memberName = candidates[Math.floor(Math.random() * candidates.length)] || (state.language === 'es' ? 'el equipo' : 'l’equip');
  modal.loadingPhraseIndex = phraseIndex;
  modal.loadingMember = memberName;
  return phrases[phraseIndex].replace('{name}', memberName);
}

function startGenerationLoadingAnimation() {
  return window.setInterval(() => {
    if (!modal?.busy) return;
    modal.loadingPhrase = nextGenerationLoadingMessage();
    const message = document.querySelector('[data-generation-loading-message]');
    if (!message) return;
    message.textContent = modal.loadingPhrase;
    message.animate?.(
      [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 360, easing: 'ease-out' },
    );
  }, 2400);
}

function generationLoadingModal() {
  const es = state.language === 'es';
  return `<div class="modal-backdrop"><section class="modal-card modal-small generation-loading-modal" role="dialog" aria-modal="true" aria-labelledby="generation-loading-title" aria-describedby="generation-loading-help"><div class="generation-loading-body"><div class="generation-loading-orbit" aria-hidden="true"><i></i><i></i><i></i></div><div class="card-kicker">${es ? 'OPTIMIZANDO' : 'OPTIMITZANT'}</div><h2 id="generation-loading-title">${es ? 'Preparando el calendario' : 'Preparant el calendari'}</h2><p data-generation-loading-message aria-live="polite">${esc(modal.loadingPhrase)}</p><div class="generation-loading-track" aria-hidden="true"><i></i></div><small id="generation-loading-help">${es ? 'Puede tardar unos minutos. No cierres esta ventana.' : 'Pot trigar uns minuts. No tanquis aquesta finestra.'}</small></div></section></div>`;
}

function generationModal() {
  if (modal.busy) return generationLoadingModal();
  const guards = modal.guards || []; const absences = modal.absences || [];
  const guardItems = guards.map((item) => generationCondition(item, 'guard')).join('') + guardImportReview(); const absenceItems = absences.map((item) => generationCondition(item, 'absence')).join('');
  const bounds = generationDateBounds();
  const monthMode = modal.periodMode !== 'custom';
  const periodControls = `<div class="generation-objective-options generation-period-options"><label><input type="radio" name="periodMode" value="month" ${monthMode ? 'checked' : ''}/><span><b>Mes complet</b><small>Selecciona directament un mes i un any.</small></span></label><label><input type="radio" name="periodMode" value="custom" ${monthMode ? '' : 'checked'}/><span><b>Període personalitzat</b><small>Escull manualment les dates dins d’un únic mes.</small></span></label></div><div class="period-fields ${monthMode ? 'single' : ''}">${monthMode ? monthYearPicker('generationMonth', modal.startMonth, 'Mes a generar') : `<div class="field"><label>Data inicial</label><input type="date" name="generationStartDate" value="${modal.startDate}" required /></div><span>→</span><div class="field"><label>Data final</label><input type="date" name="generationEndDate" value="${modal.endDate}" min="${modal.startDate}" max="${modal.startDate ? endOfMonth(modal.startDate) : ''}" required /></div>`}</div><p class="period-help">${monthMode ? 'Es generarà únicament el mes seleccionat.' : 'Les dues dates han de pertànyer al mateix mes natural.'}</p>`;
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-large generation-modal" role="dialog" aria-modal="true" aria-labelledby="generation-title"><div class="modal-head"><div><div class="card-kicker">NOU PERÍODE</div><h2 id="generation-title">Genera el calendari</h2><div class="muted">Defineix el període i les incidències noves.</div></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><form id="generation-form"><div class="modal-body"><section class="generation-period"><div class="step-number">1</div><div>${periodControls}</div></section>${modal.conflict ? `<div class="generation-warning"><b>${modal.overlap ? 'Aquest període ja té esdeveniments' : 'No es pot generar aquest període'}</b><span>${esc(modal.conflict)}</span>${modal.overlap ? '<button type="button" class="button danger small" data-action="confirm-generation-overwrite">Regenera només aquest període</button>' : ''}</div>` : ''}<section class="generation-conditions"><div class="step-title"><span class="step-number">2</span><div><h3>Condicionants variables</h3><p>Les guardies i absències existents s’apliquen automàticament. Aquí només cal afegir-ne de noves.</p></div></div><div class="condition-editor"><div class="condition-box"><div class="condition-box-head"><h4>Guàrdies</h4><div class="condition-box-actions"><button type="button" class="button ghost small" data-action="export-guards-template">Exporta plantilla</button><label class="file-import button ghost small">Importa XLS<input type="file" accept=".xls,.xlsx" data-action="import-guards-file" /></label></div></div><div class="condition-inputs guard-inputs"><div class="field"><label>Persona</label><select name="guard-member">${emptyMemberOptions()}</select></div><div class="field"><label>Data</label><input type="date" name="guard-date" min="${bounds.start}" max="${bounds.end}" /></div><button type="button" class="button secondary small" data-action="add-generation-guard">Afegeix</button></div><div class="condition-list">${guardItems || '<span class="muted">Sense guàrdies noves.</span>'}</div><p class="import-hint">${conditionDateHint()} XLS: ${state.language === 'es' ? 'columnas' : 'columnes'} <b>Persona</b> i <b>Data</b>.</p></div><div class="condition-box"><div class="condition-box-head"><h4>Vacances puntuals</h4><div class="condition-box-actions"><button type="button" class="button ghost small" data-action="export-absences-template">Exporta plantilla</button><label class="file-import button ghost small">Importa XLS<input type="file" accept=".xls,.xlsx" data-action="import-absences-file" /></label></div></div><div class="condition-inputs absence-inputs"><div class="field"><label>Persona</label><select name="absence-member">${emptyMemberOptions()}</select></div><div class="field"><label>Inici</label><input type="date" name="absence-start" min="${bounds.start}" max="${bounds.end}" /></div><div class="field"><label>Final</label><input type="date" name="absence-end" min="${bounds.start}" max="${bounds.end}" /></div><button type="button" class="button secondary small" data-action="add-generation-absence">Afegeix</button></div><div class="condition-list">${absenceItems || '<span class="muted">Sense vacances puntuals noves.</span>'}</div><p class="import-hint">${conditionDateHint()} XLS: <b>Persona</b>, <b>Inici</b> i <b>Final</b>.</p></div></div>${modal.importNotice ? `<div class="import-notice">${esc(modal.importNotice)}</div>` : ''}</section></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal" ${modal.busy ? 'disabled' : ''}>Cancel·la</button><button type="button" class="button" data-action="submit-modal" ${modal.busy ? 'disabled' : ''}>${modal.busy ? 'Generant…' : 'Genera calendari'}</button></div></form></section></div>`;
}
function guardEditorModal() {
  const guards = modal.guards || []; const bounds = generationDateBounds();
  const guardItems = guards.map((item) => generationCondition(item, 'guard')).join('') + guardImportReview();
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-large generation-modal" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">GUÀRDIES</div><h2>Edita les guàrdies</h2><div class="muted">Són esdeveniments independents de les agendes. Només bloquegen el post-guàrdia.</div></div><button class="icon-button" data-action="close-modal">×</button></div><form id="guard-editor-form"><div class="modal-body"><section class="generation-conditions"><div class="condition-editor"><div class="condition-box"><div class="condition-box-head"><h4>Guàrdies</h4><div class="condition-box-actions"><button type="button" class="button ghost small" data-action="export-guards-template">Exporta plantilla</button><label class="file-import button ghost small">Importa XLS<input type="file" accept=".xls,.xlsx" data-action="import-guards-file" /></label></div></div><div class="condition-inputs guard-inputs"><div class="field"><label>Persona</label><select name="guard-member">${emptyMemberOptions()}</select></div><div class="field"><label>Data</label><input type="date" name="guard-date" min="${bounds.start}" max="${bounds.end}" /></div><button type="button" class="button secondary small" data-action="add-generation-guard">Afegeix</button></div><div class="condition-list">${guardItems || '<span class="muted">Sense guàrdies.</span>'}</div><p class="import-hint">${conditionDateHint()}</p></div></div>${modal.importNotice ? `<div class="import-notice">${esc(modal.importNotice)}</div>` : ''}</section></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal">Desa guàrdies</button></div></form></section></div>`;
}
function memberModal(member = null) {
  const allowed = member?.allowedTypes || state.agendas.map((item) => item.id);
  const memberColor = modal?.color || member?.color || '';
  const managementEnabled = Number(member?.managementQuota || 0) > 0;
  const tab = modal.tab || 'general';
  const pattern = memberWorkPattern(member);
  const available = [...new Set(pattern.weeks.flatMap((week) => week.workingDays))].sort((a, b) => a - b);
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-large" role="dialog" aria-modal="true" aria-labelledby="member-modal-title"><div class="modal-head"><div><div class="card-kicker">EQUIP</div><h2 id="member-modal-title">${member?.id ? 'Edita membre' : 'Nou membre'}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><form id="member-form"><input type="hidden" name="id" value="${member?.id || ''}" /><div class="modal-tabs"><button type="button" class="${tab === 'general' ? 'active' : ''}" data-modal-tab="general">Perfil general</button><button type="button" class="${tab === 'vacations' ? 'active' : ''}" data-modal-tab="vacations">Vacances <span class="tab-count">${modal.vacationDates?.length || 0}</span></button><button type="button" class="${tab === 'rules' ? 'active' : ''}" data-modal-tab="rules">Regles fixes <span class="tab-count">${member?.fixedRules.length || 0}</span></button></div><div class="modal-body"><div class="tab-panel ${tab === 'general' ? 'active' : ''}" data-tab-panel="general">${colorControl('member', memberColor)}<label class="member-active-toggle"><input type="checkbox" name="active" ${member?.active === false ? '' : 'checked'} /><span></span><div><b>Perfil actiu</b><small>Les persones inactives no entren en la generació del calendari.</small></div></label><div class="form-grid"><div class="field"><label>Nom i cognoms</label><input name="name" required value="${esc(member?.name || '')}" placeholder="Ex. Núria Prat" /></div><div class="field"><label>Correu</label><input name="email" type="email" required value="${esc(member?.email || '')}" placeholder="nom@hospital.cat" /></div></div>${workPatternFields(member)}<div class="field agenda-capabilities"><span class="label">Agendes habilitades</span><small class="agenda-preference-help">Afegeix ♥ o 👎 per indicar preferències. Sense reacció significa indiferent.</small>${typeChecks('allowed', allowed, member?.agendaPreferences || {})}</div><div class="field management-settings"><label class="check management-check"><input type="checkbox" name="managementEnabled" ${managementEnabled ? 'checked' : ''}>Fa gestió</label><div class="management-quota ${managementEnabled ? '' : 'is-hidden'}" data-management-quota><label>Dies de gestió al mes</label><input name="quota" type="number" min="1" max="5" value="${managementEnabled ? member?.managementQuota || 1 : 1}" ${managementEnabled ? 'required' : 'disabled'} /></div></div></div><div class="tab-panel ${tab === 'vacations' ? 'active' : ''}" data-tab-panel="vacations">${memberVacationCalendar()}</div><div class="tab-panel ${tab === 'rules' ? 'active' : ''}" data-tab-panel="rules"><div class="panel-intro"><div><h3>Regles fixes</h3><p class="muted">Reserva una agenda recurrente per dia de la setmana.</p></div><button type="button" class="button secondary small" data-action="add-fixed-rule">Afegeix regla</button></div><div id="fixed-rules">${(member?.fixedRules || []).map((rule) => fixedRuleRow(rule, allowed, available)).join('') || '<div class="empty-rules muted">Encara no hi ha regles fixes.</div>'}</div></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal">Desa membre</button></div></form></section>${modal.saved ? '<div class="save-confirmation" role="status"><span>✓</span><div><b>Perfil desat</b><small>Els canvis s’han guardat correctament.</small></div></div>' : ''}</div>`;
}
function deleteMemberModal(member) { return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker danger-text">ACCIÓ DEFINITIVA</div><h2>Elimina ${esc(member.name)}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><form id="delete-member-form"><input type="hidden" name="id" value="${member.id}" /><div class="modal-body"><div class="deletion-warning"><b>Es conservarà l’històric</b><span>S’eliminaran les assignacions i els condicionants des d’avui, juntament amb les regles, guàrdies i absències futures associades.</span></div><p>Aquesta persona deixarà d’aparèixer a l’equip. Escriu <b>ELIMINAR</b> per confirmar.</p><div class="field"><label>Paraula de confirmació</label><input name="confirmation" autocomplete="off" required placeholder="ELIMINAR" /></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button danger" data-action="submit-modal">Elimina definitivament</button></div></form></section></div>`; }
function agendaRelatedRules(agendaId) { return state.team.flatMap((member) => member.fixedRules.filter((rule) => rule.type === agendaId).map((rule) => ({ ...rule, member }))).sort((left, right) => Number(left.weekday) - Number(right.weekday) || left.member.name.localeCompare(right.member.name)); }
function agendaRulesInfoButton(item) { if (!item?.id) return ''; const count = agendaRelatedRules(item.id).length; return `<div class="agenda-related-rules"><button type="button" class="button ghost small" data-action="open-agenda-rules-info" data-agenda-id="${item.id}">ⓘ Regles relacionades · ${count}</button><small>Consulta les persones i dies vinculats a aquesta agenda.</small></div>`; }
function agendaModal(item = null) { const agendaColor = modal?.color || item?.color || ''; const shift = item?.shift || 'morning'; const load = item?.loadPercentage || 100; return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-agenda" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">AGENDES</div><h2>${item ? 'Edita agenda' : 'Nova agenda'}</h2></div><button class="icon-button" data-action="close-modal">×</button></div><form id="agenda-form"><input type="hidden" name="id" value="${item?.id || ''}" /><div class="modal-body">${colorControl('agenda', agendaColor)}<div class="form-grid agenda-main-fields"><div class="field"><label>Nom</label><input name="name" required value="${esc(item?.name || '')}" placeholder="Ex. Ecografia avançada" /></div><div class="field"><label>Prioritat</label><select name="priority" required>${priorityOptions(item?.priority ?? 3)}</select></div></div><div class="form-grid agenda-location-fields"><div class="field"><label>Hospital</label><select name="hospitalId" required><option value="" disabled ${item?.hospitalId ? '' : 'selected'}>Selecciona un hospital</option>${hospitalOptions(item?.hospitalId)}</select>${state.hospitals.length ? '' : '<small class="form-error">Afegeix primer un hospital des de Configuració.</small>'}</div><div class="field"><span class="label">Torn</span><div class="shift-switch"><label><input type="radio" name="shift" value="morning" required ${shift === 'morning' ? 'checked' : ''}><span>Matí</span></label><label><input type="radio" name="shift" value="afternoon" required ${shift === 'afternoon' ? 'checked' : ''}><span>Tarda</span></label></div></div></div><div class="form-grid agenda-mode-fields"><div class="field"><span class="label">Càrrega</span><div class="shift-switch"><label><input type="radio" name="loadPercentage" value="100" required ${load === 100 ? 'checked' : ''}><span>Completa</span></label><label><input type="radio" name="loadPercentage" value="50" required ${load === 50 ? 'checked' : ''}><span>Parcial</span></label></div></div><div class="field check-field"><label class="check"><input name="telematic" type="checkbox" ${item?.telematic ? 'checked' : ''}>Telemàtic</label></div></div>${coverageFields(item)}${agendaRecurrencesFields(item)}${agendaRulesInfoButton(item)}</div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal">Desa agenda</button></div></form></section></div>`; }
function deleteAgendaModal(item) { return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker danger-text">ELIMINA AGENDA</div><h2>${esc(item.name)}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body"><div class="deletion-warning"><b>Es conservaran els esdeveniments passats</b><span>S’eliminaran les assignacions d’aquesta agenda des d’avui. També desapareixerà dels perfils, la cobertura i les regles fixes.</span></div></div><div class="modal-actions"><button class="button ghost" data-action="close-modal">Cancel·la</button><button class="button danger" data-action="confirm-delete-agenda" data-agenda-id="${item.id}">Elimina agenda</button></div></section></div>`; }
function agendaRuleConflictModal() {
  const item = agenda(modal.id); const rules = modal.rules || [];
  return `<div class="modal-backdrop"><section class="modal-card modal-small" role="alertdialog" aria-modal="true" aria-labelledby="agenda-conflict-title"><div class="modal-head"><div><div class="card-kicker danger-text">REGLES AFECTADES</div><h2 id="agenda-conflict-title">No es pot aplicar directament</h2></div></div><div class="modal-body"><div class="deletion-warning"><b>La nova cobertura de ${esc(item?.name || modal.payload.name)} elimina aquestes regles fixes</b><span>Revisa-les abans de continuar. Si confirmes, l’agenda i les regles s’actualitzaran alhora.</span></div><div class="conflicting-rule-list">${rules.map((rule) => `<div><span><b>${esc(rule.memberName)}</b><small>${DAYS[Number(rule.weekday) - 1]} · ${esc(rule.agendaName)}</small></span><strong>${DAYS_SHORT[Number(rule.weekday) - 1]}</strong></div>`).join('')}</div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="return-agenda-edit">Torna a editar</button><button type="button" class="button danger" data-action="confirm-agenda-rule-deletion">Esborra regles i desa</button></div></section></div>`;
}
function sharedFixedRuleConfirmModal() {
  const rules = modal.rules || [];
  return `<div class="modal-backdrop"><section class="modal-card modal-small" role="alertdialog" aria-modal="true" aria-labelledby="shared-rule-title"><div class="modal-head"><div><div class="card-kicker danger-text">REGLA COMPARTIDA</div><h2 id="shared-rule-title">Aquesta regla ja existeix</h2></div></div><div class="modal-body"><div class="deletion-warning neutral"><b>La nova regla es compartirà</b><span>Quan hi hagi menys places que persones disponibles, el planificador escollirà entre elles.</span></div><div class="conflicting-rule-list">${rules.map((rule) => `<div><span><b>${esc(rule.agendaName)} · ${DAYS[Number(rule.weekday) - 1]}</b><small>També s’aplica a ${rule.people.map((person) => esc(person.name)).join(', ')}</small></span><strong>${DAYS_SHORT[Number(rule.weekday) - 1]}</strong></div>`).join('')}</div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="return-member-edit">Torna a editar</button><button type="button" class="button" data-action="confirm-shared-fixed-rules">Confirma i desa</button></div></section></div>`;
}
function agendaRulesInfoModal() {
  const item = agenda(modal.id); const rules = agendaRelatedRules(modal.id);
  return `<div class="modal-backdrop"><section class="modal-card modal-small" role="dialog" aria-modal="true" aria-labelledby="agenda-rules-title"><div class="modal-head"><div><div class="card-kicker">REGLES RELACIONADES</div><h2 id="agenda-rules-title">${esc(item.name)}</h2></div></div><div class="modal-body">${rules.length ? `<div class="agenda-rule-info-list">${rules.map((rule) => `<div><span><b>${esc(rule.member.name)}</b><small>${rule.member.active ? 'Perfil actiu' : 'Perfil inactiu'}</small></span><strong>${DAYS[Number(rule.weekday) - 1]}</strong></div>`).join('')}</div>` : '<div class="empty-state">Aquesta agenda no té cap regla relacionada.</div>'}</div><div class="modal-actions"><button type="button" class="button" data-action="return-agenda-edit">Torna a l’agenda</button></div></section></div>`;
}
function manualHospitalModal() { return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">CENTRE MANUAL</div><h2>${esc(modal.name)}</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body"><div class="deletion-warning neutral"><b>Localització desconeguda</b><span>El centre s’afegirà sense àrea al mapa. Es podrà usar a les agendes, però no es podrà clicar ni centrar al mapa.</span></div></div><div class="modal-actions"><button class="button ghost" data-action="close-modal">Cancel·la</button><button class="button" data-action="confirm-manual-hospital">Afegeix centre</button></div></section></div>`; }
function deletionConfirmationWord() { return state.language === 'es' ? 'BORRAR' : 'ESBORRAR'; }
function clearCalendarModal() { const word = deletionConfirmationWord(); const scope = state.language === 'es' ? 'Se eliminarán todas las asignaciones y vacantes entre ambas fechas. Las guardias y ausencias se conservarán.' : 'S’eliminaran totes les assignacions i vacants entre les dues dates. Les guàrdies i absències es conservaran.'; return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker danger-text">ESBORRA PERÍODE</div><h2>Contingut del calendari</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><form id="clear-calendar-form"><div class="modal-body"><div class="deletion-warning"><b>Aquesta acció no es pot desfer</b><span>${scope}</span></div><div class="form-grid"><div class="field"><label>Data d’inici</label><input type="date" name="startDate" required value="${modal.startDate}" /></div><div class="field"><label>Data final</label><input type="date" name="endDate" required value="${modal.endDate}" /></div></div><div class="field deletion-confirmation"><label>${state.language === 'es' ? `Escribe ${word} para confirmar` : `Escriu ${word} per confirmar`}</label><input name="confirmation" required autocomplete="off" spellcheck="false" /></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button danger" data-action="submit-modal">Esborra període</button></div></form></section></div>`; }
function generationUnassignedModal() { const es = state.language === 'es'; const days = modal.count; const people = modal.people; return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small" role="dialog" aria-modal="true" aria-labelledby="unassigned-title"><div class="modal-head"><div><div class="card-kicker">${es ? 'PERÍODO GENERADO' : 'PERÍODE GENERAT'}</div><h2 id="unassigned-title">${es ? 'Hay días sin asignación' : 'Hi ha dies sense assignació'}</h2></div><button class="icon-button" data-action="close-modal" aria-label="${es ? 'Cerrar' : 'Tanca'}">×</button></div><div class="modal-body"><div class="deletion-warning neutral"><b>${people} ${es ? (people === 1 ? 'persona afectada' : 'personas afectadas') : (people === 1 ? 'persona afectada' : 'persones afectades')}</b><span>${es ? `El período contiene ${days} ${days === 1 ? 'día-persona' : 'días-persona'} sin agenda. Se muestran en rojo como “Sin asignación”.` : `El període conté ${days} ${days === 1 ? 'dia-persona' : 'dies-persona'} sense agenda. Es mostren en vermell com a “Sense assignació”.`}</span></div></div><div class="modal-actions"><button class="button" data-action="close-modal">${es ? 'Entendido' : 'Entesos'}</button></div></section></div>`; }
function fixedAssignmentWarningModal() {
  const item = calendarEvents().find((assignment) => assignment.id === modal.id);
  const member = person(item?.memberId);
  const itemAgenda = agenda(item?.type);
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small modal-fixed-warning" role="alertdialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">ASSIGNACIÓ FIXA</div><h2>Vols canviar-la?</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body"><div class="fixed-assignment-warning"><span class="fixed-warning-icon" aria-hidden="true">!</span><div><b>${esc(member?.name || '—')} · ${esc(itemAgenda?.name || '—')}</b><span>Aquesta assignació prové d’una regla fixa. Si continues, el canvi només afectarà aquest dia; la regla recurrent del perfil es conservarà.</span></div></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="confirm-fixed-exchange">Sí, continua</button></div></section></div>`;
}

function recoveryCodeModal() {
  if (modal.code) {
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small" role="dialog" aria-modal="true" aria-labelledby="recovery-code-title"><div class="modal-head"><div><div class="card-kicker">COMPTE · ${esc(state.account?.username || '')}</div><h2 id="recovery-code-title">Clau de recuperació</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body"><p class="muted">Desa-la ara. La clau anterior ja no és vàlida.</p><code class="recovery-code" id="account-recovery-code">${esc(modal.code)}</code></div><div class="modal-actions"><button type="button" class="button ghost" data-action="download-recovery-code">Descarrega</button><button type="button" class="button" data-action="copy-recovery-code">Copia la clau</button></div></section></div>`;
  }
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-small modal-fixed-warning" role="alertdialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">CLAU DE RECUPERACIÓ</div><h2>Generar una clau nova?</h2></div><button class="icon-button" data-action="close-modal" aria-label="Tanca">×</button></div><div class="modal-body"><div class="fixed-assignment-warning"><span class="fixed-warning-icon" aria-hidden="true">!</span><div><b>La clau actual no es pot mostrar per seguretat.</b><span>En generar-ne una de nova, la clau anterior deixarà de funcionar.</span></div></div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="generate-recovery-code">Genera i mostra</button></div></section></div>`;
}

function guideOnboardingModal() {
  const es = state.language === 'es';
  const g = (ca, translated) => es ? translated : ca;
  return `<div class="modal-backdrop"><section class="modal-card modal-small guide-onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="guide-onboarding-title"><div class="modal-head"><div><div class="card-kicker">${g('BENVINGUDA A PINENDAR', 'BIENVENIDA A PINENDAR')}</div><h2 id="guide-onboarding-title">${g('Vols veure com funciona?', '¿Quieres ver cómo funciona?')}</h2></div></div><div class="modal-body"><div class="guide-onboarding-mark" aria-hidden="true">?</div><p>${g('Hem preparat una guia molt breu per entendre el flux, les regles del calendari i què significa cada avís.', 'Hemos preparado una guía muy breve para entender el flujo, las reglas del calendario y qué significa cada aviso.')}</p><ul><li>${g('Preparar equip, agendes i guàrdies', 'Preparar equipo, agendas y guardias')}</li><li>${g('Entendre com decideix el planificador', 'Entender cómo decide el planificador')}</li><li>${g('Revisar i ajustar el calendari', 'Revisar y ajustar el calendario')}</li></ul></div><div class="modal-actions"><button type="button" class="button ghost" data-action="dismiss-guide-onboarding">${g('Més tard', 'Más tarde')}</button><button type="button" class="button" data-action="open-guide-onboarding">${g('Llegir la guia', 'Leer la guía')}</button></div></section></div>`;
}
function assignmentModal() {
  const fairnessBadge = (option) => {
    const signed = (value) => Number(value) > 0 ? `+${Number(value)}` : String(Number(value || 0));
    const label = option.fairnessEffect === 'improves'
      ? 'Millora l’equitat'
      : option.fairnessEffect === 'worsens'
        ? 'Empitjora l’equitat'
        : 'Equitat neutra';
    const title = `Pitjor distància: ${signed(option.fairnessWorstDeltaBasisPoints)} · Distància total: ${signed(option.fairnessDeltaBasisPoints)} punts base`;
    return `<span class="fairness-impact ${option.fairnessEffect}" title="${title}">${label}</span>`;
  };
  if (modal.type === 'assignment-exchange') {
    const source = calendarEvents().find((item) => item.id === modal.id);
    const sourceMember = person(source?.memberId);
    const sourceAgenda = agenda(source?.type);
    const options = modal.payload?.options || [];
    const rows = options.map((option) => {
      const target = calendarEvents().find((item) => item.id === option.targetAssignmentId);
      const targetMember = person(option.targetMemberId || target?.memberId);
      const targetAgenda = agenda(option.targetAgendaId || target?.type);
      const targetHospital = agendaHospital(targetAgenda);
      return `<label class="assignment-choice"><input type="radio" name="targetAssignmentId" value="${esc(option.targetAssignmentId)}" required /><span class="assignment-choice-card"><span class="assignment-choice-head"><b>${esc(targetMember?.name || option.targetMemberName || '—')}</b>${fairnessBadge(option)}</span><span class="assignment-swap-preview"><i>${esc(sourceMember?.name || '—')}</i><strong>${esc(sourceAgenda?.name || '—')} → ${esc(targetAgenda?.name || '—')}</strong><i>${esc(targetMember?.name || '—')}</i><strong>${esc(targetAgenda?.name || '—')} → ${esc(sourceAgenda?.name || '—')}</strong></span><small>${esc(targetHospital ? compactHospitalName(targetHospital) : 'Sense hospital')} · ${esc(activityMetaTitle(targetAgenda))}</small></span></label>`;
    }).join('');
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-assignment-action" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">INTERCANVI D’ASSIGNACIONS</div><h2>${esc(sourceMember?.name || '—')}</h2><div class="muted">${fmtDate(source?.date, { weekday: 'long', day: 'numeric', month: 'long' })} · ${esc(sourceAgenda?.name || '—')}</div></div><button class="icon-button" data-action="close-modal">×</button></div><form id="assignment-exchange-form"><input type="hidden" name="id" value="${esc(source?.id || '')}" /><input type="hidden" name="confirmFixed" value="${modal.confirmFixed ? 'true' : 'false'}" /><div class="modal-body"><p class="assignment-action-help">Tria una assignació compatible. El canvi s’aplicarà simultàniament a les dues persones.</p><div class="assignment-choice-list">${rows || '<div class="assignment-choice-empty">No hi ha intercanvis compatibles per a aquesta assignació.</div>'}</div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal" ${options.length ? '' : 'disabled'}>Intercanvia</button></div></form></section></div>`;
  }
  const member = person(modal.memberId);
  const options = modal.payload?.options || [];
  const rows = options.map((option) => {
    const item = agenda(option.agendaId);
    const hospital = agendaHospital(item);
    return `<label class="assignment-choice"><input type="radio" name="agendaId" value="${esc(option.agendaId)}" required /><span class="assignment-choice-card"><span class="assignment-choice-head"><b>${esc(item?.name || '—')}</b>${fairnessBadge(option)}</span><small>${esc(hospital?.name || 'Sense hospital')} · ${esc(activityMetaTitle(item))}</small></span></label>`;
  }).join('');
  return `<div class="modal-backdrop" data-action="close-modal"><section class="modal-card modal-assignment-action" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="card-kicker">PLAÇA EXTRAORDINÀRIA</div><h2>${esc(member?.name || modal.payload?.memberName || '—')}</h2><div class="muted">${fmtDate(modal.date, { weekday: 'long', day: 'numeric', month: 'long' })}</div></div><button class="icon-button" data-action="close-modal">×</button></div><form id="extra-assignment-form"><input type="hidden" name="memberId" value="${esc(modal.memberId)}" /><input type="hidden" name="date" value="${esc(modal.date)}" /><div class="modal-body"><p class="assignment-action-help">Aquesta activitat s’afegirà fora de la demanda ordinària. Comptarà en càrrega, històric i equitat.</p><div class="assignment-choice-list">${rows || '<div class="assignment-choice-empty">No hi ha cap agenda compatible amb les regles d’aquest dia.</div>'}</div></div><div class="modal-actions"><button type="button" class="button ghost" data-action="close-modal">Cancel·la</button><button type="button" class="button" data-action="submit-modal" ${options.length ? '' : 'disabled'}>Obre i assigna</button></div></form></section></div>`;
}
function modalView() {
  if (!modal) return '';
  if (modal.type === 'guide-onboarding') return guideOnboardingModal();
  if (modal.type === 'recovery-code') return recoveryCodeModal();
  if (modal.type === 'generation') return generationModal();
  if (modal.type === 'guard-editor') return guardEditorModal();
  if (modal.type === 'guard-action') return guardActionModal();
  if (modal.type === 'guard-cession') return guardCessionModal();
  if (modal.type === 'guard-exchange') return guardExchangeModal();
  if (modal.type === 'member') { const item = modal.id ? person(modal.id) : null; return memberModal(modal.pending ? { ...(item || {}), ...modal.pending, id: modal.id || '' } : item); }
  if (modal.type === 'delete-member') return deleteMemberModal(person(modal.id));
  if (modal.type === 'agenda') { const item = modal.id ? agenda(modal.id) : null; return agendaModal(modal.pending ? { ...item, ...modal.pending, id: modal.id } : item); }
  if (modal.type === 'delete-agenda') return deleteAgendaModal(agenda(modal.id));
  if (modal.type === 'agenda-rule-conflict') return agendaRuleConflictModal();
  if (modal.type === 'shared-fixed-rule-confirm') return sharedFixedRuleConfirmModal();
  if (modal.type === 'agenda-rules-info') return agendaRulesInfoModal();
  if (modal.type === 'manual-hospital') return manualHospitalModal();
  if (modal.type === 'clear-calendar') return clearCalendarModal();
  if (modal.type === 'generation-unassigned') return generationUnassignedModal();
  if (modal.type === 'fixed-assignment-warning') return fixedAssignmentWarningModal();
  if (['assignment-exchange', 'extra-assignment'].includes(modal.type)) return assignmentModal();
  return '';
}

async function searchHospitals(query) {
  const cleanQuery = query.trim(); hospitalSearchQuery = cleanQuery; pendingHospitalLocation = null;
  const sequence = ++hospitalSearchSequence;
  if (cleanQuery.length < 2) { hospitalSearchResults = []; hospitalSearchStatus = cleanQuery ? 'Escriu almenys dos caràcters.' : ''; updateHospitalSearchUi(); refocusHospitalSearch(); return; }
  const cacheKey = normalizedText(cleanQuery); if (hospitalSearchCache.has(cacheKey)) { const cached = hospitalSearchCache.get(cacheKey); hospitalSearchResults = cached.items; hospitalSearchStatus = hospitalResultStatus(cached.total); updateHospitalSearchUi(); refocusHospitalSearch(); return; }
  hospitalSearchBusy = true; updateHospitalSearchUi();
  try {
    const result = await api.searchHospitals(cleanQuery);
    if (sequence !== hospitalSearchSequence) return;
    hospitalSearchResults = result.items;
    hospitalSearchCache.set(cacheKey, { items: result.items, total: result.total });
    hospitalSearchStatus = hospitalResultStatus(result.total);
  } catch (error) { if (sequence !== hospitalSearchSequence) return; hospitalSearchResults = []; hospitalSearchStatus = 'No s’ha pogut obrir el catàleg local.'; }
  hospitalSearchBusy = false; updateHospitalSearchUi(); refocusHospitalSearch();
}

function hospitalResultStatus(total) {
  if (!total) return 'No s’han trobat hospitals per aquesta cerca.';
  return `${total} ${total === 1 ? 'coincidència' : 'coincidències'} · catàleg local`;
}

function refocusHospitalSearch() {
  requestAnimationFrame(() => { const input = $('[data-hospital-search]'); if (!input) return; input.focus(); input.setSelectionRange(input.value.length, input.value.length); });
}

function updateHospitalSearchUi() {
  const results = $('.hospital-search-results'); const form = $('#hospital-form'); if (!results || !form) return;
  results.innerHTML = hospitalSearchResultsView();
  const values = { catalogId: pendingHospitalLocation?.id || '', name: pendingHospitalLocation?.name || '', address: pendingHospitalLocation?.address || '', latitude: pendingHospitalLocation?.latitude ?? '', longitude: pendingHospitalLocation?.longitude ?? '', areaM2: pendingHospitalLocation?.areaM2 ?? '', cadastralReference: pendingHospitalLocation?.cadastralReference || '' };
  Object.entries(values).forEach(([name, value]) => { const field = form.elements[name]; if (field) field.value = value; });
  const selection = $('[data-map-selection]', form); selection.classList.toggle('selected', Boolean(pendingHospitalLocation)); selection.innerHTML = hospitalSelectionView();
  $('[data-hospital-submit]', form).disabled = !pendingHospitalLocation?.areaAvailable;
  if (state.language === 'es') translateDom(form);
}

async function hospitalDetails(item) {
  if (item?.locationKnown === false) return item;
  if (!item?.catalogId && !item?.id) return item;
  const catalogId = item.catalogId || item.id;
  if (!hospitalDetailsCache.has(catalogId)) hospitalDetailsCache.set(catalogId, api.hospitalDetails(catalogId).catch(() => item));
  return hospitalDetailsCache.get(catalogId);
}

function addGeometryCoordinates(coordinates, value) {
  if (!Array.isArray(value)) return;
  if (typeof value[0] === 'number' && typeof value[1] === 'number') { coordinates.push(value); return; }
  value.forEach((item) => addGeometryCoordinates(coordinates, item));
}

function focusHospitalArea(item) {
  if (!hospitalMap || !window.maplibregl) return;
  const coordinates = [];
  if (item?.geometry) addGeometryCoordinates(coordinates, item.geometry.coordinates);
  if (coordinates.length > 1) {
    const bounds = coordinates.reduce((box, coordinate) => box.extend(coordinate), new window.maplibregl.LngLatBounds(coordinates[0], coordinates[0]));
    hospitalMap.fitBounds(bounds, { padding: 70, maxZoom: 16, duration: 450 });
    return;
  }
  const longitude = Number(item?.longitude); const latitude = Number(item?.latitude);
  if (Number.isFinite(longitude) && Number.isFinite(latitude)) hospitalMap.easeTo({ center: [longitude, latitude], zoom: 15, duration: 450 });
}

async function initHospitalMap() {
  const container = $('#hospital-map'); if (!container) return;
  if (!window.maplibregl) { container.innerHTML = '<div class="map-unavailable">No s’ha pogut carregar el mapa.</div>'; return; }
  const map = new window.maplibregl.Map({ container, style: 'https://tiles.openfreemap.org/styles/positron', center: [-3.7, 40.15], zoom: 4.4, attributionControl: false });
  hospitalMap = map;
  map.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), 'top-left');
  map.addControl(new window.maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  const summaries = [...state.hospitals, ...(pendingHospitalLocation ? [{ ...pendingHospitalLocation, pending: true }] : [])];
  const points = await Promise.all(summaries.map(async (item) => ({ ...item, ...(await hospitalDetails(item)), pending: Boolean(item.pending) })));
  if (hospitalMap !== map) return;
  const coordinates = [];
  const areaFeatures = [];
  points.forEach((item) => { const longitude = Number(item.longitude); const latitude = Number(item.latitude); if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return; coordinates.push([longitude, latitude]); if (item.geometry) { const feature = structuredClone(item.geometry); feature.properties = { ...feature.properties, name: item.name, pending: item.pending }; areaFeatures.push(feature); addGeometryCoordinates(coordinates, feature.geometry.coordinates); } });
  map.once('load', () => {
    if (hospitalMap !== map || !areaFeatures.length) return;
    map.addSource('hospital-areas', { type: 'geojson', data: { type: 'FeatureCollection', features: areaFeatures } });
    const before = map.getStyle().layers.find((layer) => layer.type === 'symbol')?.id;
    map.addLayer({ id: 'hospital-area-fill', type: 'fill', source: 'hospital-areas', paint: { 'fill-color': ['case', ['boolean', ['get', 'pending'], false], '#c8f44c', '#7fb423'], 'fill-opacity': 0.28 } }, before);
    map.addLayer({ id: 'hospital-area-line', type: 'line', source: 'hospital-areas', paint: { 'line-color': ['case', ['boolean', ['get', 'pending'], false], '#86ad18', '#4f7312'], 'line-width': 2.4, 'line-opacity': 0.95 } }, before);
    const popup = new window.maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on('mouseenter', 'hospital-area-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mousemove', 'hospital-area-fill', (event) => { const feature = event.features?.[0]; if (feature?.properties?.name) popup.setLngLat(event.lngLat).setText(feature.properties.name).addTo(map); });
    map.on('mouseleave', 'hospital-area-fill', () => { map.getCanvas().style.cursor = ''; popup.remove(); });
  });
  if (coordinates.length === 1) map.jumpTo({ center: coordinates[0], zoom: 13.5 });
  else if (coordinates.length > 1) { const bounds = coordinates.reduce((box, coordinate) => box.extend(coordinate), new window.maplibregl.LngLatBounds(coordinates[0], coordinates[0])); map.fitBounds(bounds, { padding: 65, maxZoom: areaFeatures.length === 1 ? 15 : 12, duration: 0 }); }
}

function render() {
  if (!state) return;
  if (hospitalMap) { hospitalMap.remove(); hospitalMap = null; }
  $$('[data-enhanced-select-portal]').forEach((menu) => menu.remove());
  const view = { calendar: calendarPage, guards: guardsPage, team: teamPage, agendas: agendasPage, setup: setupPage, history: historyPage, guide: guidePage }[page]();
  app.innerHTML = shellTemplate({ navigation: nav(), view, modal: modalView() });
  $$('.modal-head .icon-button').forEach((button) => { if (!button.hasAttribute('aria-label')) button.setAttribute('aria-label', state.language === 'es' ? 'Cerrar' : 'Tanca'); });
  document.documentElement.lang = state.language === 'es' ? 'es' : 'ca'; translateDom(app);
  enhanceSelects(app);
  if (page === 'setup') requestAnimationFrame(initHospitalMap);
  if (modal) requestAnimationFrame(() => ($('.modal-body input:not([type="hidden"]),.modal-body [data-enhanced-select-trigger]') || $('.modal-card button'))?.focus());
}

function quarterLabel(value) { const [year, month] = value.split('-').map(Number); return `T${Math.floor((month - 1) / 3) + 1} ${year}`; }
function projectionStartMonth(projection) { return projection?.startMonth || projection?.quarter || currentQuarter(); }
function projectionEndMonth(projection) { return projection?.endMonth || monthKey(addMonths(`${projectionStartMonth(projection)}-01`, 2)); }
function periodLabel(startMonth, endMonth) { const start = fmtDate(`${startMonth}-01`, { month: 'short', year: 'numeric' }); const end = fmtDate(`${endMonth}-01`, { month: 'short', year: 'numeric' }); return startMonth === endMonth ? start : `${start} — ${end}`; }
function projectionPeriodLabel(projection) { return periodLabel(projectionStartMonth(projection), projectionEndMonth(projection)); }
function periodBounds(projection) { return { start: projection.startDate || `${projectionStartMonth(projection)}-01`, end: projection.endDate || endOfMonth(`${projectionEndMonth(projection)}-01`) }; }
function periodMonthCount(startMonth, endMonth) { const [startYear, start] = startMonth.split('-').map(Number); const [endYear, end] = endMonth.split('-').map(Number); return (endYear - startYear) * 12 + end - start + 1; }
function isHoliday(key) { return state.holidays.includes(key); }
function historicalCounts() {
  const records = hasCalendarContent() ? [calendarProjection()] : [];
  return historicalActivityCounts(state.team, activeActivities(), records);
}
function fairnessCounts() { return historicalCounts(); }
function download(name, content, mime) { const anchor = document.createElement('a'); const url = URL.createObjectURL(new Blob([content], { type: mime })); anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function exportRows() { return calendarEvents().filter((item) => (!selectedMemberFilters.size || selectedMemberFilters.has(item.memberId)) && (!selectedAgendaFilters.size || selectedAgendaFilters.has(item.type))); }
function exportName() { return `pinendar-${projectionStartMonth(calendarProjection())}-${projectionEndMonth(calendarProjection())}`; }
function exportData() { return exportRows().map((item) => { const member = person(item.memberId) || {}; const agendaItem = agenda(item.type); return { Data: item.date, Metge: member.name || '', Correu: member.email || '', Agenda: item.type === 'no_assignment' ? 'NO ASSIGNACIÓ' : agendaItem.name, Hospital: item.type === 'no_assignment' ? '' : agendaHospital(agendaItem)?.name || '' }; }); }
function exportCsv() { const rows = [['Data', 'Metge', 'Correu', 'Agenda', 'Hospital'], ...exportData().map((item) => Object.values(item))]; download(`${exportName()}.csv`, `\ufeff${rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(';')).join('\n')}`, 'text/csv;charset=utf-8'); }
function icsText(value = '') { return String(value).replaceAll('\\', '\\\\').replaceAll('\n', '\\n').replaceAll(',', '\\,').replaceAll(';', '\\;'); }
function exportIcs() { const events = exportRows().filter((item) => item.type !== 'no_assignment').map((item) => { const member = person(item.memberId) || {}; const agendaItem = agenda(item.type); const hospital = agendaHospital(agendaItem); const day = item.date.replaceAll('-', ''); return `BEGIN:VEVENT\nUID:${item.id}@pinendar\nDTSTART;VALUE=DATE:${day}\nDTEND;VALUE=DATE:${addDays(item.date, 1).replaceAll('-', '')}\nSUMMARY:${icsText(agendaItem.name)}\nLOCATION:${icsText(hospital?.name || '')}\nATTENDEE;CN=${icsText(member.name || '')}:MAILTO:${member.email || ''}\nEND:VEVENT`; }); download(`${exportName()}.ics`, `BEGIN:VCALENDAR\nVERSION:2.0\nCALSCALE:GREGORIAN\nPRODID:-//Pinendar//CA\n${events.join('\n')}\nEND:VCALENDAR`, 'text/calendar;charset=utf-8'); }
function exportExcel() { if (!window.XLSX) return toast('No s’ha pogut carregar l’exportador Excel'); const sheet = window.XLSX.utils.json_to_sheet(exportData()); const workbook = window.XLSX.utils.book_new(); window.XLSX.utils.book_append_sheet(workbook, sheet, 'Pinendar'); const bytes = window.XLSX.write(workbook, { bookType: 'xlsx', type: 'array' }); download(`${exportName()}.xlsx`, bytes, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'); }
function spreadsheetRow(values) { return `<Row>${values.map((value) => `<Cell><Data ss:Type="String">${esc(value)}</Data></Cell>`).join('')}</Row>`; }
function conditionTemplate(kind) { const headers = kind === 'guards' ? ['Fecha', 'Personas'] : ['Persona', 'Inici', 'Final']; const people = activeTeam().map((member) => spreadsheetRow([member.name, member.email])).join(''); const xml = `<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="${kind === 'guards' ? 'Guardies' : 'Vacances'}"><Table>${spreadsheetRow(headers)}</Table></Worksheet><Worksheet ss:Name="Persones"><Table>${spreadsheetRow(['Persona', 'Correu'])}${people}</Table></Worksheet></Workbook>`; download(`plantilla-${kind === 'guards' ? 'guardies' : 'vacances'}-pinendar.xls`, xml, 'application/vnd.ms-excel'); }

function normalizedText(value) { return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase(); }
function spreadsheetValue(row, names) { const keys = Object.keys(row); const key = keys.find((item) => names.includes(normalizedText(item))); return key ? row[key] : ''; }
function spreadsheetDate(value) {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  if (typeof value === 'number' && window.XLSX?.SSF) { const parsed = window.XLSX.SSF.parse_date_code(value); if (parsed) return `${parsed.y}-${String(parsed.m).padStart(2, '0')}-${String(parsed.d).padStart(2, '0')}`; }
  const text = String(value || '').trim(); if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const match = text.match(/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{4})$/); return match ? `${match[3]}-${match[2].padStart(2, '0')}-${match[1].padStart(2, '0')}` : '';
}
function splitGuardNames(value) { return String(value || '').split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean); }
function guardImportRowsFromSheet(sheet) {
  return window.XLSX.utils.sheet_to_json(sheet, { defval: '', raw: true }).map((row, index) => ({
    rowNumber: index + 2,
    date: spreadsheetDate(spreadsheetValue(row, ['data', 'fecha', 'date'])),
    names: splitGuardNames(spreadsheetValue(row, ['persones', 'personas', 'persona', 'metge', 'medico', 'médico', 'nombre', 'nom', 'names'])),
  }));
}
function guardImportCandidates(date) {
  const rows = modal.guardImport?.rows || [];
  const candidates = new Map();
  rows.filter((row) => row.date === date).forEach((row) => row.items.forEach((item) => {
    if (item.status === 'accepted') candidates.set(item.memberId, { memberId: item.memberId, name: item.memberName, score: item.score });
    item.candidates?.forEach((candidate) => candidates.set(candidate.memberId, candidate));
  }));
  return [...candidates.values()].sort((left, right) => String(left.name).localeCompare(String(right.name)));
}
function guardImportChoice(date) {
  const choices = modal.guardImport?.choices || {};
  if (choices[date]) return choices[date];
  const candidates = guardImportCandidates(date);
  const accepted = candidates.filter((candidate) => (modal.guardImport.rows || []).some((row) => row.date === date && row.items.some((item) => item.status === 'accepted' && item.memberId === candidate.memberId)));
  return accepted.length === 1 && candidates.length === 1 ? accepted[0].memberId : '';
}
function guardImportReady() {
  if (!modal.guardImport) return true;
  const dates = [...new Set(modal.guardImport.rows.filter((row) => row.status === 'ready').map((row) => row.date))];
  return dates.every((date) => {
    const candidates = guardImportCandidates(date);
    return candidates.length === 0 || Boolean(guardImportChoice(date));
  });
}
function applyGuardImportSelections() {
  if (!modal.guardImport) return;
  const manual = modal.guards.filter((item) => !item.imported);
  const imported = [];
  const dates = [...new Set(modal.guardImport.rows.filter((row) => row.status === 'ready').map((row) => row.date))];
  for (const date of dates) {
    const memberId = guardImportChoice(date);
    if (memberId && !imported.some((item) => item.date === date)) imported.push({ id: uid(), date, memberId, imported: true });
  }
  modal.guards = [...manual, ...imported];
}
function guardImportStatus(item) {
  if (item.status === 'accepted') return `<span class="guard-import-status accepted">Reconocido · ${item.score}</span>`;
  if (item.status === 'review') return '<span class="guard-import-status review">Revisión necesaria</span>';
  return '<span class="guard-import-status ignored">Ignorado · no registrado</span>';
}
function guardImportReview() {
  const importState = modal.guardImport;
  if (!importState) return '';
  const rows = importState.rows.map((row, rowIndex) => {
    const candidates = row.status === 'ready' ? guardImportCandidates(row.date) : [];
    const choice = row.status === 'ready' ? guardImportChoice(row.date) : '';
    const choiceField = candidates.length > 1 || candidates.some((candidate) => row.items.some((item) => item.status === 'review')) ? `<label class="guard-import-choice"><span>Adjunt per a aquesta data</span><select data-action="guard-import-choice" data-guard-import-date="${esc(row.date)}"><option value="">Selecciona una persona</option>${candidates.map((candidate) => `<option value="${esc(candidate.memberId)}" ${candidate.memberId === choice ? 'selected' : ''}>${esc(candidate.name)}${candidate.score ? ` · ${candidate.score}` : ''}</option>`).join('')}</select></label>` : '';
    const rowLabel = row.status === 'out_of_range' ? 'Fora del període' : row.status === 'invalid_date' ? 'Data no vàlida' : row.status === 'empty' ? 'Sense noms' : row.date;
    return `<div class="guard-import-row"><div class="guard-import-row-head"><b>${esc(rowLabel)}</b><small>Fila ${row.rowNumber}</small></div><div class="guard-import-items">${row.items.map((item, itemIndex) => `<div class="guard-import-item"><span><b>${esc(item.rawName)}</b>${guardImportStatus(item)}</span>${item.status === 'review' && item.candidates?.length ? `<button type="button" class="button ghost tiny" data-action="save-import-alias" data-guard-import-row="${rowIndex}" data-guard-import-item="${itemIndex}">Guardar alias</button>` : ''}</div>`).join('') || '<span class="muted">Sin nombres procesables.</span>'}</div>${choiceField}</div>`;
  }).join('');
  const summary = importState.summary || {};
  const ready = guardImportReady();
  return `<div class="guard-import-review"><div class="guard-import-summary"><b>Revisión del XLSX</b><span>${summary.accepted || 0} reconocidos · ${summary.ignored || 0} ignorados · ${summary.review || 0} pendientes${ready ? '' : ' · selecciona las fechas pendientes'}</span></div>${rows}</div>`;
}
async function previewGuardImportRows(inputRows) {
  const periodError = generationPeriodError();
  if (periodError) { modal.importNotice = periodError; render(); return; }
  const preview = await api.previewGuardImport({ ...generationPeriodPayload(), rows: inputRows });
  modal.guardImport = { ...preview, inputRows, choices: modal.guardImport?.choices || {} };
  applyGuardImportSelections();
  modal.importNotice = `${preview.summary.accepted || 0} adjuntos reconocidos · ${preview.summary.ignored || 0} nombres ignorados${preview.conflicts?.length ? ` · ${preview.conflicts.length} fechas con más de un adjunto` : ''}.`;
  render();
}
async function importGuardSpreadsheet(file) {
  if (!file) return;
  if (!window.XLSX) { modal.importNotice = 'No s’ha pogut carregar el lector XLS.'; render(); return; }
  try {
    const workbook = window.XLSX.read(await file.arrayBuffer(), { cellDates: true });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    await previewGuardImportRows(guardImportRowsFromSheet(sheet));
  } catch (error) { modal.importNotice = 'No s’ha pogut llegir el fitxer. Revisa que sigui XLS o XLSX.'; render(); }
}
async function importAbsenceSpreadsheet(file) {
  if (!file) return;
  if (!window.XLSX) { modal.importNotice = 'No s’ha pogut carregar el lector XLS.'; render(); return; }
  try {
    const workbook = window.XLSX.read(await file.arrayBuffer(), { cellDates: true }); const sheet = workbook.Sheets[workbook.SheetNames[0]]; const rows = window.XLSX.utils.sheet_to_json(sheet, { defval: '', raw: true }); const bounds = generationDateBounds(); let added = 0; let skipped = 0;
    for (const row of rows) {
      const memberText = spreadsheetValue(row, ['persona', 'metge', 'medico', 'médico', 'nombre', 'nom', 'email', 'correu']); const member = activeTeam().find((item) => [item.name, item.email].some((value) => normalizedText(value) === normalizedText(memberText))); const start = spreadsheetDate(spreadsheetValue(row, ['inici', 'inicio', 'start', 'data inici', 'fecha inicio'])); const end = spreadsheetDate(spreadsheetValue(row, ['final', 'fin', 'end', 'data final', 'fecha final']));
      if (!member || !start || !end || start < bounds.start || end > bounds.end || end < start) { skipped += 1; continue; }
      const duplicate = modal.absences.some((item) => item.memberId === member.id && item.start === start && item.end === end); if (!duplicate) { modal.absences.push({ id: uid(), memberId: member.id, start, end }); added += 1; }
    }
    modal.importNotice = `${added} períodes de vacances importats${skipped ? ` · ${skipped} files fora del període o no reconegudes` : ''}.`; render();
  } catch (error) { modal.importNotice = 'No s’ha pogut llegir el fitxer. Revisa que sigui XLS o XLSX.'; render(); }
}

document.addEventListener('click', (event) => {
  const option = event.target.closest('[data-enhanced-select-option]');
  if (option) {
    const select = option._enhancedSelect; const wrapper = select?.closest('.enhanced-select'); if (!select || !wrapper) return;
    select.value = option.dataset.enhancedSelectOption; rebuildEnhancedSelect(select); select.dispatchEvent(new Event('change', { bubbles: true })); return;
  }
  const trigger = event.target.closest('[data-enhanced-select-trigger]');
  if (trigger) {
    const wrapper = trigger.closest('.enhanced-select'); const opening = !wrapper.classList.contains('open');
    closeEnhancedSelects(wrapper);
    wrapper.classList.toggle('open', opening); trigger.setAttribute('aria-expanded', String(opening));
    if (opening) { positionEnhancedSelect(wrapper); requestAnimationFrame(() => wrapper.querySelector('.enhanced-select-native')._enhancedMenu?.querySelector('.enhanced-select-option[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })); }
    else closeEnhancedSelect(wrapper);
    return;
  }
  closeEnhancedSelects();
});
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  closeEnhancedSelects();
});
window.addEventListener('resize', () => $$('.enhanced-select.open').forEach(positionEnhancedSelect));
document.addEventListener('scroll', (event) => { if (!event.target.closest?.('.enhanced-select-menu')) $$('.enhanced-select.open').forEach(positionEnhancedSelect); }, true);

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action],[data-page],[data-calendar-view],[data-calendar-issue-filter],[data-calendar-date],[data-calendar-open],[data-edit-member],[data-delete-member],[data-edit-agenda],[data-delete-agenda],[data-edit-assignment],[data-open-extra-member],[data-remove-guard],[data-remove-time],[data-remove-hospital],[data-focus-hospital],[data-remove-generation-condition],[data-hospital-result],[data-history-member]'); if (!button) return;
  if (button.dataset.page) { if (page !== button.dataset.page) { page = button.dataset.page; modal = null; syncNavigationUrl('push'); render(); } return; }
  if (button.dataset.calendarIssueFilter) { const issue = button.dataset.calendarIssueFilter; if (selectedCalendarIssueFilters.has(issue)) selectedCalendarIssueFilters.delete(issue); else selectedCalendarIssueFilters.add(issue); syncNavigationUrl('replace'); render(); return; }
  if (button.dataset.calendarView) { if (calendarView !== button.dataset.calendarView) { calendarView = button.dataset.calendarView; syncNavigationUrl('push'); render(); } return; }
  if (button.dataset.calendarOpen) { calendarDate = button.dataset.calendarOpen; calendarView = 'day'; modal = null; syncNavigationUrl('push'); render(); return; }
  if (button.dataset.calendarDate) { calendarDate = button.dataset.calendarDate; calendarView = 'day'; syncNavigationUrl('push'); render(); return; }
  if (button.dataset.editMember) { const member = person(button.dataset.editMember); modal = { type: 'member', id: member.id, color: member.color, tab: 'general', vacationMonth: monthKey(dateKey(new Date())), vacationDates: [...member.vacationDates] }; render(); return; }
  if (button.dataset.deleteMember) { modal = { type: 'delete-member', id: button.dataset.deleteMember }; render(); return; }
  if (button.dataset.editAgenda) { const item = agenda(button.dataset.editAgenda); modal = { type: 'agenda', id: item.id, color: item.color }; render(); return; }
  if (button.dataset.deleteAgenda) { modal = { type: 'delete-agenda', id: button.dataset.deleteAgenda }; render(); return; }
  if (button.dataset.editAssignment) {
    const item = calendarEvents().find((assignment) => assignment.id === button.dataset.editAssignment);
    if (!item) return;
    if (item.type === 'management') return toast('La gestió no es pot intercanviar des del calendari');
    if (item.fixed) { modal = { type: 'fixed-assignment-warning', id: item.id }; render(); return; }
    try {
      if (item.type === 'no_assignment') {
        const payload = await api.extraAssignmentOptions(item.date, item.memberId);
        modal = { type: 'extra-assignment', memberId: item.memberId, date: item.date, payload };
      } else {
        const payload = await api.assignmentExchangeOptions(item.id);
        modal = { type: 'assignment-exchange', id: item.id, payload };
      }
      render();
    } catch (error) { showError(error); }
    return;
  }
  if (button.dataset.openExtraMember) {
    try {
      const payload = await api.extraAssignmentOptions(button.dataset.extraDate, button.dataset.openExtraMember);
      modal = { type: 'extra-assignment', memberId: button.dataset.openExtraMember, date: button.dataset.extraDate, payload };
      render();
    } catch (error) { showError(error); }
    return;
  }
  if (button.dataset.historyMember) { historyMemberFilter = button.dataset.historyMember; render(); return; }
  if (button.dataset.hospitalResult !== undefined) { const item = hospitalSearchResults[Number(button.dataset.hospitalResult)]; if (item) pendingHospitalLocation = { ...item }; render(); return; }
  if (button.dataset.focusHospital) { const item = state.hospitals.find((hospital) => hospital.catalogId === button.dataset.focusHospital); if (item) focusHospitalArea(await hospitalDetails(item)); return; }
  if (button.dataset.removeHospital) {
    try {
      await api.removeHospital(button.dataset.removeHospital);
      await reloadState();
      render();
      toast('Hospital eliminat');
    } catch (error) {
      render();
      toast(error.message);
    }
    return;
  }
  if (button.dataset.removeGenerationCondition) { const [kind, id] = button.dataset.removeGenerationCondition.split(':'); if (kind === 'guard') modal.guards = modal.guards.filter((item) => item.id !== id); else modal.absences = modal.absences.filter((item) => item.id !== id); render(); return; }
  if (button.dataset.removeGuard) { try { await api.deleteGuard(button.dataset.removeGuard); await reloadState(); } catch (error) { showError(error); } render(); return; }
  if (button.dataset.removeTime) { const [, date] = button.dataset.removeTime.split(':'); try { await api.deleteHoliday(date); await reloadState(); } catch (error) { showError(error); } render(); return; }
  const action = button.dataset.action;
  if (action === 'submit-modal') { event.preventDefault(); const formElement = button.closest('form'); if (formElement.reportValidity()) await handleForm(formElement); return; }
  if (action === 'confirm-generation-overwrite') { modal.replaceExisting = true; modal.overlap = null; modal.conflict = ''; await handleForm(button.closest('form')); return; }
  if (action === 'confirm-fixed-exchange') {
    const assignmentId = modal.id;
    try {
      const payload = await api.assignmentExchangeOptions(assignmentId, true);
      modal = { type: 'assignment-exchange', id: assignmentId, payload, confirmFixed: true };
      render();
    } catch (error) { showError(error); }
    return;
  }
  if (action === 'close-modal') { if (event.target === button || button.closest('.modal-card')) { modal = null; render(); } return; }
  if (action === 'language') { try { await api.changeLanguage(button.dataset.language); await reloadState(); } catch (error) { showError(error); } render(); return; }
  if (action === 'dismiss-guide-onboarding') { try { await api.markGuideOnboardingSeen(); state.account.guideOnboardingPending = false; modal = null; render(); } catch (error) { showError(error); } return; }
  if (action === 'open-guide-onboarding') { try { await api.markGuideOnboardingSeen(); state.account.guideOnboardingPending = false; page = 'guide'; modal = null; syncNavigationUrl('push'); render(); } catch (error) { showError(error); } return; }
  if (action === 'open-recovery-code') { modal = { type: 'recovery-code', code: '' }; render(); return; }
  if (action === 'generate-recovery-code') { try { const result = await api.rotateRecoveryCode(); modal = { type: 'recovery-code', code: result.recoveryCode }; render(); } catch (error) { showError(error); } return; }
  if (action === 'copy-recovery-code') { await navigator.clipboard.writeText(modal.code); toast('Clau copiada'); return; }
  if (action === 'download-recovery-code') { download(`pinendar-${state.account?.username || 'compte'}-recuperacio.txt`, `Pinendar · ${state.account?.username || ''}\nClau de recuperació: ${modal.code}\n`, 'text/plain'); return; }
  if (action === 'logout') { await api.logout(); state = null; loginView(); return; }
  if (action === 'open-member') { modal = { type: 'member', tab: 'general', vacationMonth: monthKey(dateKey(new Date())), vacationDates: [] }; render(); return; }
  if (action === 'open-agenda') { modal = { type: 'agenda' }; render(); return; }
  if (action === 'add-manual-hospital') { const name = hospitalSearchQuery.trim(); if (name.length < 2) return; modal = { type: 'manual-hospital', name }; render(); return; }
  if (action === 'confirm-manual-hospital') { try { await api.selectHospital({ name: modal.name }); modal = null; hospitalSearchResults = []; hospitalSearchStatus = ''; hospitalSearchQuery = ''; await reloadState('Centre afegit'); render(); } catch (error) { showError(error); } return; }
  if (action === 'open-clear-calendar') { const bounds = hasCalendarContent() ? calendarBounds() : { start: `${monthKey(calendarDate)}-01`, end: endOfMonth(calendarDate) }; modal = { type: 'clear-calendar', startDate: bounds.start, endDate: bounds.end }; render(); return; }
  if (action === 'open-generation') { const startMonth = nextGenerationMonth(); const startDate = `${startMonth}-01`; modal = { type: 'generation', periodMode: 'month', startMonth, endMonth: startMonth, startDate, endDate: endOfMonth(startDate), guards: [], absences: [], conflict: '' }; render(); return; }
  if (action === 'open-guard-editor') { const bounds = calendarBounds(); modal = { type: 'guard-editor', startMonth: projectionStartMonth(calendarProjection()), endMonth: projectionEndMonth(calendarProjection()), startDate: bounds.start, endDate: bounds.end, guards: structuredClone(calendarGuards()), conflict: '' }; render(); return; }
  if (action === 'open-incoming-guard') { modal = { type: 'guard-cession', guardId: null, date: '' }; render(); return; }
  if (action === 'open-calendar-guard') { modal = { type: 'guard-action', guardId: button.dataset.guardId }; render(); return; }
  if (action === 'open-guard-cession') { modal = { type: 'guard-cession', guardId: button.dataset.guardId }; render(); return; }
  if (action === 'open-guard-exchange') { modal = { type: 'guard-exchange', guardId: button.dataset.guardId, secondRef: '' }; render(); return; }
  if (action === 'add-generation-guard') { const formElement = button.closest('form'); const date = $('[name="guard-date"]', formElement).value; const memberId = $('[name="guard-member"]', formElement).value; const bounds = generationDateBounds(); if (!memberId) return toast('Selecciona una persona'); if (!date) return toast('Selecciona la data de la guàrdia'); if (date < bounds.start || date > bounds.end) return toast('La guàrdia ha d’estar dins del període seleccionat'); if (!modal.guards.some((item) => item.memberId === memberId && item.date === date)) modal.guards.push({ id: uid(), date, memberId }); modal.conflict = ''; render(); return; }
  if (action === 'add-generation-absence') { const formElement = button.closest('form'); const memberId = $('[name="absence-member"]', formElement).value; const start = $('[name="absence-start"]', formElement).value; const end = $('[name="absence-end"]', formElement).value; const bounds = generationDateBounds(); if (!memberId) return toast('Selecciona una persona'); if (!start || !end) return toast('Completa l’inici i el final de les vacances'); if (start < bounds.start || end > bounds.end) return toast('Les vacances han d’estar dins del període seleccionat'); if (end < start) return toast('La data final no pot ser anterior'); modal.absences.push({ id: uid(), memberId, start, end }); modal.conflict = ''; render(); return; }
  if (action === 'vacation-prev' || action === 'vacation-next') { modal.vacationMonth = monthKey(addMonths(`${modal.vacationMonth}-01`, action === 'vacation-prev' ? -1 : 1)); modal.tab = 'vacations'; render(); return; }
  if (action === 'toggle-vacation') { const key = button.dataset.vacationDate; if (!key || key < dateKey(new Date())) return; const selected = new Set(modal.vacationDates); if (selected.has(key)) selected.delete(key); else selected.add(key); modal.vacationDates = [...selected].sort(); modal.tab = 'vacations'; render(); return; }
  if (action === 'export-guards-template') { conditionTemplate('guards'); return; }
  if (action === 'export-absences-template') { conditionTemplate('absences'); return; }
  if (action === 'save-import-alias') {
    const row = modal.guardImport?.rows?.[Number(button.dataset.guardImportRow)];
    const item = row?.items?.[Number(button.dataset.guardImportItem)];
    const memberId = guardImportChoice(row?.date) || item?.candidates?.[0]?.memberId;
    if (!item || !memberId) return toast('Selecciona primero un candidato');
    try {
      await api.saveMemberAlias({ memberId, alias: item.rawName });
      await previewGuardImportRows(modal.guardImport.inputRows);
    } catch (error) { showError(error); }
    return;
  }
  if (action === 'random-color') { if (!modal?.id) return toast('El color automàtic s’assignarà en desar'); try { const result = button.dataset.colorKind === 'member' ? await api.randomMemberColor(modal.id) : await api.randomAgendaColor(modal.id); modal.color = result.color; const target = button.closest('form'); $('[data-color-swatch]', target).style.setProperty('--automatic-color', result.color); await reloadState('Color actualitzat'); } catch (error) { showError(error); } return; }
  if (action === 'toggle-agenda-reaction') { const reaction = button.closest('[data-agenda-reaction]'); const opening = !reaction.classList.contains('open'); $$('[data-agenda-reaction].open').forEach((item) => { item.classList.remove('open'); $('[data-action="toggle-agenda-reaction"]', item).setAttribute('aria-expanded', 'false'); }); reaction.classList.toggle('open', opening); button.setAttribute('aria-expanded', String(opening)); return; }
  if (action === 'set-agenda-preference') { const reaction = button.closest('[data-agenda-reaction]'); const value = Number(button.dataset.preference); const trigger = $('[data-action="toggle-agenda-reaction"]', reaction); $('[data-agenda-preference]', reaction).value = String(value); reaction.classList.toggle('liked', value === 1); reaction.classList.toggle('disliked', value === -1); reaction.classList.remove('open'); $('span', trigger).textContent = value === 1 ? '♥' : value === -1 ? '👎' : '+'; trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-label', `${value === 1 ? 'Agrada' : value === -1 ? 'Desagrada' : 'Afegeix reacció'}: ${reaction.dataset.agendaName}`); return; }
  if (action === 'add-work-pattern-week') { const formElement = button.closest('form'); const container = $('[data-work-pattern-weeks]', formElement); const rows = $$('[data-work-pattern-week]', container); if (rows.length >= 5) return toast('El patró pot tenir un màxim de 5 setmanes'); const previous = rows.at(-1); const week = { workingDays: $$('[data-pattern-working]:checked', previous).map((item) => Number(item.value)), teleDays: $$('[data-pattern-tele]:checked', previous).map((item) => Number(item.value)) }; container.insertAdjacentHTML('beforeend', workPatternWeekRow(week, rows.length, true)); renumberWorkPatternWeeks(formElement); refreshPatternDependentFields(formElement); return; }
  if (action === 'remove-work-pattern-week') { const formElement = button.closest('form'); button.closest('[data-work-pattern-week]').remove(); renumberWorkPatternWeeks(formElement); if ($$('[data-work-pattern-week]', formElement).length === 1) { $('[name="work-pattern-mode"][value="same"]', formElement).checked = true; syncWorkPatternMode(formElement); } else refreshPatternDependentFields(formElement); return; }
  if (action === 'add-fixed-rule') { const formElement = button.closest('form'); const allowed = $$('[name="allowed"]:checked', formElement).map((item) => item.value); const available = workPatternAvailableDays(formElement); const rule = defaultFixedRule(allowed, available); if (!rule.type) return toast('Habilita una agenda amb cobertura en un dia disponible'); const container = $('#fixed-rules'); $('.empty-rules', container)?.remove(); container.insertAdjacentHTML('beforeend', fixedRuleRow(rule, allowed, available)); enhanceSelects(container); $$('.tab-count').at(-1).textContent = $$('.fixed-rule-row').length; return; }
  if (action === 'remove-fixed-rule') { button.closest('.fixed-rule-row').remove(); if (!$$('.fixed-rule-row').length) $('#fixed-rules').innerHTML = '<div class="empty-rules muted">Encara no hi ha regles fixes.</div>'; $$('.tab-count').at(-1).textContent = $$('.fixed-rule-row').length; return; }
  if (action === 'add-agenda-recurrence') { const container = $('#agenda-recurrences'); $('.empty-agenda-recurrences', container)?.remove(); container.insertAdjacentHTML('beforeend', agendaRecurrenceRow()); enhanceSelects(container); return; }
  if (action === 'remove-agenda-recurrence') { button.closest('.agenda-recurrence-row').remove(); if (!$$('.agenda-recurrence-row').length) $('#agenda-recurrences').innerHTML = '<div class="empty-agenda-recurrences muted">Encara no hi ha regles especials.</div>'; return; }
  if (action === 'confirm-delete-agenda') { const id = button.dataset.agendaId; try { await api.deleteAgenda(id); selectedAgendaFilters.delete(id); modal = null; await reloadState('Agenda eliminada'); } catch (error) { showError(error); } render(); return; }
  if (action === 'return-agenda-edit') { const { id, payload } = modal; modal = { type: 'agenda', id, color: agenda(id)?.color, pending: payload }; render(); return; }
  if (action === 'confirm-agenda-rule-deletion') { const { id, payload } = modal; try { await api.saveAgenda(id, { ...payload, deleteConflictingFixedRules: true }); modal = null; await reloadState('Agenda desada i regles eliminades'); render(); } catch (error) { showError(error); } return; }
  if (action === 'open-agenda-rules-info') { const { id, payload } = agendaFormPayload(button.closest('form')); modal = { type: 'agenda-rules-info', id, payload }; render(); return; }
  if (action === 'return-member-edit') { const { id, payload, tab, vacationMonth } = modal; modal = { type: 'member', id, color: id ? person(id)?.color : '', pending: payload, tab, vacationMonth, vacationDates: [...payload.vacationDates] }; render(); return; }
  if (action === 'confirm-shared-fixed-rules') { const { id, payload, tab, vacationMonth } = modal; try { const saved = await api.saveMember(id, { ...payload, confirmSharedFixedRules: true }); await finishMemberSave(saved, tab, vacationMonth); } catch (error) { showError(error); } return; }
  if (action === 'calendar-today') calendarDate = dateKey(new Date());
  if (action === 'calendar-prev') calendarDate = calendarView === 'day' ? addDays(calendarDate, -1) : calendarView === 'week' ? addDays(calendarDate, -7) : addMonths(calendarDate, -1);
  if (action === 'calendar-next') calendarDate = calendarView === 'day' ? addDays(calendarDate, 1) : calendarView === 'week' ? addDays(calendarDate, 7) : addMonths(calendarDate, 1);
  if (['calendar-today', 'calendar-prev', 'calendar-next'].includes(action)) { syncNavigationUrl('push'); render(); return; }
  if (action === 'export-csv') exportCsv(); if (action === 'export-ics') exportIcs(); if (action === 'export-excel') exportExcel(); if (action === 'backup') download(`pinendar-backup-${dateKey(new Date())}.json`, JSON.stringify(state, null, 2), 'application/json');
});

function addMonths(key, amount) { const d = fromKey(key); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + amount); return dateKey(d); }
function agendaFormPayload(formElement) { const form = new FormData(formElement); const coverage = Object.fromEntries([1, 2, 3, 4, 5].map((day) => [String(day), Number(form.get(`coverage-${day}`) || 0)])); const recurrences = $$('.agenda-recurrence-row', formElement).map((row) => ({ ordinal: Number($('[name="recurrence-ordinal"]', row).value), weekday: Number($('[name="recurrence-weekday"]', row).value), slots: 1 })); return { id: form.get('id'), payload: { name: form.get('name').trim(), hospitalId: form.get('hospitalId'), telematic: form.get('telematic') === 'on', shift: form.get('shift'), priority: Number(form.get('priority')), loadPercentage: Number(form.get('loadPercentage')), coverage, recurrences } }; }
async function finishMemberSave(saved, tab, vacationMonth) { await reloadState(); modal = { type: 'member', id: saved.id, color: saved.color, tab, vacationMonth, vacationDates: [...saved.vacationDates], saved: true }; render(); setTimeout(() => { if (modal?.type === 'member' && modal.id === saved.id && modal.saved) { modal.saved = false; render(); } }, 2200); }
document.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-modal-tab]'); if (!tab) return;
  if (modal?.type === 'member') modal.tab = tab.dataset.modalTab;
  $$('.modal-tabs button').forEach((button) => button.classList.toggle('active', button === tab));
  $$('.tab-panel').forEach((panel) => panel.classList.toggle('active', panel.dataset.tabPanel === tab.dataset.modalTab));
});
document.addEventListener('change', async (event) => {
  if (event.target.dataset.action === 'import-guards-file') { await importGuardSpreadsheet(event.target.files?.[0]); return; }
  if (event.target.dataset.action === 'import-absences-file') { await importAbsenceSpreadsheet(event.target.files?.[0]); return; }
  if (event.target.dataset.action === 'guard-import-choice') { const date = event.target.dataset.guardImportDate; if (date) { modal.guardImport.choices[date] = event.target.value; applyGuardImportSelections(); render(); } return; }
  if (modal?.type === 'guard-cession' && ['toMemberId', 'date'].includes(event.target.name)) { await refreshGuardOperationPreview(event.target.closest('form')); return; }
  if (modal?.type === 'guard-exchange' && event.target.name === 'secondRef') { await refreshGuardOperationPreview(event.target.closest('form')); return; }
  if (modal?.type === 'member' && event.target.name === 'managementEnabled') { const field = $('[data-management-quota]'); const input = $('[name="quota"]', field); field.classList.toggle('is-hidden', !event.target.checked); input.disabled = !event.target.checked; input.required = event.target.checked; if (event.target.checked && !Number(input.value)) input.value = '1'; return; }
  if (modal?.type === 'member' && event.target.name === 'allowed') { const formElement = event.target.closest('form'); $$('.fixed-rule-row', formElement).forEach((row) => refreshFixedRuleType(row, formElement)); return; }
  if (modal?.type === 'member' && event.target.name === 'work-pattern-mode') { syncWorkPatternMode(event.target.closest('form')); return; }
  if (modal?.type === 'member' && (event.target.dataset.patternWorking !== undefined || event.target.dataset.patternTele !== undefined)) { refreshPatternDependentFields(event.target.closest('form')); return; }
  if (modal?.type === 'member' && event.target.name === 'rule-weekday') { const row = event.target.closest('.fixed-rule-row'); refreshFixedRuleType(row, event.target.closest('form')); return; }
  if (modal?.type === 'member' && event.target.name === 'rule-type') { refreshFixedRulePeers(event.target.closest('.fixed-rule-row')); return; }
  if (modal?.type === 'generation' && event.target.name === 'periodMode') { modal.periodMode = event.target.value; modal.replaceExisting = false; modal.overlap = null; modal.conflict = ''; render(); return; }
  if (modal?.type === 'generation' && event.target.dataset.monthPart) { const picker = event.target.closest('[data-month-picker]'); const month = $('[data-month-part="month"]', picker).value; const year = $('[data-month-part="year"]', picker).value; const next = `${year}-${month}`; modal.startMonth = next; modal.endMonth = next; modal.startDate = `${next}-01`; modal.endDate = endOfMonth(modal.startDate); modal.replaceExisting = false; modal.overlap = null; modal.conflict = ''; render(); return; }
  if (modal?.type === 'generation' && ['generationStartDate', 'generationEndDate'].includes(event.target.name)) { const formElement = event.target.closest('form'); const startInput = $('[name="generationStartDate"]', formElement); const endInput = $('[name="generationEndDate"]', formElement); if (event.target.name === 'generationStartDate') { modal.startDate = event.target.value; if (modal.startDate && (!modal.endDate || modal.endDate < modal.startDate || monthKey(modal.endDate) !== monthKey(modal.startDate))) modal.endDate = endOfMonth(modal.startDate); } else modal.endDate = event.target.value; if (modal.startDate) modal.startMonth = monthKey(modal.startDate); if (modal.endDate) modal.endMonth = monthKey(modal.endDate); modal.replaceExisting = false; modal.overlap = null; if (endInput) { endInput.value = modal.endDate || ''; endInput.min = modal.startDate || ''; endInput.max = modal.startDate ? endOfMonth(modal.startDate) : ''; } modal.conflict = generationPeriodError(); startInput?.setCustomValidity(modal.conflict); endInput?.setCustomValidity(modal.conflict); const warning = $('.generation-warning', formElement); if (warning) { warning.hidden = !modal.conflict; const message = $('span', warning); if (message) message.textContent = modal.conflict; } return; }
  if (event.target.dataset.calendarFilterAll) { const kind = event.target.dataset.calendarFilterAll; openCalendarFilter = kind; (kind === 'member' ? selectedMemberFilters : selectedAgendaFilters).clear(); syncNavigationUrl('replace'); render(); return; }
  if (event.target.dataset.calendarFilterOption) { const kind = event.target.dataset.calendarFilterOption; const selected = kind === 'member' ? selectedMemberFilters : selectedAgendaFilters; openCalendarFilter = kind; if (event.target.checked) selected.add(event.target.value); else selected.delete(event.target.value); syncNavigationUrl('replace'); render(); return; }
  if (event.target.dataset.action === 'history-member') { historyMemberFilter = event.target.value; render(); }
});
document.addEventListener('click', (event) => {
  $$('.language-picker[open]').forEach((picker) => { if (!picker.contains(event.target)) picker.removeAttribute('open'); });
  if (!event.target.closest('[data-agenda-reaction]')) $$('[data-agenda-reaction].open').forEach((item) => { item.classList.remove('open'); $('[data-action="toggle-agenda-reaction"]', item)?.setAttribute('aria-expanded', 'false'); });
});
document.addEventListener('toggle', (event) => { const kind = event.target.dataset?.filterKind; if (kind) openCalendarFilter = event.target.open ? kind : ''; }, true);
async function handleForm(formElement) {
  const form = new FormData(formElement); const formId = formElement.getAttribute('id');
  try {
    if (formId === 'guard-cession-form') {
      const payload = guardOperationPayload(formElement, 'cession');
      if (!payload || !modal.preview) return;
      await api.applyGuardCession(payload);
      modal = null; await reloadState('Guàrdia i calendari actualitzats'); render(); return;
    }
    if (formId === 'guard-exchange-form') {
      const payload = guardOperationPayload(formElement, 'exchange');
      if (!payload || !modal.preview) return;
      await api.applyGuardExchange(payload);
      modal = null; await reloadState('Guàrdies i calendari actualitzats'); render(); return;
    }
    if (formId === 'guard-editor-form') {
      if (!guardImportReady()) return toast('Revisa las coincidencias del XLSX');
      const bounds = generationDateBounds();
      if (modal.guards.some((item) => item.date < bounds.start || item.date > bounds.end)) return toast('Hay guardias fuera del período');
      await api.replaceGuards({ guards: modal.guards });
      modal = null; await reloadState('Guardias actualizadas'); render(); return;
    }
    if (formId === 'generation-form') {
      const bounds = generationDateBounds(); const periodError = generationPeriodError(bounds);
      if (periodError) { modal.conflict = periodError; render(); return; }
      const { startMonth, endMonth, startDate, endDate } = generationPeriodPayload();
      if (!guardImportReady()) { modal.conflict = 'Revisa les coincidències de l’XLSX i selecciona una sola persona per data.'; render(); return; }
      if (modal.guards.some((item) => item.date < bounds.start || item.date > bounds.end) || modal.absences.some((item) => item.start < bounds.start || item.end > bounds.end || item.end < item.start)) { modal.conflict = 'Hi ha guàrdies o vacances fora del període seleccionat. Elimina-les o ajusta el període.'; render(); return; }
      modal.busy = true; modal.conflict = ''; modal.loadingPhrase = nextGenerationLoadingMessage(); render();
      const loadingTimer = startGenerationLoadingAnimation();
      let job;
      try {
        const queued = await api.startGeneration({ startMonth, endMonth, startDate, endDate, guards: modal.guards, absences: modal.absences, replaceExisting: Boolean(modal.replaceExisting) });
        job = await waitForGeneration(queued.id);
      } finally {
        window.clearInterval(loadingTimer);
      }
      if (job.status !== 'succeeded') throw new Error(job.error?.message || 'No s’ha pogut generar el calendari');
      quarter = startMonth; calendarDate = startDate; modal = null; await reloadState();
      const unassigned = calendarEvents().filter((item) => item.type === 'no_assignment' && item.date >= startDate && item.date <= endDate);
      const affectedPeople = new Set(unassigned.map((item) => item.memberId)).size;
      modal = unassigned.length ? { type: 'generation-unassigned', count: unassigned.length, people: affectedPeople } : null;
      render(); if (!unassigned.length) toast('Calendari generat'); return;
    }
    if (formId === 'member-form') {
      const allowedTypes = form.getAll('allowed'); const managementEnabled = form.get('managementEnabled') === 'on'; const managementQuota = managementEnabled ? Number(form.get('quota')) : 0;
      const fixedRules = $$('.fixed-rule-row', formElement).map((row) => ({ weekday: Number($('[name="rule-weekday"]', row).value), type: $('[name="rule-type"]', row).value }));
      const workPattern = collectWorkPattern(formElement); const availableDays = [...new Set(workPattern.weeks.flatMap((week) => week.workingDays))].sort((a, b) => a - b); if (!availableDays.length) return toast('Selecciona almenys un dia de treball');
      const teleDays = [...new Set(workPattern.weeks.flatMap((week) => week.teleDays))].sort((a, b) => a - b);
      const agendaPreferences = Object.fromEntries($$('[data-agenda-preference]', formElement).map((input) => [input.closest('.agenda-capability').querySelector('[name="allowed"]').value, Number(input.value)]).filter(([, value]) => value));
      const id = form.get('id'); const payload = { name: form.get('name').trim(), email: form.get('email').trim(), active: form.get('active') === 'on', vacationDates: modal.vacationDates, workPattern, availableDays, teleDays, allowedTypes, agendaPreferences, ...(managementEnabled ? { managementQuota } : {}), fixedRules };
      const tab = modal.tab; const vacationMonth = modal.vacationMonth;
      try { const saved = await api.saveMember(id, payload); await finishMemberSave(saved, tab, vacationMonth); }
      catch (error) { if (error.code === 'SHARED_FIXED_RULE_CONFIRMATION_REQUIRED' && error.details?.rules?.length) { modal = { type: 'shared-fixed-rule-confirm', id, payload, rules: error.details.rules, tab, vacationMonth }; render(); return; } throw error; }
      return;
    }
    if (formId === 'delete-member-form') {
      if (form.get('confirmation') !== 'ELIMINAR') return toast('Escriu ELIMINAR exactament');
      const id = form.get('id'); await api.deleteMember(id); selectedMemberFilters.delete(id); modal = null; await reloadState('Membre eliminat'); render(); return;
    }
    if (formId === 'agenda-form') {
      const { id, payload } = agendaFormPayload(formElement); if (!payload.hospitalId) return toast('Selecciona un hospital vàlid');
      try { await api.saveAgenda(id, payload); }
      catch (error) { if (error.code === 'FIXED_RULE_CAPACITY' && error.details?.rules?.length) { modal = { type: 'agenda-rule-conflict', id, payload, rules: error.details.rules }; render(); return; } throw error; }
      modal = null; await reloadState('Agenda desada'); render(); return;
    }
    if (formId === 'assignment-exchange-form') {
      await api.exchangeAssignments(form.get('id'), form.get('targetAssignmentId'), form.get('confirmFixed') === 'true');
      modal = null; await reloadState('Intercanvi aplicat'); render(); return;
    }
    if (formId === 'extra-assignment-form') {
      await api.openExtraAssignment(form.get('date'), form.get('memberId'), form.get('agendaId'));
      modal = null; await reloadState('Plaça extraordinària oberta'); render(); return;
    }
    if (formId === 'hospital-form') {
      const catalogId = form.get('catalogId'); if (!catalogId || !pendingHospitalLocation?.areaAvailable) return toast('Selecciona un hospital dels resultats');
      await api.selectHospital({ catalogId }); pendingHospitalLocation = null; hospitalSearchResults = []; hospitalSearchStatus = ''; hospitalSearchQuery = ''; await reloadState('Hospital afegit'); render(); return;
    }
    if (formId === 'clear-calendar-form') { const startDate = form.get('startDate'); const endDate = form.get('endDate'); if (endDate < startDate) return toast('La data final no pot ser anterior a la data inicial'); if (String(form.get('confirmation') || '').trim().toUpperCase() !== deletionConfirmationWord()) return toast(`${state.language === 'es' ? 'Escribe' : 'Escriu'} ${deletionConfirmationWord()} ${state.language === 'es' ? 'exactamente' : 'exactament'}`); await api.deleteCalendarRange(startDate, endDate); modal = null; await reloadState(); render(); toast('Contingut del calendari eliminat dins del període seleccionat'); return; }
    if (formId === 'holiday-form') { await api.addHoliday(form.get('date')); await reloadState('Configuració desada'); render(); }
  } catch (error) {
    if (formId === 'generation-form') {
      modal.busy = false;
      if (error.code === 'PERIOD_OVERLAP' && error.details?.canReplace) {
        modal.overlap = error.details;
        modal.conflict = `${error.details.events || 0} esdeveniments i ${error.details.vacancies || 0} vacants seran recalculats. Els ${error.details.preservedManualEvents || 0} canvis manuals es conservaran.`;
      } else {
        modal.overlap = null;
        modal.conflict = error.message;
      }
      render();
    }
    else { showError(error); }
  }
}
document.addEventListener('submit', async (event) => {
  if (!['generation-form', 'member-form', 'delete-member-form', 'agenda-form', 'assignment-exchange-form', 'extra-assignment-form', 'hospital-form', 'holiday-form', 'clear-calendar-form'].includes(event.target.getAttribute('id'))) return;
  event.preventDefault(); await handleForm(event.target);
}, true);

document.addEventListener('input', (event) => {
  if (!event.target.matches?.('[data-hospital-search]')) return;
  hospitalSearchQuery = event.target.value;
  clearTimeout(hospitalSearchTimer);
  hospitalSearchTimer = setTimeout(() => searchHospitals(hospitalSearchQuery), 180);
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && modal) { modal = null; render(); return; }
  const opener = event.target.closest?.('[data-calendar-open]'); if (!opener || !['Enter', ' '].includes(event.key)) return; event.preventDefault(); calendarDate = opener.dataset.calendarOpen; calendarView = 'day'; modal = null; syncNavigationUrl('push'); render();
});

window.addEventListener('popstate', () => {
  if (!state) return;
  restoreNavigation();
  modal = null;
  render();
});

async function load() {
  try {
    state = normalizeBootstrapState(await api.bootstrap());
    if (hasCalendarContent()) { quarter = projectionStartMonth(calendarProjection()); calendarDate = `${quarter}-01`; }
    restoreNavigation();
    modal = state.account?.guideOnboardingPending ? { type: 'guide-onboarding' } : null;
    syncNavigationUrl('replace');
    render();
  } catch (error) { loginView(); }
}
load();
