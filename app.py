import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os

# ====================== CONFIG ======================
st.set_page_config(
    page_title="Negocio Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.stButton>button {
    width: 100%;
    height: 3rem;
    font-size: 1.1rem;
    border-radius: 10px;
}
.block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
h1 { font-size: 1.5rem !important; }
</style>
""", unsafe_allow_html=True)

# ====================== BASE DE DATOS ======================
def get_db_url():
    try:
        return st.secrets["DATABASE_URL"]
    except:
        return os.getenv("DATABASE_URL", "")

@contextmanager
def get_connection():
    conn = psycopg2.connect(get_db_url(), cursor_factory=RealDictCursor)
    try:
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                codigo TEXT UNIQUE,
                nombre TEXT NOT NULL,
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
            CREATE TABLE IF NOT EXISTS movimientos_stock (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER REFERENCES productos(id),
                tipo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                costo_unitario REAL,
                motivo TEXT,
                referencia TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cliente TEXT,
                total REAL NOT NULL,
                descuento REAL DEFAULT 0,
                metodo_pago TEXT,
                notas TEXT,
                anulada INTEGER DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS venta_detalle (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER REFERENCES ventas(id),
                producto_id INTEGER REFERENCES productos(id),
                cantidad REAL NOT NULL,
                precio_unitario REAL NOT NULL,
                costo_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS compras (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proveedor TEXT,
                total REAL NOT NULL,
                metodo_pago TEXT,
                notas TEXT,
                anulada INTEGER DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS compra_detalle (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER REFERENCES compras(id),
                producto_id INTEGER REFERENCES productos(id),
                cantidad REAL NOT NULL,
                costo_unitario REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                categoria TEXT NOT NULL,
                descripcion TEXT,
                monto REAL NOT NULL,
                metodo_pago TEXT,
                notas TEXT
            )
        """)

try:
    init_db()
except Exception as e:
    st.error(f"Error de base de datos: {e}")
    st.stop()

# ====================== HELPERS ======================
def fmt(v):
    try:
        return f"${float(v):,.2f}"
    except:
        return "$0.00"

def get_productos():
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, categoria, unidad FROM productos WHERE activo = 1 ORDER BY nombre",
            conn
        )

def kpi(fi, ff, sql):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(sql, (fi, ff))
        return float(c.fetchone()["v"] or 0)

