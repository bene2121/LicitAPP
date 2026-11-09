"""Dashboard SECOP Automatizador — Obras Civiles (v2 multipage)."""
import os, sys, json, sqlite3, unicodedata
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ── Validación de licencia ─────────────────────────────────────────────────────
try:
    from licencias import resolver_acceso, LicenciaInvalida
    try:
        _LICENCIA_INFO = resolver_acceso()
    except LicenciaInvalida as _e:
        import streamlit as _st
        _st.set_page_config(page_title="SECOP — Licencia", page_icon="🔒", layout="centered")
        _st.error("## 🔒 Acceso bloqueado — Licencia inválida o vencida")
        _st.markdown(f"> {str(_e).replace(chr(10), '  ')}")
        _st.markdown("**Para renovar o adquirir tu licencia:**  \n📧 polymodulospvc@gmail.com")
        _st.stop()
except ImportError as _imp_err:
    # C-2: El módulo de licencias no puede estar ausente — bloquear app
    import streamlit as _st
    _st.set_page_config(page_title="LicitApp — Error", page_icon="🔒", layout="centered")
    _st.error("## 🔒 Error crítico de instalación")
    _st.markdown(
        f"El módulo de licencias no está disponible (`{_imp_err}`).\n\n"
        "Reinstala la aplicación o contacta soporte:\n"
        "📧 polymodulospvc@gmail.com"
    )
    _st.stop()
# ───────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_PATH
from m1_ingestor.entidades import ENTIDADES, es_entidad
from m6_propuesta.armar import armar_propuesta
try:
    from m2_formulas.optimizador import optimizar_todas
    _HAS_ENGINE = True
except Exception:
    _HAS_ENGINE = False

try:
    from m3_filtrado.process_filter import get_oportunidades_top
    _HAS_FILTER = True
except Exception:
    _HAS_FILTER = False

st.set_page_config(
    page_title="SECOP Automatizador",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilos globales ──────────────────────────────────────────────────────────
st.markdown("""
<style>
:root {
    --secop-blue: #1F4E79;
    --secop-ok: #28a745;
    --secop-warn: #fd7e14;
}
.metric-card {
    background: #f0f4f8;
    border-left: 4px solid #1F4E79;
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
}
.score-bar-wrap { display:flex; align-items:center; gap:8px; }
.score-num { font-weight:700; min-width:32px; color:#1F4E79; }
.tag-conv  { background:#d4edda; color:#155724; padding:2px 8px; border-radius:12px; font-size:0.78rem; }
.tag-inv   { background:#cce5ff; color:#004085; padding:2px 8px; border-radius:12px; font-size:0.78rem; }
.tag-exp   { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:12px; font-size:0.78rem; }
</style>
""", unsafe_allow_html=True)

DEPARTAMENTOS_CO = [
    "AMAZONAS", "ANTIOQUIA", "ARAUCA", "ATLANTICO", "BOGOTA", "BOLIVAR",
    "BOYACA", "CALDAS", "CAQUETA", "CASANARE", "CAUCA", "CESAR", "CHOCO",
    "CORDOBA", "CUNDINAMARCA", "GUAINIA", "GUAVIARE", "HUILA", "LA GUAJIRA",
    "MAGDALENA", "META", "NARINO", "NORTE DE SANTANDER", "PUTUMAYO", "QUINDIO",
    "RISARALDA", "SAN ANDRES", "SANTANDER", "SUCRE", "TOLIMA", "VALLE DEL CAUCA",
    "VAUPES", "VICHADA",
]

MODALIDADES = [
    "Licitación Pública", "Mínima Cuantía", "Menor Cuantía",
    "Invitación Abierta", "Selección Abreviada", "Concurso de Méritos",
    "Contratación Directa", "Régimen Especial",
]

ESTADOS = [
    "Presentación de oferta",
    "Fase de ofertas",
    "Manifestación de interés (Menor Cuantía)",
    "Fase de Selección (Presentación de ofertas)",
    "Presentación de observaciones",
]

# DATA_DIR compatible con PyInstaller frozen exe
def _get_data_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

DATA_DIR = _get_data_dir()
PERFIL_PATH = os.path.join(DATA_DIR, "perfil_proponente.json")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar(s):
    base = unicodedata.normalize("NFD", str(s or ""))
    plano = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return plano.upper().strip()


def _departamento(s):
    plano = _normalizar(s)
    if "BOGOTA" in plano:
        return "BOGOTA"
    return plano


def fmt_cop(v):
    try:
        return f"$ {float(v):,.0f}".replace(",", ".")
    except Exception:
        return "-"


def dias_al_cierre(fecha_iso):
    try:
        cierre = datetime.fromisoformat(str(fecha_iso))
        return max(0, (cierre - datetime.now()).days)
    except Exception:
        return None


def estado_tag(estado):
    mapa = {
        "CONVOCADO": '<span class="tag-conv">CONVOCADO</span>',
        "INVITACION_ABIERTA": '<span class="tag-inv">INVITACIÓN ABIERTA</span>',
        "EXPRESION_DE_INTERES": '<span class="tag-exp">EXPRESIÓN DE INTERÉS</span>',
    }
    return mapa.get(str(estado).upper(), estado)


def cargar_procesos():
    """Retorna (lista_de_dicts, origen). origen es 'local' o 'vacio'."""
    if _HAS_FILTER and os.path.exists(DB_PATH):
        try:
            df = get_oportunidades_top(DB_PATH, top_n=100)
            if not df.empty:
                records = df.to_dict("records")
                for r in records:
                    if "dias_al_cierre" not in r:
                        r["dias_al_cierre"] = dias_al_cierre(r.get("fecha_cierre"))
                return records, "local"
        except Exception:
            pass
    return [], "vacio"


def cargar_perfil():
    if os.path.exists(PERFIL_PATH):
        try:
            with open(PERFIL_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "empresa": "", "nit": "", "email": "", "telefono": "",
        "rup_vigencia": "", "cc_vigencia": "", "indice_liquidez": "",
        "endeudamiento": "", "capital_trabajo": "", "patrimonio": "",
        "k_contratacion": 0,
        "contratos": [],
        "personal": [],
        "documentos": {},
        "historial_ofertas": [],
        "socios": [],
    }


UNSPSC_FAMILIAS = {
    "72 — Obras civiles y construcción": "72",
    "44 — Equipos de oficina y suministros": "44",
    "25 — Maquinaria y equipo industrial": "25",
    "73 — Servicios de mantenimiento": "73",
    "81 — Servicios de ingeniería": "81",
    "72.10 — Carreteras y pavimentos": "7210",
    "72.11 — Puentes y estructuras": "7211",
    "72.12 — Edificios y construcciones": "7212",
    "72.15 — Obras hidráulicas y acueductos": "7215",
    "40 — Distribución eléctrica y materiales": "40",
}


def cargar_procesos_api(filtros: dict = None) -> tuple:
    """Retorna (lista_de_dicts, origen). origen es 'api', 'local' o 'vacio'."""
    try:
        from api_client import get_procesos
        params = filtros or {}
        params.setdefault("page_size", 200)
        resultado = get_procesos(**params)
        if not resultado.get("error") and resultado.get("items"):
            items = resultado["items"]
            for p in items:
                if "dias_al_cierre" not in p:
                    p["dias_al_cierre"] = dias_al_cierre(p.get("fecha_cierre"))
            return items, "api"
    except Exception:
        pass
    return cargar_procesos()


def guardar_perfil(perfil):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PERFIL_PATH, "w", encoding="utf-8") as f:
        json.dump(perfil, f, ensure_ascii=False, indent=2)


# ── session_state defaults ────────────────────────────────────────────────────
if "perfil" not in st.session_state:
    st.session_state.perfil = cargar_perfil()
if "proceso_seleccionado" not in st.session_state:
    st.session_state.proceso_seleccionado = None
if "oferta_guardada" not in st.session_state:
    st.session_state.oferta_guardada = None
if "tab_activo" not in st.session_state:
    st.session_state.tab_activo = 0

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0; color:#1F4E79;'>🏗️ SECOP Automatizador <span style='font-size:1rem;font-weight:400;'>— Obras Civiles</span></h1>",
    unsafe_allow_html=True,
)

_dias_lic = _LICENCIA_INFO.get("dias_restantes", 0)
_plan_lic = str(_LICENCIA_INFO.get("plan", "demo")).upper()
_nombre_lic = _LICENCIA_INFO.get("nombre", "")

if _dias_lic <= 7:
    st.warning(
        f"⚠️ Tu suscripción **{_plan_lic}** vence en **{_dias_lic} días**. "
        "Renueva en: polymodulospvc@gmail.com"
    )
