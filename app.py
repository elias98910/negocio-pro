import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os

# =========================================================
# CONFIGURACIÓN
# =========================================================
st.set_page_config(
    page_title="Mi Negocio",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stButton > button {
        width: 100%;
        height: 3.2rem;
        font-size: 1.15rem;
        border-radius: 12px;
        font-weight: 600;
    }
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2.5rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    h1 { font-size: 1.55rem !important; margin-bottom: 0.8rem !important; }
    h2, h3 { font-size: 1.25rem !important; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# BASE DE DATOS
# =========================================================
def get_db_url():
    try:
        return st.secrets["DATABASE_URL"]
    except Exception:
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
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                codigo TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                categoria TEXT DEFAULT '',
                stock REAL DEFAULT 0,
                stock_minimo REAL DEFAULT 0,
                costo_unitario REAL DEFAULT 0,
                precio_venta REAL DEFAULT 0,
                unidad TEXT DEFAULT 'unidad',
                activo INTEGER DEFAULT 1,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER REFERENCES productos(id),
                tipo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                costo REAL,
                motivo TEXT,
                referencia TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cliente TEXT DEFAULT '',
                total REAL NOT NULL,
                descuento REAL DEFAULT 0,
                metodo TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS venta_items (
                id SERIAL PRIMARY KEY,
                venta_id INTEGER REFERENCES ventas(id),
                producto_id INTEGER REFERENCES productos(id),
                cantidad REAL NOT NULL,
                precio REAL NOT NULL,
                costo REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compras (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proveedor TEXT DEFAULT '',
                total REAL NOT NULL,
                metodo TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compra_items (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER REFERENCES compras(id),
                producto_id INTEGER REFERENCES productos(id),
                cantidad REAL NOT NULL,
                costo REAL NOT NULL,
                subtotal REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                categoria TEXT NOT NULL,
                descripcion TEXT DEFAULT '',
                monto REAL NOT NULL,
                metodo TEXT DEFAULT ''
            )
        """)

try:
    init_db()
except Exception as e:
    st.error(f"No se pudo conectar a la base de datos: {e}")
    st.stop()

# =========================================================
# HELPERS
# =========================================================
def money(v):
    try:
        return f"${float(v):,.2f}"
    except:
        return "$0.00"

def get_productos_df():
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT id, codigo, nombre, stock, costo_unitario, precio_venta, 
                   categoria, unidad, stock_minimo
            FROM productos 
            WHERE activo = 1 
            ORDER BY nombre
            """,
            conn
        )

def run_kpi(fi, ff, sql):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (fi, ff))
        row = cur.fetchone()
        return float(row["v"] or 0)

# =========================================================
# DASHBOARD
# =========================================================
def page_dashboard():
    st.title("📊 Resumen del Negocio")

    col1, col2 = st.columns(2)
    with col1:
        fecha_desde = st.date_input("Desde", value=datetime.now().date() - timedelta(days=30))
    with col2:
        fecha_hasta = st.date_input("Hasta", value=datetime.now().date())

    fi = str(fecha_desde)
    ff = str(fecha_hasta)

    ingresos = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(total - descuento), 0) as v 
        FROM ventas 
        WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0
    """)
    cogs = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(vi.cantidad * vi.costo), 0) as v
        FROM venta_items vi
        JOIN ventas v ON vi.venta_id = v.id
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """)
    gastos = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(monto), 0) as v 
        FROM gastos 
        WHERE DATE(fecha) BETWEEN %s AND %s
    """)
    compras = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(total), 0) as v 
        FROM compras 
        WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0
    """)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(stock * costo_unitario), 0) as v FROM productos WHERE activo = 1")
        valor_stock = float(cur.fetchone()["v"] or 0)

    utilidad_bruta = ingresos - cogs
    utilidad_neta = utilidad_bruta - gastos

    st.markdown("---")
    a, b = st.columns(2)
    a.metric("Ingresos", money(ingresos))
    b.metric("Costo de mercadería", money(cogs))

    c, d = st.columns(2)
    c.metric("Utilidad Bruta", money(utilidad_bruta))
    d.metric("Gastos", money(gastos))

    st.metric("Utilidad Neta", money(utilidad_neta))

    e, f = st.columns(2)
    e.metric("Compras del período", money(compras))
    f.metric("Valor del inventario", money(valor_stock))

    # Alerta stock bajo
    with get_connection() as conn:
        bajo = pd.read_sql_query(
            """
            SELECT nombre, stock, stock_minimo 
            FROM productos 
            WHERE activo = 1 AND stock <= stock_minimo AND stock_minimo > 0
            ORDER BY stock ASC
            """,
            conn
        )

    if not bajo.empty:
        st.warning(f"⚠️ Hay {len(bajo)} producto(s) con stock bajo")
        with st.expander("Ver productos con stock bajo"):
            st.dataframe(bajo, use_container_width=True, hide_index=True)

