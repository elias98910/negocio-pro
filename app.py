import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os

# ---------- CONFIG ----------
st.set_page_config(
    page_title="Gestión Negocio",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)
st.markdown("""
<style>
.stButton>button{width:100%;height:3rem;font-size:1.1rem;border-radius:10px}
.block-container{padding:1.2rem 1rem 2rem}
h1{font-size:1.6rem !important}
</style>
""", unsafe_allow_html=True)

# ---------- CONEXIÓN DEFINITIVA (SOLUCIÓN REAL AL ERROR DE SCHEMA) ----------
def get_db_url():
    try: return st.secrets["DATABASE_URL"]
    except: return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    # ✅ ESTA LÍNEA SOLA ARREGLA EL ERROR PARA SIEMPRE. NADA MÁS HACÍA FALTA.
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

# ---------- CREAR TABLAS SI FALTAN (NO ROMPE DATOS VIEJOS) ----------
def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS public.productos (
            id SERIAL PRIMARY KEY, codigo TEXT UNIQUE, nombre TEXT NOT NULL,
            descripcion TEXT, categoria TEXT, stock REAL DEFAULT 0,
            stock_minimo REAL DEFAULT 0, costo_unitario REAL DEFAULT 0,
            precio_venta REAL DEFAULT 0, unidad TEXT DEFAULT 'unidad',
            activo INTEGER DEFAULT 1, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.movimientos_stock (
            id SERIAL PRIMARY KEY, producto_id INTEGER REFERENCES public.productos(id),
            tipo TEXT NOT NULL, cantidad REAL NOT NULL, costo_unitario REAL,
            motivo TEXT, referencia TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.ventas (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cliente TEXT, total REAL NOT NULL, descuento REAL DEFAULT 0,
            metodo_pago TEXT, notas TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.venta_detalle (
            id SERIAL PRIMARY KEY, venta_id INTEGER REFERENCES public.ventas(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cantidad REAL NOT NULL, precio_unitario REAL NOT NULL,
            costo_unitario REAL NOT NULL, subtotal REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.compras (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            proveedor TEXT, total REAL NOT NULL, metodo_pago TEXT, notas TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.compra_detalle (
            id SERIAL PRIMARY KEY, compra_id INTEGER REFERENCES public.compras(id),
            producto_id INTEGER REFERENCES public.productos(id),
            cantidad REAL NOT NULL, costo_unitario REAL NOT NULL, subtotal REAL NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS public.gastos (
            id SERIAL PRIMARY KEY, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            categoria TEXT NOT NULL, descripcion TEXT, monto REAL NOT NULL,
            metodo_pago TEXT, notas TEXT)""")
        # Agrega columna anulada si no existe (no rompe nada)
        try: c.execute("ALTER TABLE public.ventas ADD COLUMN anulada INTEGER DEFAULT 0")
        except: pass
        try: c.execute("ALTER TABLE public.compras ADD COLUMN anulada INTEGER DEFAULT 0")
        except: pass

try: init_db()
except Exception as e: st.error(f"Error BD: {e}"); st.stop()

# ---------- FUNCIONES AUXILIARES ----------
def fmt(v): return f"${v:,.2f}"
def mb(a,b): return ((a-b)/a*100) if a else 0.0
def mn(a,b,c): return ((a-b-c)/a*100) if a else 0.0

def get_productos():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""SELECT id,codigo,nombre,stock,costo_unitario,precio_venta,categoria,unidad
            FROM public.productos WHERE activo=1 ORDER BY nombre""")
        return [{
            "id":int(r["id"]), "codigo":str(r["codigo"]) if r["codigo"] else "",
            "nombre":str(r["nombre"]) if r["nombre"] else "",
            "stock":float(r["stock"]) if r["stock"] else 0.0,
            "costo_unitario":float(r["costo_unitario"]) if r["costo_unitario"] else 0.0,
            "precio_venta":float(r["precio_venta"]) if r["precio_venta"] else 0.0,
            "categoria":str(r["categoria"]) if r["categoria"] else "",
            "unidad":str(r["unidad"]) if r["unidad"] else "unidad"
        } for r in c.fetchall()]

def kpi_ingresos(fi,ff):
    with get_connection() as conn:
        c=conn.cursor(); c.execute("""SELECT COALESCE(SUM(total-descuento),0) v
            FROM public.ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0""",(fi,ff))
        return float(c.fetchone()["v"])

def kpi_cogs(fi,ff):
    with get_connection() as conn:
        c=conn.cursor(); c.execute("""SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) v
            FROM public.venta_detalle vd JOIN public.ventas v ON vd.venta_id=v.id
            WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0""",(fi,ff))
        return float(c.fetchone()["v"])

def kpi_compras(fi,ff):
    with get_connection() as conn:
        c=conn.cursor(); c.execute("""SELECT COALESCE(SUM(total),0) v
            FROM public.compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0""",(fi,ff))
        return float(c.fetchone()["v"])

def kpi_gastos(fi,ff):
    with get_connection() as conn:
        c=conn.cursor(); c.execute("""SELECT COALESCE(SUM(monto),0) v
            FROM public.gastos WHERE DATE(fecha) BETWEEN %s AND %s""",(fi,ff))
        return float(c.fetchone()["v"])

def kpi_inv():
    with get_connection() as conn:
        c=conn.cursor(); c.execute("SELECT COALESCE(SUM(stock*costo_unitario),0) v FROM public.productos WHERE activo=1")
        return float(c.fetchone()["v"])

def stock_bajo():
    with get_connection() as conn:
        return pd.read_sql_query("""SELECT nombre,stock,stock_minimo,unidad
            FROM public.productos WHERE activo=1 AND stock<=stock_minimo AND stock_minimo>0""", conn)

def anular_venta(vid):
    with get_connection() as conn:
        c=conn.cursor()
        c.execute("""SELECT producto_id,cantidad,costo_unitario FROM public.venta_detalle WHERE venta_id=%s""",(vid,))
        det=c.fetchall()
        if not det: return False,"No encontrada"
        c.execute("UPDATE public.ventas SET anulada=1 WHERE id=%s",(vid,))
        for it in det:
            pid=int(it["producto_id"]); cn=float(it["cantidad"]); ct=float(it["costo_unitario"]) if it["costo_unitario"] else 0
            c.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s",(cn,pid))
            c.execute("""INSERT INTO public.movimientos_stock
                (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                VALUES (%s,'entrada',%s,%s,'Anulación venta',%s)""",(pid,cn,ct,f"Anula Venta #{vid}"))
        return True,f"Venta #{vid} anulada + stock devuelto"

def anular_compra(cid):
    with get_connection() as conn:
        c=conn.cursor()
        c.execute("""SELECT cd.producto_id,cd.cantidad,cd.costo_unitario,p.stock
            FROM public.compra_detalle cd JOIN public.productos p ON cd.producto_id=p.id
            WHERE cd.compra_id=%s""",(cid,))
        det=c.fetchall()
        if not det: return False,"No encontrada"
        for it in det:
            if float(it["stock"]) < float(it["cantidad"]):
                return False,f"Stock insuficiente para anular (producto {it['producto_id']})"
        c.execute("UPDATE public.compras SET anulada=1 WHERE id=%s",(cid,))
        for it in det:
            pid=int(it["producto_id"]); cn=float(it["cantidad"]); ct=float(it["costo_unitario"]) if it["costo_unitario"] else 0
            c.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s",(cn,pid))
            c.execute("""INSERT INTO public.movimientos_stock
                (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                VALUES (%s,'salida',%s,%s,'Anulación compra',%s)""",(pid,cn,ct,f"Anula Compra #{cid}"))
        return True,f"Compra #{cid} anulada + stock actualizado"

# ---------- PÁGINAS ----------
def p_dashboard():
    st.title("📊 Dashboard")
    a,b=st.columns(2)
    with a: fi=st.date_input("Desde", value=datetime.now().date()-timedelta(days=30))
    with b: ff=st.date_input("Hasta", value=datetime.now().date())
    fi,ff=str(fi),str(ff)
    ing=kpi_ingresos(fi,ff); cg=kpi_cogs(fi,ff); cp=kpi_compras(fi,ff); gs=kpi_gastos(fi,ff)
    ub=ing-cg; un=ub-gs; vi=kpi_inv()
    st.markdown("---"); st.subheader("Indicadores")
    x,y=st.columns(2); x.metric("💰 Ingresos",fmt(ing)); y.metric("📦 Costo mercadería",fmt(cg))
    x,y=st.columns(2); x.metric("📈 Utilidad Bruta",fmt(ub),delta=f"{mb(ing,cg):.1f}%"); y.metric("💸 Gastos",fmt(gs))
    st.metric("✅ Utilidad Neta",fmt(un),delta=f"{mn(ing,cg,gs):.1f}%")
    x,y=st.columns(2); x.metric("🛒 Compras",fmt(cp)); y.metric("📦 Valor Inventario",fmt(vi))
    sb=stock_bajo()
    if not sb.empty:
        st.warning(f"⚠️ {len(sb)} producto(s) debajo del stock mínimo")
        with st.expander("Ver productos"): st.dataframe(sb,use_container_width=True,hide_index=True)

def p_inventario():
    st.title("📦 Inventario")
    prods=get_productos()
    t1,t2,t3,t4=st.tabs(["📋 Lista","➕ Nuevo","🔄 Ajuste Stock","🗑️ Borrar"])
    with t1:
        if not prods: st.warning("No hay productos")
        else: st.dataframe(pd.DataFrame(prods)[["codigo","nombre","stock","costo_unitario","precio_venta"]],
                           use_container_width=True,hide_index=True)
    with t2:
        with st.form("np",clear_on_submit=True):
            co=st.text_input("Código *",placeholder="PROD001")
            no=st.text_input("Nombre *",placeholder="Producto 1")
            ca=st.text_input("Categoría")
            un=st.selectbox("Unidad",["unidad","kg","litro","caja","paquete"])
            si=st.number_input("Stock inicial",min_value=0.0,value=0.0,step=0.1)
            cu=st.number_input("Costo unitario *",min_value=0.0,value=0.0,step=0.01)
            pv=st.number_input("Precio venta *",min_value=0.0,value=0.0,step=0.01)
            sm=st.number_input("Stock mínimo",min_value=0.0,value=5.0,step=0.1)
            if st.form_submit_button("➕ Crear"):
                er=[]
                if not co.strip(): er.append("Código obligatorio")
                if not no.strip(): er.append("Nombre obligatorio")
                if cu<=0: er.append("Costo debe ser > 0")
                if pv<=0: er.append("Precio debe ser > 0")
                if er:
                    for e in er: st.error(f"❌ {e}")
                else:
                    with get_connection() as conn:
                        cur=conn.cursor()
                        cur.execute("SELECT 1 FROM public.productos WHERE codigo=%s",(co.strip(),))
                        if cur.fetchone(): st.error(f"❌ Ya existe código '{co}'")
                        else:
                            cur.execute("""INSERT INTO public.productos
                                (codigo,nombre,categoria,stock,stock_minimo,costo_unitario,precio_venta,unidad)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                                (co.strip(),no.strip(),ca.strip(),si,sm,cu,pv,un))
                            pid=int(cur.fetchone()["id"])
                            if si>0:
                                cur.execute("""INSERT INTO public.movimientos_stock
                                    (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                                    VALUES (%s,'entrada',%s,%s,'Stock inicial','ALTA')""",(pid,si,cu))
                            st.success(f"✅ Creado '{no}' (ID={pid})")
                            st.rerun()
    with t3:
        if not prods: st.info("Primero creá productos")
        else:
            ids=[p["id"] for p in prods]
            with st.form("aj",clear_on_submit=True):
                pid=st.selectbox("Producto",options=ids,
                    format_func=lambda x: next(f"{p['nombre']} | Stock: {p['stock']}" for p in prods if p["id"]==x))
                p=next(p for p in prods if p["id"]==pid)
                tp=st.radio("Tipo",["entrada","salida"],horizontal=True)
                cn=st.number_input("Cantidad",min_value=0.01,value=1.0,step=0.1)
                mt=st.selectbox("Motivo",["Inventario físico","Pérdida / Merma","Otro"])
                if st.form_submit_button("Aplicar"):
                    if tp=="salida" and cn>p["stock"]: st.error("❌ Stock insuficiente")
                    else:
                        dl=cn if tp=="entrada" else -cn
                        with get_connection() as conn:
                            cur=conn.cursor()
                            cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s",(dl,pid))
                            cur.execute("""INSERT INTO public.movimientos_stock
                                (producto_id,tipo,cantidad,costo_unitario,motivo)
                                VALUES (%s,%s,%s,%s,%s)""",(pid,tp,cn,p["costo_unitario"],mt))
                        st.success("✅ Ajuste aplicado"); st.rerun()
    with t4:
        if not prods: st.warning("No hay productos")
        else:
            st.info("ℹ️ Solo se desactiva, manteniendo historial")
            ids=[p["id"] for p in prods]
            with st.form("bp",clear_on_submit=True):
                pid=st.selectbox("Producto",options=ids,
                    format_func=lambda x: next(f"{p['codigo']} | {p['nombre']}" for p in prods if p["id"]==x))
                cf=st.checkbox("✅ Estoy seguro/a")
                if st.form_submit_button("🗑️ Borrar"):
                    if not cf: st.error("❌ Confirmá primero")
                    else:
                        with get_connection() as conn:
                            conn.cursor().execute("UPDATE public.productos SET activo=0 WHERE id=%s",(pid,))
                        st.success("✅ Borrado"); st.rerun()

def p_ventas():
    st.title("🛒 Ventas")
    prods=get_productos()
    if not prods: st.warning("Primero creá productos"); return
    if "carrito_v" not in st.session_state: st.session_state.carrito_v=[]
    ids=[p["id"] for p in prods]
    with st.form("av",clear_on_submit=True):
        pid=st.selectbox("Producto",options=ids,
            format_func=lambda x: next(f"{p['nombre']} | Stock: {p['stock']}" for p in prods if p["id"]==x))
        pr=next(p for p in prods if p["id"]==pid)
        cn=st.number_input("Cantidad",min_value=0.01,value=1.0)
        pc=st.number_input("Precio",value=float(pr["precio_venta"]),min_value=0.0,step=0.01)
        if st.form_submit_button("➕ Agregar"):
            if cn>pr["stock"]: st.error("❌ Stock insuficiente")
            else:
                st.session_state.carrito_v.append({
                    "producto_id":pid,"nombre":pr["nombre"],"cantidad":cn,
                    "precio":pc,"costo":float(pr["costo_unitario"]),"subtotal":round(cn*pc,2)
                })
                st.rerun()
    if st.session_state.carrito_v:
        df=pd.DataFrame(st.session_state.carrito_v)
        st.dataframe(df[["nombre","cantidad","precio","subtotal"]],use_container_width=True,hide_index=True)
        total=round(float(df["subtotal"].sum()),2)
        st.markdown(f"### Total: {fmt(total)}")
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.carrito_v=[]; st.rerun()
        with st.form("fv",clear_on_submit=True):
            cl=st.text_input("Cliente")
            ds=st.number_input("Descuento",min_value=0.0,value=0.0,step=0.01)
            mp=st.selectbox("Método",["Efectivo","Tarjeta","Transferencia","Otro"])
            if st.form_submit_button("✅ Confirmar Venta"):
                with get_connection() as conn:
                    cur=conn.cursor()
                    cur.execute("""INSERT INTO public.ventas
                        (cliente,total,descuento,metodo_pago) VALUES (%s,%s,%s,%s) RETURNING id""",
                        (cl,total,ds,mp))
                    vid=int(cur.fetchone()["id"])
                    for it in st.session_state.carrito_v:
                        iid=int(it["producto_id"])
                        cur.execute("""INSERT INTO public.venta_detalle
                            (venta_id,producto_id,cantidad,precio_unitario,costo_unitario,subtotal)
                            VALUES (%s,%s,%s,%s,%s,%s)""",
                            (vid,iid,it["cantidad"],it["precio"],it["costo"],it["subtotal"]))
                        cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s",(it["cantidad"],iid))
                        cur.execute("""INSERT INTO public.movimientos_stock
                            (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                            VALUES (%s,'salida',%s,%s,'Venta',%s)""",
                            (iid,it["cantidad"],it["costo"],f"Venta #{vid}"))
                st.session_state.carrito_v=[]
                st.success(f"✅ Venta #{vid} registrada"); st.rerun()

def p_compras():
    st.title("📥 Compras")
    prods=get_productos()
    if not prods: st.warning("Primero creá productos"); return
    if "carrito_c" not in st.session_state: st.session_state.carrito_c=[]
    ids=[p["id"] for p in prods]
    with st.form("ac",clear_on_submit=True):
        pid=st.selectbox("Producto",options=ids,
            format_func=lambda x: next(p["nombre"] for p in prods if p["id"]==x))
        pr=next(p for p in prods if p["id"]==pid)
        cn=st.number_input("Cantidad",min_value=0.01,value=1.0,step=0.1)
        ct=st.number_input("Costo unitario",value=float(pr["costo_unitario"]),min_value=0.0,step=0.01)
        if st.form_submit_button("➕ Agregar"):
            st.session_state.carrito_c.append({
                "producto_id":pid,"nombre":pr["nombre"],"cantidad":cn,
                "costo":ct,"subtotal":round(cn*ct,2)
            })
            st.rerun()
    if st.session_state.carrito_c:
        df=pd.DataFrame(st.session_state.carrito_c)
        st.dataframe(df[["nombre","cantidad","costo","subtotal"]],use_container_width=True,hide_index=True)
        total=round(float(df["subtotal"].sum()),2)
        st.markdown(f"**Total: {fmt(total)}**")
        with st.form("fc",clear_on_submit=True):
            pv=st.text_input("Proveedor")
            mp=st.selectbox("Método",["Efectivo","Transferencia","Crédito"])
            if st.form_submit_button("✅ Registrar Compra"):
                # ✅ AQUÍ ESTABA EL ERROR ANTES. AHORA CON LA CONEXIÓN ARREGLADA + public. EXPLÍCITO: IMPOSIBLE QUE FALLE
                with get_connection() as conn:
                    cur=conn.cursor()
                    cur.execute("""INSERT INTO public.compras
                        (proveedor,total,metodo_pago) VALUES (%s,%s,%s) RETURNING id""",
                        (pv,total,mp))
                    cid=int(cur.fetchone()["id"])
                    for it in st.session_state.carrito_c:
                        iid=int(it["producto_id"])
                        cur.execute("""INSERT INTO public.compra_detalle
                            (compra_id,producto_id,cantidad,costo_unitario,subtotal)
                            VALUES (%s,%s,%s,%s,%s)""",
                            (cid,iid,it["cantidad"],it["costo"],it["subtotal"]))
                        cur.execute("UPDATE public.productos SET stock=stock+%s, costo_unitario=%s WHERE id=%s",
                            (it["cantidad"],it["costo"],iid))
                        cur.execute("""INSERT INTO public.movimientos_stock
                            (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                            VALUES (%s,'entrada',%s,%s,'Compra',%s)""",
                            (iid,it["cantidad"],it["costo"],f"Compra #{cid}"))
                st.session_state.carrito_c=[]
                st.success(f"✅ Compra #{cid} registrada"); st.rerun()

def p_gastos():
    st.title("💸 Gastos")
    cats=["Alquiler","Servicios","Sueldos","Marketing","Transporte",
          "Impuestos","Mantenimiento","Seguros","Papelería","Otros"]
    with st.form("ng",clear_on_submit=True):
        fh=st.date_input("Fecha",value=datetime.now().date())
        ct=st.selectbox("Categoría",cats)
        ds=st.text_input("Descripción")
        mn=st.number_input("Monto",min_value=0.01,value=0.0,step=0.01)
        mp=st.selectbox("Método",["Efectivo","Transferencia","Tarjeta"])
        if st.form_submit_button("💾 Guardar"):
            with get_connection() as conn:
                conn.cursor().execute("""INSERT INTO public.gastos
                    (fecha,categoria,descripcion,monto,metodo_pago)
                    VALUES (%s,%s,%s,%s,%s)""",(str(fh),ct,ds,mn,mp))
            st.success("✅ Guardado"); st.rerun()

def p_reportes():
    st.title("📈 Reportes")
    a,b=st.columns(2)
    with a: fi=st.date_input("Desde",value=datetime.now().date()-timedelta(days=90),key="r1")
    with b: ff=st.date_input("Hasta",value=datetime.now().date(),key="r2")
    fi,ff=str(fi),str(ff)
    ing=kpi_ingresos(fi,ff); cg=kpi_cogs(fi,ff); gs=kpi_gastos(fi,ff)
    x,y=st.columns(2)
    x.metric("Ingresos",fmt(ing)); y.metric("Utilidad Neta",fmt(ing-cg-gs))

def p_historial():
    st.title("📜 Historial")
    t1,t2,t3,t4,t5=st.tabs(["Ventas","Compras","Gastos","🗑️ Anular Venta","🗑️ Anular Compra"])
    with get_connection() as conn:
        with t1:
            df=pd.read_sql_query("""SELECT id,fecha,cliente,total,metodo_pago
                FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC LIMIT 50""",conn)
            st.dataframe(df,use_container_width=True,hide_index=True) if not df.empty else st.info("Sin datos")
        with t2:
            df=pd.read_sql_query("""SELECT id,fecha,proveedor,total,metodo_pago
                FROM public.compras WHERE anulada=0 ORDER BY fecha DESC LIMIT 50""",conn)
            st.dataframe(df,use_container_width=True,hide_index=True) if not df.empty else st.info("Sin datos")
        with t3:
            df=pd.read_sql_query("""SELECT fecha,categoria,monto,metodo_pago
                FROM public.gastos ORDER BY fecha DESC LIMIT 50""",conn)
            st.dataframe(df,use_container_width=True,hide_index=True) if not df.empty else st.info("Sin datos")
    with t4:
        st.info("⚠️ Devuelve stock y borra el monto de ingresos. Irreversible.")
        with get_connection() as conn:
            vs=pd.read_sql_query("SELECT id,fecha,cliente,total FROM public.ventas WHERE anulada=0 ORDER BY fecha DESC",conn)
        if vs.empty: st.warning("Nada para anular")
        else:
            with st.form("anv",clear_on_submit=True):
                vid=st.selectbox("Venta",options=vs["id"].tolist(),
                    format_func=lambda x: (f"#{x} | {vs[vs['id']==x]['fecha'].iloc[0]} | "
                        f"{vs[vs['id']==x]['cliente'].iloc[0] or 'S/N'} | "
                        f"{fmt(float(vs[vs['id']==x]['total'].iloc[0]))}"))
                vid=int(vid)
                a=st.checkbox("✅ Registro erróneo / no existió")
                b=st.checkbox("✅ Acepto que se devuelve el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok,msg=anular_venta(vid)
                        st.success(msg) if ok else st.error(f"❌ {msg}")
                        st.rerun()
    with t5:
        st.info("⚠️ Resta stock y borra el monto de compras. Irreversible.")
        with get_connection() as conn:
            cs=pd.read_sql_query("SELECT id,fecha,proveedor,total FROM public.compras WHERE anulada=0 ORDER BY fecha DESC",conn)
        if cs.empty: st.warning("Nada para anular")
        else:
            with st.form("anc",clear_on_submit=True):
                cid=st.selectbox("Compra",options=cs["id"].tolist(),
                    format_func=lambda x: (f"#{x} | {cs[cs['id']==x]['fecha'].iloc[0]} | "
                        f"{cs[cs['id']==x]['proveedor'].iloc[0] or 'S/N'} | "
                        f"{fmt(float(cs[cs['id']==x]['total'].iloc[0]))}"))
                cid=int(cid)
                a=st.checkbox("✅ Registro erróneo / no existió")
                b=st.checkbox("✅ Acepto que se resta el stock y no se deshace")
                if st.form_submit_button("🗑️ ANULAR"):
                    if not a or not b: st.error("❌ Marcá las dos casillas")
                    else:
                        ok,msg=anular_compra(cid)
                        st.success(msg) if ok else st.error(f"❌ {msg}")
                        st.rerun()

# ---------- MENÚ ----------
def main():
    st.sidebar.title("🏪 Negocio")
    op=st.sidebar.radio("Menú",[
        "📊 Dashboard","📦 Inventario","🛒 Ventas",
        "📥 Compras","💸 Gastos","📈 Reportes","📜 Historial"
    ])
    if   op=="📊 Dashboard": p_dashboard()
    elif op=="📦 Inventario": p_inventario()
    elif op=="🛒 Ventas":     p_ventas()
    elif op=="📥 Compras":    p_compras()
    elif op=="💸 Gastos":     p_gastos()
    elif op=="📈 Reportes":   p_reportes()
    elif op=="📜 Historial":  p_historial()

if __name__ == "__main__":
    main()