# ====================== DASHBOARD ======================
def pagina_dashboard():
    st.title("📊 Dashboard")
    c1, c2 = st.columns(2)
    with c1:
        fi = st.date_input("Desde", value=datetime.now().date() - timedelta(days=30))
    with c2:
        ff = st.date_input("Hasta", value=datetime.now().date())
    
    fi, ff = str(fi), str(ff)
    
    ingresos = kpi(fi, ff, "SELECT COALESCE(SUM(total-descuento),0) as v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    cogs = kpi(fi, ff, """
        SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) as v 
        FROM venta_detalle vd JOIN ventas v ON vd.venta_id=v.id 
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0
    """)
    gastos = kpi(fi, ff, "SELECT COALESCE(SUM(monto),0) as v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    compras = kpi(fi, ff, "SELECT COALESCE(SUM(total),0) as v FROM compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(stock*costo_unitario),0) as v FROM productos WHERE activo=1")
        valor_inv = float(c.fetchone()["v"] or 0)
    
    ub = ingresos - cogs
    un = ub - gastos
    
    st.markdown("---")
    k1, k2 = st.columns(2)
    k1.metric("💰 Ingresos", fmt(ingresos))
    k2.metric("📦 COGS", fmt(cogs))
    k3, k4 = st.columns(2)
    k3.metric("📈 Utilidad Bruta", fmt(ub))
    k4.metric("💸 Gastos", fmt(gastos))
    st.metric("✅ Utilidad Neta", fmt(un))
    m1, m2 = st.columns(2)
    m1.metric("🛒 Compras", fmt(compras))
    m2.metric("📦 Valor Inventario", fmt(valor_inv))
    
    with get_connection() as conn:
        sb = pd.read_sql_query(
            "SELECT nombre, stock, stock_minimo FROM productos WHERE activo=1 AND stock <= stock_minimo AND stock_minimo > 0",
            conn
        )
    if not sb.empty:
        st.warning(f"⚠️ {len(sb)} producto(s) con stock bajo")
        with st.expander("Ver"):
            st.dataframe(sb, use_container_width=True, hide_index=True)

# ====================== INVENTARIO ======================
def pagina_inventario():
    st.title("📦 Inventario")
    t1, t2, t3, t4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Eliminar"])
    df = get_productos()
    
    # LISTA
    with t1:
        if df.empty:
            st.warning("No hay productos")
        else:
            st.dataframe(df[["codigo", "nombre", "stock", "costo_unitario", "precio_venta"]], use_container_width=True, hide_index=True)
    
    # NUEVO PRODUCTO (versión anti-bug)
    with t2:
        st.subheader("Crear producto")
        
        # Usamos un form limpio
        with st.form(key="crear_producto_form", clear_on_submit=True):
            codigo = st.text_input("Código *")
            nombre = st.text_input("Nombre *")
            categoria = st.text_input("Categoría")
            unidad = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"])
            stock_inicial = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=1.0)
            costo = st.number_input("Costo unitario *", min_value=0.0, value=0.0, step=0.01)
            precio = st.number_input("Precio de venta *", min_value=0.0, value=0.0, step=0.01)
            stock_min = st.number_input("Stock mínimo", min_value=0.0, value=5.0, step=1.0)
            
            submitted = st.form_submit_button("Crear producto")
        
        if submitted:
            # Limpiamos y validamos
            codigo = (codigo or "").strip()
            nombre = (nombre or "").strip()
            categoria = (categoria or "").strip()
            
            if codigo == "" or nombre == "":
                st.error("Código y Nombre son obligatorios")
            elif costo <= 0 or precio <= 0:
                st.error("Costo y Precio deben ser mayores a 0")
            else:
                try:
                    with get_connection() as conn:
                        c = conn.cursor()
                        
                        # Verificar si ya existe
                        c.execute("SELECT id FROM productos WHERE codigo = %s", (codigo,))
                        if c.fetchone():
                            st.error(f"Ya existe el código: {codigo}")
                        else:
                            c.execute("""
                                INSERT INTO productos 
                                (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (codigo, nombre, categoria, stock_inicial, stock_min, costo, precio, unidad))
                            
                            prod_id = c.fetchone()["id"]
                            
                            if stock_inicial > 0:
                                c.execute("""
                                    INSERT INTO movimientos_stock 
                                    (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (prod_id, stock_inicial, costo))
                    
                    st.success(f"Producto creado: {nombre}")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error al crear: {e}")
    
    # AJUSTE
    with t3:
        if df.empty:
            st.info("No hay productos")
        else:
            prod_id = st.selectbox(
                "Producto",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]} (stock: {df.loc[df['id']==x, 'stock'].values[0]})"
            )
            tipo = st.radio("Tipo", ["entrada", "salida"], horizontal=True)
            cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
            motivo = st.selectbox("Motivo", ["Inventario físico", "Pérdida / Merma", "Otro"])
            
            if st.button("Aplicar ajuste"):
                try:
                    with get_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT stock, costo_unitario FROM productos WHERE id = %s", (int(prod_id),))
                        p = c.fetchone()
                        
                        if tipo == "salida" and cantidad > p["stock"]:
                            st.error("Stock insuficiente")
                        else:
                            delta = cantidad if tipo == "entrada" else -cantidad
                            c.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (delta, int(prod_id)))
                            c.execute("""
                                INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (int(prod_id), tipo, cantidad, p["costo_unitario"], motivo))
                    st.success("Ajuste realizado")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    
    # ELIMINAR
    with t4:
        if df.empty:
            st.warning("No hay productos")
        else:
            prod_id = st.selectbox(
                "Producto a eliminar",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df.loc[df['id']==x, 'codigo'].values[0]} - {df.loc[df['id']==x, 'nombre'].values[0]}"
            )
            if st.checkbox("Confirmo eliminar"):
                if st.button("Eliminar", type="primary"):
                    with get_connection() as conn:
                        c = conn.cursor()
                        c.execute("UPDATE productos SET activo = 0 WHERE id = %s", (int(prod_id),))
                    st.success("Producto eliminado")
                    st.rerun()

