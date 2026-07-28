import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
import uuid

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
# CONEXIÓN A SUPABASE
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
    st.error(f"Error conectando a la base de datos: {e}")
    st.stop()

# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def fmt(v):
    try:
        return f"${float(v):,.2f}"
    except:
        return "$0.00"

def get_productos():
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, categoria, unidad FROM productos WHERE activo = 1 ORDER BY nombre",
            conn
        )
    return df

def calcular_kpi(fi, ff, query):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(query, (fi, ff))
        row = c.fetchone()
        return float(row["v"] or 0)

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
    
    fi, ff = str(fecha_inicio), str(fecha_fin)
    
    ingresos = calcular_kpi(fi, ff, "SELECT COALESCE(SUM(total - descuento),0) as v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0")
    cogs = calcular_kpi(fi, ff, """
        SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario),0) as v 
        FROM venta_detalle vd 
        JOIN ventas v ON vd.venta_id = v.id 
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """)
    gastos = calcular_kpi(fi, ff, "SELECT COALESCE(SUM(monto),0) as v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    compras = calcular_kpi(fi, ff, "SELECT COALESCE(SUM(total),0) as v FROM compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0")
    
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(stock * costo_unitario),0) as v FROM productos WHERE activo = 1")
        valor_inv = float(c.fetchone()["v"] or 0)
    
    utilidad_bruta = ingresos - cogs
    utilidad_neta = utilidad_bruta - gastos
    margen_b = (utilidad_bruta / ingresos * 100) if ingresos > 0 else 0
    margen_n = (utilidad_neta / ingresos * 100) if ingresos > 0 else 0
    
    st.markdown("---")
    st.subheader("Indicadores clave")
    
    k1, k2 = st.columns(2)
    k1.metric("💰 Ingresos", fmt(ingresos))
    k2.metric("📦 COGS", fmt(cogs))
    
    k3, k4 = st.columns(2)
    k3.metric("📈 Utilidad Bruta", fmt(utilidad_bruta), delta=f"{margen_b:.1f}%")
    k4.metric("💸 Gastos", fmt(gastos))
    
    st.metric("✅ Utilidad Neta", fmt(utilidad_neta), delta=f"{margen_n:.1f}%")
    
    m1, m2 = st.columns(2)
    m1.metric("🛒 Compras", fmt(compras))
    m2.metric("📦 Valor Inventario", fmt(valor_inv))
    
    # Stock bajo
    with get_connection() as conn:
        stock_bajo = pd.read_sql_query(
            "SELECT nombre, stock, stock_minimo, unidad FROM productos WHERE activo=1 AND stock <= stock_minimo AND stock_minimo > 0",
            conn
        )
    
    if not stock_bajo.empty:
        st.warning(f"⚠️ {len(stock_bajo)} producto(s) con stock bajo")
        with st.expander("Ver productos con stock bajo"):
            st.dataframe(stock_bajo, use_container_width=True, hide_index=True)

