# Plan de implementación integral — LicitAPP

Actualizado: 2026-11-10

## Objetivo

Convertir LicitAPP en un asistente verificable para descubrir oportunidades,
decidir si participar, preparar la propuesta sin omisiones, presentarla por el
canal correcto y aprender de los resultados. LicitAPP prepara y controla la
oferta; la presentación final siempre la realiza el usuario.

## Reglas de entrega

- Ningún dato contractual se inventa: debe venir de SECOP, del documento oficial
  o del usuario.
- Todo requisito extraído debe conservar documento, página y fragmento de origen.
- La falta de información se muestra como `Sin verificar`, nunca como cumplimiento.
- Una oferta solo llega al 100 % con evidencia, revisión y controles críticos completos.
- Cada fase exige pruebas automatizadas, validación con procesos reales, commit,
  compilación, verificación HTTP 200, instalación y actualización de GitHub.
- Los expedientes y datos existentes del usuario nunca se sobrescriben.

## Estados

- `[ ]` Pendiente
- `[~]` En desarrollo
- `[x]` Implementado y validado

## Base ya terminada

- [x] Explorador con filtros de ubicación, modalidad, sector y entidad.
- [x] Apertura del expediente oficial en SECOP II.
- [x] Comparables de entidad con ampliación progresiva y estado de cobertura.
- [x] Biblioteca reutilizable de documentos del proponente.
- [x] Checklist verificable por oferta.
- [x] Evaluación preliminar de experiencia, finanzas y capacidad jurídica.
- [x] Ficha `PARTICIPAR / REVISAR / DESCARTAR` con trazabilidad y margen.
- [x] Calculadora con cinco fórmulas y precio propio sin competidores.

---

## Fase 1 — Resumen verificable del pliego

**Estado:** `[~] En desarrollo` — primer incremento implementado.

**Resultado:** una persona sin experiencia entiende qué compra la entidad, qué
debe acreditar y dónde aparece cada exigencia.

- [~] Descargar y catalogar pliego, anexos, formatos y adendas disponibles.
- [~] Extraer texto de PDF nativo y aplicar OCR local a documentos escaneados.
- [ ] Detectar: objeto, alcance, presupuesto, cronograma, experiencia, indicadores,
  personal, equipos, licencias, garantías, documentos y causales de rechazo.
- [x] Mostrar documento, página y fragmento para cada hallazgo.
- [~] Permitir corregir, confirmar o descartar cada hallazgo automático.
- [~] Convertir requisitos confirmados en la matriz y el checklist de la oferta.
- [x] Mostrar estado de lectura: completo, parcial, escaneado o fallido.
- [x] Cargar y analizar conjuntamente pliego, anexos y adendas conservando su procedencia.
- [x] Señalar menciones potencialmente relevantes en adendas sin afirmar automáticamente que son cambios.

**Aceptación:** probar al menos 10 procesos de modalidades y sectores distintos;
ningún requisito sin referencia puede presentarse como confirmado.

## Fase 2 — Expediente empresarial inteligente

**Resultado:** los soportes de la empresa se registran una vez y LicitAPP propone
los adecuados para cada proceso.

- [ ] Ficha de cada documento con empresa/integrante, expedición, vencimiento,
  firmante, categoría, versión y estado de aprobación.
- [ ] Alertas de vencimiento a 60, 30, 15 y 7 días.
- [ ] Búsqueda, filtros, reemplazo de versión y prevención de duplicados.
- [ ] Validación de legibilidad, archivo faltante y vigencia.
- [ ] Separación entre documentos reutilizables y documentos específicos del proceso.
- [ ] Exportar e importar copia de seguridad del expediente empresarial.

**Aceptación:** crear una segunda oferta reutilizando soportes vigentes sin copiar
documentos vencidos ni específicos de la primera.

## Fase 3 — Banco inteligente de experiencia

**Resultado:** LicitAPP selecciona la combinación de contratos que mejor cumple.

- [ ] Registrar contrato, objeto, alcance, fechas, valor ejecutado, moneda, SMMLV,
  participación, consorcio, UNSPSC y actividades acreditadas.
- [ ] Vincular certificado, contrato, acta de recibo/liquidación y página probatoria.
- [ ] Registrar observaciones y aprobación interna de la evidencia.
- [ ] Calcular valor computable según participación y reglas del pliego.
- [ ] Optimizar la combinación dentro del máximo de contratos permitido.
- [ ] Explicar por qué cada contrato fue elegido o excluido.
- [ ] Detectar capacidad faltante y apoyar decisiones de consorcio.

**Aceptación:** reproducir manualmente tres matrices de experiencia reales y obtener
el mismo resultado, mostrando cada operación.

## Fase 4 — Adendas y vigilancia del proceso

**Resultado:** ningún cambio oficial deja obsoleta una propuesta sin advertencia.

- [ ] Guardar huella y versión de documentos oficiales.
- [ ] Detectar documentos nuevos o modificados.
- [ ] Comparar versiones y resumir cambios verificables.
- [ ] Identificar impacto sobre fechas, requisitos, garantía, precio y formatos.
- [ ] Reabrir automáticamente controles afectados.
- [ ] Registrar fecha de última comprobación y cobertura de la consulta.

**Aceptación:** al introducir una adenda de prueba, el sistema señala exactamente
qué requisito y documento preparado debe revisarse.

## Fase 5 — Control de calidad documental

**Resultado:** evitar rechazos por errores formales antes de cargar la propuesta.

- [ ] Detectar campos vacíos, fechas antiguas, referencias a otra entidad/proceso,
  archivos ilegibles, documentos vencidos y posibles firmas faltantes.
