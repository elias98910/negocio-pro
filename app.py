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
# CONFIGURACIÓN (SIN CAMBIOS)
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
# CONEXIÓN A SUPABASE (SIN CAMBIOS)
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
            CREATE TABLE IF NOT EXISTS movimientos_stock (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER NOT NULL REFERENCES productos(id),
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
                notas TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS venta_detalle (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER NOT NULL REFERENCES ventas(id),
                producto_id INTEGER NOT NULL REFERENCES productos(id),
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
                notas TEXT
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS compra_detalle (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER NOT NULL REFERENCES compras(id),
                producto_id INTEGER NOT NULL REFERENCES productos(id),
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
# FUNCIONES DE NEGOCIO (SIN CAMBIOS)
# ============================================================
def calcular_cogs_periodo(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario), 0) as cogs
            FROM venta_detalle vd
            JOIN ventas v ON vd.venta_id = v.id
            WHERE DATE(v.fecha) BETWEEN %s AND %s
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["cogs"])

def calcular_ingresos(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(total - descuento), 0) as ingresos
            FROM ventas
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["ingresos"])

def calcular_gastos(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(monto), 0) as total
            FROM gastos
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["total"])

def calcular_compras(fecha_inicio, fecha_fin):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(total), 0) as total
            FROM compras
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (fecha_inicio, fecha_fin))
        return float(c.fetchone()["total"])

def valor_inventario():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(stock * costo_unitario), 0) as valor FROM productos WHERE activo = 1")
        return float(c.fetchone()["valor"])

def margen_bruto(ingresos, cogs):
    return ((ingresos - cogs) / ingresos * 100) if ingresos else 0.0

def margen_neto(ingresos, cogs, gastos):
    return ((ingresos - cogs - gastos) / ingresos * 100) if ingresos else 0.0

def formato_moneda(valor):
    return f"${valor:,.2f}"

# ✅ ARREGLO 1: Caché corto para no mostrar productos viejos
@st.cache_data(ttl=5)
def get_productos_activos():
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, categoria, unidad FROM productos WHERE activo = 1 ORDER BY nombre",
            conn
        )

def get_categorias_gastos():
    return ["Alquiler", "Servicios (luz/agua/gas)", "Sueldos", "Marketing", "Transporte", 
            "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"]

# ============================================================
# PÁGINAS
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
        stock_bajo = pd.read_sql_query(
            "SELECT nombre, stock, stock_minimo, unidad FROM productos WHERE activo=1 AND stock <= stock_minimo AND stock_minimo > 0",
            conn
        )
    
    if not stock_bajo.empty:
        st.warning(f"⚠️ {len(stock_bajo)} producto(s) con stock bajo")
        with st.expander("Ver productos"):
            st.dataframe(stock_bajo, use_container_width=True, hide_index=True)

