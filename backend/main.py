import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional
from uuid import UUID

import jwt
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

DSN = os.getenv("DATABASE_URL", "postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia")
SECRET = os.getenv("JWT_SECRET", "cambia-esto-en-produccion")
DEV_PASSWORD = "farmacia123"
app = FastAPI(title="API FarmaSalud", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def connect():
    # Las escrituras usan transacciones explícitas: commit ANTES de responder éxito.
    return psycopg.connect(DSN, autocommit=True, row_factory=dict_row,
                           options="-c search_path=farmacia,public -c timezone=America/Bogota")


def get_db():
    with connect() as conn:
        yield conn


def hash_pw(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def check_pw(pw: str, stored: str) -> bool:
    return "$" in stored and hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)


@app.on_event("startup")
def fijar_hashes():
    # Solo sustituye los marcadores de las cuentas de demostración.
    with connect() as db, db.transaction():
        db.execute("SELECT clave_operacion, comprobante FROM pedidos LIMIT 0")
        for u in db.execute("SELECT id_usuario FROM usuarios WHERE password_hash='REEMPLAZAR_POR_HASH'").fetchall():
            db.execute("UPDATE usuarios SET password_hash=%s WHERE id_usuario=%s",
                       (hash_pw(DEV_PASSWORD), u["id_usuario"]))


def current_user(authorization: str = Header(default=""), db=Depends(get_db)):
    try:
        if not authorization.startswith("Bearer "):
            raise ValueError()
        claims = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"],
                            options={"require": ["sub", "exp"]})
        uid = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Inicia sesión para continuar.")
    # Los permisos y el estado se consultan en la BD, no en un selector del navegador.
    user = db.execute("SELECT id_usuario,correo,rol FROM usuarios WHERE id_usuario=%s AND activo", (uid,)).fetchone()
    if not user:
        raise HTTPException(401, "La cuenta no está activa.")
    return user


def empleado_only(user=Depends(current_user)):
    if user["rol"] != "empleado":
        raise HTTPException(403, "Esta operación requiere una cuenta de empleado.")
    return user


class Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Credenciales(Entrada):
    correo: str = Field(pattern=r"^\S+@\S+\.\S+$", max_length=100)
    password: str = Field(min_length=4, max_length=128)


class ClienteIn(Entrada):
    tipo_documento: Literal["CC", "CE", "TI", "PAS", "NIT"]
    documento: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=100)
    apellido: str = Field(min_length=1, max_length=100)
    correo: str = Field(pattern=r"^\S+@\S+\.\S+$", max_length=100)
    celular: str = Field(min_length=1, max_length=20)


class ItemIn(Entrada):
    id_medicamento: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=1_000_000, strict=True)
    numero_formula: Optional[str] = Field(default=None, min_length=1, max_length=50)
    medico: Optional[str] = Field(default=None, min_length=1, max_length=100)
    fecha_emision: Optional[date] = None
    fecha_vence: Optional[date] = None
    formula_verificada: bool = False


