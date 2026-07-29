import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
import uuid

# ===================== CONFIG =====================
st.set_page_config(
    page_title="Gestión Negocio",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stButton>button { width:100%; height:3rem; font-size:1.05rem; border-radius:12px; font-weight:500 }
    .block-container { padding:1.2rem 1rem 2rem }
    h1 { font-size:1.7rem !important; margin-bottom:1rem }
    h2 { font-size:1.25rem !important; margin:1rem 0 .5rem }
    div[data-testid="stForm"] { border:1px solid #f3f4f6; border-radius:12px; padding:1rem; background:#fafafa }
</style>
""", unsafe_allow_html=True)

# ===================== HELPERS SEGUROS =====================
def fmt(v):
    try: return f"${float(v):,.2f}"
    except: return "$0.00"

def _i(v):
    try:
        if v is None: return 0
        if hasattr(v, "item"): return int(v.item())
        return int(pd.to_numeric(v, errors="coerce") or 0)
    except: return 0

def _f(v):
    try:
        if v is None: return 0.0
        if hasattr(v, "item"): return float(v.item())
        return float(pd.to_numeric(v, errors="coerce") or 0.0)
    except: return 0.0

def _s(v, default=""):
    try:
        if v is None: return default
        r = str(v).strip()
        return r if r else default
    except: return default

# ===================== CONEXIÓN =====================
def get_db_url():
    try: return st.secrets["DATABASE_URL"]
    except: return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    conn = psycopg2.connect(
        get_db_url(),
        cursor_factory=RealDictCursor,
        options="-c search_path=public"
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ===================== TABLAS =====================
def init_db():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.productos (
                id SERIAL PRIMARY KEY,
                codigo TEXT UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT DEFAULT '',
                categoria TEXT DEFAULT '',
                stock REAL DEFAULT 0,
                stock_minimo REAL DEFAULT 0,
                costo_unitario REAL DEFAULT 0,
                precio_venta REAL DEFAULT 0,
                unidad TEXT DEFAULT 'unidad',
                activo INTEGER DEFAULT 1,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.movimientos (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER REFERENCES public.productos(id),
                tipo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                costo REAL,
                motivo TEXT,
                ref TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.ventas (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cliente TEXT DEFAULT '',
                total REAL NOT NULL,
                descu REAL DEFAULT 0,
                mp TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.ventas_det (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER REFERENCES public.ventas(id),
                producto_id INTEGER REFERENCES public.productos(id),
                cant REAL NOT NULL,
                pu REAL NOT NULL,
                costo REAL NOT NULL,
                sub REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.compras (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                prov TEXT DEFAULT '',
                total REAL NOT NULL,
                mp TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.compras_det (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER REFERENCES public.compras(id),
                producto_id INTEGER REFERENCES public.productos(id),
                cant REAL NOT NULL,
                costo REAL NOT NULL,
                sub REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.gastos (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cat TEXT NOT NULL,
                descr TEXT DEFAULT '',
                monto REAL NOT NULL,
                mp TEXT DEFAULT ''
            )
        """)

try:
    init_db()
except Exception as e:
    st.error(f"Error al iniciar BD: {e}")
    st.stop()

# ===================== DATOS =====================
def get_productos():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, 
                   categoria, unidad, stock_minimo
            FROM public.productos 
            WHERE activo = 1 
            ORDER BY nombre
        """)
        return [{
            "id": _i(r["id"]),
            "cod": _s(r["codigo"]),
            "nom": _s(r["nombre"]),
            "stk": _f(r["stock"]),
            "cos": _f(r["costo_unitario"]),
            "pre": _f(r["precio_venta"]),
            "cat": _s(r["categoria"]),
            "und": _s(r["unidad"], "unidad"),
            "smin": _f(r["stock_minimo"])
        } for r in cur.fetchall()]

def kpi(sql, fi, ff):
    with get_connection() as c:
        cur = c.cursor()
        cur.execute(sql, (fi, ff))
        return _f(cur.fetchone()["v"])

def stock_bajo():
    try:
        with get_connection() as c:
            return pd.read_sql_query(
                "SELECT nombre, stock, stock_minimo, unidad FROM public.productos WHERE activo=1 AND stock <= stock_minimo AND stock_minimo > 0",
                c
            )
    except:
        return pd.DataFrame()

def valor_inv():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("SELECT COALESCE(SUM(stock * costo_unitario), 0) v FROM public.productos WHERE activo = 1")
        return _f(cur.fetchone()["v"])

# ===================== PROTECCIÓN DOBLE ENVÍO =====================
def procesar_si_no_hecho(nonce):
    if "procesados" not in st.session_state:
        st.session_state.procesados = set()
    if nonce in st.session_state.procesados:
        return False
    st.session_state.procesados.add(nonce)
    return True

# ===================== ESTADO =====================
for k, v in {
    "cv": [],
    "cc": [],
    "nv": uuid.uuid4().hex,
    "nc": uuid.uuid4().hex,
    "procesados": set()
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ===================== ANULAR =====================
def anular_venta(vid):
    vid = _i(vid)
    if vid <= 0:
        return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("SELECT producto_id, cant, costo FROM public.ventas_det WHERE venta_id = %s", (vid,))
            det = cur.fetchall()
            if not det:
                return False, "No existe"
            cur.execute("UPDATE public.ventas SET anulada = 1 WHERE id = %s", (vid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cant"]), _f(it["costo"])
                if pid > 0 and cn > 0:
                    cur.execute("UPDATE public.productos SET stock = stock + %s WHERE id = %s", (cn, pid))
                    cur.execute("""
                        INSERT INTO public.movimientos (producto_id, tipo, cantidad, costo, motivo, ref)
                        VALUES (%s, 'entrada', %s, %s, 'Anula venta', %s)
                    """, (pid, cn, ct, f"V{vid}"))
            return True, f"✅ Venta #{vid} anulada + stock devuelto"
    except Exception as e:
        return False, f"❌ Error: {e}"

def anular_compra(cid):
    cid = _i(cid)
    if cid <= 0:
        return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("""
                SELECT d.producto_id, d.cant, d.costo, p.stock 
                FROM public.compras_det d 
                JOIN public.productos p ON d.producto_id = p.id 
                WHERE d.compra_id = %s
            """, (cid,))
            det = cur.fetchall()
            if not det:
                return False, "No existe"
            for it in det:
                if _f(it["stock"]) < _f(it["cant"]):
                    return False, f"❌ Stock insuficiente en producto {_i(it['producto_id'])}"
            cur.execute("UPDATE public.compras SET anulada = 1 WHERE id = %s", (cid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cant"]), _f(it["costo"])
                if pid > 0 and cn > 0:
                    cur.execute("UPDATE public.productos SET stock = stock - %s WHERE id = %s", (cn, pid))
                    cur.execute("""
                        INSERT INTO public.movimientos (producto_id, tipo, cantidad, costo, motivo, ref)
                        VALUES (%s, 'salida', %s, %s, 'Anula compra', %s)
                    """, (pid, cn, ct, f"C{cid}"))
            return True, f"✅ Compra #{cid} anulada + stock actualizado"
    except Exception as e:
        return False, f"❌ Error: {e}"

# ===================== DASHBOARD =====================
def p_dash():
    st.title("📊 Panel principal")
    a, b = st.columns(2)
    with a:
        fi = st.date_input("Desde", value=datetime.now().date() - timedelta(days=30))
    with b:
        ff = st.date_input("Hasta", value=datetime.now().date())
    fi, ff = str(fi), str(ff)

    ing = kpi("SELECT COALESCE(SUM(total - descu), 0) v FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0", fi, ff)
    cog = kpi("""
        SELECT COALESCE(SUM(d.cant * d.costo), 0) v 
        FROM public.ventas_det d 
        JOIN public.ventas v ON d.venta_id = v.id 
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """, fi, ff)
    gas = kpi("SELECT COALESCE(SUM(monto), 0) v FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s", fi, ff)
    com = kpi("SELECT COALESCE(SUM(total), 0) v FROM public.compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0", fi, ff)
    inv = valor_inv()
    ub, un = ing - cog, ing - cog - gas
    mb = (ub / ing * 100) if ing > 0 else 0
    mn = (un / ing * 100) if ing > 0 else 0

    st.subheader("Indicadores")
    cols = st.columns(3)
    cols[0].metric("💰 Ingresos", fmt(ing))
    cols[1].metric("📦 Costo mercadería", fmt(cog))
    cols[2].metric("💸 Gastos", fmt(gas))
    cols = st.columns(3)
    cols[0].metric("📈 Bruta", fmt(ub), delta=f"{mb:.1f}%")
    cols[1].metric("✅ Neta", fmt(un), delta=f"{mn:.1f}%")
    cols[2].metric("🛒 Compras", fmt(com))
    st.metric("📦 Valor inventario", fmt(inv))

    sb = stock_bajo()
    if not sb.empty:
        st.warning(f"⚠️ {len(sb)} producto(s) debajo del stock mínimo")
        with st.expander("Ver lista"):
            st.dataframe(sb, use_container_width=True, hide_index=True)

# ===================== INVENTARIO =====================
def p_inv():
    st.title("📦 Inventario")
    prods = get_productos()
    t1, t2, t3, t4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Desactivar"])

    with t1:
        if not prods:
            st.info("No hay productos cargados")
        else:
            st.dataframe(pd.DataFrame(prods)[["cod", "nom", "stk", "cos", "pre"]], use_container_width=True, hide_index=True)

    # ---------- NUEVO PRODUCTO (SIN PLACEHOLDERS + RERUN FUERA) ----------
    with t2:
        st.subheader("Crear producto")
        with st.form("form_nuevo_prod", clear_on_submit=True):
            co = st.text_input("Código *")
            no = st.text_input("Nombre *")
            ca = st.text_input("Categoría")
            un = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"])
            si = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=0.1)
            cu = st.number_input("Costo unitario *", min_value=0.0, value=0.0, step=0.01)
            pv = st.number_input("Precio de venta *", min_value=0.0, value=0.0, step=0.01)
            sm = st.number_input("Stock mínimo", min_value=0.0, value=5.0, step=0.1)
            enviar = st.form_submit_button("💾 Guardar producto")

        if enviar:
            co = _s(co)
            no = _s(no)
            ca = _s(ca)

            if not co or not no:
                st.error("❌ Código y Nombre son obligatorios")
            elif _f(cu) <= 0 or _f(pv) <= 0:
                st.error("❌ Costo y Precio deben ser mayores a 0")
            else:
                try:
                    pid = None
                    with get_connection() as c:
                        cur = c.cursor()
                        cur.execute("SELECT 1 FROM public.productos WHERE codigo = %s", (co,))
                        if cur.fetchone():
                            st.error(f"❌ Ya existe el código: {co}")
                        else:
                            cur.execute("""
                                INSERT INTO public.productos 
                                (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (co, no, ca, _f(si), _f(sm), _f(cu), _f(pv), un))
                            pid = _i(cur.fetchone()["id"])
                            if _f(si) > 0:
                                cur.execute("""
                                    INSERT INTO public.movimientos (producto_id, tipo, cantidad, costo, motivo, ref)
                                    VALUES (%s, 'entrada', %s, %s, 'Inicial', 'ALTA')
                                """, (pid, _f(si), _f(cu)))

                    if pid:
                        st.success(f"✅ Producto creado: {no} (ID={pid})")
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    with t3:
        if not prods:
            st.info("Cargá productos primero")
        else:
            ids = [p["id"] for p in prods]
            with st.form("form_ajuste", clear_on_submit=True):
                pid = st.selectbox(
                    "Producto",
                    ids,
                    format_func=lambda x: next((f"{p['nom']} | Stk: {p['stk']}" for p in prods if p["id"] == _i(x)), "")
                )
                p = next((p for p in prods if p["id"] == _i(pid)), None)
                tp = st.radio("Movimiento", ["entrada", "salida"], horizontal=True)
                cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
                mt = st.selectbox("Motivo", ["Inventario físico", "Merma", "Otro"])
                if st.form_submit_button("✅ Aplicar") and p:
                    if tp == "salida" and _f(cn) > _f(p["stk"]):
                        st.error("❌ Stock insuficiente")
                    else:
                        try:
                            dl = _f(cn) if tp == "entrada" else -_f(cn)
                            with get_connection() as c:
                                cur = c.cursor()
                                cur.execute("UPDATE public.productos SET stock = stock + %s WHERE id = %s", (dl, _i(pid)))
                                cur.execute("""
                                    INSERT INTO public.movimientos (producto_id, tipo, cantidad, costo, motivo)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (_i(pid), tp, _f(cn), _f(p["cos"]), _s(mt)))
                            st.success("✅ Ajuste aplicado")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")

    with t4:
        if not prods:
            st.info("No hay productos")
        else:
            ids = [p["id"] for p in prods]
            with st.form("form_desact", clear_on_submit=True):
                pid = st.selectbox(
                    "Producto a desactivar",
                    ids,
                    format_func=lambda x: next((f"{p['cod']} | {p['nom']}" for p in prods if p["id"] == _i(x)), "")
                )
                cf = st.checkbox("✅ Confirmo que no se verá más en las listas")
                if st.form_submit_button("🗑️ Desactivar"):
                    if not cf:
                        st.error("❌ Confirmá primero")
                    else:
                        with get_connection() as c:
                            c.cursor().execute("UPDATE public.productos SET activo = 0 WHERE id = %s", (_i(pid),))
                        st.success("✅ Desactivado")
                        st.rerun()

# ===================== VENTAS =====================
def p_ven():
    st.title("🛒 Ventas")
    prods = get_productos()
    if not prods:
        st.warning("Cargá productos primero")
        return
    ids = [p["id"] for p in prods]

    with st.form("form_add_venta", clear_on_submit=True):
        pid = st.selectbox(
            "Producto",
            ids,
            format_func=lambda x: next((f"{p['nom']} | Stk: {p['stk']}" for p in prods if p["id"] == _i(x)), "")
        )
        pr = next((p for p in prods if p["id"] == _i(pid)), None)
        cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
        pc = st.number_input("Precio", value=_f(pr["pre"]) if pr else 0.0, min_value=0.0, step=0.01)
        if st.form_submit_button("➕ Agregar al carrito") and pr:
            if _f(cn) > _f(pr["stk"]):
                st.error("❌ Stock insuficiente")
            else:
                st.session_state.cv.append({
                    "pid": _i(pr["id"]),
                    "nom": _s(pr["nom"]),
                    "cn": _f(cn),
                    "pu": _f(pc),
                    "co": _f(pr["cos"]),
                    "sub": round(_f(cn) * _f(pc), 2)
                })
                st.rerun()

    if st.session_state.cv:
        df = pd.DataFrame(st.session_state.cv)
        st.dataframe(df[["nom", "cn", "pu", "sub"]], use_container_width=True, hide_index=True)
        tot = round(_f(df["sub"].sum()), 2)
        st.subheader(f"Total: {fmt(tot)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cv = []
            st.rerun()

        nonce = st.session_state.nv
        with st.form(f"form_conf_venta_{nonce}"):
            cl = st.text_input("Cliente")
            ds = st.number_input("Descuento", min_value=0.0, value=0.0, step=0.01)
            mp = st.selectbox("Método", ["Efectivo", "Tarjeta", "Transferencia", "Otro"])
            if st.form_submit_button("✅ CONFIRMAR VENTA"):
                if not procesar_si_no_hecho(nonce):
                    st.info("ℹ️ Ya se procesó esta operación")
                else:
                    carrito = list(st.session_state.cv)
                    try:
                        with get_connection() as c:
                            cur = c.cursor()
                            cur.execute("""
                                INSERT INTO public.ventas (cliente, total, descu, mp)
                                VALUES (%s, %s, %s, %s) RETURNING id
                            """, (_s(cl), _f(tot), _f(ds), _s(mp)))
                            vid = _i(cur.fetchone()["id"])
                            for it in carrito:
                                cur.execute("""
                                    INSERT INTO public.ventas_det (venta_id, producto_id, cant, pu, costo, sub)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (vid, _i(it["pid"]), _f(it["cn"]), _f(it["pu"]), _f(it["co"]), _f(it["sub"])))
                                cur.execute("UPDATE public.productos SET stock = stock - %s WHERE id = %s", (_f(it["cn"]), _i(it["pid"])))
                                cur.execute("""
                                    INSERT INTO public.movimientos (producto_id, tipo, cantidad, costo, motivo, ref)
                                    VALUES (%s, 'salida', %s, %s, 'Venta', %s)
                                """, (_i(it["pid"]), _f(it["cn"]), _f(it["co"]), f"V{vid}"))
                        st.session_state.cv = []
                        st.session_state.nv = uuid.uuid4().hex
                        st.success(f"✅ Venta #{vid} registrada")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

# ===================== COMPRAS =====================
def p_com():
    st.title("📥 Compras")
    prods = get_productos()
    if not prods:
        st.warning("Cargá productos primero")
        return
    ids = [p["id"] for p in prods]

    with st.form("form_add_compra", clear_on_submit=True):
        pid = st.selectbox(
            "Producto",
            ids,
            format_func=lambda x: next((p["nom"] for p in prods if p["id"] == _i(x)), "")
        )
        pr = next((p for p in prods if p["id"] == _i(pid)), None)
        cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
        ct = st.number_input("Costo unitario", value=_f(pr["cos"]) if pr else 0.0, min_value=0.0, step=0.01)
        if st.form_submit_button("➕ Agregar al carrito") and pr:
            st.session_state.cc.append({
                "pid": _i(pr["id"]),
                "nom": _s(pr["nom"]),
                "cn": _f(cn),
                "co": _f(ct),
                "sub": round(_f(cn) * _f(ct), 2)
            })
            st.rerun()

    if st.session_state.cc:
        df = pd.DataFrame(st.session_state.cc)
        st.dataframe(df[["nom", "cn", "co", "sub"]], use_container_width=True, hide_index=True)
        tot = round(_f(df["sub"].sum()), 2)
        st.subheader(f"Total: {fmt(tot)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cc = []
            st.rerun()

        nonce = st.session_state.nc
        with st.form(f"form_conf_compra_{nonce}"):
            pv = st.text_input("Proveedor")
            mp = st.selectbox("Método", ["Efectivo", "Transferencia", "Crédito"])
            if st.form_submit_button("✅ CONFIRMAR COMPRA"):
                if not procesar_si_no_hecho(nonce):
                    st.info("ℹ️ Ya se procesó esta operación")
                else:
                    carrito = list(st.session_state.cc)
                    try:
                        with get_connection() as c:
                            cur = c.cursor()
                            cur.execute("""
                                INSERT INTO public.compras (prov, total, mp)
                                VALUES (%s, %s, %s) RETURNING id
                            """, (_s(pv), _f(tot), _s(mp)))
                            cid = _i(cur.fetchone()["id"])
                            for it in carrito:
                                cur.execute("""
                                    INSERT INTO public.compras_det (compra_id, producto_id, cant, costo, sub)