- [ ] Comparar total económico entre formulario, carta y valor de la oferta.
- [ ] Verificar que se usó la última versión de cada formato oficial.
- [ ] Revisar nombres, NIT y porcentajes de integrantes en todos los documentos.
- [ ] Generar informe de hallazgos críticos, advertencias y controles aprobados.
- [ ] Bloquear el 100 % mientras exista un hallazgo crítico abierto.

**Aceptación:** conjunto de expedientes con errores sembrados; detección completa de
los errores críticos sin modificar silenciosamente documentos oficiales.

## Fase 6 — Calculadora económica integral

**Resultado:** conocer precio, margen y riesgo de caja, incluso sin datos de rivales.

- [ ] Costos directos, indirectos, AIU, impuestos, retenciones, garantías, logística,
  contingencia y financiación.
- [ ] Cantidades, precios unitarios y total por lote.
- [ ] Plazo de pago y costo financiero del retraso.
- [ ] Escenarios optimista, probable y crítico.
- [ ] Precio mínimo sostenible y margen mínimo configurables.
- [ ] Comparación con presupuesto y distribución histórica verificable.
- [ ] Alertas por pérdida esperada, precio artificialmente bajo e inconsistencias.

**Aceptación:** cada resultado debe poder reconstruirse desde sus entradas y exportarse.

## Fase 7 — Plantillas y generación asistida

**Resultado:** preparar documentos repetitivos preservando el formato oficial.

- [ ] Biblioteca de plantillas DOCX/XLSX/PDF por entidad y modalidad.
- [ ] Detectar y mapear campos variables con confirmación del usuario.
- [ ] Rellenar datos de empresa, proceso, integrantes, experiencia y precio.
- [ ] Conservar fórmulas, estilos, tablas y estructura oficial.
- [ ] Nunca fabricar firmas ni alterar certificados de terceros.
- [ ] Comparar el resultado contra la plantilla de origen.

**Aceptación:** generar tres paquetes con plantillas reales sin perder formato ni fórmulas.

## Fase 8 — Centro de tareas, calendario y alertas

**Resultado:** cada oferta tiene responsables, fechas y avance verificable.

- [ ] Responsables técnico, jurídico, financiero, económico y coordinador.
- [ ] Tareas, dependencias, prioridad, fecha y evidencia de terminación.
- [ ] Cronograma del proceso y recordatorios locales.
- [ ] Tablero por oferta y tablero global de próximos vencimientos.
- [ ] Historial de cambios y reapertura de tareas por adendas.
- [ ] Modos principiante y experto.

**Aceptación:** ninguna tarea vencida o requisito crítico puede quedar oculto detrás
de un porcentaje agregado.

## Fase 9 — Competencia, simulación y aprendizaje

**Resultado:** usar datos históricos para orientar decisiones, no para prometer resultados.

- [ ] Identidad consolidada de entidades y proveedores por NIT y alias.
- [ ] Participación, adjudicación, descuentos, recurrencia y consorcios por contexto.
- [ ] Calidad, periodo, cobertura y limitaciones visibles en cada indicador.
- [ ] Simulador de evaluación cuando el pliego publique reglas calculables.
- [ ] Registro de ofertas ganadas, perdidas, descartadas y causa.
- [ ] Lectura del informe de evaluación y conversión de observaciones en mejoras.
- [ ] Comparador de oportunidades y priorización de capacidad del equipo.

**Aceptación:** contrastar indicadores contra una muestra manual y mantener separado
lo observado, lo calculado y lo inferido.

## Fase 10 — Plataforma, seguridad y operación

**Resultado:** datos recuperables, aislados y preparados para crecer.

- [ ] Persistencia transaccional en SQLite fuera del estado de pantalla.
- [ ] Migraciones de datos compatibles con versiones anteriores.
- [ ] Copia de seguridad, restauración y prueba periódica de recuperación.
- [ ] Cifrado de secretos usando almacenamiento seguro de Windows.
- [ ] Usuarios, roles y separación de empresas cuando se habilite modo multiusuario.
- [ ] Registro de auditoría sin contraseñas ni documentos sensibles.
- [ ] Diagnóstico de conectividad y distinción entre cero real, consulta fallida y sin datos.
- [ ] Actualización segura de la aplicación y documentación de soporte.

**Aceptación:** restaurar una copia en una instalación limpia y comprobar que ofertas,
documentos, trazabilidad y configuración se conservan.

---

## Entregas transversales

- [ ] Buscador en lenguaje natural con filtros transparentes y editables.
- [ ] Índice documental y exportación ordenada del expediente.
- [ ] Dashboard gerencial de oportunidades, propuestas, resultados y rentabilidad.
- [ ] Accesibilidad: textos claros, ayudas contextuales, teclado y contraste.
- [ ] Rendimiento: consultas paginadas, caché explícita y trabajo pesado en segundo plano.
- [ ] Manual dentro de la aplicación con ejemplos y glosario SECOP.

## Métricas de éxito

- Tasa de ceros falsos en comparables.
- Tiempo desde encontrar un proceso hasta decidir si participar.
- Tiempo para preparar una segunda oferta usando el expediente empresarial.
- Cantidad de omisiones críticas detectadas antes de presentar.
- Porcentaje de requisitos con fuente, página y evidencia.
- Procesos presentados, habilitados, adjudicados y margen real.
- Causas de descarte y pérdida más frecuentes.

## Orden de ejecución inmediato

1. Fase 1: modelo de hallazgos verificables y lector de PDF/OCR.
2. Integración de hallazgos con la ficha de decisión y checklist existentes.
3. Prueba con 10 procesos reales y corrección de falsos positivos.
4. Fase 2: expediente empresarial versionado.
5. Fase 3: banco de experiencia y optimizador de contratos.

