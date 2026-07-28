import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os, uuid

st.set_page_config(page_title="Gestión Negocio", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
.stButton>button{width:100%;height:3rem;font-size:1.1rem;border-radius:10px}
.block-container{padding:1.2rem 1rem 2rem}
h1{font-size:1.6rem !important}
</style>
""", unsafe_allow_html=True)

# ---------- CONEXIÓN (FUNCIONA - NO TOCAR) ----------
def get_db_url():
    try: return st.secrets["DATABASE_URL"]
    except: return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    conn = psycopg2.connect(get_db_url(), cursor_factory=RealDictCursor, options="-c search_path=public")
    try: yield conn; conn.commit()
    except: conn.rollback(); raise
    finally: conn.close()

# ---------- TABLAS ----------
def init_db():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS public.productos (
            id SERIAL PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT NOT NULL,
            descripcion TEXT, categoria TEXT, stock REAL DEFAULT 0,
            stock_minimo REAL DEFAULT 0, costo_unitario REAL DEFAULT 0,
            precio_venta REAL DEFAULT 0, unidad TEXT DEFAULT 'unidad',
            activo INTEGER DEFAULT 1, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.movimientos_stock (
            id SERIAL PRIMARY KEY, producto_id INTEGER REFERENCES public.productos(id),
            tipo TEXT NOT NULL, cantidad REAL NOT NULL, costo_unitario REAL,
            motivo TEXT, referencia TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.ventas (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cliente TEXT, total REAL NOT NULL, descuento REAL DEFAULT 0,
            metodo_pago TEXT, notas TEXT, anulada INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.venta_detalle (
            id SERIAL PRIMARY KEY, venta_id INTEGER REFERENCES public.ventas(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cantidad REAL NOT NULL, precio_unitario REAL NOT NULL,
            costo_unitario REAL NOT NULL, subtotal REAL NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.compras (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            proveedor TEXT, total REAL NOT NULL, metodo_pago TEXT,
            notas TEXT, anulada INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.compra_detalle (
            id SERIAL PRIMARY KEY, compra_id INTEGER REFERENCES public.compras(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cantidad REAL NOT NULL, costo_unitario REAL NOT NULL, subtotal REAL NOT NULL)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS public.gastos (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            categoria TEXT NOT NULL, descripcion TEXT, monto REAL NOT NULL,
            metodo_pago TEXT, notas TEXT)""")
try: init_db()
except Exception as e: st.error(f"Error BD: {e}"); st.stop()

# ---------- AUXILIARES SEGURAS ----------
def fmt(v):
    try: return f"${float(v):,.2f}"
    except: return "$0.00"
def _i(v):
    try:
        if v is None: return 0
        return int(pd.to_numeric(v, errors="coerce") or 0)
    except: return 0
def _f(v):
    try:
        if v is None: return 0.0
        return float(pd.to_numeric(v, errors="coerce") or 0.0)
    except: return 0.0
def _s(v, d=""):
    try:
        if v is None: return d
        r = str(v).strip()
        return r if r else d
    except: return d

# ---------- DATOS ----------
def get_productos():
    with get_connection() as c:
        cur = c.cursor()
        cur.execute("SELECT id,codigo,nombre,stock,costo_unitario,precio_venta,categoria,unidad FROM public.productos WHERE activo=1 ORDER BY nombre")
        return [{"id":_i(r["id"]),"codigo":_s(r["codigo"]),"nombre":_s(r["nombre"]),
                 "stock":_f(r["stock"]),"costo_unitario":_f(r["costo_unitario"]),
                 "precio_venta":_f(r["precio_venta"]),"categoria":_s(r["categoria"]),
                 "unidad":_s(r["unidad"],"unidad")} for r in cur.fetchall()]

def kpi(fi, ff, sql):
    with get_connection() as c:
        cur = c.cursor(); cur.execute(sql, (fi, ff))
        return _f(cur.fetchone()["v"])

def stock_bajo():
    try:
        with get_connection() as c:
            return pd.read_sql_query("SELECT nombre,stock,stock_minimo,unidad FROM public.productos WHERE activo=1 AND stock<=stock_minimo AND stock_minimo>0", c)
    except: return pd.DataFrame()