else:
    st.caption(
        f"✅ Plan **{_plan_lic}** | Vence en {_dias_lic} días "
        f"| Cliente: {_nombre_lic}"
    )

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🔍 EXPLORADOR",
    "🧮 CALCULADORA DE OFERTAS",
    "📁 MIS DOCUMENTOS",
    "🤝 CONSORCIOS",
    "🕵️ COMPETIDORES",
    "📌 SEGUIMIENTO",
    "📄 PROPUESTA",
    "⚙️ MI CUENTA",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — EXPLORADOR
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    # ── Sidebar con filtros avanzados ─────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🔍 Filtros")
        perfil_filtros = st.session_state.perfil
        usar_perfil = st.toggle("Aplicar filtros de mi perfil", value=True, key="usar_perfil_tog")
        if st.button("🗑️ Limpiar todos los filtros", key="btn_limpiar"):
            for k in ["deptos_sel_adv","modal_sel_adv","estado_sel_adv","unspsc_sel_adv",
                      "mun_txt_adv","ent_txt_adv","texto_busq_adv","dias_max_adv",
                      "score_min_adv","fuente_sel_adv"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

        texto_busq = st.text_input("🔍 Buscar objeto / entidad / ID",
                                   placeholder="pavimentación, IDU, CO1.BDOS...",
                                   key="texto_busq_adv")

        st.markdown("**📍 Geografía**")
        deptos_sel = st.multiselect(
            "Departamento", DEPARTAMENTOS_CO, key="deptos_sel_adv",
            default=perfil_filtros.get("departamentos", []) if usar_perfil else [],
        )
        municipio_txt = st.text_input("Municipio", placeholder="Zipaquirá, Chía...", key="mun_txt_adv")

        st.markdown("**🏗️ Sector UNSPSC**")
        unspsc_sel_labels = st.multiselect(
            "Sector / Código UNSPSC", list(UNSPSC_FAMILIAS.keys()),
            default=[k for k, v in UNSPSC_FAMILIAS.items()
                     if v in perfil_filtros.get("sectores_unspsc", [])] if usar_perfil else [],
            key="unspsc_sel_adv",
        )
        unspsc_codes = [UNSPSC_FAMILIAS[l] for l in unspsc_sel_labels]

        st.markdown("**📋 Proceso**")
        modal_sel  = st.multiselect("Modalidad", MODALIDADES, key="modal_sel_adv")
        estado_sel = st.multiselect(
            "Estado", ESTADOS, key="estado_sel_adv",
            default=["Presentación de oferta", "Fase de ofertas"] if usar_perfil else [],
        )
        fuente_sel = st.radio(
            "Fuente",
            ["Ambas", "SECOP II", "Ecopetrol", "Findeter"],
            horizontal=True,
            key="fuente_sel_adv",
        )
        entidad_txt = st.text_input("Entidad contratante", placeholder="IDU, Gobernación...",
                                    key="ent_txt_adv")

        st.markdown("**💰 Presupuesto Oficial**")
        po_def_min = int(perfil_filtros.get("presupuesto_min", 0)) if usar_perfil else 0
        po_def_max = int(perfil_filtros.get("presupuesto_max", 2_000_000_000)) if usar_perfil else 2_000_000_000
        rango_ppto = st.slider(
            "Rango COP", 0, 2_000_000_000, (po_def_min, po_def_max),
            step=5_000_000, format="$%d", key="rango_ppto",
            label_visibility="collapsed",
        )
        dias_max    = st.slider("Días máx. al cierre", 1, 180, 90, key="dias_max_adv")
        score_min_f = st.slider("Score mínimo", 0, 100, 60, key="score_min_adv")

    # Construir filtros para la API
    filtros_api = {}
    if deptos_sel:
        filtros_api["departamento"] = deptos_sel[0] if len(deptos_sel) == 1 else None
    if municipio_txt:
        filtros_api["municipio"] = municipio_txt
    fuente_especial = fuente_sel in ("Ecopetrol", "Findeter")
    if unspsc_codes and not fuente_especial:
        fams  = [c for c in unspsc_codes if len(c) == 2]
        clases = [c for c in unspsc_codes if len(c) == 4]
        if fams:   filtros_api["unspsc_familia"] = fams[0]
        if clases: filtros_api["unspsc_clase"]   = clases[0]
    if modal_sel:
        filtros_api["modalidad"] = modal_sel[0]
    if estado_sel:
        filtros_api["estado"] = ",".join(estado_sel)
    if fuente_sel == "Ecopetrol":
        filtros_api["entidad"] = "EMPRESA COLOMBIANA DE PETROLEOS"
    elif fuente_sel == "Findeter":
        filtros_api["entidad"] = "FINANCIERA DE DESARROLLO TERRITORIAL"
    elif fuente_sel == "SECOP II":
        filtros_api["fuente"] = "SECOP2"
    if texto_busq:
        filtros_api["q"] = texto_busq
    if entidad_txt:
        filtros_api["entidad"] = entidad_txt
    filtros_api["po_min"]         = rango_ppto[0]
    filtros_api["po_max"]         = rango_ppto[1]
    if not fuente_especial:
        filtros_api["score_min"] = float(score_min_f)
    filtros_api["dias_cierre_max"] = dias_max

    # Eliminar claves con valor None
    filtros_api = {k: v for k, v in filtros_api.items() if v is not None}

    procesos_todos, origen = cargar_procesos_api(filtros_api)

    if fuente_especial:
        codigo_fuente = "ECOPETROL" if fuente_sel == "Ecopetrol" else "FINDETER"
        st.info(ENTIDADES[codigo_fuente]["canal_oferta"])

    if origen == "vacio":
        st.info(
            "No hay procesos reales cargados. "
            "Ejecuta `python m1_ingestor/ingestor.py` para sincronizar SECOP, Ecopetrol y Findeter.",
            icon="ℹ️",
        )

    # ── Filtrar ───────────────────────────────────────────────────────────────
    filtrados = []
    for p in procesos_todos:
        # texto
        if texto_busq:
            haystack = _normalizar(
                f"{p.get('objeto','')} {p.get('titulo','')} {p.get('entidad','')} {p.get('id','')}"
            )
            if _normalizar(texto_busq) not in haystack:
                continue
        if (
            not fuente_especial
            and deptos_sel
            and _departamento(p.get("departamento") or p.get("departamento_entidad"))
            not in [_departamento(d) for d in deptos_sel]
        ):
            continue
        # modalidad
        if modal_sel:
            p_mod = _normalizar(p.get("modalidad", ""))
            if not any(_normalizar(m) in p_mod or p_mod in _normalizar(m) for m in modal_sel):
                continue
        # estado
        if estado_sel and _normalizar(p.get("estado", "")) not in [_normalizar(e) for e in estado_sel]:
            continue
        # presupuesto
        po = float(p.get("presupuesto_oficial", 0) or 0)
        if not (rango_ppto[0] <= po <= rango_ppto[1]):
            continue
        # dias
        d = p.get("dias_al_cierre")
        if d is not None and d > dias_max:
            continue
        if unspsc_codes and not fuente_especial:
            p_unspsc = str(p.get("unspsc", ""))
            if not any(p_unspsc.startswith(c) for c in unspsc_codes):
                continue
        if not fuente_especial and p.get("score", 0) < score_min_f:
            continue
        if fuente_especial and not es_entidad(
            {"nit_entidad": p.get("nit_entidad"), "entidad": p.get("entidad")},
            "ECOPETROL" if fuente_sel == "Ecopetrol" else "FINDETER",
        ):
            continue
        filtrados.append(p)

    # ── Métricas superiores ───────────────────────────────────────────────────
    total_po = sum(float(p.get("presupuesto_oficial", 0) or 0) for p in filtrados)
    dias_list = [p["dias_al_cierre"] for p in filtrados if p.get("dias_al_cierre") is not None]
    avg_dias = sum(dias_list) / len(dias_list) if dias_list else 0

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Procesos encontrados", len(filtrados))
    mc2.metric("Suma presupuestos", fmt_cop(total_po))
    mc3.metric("Promedio días al cierre", f"{avg_dias:.0f} días" if dias_list else "–")

    st.markdown("---")

    if origen == "vacio":
        pass
    elif not filtrados:
        st.warning("No hay procesos que cumplan los filtros seleccionados.")
    else:
        # ── Tabla de resultados ───────────────────────────────────────────────
        rows = []
        for p in sorted(filtrados, key=lambda x: -x.get("score", 0)):
            nombre = p.get("objeto") or p.get("titulo") or ""
            nombre_trunc = nombre[:60] + "…" if len(nombre) > 60 else nombre
            d = p.get("dias_al_cierre")
            cierre_str = ""
            try:
                cierre_str = datetime.fromisoformat(str(p["fecha_cierre"])).strftime("%d/%m/%Y")
            except Exception:
                cierre_str = str(p.get("fecha_cierre", ""))[:10]

            rows.append({
                "_id": p.get("id") or p.get("id_del_proceso", ""),
                "Score 🎯": int(p.get("score", 0)),
                "Entidad": p.get("entidad", ""),
                "Objeto": nombre_trunc,
                "Modalidad": p.get("modalidad", ""),
                "P.O. (COP)": fmt_cop(p.get("presupuesto_oficial", 0)),
                "Cierre": cierre_str,
                "Días": d if d is not None else "–",
                "Estado": str(p.get("estado", "")),
            })

        df_tabla = pd.DataFrame(rows)

        # Mostrar tabla interactiva con botones de acción
        st.markdown("### Resultados")

        # Cabecera
        hc = st.columns([1, 2, 3, 2, 2, 1, 1, 2])
        for col, header in zip(hc, ["Score 🎯", "Entidad", "Objeto", "Modalidad", "P.O. (COP)", "Cierre", "Días", "Acción"]):
            col.markdown(f"**{header}**")
        st.markdown("<hr style='margin:2px 0 8px 0'>", unsafe_allow_html=True)

        for i, row in enumerate(rows):
            score = row["Score 🎯"]
            color = "#28a745" if score >= 75 else ("#fd7e14" if score >= 50 else "#dc3545")

            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1, 2, 3, 2, 2, 1, 1, 2])
            c1.markdown(
                f"<div class='score-bar-wrap'><span class='score-num' style='color:{color}'>{score}</span></div>",
                unsafe_allow_html=True,
            )
            c1.progress(score / 100)
            c2.markdown(f"<small>{row['Entidad']}</small>", unsafe_allow_html=True)
            c3.markdown(f"<small>{row['Objeto']}</small>", unsafe_allow_html=True)
            c4.markdown(f"<small>{row['Modalidad']}</small>", unsafe_allow_html=True)
            c5.markdown(f"<small>**{row['P.O. (COP)']}**</small>", unsafe_allow_html=True)
            c6.markdown(f"<small>{row['Cierre']}</small>", unsafe_allow_html=True)
            dias_v = row["Días"]
            dias_color = "red" if isinstance(dias_v, int) and dias_v <= 5 else "inherit"
            c7.markdown(f"<small style='color:{dias_color};font-weight:600'>{dias_v}</small>", unsafe_allow_html=True)
            if c8.button("📋 Preparar oferta", key=f"btn_prep_{i}_{row['_id']}"):
                # Encontrar el proceso completo y guardarlo en session_state
                for p in filtrados:
                    if (p.get("id") or p.get("id_del_proceso", "")) == row["_id"]:
                        st.session_state.proceso_seleccionado = p
                        break
                st.info(
                    f"✅ Proceso seleccionado: **{row['Objeto']}**. "
                    "Calcula el precio en **🧮 CALCULADORA** y ármala en **📄 PROPUESTA**."
                )

            st.markdown("<hr style='margin:2px 0 6px 0; opacity:0.2'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — CALCULADORA DE OFERTAS
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.subheader("🧮 Calculadora de Ofertas — 5 Fórmulas SECOP")

    # Si llegó un proceso seleccionado desde Tab 1
    proc_sel = st.session_state.get("proceso_seleccionado")
    if proc_sel:
        st.success(
            f"📌 Proceso pre-cargado: **{proc_sel.get('objeto') or proc_sel.get('titulo','')}** "
            f"| P.O.: {fmt_cop(proc_sel.get('presupuesto_oficial', 0))}"
        )

    col_inp1, col_inp2, col_inp3 = st.columns(3)
    with col_inp1:
        po_default = int(proc_sel.get("presupuesto_oficial", 100_000_000)) if proc_sel else 100_000_000
        po_calc = st.number_input(
            "💰 Presupuesto Oficial (COP)",
            min_value=1_000_000, max_value=10_000_000_000,
            value=po_default, step=1_000_000, format="%d",
        )
    with col_inp2:
        pts_max_calc = st.number_input(
            "🏆 Puntaje máximo precio",
            min_value=100, max_value=1000,
            value=1000, step=50,
        )
    with col_inp3:
        st.caption("El cálculo usa solo las ofertas reales que escribas abajo.")

    # Tabla de ofertas rivales
    st.markdown("**Ofertas reales de rivales** *(al menos una)*")
    rivales_df_init = pd.DataFrame(
        [{"Rival": f"Rival {i+1}", "Precio (COP)": 0} for i in range(5)]
    )
    rivales_edited = st.data_editor(
        rivales_df_init,
        num_rows="dynamic",
        use_container_width=True,
        key="tabla_rivales",
    )
    ofertas_rivales_vals = [
        float(r["Precio (COP)"])
        for _, r in rivales_edited.iterrows()
        if float(r["Precio (COP)"] or 0) > 0
    ]

    # Nota informativa fórmulas
    st.info(
        "📌 **¿Cómo se elige la fórmula en Colombia?**  \n"
        "La fórmula se define en el pliego de condiciones. Cuando el pliego dice "
        "'se seleccionará aleatoriamente', se usa el **ÚLTIMO DÍGITO de la TRM del día del cierre**: "
        "0-1 = MV · 2-3 = M · 4-5 = MG · 6-7 = MAB · 8-9 = MAA.",
        icon="📋",
    )

    if st.button("⚡ Calcular las 5 Fórmulas", type="primary"):
        if not _HAS_ENGINE:
            st.error("Motor de fórmulas no disponible. Verifica la instalación del módulo m2_formulas.")
        elif not ofertas_rivales_vals:
            st.error("Ingresa al menos una oferta real de rival. No se inventan precios.")
        else:
            formulas_info = {
                "M":   {"nombre": "Mediana",               "riesgo": "Medio"},
                "MG":  {"nombre": "Media Geométrica",      "riesgo": "Medio"},
                "MAB": {"nombre": "Media Aritmética Baja", "riesgo": "Alto"},
                "MAA": {"nombre": "Media Aritmética Alta", "riesgo": "Bajo"},
                "MV":  {"nombre": "Menor Valor",           "riesgo": "Alto"},
            }
            try:
                with st.spinner("Calculando ofertas óptimas para las 5 fórmulas…"):
                    resultados_por_formula = optimizar_todas(
                        presupuesto_oficial=float(po_calc),
                        pts_max=float(pts_max_calc),
                        ofertas_historicas=ofertas_rivales_vals,
                    )
            except ValueError as exc:
                st.error(str(exc))
                resultados_por_formula = None

            if resultados_por_formula:
                st.markdown("---")
                st.markdown("### Comparativa de las 5 Fórmulas")

                # Tabla comparativa
                tabla_rows = []
                for cod, fi in formulas_info.items():
                    r = resultados_por_formula[cod]
                    precio = r["oferta_optima"]
                    pct = r["pct_mejora"] * 100
                    puntaje = r["scores"][cod]
                    tabla_rows.append({
                        "Fórmula": cod,
                        "Nombre": fi["nombre"],
                        "Precio Sugerido": precio,
                        "% Mejora P.O.": pct,
                        "Puntaje Esperado": puntaje,
                        "/ Máx.": pts_max_calc,
                        "Riesgo": fi["riesgo"],
                    })

                # Mostrar tabla con radio buttons
                col_radio_sel = st.radio(
                    "Seleccionar fórmula:",
                    options=[r["Fórmula"] for r in tabla_rows],
                    format_func=lambda x: f"{x} — {formulas_info[x]['nombre']}",
                    horizontal=True,
                    key="formula_radio",
                )

                # Header tabla
                th = st.columns([1, 2, 2, 1, 2, 1])
                for c, h in zip(th, ["Fórmula", "Nombre", "Precio Sugerido", "% Mejora", "Puntaje", "Riesgo"]):
                    c.markdown(f"**{h}**")
                st.markdown("<hr style='margin:2px 0 6px 0'>", unsafe_allow_html=True)

                for row in tabla_rows:
                    riesgo_color = {"Alto": "#dc3545", "Medio": "#fd7e14", "Bajo": "#28a745"}.get(row["Riesgo"], "#333")
                    sel = "✅" if row["Fórmula"] == col_radio_sel else "⭕"
                    tc1, tc2, tc3, tc4, tc5, tc6 = st.columns([1, 2, 2, 1, 2, 1])
                    tc1.markdown(f"**{sel} {row['Fórmula']}**")
                    tc2.write(row["Nombre"])
                    tc3.markdown(f"**{fmt_cop(row['Precio Sugerido'])}**")
                    tc4.write(f"{row['% Mejora P.O.']:.1f}%")
                    pct_pts = row["Puntaje Esperado"] / row["/ Máx."]
                    tc5.progress(min(1.0, pct_pts), text=f"{row['Puntaje Esperado']:.0f}/{row['/ Máx.']}")
                    tc6.markdown(f"<span style='color:{riesgo_color};font-weight:600'>{row['Riesgo']}</span>", unsafe_allow_html=True)
                    st.markdown("<hr style='margin:2px 0 4px 0; opacity:0.15'>", unsafe_allow_html=True)

                # Campo "Mi precio final" editable
                selected_precio = resultados_por_formula[col_radio_sel]["oferta_optima"]
                st.markdown("---")
                col_f1, col_f2 = st.columns([2, 1])
                with col_f1:
                    mi_precio_final = st.number_input(
                        f"✏️ Mi precio final para fórmula **{col_radio_sel}** (COP)",
                        min_value=1_000_000, max_value=int(po_calc),
                        value=int(selected_precio), step=100_000, format="%d",
                        key="mi_precio_final",
                    )
                with col_f2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("✅ Usar esta oferta", type="primary"):
                        oferta_info = {
                            "formula": col_radio_sel,
                            "nombre_formula": formulas_info[col_radio_sel]["nombre"],
                            "precio": mi_precio_final,
                            "presupuesto_oficial": po_calc,
                            "pct_mejora": (po_calc - mi_precio_final) / po_calc * 100,
                            "fecha": datetime.now().isoformat(),
                            "proceso": (
                                (proc_sel.get("id") or proc_sel.get("id_del_proceso", ""))
                                if proc_sel else ""
                            ),
                        }
                        st.session_state.oferta_guardada = oferta_info
                        # Guardar en historial del perfil
                        perfil = st.session_state.perfil
                        perfil.setdefault("historial_ofertas", []).append(oferta_info)
                        guardar_perfil(perfil)
                        st.success(
                            f"✅ Oferta guardada: **{fmt_cop(mi_precio_final)}** "
                            f"con fórmula **{col_radio_sel}** ({formulas_info[col_radio_sel]['nombre']})"
                        )

                # Gráfico comparativo de puntajes
                st.markdown("---")
                st.markdown("### 📊 Comparativa de Puntajes por Fórmula")

                fig_bar = go.Figure()
                colores_formula = {
                    "M": "#1F4E79", "MG": "#28a745", "MAB": "#fd7e14",
                    "MAA": "#6f42c1", "MV": "#dc3545",
                }
                puntajes_lista = [resultados_por_formula[c]["scores"][c] for c in ["M", "MG", "MAB", "MAA", "MV"]]
                nombres_lista = [formulas_info[c]["nombre"] for c in ["M", "MG", "MAB", "MAA", "MV"]]
                colores_lista = [colores_formula[c] for c in ["M", "MG", "MAB", "MAA", "MV"]]

                fig_bar.add_trace(go.Bar(
                    y=nombres_lista,
                    x=puntajes_lista,
                    orientation="h",
                    marker_color=colores_lista,
                    text=[f"{p:.0f}" for p in puntajes_lista],
                    textposition="outside",
                ))
                fig_bar.update_layout(
                    xaxis_title="Puntaje", xaxis_range=[0, pts_max_calc * 1.1],
                    height=320, margin=dict(l=10, r=40, t=20, b=20),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_bar, use_container_width=True)

                # Explicación de fórmulas
                with st.expander("ℹ️ ¿Cuándo se usa cada fórmula en Colombia?"):
                    st.markdown("""
| Fórmula | Cuándo se usa |
|---------|---------------|
| **M — Mediana** | Licitaciones con múltiples oferentes; penaliza valores extremos. Equilibrada. |
| **MG — Media Geométrica** | Similar a la Mediana; favorece precios competitivos pero no extremos. |
| **MAB — M.A. Baja** | Usada cuando la entidad quiere incentivar precios bajos. Mayor riesgo de dumping. |
| **MAA — M.A. Alta** | Penaliza fuertemente a quien oferte por encima de la media alta. Favorece calidad. |
| **MV — Menor Valor** | El precio más bajo obtiene el máximo puntaje. Alto riesgo: requiere solidez financiera. |
""")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — MIS DOCUMENTOS
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.subheader("📁 Gestor de Documentos Habilitantes")
    perfil = st.session_state.perfil

    # ── JURÍDICOS ─────────────────────────────────────────────────────────────
    with st.expander("📜 DOCUMENTOS JURÍDICOS", expanded=True):
        def doc_estado_widget(label, key_fecha, key_estado):
            col_d1, col_d2, col_d3 = st.columns([3, 2, 2])
            with col_d1:
                st.markdown(f"**{label}**")
            with col_d2:
                fecha_val = perfil.get("documentos", {}).get(key_fecha, "")
                nueva_fecha = st.text_input("Vencimiento (YYYY-MM-DD)", value=fecha_val, key=f"tf_{key_fecha}", label_visibility="collapsed", placeholder="YYYY-MM-DD")
                perfil.setdefault("documentos", {})[key_fecha] = nueva_fecha
            with col_d3:
                estado_opts = ["✅ Vigente", "⚠️ Por vencer", "❌ Vencido", "📤 Pendiente"]
                estado_val = perfil.get("documentos", {}).get(key_estado, "📤 Pendiente")
                idx = estado_opts.index(estado_val) if estado_val in estado_opts else 3
                nuevo_estado = st.selectbox("Estado", estado_opts, index=idx, key=f"sel_{key_estado}", label_visibility="collapsed")
                perfil["documentos"][key_estado] = nuevo_estado

        doc_estado_widget("RUP Vigente", "rup_fecha", "rup_estado")
        doc_estado_widget("Cámara de Comercio (<30 días)", "cc_fecha", "cc_estado")
        doc_estado_widget("Cédula Representante Legal", "cedula_fecha", "cedula_estado")
        doc_estado_widget("RUT actualizado", "rut_fecha", "rut_estado")

    # ── FINANCIEROS ───────────────────────────────────────────────────────────
    with st.expander("💰 DOCUMENTOS FINANCIEROS"):
        cf1, cf2, cf3, cf4 = st.columns(4)
        perfil["indice_liquidez"] = cf1.text_input(
            "Índice de Liquidez", value=str(perfil.get("indice_liquidez", "")), key="f_liq"
        )
        perfil["endeudamiento"] = cf2.text_input(
            "Endeudamiento (%)", value=str(perfil.get("endeudamiento", "")), key="f_end"
        )
        perfil["capital_trabajo"] = cf3.text_input(
            "Capital de Trabajo (COP)", value=str(perfil.get("capital_trabajo", "")), key="f_cap"
        )
        perfil["patrimonio"] = cf4.text_input(
            "Patrimonio (COP)", value=str(perfil.get("patrimonio", "")), key="f_pat"
        )
        st.markdown("**Estados Financieros**")
        doc_estado_widget_fe = lambda lbl, kf, ks: None
        col_ef1, col_ef2, col_ef3 = st.columns([3, 2, 2])
        col_ef1.markdown("**Estados Financieros año vigente**")
        ef_fecha = perfil.setdefault("documentos", {}).get("ef_fecha", "")
        ef_fecha_new = col_ef2.text_input("Vencimiento EF", value=ef_fecha, key="ef_fecha_input", label_visibility="collapsed", placeholder="YYYY-MM-DD")
        perfil["documentos"]["ef_fecha"] = ef_fecha_new
        ef_estado_opts = ["✅ Vigente", "⚠️ Por vencer", "❌ Vencido", "📤 Pendiente"]
        ef_estado = perfil["documentos"].get("ef_estado", "📤 Pendiente")
        ef_idx = ef_estado_opts.index(ef_estado) if ef_estado in ef_estado_opts else 3
        ef_estado_new = col_ef3.selectbox("Estado EF", ef_estado_opts, index=ef_idx, key="ef_estado_sel", label_visibility="collapsed")
        perfil["documentos"]["ef_estado"] = ef_estado_new

    # ── CAPACIDAD TÉCNICA ─────────────────────────────────────────────────────
    with st.expander("🔧 CAPACIDAD TÉCNICA"):
        perfil["k_contratacion"] = st.number_input(
            "K de Contratación (COP)",
            min_value=0, max_value=100_000_000_000,
            value=int(perfil.get("k_contratacion") or 0),
            step=10_000_000, format="%d",
            key="k_cont_input",
        )
        st.markdown("**Contratos de experiencia**")
        contratos_init = pd.DataFrame(
            perfil.get("contratos") or [],
            columns=["Entidad", "Objeto", "Valor (COP)", "Año", "Estado"],
        ) if perfil.get("contratos") else pd.DataFrame(
            columns=["Entidad", "Objeto", "Valor (COP)", "Año", "Estado"]
        )
        contratos_edit = st.data_editor(
            contratos_init,
            num_rows="dynamic",
            use_container_width=True,
            key="tabla_contratos",
        )
        perfil["contratos"] = contratos_edit.to_dict("records")

    # ── EQUIPO ────────────────────────────────────────────────────────────────
    with st.expander("👷 EQUIPO DE TRABAJO"):
        personal_init = pd.DataFrame(
            perfil.get("personal") or [],
            columns=["Nombre", "Cargo", "Matrícula Profesional", "Años Experiencia"],
        ) if perfil.get("personal") else pd.DataFrame(
            columns=["Nombre", "Cargo", "Matrícula Profesional", "Años Experiencia"]
        )
        personal_edit = st.data_editor(
            personal_init,
            num_rows="dynamic",
            use_container_width=True,
            key="tabla_personal",
        )
        perfil["personal"] = personal_edit.to_dict("records")

    st.markdown("---")
    if st.button("💾 Guardar perfil", type="primary"):
        st.session_state.perfil = perfil
        guardar_perfil(perfil)
        st.success(f"✅ Perfil guardado en `{PERFIL_PATH}`")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — CONSORCIOS
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("🤝 Gestor de Consorcios y Uniones Temporales")
    perfil4 = st.session_state.perfil

    # ── Mi red de socios ──────────────────────────────────────────────────────
    with st.expander("👥 Mi red de socios potenciales", expanded=True):
        socios_init = pd.DataFrame(
            perfil4.get("socios") or [],
            columns=["NIT", "Razón Social", "Contacto", "Especialidad", "Departamento", "K disponible (COP)"],
        ) if perfil4.get("socios") else pd.DataFrame(
            columns=["NIT", "Razón Social", "Contacto", "Especialidad", "Departamento", "K disponible (COP)"]
        )
        socios_edit = st.data_editor(
            socios_init,
            num_rows="dynamic",
            use_container_width=True,
            key="tabla_socios",
        )
        perfil4["socios"] = socios_edit.to_dict("records")
        if st.button("💾 Guardar red de socios"):
            st.session_state.perfil = perfil4
            guardar_perfil(perfil4)
            st.success("Red de socios guardada.")

    # ── Armar consorcio ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🏗️ Armar consorcio para proceso")

    procesos_cons, _ = cargar_procesos()
    opciones_proc = {
        f"{p.get('id',p.get('id_del_proceso',''))} — {(p.get('objeto') or p.get('titulo',''))[:55]}": p
        for p in procesos_cons
    }
    proc_cons = None
    proc_cons_key = None
    if not opciones_proc:
        st.info("No hay procesos reales cargados para armar un consorcio.")
    else:
        proc_cons_key = st.selectbox("Seleccionar proceso", list(opciones_proc.keys()), key="proc_cons_sel")
        proc_cons = opciones_proc.get(proc_cons_key)

    # Armar lista de posibles miembros
    mi_empresa = perfil4.get("empresa", "Mi empresa")
    socios_nombres = [s.get("Razón Social", "") for s in perfil4.get("socios", []) if s.get("Razón Social")]
    miembros_opciones = [mi_empresa] + socios_nombres if mi_empresa else socios_nombres

    miembros_sel = st.multiselect(
        "Miembros del consorcio",
        options=miembros_opciones,
        default=[mi_empresa] if mi_empresa else [],
        key="miembros_cons",
    )

    if miembros_sel:
        st.markdown("**Asignar porcentajes de participación** *(deben sumar 100%)*")
        pcts = {}
        n_mem = len(miembros_sel)
        default_pct = 100 // n_mem
        cols_pct = st.columns(min(n_mem, 4))
        for i, mem in enumerate(miembros_sel):
            with cols_pct[i % 4]:
                pcts[mem] = st.number_input(
                    f"{mem[:20]}", min_value=0, max_value=100,
                    value=default_pct, step=5, key=f"pct_{i}_{mem}",
                )
        total_pct = sum(pcts.values())
        if total_pct == 100:
            st.success(f"✅ Total: {total_pct}% — OK")
        else:
            st.warning(f"⚠️ Total: {total_pct}% — debe ser exactamente 100%")

        # Tabla resumen
        st.markdown("**Verificación de requisitos habilitantes:**")
        k_total = int(perfil4.get("k_contratacion") or 0)
        po_cons = float(proc_cons.get("presupuesto_oficial", 0) or 0) if proc_cons else 0

        check_rows = []
        for mem in miembros_sel:
            socio_info = next((s for s in perfil4.get("socios", []) if s.get("Razón Social") == mem), {})
            k_mem = float(socio_info.get("K disponible (COP)", 0) or 0) if mem != mi_empresa else k_total
            pct_m = pcts.get(mem, 0)
            k_aporte = k_mem * pct_m / 100
            cumple_k = "✅" if k_aporte >= po_cons * pct_m / 100 else "⚠️"
            check_rows.append({
                "Miembro": mem,
                "% Participación": f"{pct_m}%",
                "K disponible": fmt_cop(k_mem),
                "K aportado": fmt_cop(k_aporte),
                "K requerido": fmt_cop(po_cons * pct_m / 100),
                "Cumple K": cumple_k,
            })
        st.dataframe(pd.DataFrame(check_rows), use_container_width=True, hide_index=True)

        # Botón generar acuerdo
        if st.button("📄 Generar acuerdo de consorcio (.txt)"):
            if total_pct != 100:
                st.error("Los porcentajes deben sumar 100% antes de generar el acuerdo.")
            else:
                fecha_hoy = datetime.now().strftime("%d de %B de %Y")
                nombre_consorcio = "CONSORCIO " + " & ".join([m.upper().split()[0] for m in miembros_sel[:3]])
                objeto_cons = (proc_cons.get("objeto") or proc_cons.get("titulo", "")) if proc_cons else ""
                lineas_partic = "\n".join([
                    f"  - {mem}: {pcts[mem]}% de participación"
                    for mem in miembros_sel
                ])
                acuerdo_txt = f"""ACUERDO DE CONSORCIO
====================

Fecha: {fecha_hoy}
Nombre del Consorcio: {nombre_consorcio}
Proceso: {proc_cons_key if proc_cons else 'N/A'}
Objeto del proceso: {objeto_cons}
Presupuesto Oficial: {fmt_cop(po_cons)}

PARTES INTEGRANTES Y PARTICIPACIÓN:
{lineas_partic}

CLÁUSULA PRIMERA — OBJETO
Los abajo firmantes acuerdan conformar el {nombre_consorcio} con el propósito de
participar en el proceso de contratación identificado arriba, bajo los términos
del Pliego de Condiciones y la normativa vigente (Ley 80 de 1993, Ley 1150 de 2007).

CLÁUSULA SEGUNDA — REPRESENTANTE LEGAL
El representante legal del consorcio será designado por acuerdo unánime de los miembros
antes de la presentación de la oferta.

CLÁUSULA TERCERA — RESPONSABILIDAD
Los miembros del consorcio responden SOLIDARIAMENTE ante la entidad contratante
por todas las obligaciones derivadas del proceso de selección y del contrato.

CLÁUSULA CUARTA — VIGENCIA
Este acuerdo tiene vigencia desde su firma hasta la liquidación del contrato resultante
o hasta la no adjudicación del proceso, según corresponda.

CLÁUSULA QUINTA — LEY APLICABLE
Este acuerdo se rige por la legislación colombiana vigente en materia de contratación
pública y derecho comercial.

FIRMAS:
{chr(10).join([f"_____________________________" + chr(10) + f"{mem}" + chr(10) + f"C.C. / NIT: _______________" + chr(10) for mem in miembros_sel])}

Nota: Este documento fue generado por SECOP Automatizador y debe ser revisado
por asesoría jurídica antes de su firma y presentación oficial.
"""
                st.download_button(
                    label="⬇️ Descargar acuerdo.txt",
                    data=acuerdo_txt.encode("utf-8"),
                    file_name=f"acuerdo_consorcio_{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 8 — MI CUENTA
# ─────────────────────────────────────────────────────────────────────────────
with tab8:
    st.subheader("📊 Mi Cuenta")
    perfil5 = st.session_state.perfil

    # ── Licencia ──────────────────────────────────────────────────────────────
    with st.expander("🔑 Información de Licencia", expanded=True):
        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("Plan", _plan_lic)
        lc2.metric(
            "Vencimiento",
            _LICENCIA_INFO.get("fecha_vencimiento", "N/A"),
        )
        dias_lic_v = _LICENCIA_INFO.get("dias_restantes", 0)
        lc3.metric(
            "Días restantes",
            dias_lic_v,
            delta=None if dias_lic_v > 7 else "⚠️ Renovar pronto",
            delta_color="off" if dias_lic_v <= 7 else "normal",
        )
        if dias_lic_v <= 30:
            st.warning("Para renovar tu licencia contacta: **polymodulospvc@gmail.com**")

    # ── Estadísticas ──────────────────────────────────────────────────────────
    with st.expander("📈 Estadísticas de uso", expanded=True):
        historial = perfil5.get("historial_ofertas", [])
        n_ofertas = len(historial)
        n_ganadas = sum(1 for o in historial if o.get("resultado") == "GANADA")
        tasa = n_ganadas / n_ofertas * 100 if n_ofertas else 0

        sc1, sc2, sc3, sc4 = st.columns(4)
        _procesos_locales, _ = cargar_procesos()
        sc1.metric("Procesos en base local", len(_procesos_locales))
        sc2.metric("Ofertas preparadas", n_ofertas)
        sc3.metric("Ofertas ganadas", n_ganadas)
        sc4.metric("Tasa de éxito", f"{tasa:.0f}%")

        if historial:
            st.markdown("**Historial de ofertas presentadas:**")
            hist_df = pd.DataFrame(historial)
            cols_show = [c for c in ["fecha", "proceso", "formula", "nombre_formula", "precio", "pct_mejora", "resultado"] if c in hist_df.columns]
            if cols_show:
                st.dataframe(hist_df[cols_show], use_container_width=True, hide_index=True)
        else:
            st.info("Aún no has preparado ofertas. Usa la Calculadora para crear tu primera propuesta.")

    # ── Configuración ─────────────────────────────────────────────────────────
    with st.expander("⚙️ Configuración del proponente"):
        cfgc1, cfgc2 = st.columns(2)
        with cfgc1:
            perfil5["empresa"] = st.text_input(
                "Razón Social / Empresa",
                value=perfil5.get("empresa", ""),
                key="cfg_empresa",
            )
            perfil5["nit"] = st.text_input(
                "NIT",
                value=perfil5.get("nit", ""),
                key="cfg_nit",
            )
        with cfgc2:
            perfil5["email"] = st.text_input(
                "Email de contacto",
                value=perfil5.get("email", ""),
                key="cfg_email",
            )
            perfil5["telefono"] = st.text_input(
                "Teléfono / WhatsApp",
                value=perfil5.get("telefono", ""),
                key="cfg_tel",
            )

        st.markdown("**Alertas por email:**")
        alert_c1, alert_c2 = st.columns(2)
        perfil5["alerta_nuevos"] = alert_c1.checkbox(
            "Notificar nuevos procesos", value=perfil5.get("alerta_nuevos", True)
        )
        perfil5["alerta_cierre"] = alert_c2.checkbox(
            "Alertar 3 días antes del cierre", value=perfil5.get("alerta_cierre", True)
        )

        # ── SMTP ──────────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**⚙️ Configuración de email (alertas automáticas)**")
        st.caption(
            "Gmail: activa *Contraseñas de aplicación* en tu cuenta Google "
            "y usa esa contraseña aquí (no la de tu cuenta)."
        )
        smtp_c1, smtp_c2 = st.columns(2)
        perfil5["smtp_user"] = smtp_c1.text_input(
            "Email remitente (Gmail)", value=perfil5.get("smtp_user", ""), key="smtp_user"
        )
        perfil5["smtp_pass"] = smtp_c2.text_input(
            "Contraseña de aplicación", value=perfil5.get("smtp_pass", ""),
            type="password", key="smtp_pass"
        )

        if st.button("💾 Guardar configuración", type="primary"):
            st.session_state.perfil = perfil5
            guardar_perfil(perfil5)
            st.success("✅ Configuración guardada.")

        st.markdown("---")
        col_alert1, col_alert2 = st.columns([2, 1])
        with col_alert1:
            score_min_alert = st.slider("Score mínimo para alerta", 50, 99, 80, key="score_alerta")
        with col_alert2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("📧 Enviar alerta ahora", key="btn_alerta_manual"):
                try:
                    from m4_bot.scheduler import enviar_alerta_manual
                    res = enviar_alerta_manual(score_min=score_min_alert)
                    if res["enviado"]:
                        st.success(f"✅ {res['mensaje']}")
                    else:
                        st.warning(f"⚠️ {res['mensaje']}")
                except Exception as _e:
                    st.error(f"Error: {_e}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — COMPETIDORES
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.subheader("🕵️ Inteligencia Competitiva")

    subtab_c1, subtab_c2 = st.tabs(["👤 Rastreo de Rivales", "🏛️ Análisis de Entidades"])

    with subtab_c1:
        perfil_comp = st.session_state.perfil
        st.markdown("**NITs de competidores a monitorear:**")
        nits_data = perfil_comp.get("nits_rivales") or []
        nits_init = pd.DataFrame(nits_data, columns=["NIT", "Alias"]) if nits_data else pd.DataFrame(columns=["NIT", "Alias"])
        nits_edit = st.data_editor(nits_init, num_rows="dynamic", use_container_width=True, key="tabla_nits_rivales")
        if st.button("💾 Guardar NITs", key="btn_guardar_nits"):
            perfil_comp["nits_rivales"] = nits_edit.to_dict("records")
            guardar_perfil(perfil_comp)
            st.session_state.perfil = perfil_comp
            st.success("✅ NITs guardados.")

        st.markdown("---")
        st.markdown("**🔍 Consultar rival por NIT:**")
        nit_buscar = st.text_input("NIT del competidor", placeholder="Ej: 900123456", key="nit_buscar_inp")
        if st.button("Consultar rival", key="btn_consultar_rival") and nit_buscar:
            with st.spinner(f"Consultando NIT {nit_buscar}..."):
                try:
                    from api_client import get_perfil_competidor
                    data = get_perfil_competidor(nit_buscar.strip())
                except Exception as _e:
                    data = {"error": str(_e)}
            if data.get("error"):
                st.warning(f"⚠️ {data['error']}")
            else:
                st.markdown(f"### {data.get('nombre','N/A')} — NIT {data.get('nit','')}")
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Contratos ganados", data.get("total_contratos", 0))
                rc2.metric("Valor total", fmt_cop(data.get("valor_total_cop", 0)))
                pct_dto = (data.get("pct_descuento_avg") or 0) * 100
                rc3.metric("Descuento promedio", f"{pct_dto:.1f}%")

                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    st.markdown("**Sectores UNSPSC:**")
                    sect = data.get("sectores_unspsc", {})
                    if sect:
                        st.dataframe(
                            pd.DataFrame(list(sect.items()), columns=["UNSPSC", "Contratos"])
                            .sort_values("Contratos", ascending=False),
                            use_container_width=True, hide_index=True,
                        )
                with col_s2:
                    st.markdown("**Departamentos activos:**")
                    deptos_r = data.get("departamentos", {})
                    if deptos_r:
                        st.dataframe(
                            pd.DataFrame(list(deptos_r.items()), columns=["Departamento", "Contratos"])
                            .sort_values("Contratos", ascending=False),
                            use_container_width=True, hide_index=True,
                        )

                st.markdown("**Últimos contratos:**")
                recientes = data.get("contratos_recientes", [])
                if recientes:
                    st.dataframe(pd.DataFrame(recientes)[["entidad","objeto","valor","fecha","departamento","modalidad"]],
                                 use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("**⚡ Predecir rivales para un proceso activo:**")
        id_pred_inp = st.text_input("ID del proceso", placeholder="CO1.BDOS.1234567", key="id_pred_rival")
        if st.button("Predecir rivales", key="btn_pred_rivals") and id_pred_inp:
            with st.spinner("Analizando historial de la entidad y sector..."):
                try:
                    from api_client import get_prediccion_competidores
                    pred = get_prediccion_competidores(id_pred_inp.strip())
                except Exception as _e:
                    pred = {"error": str(_e), "rivales_probables": []}
            if pred.get("error"):
                st.warning(f"⚠️ {pred['error']}")
            else:
                st.markdown(f"**Entidad:** {pred.get('entidad','')} | **Sector UNSPSC:** {pred.get('sector_unspsc','')}")
                rivales = pred.get("rivales_probables", [])
                if rivales:
                    st.dataframe(pd.DataFrame(rivales), use_container_width=True, hide_index=True)
                    st.info("💡 Usa estos datos en la **Calculadora** para ajustar tu oferta sobre los rivales probables.")
                else:
                    st.info("Sin historial suficiente para predecir rivales en este proceso.")

    with subtab_c2:
        st.markdown("**🏛️ Buscar entidad contratante:**")
        ent_q = st.text_input("Nombre de la entidad", placeholder="IDU, Gobernación de Antioquia...", key="ent_q_comp")
        ent_depto = st.selectbox("Filtrar por departamento", [""] + DEPARTAMENTOS_CO, key="ent_depto_comp")
        if st.button("Buscar", key="btn_buscar_ent_comp") and ent_q:
            with st.spinner("Buscando entidades..."):
                try:
                    from api_client import get_entidades
                    ents = get_entidades(q=ent_q, departamento=ent_depto if ent_depto else None)
                except Exception as _e:
                    ents = {"error": str(_e), "items": []}
            if ents.get("error"):
                st.warning(ents["error"])
            elif not ents.get("items"):
                st.info("Sin resultados para esa búsqueda.")
            else:
                opciones_ent = {
                    f"{e['entidad']} ({e['departamento']}) — {e['total_procesos']} procesos": e["nit_entidad"]
                    for e in ents["items"]
                }
                sel_ent_key = st.selectbox("Seleccionar:", list(opciones_ent.keys()), key="sel_ent_det_comp")
                if st.button("Ver perfil completo de la entidad", key="btn_ver_ent_det"):
                    nit_ent_sel = opciones_ent[sel_ent_key]
                    with st.spinner("Cargando..."):
                        try:
                            from api_client import get_detalle_entidad
                            det = get_detalle_entidad(nit_ent_sel)
                        except Exception as _e:
                            det = {"error": str(_e)}
                    if det.get("error"):
                        st.warning(det["error"])
                    else:
                        st.markdown(f"### {det.get('nombre','')} — {det.get('departamento','')}")
                        st.metric("Procesos históricos", det.get("total_procesos", 0))
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            st.markdown("**Contratistas habituales de esta entidad:**")
                            hab = det.get("contratistas_habituales", [])
                            if hab:
                                st.dataframe(pd.DataFrame(hab), use_container_width=True, hide_index=True)
                        with col_e2:
                            st.markdown("**Entidades cercanas (mismo departamento):**")
                            cer = det.get("entidades_cercanas", [])
                            if cer:
                                st.dataframe(pd.DataFrame(cer), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 — SEGUIMIENTO
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.subheader("📌 Seguimiento de Procesos — Watchlist")

    perfil_seg = st.session_state.perfil
    watchlist  = perfil_seg.get("watchlist", [])

    # ── Agregar proceso ────────────────────────────────────────────────────────
    st.markdown("**➕ Agregar proceso al seguimiento:**")
    ws_c1, ws_c2 = st.columns([3, 1])
    nuevo_id_ws   = ws_c1.text_input("ID del proceso", placeholder="CO1.BDOS.1234567 o CCE-001",
                                      key="ws_nuevo_id")
    nueva_nota_ws = st.text_input("Nota personal (opcional)", key="ws_nota")
    if ws_c2.button("⭐ Agregar", key="btn_ws_add"):
        if nuevo_id_ws and not any(w["id"] == nuevo_id_ws for w in watchlist):
            watchlist.append({
                "id": nuevo_id_ws.strip(),
                "nota": nueva_nota_ws,
                "agregado": datetime.now().isoformat(),
                "ultimo_estado": None,
                "alertas": True,
            })
            perfil_seg["watchlist"] = watchlist
            guardar_perfil(perfil_seg)
            st.session_state.perfil = perfil_seg
            st.success(f"✅ {nuevo_id_ws} agregado al seguimiento.")
            st.rerun()
        elif nuevo_id_ws:
            st.warning("Este proceso ya está en tu watchlist.")

    st.markdown("---")

    # ── Lista de watchlist ─────────────────────────────────────────────────────
    if not watchlist:
        st.info("📭 No tienes procesos en seguimiento. Agrégalos arriba o con el botón '📋 Preparar oferta' en el Explorador.")
    else:
        col_ws_h1, col_ws_h2 = st.columns([3, 1])
        col_ws_h1.markdown(f"**{len(watchlist)} proceso(s) en seguimiento:**")
        if col_ws_h2.button("🔄 Actualizar todos", key="btn_ws_update_all"):
            try:
                from api_client import get_procesos
                actualizados = 0
                for w in watchlist:
                    try:
                        res = get_procesos(q=w["id"], page_size=1)
                        if res.get("items"):
                            nuevo_estado = res["items"][0].get("estado", "")
                            if nuevo_estado and nuevo_estado != w.get("ultimo_estado"):
                                w["ultimo_estado"] = nuevo_estado
                                actualizados += 1
                    except Exception:
                        pass
                perfil_seg["watchlist"] = watchlist
                guardar_perfil(perfil_seg)
                st.session_state.perfil = perfil_seg
                st.success(f"✅ {actualizados} proceso(s) actualizados.")
                st.rerun()
            except ImportError:
                st.warning("API central no disponible. Activa la conexión en Mi Cuenta.")

        for i, w in enumerate(watchlist):
            estado_badge = f" — {w['ultimo_estado']}" if w.get("ultimo_estado") else ""
            nota_txt     = f" — {w['nota']}"          if w.get("nota")           else ""
            dias_ws      = None
            color_dias   = "inherit"

            with st.expander(f"📌 {w['id']}{estado_badge}{nota_txt}", expanded=False):
                wc1, wc2, wc3, wc4 = st.columns([2, 2, 2, 1])
                wc1.markdown(f"**Agregado:** {str(w.get('agregado',''))[:10]}")
                if w.get("ultimo_estado"):
                    estado_col = (
                        "#28a745" if "CONVOCADO" in str(w["ultimo_estado"]).upper()
                        else "#fd7e14" if "CIERRE" in str(w["ultimo_estado"]).upper()
                        else "#1F4E79"
                    )
                    wc2.markdown(
                        f"**Estado:** <span style='color:{estado_col};font-weight:700'>{w['ultimo_estado']}</span>",
                        unsafe_allow_html=True,
                    )
                alertas_ws = wc3.checkbox("🔔 Alertas email", value=w.get("alertas", True),
                                          key=f"ws_alerta_{i}")
                watchlist[i]["alertas"] = alertas_ws
                if wc4.button("🗑️ Quitar", key=f"rm_ws_{i}"):
                    watchlist.pop(i)
                    perfil_seg["watchlist"] = watchlist
                    guardar_perfil(perfil_seg)
                    st.session_state.perfil = perfil_seg
                    st.rerun()

        # Guardar cambios de alertas
        if st.button("💾 Guardar preferencias de seguimiento", key="btn_ws_save"):
            perfil_seg["watchlist"] = watchlist
            guardar_perfil(perfil_seg)
            st.session_state.perfil = perfil_seg
            st.success("✅ Preferencias guardadas.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 7 — BOT SECOP II
# ─────────────────────────────────────────────────────────────────────────────
with tab7:
    st.subheader("Armar la propuesta para presentarla")
    st.caption(
        "LicitApp reúne el proceso, el precio y los habilitantes. "
        "La radicación la haces tú en el canal de la entidad."
    )
    _proc_prop = st.session_state.get("proceso_seleccionado")
    _oferta_prop = st.session_state.get("oferta_guardada")
    _perfil_prop = st.session_state.perfil
    if not _proc_prop:
        st.warning("En el Explorador pulsa **Preparar oferta** sobre un proceso real.")
    elif not _oferta_prop or not _oferta_prop.get("precio"):
        st.warning("En la Calculadora pulsa **Usar esta oferta** con un precio calculado.")
    else:
        try:
            _paquete = armar_propuesta(_proc_prop, _perfil_prop, _oferta_prop)
        except ValueError as _exc_prop:
            st.error(str(_exc_prop))
            _paquete = None
        if _paquete:
            _c1, _c2, _c3 = st.columns(3)
            _c1.metric("Proceso", _paquete["proceso"]["id"])
            _c2.metric("Oferta", f"$ {_paquete['economica']['precio']:,.0f}".replace(",", "."))
            _c3.metric("Canal", _paquete["canal"]["tipo"])
            st.info(_paquete["canal"]["instruccion"])
            st.dataframe(
                [{"Documento": h["nombre"], "Estado": h["estado"], "Listo": "Sí" if h["listo"] else "No"}
                 for h in _paquete["habilitantes"]],
                use_container_width=True,
                hide_index=True,
            )
            if _paquete["lista_para_presentar"]:
                st.success("La propuesta está completa para revisarla y presentarla.")
            else:
                st.warning("Falta: " + ", ".join(_paquete["faltantes"]))
            st.text_area("Carta de oferta", _paquete["carta"], height=260)
            _nombre_archivo = f"propuesta_{_paquete['proceso']['id']}.txt"
            st.download_button(
                "Descargar carta de oferta",
                data=_paquete["carta"].encode("utf-8"),
                file_name=_nombre_archivo,
                mime="text/plain",
                key="btn_descarga_propuesta",
            )
            if _paquete["correo"]:
                _correo_txt = (
                    f"Para: {_paquete['correo']['para']}\n"
                    f"Asunto: {_paquete['correo']['asunto']}\n\n"
                    f"{_paquete['correo']['cuerpo']}"
                )
                st.download_button(
                    "Descargar correo para Findeter",
                    data=_correo_txt.encode("utf-8"),
                    file_name=f"correo_{_paquete['proceso']['id']}.txt",
                    mime="text/plain",
                    key="btn_descarga_correo",
                )
            if st.button("Guardar propuesta en mi cuenta", key="btn_guardar_propuesta"):
                _perfil_prop.setdefault("propuestas", []).append({
                    "fecha": _paquete["fecha"],
                    "proceso": _paquete["proceso"]["id"],
                    "precio": _paquete["economica"]["precio"],
                    "canal": _paquete["canal"]["tipo"],
                    "lista": _paquete["lista_para_presentar"],
                })
                guardar_perfil(_perfil_prop)
                st.session_state.perfil = _perfil_prop
                st.success("Propuesta guardada en el perfil.")

    st.markdown("---")
    st.subheader("Bot de SECOP II, opcional")
    st.caption(
        "Solo intenta el formulario de SECOP II y, en ensayo, no envía la oferta. "
        "Ecopetrol se presenta en Ariba y Findeter por correo."
    )

    # ── Advertencia legal ──────────────────────────────────────────────────────
    st.warning(
        "**⚠️ Importante:** Antes de usar el bot en modo REAL, asegúrate de:\n"
        "1. Tener tu **RUP vigente** y todos los documentos habilitantes listos.\n"
        "2. Haber revisado el pliego de condiciones del proceso.\n"
        "3. Haber calculado tu oferta óptima en la **Calculadora de Ofertas**.\n"
        "4. Usar **dry_run** primero para verificar que todo funciona.\n\n"
        "El modo **dry_run** NO envía la oferta — solo completa el formulario y toma capturas.",
    )

    perfil6 = st.session_state.perfil

    # ── Credenciales SECOP II ──────────────────────────────────────────────────
    with st.expander("🔐 Credenciales SECOP II", expanded=False):
        cred_c1, cred_c2 = st.columns(2)
        usuario_bot   = cred_c1.text_input("Usuario SECOP II", value=perfil6.get("secop2_usuario", ""), key="bot_usuario")
        contrasena_bot = cred_c2.text_input("Contraseña SECOP II", value="", type="password", key="bot_pass")

        st.caption(
            "Las credenciales NO se guardan en disco por seguridad. "
            "Deberás ingresarlas cada vez que uses el bot."
        )

    # ── Seleccionar proceso ────────────────────────────────────────────────────
    with st.expander("🎯 Proceso objetivo", expanded=False):
        procesos_bot, _origen_bot = cargar_procesos()

        # Si viene de Tab 1
        proc_presel = st.session_state.get("proceso_seleccionado")
        opciones_bot = {
            f"{p.get('id', p.get('id_del_proceso',''))} — {(p.get('objeto') or p.get('titulo',''))[:60]}": p
            for p in procesos_bot
        }
        opciones_keys = list(opciones_bot.keys())
        proc_bot = {}

        if not opciones_keys:
            st.info("No hay procesos reales cargados. Puedes escribir el ID de SECOP II abajo.")
        else:
            default_idx = 0
            if proc_presel:
                pid = proc_presel.get("id") or proc_presel.get("id_del_proceso", "")
                for i, k in enumerate(opciones_keys):
                    if k.startswith(str(pid)):
                        default_idx = i
                        break

            proc_bot_key = st.selectbox(
                "Proceso a ofertar",
                opciones_keys,
                index=default_idx,
                key="bot_proc_sel",
            )
            proc_bot = opciones_bot.get(proc_bot_key, {})

        if proc_bot:
            bot_c1, bot_c2, bot_c3 = st.columns(3)
            bot_c1.metric("Presupuesto Oficial", fmt_cop(proc_bot.get("presupuesto_oficial", 0)))
            bot_c2.metric("Score", int(proc_bot.get("score", 0)))
            dias_bot = proc_bot.get("dias_al_cierre") or dias_al_cierre(proc_bot.get("fecha_cierre"))
            bot_c3.metric("Días al cierre", dias_bot if dias_bot is not None else "–")

        # ID manual (por si el proceso está en SECOP II y no en la BD local)
        id_manual = st.text_input(
            "O ingresa el ID del proceso directamente (SECOP II)",
            placeholder="Ej: CO1.BDOS.1234567",
            key="bot_id_manual",
        )
        id_proceso_final = id_manual.strip() if id_manual.strip() else (
            proc_bot.get("id") or proc_bot.get("id_del_proceso", "")
        )

    # ── Propuesta económica ────────────────────────────────────────────────────
    with st.expander("💰 Propuesta económica", expanded=True):
        oferta_guardada = st.session_state.get("oferta_guardada")

        po_default_bot = int(proc_bot.get("presupuesto_oficial", 100_000_000) or 100_000_000)
        valor_default  = int(oferta_guardada["precio"]) if oferta_guardada else int(po_default_bot * 0.92)

        if oferta_guardada:
            st.info(
                f"📌 Oferta pre-cargada desde la Calculadora: "
                f"**{fmt_cop(oferta_guardada['precio'])}** "
                f"(fórmula {oferta_guardada['formula']} — {oferta_guardada['nombre_formula']})"
            )

        propuesta_bot = st.number_input(
            "Valor de la propuesta económica (COP)",
            min_value=1_000_000, max_value=10_000_000_000,
            value=valor_default, step=500_000, format="%d",
            key="bot_propuesta",
        )
        pct_dto = (po_default_bot - propuesta_bot) / po_default_bot * 100 if po_default_bot else 0
        st.caption(f"Descuento sobre el P.O.: **{pct_dto:.1f}%** | P.O.: {fmt_cop(po_default_bot)}")

    # ── Documentos habilitantes ────────────────────────────────────────────────
    with st.expander("📎 Documentos habilitantes (rutas a archivos PDF)"):
        st.caption(
            "Ingresa las rutas absolutas a los archivos en tu computador. "
            "Deja en blanco los que no aplican."
        )
        doc_c1, doc_c2 = st.columns(2)
        ruta_rut  = doc_c1.text_input("RUT", placeholder="C:\\Documentos\\rut.pdf", key="doc_rut")
        ruta_cc   = doc_c2.text_input("Cámara de Comercio", placeholder="C:\\Documentos\\camara.pdf", key="doc_cc")
        ruta_rup  = doc_c1.text_input("RUP", placeholder="C:\\Documentos\\rup.pdf", key="doc_rup")
        ruta_ef   = doc_c2.text_input("Estados Financieros", placeholder="C:\\Documentos\\ef.pdf", key="doc_ef")
        ruta_exp  = doc_c1.text_input("Certificado de Experiencia", placeholder="C:\\Documentos\\exp.pdf", key="doc_exp")

        documentos_bot = {k: v for k, v in {
            "rut": ruta_rut, "camara_comercio": ruta_cc,
            "rup": ruta_rup, "estados_financieros": ruta_ef,
            "experiencia": ruta_exp,
        }.items() if v.strip()}

    # ── Modo y ejecución ───────────────────────────────────────────────────────
    st.markdown("---")
    modo_c1, modo_c2 = st.columns([2, 1])
    with modo_c1:
        modo_bot = st.radio(
            "Modo de ejecución",
            ["dry_run", "real"],
            index=0,
            horizontal=True,
            key="bot_modo",
            captions=[
                "✅ Seguro — completa formularios, toma capturas, NO envía",
                "⚠️ Envío real — presenta la oferta en SECOP II",
            ],
        )
    with modo_c2:
        headless_bot = st.checkbox("Ocultar ventana del navegador", value=False, key="bot_headless")

    if modo_bot == "real":
        st.error(
            "**Modo REAL seleccionado.** La oferta se presentará formalmente en SECOP II. "
            "Asegúrate de haber revisado TODO antes de continuar."
        )
        confirmar_real = st.checkbox(
            "Confirmo que revisé el pliego, tengo el RUP vigente y quiero enviar la oferta.",
            key="bot_confirmar_real",
        )
    else:
        confirmar_real = True

    st.markdown("---")
    btn_ejecutar = st.button(
        "🚀 Ejecutar Bot" if modo_bot == "dry_run" else "🚀 PRESENTAR OFERTA (REAL)",
        type="primary",
        disabled=not (usuario_bot and contrasena_bot and id_proceso_final and confirmar_real),
        key="btn_bot_ejecutar",
    )

    if not usuario_bot or not contrasena_bot:
        st.caption("⬆️ Completa las credenciales de SECOP II para habilitar el bot.")
    if not id_proceso_final:
        st.caption("⬆️ Selecciona o ingresa el ID del proceso.")

    # ── Ejecución del bot ──────────────────────────────────────────────────────
    if btn_ejecutar:
        placeholder_log = st.empty()
        placeholder_resultado = st.empty()

        with st.spinner(f"Ejecutando bot en modo **{modo_bot}**…"):
            try:
                from m4_bot.secop_bot import SecopBot
                bot = SecopBot(
                    usuario=usuario_bot,
                    contrasena=contrasena_bot,
                    modo=modo_bot,
                    headless=headless_bot,
                )
                resultado = bot.presentar_oferta(
                    id_proceso=id_proceso_final,
                    propuesta_economica=float(propuesta_bot),
                    documentos=documentos_bot if documentos_bot else None,
                )
            except ImportError:
                resultado = {
                    "exito": False,
                    "error": "Playwright no instalado. Ejecuta: pip install playwright && playwright install chromium",
                    "log": [],
                }
            except Exception as _e:
                resultado = {"exito": False, "error": str(_e), "log": []}

        # ── Mostrar resultado ─────────────────────────────────────────────────
        if resultado.get("exito"):
            if resultado.get("dry_run"):
                placeholder_resultado.success(
                    f"✅ **DRY-RUN completado.** Formulario preparado sin enviar.\n\n"
                    f"📄 Comprobante PDF: `{resultado.get('comprobante','–')}`"
                )
            else:
                placeholder_resultado.success(
                    f"🎉 **OFERTA ENVIADA.** ID oferta: `{resultado.get('id_oferta','pendiente')}`\n\n"
                    f"📄 Comprobante PDF: `{resultado.get('comprobante','–')}`"
                )
                # Guardar en historial
                historial_entry = {
                    "fecha": datetime.now().isoformat(),
                    "proceso": id_proceso_final,
                    "precio": propuesta_bot,
                    "formula": oferta_guardada.get("formula", "") if oferta_guardada else "",
                    "nombre_formula": oferta_guardada.get("nombre_formula", "") if oferta_guardada else "",
                    "resultado": "PRESENTADA",
                    "id_oferta": resultado.get("id_oferta"),
                    "comprobante": resultado.get("comprobante"),
                }
                perfil6.setdefault("historial_ofertas", []).append(historial_entry)
                guardar_perfil(perfil6)
                st.session_state.perfil = perfil6
        else:
            placeholder_resultado.error(
                f"❌ **Error:** {resultado.get('error', 'Error desconocido')}"
            )

        # ── Log de pasos ──────────────────────────────────────────────────────
        log_lines = resultado.get("log", [])
        if log_lines:
            with st.expander("📋 Log de ejecución", expanded=True):
                st.code("\n".join(log_lines), language="text")

        # ── Pasos completados ─────────────────────────────────────────────────
        pasos = resultado.get("pasos", [])
        if pasos:
            st.markdown("**Pasos completados:**")
            mapa_pasos = {
                "login_ok":          "✅ Login en SECOP II",
                "proceso_navegado":  "✅ Proceso encontrado y verificado",
                "suscrito":          "✅ Suscripción al proceso",
                "formulario_abierto":"✅ Formulario de oferta abierto",
                "propuesta_ingresada":"✅ Propuesta económica ingresada",
                "envio_completado":  "✅ Oferta enviada" if modo_bot == "real" else "✅ Dry-run completado",
            }
            for paso in pasos:
                label = mapa_pasos.get(paso, f"✅ {paso}")
                st.markdown(f"- {label}")
            if resultado.get("documentos_cargados"):
                n_docs = len(resultado["documentos_cargados"])
                st.markdown(f"- ✅ {n_docs} documento(s) cargado(s)")