class PedidoIn(Entrada):
    clave_operacion: UUID
    cliente: Optional[ClienteIn] = None
    id_cliente: Optional[int] = Field(default=None, gt=0)
    direccion: str = Field(default="Venta presencial", min_length=1, max_length=200)
    metodo_pago: Literal["Efectivo", "Datafono", "Nequi/PSE"]
    items: List[ItemIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def sin_repetidos(self):
        ids = [it.id_medicamento for it in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Cada medicamento debe aparecer una sola vez.")
        return self


def token_for(u):
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    tok = jwt.encode({"sub": str(u["id_usuario"]), "exp": exp}, SECRET, "HS256")
    return {"token": tok, "correo": u["correo"], "rol": u["rol"]}


@app.post("/api/auth/register", status_code=201)
def register(c: Credenciales, db=Depends(get_db)):
    try:
        with db.transaction():
            u = db.execute("INSERT INTO usuarios (correo,password_hash,rol) VALUES (%s,%s,'cliente') RETURNING *",
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


@app.get("/api/salud")
def salud(db=Depends(get_db)):
    return db.execute("SELECT current_database() AS base_datos,current_schema() AS esquema, "
                      "(SELECT count(*) FROM medicamentos) AS medicamentos").fetchone()


CATALOGO = """
SELECT m.id_medicamento,m.nombre || COALESCE(' ' || m.mg || 'mg', '') AS nombre,
       m.forma AS presentacion,m.precio,m.requiere_formula,m.stock AS stock_fisico,
       v.disponible AS stock,c.nombre AS categoria,l.nombre AS laboratorio,
       CASE WHEN m.requiere_formula THEN 'Requiere Receta'
            WHEN v.disponible <= 5 THEN 'Bajo Stock' END AS etiqueta
FROM medicamentos m JOIN categorias c USING (id_categoria)
JOIN laboratorios l USING (id_laboratorio) JOIN v_stock_disponible v USING (id_medicamento)
WHERE m.activo AND m.nombre ILIKE %s ORDER BY m.nombre
"""


@app.get("/api/medicamentos")
def medicamentos(q: str = "", db=Depends(get_db)):
    return db.execute(CATALOGO, (f"%{q}%",)).fetchall()


@app.get("/api/clientes/yo")
def mi_cliente(user=Depends(current_user), db=Depends(get_db)):
    if user["rol"] != "cliente":
        raise HTTPException(403, "Solo para cuentas de cliente.")
    return db.execute("SELECT * FROM clientes WHERE id_usuario=%s", (user["id_usuario"],)).fetchone()


@app.get("/api/clientes")
def clientes(documento: str, tipo_documento: str = "CC", user=Depends(empleado_only), db=Depends(get_db)):
    return db.execute("SELECT * FROM clientes WHERE tipo_documento=%s AND documento=%s",
                      (tipo_documento, documento.strip())).fetchall()


@app.post("/api/clientes", status_code=201)
def crear_cliente(c: ClienteIn, user=Depends(empleado_only), db=Depends(get_db)):
    try:
        with db.transaction():
            return db.execute("INSERT INTO clientes (tipo_documento,documento,nombre,apellido,correo,celular) "
                              "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                              (c.tipo_documento, c.documento, c.nombre, c.apellido, c.correo, c.celular)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "El documento ya está registrado. Busca y selecciona ese cliente.")


@app.get("/api/pedidos")
def pedidos(user=Depends(current_user), db=Depends(get_db)):
    return db.execute("SELECT p.id_pedido,p.fecha_pedido,p.estado,p.total,p.id_cliente,p.id_empleado, "
                      "COALESCE(p.comprobante->'cliente'->>'nombre',c.nombre || ' ' || c.apellido) AS cliente, "
                      "COALESCE(p.comprobante->>'empleado',u.correo) AS empleado "
                      "FROM pedidos p JOIN clientes c USING (id_cliente) "
                      "LEFT JOIN usuarios u ON u.id_usuario=p.id_empleado "
                      "WHERE (%s IN ('empleado','admin') OR c.id_usuario=%s) ORDER BY p.id_pedido DESC",
                      (user["rol"], user["id_usuario"])).fetchall()


@app.get("/api/pedidos/{id_pedido}/comprobante")
def comprobante(id_pedido: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT p.comprobante FROM pedidos p JOIN clientes c USING (id_cliente) "
                     "WHERE p.id_pedido=%s AND (%s IN ('empleado','admin') OR c.id_usuario=%s)",
                     (id_pedido, user["rol"], user["id_usuario"])).fetchone()
    if not row:
        raise HTTPException(404, "Comprobante no encontrado.")
    return row["comprobante"]


def cliente_de_compra(p, user, db):
    if user["rol"] == "empleado":
        if not p.id_cliente or p.cliente is not None:
            raise HTTPException(422, "Selecciona un cliente existente para la venta.")
        cli = db.execute("SELECT * FROM clientes WHERE id_cliente=%s FOR UPDATE", (p.id_cliente,)).fetchone()
        if not cli:
            raise HTTPException(404, "Cliente no encontrado.")
        return cli
    if user["rol"] != "cliente":
        raise HTTPException(403, "El administrador solo consulta ventas e inventario.")
    if p.id_cliente is not None or p.cliente is None:
        raise HTTPException(422, "Completa tus datos de cliente.")
    c = p.cliente
    # Serializa compras de la misma cuenta antes de buscar o crear su perfil.
    db.execute("SELECT id_usuario FROM usuarios WHERE id_usuario=%s FOR UPDATE", (user["id_usuario"],))
    cli = db.execute("SELECT * FROM clientes WHERE id_usuario=%s FOR UPDATE", (user["id_usuario"],)).fetchone()
    if cli:
        if (cli["tipo_documento"], cli["documento"]) != (c.tipo_documento, c.documento):
            raise HTTPException(409, "El documento no coincide con tu perfil registrado.")
        return db.execute("UPDATE clientes SET nombre=%s,apellido=%s,correo=%s,celular=%s "
                          "WHERE id_cliente=%s RETURNING *", (c.nombre, c.apellido, c.correo, c.celular, cli["id_cliente"])).fetchone()
    if db.execute("SELECT 1 FROM clientes WHERE tipo_documento=%s AND documento=%s",
                  (c.tipo_documento, c.documento)).fetchone():
        raise HTTPException(409, "Ese documento ya está registrado. Solicita atención del empleado.")
    return db.execute("INSERT INTO clientes (id_usuario,tipo_documento,documento,nombre,apellido,correo,celular) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                      (user["id_usuario"], c.tipo_documento, c.documento, c.nombre, c.apellido, c.correo, c.celular)).fetchone()


@app.post("/api/pedidos", status_code=201)
def crear_pedido(p: PedidoIn, user=Depends(current_user), db=Depends(get_db)):
    huella = hashlib.sha256(json.dumps(p.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        with db.transaction():
            # Un reintento con la misma clave espera y devuelve la venta original.
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(p.clave_operacion),))
            anterior = db.execute("SELECT id_usuario_operacion,solicitud_hash,comprobante FROM pedidos "
                                  "WHERE clave_operacion=%s", (p.clave_operacion,)).fetchone()
            if anterior:
                if anterior["id_usuario_operacion"] != user["id_usuario"] or anterior["solicitud_hash"] != huella:
                    raise HTTPException(409, "La clave de operación ya se usó con otra solicitud.")
                return anterior["comprobante"]
            cli = cliente_de_compra(p, user, db)
            cid = cli["id_cliente"]
            ids = sorted(it.id_medicamento for it in p.items)
            # Orden fijo de bloqueo; ni precios ni totales se aceptan del navegador.
            meds = {m["id_medicamento"]: m for m in db.execute(
                "SELECT * FROM medicamentos WHERE id_medicamento=ANY(%s) AND activo "
                "ORDER BY id_medicamento FOR UPDATE", (ids,)).fetchall()}
            formulas = []
            hoy = db.execute("SELECT CURRENT_DATE AS hoy").fetchone()["hoy"]
            for it in p.items:
                m = meds.get(it.id_medicamento)
                if not m:
                    raise HTTPException(404, "Un medicamento ya no está disponible.")
                if m["requiere_formula"]:
                    if user["rol"] != "empleado":
                        raise HTTPException(422, f"{m['nombre']} requiere venta asistida y verificación del empleado.")
                    if not (it.formula_verificada and it.numero_formula and it.medico and
                            it.fecha_emision and it.fecha_vence and it.fecha_emision <= hoy <= it.fecha_vence):
                        raise HTTPException(422, "Verifica la fórmula: número, médico y fechas vigentes son obligatorios.")
                    formulas.append(it.model_dump(mode="json"))
            # El bloqueo del cliente evita mezclar sus reservas en compras simultáneas.
            db.execute("UPDATE reservas SET estado='no_activa' WHERE id_cliente=%s AND estado='activa'", (cid,))
            for it in sorted(p.items, key=lambda x: x.id_medicamento):
                db.execute("SELECT reservar_stock(%s,%s,%s)", (cid, it.id_medicamento, it.cantidad))
            empleado = user["id_usuario"] if user["rol"] == "empleado" else None
            pid = db.execute("SELECT confirmar_pedido(%s,%s,%s,%s,%s) AS id",
                             (cid, empleado, p.direccion, p.metodo_pago, Jsonb(formulas))).fetchone()["id"]
            result = db.execute("UPDATE pedidos SET clave_operacion=%s,id_usuario_operacion=%s,solicitud_hash=%s, "
                                "comprobante=snapshot_pedido(id_pedido) WHERE id_pedido=%s RETURNING comprobante",
                                (p.clave_operacion, user["id_usuario"], huella, pid)).fetchone()["comprobante"]
        # Venta, descuento y comprobante ya fueron confirmados juntos.
        return result
    except psycopg.errors.RaiseException as e:
        raise HTTPException(409, e.diag.message_primary or "No se pudo completar la venta.")
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "El cliente o la operación ya están registrados. Actualiza los datos.")
    except psycopg.errors.CheckViolation:
        raise HTTPException(409, "No se pudo completar la venta: revisa las cantidades disponibles.")