# ============================================================
# INVENTARIO
# ============================================================
def pagina_inventario():
    st.title("📦 Inventario")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Eliminar"])
    
    df = get_productos()
    
    # ----- LISTA -----
    with tab1:
        if df.empty:
            st.warning("No hay productos. Crea uno en la pestaña Nuevo.")
        else:
            st.dataframe(
                df[["codigo", "nombre", "stock", "costo_unitario", "precio_venta"]],
                use_container_width=True,
                hide_index=True
            )
    
    # ----- NUEVO PRODUCTO (sin form para evitar problemas en móvil) -----
    with tab2:
        st.subheader("Crear nuevo producto")
        
        codigo = st.text_input("Código / SKU *", key="np_codigo")
        nombre = st.text_input("Nombre del producto *", key="np_nombre")
        categoria = st.text_input("Categoría", key="np_categoria")
        unidad = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"], key="np_unidad")
        stock_inicial = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=1.0, key="np_stock")
        costo = st.number_input("Costo unitario *", min_value=0.0, value=0.0, step=0.01, key="np_costo")
        precio = st.number_input("Precio de venta *", min_value=0.0, value=0.0, step=0.01, key="np_precio")
        stock_min = st.number_input("Stock mínimo", min_value=0.0, value=5.0, step=1.0, key="np_min")
        
        if st.button("➕ Crear producto", key="btn_crear"):
            if not codigo.strip() or not nombre.strip():
                st.error("Código y Nombre son obligatorios")
            elif costo <= 0 or precio <= 0:
                st.error("Costo y Precio deben ser mayores a 0")
            else:
                try:
                    with get_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT 1 FROM productos WHERE codigo = %s", (codigo.strip(),))
                        if c.fetchone():
                            st.error(f"Ya existe un producto con el código '{codigo}'")
                        else:
                            c.execute("""
                                INSERT INTO productos (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                            """, (codigo.strip(), nombre.strip(), categoria.strip(), stock_inicial, stock_min, costo, precio, unidad))
                            prod_id = c.fetchone()["id"]
                            
                            if stock_inicial > 0:
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (prod_id, stock_inicial, costo))
                            
                            st.success(f"✅ Producto '{nombre}' creado correctamente")
                            st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    
    # ----- AJUSTE DE STOCK -----
    with tab3:
        if df.empty:
            st.info("Primero crea productos")
        else:
            prod_id = st.selectbox(
                "Producto",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df[df['id']==x]['nombre'].values[0]} (stock: {df[df['id']==x]['stock'].values[0]})"
            )
            tipo = st.radio("Tipo de ajuste", ["entrada", "salida"], horizontal=True)
            cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
            motivo = st.selectbox("Motivo", ["Inventario físico", "Pérdida / Merma", "Donación", "Otro"])
            
            if st.button("Aplicar ajuste"):
                with get_connection() as conn:
                    c = conn.cursor()
                    c.execute("SELECT stock, costo_unitario FROM productos WHERE id = %s", (prod_id,))
                    p = c.fetchone()
                    
                    if tipo == "salida" and cantidad > p["stock"]:
                        st.error(f"Stock insuficiente. Disponible: {p['stock']}")
                    else:
                        delta = cantidad if tipo == "entrada" else -cantidad
                        c.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (delta, prod_id))
                        c.execute("""
                            INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (prod_id, tipo, cantidad, p["costo_unitario"], motivo))
                        st.success("Ajuste aplicado")
                        st.rerun()
    
    # ----- ELIMINAR PRODUCTO -----
    with tab4:
        if df.empty:
            st.warning("No hay productos")
        else:
            st.info("Se desactiva el producto (no se borra el historial)")
            prod_id = st.selectbox(
                "Selecciona producto a eliminar",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df[df['id']==x]['codigo'].values[0]} - {df[df['id']==x]['nombre'].values[0]}"
            )
            confirmar = st.checkbox("Estoy seguro de eliminar este producto")
            
            if st.button("🗑️ Eliminar producto", type="primary"):
                if not confirmar:
                    st.error("Debes confirmar la eliminación")
                else:
                    with get_connection() as conn:
                        c = conn.cursor()
                        c.execute("UPDATE productos SET activo = 0 WHERE id = %s", (prod_id,))
                    st.success("Producto eliminado")
                    st.rerun()

# ============================================================
# VENTAS
# ============================================================
def pagina_ventas():
    st.title("🛒 Ventas")
    
    df = get_productos()
    if df.empty:
        st.warning("Primero crea productos en Inventario")
        return
    
    if "carrito" not in st.session_state:
        st.session_state.carrito = []
    
    # Agregar al carrito
    st.subheader("Agregar producto")
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df[df['id']==x]['nombre'].values[0]} | Stock: {df[df['id']==x]['stock'].values[0]} | ${df[df['id']==x]['precio_venta'].values[0]:.2f}"
    )
    p = df[df["id"] == prod_id].iloc[0]
    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
    precio = st.number_input("Precio unitario", value=float(p["precio_venta"]), min_value=0.0, step=0.01)
    
    if st.button("➕ Agregar al carrito"):
        if cantidad > p["stock"]:
            st.error("Stock insuficiente")
        else:
            st.session_state.carrito.append({
                "producto_id": int(prod_id),
                "nombre": p["nombre"],
                "cantidad": cantidad,
                "precio": precio,
                "costo": float(p["costo_unitario"]),
                "subtotal": cantidad * precio
            })
            st.success("Agregado al carrito")
            st.rerun()
    
    # Carrito
    if st.session_state.carrito:
        st.subheader("Carrito")
        cart_df = pd.DataFrame(st.session_state.carrito)
        st.dataframe(cart_df[["nombre", "cantidad", "precio", "subtotal"]], use_container_width=True, hide_index=True)
        
        total = cart_df["subtotal"].sum()
        st.markdown(f"### Total: {fmt(total)}")
        
        if st.button("🗑️ Vaciar carrito"):
            st.session_state.carrito = []
            st.rerun()
        
        st.markdown("---")
        cliente = st.text_input("Cliente (opcional)")
        descuento = st.number_input("Descuento ($)", min_value=0.0, value=0.0, step=1.0)
        metodo = st.selectbox("Método de pago", ["Efectivo", "Tarjeta", "Transferencia", "Otro"])
        
        if st.button("✅ Confirmar Venta", type="primary"):
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
                            INSERT INTO venta_detalle (venta_id, producto_id, cantidad, precio_unitario, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (venta_id, item["producto_id"], item["cantidad"], item["precio"], item["costo"], item["subtotal"]))
                        
                        c.execute("UPDATE productos SET stock = stock - %s WHERE id = %s", (item["cantidad"], item["producto_id"]))
                        
                        c.execute("""
                            INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'salida', %s, %s, 'Venta', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Venta #{venta_id}"))
                
                st.session_state.carrito = []
                st.success(f"✅ Venta #{venta_id} registrada — {fmt(total - descuento)}")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

# ============================================================
# COMPRAS
# ============================================================
def pagina_compras():
    st.title("📥 Compras")
    
    df = get_productos()
    if df.empty:
        st.warning("Primero crea productos")
        return
    
    if "carrito_compra" not in st.session_state:
        st.session_state.carrito_compra = []
    
    st.subheader("Agregar ítems")
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df[df['id']==x]['nombre'].values[0]} | Costo actual: ${df[df['id']==x]['costo_unitario'].values[0]:.2f}"
    )
    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0, key="c_cant")
    costo = st.number_input("Costo unitario de esta compra", min_value=0.0, value=float(df[df["id"]==prod_id]["costo_unitario"].values[0]), step=0.01, key="c_costo")
    
    if st.button("➕ Agregar"):
        nombre = df[df["id"]==prod_id]["nombre"].values[0]
        st.session_state.carrito_compra.append({
            "producto_id": int(prod_id),
            "nombre": nombre,
            "cantidad": cantidad,
            "costo": costo,
            "subtotal": cantidad * costo
        })
        st.success("Agregado")
        st.rerun()
    
    if st.session_state.carrito_compra:
        cdf = pd.DataFrame(st.session_state.carrito_compra)
        st.dataframe(cdf[["nombre", "cantidad", "costo", "subtotal"]], use_container_width=True, hide_index=True)
        total = cdf["subtotal"].sum()
        st.markdown(f"**Total compra: {fmt(total)}**")
        
        if st.button("🗑️ Vaciar"):
            st.session_state.carrito_compra = []
            st.rerun()
        
        proveedor = st.text_input("Proveedor")
        metodo = st.selectbox("Método de pago", ["Efectivo", "Transferencia", "Crédito"])
        
        if st.button("✅ Registrar Compra", type="primary"):
            try:
                with get_connection() as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO compras (proveedor, total, metodo_pago)
                        VALUES (%s, %s, %s) RETURNING id
                    """, (proveedor, total, metodo))
                    compra_id = c.fetchone()["id"]
                    
                    for item in st.session_state.carrito_compra:
                        c.execute("""
                            INSERT INTO compra_detalle (compra_id, producto_id, cantidad, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (compra_id, item["producto_id"], item["cantidad"], item["costo"], item["subtotal"]))
                        
                        c.execute("""
                            UPDATE productos SET stock = stock + %s, costo_unitario = %s WHERE id = %s
                        """, (item["cantidad"], item["costo"], item["producto_id"]))
                        
                        c.execute("""
                            INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'entrada', %s, %s, 'Compra', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Compra #{compra_id}"))
                
                st.session_state.carrito_compra = []
                st.success(f"✅ Compra #{compra_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

# ============================================================
# GASTOS
# ============================================================
def pagina_gastos():
    st.title("💸 Gastos")
    
    fecha = st.date_input("Fecha", value=datetime.now().date())
    categoria = st.selectbox("Categoría", [
        "Alquiler", "Servicios (luz/agua/gas)", "Sueldos", "Marketing",
        "Transporte", "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"
    ])
    descripcion = st.text_input("Descripción")
    monto = st.number_input("Monto *", min_value=0.01, value=0.0, step=1.0)
    metodo = st.selectbox("Método de pago", ["Efectivo", "Transferencia", "Tarjeta"])
    
    if st.button("💾 Guardar gasto"):
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO gastos (fecha, categoria, descripcion, monto, metodo_pago)
                VALUES (%s, %s, %s, %s, %s)
            """, (fecha, categoria, descripcion, monto, metodo))
        st.success("Gasto registrado")
        st.rerun()