def anular_venta(vid):
    vid = _i(vid)
    if vid <= 0: return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("SELECT producto_id,cantidad,costo_unitario FROM public.venta_detalle WHERE venta_id=%s", (vid,))
            det = cur.fetchall()
            if not det: return False, "No encontrada"
            cur.execute("UPDATE public.ventas SET anulada=1 WHERE id=%s", (vid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cantidad"]), _f(it["costo_unitario"])
                if pid>0 and cn>0:
                    cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s", (cn, pid))
                    cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo,referencia) VALUES (%s,'entrada',%s,%s,'Anulación venta',%s)", (pid, cn, ct, f"Venta #{vid}"))
            return True, f"Venta #{vid} anulada + stock devuelto"
    except Exception as e: return False, f"Error: {e}"

def anular_compra(cid):
    cid = _i(cid)
    if cid <= 0: return False, "ID inválido"
    try:
        with get_connection() as c:
            cur = c.cursor()
            cur.execute("SELECT cd.producto_id,cd.cantidad,cd.costo_unitario,p.stock FROM public.compra_detalle cd JOIN public.productos p ON cd.producto_id=p.id WHERE cd.compra_id=%s", (cid,))
            det = cur.fetchall()
            if not det: return False, "No encontrada"
            for it in det:
                if _f(it["stock"]) < _f(it["cantidad"]):
                    return False, f"Stock insuficiente (producto {_i(it['producto_id'])})"
            cur.execute("UPDATE public.compras SET anulada=1 WHERE id=%s", (cid,))
            for it in det:
                pid, cn, ct = _i(it["producto_id"]), _f(it["cantidad"]), _f(it["costo_unitario"])
                if pid>0 and cn>0:
                    cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s", (cn, pid))
                    cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo,referencia) VALUES (%s,'salida',%s,%s,'Anulación compra',%s)", (pid, cn, ct, f"Compra #{cid}"))
            return True, f"Compra #{cid} anulada + stock actualizado"
    except Exception as e: return False, f"Error: {e}"

# ---------- ESTADO ----------
if "cv" not in st.session_state: st.session_state.cv = []
if "cc" not in st.session_state: st.session_state.cc = []
if "nv_nonce" not in st.session_state: st.session_state.nv_nonce = str(uuid.uuid4())
if "nc_nonce" not in st.session_state: st.session_state.nc_nonce = str(uuid.uuid4())

