import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os

# ============================================================
# CONFIGURACIÓN
# ============================================================
st.set_page_config(
    page_title="Gestión de Negocio Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stButton > button {
        width: 100%;
        height: 3rem;
        font-size: 1.1rem;
        border-radius: 10px;
    }
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    h1 { font-size: 1.6rem !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# CONEXIÓN A SUPABASE (BLINDADA SCHEMA PUBLIC)
# ============================================================
def get_db_url():
    try:
        return st.secrets["DATABASE_URL"]
    except:
        return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    conn = psycopg2.connect(get_db_url(), cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO public;")
        cur.close()
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        
        # Tablas originales
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.productos (
                id SERIAL PRIMARY KEY,
                codigo TEXT UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                categoria TEXT,
                stock REAL DEFAULT 0,
                stock_minimo REAL DEFAULT 0,
                costo_unitario REAL DEFAULT 0,
                precio_venta REAL DEFAULT 0,
                unidad TEXT DEFAULT 'unidad',
                activo INTEGER DEFAULT 1,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.movimientos_stock (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER NOT NULL REFERENCES public.productos(id),
                tipo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                costo_unitario REAL,
                motivo TEXT,
                referencia TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.ventas (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cliente TEXT,
                total REAL NOT NULL,
                descuento REAL DEFAULT 0,
                metodo_pago TEXT,
                notas TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.venta_detalle (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER NOT NULL REFERENCES public.ventas(id),
                producto_id INTEGER NOT NULL REFERENCES public.productos(id),
                cantidad REAL NOT NULL,
                precio_unitario REAL NOT NULL,
                costo_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.compras (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proveedor TEXT,
                total REAL NOT NULL,
                metodo_pago TEXT,
                notas TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.compra_detalle (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER NOT NULL REFERENCES public.compras(id),
                producto_id INTEGER NOT NULL REFERENCES public.productos(id),
                cantidad REAL NOT NULL,
                costo_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS public.gastos (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                categoria TEXT NOT NULL,
                descripcion TEXT,
                monto REAL NOT NULL,
                metodo_pago TEXT,
                notas TEXT
            )
        """)
        
        # ✅ NUEVO: Agregamos columna ANULADA (si no existe, no rompe nada)
        c.execute("ALTER TABLE IF EXISTS public.ventas ADD COLUMN IF NOT EXISTS anulada INTEGER DEFAULT 0")
        c.execute("ALTER TABLE IF EXISTS public.compras ADD COLUMN IF NOT EXISTS anulada INTEGER DEFAULT 0")

try:
    init_db()
except Exception as e:
    st.error(f"Error conectando a la base de datos: {e}")
    st.stop()

# ============================================================
# FUNCIONES DE NEGOCIO (TODAS EXCLUYEN ANULADAS)
# ============================================================
def calcular_cogs_periodo(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario), 0) as cogs
            FROM public.venta_detalle vd
            JOIN public.ventas v ON vd.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["cogs"])

def calcular_ingresos(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(total - descuento), 0) as ingresos
            FROM public.ventas
            WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["ingresos"])

def calcular_gastos(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(monto), 0) as total
            FROM public.gastos
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["total"])

def calcular_compras(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(total), 0) as total
            FROM public.compras
            WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["total"])

def valor_inventario():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(stock * costo_unitario), 0) as valor FROM public.productos WHERE activo = 1")
        return float(c.fetchone()["valor"])

def margen_bruto(ingresos, cogs):
    return ((ingresos - cogs) / ingresos * 100) if ingresos else 0.0

def margen_neto(ingresos, cogs, gastos):
    return ((ingresos - cogs - gastos) / ingresos * 100) if ingresos else 0.0

def formato_moneda(valor):
    return f"${valor:,.2f}"

def get_productos_activos():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, categoria, unidad 
            FROM public.productos 
            WHERE activo = 1 
            ORDER BY nombre
        """)
        filas = c.fetchall()
        return [
            {
                "id": int(f["id"]),
                "codigo": str(f["codigo"]) if f["codigo"] else "",
                "nombre": str(f["nombre"]) if f["nombre"] else "",
                "stock": float(f["stock"]) if f["stock"] else 0.0,
                "costo_unitario": float(f["costo_unitario"]) if f["costo_unitario"] else 0.0,
                "precio_venta": float(f["precio_venta"]) if f["precio_venta"] else 0.0,
                "categoria": str(f["categoria"]) if f["categoria"] else "",
                "unidad": str(f["unidad"]) if f["unidad"] else "unidad"
            } for f in filas
        ]

def productos_a_df(lista):
    return pd.DataFrame(lista)

def get_categorias_gastos():
    return ["Alquiler", "Servicios (luz/agua/gas)", "Sueldos", "Marketing", "Transporte", 
            "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"]

# ✅ NUEVO: Funciones para ANULAR VENTA y COMPRA
def anular_venta(venta_id):
    with get_connection() as conn:
        c = conn.cursor()
        # 1. Buscamos el detalle de la venta
        c.execute("""
            SELECT vd.producto_id, vd.cantidad, vd.costo_unitario
            FROM public.venta_detalle vd
            WHERE vd.venta_id = %s
        """, (venta_id,))
        detalle = c.fetchall()
        
        if not detalle:
            return False, "Venta no encontrada"
        
        # 2. Marcamos como anulada
        c.execute("UPDATE public.ventas SET anulada = 1 WHERE id = %s", (venta_id,))
        
        # 3. Devolvemos stock a cada producto + registramos movimiento
        for item in detalle:
            pid = int(item["producto_id"])
            cant = float(item["cantidad"])
            costo = float(item["costo_unitario"]) if item["costo_unitario"] else 0.0
            c.execute("UPDATE public.productos SET stock = stock + %s WHERE id = %s", (cant, pid))
            c.execute("""
                INSERT INTO public.movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                VALUES (%s, 'entrada', %s, %s, 'Anulación de venta', %s)
            """, (pid, cant, costo, f"Anula Venta #{venta_id}"))
        
        return True, f"Venta #{venta_id} anulada correctamente. Stock devuelto."

def anular_compra(compra_id):
    with get_connection() as conn:
        c = conn.cursor()
        # 1. Buscamos detalle
        c.execute("""
            SELECT cd.producto_id, cd.cantidad, cd.costo_unitario, p.stock
            FROM public.compra_detalle cd
            JOIN public.productos p ON cd.producto_id = p.id
            WHERE cd.compra_id = %s
        """, (compra_id,))
        detalle = c.fetchall()
        
        if not detalle:
            return False, "Compra no encontrada"
        
        # 2. Validamos que no quede stock negativo
        for item in detalle:
            if float(item["stock"]) < float(item["cantidad"]):
                return False, f"No se puede anular: el producto '{item['producto_id']}' tiene menos stock que el de la compra."
        
        # 3. Marcamos anulada
        c.execute("UPDATE public.compras SET anulada = 1 WHERE id = %s", (compra_id,))
        
        # 4. Restamos stock + movimiento
        for item in detalle:
            pid = int(item["producto_id"])
            cant = float(item["cantidad"])
            costo = float(item["costo_unitario"]) if item["costo_unitario"] else 0.0
            c.execute("UPDATE public.productos SET stock = stock - %s WHERE id = %s", (cant, pid))
            c.execute("""
                INSERT INTO public.movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                VALUES (%s, 'salida', %s, %s, 'Anulación de compra', %s)
            """, (pid, cant, costo, f"Anula Compra #{compra_id}"))
        
        return True, f"Compra #{compra_id} anulada correctamente. Stock actualizado."

# ============================================================
# DASHBOARD
# ============================================================
def pagina_dashboard():
    st.title("📊 Dashboard")
    
    c1, c2 = st.columns(2)
    with c1:
        fecha_inicio = st.date_input("Desde", value=datetime.now().date() - timedelta(days=30))
    with c2:
        fecha_fin = st.date_input("Hasta", value=datetime.now().date())
    
    fi, ff = fecha_inicio.isoformat(), fecha_fin.isoformat()
    
    ingresos = calcular_ingresos(fi, ff)
    cogs = calcular_cogs_periodo(fi, ff)
    gastos = calcular_gastos(fi, ff)
    compras = calcular_compras(fi, ff)
    utilidad_bruta = ingresos - cogs
    utilidad_neta = utilidad_bruta - gastos
    valor_inv = valor_inventario()
    
    st.markdown("---")
    st.subheader("Indicadores clave")
    
    k1, k2 = st.columns(2)
    k1.metric("💰 Ingresos", formato_moneda(ingresos))
    k2.metric("📦 COGS", formato_moneda(cogs))
    
    k3, k4 = st.columns(2)
    k3.metric("📈 Utilidad Bruta", formato_moneda(utilidad_bruta), delta=f"{margen_bruto(ingresos, cogs):.1f}%")
    k4.metric("💸 Gastos", formato_moneda(gastos))
    
    st.metric("✅ Utilidad Neta", formato_moneda(utilidad_neta), delta=f"{margen_neto(ingresos, cogs, gastos):.1f}%")
    
    m1, m2 = st.columns(2)
    m1.metric("🛒 Compras", formato_moneda(compras))
    m2.metric("📦 Valor Inventario", formato_moneda(valor_inv))
    
    with get_connection() as conn:
        stock_bajo = pd.read_sql_query("""
            SELECT nombre, stock, stock_minimo, unidad 
            FROM public.productos 
            WHERE activo=1 AND stock <= stock_minimo AND stock_minimo > 0
        """, conn)
    
    if not stock_bajo.empty:
        st.warning(f"⚠️ {len(stock_bajo)} producto(s) con stock bajo")
        with st.expander("Ver productos"):
            st.dataframe(stock_bajo, use_container_width=True, hide_index=True)

# ============================================================
# INVENTARIO
# ============================================================
def pagina_inventario():
    st.title("📦 Inventario")
    productos = get_productos_activos()
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Borrar"])
    
    with tab1:
        if not productos:
            st.warning("No hay productos. Crea uno en la pestaña Nuevo.")
        else:
            df = productos_a_df(productos)
            st.dataframe(
                df[["codigo", "nombre", "stock", "costo_unitario", "precio_venta"]], 
                use_container_width=True, 
                hide_index=True
            )
    
    with tab2:
        with st.form("nuevo_producto", clear_on_submit=True):
            codigo = st.text_input("Código / SKU *", placeholder="Ej: PROD001")
            nombre = st.text_input("Nombre *", placeholder="Ej: Coca Cola 1L")
            categoria = st.text_input("Categoría", placeholder="Ej: Bebidas")
            unidad = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"])
            stock_inicial = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=0.1)
            costo = st.number_input("Costo unitario *", min_value=0.0, value=0.0, step=0.01)
            precio = st.number_input("Precio de venta *", min_value=0.0, value=0.0, step=0.01)
            stock_min = st.number_input("Stock mínimo", min_value=0.0, value=5.0, step=0.1)
            
            enviado = st.form_submit_button("➕ Crear producto")
            
            if enviado:
                errores = []
                if not codigo.strip(): errores.append("❌ El Código es obligatorio")
                if not nombre.strip(): errores.append("❌ El Nombre es obligatorio")
                if costo <= 0: errores.append("❌ El Costo debe ser mayor a 0")
                if precio <= 0: errores.append("❌ El Precio de venta debe ser mayor a 0")
                
                if errores:
                    for e in errores: st.error(e)
                else:
                    codigo, nombre, categoria = codigo.strip(), nombre.strip(), categoria.strip()
                    try:
                        with get_connection() as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT 1 FROM public.productos WHERE codigo = %s", (codigo,))
                            if cur.fetchone():
                                st.error(f"❌ Ya existe un producto con el código '{codigo}'")
                                return
                            
                            cur.execute("""
                                INSERT INTO public.productos (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                            """, (codigo, nombre, categoria, stock_inicial, stock_min, costo, precio, unidad))
                            prod_id = int(cur.fetchone()['id'])
                            
                            if stock_inicial > 0:
                                cur.execute("""
                                    INSERT INTO public.movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (prod_id, stock_inicial, costo))
                        
                        st.success(f"✅ Producto '{nombre}' creado (ID={prod_id})")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {type(e).__name__}: {str(e)}")
    
    with tab3:
        if not productos:
            st.info("Primero creá productos")
        else:
            ids = [p["id"] for p in productos]
            with st.form("ajuste", clear_on_submit=True):
                pid = st.selectbox(
                    "Producto", options=ids,
                    format_func=lambda x: next(f"{p['nombre']} | Stock: {p['stock']}" for p in productos if p["id"]==x)
                )
                p = next(p for p in productos if p["id"]==pid)
                tipo = st.radio("Tipo", ["entrada", "salida"], horizontal=True)
                cant = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
                mot = st.selectbox("Motivo", ["Inventario físico", "Pérdida / Merma", "Otro"])
                
                if st.form_submit_button("Aplicar ajuste"):
                    if tipo=="salida" and cant > p["stock"]:
                        st.error("❌ Stock insuficiente")
                    else:
                        delta = cant if tipo=="entrada" else -cant
                        with get_connection() as conn:
                            cur = conn.cursor()
                            cur.execute("UPDATE public.productos SET stock=stock+%s WHERE id=%s", (delta, pid))
                            cur.execute("""INSERT INTO public.movimientos_stock 
                                (producto_id, tipo, cantidad, costo_unitario, motivo)
                                VALUES (%s,%s,%s,%s,%s)""",
                                (pid, tipo, cant, p["costo_unitario"], mot))
                        st.success("✅ Ajuste realizado")
                        st.rerun()

    with tab4:
        if not productos:
            st.warning("No hay productos para borrar")
        else:
            st.info("ℹ️ Desaparece de las listas, manteniendo tu historial")
            ids = [p["id"] for p in productos]
            with st.form("borrar", clear_on_submit=True):
                pid = st.selectbox(
                    "Producto a borrar", options=ids,
                    format_func=lambda x: next(f"{p['codigo']} | {p['nombre']}" for p in productos if p["id"]==x)
                )
                conf = st.checkbox("✅ Estoy seguro/a")
                if st.form_submit_button("🗑️ BORRAR"):
                    if not conf:
                        st.error("❌ Confirmá primero")
                    else:
                        with get_connection() as conn:
                            conn.cursor().execute("UPDATE public.productos SET activo=0 WHERE id=%s", (pid,))
                        st.success("✅ Producto borrado")
                        st.rerun()

# ============================================================
# VENTAS
# ============================================================
def pagina_ventas():
    st.title("🛒 Ventas")
    productos = get_productos_activos()
    if not productos:
        st.warning("Primero crea productos"); return
    
    if "carrito" not in st.session_state:
        st.session_state.carrito = []
    
    ids = [p["id"] for p in productos]
    with st.form("add_item", clear_on_submit=True):
        pid = st.selectbox("Producto", options=ids,
            format_func=lambda x: next(f"{p['nombre']} | Stock: {p['stock']}" for p in productos if p["id"]==x))
        pr = next(p for p in productos if p["id"]==pid)
        cant = st.number_input("Cantidad", min_value=0.01, value=1.0)
        prec = st.number_input("Precio", value=float(pr["precio_venta"]), min_value=0.0)
        
        if st.form_submit_button("➕ Agregar"):
            if cant > pr["stock"]:
                st.error("Stock insuficiente")
            else:
                st.session_state.carrito.append({
                    "producto_id": pid, "nombre": pr["nombre"],
                    "cantidad": cant, "precio": prec,
                    "costo": float(pr["costo_unitario"]), "subtotal": cant*prec
                })
                st.rerun()
    
    if st.session_state.carrito:
        cdf = pd.DataFrame(st.session_state.carrito)
        st.dataframe(cdf[["nombre","cantidad","precio","subtotal"]], use_container_width=True, hide_index=True)
        total = cdf["subtotal"].sum()
        st.markdown(f"### Total: {formato_moneda(total)}")
        
        if st.button("🗑️ Vaciar"):
            st.session_state.carrito = []; st.rerun()
        
        with st.form("finalizar"):
            cli = st.text_input("Cliente")
            desc = st.number_input("Descuento", min_value=0.0, value=0.0)
            met = st.selectbox("Método", ["Efectivo","Tarjeta","Transferencia","Otro"])
            if st.form_submit_button("✅ Confirmar Venta"):
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""INSERT INTO public.ventas (cliente,total,descuento,metodo_pago)
                        VALUES (%s,%s,%s,%s) RETURNING id""", (cli,total,desc,met))
                    vid = int(cur.fetchone()['id'])
                    
                    for it in st.session_state.carrito:
                        iid = int(it["producto_id"])
                        cur.execute("""INSERT INTO public.venta_detalle
                            (venta_id,producto_id,cantidad,precio_unitario,costo_unitario,subtotal)
                            VALUES (%s,%s,%s,%s,%s,%s)""",
                            (vid,iid,it["cantidad"],it["precio"],it["costo"],it["subtotal"]))
                        cur.execute("UPDATE public.productos SET stock=stock-%s WHERE id=%s", (it["cantidad"],iid))
                        cur.execute("""INSERT INTO public.movimientos_stock
                            (producto_id,tipo,cantidad,costo_unitario,motivo,referencia)
                            VALUES (%s,'salida',%s,%s,'Venta',%s)""",
                            (iid,it["cantidad"],it["costo"],f"Venta #{vid}"))
                
                st.session_state.carrito = []
                st.success(f"✅ Venta #{vid} registrada")
                st.rerun()

# ============================================================
# COMPRAS
# ============================================================
def pagina_compras():
    st.title("📥 Compras")
    productos = get_productos_activos()
    if not productos:
        st.warning("Primero crea productos"); return
    
    if "carrito_compra" not in st.session_state:
        st.session_state.carrito_compra = []
    
    ids = [p["id"] for p in productos]
    with st.form("add_compra", clear_on_submit=True):
        pid = st.selectbox("Producto", options=ids,
            format_func=lambda x: next(p["nombre"] for p in productos if p["id"]==x))
        pr = next(p for p in productos if p["id"]==pid)
        cant = st.number_input("Cantidad", min_value=0.01, value=1.0)
        cost = st.number_input("Costo unitario", value=float(pr["costo_unitario"]), min_value=0.0, step=0.01)
        
        if st.form_submit_button("➕ Agregar"):
            st.session_state.carrito_compra.append({
                "producto_id": pid, "nombre": pr["nombre"],
                "cantidad": cant, "costo": cost, "subtotal": cant*cost
            })
            st.rerun()
    
    if st.session_state.carrito_compra:
        cdf = pd.DataFrame(st.session_state.carrito_compra)
        st.dataframe(cdf[["nombre","cantidad","costo","subtotal"]], use_container_width=True, hide_index=True)
        total = cdf["subtotal"].sum()
        st.markdown(f"**Total: {formato_moneda(total)}**")
        
        with st.form("confirmar_compra"):
            prov = st.text_input("Proveedor")
            met = st.selectbox("Método", ["Efectivo","Transferencia","Crédito"])
            if st.form_submit_button("✅ Registrar Compra"):
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO public.compras (proveedor,total,metodo_pago) VALUES (%s,%s,%s) RETURNING id",
                        (prov,total,met))
                    cid = int(cur.fetchone()['id'])
                    
                    for it in st.session_state.carrito_compra:
                        iid = int(it["producto_id"])
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
                
                st.session_state.carrito_compra = []
                st.success(f"✅ Compra #{cid} registrada")
                st.rerun()

# ============================================================
# GASTOS | REPORTES
# ============================================================
def pagina_gastos():
    st.title("💸 Gastos")
    with st.form("nuevo_gasto"):
        fecha = st.date_input("Fecha", value=datetime.now().date())
        cat = st.selectbox("Categoría", get_categorias_gastos())
        desc = st.text_input("Descripción")
        mon = st.number_input("Monto", min_value=0.01, value=0.0)
        met = st.selectbox("Método", ["Efectivo","Transferencia","Tarjeta"])
        if st.form_submit_button("💾 Guardar"):
            with get_connection() as conn:
                conn.cursor().execute("""
                    INSERT INTO public.gastos (fecha,categoria,descripcion,monto,metodo_pago)
                    VALUES (%s,%s,%s,%s,%s)""", (fecha,cat,desc,mon,met))
            st.success("✅ Gasto guardado"); st.rerun()

def pagina_reportes():
    st.title("📈 Reportes")
    c1, c2 = st.columns(2)
    with c1: fi = st.date_input("Desde", value=datetime.now().date()-timedelta(days=90), key="r1")
    with c2: ff = st.date_input("Hasta", value=datetime.now().date(), key="r2")
    fi, ff = fi.isoformat(), ff.isoformat()
    ing = calcular_ingresos(fi,ff)
    cg = calcular_cogs_periodo(fi,ff)
    gs = calcular_gastos(fi,ff)
    r1,r2 = st.columns(2)
    r1.metric("Ingresos", formato_moneda(ing))
    r2.metric("Utilidad Neta", formato_moneda(ing-cg-gs))

# ============================================================
# HISTORIAL + ✅ NUEVO: ANULAR VENTA / ANULAR COMPRA
# ============================================================
def pagina_historial():
    st.title("📜 Historial")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Ventas", "Compras", "Gastos", 
        "🗑️ Anular Venta", "🗑️ Anular Compra"
    ])
    
    with get_connection() as conn:
        # TAB 1: Ventas ACTIVAS
        with tab1:
            df = pd.read_sql_query("""
                SELECT id, fecha, cliente, total, metodo_pago 
                FROM public.ventas 
                WHERE anulada = 0 
                ORDER BY fecha DESC LIMIT 50
            """, conn)
            if df.empty:
                st.info("Sin ventas")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)
        
        # TAB 2: Compras ACTIVAS
        with tab2:
            df = pd.read_sql_query("""
                SELECT id, fecha, proveedor, total, metodo_pago 
                FROM public.compras 
                WHERE anulada = 0 
                ORDER BY fecha DESC LIMIT 50
            """, conn)
            if df.empty:
                st.info("Sin compras")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)
        
        # TAB 3: Gastos
        with tab3:
            df = pd.read_sql_query("""
                SELECT fecha, categoria, monto, metodo_pago 
                FROM public.gastos 
                ORDER BY fecha DESC LIMIT 50
            """, conn)
            if df.empty:
                st.info("Sin gastos")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)
    
    # ✅ TAB 4: ANULAR VENTA
    with tab4:
        st.info("⚠️ Anular una venta devuelve el stock a los productos y borra el monto de tus ingresos. No se puede deshacer.")
        with get_connection() as conn:
            ventas = pd.read_sql_query("""
                SELECT id, fecha, cliente, total, metodo_pago
                FROM public.ventas
                WHERE anulada = 0
                ORDER BY fecha DESC
            """, conn)
        
        if ventas.empty:
            st.warning("No hay ventas para anular")
        else:
            with st.form("anular_venta", clear_on_submit=True):
                vid = st.selectbox(
                    "Seleccioná la venta a anular",
                    options=ventas["id"].tolist(),
                    format_func=lambda x: (
                        f"#{x} | "
                        f"{ventas[ventas['id']==x]['fecha'].values[0]} | "
                        f"Cliente: {ventas[ventas['id']==x]['cliente'].values[0] or 'Sin nombre'} | "
                        f"Total: {formato_moneda(float(ventas[ventas['id']==x]['total'].values[0]))}"
                    )
                )
                vid = int(vid)
                conf1 = st.checkbox("✅ Estoy seguro/a que esta venta NO existió o se cargó mal")
                conf2 = st.checkbox("✅ Entiendo que el stock se devolverá automáticamente y no se puede deshacer")
                
                if st.form_submit_button("🗑️ ANULAR ESTA VENTA"):
                    if not conf1 or not conf2:
                        st.error("❌ Tenés que marcar LAS DOS casillas de confirmación")
                    else:
                        ok, msg = anular_venta(vid)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")
    
    # ✅ TAB 5: ANULAR COMPRA
    with tab5:
        st.info("⚠️ Anular una compra resta el stock de los productos y borra el monto de tus compras. No se puede deshacer.")
        with get_connection() as conn:
            compras = pd.read_sql_query("""
                SELECT id, fecha, proveedor, total, metodo_pago
                FROM public.compras
                WHERE anulada = 0
                ORDER BY fecha DESC
            """, conn)
        
        if compras.empty:
            st.warning("No hay compras para anular")
        else:
            with st.form("anular_compra", clear_on_submit=True):
                cid = st.selectbox(
                    "Seleccioná la compra a anular",
                    options=compras["id"].tolist(),
                    format_func=lambda x: (
                        f"#{x} | "
                        f"{compras[compras['id']==x]['fecha'].values[0]} | "
                        f"Proveedor: {compras[compras['id']==x]['proveedor'].values[0] or 'Sin nombre'} | "
                        f"Total: {formato_moneda(float(compras[compras['id']==x]['total'].values[0]))}"
                    )
                )
                cid = int(cid)
                conf1 = st.checkbox("✅ Estoy seguro/a que esta compra NO existió o se cargó mal")
                conf2 = st.checkbox("✅ Entiendo que se restará el stock y no se puede deshacer")
                
                if st.form_submit_button("🗑️ ANULAR ESTA COMPRA"):
                    if not conf1 or not conf2:
                        st.error("❌ Tenés que marcar LAS DOS casillas de confirmación")
                    else:
                        ok, msg = anular_compra(cid)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")

# ============================================================
# MAIN
# ============================================================
def main():
    st.sidebar.title("🏪 Negocio Pro")
    st.sidebar.caption("Versión definitiva + anular ventas/compras")
    p = st.sidebar.radio("Menú", [
        "📊 Dashboard","📦 Inventario","🛒 Ventas",
        "📥 Compras","💸 Gastos","📈 Reportes","📜 Historial"
    ])
    if p=="📊 Dashboard": pagina_dashboard()
    elif p=="📦 Inventario": pagina_inventario()
    elif p=="🛒 Ventas": pagina_ventas()
    elif p=="📥 Compras": pagina_compras()
    elif p=="💸 Gastos": pagina_gastos()
    elif p=="📈 Reportes": pagina_reportes()
    elif p=="📜 Historial": pagina_historial()

if __name__ == "__main__":
    main()