# ====================== VENTAS ======================
def pagina_ventas():
    st.title("🛒 Ventas")
    df = get_productos()
    if df.empty:
        st.warning("Primero crea productos")
        return
    
    if "carrito" not in st.session_state:
        st.session_state.carrito = []
    
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]} | Stock: {df.loc[df['id']==x, 'stock'].values[0]}"
    )
    p = df[df["id"] == prod_id].iloc[0]
    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
    precio = st.number_input("Precio", value=float(p["precio_venta"]), min_value=0.0, step=0.01)
    
    if st.button("Agregar al carrito"):
        if cantidad > p["stock"]:
            st.error("Stock insuficiente")
        else:
            st.session_state.carrito.append({
                "producto_id": int(prod_id),
                "nombre": p["nombre"],
                "cantidad": float(cantidad),
                "precio": float(precio),
                "costo": float(p["costo_unitario"]),
                "subtotal": float(cantidad) * float(precio)
            })
            st.rerun()
    
    if st.session_state.carrito:
        cart = pd.DataFrame(st.session_state.carrito)
        st.dataframe(cart[["nombre", "cantidad", "precio", "subtotal"]], use_container_width=True, hide_index=True)
        total = cart["subtotal"].sum()
        st.markdown(f"### Total: {fmt(total)}")
        
        if st.button("Vaciar carrito"):
            st.session_state.carrito = []
            st.rerun()
        
        cliente = st.text_input("Cliente")
        descuento = st.number_input("Descuento", min_value=0.0, value=0.0, step=1.0)
        metodo = st.selectbox("Método", ["Efectivo", "Tarjeta", "Transferencia", "Otro"])
        
        if st.button("Confirmar Venta", type="primary"):
            try:
                with get_connection() as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO ventas (cliente, total, descuento, metodo_pago)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    """, (cliente, total, descuento, metodo))
                    venta_id = c.fetchone()["id"]
                    
                    for item in st.session_state.carrito:
                        c.execute("""
                            INSERT INTO venta_detalle 
                            (venta_id, producto_id, cantidad, precio_unitario, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (venta_id, item["producto_id"], item["cantidad"], item["precio"], item["costo"], item["subtotal"]))
                        c.execute("UPDATE productos SET stock = stock - %s WHERE id = %s", (item["cantidad"], item["producto_id"]))
                        c.execute("""
                            INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'salida', %s, %s, 'Venta', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Venta #{venta_id}"))
                
                st.session_state.carrito = []
                st.success(f"Venta #{venta_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ====================== COMPRAS ======================
def pagina_compras():
    st.title("📥 Compras")
    df = get_productos()
    if df.empty:
        st.warning("Primero crea productos")
        return
    
    if "carrito_c" not in st.session_state:
        st.session_state.carrito_c = []
    
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]}"
    )
    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0, key="cc_cant")
    costo = st.number_input("Costo unitario", min_value=0.0, value=0.0, step=0.01, key="cc_costo")
    
    if st.button("Agregar"):
        nombre = df.loc[df["id"]==prod_id, "nombre"].values[0]
        st.session_state.carrito_c.append({
            "producto_id": int(prod_id),
            "nombre": nombre,
            "cantidad": float(cantidad),
            "costo": float(costo),
            "subtotal": float(cantidad) * float(costo)
        })
        st.rerun()
    
    if st.session_state.carrito_c:
        cdf = pd.DataFrame(st.session_state.carrito_c)
        st.dataframe(cdf[["nombre", "cantidad", "costo", "subtotal"]], use_container_width=True, hide_index=True)
        total = cdf["subtotal"].sum()
        st.markdown(f"**Total: {fmt(total)}**")
        
        if st.button("Vaciar"):
            st.session_state.carrito_c = []
            st.rerun()
        
        proveedor = st.text_input("Proveedor")
        metodo = st.selectbox("Método", ["Efectivo", "Transferencia", "Crédito"])
        
        if st.button("Registrar Compra", type="primary"):
            try:
                with get_connection() as conn:
                    c = conn.cursor()
                    c.execute("INSERT INTO compras (proveedor, total, metodo_pago) VALUES (%s, %s, %s) RETURNING id",
                              (proveedor, total, metodo))
                    compra_id = c.fetchone()["id"]
                    
                    for item in st.session_state.carrito_c:
                        c.execute("""
                            INSERT INTO compra_detalle (compra_id, producto_id, cantidad, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (compra_id, item["producto_id"], item["cantidad"], item["costo"], item["subtotal"]))
                        c.execute("UPDATE productos SET stock = stock + %s, costo_unitario = %s WHERE id = %s",
                                  (item["cantidad"], item["costo"], item["producto_id"]))
                        c.execute("""
                            INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'entrada', %s, %s, 'Compra', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Compra #{compra_id}"))
                
                st.session_state.carrito_c = []
                st.success(f"Compra #{compra_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ====================== GASTOS ======================
def pagina_gastos():
    st.title("💸 Gastos")
    fecha = st.date_input("Fecha", value=datetime.now().date())
    categoria = st.selectbox("Categoría", [
        "Alquiler", "Servicios", "Sueldos", "Marketing", "Transporte",
        "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"
    ])
    descripcion = st.text_input("Descripción")
    monto = st.number_input("Monto", min_value=0.01, value=0.0, step=1.0)
    metodo = st.selectbox("Método", ["Efectivo", "Transferencia", "Tarjeta"])
    
    if st.button("Guardar gasto"):
        try:
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO gastos (fecha, categoria, descripcion, monto, metodo_pago)
                    VALUES (%s, %s, %s, %s, %s)
                """, (fecha, categoria, descripcion, monto, metodo))
            st.success("Gasto guardado")
            st.rerun()
        except Exception as e:
            st.error(str(e))

# ====================== REPORTES ======================
def pagina_reportes():
    st.title("📈 Reportes")
    c1, c2 = st.columns(2)
    with c1:
        fi = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="rfi")
    with c2:
        ff = st.date_input("Hasta", value=datetime.now().date(), key="rff")
    
    fi, ff = str(fi), str(ff)
    ingresos = kpi(fi, ff, "SELECT COALESCE(SUM(total-descuento),0) as v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada=0")
    cogs = kpi(fi, ff, """
        SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) as v 
        FROM venta_detalle vd JOIN ventas v ON vd.venta_id=v.id 
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada=0
    """)
    gastos = kpi(fi, ff, "SELECT COALESCE(SUM(monto),0) as v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    
    r1, r2 = st.columns(2)
    r1.metric("Ingresos", fmt(ingresos))
    r2.metric("Utilidad Neta", fmt(ingresos - cogs - gastos))

# ====================== HISTORIAL ======================
def pagina_historial():
    st.title("📜 Historial")
    t1, t2, t3, t4, t5 = st.tabs(["Ventas", "Compras", "Gastos", "Anular Venta", "Anular Compra"])
    
    with get_connection() as conn:
        with t1:
            df = pd.read_sql_query("SELECT id, fecha, cliente, total, metodo_pago FROM ventas WHERE anulada=0 ORDER BY fecha DESC LIMIT 40", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin ventas")
        with t2:
            df = pd.read_sql_query("SELECT id, fecha, proveedor, total FROM compras WHERE anulada=0 ORDER BY fecha DESC LIMIT 40", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin compras")
        with t3:
            df = pd.read_sql_query("SELECT fecha, categoria, monto FROM gastos ORDER BY fecha DESC LIMIT 40", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin gastos")
    
    with t4:
        st.info("Anular venta devuelve el stock")
        with get_connection() as conn:
            ventas = pd.read_sql_query("SELECT id, fecha, total FROM ventas WHERE anulada=0 ORDER BY fecha DESC LIMIT 20", conn)
        if ventas.empty:
            st.warning("No hay ventas")
        else:
            vid = st.selectbox("Venta", options=ventas["id"].tolist(),
                               format_func=lambda x: f"#{x} - {fmt(ventas.loc[ventas['id']==x, 'total'].values[0])}")
            if st.checkbox("Confirmar anulación de venta"):
                if st.button("Anular Venta", type="primary"):
                    try:
                        with get_connection() as conn:
                            c = conn.cursor()
                            c.execute("SELECT producto_id, cantidad, costo_unitario FROM venta_detalle WHERE venta_id=%s", (int(vid),))
                            dets = c.fetchall()
                            c.execute("UPDATE ventas SET anulada=1 WHERE id=%s", (int(vid),))
                            for d in dets:
                                c.execute("UPDATE productos SET stock = stock + %s WHERE id=%s", (d["cantidad"], d["producto_id"]))
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Anulación venta', %s)
                                """, (d["producto_id"], d["cantidad"], d["costo_unitario"], f"Anul Venta #{vid}"))
                        st.success("Venta anulada")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
    
    with t5:
        st.info("Anular compra resta el stock")
        with get_connection() as conn:
            compras = pd.read_sql_query("SELECT id, fecha, total FROM compras WHERE anulada=0 ORDER BY fecha DESC LIMIT 20", conn)
        if compras.empty:
            st.warning("No hay compras")
        else:
            cid = st.selectbox("Compra", options=compras["id"].tolist(),
                               format_func=lambda x: f"#{x} - {fmt(compras.loc[compras['id']==x, 'total'].values[0])}")
            if st.checkbox("Confirmar anulación de compra"):
                if st.button("Anular Compra", type="primary"):
                    try:
                        with get_connection() as conn:
                            c = conn.cursor()
                            c.execute("SELECT producto_id, cantidad, costo_unitario FROM compra_detalle WHERE compra_id=%s", (int(cid),))
                            dets = c.fetchall()
                            for d in dets:
                                c.execute("SELECT stock FROM productos WHERE id=%s", (d["producto_id"],))
                                if c.fetchone()["stock"] < d["cantidad"]:
                                    st.error("Stock insuficiente para anular")
                                    return
                            c.execute("UPDATE compras SET anulada=1 WHERE id=%s", (int(cid),))
                            for d in dets:
                                c.execute("UPDATE productos SET stock = stock - %s WHERE id=%s", (d["cantidad"], d["producto_id"]))
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'salida', %s, %s, 'Anulación compra', %s)
                                """, (d["producto_id"], d["cantidad"], d["costo_unitario"], f"Anul Compra #{cid}"))
                        st.success("Compra anulada")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

# ====================== MAIN ======================
def main():
    st.sidebar.title("🏪 Negocio Pro")
    op = st.sidebar.radio("Menú", [
        "📊 Dashboard",
        "📦 Inventario",
        "🛒 Ventas",
        "📥 Compras",
        "💸 Gastos",
        "📈 Reportes",
        "📜 Historial"
    ])
    
    if op == "📊 Dashboard":
        pagina_dashboard()
    elif op == "📦 Inventario":
        pagina_inventario()
    elif op == "🛒 Ventas":
        pagina_ventas()
    elif op == "📥 Compras":
        pagina_compras()
    elif op == "💸 Gastos":
        pagina_gastos()
    elif op == "📈 Reportes":
        pagina_reportes()
    elif op == "📜 Historial":
        pagina_historial()

if __name__ == "__main__":
    main()