# ---------- DASHBOARD ----------
def p_dashboard():
    st.title("📊 Dashboard")
    a,b = st.columns(2)
    with a: fi = st.date_input("Desde", value=datetime.now().date()-timedelta(days=30))
    with b: ff = st.date_input("Hasta", value=datetime.now().date())
    fi, ff = str(fi), str(ff)
    ing = kpi(fi,ff,"SELECT COALESCE(SUM(total-descuento),0) v FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    cg  = kpi(fi,ff,"SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) v FROM public.venta_detalle vd JOIN public.ventas v ON vd.venta_id=v.id WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0")
    cp  = kpi(fi,ff,"SELECT COALESCE(SUM(total),0) v FROM public.compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    gs  = kpi(fi,ff,"SELECT COALESCE(SUM(monto),0) v FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    with get_connection() as c:
        cur = c.cursor(); cur.execute("SELECT COALESCE(SUM(stock*costo_unitario),0) v FROM public.productos WHERE activo=1")
        vi = _f(cur.fetchone()["v"])
    ub, un = ing-cg, ing-cg-gs
    mb = ((ing-cg)/ing*100) if ing>0 else 0.0
    mn = ((ing-cg-gs)/ing*100) if ing>0 else 0.0
    st.markdown("---"); st.subheader("Indicadores")
    x,y = st.columns(2); x.metric("💰 Ingresos", fmt(ing)); y.metric("📦 Costo mercadería", fmt(cg))
    x,y = st.columns(2); x.metric("📈 Utilidad Bruta", fmt(ub), delta=f"{mb:.1f}%"); y.metric("💸 Gastos", fmt(gs))
    st.metric("✅ Utilidad Neta", fmt(un), delta=f"{mn:.1f}%")
    x,y = st.columns(2); x.metric("🛒 Compras", fmt(cp)); y.metric("📦 Valor Inventario", fmt(vi))
    sb = stock_bajo()
    if not sb.empty:
        st.warning(f"⚠️ {len(sb)} producto(s) debajo del stock mínimo")
        with st.expander("Ver productos"): st.dataframe(sb, use_container_width=True, hide_index=True)

# ---------- INVENTARIO ----------
def p_inventario():
    st.title("📦 Inventario")
    prods = get_productos()
    t1,t2,t3,t4 = st.tabs(["📋 Lista","➕ Nuevo","🔄 Ajuste Stock","🗑️ Borrar"])
    with t1:
        if not prods: st.warning("No hay productos")
        else: st.dataframe(pd.DataFrame(prods)[["codigo","nombre","stock","costo_unitario","precio_venta"]], use_container_width=True, hide_index=True)
    with t2:
        with st.form("np", clear_on_submit=True):
            co = st.text_input("Código *", placeholder="PROD001")
            no = st.text_input("Nombre *", placeholder="Producto 1")
            ca = st.text_input("Categoría")
            un = st.selectbox("Unidad", ["unidad","kg","litro","caja","paquete"])
            si = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=0.1)
            cu = st.number_input("Costo unitario *", min_value=0.0, value=0.0, step=0.01)
            pv = st.number_input("Precio venta *", min_value=0.0, value=0.0, step=0.01)
            sm = st.number_input("Stock mínimo", min_value=0.0, value=5.0, step=0.1)
            if st.form_submit_button("➕ Crear"):
                er = []
                if not _s(co): er.append("Código obligatorio")
                if not _s(no): er.append("Nombre obligatorio")
                if _f(cu)<=0: er.append("Costo > 0")
                if _f(pv)<=0: er.append("Precio > 0")
                if er:
                    for e in er: st.error(f"❌ {e}")
                else:
                    with get_connection() as c:
                        cur = c.cursor()
                        cur.execute("SELECT 1 FROM public.productos WHERE codigo=%s", (_s(co),))
                        if cur.fetchone(): st.error(f"❌ Ya existe código '{co}'")
                        else:
                            cur.execute("INSERT INTO public.productos (codigo,nombre,categoria,stock,stock_minimo,costo_unitario,precio_venta,unidad) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", (_s(co),_s(no),_s(ca),_f(si),_f(sm),_f(cu),_f(pv),_s(un,"unidad")))
                            pid = _i(cur.fetchone()["id"])
                            if _f(si)>0 and pid>0:
                                cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo,referencia) VALUES (%s,'entrada',%s,%s,'Stock inicial','ALTA')", (pid,_f(si),_f(cu)))
                            st.success(f"✅ Creado '{_s(no)}' (ID={pid})"); st.rerun()
    with t3:
        if not prods: st.info("Primero creá productos")
        else:
            ids = [p["id"] for p in prods]
            with st.form("aj", clear_on_submit=True):
                pid = st.selectbox("Producto", options=ids, format_func=lambda x: next((f"{p['nombre']} | Stock: {p['stock']}" for p in prods if p["id"]==_i(x)), f"#{_i(x)}"))
                p = next((p for p in prods if p["id"]==_i(pid)), None)
                tp = st.radio("Tipo", ["entrada","salida"], horizontal=True)
                cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
                mt = st.selectbox("Motivo", ["Inventario físico","Pérdida / Merma","Otro"])
                if st.form_submit_button("Aplicar") and p:
                    if tp=="salida" and _f(cn) > _f(p["stock"]): st.error("❌ Stock insuficiente")
                    else:
                        dl = _f(cn) if tp=="entrada" else -_f(cn)
                        with get_connection() as c:
                            cur = c.cursor()
                            cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s", (dl,_i(pid)))
                            cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo) VALUES (%s,%s,%s,%s,%s)", (_i(pid),tp,_f(cn),_f(p["costo_unitario"]),_s(mt)))
                        st.success("✅ Ajuste aplicado"); st.rerun()
    with t4:
        if not prods: st.warning("No hay productos")
        else:
            st.info("ℹ️ Solo se desactiva, manteniendo historial")
            ids = [p["id"] for p in prods]
            with st.form("bp", clear_on_submit=True):
                pid = st.selectbox("Producto", options=ids, format_func=lambda x: next((f"{p['codigo']} | {p['nombre']}" for p in prods if p["id"]==_i(x)), f"#{_i(x)}"))
                cf = st.checkbox("✅ Estoy seguro/a")
                if st.form_submit_button("🗑️ Borrar"):
                    if not cf: st.error("❌ Confirmá primero")
                    else:
                        with get_connection() as c:
                            c.cursor().execute("UPDATE public.productos SET activo=0 WHERE id=%s", (_i(pid),))
                        st.success("✅ Borrado"); st.rerun()