# =========================================================
# INVENTARIO
# =========================================================
def page_inventario():
    st.title("📦 Inventario")

    tab_lista, tab_nuevo, tab_ajuste, tab_borrar = st.tabs(
        ["Lista", "Nuevo producto", "Ajuste de stock", "Eliminar"]
    )

    df = get_productos_df()

    # ----- LISTA -----
    with tab_lista:
        if df.empty:
            st.info("Todavía no hay productos cargados.")
        else:
            st.dataframe(
                df[["codigo", "nombre", "stock", "costo_unitario", "precio_venta"]],
                use_container_width=True,
                hide_index=True
            )

    # ----- NUEVO PRODUCTO -----
    with tab_nuevo:
        st.subheader("Cargar producto nuevo")

        with st.form("form_nuevo", clear_on_submit=True):
            codigo = st.text_input("Código del producto")
            nombre = st.text_input("Nombre del producto")
            categoria = st.text_input("Categoría (opcional)")
            unidad = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"])
            stock_ini = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=1.0)
            costo = st.number_input("Costo unitario", min_value=0.0, value=0.0, step=0.01)
            precio = st.number_input("Precio de venta", min_value=0.0, value=0.0, step=0.01)
            stock_min = st.number_input("Stock mínimo (alerta)", min_value=0.0, value=5.0, step=1.0)

            boton = st.form_submit_button("Guardar producto")

        if boton:
            codigo = (codigo or "").strip()
            nombre = (nombre or "").strip()
            categoria = (categoria or "").strip()

            if not codigo or not nombre:
                st.error("El código y el nombre son obligatorios.")
            elif costo <= 0 or precio <= 0:
                st.error("El costo y el precio deben ser mayores a cero.")
            else:
                try:
                    with get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM productos WHERE codigo = %s", (codigo,))
                        if cur.fetchone():
                            st.error(f"Ya existe un producto con el código: {codigo}")
                        else:
                            cur.execute("""
                                INSERT INTO productos 
                                (codigo, nombre, categoria, stock, stock_minimo, costo_unitario, precio_venta, unidad)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING id
                            """, (codigo, nombre, categoria, stock_ini, stock_min, costo, precio, unidad))
                            nuevo_id = cur.fetchone()["id"]

                            if stock_ini > 0:
                                cur.execute("""
                                    INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (nuevo_id, stock_ini, costo))

                    st.success(f"Producto guardado: {nombre}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")

    # ----- AJUSTE -----
    with tab_ajuste:
        if df.empty:
            st.info("Primero carga productos.")
        else:
            prod_id = st.selectbox(
                "Elegir producto",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]}  |  Stock actual: {df.loc[df['id']==x, 'stock'].values[0]}"
            )
            tipo = st.radio("Tipo de movimiento", ["entrada", "salida"], horizontal=True)
            cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
            motivo = st.selectbox("Motivo", ["Inventario físico", "Merma / Pérdida", "Ajuste", "Otro"])

            if st.button("Aplicar ajuste"):
                try:
                    with get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT stock, costo_unitario FROM productos WHERE id = %s", (int(prod_id),))
                        p = cur.fetchone()

                        if tipo == "salida" and cantidad > p["stock"]:
                            st.error("No hay suficiente stock.")
                        else:
                            delta = cantidad if tipo == "entrada" else -cantidad
                            cur.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (delta, int(prod_id)))
                            cur.execute("""
                                INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (int(prod_id), tipo, cantidad, p["costo_unitario"], motivo))
                    st.success("Ajuste realizado.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # ----- ELIMINAR -----
    with tab_borrar:
        if df.empty:
            st.info("No hay productos.")
        else:
            prod_id = st.selectbox(
                "Producto a eliminar",
                options=df["id"].tolist(),
                format_func=lambda x: f"{df.loc[df['id']==x, 'codigo'].values[0]} - {df.loc[df['id']==x, 'nombre'].values[0]}"
            )
            if st.checkbox("Confirmo que quiero eliminar este producto"):
                if st.button("Eliminar producto", type="primary"):
                    with get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("UPDATE productos SET activo = 0 WHERE id = %s", (int(prod_id),))
                    st.success("Producto eliminado.")
                    st.rerun()

# =========================================================
# VENTAS
# =========================================================
def page_ventas():
    st.title("🛒 Ventas")

    df = get_productos_df()
    if df.empty:
        st.warning("Primero debes cargar productos.")
        return

    if "carrito_venta" not in st.session_state:
        st.session_state.carrito_venta = []

    st.subheader("Agregar al carrito")
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]}  |  Stock: {df.loc[df['id']==x, 'stock'].values[0]}  |  ${df.loc[df['id']==x, 'precio_venta'].values[0]:.2f}"
    )
    fila = df[df["id"] == prod_id].iloc[0]
    cant = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
    precio = st.number_input("Precio unitario", value=float(fila["precio_venta"]), min_value=0.0, step=0.01)

    if st.button("Agregar"):
        if cant > fila["stock"]:
            st.error("Stock insuficiente.")
        else:
            st.session_state.carrito_venta.append({
                "producto_id": int(prod_id),
                "nombre": fila["nombre"],
                "cantidad": float(cant),
                "precio": float(precio),
                "costo": float(fila["costo_unitario"]),
                "subtotal": float(cant) * float(precio)
            })
            st.rerun()

    if st.session_state.carrito_venta:
        carrito = pd.DataFrame(st.session_state.carrito_venta)
        st.dataframe(carrito[["nombre", "cantidad", "precio", "subtotal"]], use_container_width=True, hide_index=True)
        total = carrito["subtotal"].sum()
        st.markdown(f"### Total: {money(total)}")

        if st.button("Vaciar carrito"):
            st.session_state.carrito_venta = []
            st.rerun()

        st.markdown("---")
        cliente = st.text_input("Cliente (opcional)")
        descuento = st.number_input("Descuento", min_value=0.0, value=0.0, step=1.0)
        metodo = st.selectbox("Forma de pago", ["Efectivo", "Tarjeta", "Transferencia", "Otro"])

        if st.button("Confirmar venta", type="primary"):
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO ventas (cliente, total, descuento, metodo)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    """, (cliente, total, descuento, metodo))
                    venta_id = cur.fetchone()["id"]

                    for item in st.session_state.carrito_venta:
                        cur.execute("""
                            INSERT INTO venta_items 
                            (venta_id, producto_id, cantidad, precio, costo, subtotal)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (venta_id, item["producto_id"], item["cantidad"], item["precio"], item["costo"], item["subtotal"]))
                        cur.execute("UPDATE productos SET stock = stock - %s WHERE id = %s",
                                    (item["cantidad"], item["producto_id"]))
                        cur.execute("""
                            INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo, referencia)
                            VALUES (%s, 'salida', %s, %s, 'Venta', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Venta #{venta_id}"))

                st.session_state.carrito_venta = []
                st.success(f"Venta #{venta_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# =========================================================
# COMPRAS
# =========================================================
def page_compras():
    st.title("📥 Compras")

    df = get_productos_df()
    if df.empty:
        st.warning("Primero debes cargar productos.")
        return

    if "carrito_compra" not in st.session_state:
        st.session_state.carrito_compra = []

    st.subheader("Agregar productos comprados")
    prod_id = st.selectbox(
        "Producto",
        options=df["id"].tolist(),
        format_func=lambda x: f"{df.loc[df['id']==x, 'nombre'].values[0]}"
    )
    cant = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0, key="compra_cant")
    costo = st.number_input("Costo unitario de esta compra", min_value=0.0, value=0.0, step=0.01, key="compra_costo")

    if st.button("Agregar a la compra"):
        nombre = df.loc[df["id"] == prod_id, "nombre"].values[0]
        st.session_state.carrito_compra.append({
            "producto_id": int(prod_id),
            "nombre": nombre,
            "cantidad": float(cant),
            "costo": float(costo),
            "subtotal": float(cant) * float(costo)
        })
        st.rerun()

    if st.session_state.carrito_compra:
        carrito = pd.DataFrame(st.session_state.carrito_compra)
        st.dataframe(carrito[["nombre", "cantidad", "costo", "subtotal"]], use_container_width=True, hide_index=True)
        total = carrito["subtotal"].sum()
        st.markdown(f"**Total compra: {money(total)}**")

        if st.button("Vaciar"):
            st.session_state.carrito_compra = []
            st.rerun()

        proveedor = st.text_input("Proveedor")
        metodo = st.selectbox("Forma de pago", ["Efectivo", "Transferencia", "Crédito"])

        if st.button("Registrar compra", type="primary"):
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO compras (proveedor, total, metodo)
                        VALUES (%s, %s, %s) RETURNING id
                    """, (proveedor, total, metodo))
                    compra_id = cur.fetchone()["id"]

                    for item in st.session_state.carrito_compra:
                        cur.execute("""
                            INSERT INTO compra_items (compra_id, producto_id, cantidad, costo, subtotal)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (compra_id, item["producto_id"], item["cantidad"], item["costo"], item["subtotal"]))
                        cur.execute("""
                            UPDATE productos 
                            SET stock = stock + %s, costo_unitario = %s 
                            WHERE id = %s
                        """, (item["cantidad"], item["costo"], item["producto_id"]))
                        cur.execute("""
                            INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo, referencia)
                            VALUES (%s, 'entrada', %s, %s, 'Compra', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Compra #{compra_id}"))

                st.session_state.carrito_compra = []
                st.success(f"Compra #{compra_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# =========================================================
# GASTOS
# =========================================================
def page_gastos():
    st.title("💸 Gastos")

    fecha = st.date_input("Fecha", value=datetime.now().date())
    categoria = st.selectbox("Categoría", [
        "Alquiler", "Servicios", "Sueldos", "Marketing", "Transporte",
        "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"
    ])
    descripcion = st.text_input("Descripción")
    monto = st.number_input("Monto", min_value=0.01, value=0.0, step=1.0)
    metodo = st.selectbox("Forma de pago", ["Efectivo", "Transferencia", "Tarjeta"])

    if st.button("Guardar gasto"):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO gastos (fecha, categoria, descripcion, monto, metodo)
                    VALUES (%s, %s, %s, %s, %s)
                """, (fecha, categoria, descripcion, monto, metodo))
            st.success("Gasto guardado")
            st.rerun()
        except Exception as e:
            st.error(str(e))

# =========================================================
# REPORTES
# =========================================================
def page_reportes():
    st.title("📈 Reportes")

    col1, col2 = st.columns(2)
    with col1:
        fi = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="rep_desde")
    with col2:
        ff = st.date_input("Hasta", value=datetime.now().date(), key="rep_hasta")

    fi, ff = str(fi), str(ff)

    ingresos = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(total - descuento), 0) as v 
        FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0
    """)
    cogs = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(vi.cantidad * vi.costo), 0) as v
        FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """)
    gastos = run_kpi(fi, ff, """
        SELECT COALESCE(SUM(monto), 0) as v 
        FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s
    """)

    a, b = st.columns(2)
    a.metric("Ingresos", money(ingresos))
    b.metric("Utilidad Neta", money(ingresos - cogs - gastos))

# =========================================================
# HISTORIAL + ANULAR
# =========================================================
def page_historial():
    st.title("📜 Historial")

    t1, t2, t3, t4, t5 = st.tabs(["Ventas", "Compras", "Gastos", "Anular Venta", "Anular Compra"])

    with get_connection() as conn:
        with t1:
            df = pd.read_sql_query(
                "SELECT id, fecha, cliente, total, descuento, metodo FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 40",
                conn
            )
            if df.empty:
                st.info("Sin ventas")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)

        with t2:
            df = pd.read_sql_query(
                "SELECT id, fecha, proveedor, total, metodo FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 40",
                conn
            )
            if df.empty:
                st.info("Sin compras")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)

        with t3:
            df = pd.read_sql_query(
                "SELECT fecha, categoria, descripcion, monto FROM gastos ORDER BY fecha DESC LIMIT 40",
                conn
            )
            if df.empty:
                st.info("Sin gastos")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)

    # Anular Venta
    with t4:
        st.info("Al anular una venta se devuelve el stock automáticamente.")
        with get_connection() as conn:
            ventas = pd.read_sql_query(
                "SELECT id, fecha, total FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 25",
                conn
            )

        if ventas.empty:
            st.warning("No hay ventas para anular")
        else:
            venta_id = st.selectbox(
                "Seleccionar venta",
                options=ventas["id"].tolist(),
                format_func=lambda x: f"#{x}  —  {money(ventas.loc[ventas['id']==x, 'total'].values[0])}"
            )
            if st.checkbox("Confirmo anular esta venta"):
                if st.button("Anular Venta", type="primary"):
                    try:
                        with get_connection() as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT producto_id, cantidad, costo FROM venta_items WHERE venta_id = %s", (int(venta_id),))
                            items = cur.fetchall()
                            cur.execute("UPDATE ventas SET anulada = 1 WHERE id = %s", (int(venta_id),))
                            for it in items:
                                cur.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (it["cantidad"], it["producto_id"]))
                                cur.execute("""
                                    INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Anulación de venta', %s)
                                """, (it["producto_id"], it["cantidad"], it["costo"], f"Anul. Venta #{venta_id}"))
                        st.success("Venta anulada y stock devuelto")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    # Anular Compra
    with t5:
        st.info("Al anular una compra se descuenta el stock.")
        with get_connection() as conn:
            compras = pd.read_sql_query(
                "SELECT id, fecha, total FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 25",
                conn
            )

        if compras.empty:
            st.warning("No hay compras para anular")
        else:
            compra_id = st.selectbox(
                "Seleccionar compra",
                options=compras["id"].tolist(),
                format_func=lambda x: f"#{x}  —  {money(compras.loc[compras['id']==x, 'total'].values[0])}"
            )
            if st.checkbox("Confirmo anular esta compra"):
                if st.button("Anular Compra", type="primary"):
                    try:
                        with get_connection() as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT producto_id, cantidad, costo FROM compra_items WHERE compra_id = %s", (int(compra_id),))
                            items = cur.fetchall()

                            for it in items:
                                cur.execute("SELECT stock FROM productos WHERE id = %s", (it["producto_id"],))
                                stock_actual = cur.fetchone()["stock"]
                                if stock_actual < it["cantidad"]:
                                    st.error("No se puede anular: stock insuficiente")
                                    return

                            cur.execute("UPDATE compras SET anulada = 1 WHERE id = %s", (int(compra_id),))
                            for it in items:
                                cur.execute("UPDATE productos SET stock = stock - %s WHERE id = %s", (it["cantidad"], it["producto_id"]))
                                cur.execute("""
                                    INSERT INTO movimientos (producto_id, tipo, cantidad, costo, motivo, referencia)
                                    VALUES (%s, 'salida', %s, %s, 'Anulación de compra', %s)
                                """, (it["producto_id"], it["cantidad"], it["costo"], f"Anul. Compra #{compra_id}"))
                        st.success("Compra anulada y stock actualizado")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

# =========================================================
# MAIN
# =========================================================
def main():
    st.sidebar.title("🏪 Mi Negocio")
    st.sidebar.caption("Control diario")

    opcion = st.sidebar.radio(
        "Ir a",
        [
            "📊 Resumen",
            "📦 Inventario",
            "🛒 Ventas",
            "📥 Compras",
            "💸 Gastos",
            "📈 Reportes",
            "📜 Historial"
        ]
    )

    if opcion == "📊 Resumen":
        page_dashboard()
    elif opcion == "📦 Inventario":
        page_inventario()
    elif opcion == "🛒 Ventas":
        page_ventas()
    elif opcion == "📥 Compras":
        page_compras()
    elif opcion == "💸 Gastos":
        page_gastos()
    elif opcion == "📈 Reportes":
        page_reportes()
    elif opcion == "📜 Historial":
        page_historial()

if __name__ == "__main__":
    main()
