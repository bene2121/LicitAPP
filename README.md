# 🏗️ SECOP Automatizador — Obras Civiles

Aplicativo para detectar, analizar y ganar licitaciones públicas en Colombia (SECOP I & II).

El siguiente objetivo, después de las notificaciones automáticas, es el **asistente de pre-oferta**. Está descrito en [ROADMAP.md](ROADMAP.md). Aún no está implementado.

## Instalación

```bash
cd secop-automatizador
pip install -r requirements.txt
playwright install chromium   # solo necesario para el bot (Fase 5)
```

## Configuración

```bash
cp .env.example .env
# Edita .env con tu NIT y preferencias
```

## Uso

### 1. Descargar procesos de SECOP
```bash
python m1_ingestor/ingestor.py
```

### 2. Abrir el dashboard
```bash
python m5_dashboard/run.py
# Abre http://localhost:8501
```

El dashboard tiene 3 secciones:
- **🎯 Oportunidades** — procesos rankeados por probabilidad de ganar
- **🧮 Simulador** — calcula tu oferta óptima con las 5 fórmulas del SECOP
- **📋 Mis Ofertas** — historial de ofertas presentadas

## Estructura del proyecto

```
secop-automatizador/
├── config.py              ← configuración central
├── requirements.txt
├── .env.example
├── m1_ingestor/           ← descarga y almacena datos SECOP
│   ├── secop_client.py    ← cliente API Socrata
│   ├── db_schema.py       ← esquema SQLite
│   └── ingestor.py        ← sincronización incremental
├── m2_formulas/           ← motor de cálculo de ofertas
│   ├── formula_engine.py  ← 5 fórmulas SECOP (M, MG, MAB, MAA, MV)
│   └── optimizador.py     ← encuentra el precio óptimo
├── m3_filtrado/           ← scoring y priorización de procesos
│   └── process_filter.py
├── m4_bot/                ← automatización SECOP 2 (Fase 5)
├── m5_dashboard/          ← interfaz Streamlit
│   └── app.py
├── tests/                 ← tests pytest
└── data/                  ← secop.db (base de datos local)
```

## Fases de desarrollo

| Fase | Estado | Descripción |
|------|--------|-------------|
| F1 Ingestor | ✅ Listo | API Socrata + SQLite |
| F2 Fórmulas | ✅ Listo | 5 métodos + optimizador (23/23 tests) |
| F3 Filtrado | ✅ Listo | Scoring de oportunidad |
| F4 Dashboard | ✅ Listo | Streamlit con simulador interactivo |
| F5 Bot SECOP 2 | 🔜 Pendiente RUP | Playwright — presentación automática |
| F6 Scheduler | 🔜 Próximo | Ejecución diaria automática |