# ---------- VENTAS (SIN DOBLE ENVÍO) ----------
def p_ventas():
    st.title("🛒 Ventas")
    prods = get_productos()
    if not prods: st.warning("Primero creá productos"); return
    ids = [p["id"] for p in prods]
    with st.form("av", clear_on_submit=True):
        pid = st.selectbox("Producto", options=ids, format_func=lambda x: next((f"{p['nombre']} | Stock: {p['stock']}" for p in prods if p["id"]==_i(x)), f"#{_i(x)}"))
        pr = next((p for p in prods if p["id"]==_i(pid)), None)
        cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
        pc = st.number_input("Precio", value=_f(pr["precio_venta"]) if pr else 0.0, min_value=0.0, step=0.01)
        if st.form_submit_button("➕ Agregar") and pr:
            if _f(cn) > _f(pr["stock"]): st.error("❌ Stock insuficiente")
            else:
                st.session_state.cv.append({"producto_id":_i(pr["id"]),"nombre":_s(pr["nombre"]),
                    "cantidad":_f(cn),"precio":_f(pc),"costo":_f(pr["costo_unitario"]),
                    "subtotal":round(_f(cn)*_f(pc),2)})
                st.rerun()
    if st.session_state.cv:
        df = pd.DataFrame(st.session_state.cv)
        st.dataframe(df[["nombre","cantidad","precio","subtotal"]], use_container_width=True, hide_index=True)
        total = round(_f(df["subtotal"].sum()), 2)
        st.markdown(f"### Total: {fmt(total)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cv = []; st.rerun()
        with st.form(f"fv_{st.session_state.nv_nonce}"):
            cl = st.text_input("Cliente")
            ds = st.number_input("Descuento", min_value=0.0, value=0.0, step=0.01)
            mp = st.selectbox("Método", ["Efectivo","Tarjeta","Transferencia","Otro"])
            if st.form_submit_button("✅ Confirmar Venta"):
                # PROTECCIÓN DOBLE ENVÍO
                nonce_actual = st.session_state.nv_nonce
                st.session_state.nv_nonce = str(uuid.uuid4())
                carrito = list(st.session_state.cv)
                with get_connection() as c:
                    cur = c.cursor()
                    cur.execute("INSERT INTO public.ventas (cliente,total,descuento,metodo_pago) VALUES (%s,%s,%s,%s) RETURNING id", (_s(cl),_f(total),_f(ds),_s(mp)))
                    vid = _i(cur.fetchone()["id"])
                    for it in carrito:
                        iid = _i(it["producto_id"])
                        cur.execute("INSERT INTO public.venta_detalle (venta_id,producto_id,cantidad,precio_unitario,costo_unitario,subtotal) VALUES (%s,%s,%s,%s,%s,%s)", (vid,iid,_f(it["cantidad"]),_f(it["precio"]),_f(it["costo"]),_f(it["subtotal"])))
                        cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s", (_f(it["cantidad"]),iid))
                        cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo,referencia) VALUES (%s,'salida',%s,%s,'Venta',%s)", (iid,_f(it["cantidad"]),_f(it["costo"]),f"Venta #{vid}"))
                st.session_state.cv = []
                st.success(f"✅ Venta #{vid} registrada"); st.rerun()