# ✅ ARREGLO 2 + NUEVO: INVENTARIO CON BORRAR (4TA PESTAÑA)
def pagina_inventario():
    st.title("📦 Inventario")
    # ➕ AGREGUÉ LA PESTAÑA NUEVA: 🗑️ Borrar
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Lista", "➕ Nuevo", "🔄 Ajuste", "🗑️ Borrar"])
    
    with tab1:
        df = get_productos_activos()
        if df.empty:
            st.warning("No hay productos. Crea uno en la pestaña Nuevo.")
        else:
            st.dataframe(df[["codigo", "nombre", "stock", "costo_unitario", "precio_venta"]], 
                         use_container_width=True, hide_index=True)
    
    with tab2:
        # ⭐ Error principal arreglado: limpia campos solos
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
                if not codigo.strip():
                    errores.append("❌ El Código es obligatorio")
                if not nombre.strip():
                    errores.append("❌ El Nombre es obligatorio")
                if costo <= 0:
                    errores.append("❌ El Costo debe ser mayor a 0")
                if precio <= 0:
                    errores.append("❌ El Precio de venta debe ser mayor a 0")
                
                if errores:
                    for e in errores:
                        st.error(e)
                else:
                    codigo = codigo.strip()
                    nombre = nombre.strip()
                    categoria = categoria.strip()
                    
                    try:
                        with get_connection() as conn:
                            c = conn.cursor()
                            # ✅ Arreglo 3: evita código repetido
                            c.execute("SELECT id FROM productos WHERE codigo = %s", (codigo,))
                            if c.fetchone():
                                st.error(f"❌ Ya existe un producto con el código '{codigo}'. Usá otro.")
                                return
                            
                            c.execute("""
                                INSERT INTO productos (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                            """, (codigo, nombre, categoria, stock_inicial, stock_min, costo, precio, unidad))
                            prod_id = c.fetchone()["id"]
                            
                            if stock_inicial > 0:
                                c.execute("""
                                    INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (prod_id, stock_inicial, costo))
                        
                        st.success(f"✅ Producto '{nombre}' creado correctamente")
                        get_productos_activos.clear()
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {str(e)}")
    
    with tab3:
        df = get_productos_activos()
        if not df.empty:
            with st.form("ajuste", clear_on_submit=True):
                prod_id = st.selectbox("Producto", options=df["id"].tolist(),
                                       format_func=lambda x: f"{df[df['id']==x]['nombre'].values[0]} | Stock: {df[df['id']==x]['stock'].values[0]}")
                tipo = st.radio("Tipo", ["entrada", "salida"], horizontal=True)
                cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=0.1)
                motivo = st.selectbox("Motivo", ["Inventario físico", "Pérdida / Merma", "Otro"])
                if st.form_submit_button("Aplicar ajuste"):
                    with get_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT stock, costo_unitario FROM productos WHERE id=%s", (prod_id,))
                        p = c.fetchone()
                        if tipo == "salida" and cantidad > p["stock"]:
                            st.error("❌ Stock insuficiente")
                        else:
                            delta = cantidad if tipo == "entrada" else -cantidad
                            c.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (delta, prod_id))
                            c.execute("""
                                INSERT INTO movimientos_stock (producto_id, tipo, cantidad, costo_unitario, motivo)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (prod_id, tipo, cantidad, p["costo_unitario"], motivo))
                    st.success("✅ Ajuste realizado")
                    get_productos_activos.clear()
                    st.rerun()
        else:
            st.info("Primero creá productos para poder ajustar stock")

    # ➕➖➗ NUEVA PESTAÑA COMPLETA: BORRAR PRODUCTO
    with tab4:
        df = get_productos_activos()
        if df.empty:
            st.warning("No hay productos para borrar.")
        else:
            st.info("ℹ️ El producto desaparecerá de todas las listas, pero se mantendrá tu historial de ventas/compras (no se pierden datos).")
            
            with st.form("borrar_producto", clear_on_submit=True):
                prod_id = st.selectbox(
                    "Seleccioná el producto a borrar",
                    options=df["id"].tolist(),
                    format_func=lambda x: f"Cód: {df[df['id']==x]['codigo'].values[0]} | {df[df['id']==x]['nombre'].values[0]} | Stock: {df[df['id']==x]['stock'].values[0]}"
                )
                confirmar = st.checkbox("✅ Estoy seguro/a, quiero borrar este producto definitivamente de las listas")
                
                if st.form_submit_button("🗑️ BORRAR PRODUCTO"):
                    if not confirmar:
                        st.error("❌ Primero tenés que marcar la casilla de confirmación para borrar")
                    else:
                        try:
                            with get_connection() as conn:
                                c = conn.cursor()
                                # Lo marcamos inactivo (no lo borramos físico para no romper historiales)
                                c.execute("UPDATE productos SET activo = 0 WHERE id = %s", (prod_id,))
                            
                            st.success("✅ Producto borrado correctamente. Ya no aparecerá en ninguna lista.")
                            get_productos_activos.clear()  # Actualizamos la lista al instante
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Error al borrar: {str(e)}")

# ============================================================
# RESTO DEL CÓDIGO 100% IGUAL AL ORIGINAL (SIN TOCAR NADA)
# ============================================================
def pagina_ventas():
    st.title("🛒 Ventas")
    df_prod = get_productos_activos()
    if df_prod.empty:
        st.warning("Primero crea productos")
        return
    
    if "carrito" not in st.session_state:
        st.session_state.carrito = []
    
    with st.form("add_item", clear_on_submit=True):
        prod_id = st.selectbox("Producto", options=df_prod["id"].tolist(),
                               format_func=lambda x: f"{df_prod[df_prod['id']==x]['nombre'].values[0]} | Stock: {df_prod[df_prod['id']==x]['stock'].values[0]}")
        p_row = df_prod[df_prod["id"] == prod_id].iloc[0]
        cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0)
        precio = st.number_input("Precio", value=float(p_row["precio_venta"]), min_value=0.0)
        
        if st.form_submit_button("➕ Agregar"):
            if cantidad > p_row["stock"]:
                st.error("Stock insuficiente")
            else:
                st.session_state.carrito.append({
                    "producto_id": int(prod_id), "nombre": p_row["nombre"],
                    "cantidad": cantidad, "precio": precio,
                    "costo": float(p_row["costo_unitario"]), "subtotal": cantidad * precio
                })
                st.rerun()
    
    if st.session_state.carrito:
        cart_df = pd.DataFrame(st.session_state.carrito)
        st.dataframe(cart_df[["nombre", "cantidad", "precio", "subtotal"]], use_container_width=True, hide_index=True)
        total = cart_df["subtotal"].sum()
        st.markdown(f"### Total: {formato_moneda(total)}")
        
        if st.button("🗑️ Vaciar"):
            st.session_state.carrito = []
            st.rerun()
        
        with st.form("finalizar"):
            cliente = st.text_input("Cliente")
            descuento = st.number_input("Descuento", min_value=0.0, value=0.0)
            metodo = st.selectbox("Método de pago", ["Efectivo", "Tarjeta", "Transferencia", "Otro"])
            if st.form_submit_button("✅ Confirmar Venta"):
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
                st.success(f"Venta #{venta_id} registrada")
                st.rerun()

