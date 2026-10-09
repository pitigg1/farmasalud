import hashlib, hmac, os, secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
import psycopg
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DSN = os.getenv("DATABASE_URL", "postgresql://farmacia:farmacia@localhost:5432/farmacia")
SECRET = os.getenv("JWT_SECRET", "cambia-esto-en-produccion")
DEV_PASSWORD = "farmacia123"  # contraseña de desarrollo para los usuarios sembrados en farmaciadb.sql

app = FastAPI(title="API Farmacia", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def connect():
    # Todas las tablas viven en el esquema "farmacia" (ver farmaciadb.sql)
    return psycopg.connect(DSN, row_factory=dict_row, options="-c search_path=farmacia,public")


def get_db():
    with connect() as conn:  # commit al salir bien, rollback si hay excepción
        yield conn


def hash_pw(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def check_pw(pw: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    return hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)


@app.on_event("startup")
def fijar_hashes():
    """Los usuarios de farmaciadb.sql traen 'REEMPLAZAR_POR_HASH': les asigna la contraseña de desarrollo."""
    try:
        with connect() as c:
            for u in c.execute("SELECT id_usuario FROM usuarios WHERE password_hash='REEMPLAZAR_POR_HASH'").fetchall():
                c.execute("UPDATE usuarios SET password_hash=%s WHERE id_usuario=%s",
                          (hash_pw(DEV_PASSWORD), u["id_usuario"]))
    except Exception as e:
        print("Aviso: no se pudieron fijar las contraseñas de desarrollo:", e)


def current_user(authorization: str = Header(default="")):
    try:
        return jwt.decode(authorization.replace("Bearer ", "", 1), SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Inicia sesión para continuar.")


def admin_only(user=Depends(current_user)):
    if user.get("rol") != "admin":
        raise HTTPException(403, "Solo el administrador puede hacer esto.")
    return user


# ---------- Esquemas ----------
class Credenciales(BaseModel):
    correo: str = Field(pattern=r"^\S+@\S+\.\S+$")
    password: str = Field(min_length=4)


class ClienteIn(BaseModel):
    tipo_documento: str = Field(pattern="^(CC|CE|TI|PAS|NIT)$")
    documento: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    apellido: str = Field(min_length=1)
    correo: str = Field(pattern=r"^\S+@\S+\.\S+$")
    celular: str = Field(min_length=1)


class ItemIn(BaseModel):
    id_medicamento: int
    cantidad: int = Field(gt=0)
    numero_formula: Optional[str] = None


class PedidoIn(BaseModel):
    cliente: ClienteIn
    direccion: str = Field(min_length=1)
    metodo_pago: str
    items: List[ItemIn] = Field(min_length=1)


class MedIn(BaseModel):
    nombre: str = Field(min_length=1)
    mg: Optional[int] = Field(default=None, gt=0)
    forma: Optional[str] = None
    id_categoria: int
    id_laboratorio: int
    precio: float = Field(ge=0)
    stock: int = Field(default=0, ge=0)
    requiere_formula: bool = False


class StockIn(BaseModel):
    delta: int
    motivo: Optional[str] = None


# ---------- Autenticación ----------
def token_for(u) -> dict:
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    tok = jwt.encode({"sub": str(u["id_usuario"]), "rol": u["rol"], "exp": exp}, SECRET, "HS256")
    return {"token": tok, "correo": u["correo"], "rol": u["rol"]}


@app.post("/api/auth/register", status_code=201)
def register(c: Credenciales, db=Depends(get_db)):
    try:
        u = db.execute("INSERT INTO usuarios (correo, password_hash, rol) VALUES (%s,%s,'cliente') RETURNING *",
                       (c.correo.lower(), hash_pw(c.password))).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Ese correo ya está registrado.")
    return token_for(u)


@app.post("/api/auth/login")
def login(c: Credenciales, db=Depends(get_db)):
    u = db.execute("SELECT * FROM usuarios WHERE correo=%s AND activo", (c.correo.lower(),)).fetchone()
    if not u or not check_pw(c.password, u["password_hash"]):
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    return token_for(u)


# ---------- Catálogo e inventario ----------
CATALOGO = """
SELECT m.id_medicamento,
       m.nombre || COALESCE(' ' || m.mg || 'mg', '') AS nombre,
       m.nombre AS nombre_base, m.mg, m.forma AS presentacion, m.precio, m.requiere_formula,
       m.stock AS stock_fisico, v.disponible AS stock,
       c.nombre AS categoria, l.nombre AS laboratorio, m.id_categoria, m.id_laboratorio,
       CASE WHEN m.requiere_formula THEN 'Requiere Receta' WHEN v.disponible <= 5 THEN 'Bajo Stock' END AS etiqueta
FROM medicamentos m
JOIN categorias c ON c.id_categoria = m.id_categoria
JOIN laboratorios l ON l.id_laboratorio = m.id_laboratorio
JOIN v_stock_disponible v ON v.id_medicamento = m.id_medicamento
WHERE m.activo AND m.nombre ILIKE %s
ORDER BY m.nombre
"""


@app.get("/api/medicamentos")
def medicamentos(q: str = "", db=Depends(get_db)):
    return db.execute(CATALOGO, (f"%{q}%",)).fetchall()


@app.get("/api/catalogos")
def catalogos(db=Depends(get_db)):
    return {"categorias": db.execute("SELECT * FROM categorias ORDER BY nombre").fetchall(),
            "laboratorios": db.execute("SELECT * FROM laboratorios ORDER BY nombre").fetchall()}


@app.post("/api/medicamentos", status_code=201)
def crear_medicamento(m: MedIn, user=Depends(admin_only), db=Depends(get_db)):
    try:
        with db.transaction():
            r = db.execute(
                "INSERT INTO medicamentos (id_laboratorio,id_categoria,nombre,mg,forma,requiere_formula,stock,precio) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_medicamento",
                (m.id_laboratorio, m.id_categoria, m.nombre, m.mg, m.forma, m.requiere_formula, m.stock, m.precio)).fetchone()
            if m.stock > 0:
                db.execute("INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo) "
                           "VALUES (%s,%s,'entrada',%s,'Alta de medicamento')", (r["id_medicamento"], int(user["sub"]), m.stock))
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "Categoría o laboratorio inválido.")
    return r


@app.patch("/api/medicamentos/{id_medicamento}/stock")
def ajustar_stock(id_medicamento: int, s: StockIn, user=Depends(admin_only), db=Depends(get_db)):
    if s.delta == 0:
        raise HTTPException(422, "El ajuste no puede ser 0.")
    try:
        with db.transaction():
            r = db.execute("UPDATE medicamentos SET stock = stock + %s WHERE id_medicamento=%s AND activo RETURNING stock",
                           (s.delta, id_medicamento)).fetchone()
            if not r:
                raise HTTPException(404, "Medicamento no encontrado.")
            db.execute("INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo) VALUES (%s,%s,%s,%s,%s)",
                       (id_medicamento, int(user["sub"]), "entrada" if s.delta > 0 else "salida", abs(s.delta), s.motivo))
    except psycopg.errors.CheckViolation:
        raise HTTPException(409, "El stock no puede quedar negativo.")
    return r


@app.delete("/api/medicamentos/{id_medicamento}")
def quitar_medicamento(id_medicamento: int, user=Depends(admin_only), db=Depends(get_db)):
    # Baja lógica: conserva el historial de pedidos que ya lo incluyen
    r = db.execute("UPDATE medicamentos SET activo=FALSE WHERE id_medicamento=%s AND activo RETURNING id_medicamento",
                   (id_medicamento,)).fetchone()
    if not r:
        raise HTTPException(404, "Medicamento no encontrado.")
    return {"ok": True}


# ---------- Pedido: usa reservar_stock() y confirmar_pedido() de la base de datos ----------
@app.post("/api/pedidos", status_code=201)
def crear_pedido(p: PedidoIn, user=Depends(current_user), db=Depends(get_db)):
    ids = sorted({i.id_medicamento for i in p.items})
    try:
        with db.transaction():  # cualquier excepción dentro hace rollback de todo
            db.execute("SELECT liberar_reservas_vencidas()")
            meds = {m["id_medicamento"]: m for m in db.execute(
                "SELECT id_medicamento, nombre, requiere_formula FROM medicamentos WHERE id_medicamento = ANY(%s) AND activo",
                (ids,)).fetchall()}
            for it in p.items:
                m = meds.get(it.id_medicamento)
                if not m:
                    raise HTTPException(404, "Un medicamento del carrito ya no está disponible.")
                if m["requiere_formula"] and not (it.numero_formula or "").strip():
                    raise HTTPException(422, f"{m['nombre']} requiere número de fórmula.")

            c = p.cliente
            cli = db.execute("SELECT id_cliente FROM clientes WHERE id_usuario=%s", (int(user["sub"]),)).fetchone()
            if cli:
                db.execute("UPDATE clientes SET nombre=%s, apellido=%s, correo=%s, celular=%s WHERE id_cliente=%s",
                           (c.nombre, c.apellido, c.correo, c.celular, cli["id_cliente"]))
            else:
                cli = db.execute(
                    "INSERT INTO clientes (id_usuario,nombre,apellido,tipo_documento,documento,correo,celular) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tipo_documento, documento) DO UPDATE SET "
                    "nombre=EXCLUDED.nombre, apellido=EXCLUDED.apellido, correo=EXCLUDED.correo, celular=EXCLUDED.celular, "
                    "id_usuario=COALESCE(clientes.id_usuario, EXCLUDED.id_usuario) RETURNING id_cliente",
                    (int(user["sub"]), c.nombre, c.apellido, c.tipo_documento, c.documento, c.correo, c.celular)).fetchone()
            cid = cli["id_cliente"]

            # Limpia reservas activas previas del cliente y reserva lo del carrito (orden fijo evita deadlocks)
            db.execute("UPDATE reservas SET estado='no_activa' WHERE id_cliente=%s AND estado='activa'", (cid,))
            for it in sorted(p.items, key=lambda i: i.id_medicamento):
                db.execute("SELECT reservar_stock(%s,%s,%s)", (cid, it.id_medicamento, it.cantidad))
            pid = db.execute("SELECT confirmar_pedido(%s, NULL, %s, %s) AS id",
                             (cid, p.direccion, p.metodo_pago)).fetchone()["id"]

            for it in p.items:  # las fórmulas quedan pendientes de verificar por un empleado (valida = false)
                if meds[it.id_medicamento]["requiere_formula"]:
                    db.execute("INSERT INTO formulas (id_pedido,id_medicamento,medico,numero_formula,fecha_emision,fecha_vence,valida) "
                               "VALUES (%s,%s,'Por verificar',%s,CURRENT_DATE,CURRENT_DATE + 30,FALSE)",
                               (pid, it.id_medicamento, it.numero_formula.strip()))
            total = db.execute("SELECT total FROM pedidos WHERE id_pedido=%s", (pid,)).fetchone()["total"]
            items = db.execute("SELECT m.nombre, d.cantidad, d.precio_unitario AS precio FROM detalles_pedido d "
                               "JOIN medicamentos m ON m.id_medicamento=d.id_medicamento WHERE d.id_pedido=%s", (pid,)).fetchall()
    except psycopg.errors.RaiseException as e:  # mensajes de reservar_stock / confirmar_pedido
        raise HTTPException(409, e.diag.message_primary or "No se pudo completar el pedido.")
    return {"id_pedido": pid, "total": total, "items": items}
