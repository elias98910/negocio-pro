import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
import uuid

# ===================== CONFIGURACIÓN E INTERFAZ =====================
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
    .kpi-card { padding:1rem; border-radius:12px; border:1px solid #e5e7eb; background:#fff }
    div[data-testid="stForm"] { border:1px solid #f3f4f6; border-radius:12px; padding:1rem; background:#fafafa }
</style>
""", unsafe_allow_html=True)

# ===================== FUNCIONES SEGURAS (NUNCA REVIENTAN) =====================
def fmt(v):
    """Formato moneda seguro"""
    try: return f"${float(v):,.2f}"
    except: return "$0.00"

def _i(v):
    """Convierte CUALQUIER cosa a int sin errores"""
    try:
        if v is None: return 0
        if hasattr(v, "item"): return int(v.item())
        return int(pd.to_numeric(v, errors="coerce") or 0)
    except: return 0

def _f(v):
    """Convierte CUALQUIER cosa a float sin errores"""
    try:
        if v is None: return 0.0
        if hasattr(v, "item"): return float(v.item())
        return float(pd.to_numeric(v, errors="coerce") or 0.0)
    except: return 0.0

def _s(v, default=""):
    """Convierte CUALQUIER cosa a string sin errores"""
    try:
        if v is None: return default
        r = str(v).strip()
        return r if r else default
    except: return default

# ===================== CONEXIÓN DEFINITIVA (NO MÁS ERROR SCHEMA) =====================
def get_db_url():
    try: return st.secrets["DATABASE_URL"]
    except: return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    # ✅ SOLUCIÓN 1 AL ERROR SCHEMA: forzado en la conexión
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

# ===================== CREAR TABLAS (NO ROMPRE DATOS VIEJOS) =====================
def init_db():
    with get_connection() as c:
        cur = c.cursor()
        # ✅ SOLUCIÓN 2 AL ERROR SCHEMA: public. EN TODAS LAS CONSULTAS
        cur.execute("""CREATE TABLE IF NOT EXISTS public.productos (
            id SERIAL PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT NOT NULL,
            descripcion TEXT, categoria TEXT, stock REAL DEFAULT 0,
            stock_minimo REAL DEFAULT 0, costo_unitario REAL DEFAULT 0,
            precio_venta REAL DEFAULT 0, unidad TEXT DEFAULT 'unidad',
            activo INTEGER DEFAULT 1, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.movimientos (
            id SERIAL PRIMARY KEY, producto_id INTEGER REFERENCES public.productos(id),
            tipo TEXT NOT NULL, cantidad REAL NOT NULL, costo REAL,
            motivo TEXT, ref TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.ventas (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cliente TEXT, total REAL NOT NULL, descu REAL DEFAULT 0,
            mp TEXT, anulada INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.ventas_det (
            id SERIAL PRIMARY KEY, venta_id INTEGER REFERENCES public.ventas(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cant REAL NOT NULL, pu REAL NOT NULL, costo REAL NOT NULL, sub REAL NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.compras (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            prov TEXT, total REAL NOT NULL, mp TEXT, anulada INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.compras_det (
            id SERIAL PRIMARY KEY, compra_id INTEGER REFERENCES public.compras(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cant REAL NOT NULL, costo REAL NOT NULL, sub REAL NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.gastos (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cat TEXT NOT NULL, descr TEXT, monto REAL NOT NULL, mp TEXT)""")

try: init_db()
except Exception as e: st.error(f"⚠️ Error al iniciar BD: {e}"); st.stop()

# ===================== FUNCIONES DE DATOS (TODAS ATÓMICAS) =====================
def get_productos():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM public.productos WHERE activo=1 ORDER BY nombre")
        return [{
            "id":_i(r["id"]), "cod":_s(r["codigo"]), "nom":_s(r["nombre"]),
            "stk":_f(r["stock"]), "cos":_f(r["costo_unitario"]),
            "pre":_f(r["precio_venta"]), "cat":_s(r["categoria"]),
            "und":_s(r["unidad"],"unidad")
        } for r in cur.fetchall()]

def kpi(sql, fi, ff):
    with get_connection() as c:
        cur = c.cursor(); cur.execute(sql, (fi, ff))
        return _f(cur.fetchone()["v"])

def stock_bajo():
    try:
        with get_connection() as c:
            return pd.read_sql_query(
                "SELECT nombre,stock,stock_minimo,unidad FROM public.productos WHERE activo=1 AND stock<=stock_minimo AND stock_minimo>0", c)
    except: return pd.DataFrame()

def valor_inv():
    with get_connection() as c:
        cur = c.cursor(); cur.execute("SELECT COALESCE(SUM(stock*costo_unitario),0) v FROM public.productos WHERE activo=1")
        return _f(cur.fetchone()["v"])

# ===================== PROTECCIÓN DOBLE ENVÍO (NO MÁS DUPLICADOS) =====================
def procesar_si_no_hecho(nonce):
    """Devuelve True SOLO la PRIMERA vez que se llama con ese nonce"""
    if "procesados" not in st.session_state:
        st.session_state.procesados = set()
    if nonce in st.session_state.procesados:
        return False
    st.session_state.procesados.add(nonce)
    return True

# ===================== INICIALIZAR ESTADO =====================
for k, v in {
    "cv": [],          # carrito ventas
    "cc": [],          # carrito compras
    "nv": uuid.uuid4().hex,  # nonce venta
    "nc": uuid.uuid4().hex,  # nonce compra
    "procesados": set()
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ===================== ANULAR VENTA / COMPRA (SEGURO) =====================
def anular_venta(vid):
    vid = _i(vid)
    if vid <= 0: return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("SELECT producto_id,cant,costo FROM public.ventas_det WHERE venta_id=%s", (vid,))
            det = cur.fetchall()
            if not det: return False, "No existe"
            cur.execute("UPDATE public.ventas SET anulada=1 WHERE id=%s", (vid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cant"]), _f(it["costo"])
                if pid>0 and cn>0:
                    cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s", (cn, pid))
                    cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,'entrada',%s,%s,'Anula venta',%s,DEFAULT)",
                                (pid, cn, ct, f"V{vid}"))
            return True, f"✅ Venta #{vid} anulada + stock devuelto"
    except Exception as e: return False, f"❌ Error: {e}"

def anular_compra(cid):
    cid = _i(cid)
    if cid <= 0: return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("SELECT d.producto_id,d.cant,d.costo,p.stock FROM public.compras_det d JOIN public.productos p ON d.producto_id=p.id WHERE d.compra_id=%s", (cid,))
            det = cur.fetchall()
            if not det: return False, "No existe"
            for it in det:
                if _f(it["stock"]) < _f(it["cant"]):
                    return False, f"❌ Stock insuficiente en producto {_i(it['producto_id'])}"
            cur.execute("UPDATE public.compras SET anulada=1 WHERE id=%s", (cid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cant"]), _f(it["costo"])
                if pid>0 and cn>0:
                    cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s", (cn, pid))
                    cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,'salida',%s,%s,'Anula compra',%s,DEFAULT)",
                                (pid, cn, ct, f"C{cid}"))
            return True, f"✅ Compra #{cid} anulada + stock actualizado"
    except Exception as e: return False, f"❌ Error: {e}"

# ===================== PÁGINA 1: DASHBOARD =====================
def p_dash():
    st.title("📊 Panel principal")
    a, b = st.columns(2)
    with a: fi = st.date_input("Desde", value=datetime.now().date()-timedelta(days=30))
    with b: ff = st.date_input("Hasta", value=datetime.now().date())
    fi, ff = str(fi), str(ff)

    ing = kpi("SELECT COALESCE(SUM(total-descu),0) v FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0", fi, ff)
    cog = kpi("SELECT COALESCE(SUM(d.cant*d.costo),0) v FROM public.ventas_det d JOIN public.ventas v ON d.venta_id=v.id WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0", fi, ff)
    gas = kpi("SELECT COALESCE(SUM(monto),0) v FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s", fi, ff)
    com = kpi("SELECT COALESCE(SUM(total),0) v FROM public.compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0", fi, ff)
    inv = valor_inv()
    ub, un = ing-cog, ing-cog-gas
    mb = (ub/ing*100) if ing>0 else 0
    mn = (un/ing*100) if ing>0 else 0

    st.subheader("Indicadores")
    cols = st.columns(3)
    with cols[0]: st.metric("💰 Ingresos", fmt(ing))
    with cols[1]: st.metric("📦 Costo mercadería", fmt(cog))
    with cols[2]: st.metric("💸 Gastos", fmt(gas))
    cols = st.columns(3)
    with cols[0]: st.metric("📈 Bruta", fmt(ub), delta=f"{mb:.1f}%")
    with cols[1]: st.metric("✅ Neta", fmt(un), delta=f"{mn:.1f}%")
    with cols[2]: st.metric("🛒 Compras", fmt(com))
    st.metric("📦 Valor inventario", fmt(inv))

    sb = stock_bajo()
    if not sb.empty:
        st.warning(f"⚠️ {len(sb)} producto(s) debajo del stock mínimo")
        with st.expander("Ver lista"): st.dataframe(sb, use_container_width=True, hide_index=True)

# ===================== PÁGINA 2: INVENTARIO =====================
def p_inv():
    st.title("📦 Inventario")
    prods = get_productos()
    t1, t2, t3, t4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Desactivar"])

    with t1:
        if not prods: st.info("No hay productos cargados")
        else: st.dataframe(pd.DataFrame(prods)[["cod","nom","stk","cos","pre"]], use_container_width=True, hide_index=True)

    with t2:
        with st.form("np", clear_on_submit=True):
            co = st.text_input("Código *", placeholder="PROD001")
            no = st.text_input("Nombre *", placeholder="Ej: Coca Cola 1L")
            ca = st.text_input("Categoría")
            un = st.selectbox("Unidad", ["unidad","kg","litro","caja","paquete"])
            si = st.number_input("Stock inicial", 0.0, step=0.1)
            cu = st.number_input("Costo *", 0.0, step=0.01)
            pv = st.number_input("Precio venta *", 0.0, step=0.01)
            sm = st.number_input("Stock mínimo", 0.0, value=5.0, step=0.1)
            if st.form_submit_button("💾 Guardar"):
                if not _s(co) or not _s(no) or _f(cu)<=0 or _f(pv)<=0:
                    st.error("❌ Completá los campos obligatorios (código, nombre, costo>0, precio>0)")
                else:
                    with get_connection() as c:
                        cur = c.cursor()
                        cur.execute("SELECT 1 FROM public.productos WHERE codigo=%s", (_s(co),))
                        if cur.fetchone(): st.error("❌ Ya existe ese código")
                        else:
                            cur.execute("INSERT INTO public.productos VALUES (DEFAULT,%s,%s,%s,%s,%s,%s,%s,%s,%s,DEFAULT,DEFAULT) RETURNING id",
                                        (_s(co),_s(no),"",_s(ca),_f(si),_f(sm),_f(cu),_f(pv),_s(un,"unidad")))
                            pid = _i(cur.fetchone()["id"])
                            if _f(si)>0:
                                cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,'entrada',%s,%s,'Inicial','ALTA',DEFAULT)",
                                            (pid,_f(si),_f(cu)))
                            st.success(f"✅ Creado: {_s(no)} (ID={pid})"); st.rerun()

    with t3:
        if not prods: st.info("Cargá productos primero")
        else:
            ids = [p["id"] for p in prods]
            with st.form("aj", clear_on_submit=True):
                pid = st.selectbox("Producto", ids, format_func=lambda x: next((f"{p['nom']} | Stk: {p['stk']}" for p in prods if p["id"]==_i(x)), ""))
                p = next((p for p in prods if p["id"]==_i(pid)), None)
                tp = st.radio("Movimiento", ["entrada","salida"], horizontal=True)
                cn = st.number_input("Cantidad", 0.01, step=0.1)
                mt = st.selectbox("Motivo", ["Inventario físico","Merma","Otro"])
                if st.form_submit_button("✅ Aplicar") and p:
                    if tp=="salida" and _f(cn) > _f(p["stk"]): st.error("❌ Stock insuficiente")
                    else:
                        dl = _f(cn) if tp=="entrada" else -_f(cn)
                        with get_connection() as c:
                            cur = c.cursor()
                            cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s", (dl,_i(pid)))
                            cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,%s,%s,%s,%s,DEFAULT)",
                                        (_i(pid),tp,_f(cn),_f(p["cos"]),_s(mt)))
                        st.success("✅ Ajuste aplicado"); st.rerun()

    with t4:
        if not prods: st.info("No hay productos")
        else:
            ids = [p["id"] for p in prods]
            with st.form("bp", clear_on_submit=True):
                pid = st.selectbox("Producto a desactivar", ids, format_func=lambda x: next((f"{p['cod']} | {p['nom']}" for p in prods if p["id"]==_i(x)), ""))
                cf = st.checkbox("✅ Confirmo que no se verá más en las listas")
                if st.form_submit_button("🗑️ Desactivar"):
                    if not cf: st.error("❌ Confirmá primero")
                    else:
                        with get_connection() as c:
                            c.cursor().execute("UPDATE public.productos SET activo=0 WHERE id=%s", (_i(pid),))
                        st.success("✅ Desactivado"); st.rerun()

# ===================== PÁGINA 3: VENTAS =====================
def p_ven():
    st.title("🛒 Ventas")
    prods = get_productos()
    if not prods: st.warning("Cargá productos primero"); return
    ids = [p["id"] for p in prods]

    with st.form("av", clear_on_submit=True):
        pid = st.selectbox("Producto", ids, format_func=lambda x: next((f"{p['nom']} | Stk: {p['stk']}" for p in prods if p["id"]==_i(x)), ""))
        pr = next((p for p in prods if p["id"]==_i(pid)), None)
        cn = st.number_input("Cantidad", 0.01, step=0.1)
        pc = st.number_input("Precio", _f(pr["pre"]) if pr else 0.0, 0.0, step=0.01)
        if st.form_submit_button("➕ Agregar al carrito") and pr:
            if _f(cn) > _f(pr["stk"]): st.error("❌ Stock insuficiente")
            else:
                st.session_state.cv.append({
                    "pid":_i(pr["id"]), "nom":_s(pr["nom"]),
                    "cn":_f(cn), "pu":_f(pc), "co":_f(pr["cos"]),
                    "sub":round(_f(cn)*_f(pc),2)
                })
                st.rerun()

    if st.session_state.cv:
        df = pd.DataFrame(st.session_state.cv)
        st.dataframe(df[["nom","cn","pu","sub"]], use_container_width=True, hide_index=True)
        tot = round(_f(df["sub"].sum()), 2)
        st.subheader(f"Total: {fmt(tot)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cv = []; st.rerun()

        nonce = st.session_state.nv
        with st.form(f"fv_{nonce}"):
            cl = st.text_input("Cliente")
            ds = st.number_input("Descuento", 0.0, step=0.01)
            mp = st.selectbox("Método", ["Efectivo","Tarjeta","Transferencia","Otro"])
            if st.form_submit_button("✅ CONFIRMAR VENTA"):
                if not procesar_si_no_hecho(nonce):
                    st.info("ℹ️ Ya se procesó esta operación")
                else:
                    carrito = list(st.session_state.cv)
                    with get_connection() as c:
                        cur = c.cursor()
                        cur.execute("INSERT INTO public.ventas VALUES (DEFAULT,DEFAULT,%s,%s,%s,%s,DEFAULT) RETURNING id",
                                    (_s(cl),_f(tot),_f(ds),_s(mp)))
                        vid = _i(cur.fetchone()["id"])
                        for it in carrito:
                            cur.execute("INSERT INTO public.ventas_det VALUES (DEFAULT,%s,%s,%s,%s,%s,%s)",
                                        (vid,_i(it["pid"]),_f(it["cn"]),_f(it["pu"]),_f(it["co"]),_f(it["sub"])))
                            cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s", (_f(it["cn"]),_i(it["pid"])))
                            cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,'salida',%s,%s,'Venta',%s,DEFAULT)",
                                        (_i(it["pid"]),_f(it["cn"]),_f(it["co"]),f"V{vid}"))
                    st.session_state.cv = []
                    st.session_state.nv = uuid.uuid4().hex
                    st.success(f"✅ Venta #{vid} registrada"); st.rerun()

# ===================== PÁGINA 4: COMPRAS =====================
def p_com():
    st.title("📥 Compras")
    prods = get_productos()
    if not prods: st.warning("Cargá productos primero"); return
    ids = [p["id"] for p in prods]

    with st.form("ac", clear_on_submit=True):
        pid = st.selectbox("Producto", ids, format_func=lambda x: next((p["nom"] for p in prods if p["id"]==_i(x)), ""))
        pr = next((p for p in prods if p["id"]==_i(pid)), None)
        cn = st.number_input("Cantidad", 0.01, step=0.1)
        ct = st.number_input("Costo unitario", _f(pr["cos"]) if pr else 0.0, 0.0, step=0.01)
        if st.form_submit_button("➕ Agregar al carrito") and pr:
            st.session_state.cc.append({
                "pid":_i(pr["id"]), "nom":_s(pr["nom"]),
                "cn":_f(cn), "co":_f(ct),
                "sub":round(_f(cn)*_f(ct),2)
            })
            st.rerun()

    if st.session_state.cc:
        df = pd.DataFrame(st.session_state.cc)
        st.dataframe(df[["nom","cn","co","sub"]], use_container_width=True, hide_index=True)
        tot = round(_f(df["sub"].sum()), 2)
        st.subheader(f"Total: {fmt(tot)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cc = []; st.rerun()

        nonce = st.session_state.nc
        with st.form(f"fc_{nonce}"):
            pv = st.text_input("Proveedor")
            mp = st.selectbox("Método", ["Efectivo","Transferencia","Crédito"])
            if st.form_submit_button("✅ CONFIRMAR COMPRA"):
                if not procesar_si_no_hecho(nonce):
                    st.info("ℹ️ Ya se procesó esta operación")
                else:
                    carrito = list(st.session_state.cc)
                    with get_connection() as c:
                        cur = c.cursor()
                        cur.execute("INSERT INTO public.compras VALUES (DEFAULT,DEFAULT,%s,%s,%s,DEFAULT) RETURNING id",
                                    (_s(pv),_f(tot),_s(mp)))
                        cid = _i(cur.fetchone()["id"])
                        for it in carrito:
                            cur.execute("INSERT INTO public.compras_det VALUES (DEFAULT,%s,%s,%s,%s,%s)",
                                        (cid,_i(it["pid"]),_f(it["cn"]),_f(it["co"]),_f(it["sub"])))
                            cur.execute("UPDATE public.productos SET stock=stock+%s, costo_unitario=%s WHERE id=%s",
                                        (_f(it["cn"]),_f(it["co"]),_i(it["pid"])))
                            cur.execute("INSERT INTO public.movimientos VALUES (DEFAULT,%s,'entrada',%s,%s,'Compra',%s,DEFAULT)",
                                        (_i(it["pid"]),_f(it["cn"]),_f(it["co"]),f"C{cid}"))
                    st.session_state.cc = []
                    st.session_state.nc = uuid.uuid4().hex
                    st.success(f"✅ Compra #{cid} registrada"); st.rerun()

# ===================== PÁGINA 5: GASTOS =====================
def p_gas():
    st.title("💸 Gastos")
    cats = ["Alquiler","Servicios","Sueldos","Marketing","Transporte",
            "Impuestos","Mantenimiento","Seguros","Papelería","Otros"]
    with st.form("ng", clear_on_submit=True):
        fh = st.date_input("Fecha", value=datetime.now().date())
        ct = st.selectbox("Categoría", cats)
        ds = st.text_input("Descripción")
        mn = st.number_input("Monto", 0.01, step=0.01)
        mp = st.selectbox("Método", ["Efectivo","Transferencia","Tarjeta"])
        if st.form_submit_button("💾 Guardar"):
            with get_connection() as c:
                c.cursor().execute("INSERT INTO public.gastos VALUES (DEFAULT,%s,%s,%s,%s,%s)",
                                   (str(fh),_s(ct),_s(ds),_f(mn),_s(mp)))
            st.success("✅ Guardado"); st.rerun()

# ===================== PÁGINA 6: REPORTES =====================
def p_rep():
    st.title("📈 Reportes")
    a, b = st.columns(2)
    with a: fi = st.date_input("Desde", value=datetime.now().date()-timedelta(days=90), key="r1")
    with b: ff = st.date_input("Hasta", value=datetime.now().date(), key="r2")
    fi, ff = str(fi), str(ff)
    ing = kpi("SELECT COALESCE(SUM(total-descu),0) v FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0", fi, ff)
    cog = kpi("SELECT COALESCE(SUM(d.cant*d.costo),0) v FROM public.ventas_det d JOIN public.ventas v ON d.venta_id=v.id WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0", fi, ff)
    gas = kpi("SELECT COALESCE(SUM(monto),0) v FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s", fi, ff)
    x, y = st.columns(2)
    x.metric("Ingresos", fmt(ing))
    y.metric("Utilidad Neta", fmt(ing-cog-gas))

# ===================== PÁGINA 7: HISTORIAL + ANULAR (100% SEGURO) =====================
def _cargar(sql):
    """Carga datos y devuelve (ids, labels) SIN ACCESOS RAROS"""
    try:
        with get_connection() as c:
            df = pd.read_sql_query(sql, c)
        ids, lbl = [], {}
        for r in df.to_dict("records"):
            i = _i(r.get("id"))
            if i <= 0: continue
            ids.append(i)
            f = _s(r.get("fecha"), "---")[:16]
            t = _s(r.get("tercero"), "S/N")
            v = _f(r.get("total"))
            lbl[i] = f"#{i} | {f} | {t} | {fmt(v)}"
        return ids, lbl, None
    except Exception as e: return [], {}, str(e)

def p_his():
    st.title("📜 Historial y anulaciones")
    t1, t2, t3, t4, t5 = st.tabs(["Ventas","Compras","Gastos","🗑️ Anular Venta","🗑️ Anular Compra"])

    try:
        with get_connection() as c:
            with t1:
                df = pd.read_sql_query("SELECT id,fecha,cliente,total,mp FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
            with t2:
                df = pd.read_sql_query("SELECT id,fecha,prov,total,mp FROM public.compras WHERE anulada=0 ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
            with t3:
                df = pd.read_sql_query("SELECT fecha,cat,monto,mp FROM public.gastos ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
    except Exception as e: st.error(f"Error al cargar: {e}")

    # ✅ ANULAR VENTA: NUNCA toca DF dentro de format_func
    with t4:
        st.info("⚠️ Devuelve stock y elimina el monto de ingresos. Irreversible.")
        ids, lbl, err = _cargar("SELECT id,fecha,cliente AS tercero,total FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC")
        if err: st.error(err)
        elif not ids: st.warning("Nada para anular")
        else:
            with st.form("anv", clear_on_submit=True):
                vid = st.selectbox("Venta", options=ids, format_func=lambda x: lbl.get(_i(x), f"#{_i(x)}"))
                a = st.checkbox("✅ El registro es erróneo / no existió")
                b = st.checkbox("✅ Acepto que se devuelve el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok, msg = anular_venta(vid)
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()

    # ✅ ANULAR COMPRA: MISMA SEGURIDAD
    with t5:
        st.info("⚠️ Resta stock y elimina el monto de compras. Irreversible.")
        ids, lbl, err = _cargar("SELECT id,fecha,prov AS tercero,total FROM public.compras WHERE anulada=0 ORDER BY fecha DESC")
        if err: st.error(err)
        elif not ids: st.warning("Nada para anular")
        else:
            with st.form("anc", clear_on_submit=True):
                cid = st.selectbox("Compra", options=ids, format_func=lambda x: lbl.get(_i(x), f"#{_i(x)}"))
                a = st.checkbox("✅ El registro es erróneo / no existió")
                b = st.checkbox("✅ Acepto que se resta el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok, msg = anular_compra(cid)
                        st.success(msg) if ok else st.error(msg)
                        st.rerun()

# ===================== MENÚ PRINCIPAL =====================
def main():
    st.sidebar.title("🏪 Menú")
    menu = {
        "📊 Dashboard": p_dash,
        "📦 Inventario": p_inv,
        "🛒 Ventas": p_ven,
        "📥 Compras": p_com,
        "💸 Gastos": p_gas,
        "📈 Reportes": p_rep,
        "📜 Historial": p_his
    }
    op = st.sidebar.radio("Ir a", list(menu.keys()))
    menu[op]()

if __name__ == "__main__":
    main()
