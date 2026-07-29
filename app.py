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
    font-size: 1.1rem;
    border-radius: 12px;
    font-weight: 600;
}
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2.5rem;
    padding-left: 1rem;
    padding-right: 1rem;
}
h1 { font-size: 1.6rem !important; }
div[data-testid="stForm"] {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 1.2rem;
    background: #fafafa;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# HELPERS SEGUROS
# ============================================================
def money(v):
    try:
        return f"${float(v):,.2f}"
    except:
        return "$0.00"

def to_int(v):
    try:
        if v is None:
            return 0
        return int(float(v))
    except:
        return 0

def to_float(v):
    try:
        if v is None:
            return 0.0
        return float(v)
    except:
        return 0.0

def to_str(v):
    try:
        if v is None:
            return ""
        return str(v).strip()
    except:
        return ""

# ============================================================
# BASE DE DATOS
# ============================================================
def get_db_url():
    try:
        return st.secrets["DATABASE_URL"]
    except:
        return os.getenv("DATABASE_URL", "")

@contextmanager
def db():
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

def init_tables():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS productos (
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
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_stock (
                id SERIAL PRIMARY KEY,
                producto_id INTEGER REFERENCES productos(id),
                tipo TEXT NOT NULL,
                cantidad REAL NOT NULL,
                costo_unitario REAL DEFAULT 0,
                motivo TEXT DEFAULT '',
                referencia TEXT DEFAULT '',
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
                metodo_pago TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compras (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proveedor TEXT DEFAULT '',
                total REAL NOT NULL,
                metodo_pago TEXT DEFAULT '',
                anulada INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compra_detalle (
                id SERIAL PRIMARY KEY,
                compra_id INTEGER REFERENCES compras(id),
                producto_id INTEGER REFERENCES productos(id),
                cantidad REAL NOT NULL,
                costo_unitario REAL NOT NULL,
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
                metodo_pago TEXT DEFAULT ''
            )
        """)

try:
    init_tables()
except Exception as e:
    st.error(f"Error de base de datos: {e}")
    st.stop()

# ============================================================
# FUNCIONES DE DATOS
# ============================================================
def listar_productos():
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, codigo, nombre, stock, costo_unitario, precio_venta,
                   categoria, unidad, stock_minimo
            FROM productos
            WHERE activo = 1
            ORDER BY nombre
        """)
        rows = cur.fetchall()
        return [{
            "id": to_int(r["id"]),
            "codigo": to_str(r["codigo"]),
            "nombre": to_str(r["nombre"]),
            "stock": to_float(r["stock"]),
            "costo": to_float(r["costo_unitario"]),
            "precio": to_float(r["precio_venta"]),
            "categoria": to_str(r["categoria"]),
            "unidad": to_str(r["unidad"]) or "unidad",
            "stock_minimo": to_float(r["stock_minimo"])
        } for r in rows]

def calcular(sql, params=None):
    with db() as conn:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        row = cur.fetchone()
        return to_float(row["v"]) if row else 0.0

# ============================================================
# ESTADO
# ============================================================
if "carrito_venta" not in st.session_state:
    st.session_state.carrito_venta = []
if "carrito_compra" not in st.session_state:
    st.session_state.carrito_compra = []

# ============================================================
# RESUMEN
# ============================================================
def pagina_resumen():
    st.title("📊 Resumen")

    c1, c2 = st.columns(2)
    with c1:
        desde = st.date_input("Desde", value=datetime.now().date() - timedelta(days=30))
    with c2:
        hasta = st.date_input("Hasta", value=datetime.now().date())

    fi, ff = str(desde), str(hasta)

    ingresos = calcular(
        "SELECT COALESCE(SUM(total - descuento),0) AS v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0",
        (fi, ff)
    )
    cogs = calcular("""
        SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario),0) AS v
        FROM venta_detalle vd
        JOIN ventas v ON vd.venta_id = v.id
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """, (fi, ff))
    gastos = calcular(
        "SELECT COALESCE(SUM(monto),0) AS v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s",
        (fi, ff)
    )
    compras = calcular(
        "SELECT COALESCE(SUM(total),0) AS v FROM compras WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0",
        (fi, ff)
    )
    valor_stock = calcular(
        "SELECT COALESCE(SUM(stock * costo_unitario),0) AS v FROM productos WHERE activo = 1"
    )

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

    with db() as conn:
        bajo = pd.read_sql_query(
            "SELECT nombre, stock, stock_minimo FROM productos WHERE activo = 1 AND stock <= stock_minimo AND stock_minimo > 0 ORDER BY stock",
            conn
        )
    if not bajo.empty:
        st.warning(f"⚠️ {len(bajo)} producto(s) con stock bajo")
        with st.expander("Ver productos"):
            st.dataframe(bajo, use_container_width=True, hide_index=True)

# ============================================================
# INVENTARIO
# ============================================================
def pagina_inventario():
    st.title("📦 Inventario")

    tab1, tab2, tab3, tab4 = st.tabs(["Lista", "Nuevo producto", "Ajuste de stock", "Eliminar"])

    productos = listar_productos()

    with tab1:
        if not productos:
            st.info("Todavía no hay productos.")
        else:
            df = pd.DataFrame(productos)
            st.dataframe(
                df[["codigo", "nombre", "stock", "costo", "precio"]],
                use_container_width=True,
                hide_index=True
            )

    with tab2:
        st.subheader("Cargar producto nuevo")

        with st.form("form_nuevo_producto", clear_on_submit=True):
            codigo = st.text_input("Código del producto")
            nombre = st.text_input("Nombre del producto")
            categoria = st.text_input("Categoría")
            unidad = st.selectbox("Unidad", ["unidad", "kg", "litro", "caja", "paquete"])
            stock_inicial = st.number_input("Stock inicial", min_value=0.0, value=0.0, step=1.0)
            costo = st.number_input("Costo unitario", min_value=0.0, value=0.0, step=0.01)
            precio = st.number_input("Precio de venta", min_value=0.0, value=0.0, step=0.01)
            stock_minimo = st.number_input("Stock mínimo (alerta)", min_value=0.0, value=5.0, step=1.0)

            guardar = st.form_submit_button("Guardar producto")

        if guardar:
            codigo = to_str(codigo)
            nombre = to_str(nombre)
            categoria = to_str(categoria)

            if codigo == "" or nombre == "":
                st.error("El código y el nombre son obligatorios.")
            elif costo <= 0 or precio <= 0:
                st.error("El costo y el precio deben ser mayores a cero.")
            else:
                try:
                    nuevo_id = None
                    with db() as conn:
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
                            """, (codigo, nombre, categoria, stock_inicial, stock_minimo, costo, precio, unidad))
                            nuevo_id = to_int(cur.fetchone()["id"])

                            if stock_inicial > 0:
                                cur.execute("""
                                    INSERT INTO movimientos_stock
                                    (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Stock inicial', 'ALTA')
                                """, (nuevo_id, stock_inicial, costo))

                    if nuevo_id:
                        st.success(f"Producto guardado: {nombre}")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")

    with tab3:
        if not productos:
            st.info("Primero cargá productos.")
        else:
            ids = [p["id"] for p in productos]
            prod_id = st.selectbox(
                "Producto",
                options=ids,
                format_func=lambda x: next(
                    (f"{p['nombre']}  |  Stock: {p['stock']}" for p in productos if p["id"] == x),
                    str(x)
                )
            )
            tipo = st.radio("Tipo", ["entrada", "salida"], horizontal=True)
            cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
            motivo = st.selectbox("Motivo", ["Inventario físico", "Merma / Pérdida", "Ajuste", "Otro"])

            if st.button("Aplicar ajuste"):
                try:
                    with db() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT stock, costo_unitario FROM productos WHERE id = %s", (prod_id,))
                        p = cur.fetchone()
                        stock_actual = to_float(p["stock"])
                        costo_actual = to_float(p["costo_unitario"])

                        if tipo == "salida" and cantidad > stock_actual:
                            st.error("No hay suficiente stock.")
                        else:
                            delta = cantidad if tipo == "entrada" else -cantidad
                            cur.execute("UPDATE productos SET stock = stock + %s WHERE id = %s", (delta, prod_id))
                            cur.execute("""
                                INSERT INTO movimientos_stock
                                (producto_id, tipo, cantidad, costo_unitario, motivo)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (prod_id, tipo, cantidad, costo_actual, motivo))
                    st.success("Ajuste realizado.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with tab4:
        if not productos:
            st.info("No hay productos.")
        else:
            ids = [p["id"] for p in productos]
            prod_id = st.selectbox(
                "Producto a eliminar",
                options=ids,
                format_func=lambda x: next(
                    (f"{p['codigo']} - {p['nombre']}" for p in productos if p["id"] == x),
                    str(x)
                )
            )
            if st.checkbox("Confirmo eliminar este producto"):
                if st.button("Eliminar", type="primary"):
                    with db() as conn:
                        cur = conn.cursor()
                        cur.execute("UPDATE productos SET activo = 0 WHERE id = %s", (prod_id,))
                    st.success("Producto eliminado.")
                    st.rerun()

# ============================================================
# VENTAS
# ============================================================
def pagina_ventas():
    st.title("🛒 Ventas")

    productos = listar_productos()
    if not productos:
        st.warning("Primero debés cargar productos.")
        return

    ids = [p["id"] for p in productos]

    st.subheader("Agregar al carrito")
    prod_id = st.selectbox(
        "Producto",
        options=ids,
        format_func=lambda x: next(
            (f"{p['nombre']}  |  Stock: {p['stock']}  |  ${p['precio']:.2f}" for p in productos if p["id"] == x),
            str(x)
        )
    )
    prod = next(p for p in productos if p["id"] == prod_id)

    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0)
    precio = st.number_input("Precio unitario", value=prod["precio"], min_value=0.0, step=0.01)

    if st.button("Agregar al carrito"):
        if cantidad > prod["stock"]:
            st.error("Stock insuficiente.")
        else:
            st.session_state.carrito_venta.append({
                "producto_id": prod_id,
                "nombre": prod["nombre"],
                "cantidad": cantidad,
                "precio": precio,
                "costo": prod["costo"],
                "subtotal": cantidad * precio
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
                with db() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO ventas (cliente, total, descuento, metodo_pago)
                        VALUES (%s, %s, %s, %s) RETURNING id
                    """, (to_str(cliente), total, descuento, metodo))
                    venta_id = to_int(cur.fetchone()["id"])

                    for item in st.session_state.carrito_venta:
                        cur.execute("""
                            INSERT INTO venta_detalle
                            (venta_id, producto_id, cantidad, precio_unitario, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (venta_id, item["producto_id"], item["cantidad"], item["precio"], item["costo"], item["subtotal"]))
                        cur.execute(
                            "UPDATE productos SET stock = stock - %s WHERE id = %s",
                            (item["cantidad"], item["producto_id"])
                        )
                        cur.execute("""
                            INSERT INTO movimientos_stock
                            (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'salida', %s, %s, 'Venta', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Venta #{venta_id}"))

                st.session_state.carrito_venta = []
                st.success(f"Venta #{venta_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ============================================================
# COMPRAS
# ============================================================
def pagina_compras():
    st.title("📥 Compras")

    productos = listar_productos()
    if not productos:
        st.warning("Primero debés cargar productos.")
        return

    ids = [p["id"] for p in productos]

    st.subheader("Agregar productos comprados")
    prod_id = st.selectbox(
        "Producto",
        options=ids,
        format_func=lambda x: next((p["nombre"] for p in productos if p["id"] == x), str(x))
    )
    cantidad = st.number_input("Cantidad", min_value=0.01, value=1.0, step=1.0, key="compra_cant")
    costo = st.number_input("Costo unitario de esta compra", min_value=0.0, value=0.0, step=0.01, key="compra_costo")

    if st.button("Agregar a la compra"):
        nombre = next(p["nombre"] for p in productos if p["id"] == prod_id)
        st.session_state.carrito_compra.append({
            "producto_id": prod_id,
            "nombre": nombre,
            "cantidad": cantidad,
            "costo": costo,
            "subtotal": cantidad * costo
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
                with db() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO compras (proveedor, total, metodo_pago)
                        VALUES (%s, %s, %s) RETURNING id
                    """, (to_str(proveedor), total, metodo))
                    compra_id = to_int(cur.fetchone()["id"])

                    for item in st.session_state.carrito_compra:
                        cur.execute("""
                            INSERT INTO compra_detalle
                            (compra_id, producto_id, cantidad, costo_unitario, subtotal)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (compra_id, item["producto_id"], item["cantidad"], item["costo"], item["subtotal"]))
                        cur.execute("""
                            UPDATE productos
                            SET stock = stock + %s, costo_unitario = %s
                            WHERE id = %s
                        """, (item["cantidad"], item["costo"], item["producto_id"]))
                        cur.execute("""
                            INSERT INTO movimientos_stock
                            (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                            VALUES (%s, 'entrada', %s, %s, 'Compra', %s)
                        """, (item["producto_id"], item["cantidad"], item["costo"], f"Compra #{compra_id}"))

                st.session_state.carrito_compra = []
                st.success(f"Compra #{compra_id} registrada")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ============================================================
# GASTOS
# ============================================================
def pagina_gastos():
    st.title("💸 Gastos")

    fecha = st.date_input("Fecha", value=datetime.now().date())
    categoria = st.selectbox("Categoría", [
        "Alquiler", "Servicios", "Sueldos", "Marketing", "Transporte",
        "Impuestos", "Mantenimiento", "Seguros", "Papelería", "Otros"
    ])
    descripcion = st.text_input("Descripción")
    monto = st.number_input("Monto", min_value=0.0, value=0.0, step=1.0)
    metodo = st.selectbox("Forma de pago", ["Efectivo", "Transferencia", "Tarjeta"])

    if st.button("Guardar gasto"):
        if monto <= 0:
            st.error("El monto debe ser mayor a 0")
        else:
            try:
                with db() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO gastos (fecha, categoria, descripcion, monto, metodo_pago)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (fecha, categoria, to_str(descripcion), monto, metodo))
                st.success("Gasto guardado")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ============================================================
# REPORTES
# ============================================================
def pagina_reportes():
    st.title("📈 Reportes")

    c1, c2 = st.columns(2)
    with c1:
        desde = st.date_input("Desde", value=datetime.now().date() - timedelta(days=90), key="rep_desde")
    with c2:
        hasta = st.date_input("Hasta", value=datetime.now().date(), key="rep_hasta")

    fi, ff = str(desde), str(hasta)

    ingresos = calcular(
        "SELECT COALESCE(SUM(total - descuento),0) AS v FROM ventas WHERE DATE(fecha) BETWEEN %s AND %s AND anulada = 0",
        (fi, ff)
    )
    cogs = calcular("""
        SELECT COALESCE(SUM(vd.cantidad * vd.costo_unitario),0) AS v
        FROM venta_detalle vd JOIN ventas v ON vd.venta_id = v.id
        WHERE DATE(v.fecha) BETWEEN %s AND %s AND v.anulada = 0
    """, (fi, ff))
    gastos = calcular(
        "SELECT COALESCE(SUM(monto),0) AS v FROM gastos WHERE DATE(fecha) BETWEEN %s AND %s",
        (fi, ff)
    )

    a, b = st.columns(2)
    a.metric("Ingresos", money(ingresos))
    b.metric("Utilidad Neta", money(ingresos - cogs - gastos))

# ============================================================
# HISTORIAL + ANULAR
# ============================================================
def pagina_historial():
    st.title("📜 Historial")

    t1, t2, t3, t4, t5 = st.tabs(["Ventas", "Compras", "Gastos", "Anular Venta", "Anular Compra"])

    with db() as conn:
        with t1:
            df = pd.read_sql_query(
                "SELECT id, fecha, cliente, total, descuento, metodo_pago FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 40",
                conn
            )
            if df.empty:
                st.info("Sin ventas")
            else:
                st.dataframe(df, use_container_width=True, hide_index=True)

        with t2:
            df = pd.read_sql_query(
                "SELECT id, fecha, proveedor, total, metodo_pago FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 40",
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

    with t4:
        st.info("Al anular una venta se devuelve el stock.")
        with db() as conn:
            ventas = pd.read_sql_query(
                "SELECT id, fecha, total FROM ventas WHERE anulada = 0 ORDER BY fecha DESC LIMIT 25",
                conn
            )
        if ventas.empty:
            st.warning("No hay ventas para anular")
        else:
            opciones_ventas = [int(x) for x in ventas["id"].tolist()]
            venta_id = st.selectbox(
                "Venta",
                options=opciones_ventas,
                format_func=lambda x: f"#{x} — {money(float(ventas.loc[ventas['id']==x, 'total'].values[0]))}"
            )
            venta_id = to_int(venta_id)
            
            if st.checkbox("Confirmo anular esta venta"):
                if st.button("Anular Venta", type="primary"):
                    try:
                        with db() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT producto_id, cantidad, costo_unitario FROM venta_detalle WHERE venta_id = %s",
                                (venta_id,)
                            )
                            items = cur.fetchall()
                            cur.execute("UPDATE ventas SET anulada = 1 WHERE id = %s", (venta_id,))
                            for it in items:
                                cur.execute(
                                    "UPDATE productos SET stock = stock + %s WHERE id = %s",
                                    (it["cantidad"], it["producto_id"])
                                )
                                cur.execute("""
                                    INSERT INTO movimientos_stock
                                    (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'entrada', %s, %s, 'Anulación venta', %s)
                                """, (it["producto_id"], it["cantidad"], it["costo_unitario"], f"Anul Venta #{venta_id}"))
                        st.success("Venta anulada y stock devuelto")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    with t5:
        st.info("Al anular una compra se descuenta el stock.")
        with db() as conn:
            compras = pd.read_sql_query(
                "SELECT id, fecha, total FROM compras WHERE anulada = 0 ORDER BY fecha DESC LIMIT 25",
                conn
            )
        if compras.empty:
            st.warning("No hay compras para anular")
        else:
            opciones_compras = [int(x) for x in compras["id"].tolist()]
            compra_id = st.selectbox(
                "Compra",
                options=opciones_compras,
                format_func=lambda x: f"#{x} — {money(float(compras.loc[compras['id']==x, 'total'].values[0]))}"
            )
            compra_id = to_int(compra_id)
            
            if st.checkbox("Confirmo anular esta compra"):
                if st.button("Anular Compra", type="primary"):
                    try:
                        with db() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT producto_id, cantidad, costo_unitario FROM compra_detalle WHERE compra_id = %s",
                                (compra_id,)
                            )
                            items = cur.fetchall()

                            for it in items:
                                cur.execute("SELECT stock FROM productos WHERE id = %s", (it["producto_id"],))
                                stock_actual = to_float(cur.fetchone()["stock"])
                                if stock_actual < to_float(it["cantidad"]):
                                    st.error("No se puede anular: stock insuficiente")
                                    return

                            cur.execute("UPDATE compras SET anulada = 1 WHERE id = %s", (compra_id,))
                            for it in items:
                                cur.execute(
                                    "UPDATE productos SET stock = stock - %s WHERE id = %s",
                                    (it["cantidad"], it["producto_id"])
                                )
                                cur.execute("""
                                    INSERT INTO movimientos_stock
                                    (producto_id, tipo, cantidad, costo_unitario, motivo, referencia)
                                    VALUES (%s, 'salida', %s, %s, 'Anulación compra', %s)
                                """, (it["producto_id"], it["cantidad"], it["costo_unitario"], f"Anul Compra #{compra_id}"))
                        st.success("Compra anulada y stock actualizado")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

# ============================================================
# MAIN
# ============================================================
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
        pagina_resumen()
    elif opcion == "📦 Inventario":
        pagina_inventario()
    elif opcion == "🛒 Ventas":
        pagina_ventas()
    elif opcion == "📥 Compras":
        pagina_compras()
    elif opcion == "💸 Gastos":
        pagina_gastos()
    elif opcion == "📈 Reportes":
        pagina_reportes()
    elif opcion == "📜 Historial":
        pagina_historial()

if __name__ == "__main__":
    main()