# ============================================================
# REPORTES
# ============================================================
def pagina_reportes():
    st.title("📈 Reportes")
    
    c1, c2 = st.columns(2)
    with c1:
        fecha_inicio = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="rep_fi")
    with c2:
        fecha_fin = st.date_input("Hasta", value=datetime.now().date(), key="rep_ff")
    
    fi, ff = str(fecha_inicio), str(fecha_fin)
    
    ingresos = calcular_kpi(fi, ff, "SELECT COALESCE(SUM(total - descuento),0) as v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0")
    cogs = calcular_kpi(fi, ff, """
        SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario),0) as v 
        FROM venta_detalle vd JOIN ventas v ON vd.venta_id = v.id 
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """)
    gastos = calcular_kpi(fi, ff, "SELECT COALESCE(SUM(monto),0) as v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s")
    
    r1, r2 = st.columns(2)
    r1.metric("Ingresos", fmt(ingresos))
    r2.metric("Utilidad Neta", fmt(ingresos - cogs - gastos))

# ============================================================
# HISTORIAL + ANULAR
# ============================================================
def pagina_historial():
    st.title("📜 Historial")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Ventas", "Compras", "Gastos", "🗑️ Anular Venta", "🗑️ Anular Compra"])
    
    with get_connection() as conn:
        with tab1:
            df = pd.read_sql_query(
                "SELECT id, fecha, cliente, total, descuento, metodo_pago FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 50",
                conn
            )
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("Sin ventas")
        
        with tab2:
            df = pd.read_sql_query(
                "SELECT id, fecha, proveedor, total, metodo_pago FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 50",
                conn
            )
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("Sin compras")
        
        with tab3:
            df = pd.read_sql_query(
                "SELECT fecha, categoria, descripcion, monto FROM gastos ORDER BY fecha DESC LIMIT 50",
                conn
            )
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("Sin gastos")
    
    # Anular Venta
    with tab4:
        st.info("Al anular una venta se devuelve el stock automáticamente.")
        with get_connection() as conn:
            ventas = pd.read_sql_query(
                "SELECT id, fecha, cliente, total FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 30",
                conn
            )
        
        if ventas.empty:
            st.warning("No hay ventas para anular")
        else:
            venta_id = st.selectbox(
                "Selecciona la venta",
                options=ventas["id"].tolist(),
                format_func=lambda x: f"#{x} | {ventas[ventas['id']==x]['fecha'].values[0]} | {fmt(ventas[ventas['id']==x]['total'].values[0])}"
            )
            confirmar = st.checkbox("Confirmo que quiero anular esta venta")
            
            if st.button("🗑️ Anular Venta", type="primary"):
                if not confirmar:
                    st.error("Debes confirmar")
                else:
                    try:
                        with get_connection() as conn:
                            c = conn.cursor()
                            # Obtener detalle
                            c.execute("SELECT producto_id, cantidad, costo_unitario FROM venta_detalle WHERE venta_id = %s", (venta_id,))
                            detalles = c.fetchall()
                            
                            # Marcar como anulada
                            c.execute("UPDATE ventas SET anulada = 1 WHERE id = %s", (venta_id,))
                            
                            # Devolver stock
                            for d in detalles:
                                c.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (d["cantidad"], d["producto_id"]))
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Anulación de venta', %s)
                                """, (d["producto_id"], d["cantidad"], d["costo_unitario"], f"Anulación Venta #{venta_id}"))
                        
                        st.success(f"Venta #{venta_id} anulada y stock devuelto")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    # Anular Compra
    with tab5:
        st.info("Al anular una compra se resta el stock automáticamente.")
        with get_connection() as conn:
            compras = pd.read_sql_query(
                "SELECT id, fecha, proveedor, total FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 30",
                conn
            )
        
        if compras.empty:
            st.warning("No hay compras para anular")
        else:
            compra_id = st.selectbox(
                "Selecciona la compra",
                options=compras["id"].tolist(),
                format_func=lambda x: f"#{x} | {compras[compras['id']==x]['fecha'].values[0]} | {fmt(compras[compras['id']==x]['total'].values[0])}"
            )
            confirmar = st.checkbox("Confirmo que quiero anular esta compra")
            
            if st.button("🗑️ Anular Compra", type="primary"):
                if not confirmar:
                    st.error("Debes confirmar")
                else:
                    try:
                        with get_connection() as conn:
                            c = conn.cursor()
                            c.execute("SELECT producto_id, cantidad, costo_unitario FROM compra_detalle WHERE compra_id = %s", (compra_id,))
                            detalles = c.fetchall()
                            
                            # Verificar stock suficiente
                            for d in detalles:
                                c.execute("SELECT stock FROM productos WHERE id = %s", (d["producto_id"],))
                                stock_actual = c.fetchone()["stock"]
                                if stock_actual < d["cantidad"]:
                                    st.error(f"No se puede anular: stock insuficiente del producto ID {d['producto_id']}")
                                    return
                            
                            c.execute("UPDATE compras SET anulada = 1 WHERE id = %s", (compra_id,))
                            
                            for d in detalles:
                                c.execute("UPDATE productos SET stock = stock - %s WHERE id = %s", (d["cantidad"], d["producto_id"]))
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'salida', %s, %s, 'Anulación de compra', %s)
                                """, (d["producto_id"], d["cantidad"], d["costo_unitario"], f"Anulación Compra #{compra_id}"))
                        
                        st.success(f"Compra #{compra_id} anulada y stock actualizado")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

# ============================================================
# MAIN
# ============================================================
def main():
    st.sidebar.title("🏪 Negocio Pro")
    st.sidebar.caption("Versión estable")
    
    pagina = st.sidebar.radio("Menú", [
        "📊 Dashboard",
        "📦 Inventario",
        "🛒 Ventas",
        "📥 Compras",
        "💸 Gastos",
        "📈 Reportes",
        "📜 Historial"
    ])
    
    if pagina == "📊 Dashboard":
        pagina_dashboard()
    elif pagina == "📦 Inventario":
        pagina_inventario()
    elif pagina == "🛒 Ventas":
        pagina_ventas()
    elif pagina == "📥 Compras":
        pagina_compras()
    elif pagina == "💸 Gastos":
        pagina_gastos()
    elif pagina == "📈 Reportes":
        pagina_reportes()
    elif pagina == "📜 Historial":
        pagina_historial()

if __name__ == "__main__":
    main()