def pagina_compras():
    st.title("📥 Compras")
    df_prod = get_productos_activos()
    if df_prod.empty:
        st.warning("Primero crea productos")
        return
    
    if "carrito_compra" not in st.session_state:
        st.session_state.carrito_compra = []
    
    with st.form("add_compra", clear_on_submit=True):
        prod_id = st.selectbox("Producto", options=df_prod["id"].tolist(),
                               format_func=lambda x: df_prod[df_prod["id"]==x]["nombre"].values[0])
        cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0)
        costo = st.number_input("Costo unitario", min_value=0.0, value=0.0, step=0.01)
        if st.form_submit_button("➕ Agregar"):
            p_name = df_prod[df_prod["id"]==prod_id]["nombre"].values[0]
            st.session_state.carrito_compra.append({
                "producto_id": int(prod_id), "nombre": p_name,
                "cantidad": cantidad, "costo": costo, "subtotal": cantidad * costo
            })
            st.rerun()
    
    if st.session_state.carrito_compra:
        cdf = pd.DataFrame(st.session_state.carrito_compra)
        st.dataframe(cdf[["nombre", "cantidad", "costo", "subtotal"]], use_container_width=True, hide_index=True)
        total = cdf["subtotal"].sum()
        st.markdown(f"**Total: {formato_moneda(total)}**")
        
        with st.form("confirmar_compra"):
            proveedor = st.text_input("Proveedor")
            metodo = st.selectbox("Método", ["Efectivo", "Transferencia", "Crédito"])
            if st.form_submit_button("✅ Registrar Compra"):
                with get_connection() as conn:
                    c = conn.cursor()
                    c.execute("INSERT INTO compras (proveedor, total, metodo_pago) VALUES (%s, %s, %s) RETURNING id",
                              (proveedor, total, metodo))
                    compra_id = c.fetchone()["id"]
                    for item in st.session_state.carrito_compra:
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
                st.session_state.carrito_compra = []
                st.success("Compra registrada")
                st.rerun()

def pagina_gastos():
    st.title("💸 Gastos")
    with st.form("nuevo_gasto"):
        fecha = st.date_input("Fecha", value=datetime.now().date())
        categoria = st.selectbox("Categoría", get_categorias_gastos())
        descripcion = st.text_input("Descripción")
        monto = st.number_input("Monto", min_value=0.01, value=0.0)
        metodo = st.selectbox("Método", ["Efectivo", "Transferencia", "Tarjeta"])
        if st.form_submit_button("💾 Guardar"):
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO gastos (fecha, categoria, descripcion, monto, metodo_pago)
                    VALUES (%s, %s, %s, %s, %s)
                """, (fecha, categoria, descripcion, monto, metodo))
            st.success("Gasto guardado")
            st.rerun()

def pagina_reportes():
    st.title("📈 Reportes")
    c1, c2 = st.columns(2)
    with c1:
        fecha_inicio = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="r1")
    with c2:
        fecha_fin = st.date_input("Hasta", value=datetime.now().date(), key="r2")
    
    fi, ff = fecha_inicio.isoformat(), fecha_fin.isoformat()
    ingresos = calcular_ingresos(fi, ff)
    cogs = calcular_cogs_periodo(fi, ff)
    gastos = calcular_gastos(fi, ff)
    
    r1, r2 = st.columns(2)
    r1.metric("Ingresos", formato_moneda(ingresos))
    r2.metric("Utilidad Neta", formato_moneda(ingresos - cogs - gastos))

def pagina_historial():
    st.title("📜 Historial")
    tab1, tab2, tab3 = st.tabs(["Ventas", "Compras", "Gastos"])
    
    with get_connection() as conn:
        with tab1:
            df = pd.read_sql_query("SELECT fecha, cliente, total, metodo_pago FROM ventas ORDER BY fecha DESC LIMIT 30", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin ventas")
        with tab2:
            df = pd.read_sql_query("SELECT fecha, proveedor, total FROM compras ORDER BY fecha DESC LIMIT 30", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin compras")
        with tab3:
            df = pd.read_sql_query("SELECT fecha, categoria, monto FROM gastos ORDER BY fecha DESC LIMIT 30", conn)
            st.dataframe(df, use_container_width=True, hide_index=True) if not df.empty else st.info("Sin gastos")

# ============================================================
# MAIN (SIN CAMBIOS)
# ============================================================
def main():
    st.sidebar.title("🏪 Negocio Pro")
    st.sidebar.caption("Versión en la nube")
    
    pagina = st.sidebar.radio("Menú", [
        "📊 Dashboard", "📦 Inventario", "🛒 Ventas",
        "📥 Compras", "💸 Gastos", "📈 Reportes", "📜 Historial"
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