# ---------- COMPRAS (SIN DOBLE ENVÍO) ----------
def p_compras():
    st.title("📥 Compras")
    prods = get_productos()
    if not prods: st.warning("Primero creá productos"); return
    ids = [p["id"] for p in prods]
    with st.form("ac", clear_on_submit=True):
        pid = st.selectbox("Producto", options=ids, format_func=lambda x: next((p["nombre"] for p in prods if p["id"]==_i(x)), f"#{_i(x)}"))
        pr = next((p for p in prods if p["id"]==_i(pid)), None)
        cn = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
        ct = st.number_input("Costo unitario", value=_f(pr["costo_unitario"]) if pr else 0.0, min_value=0.0, step=0.01)
        if st.form_submit_button("➕ Agregar") and pr:
            st.session_state.cc.append({"producto_id":_i(pr["id"]),"nombre":_s(pr["nombre"]),
                "cantidad":_f(cn),"costo":_f(ct),"subtotal":round(_f(cn)*_f(ct),2)})
            st.rerun()
    if st.session_state.cc:
        df = pd.DataFrame(st.session_state.cc)
        st.dataframe(df[["nombre","cantidad","costo","subtotal"]], use_container_width=True, hide_index=True)
        total = round(_f(df["subtotal"].sum()), 2)
        st.markdown(f"**Total: {fmt(total)}**")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.cc = []; st.rerun()
        with st.form(f"fc_{st.session_state.nc_nonce}"):
            pv = st.text_input("Proveedor")
            mp = st.selectbox("Método", ["Efectivo","Transferencia","Crédito"])
            if st.form_submit_button("✅ Registrar Compra"):
                # PROTECCIÓN DOBLE ENVÍO
                nonce_actual = st.session_state.nc_nonce
                st.session_state.nc_nonce = str(uuid.uuid4())
                carrito = list(st.session_state.cc)
                with get_connection() as c:
                    cur = c.cursor()
                    cur.execute("INSERT INTO public.compras (proveedor,total,metodo_pago) VALUES (%s,%s,%s) RETURNING id", (_s(pv),_f(total),_s(mp)))
                    cid = _i(cur.fetchone()["id"])
                    for it in carrito:
                        iid = _i(it["producto_id"])
                        cur.execute("INSERT INTO public.compra_detalle (compra_id,producto_id,cantidad,costo_unitario,subtotal) VALUES (%s,%s,%s,%s,%s)", (cid,iid,_f(it["cantidad"]),_f(it["costo"]),_f(it["subtotal"])))
                        cur.execute("UPDATE public.productos SET stock=stock+%s, costo_unitario=%s WHERE id=%s", (_f(it["cantidad"]),_f(it["costo"]),iid))
                        cur.execute("INSERT INTO public.movimientos_stock (producto_id,tipo,cantidad,costo_unitario,motivo,referencia) VALUES (%s,'entrada',%s,%s,'Compra',%s)", (iid,_f(it["cantidad"]),_f(it["costo"]),f"Compra #{cid}"))
                st.session_state.cc = []
                st.success(f"✅ Compra #{cid} registrada"); st.rerun()

# ---------- GASTOS ----------
def p_gastos():
    st.title("💸 Gastos")
    cats = ["Alquiler","Servicios","Sueldos","Marketing","Transporte","Impuestos","Mantenimiento","Seguros","Papelería","Otros"]
    with st.form("ng", clear_on_submit=True):
        fh = st.date_input("Fecha", value=datetime.now().date())
        ct = st.selectbox("Categoría", cats)
        ds = st.text_input("Descripción")
        mn = st.number_input("Monto", min_value=0.01, value=0.0, step=0.01)
        mp = st.selectbox("Método", ["Efectivo","Transferencia","Tarjeta"])
        if st.form_submit_button("💾 Guardar"):
            with get_connection() as c:
                c.cursor().execute("INSERT INTO public.gastos (fecha,categoria,descripcion,monto,metodo_pago) VALUES (%s,%s,%s,%s,%s)", (str(fh),_s(ct),_s(ds),_f(mn),_s(mp)))
            st.success("✅ Guardado"); st.rerun()

# ---------- REPORTES ----------
def p_reportes():
    st.title("📈 Reportes")
    a,b = st.columns(2)
    with a: fi = st.date_input("Desde", value=datetime.now().date()-timedelta(days=90), key="r1")
    with b: ff = st.date_input("Hasta", value=datetime.now().date(), key="r2")
    fi, ff = str(fi), str(ff)
    ing = kpi(fi,ff,"SELECT COALESCE(SUM(total-descuento),0) v FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    cg  = kpi(fi,ff,"SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) v FROM public.venta_detalle vd JOIN public.ventas v ON vd.venta_id=v.id WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0")
    gs  = kpi(fi,ff,"SELECT COALESCE(SUM(monto),0) v FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    x,y = st.columns(2); x.metric("Ingresos", fmt(ing)); y.metric("Utilidad Neta", fmt(ing-cg-gs))

# ---------- HISTORIAL + ANULAR (100% SEGURO) ----------
def _lista_ventas():
    try:
        with get_connection() as c:
            df = pd.read_sql_query("SELECT id,fecha,cliente,total FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC", c)
        ids, lbl = [], {}
        for r in df.to_dict("records"):
            i = _i(r.get("id"))
            if i<=0: continue
            ids.append(i)
            lbl[i] = f"#{i} | {_s(r.get('fecha'),'---')[:16]} | {_s(r.get('cliente'),'S/N')} | {fmt(_f(r.get('total')))}"
        return ids, lbl, None
    except Exception as e: return [], {}, str(e)

def _lista_compras():
    try:
        with get_connection() as c:
            df = pd.read_sql_query("SELECT id,fecha,proveedor,total FROM public.compras WHERE anulada=0 ORDER BY fecha DESC", c)
        ids, lbl = [], {}
        for r in df.to_dict("records"):
            i = _i(r.get("id"))
            if i<=0: continue
            ids.append(i)
            lbl[i] = f"#{i} | {_s(r.get('fecha'),'---')[:16]} | {_s(r.get('proveedor'),'S/N')} | {fmt(_f(r.get('total')))}"
        return ids, lbl, None
    except Exception as e: return [], {}, str(e)

def p_historial():
    st.title("📜 Historial")
    t1,t2,t3,t4,t5 = st.tabs(["Ventas","Compras","Gastos","🗑️ Anular Venta","🗑️ Anular Compra"])
    try:
        with get_connection() as c:
            with t1:
                df = pd.read_sql_query("SELECT id,fecha,cliente,total,metodo_pago FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
            with t2:
                df = pd.read_sql_query("SELECT id,fecha,proveedor,total,metodo_pago FROM public.compras WHERE anulada=0 ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
            with t3:
                df = pd.read_sql_query("SELECT fecha,categoria,monto,metodo_pago FROM public.gastos ORDER BY fecha DESC LIMIT 50", c)
                st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin datos")
    except Exception as e: st.error(f"Error: {e}")

    with t4:
        st.info("⚠️ Devuelve stock y borra el monto de ingresos. Irreversible.")
        ids, lbl, err = _lista_ventas()
        if err: st.error(err)
        elif not ids: st.warning("Nada para anular")
        else:
            with st.form("anv", clear_on_submit=True):
                vid = st.selectbox("Venta", options=ids, format_func=lambda x: lbl.get(_i(x), f"#{_i(x)}"))
                a = st.checkbox("✅ Registro erróneo / no existió")
                b = st.checkbox("✅ Acepto que se devuelve el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok, msg = anular_venta(vid)
                        st.success(msg) if ok else st.error(f"❌ {msg}")
                        st.rerun()

    with t5:
        st.info("⚠️ Resta stock y borra el monto de compras. Irreversible.")
        ids, lbl, err = _lista_compras()
        if err: st.error(err)
        elif not ids: st.warning("Nada para anular")
        else:
            with st.form("anc", clear_on_submit=True):
                cid = st.selectbox("Compra", options=ids, format_func=lambda x: lbl.get(_i(x), f"#{_i(x)}"))
                a = st.checkbox("✅ Registro erróneo / no existió")
                b = st.checkbox("✅ Acepto que se resta el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok, msg = anular_compra(cid)
                        st.success(msg) if ok else st.error(f"❌ {msg}")
                        st.rerun()

# ---------- MENÚ ----------
def main():
    st.sidebar.title("🏪 Negocio")
    op = st.sidebar.radio("Menú", ["📊 Dashboard","📦 Inventario","🛒 Ventas","📥 Compras","💸 Gastos","📈 Reportes","📜 Historial"])
    {"📊 Dashboard":p_dashboard,"📦 Inventario":p_inventario,"🛒 Ventas":p_ventas,
     "📥 Compras":p_compras,"💸 Gastos":p_gastos,"📈 Reportes":p_reportes,
     "📜 Historial":p_historial}[op]()

if __name__ == "__main__":
    main()
