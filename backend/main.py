import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
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



# ---------- Gestionar inventario (caso de uso del Administrador) ----------
def admin_only(user=Depends(current_user)):
    if user["rol"] != "admin":
        raise HTTPException(403, "Esta operación requiere una cuenta de administrador.")
    return user


class MedicamentoIn(Entrada):
    id_laboratorio: int = Field(gt=0)
    id_categoria: int = Field(gt=0)
    nombre: str = Field(min_length=1, max_length=150)
    mg: Optional[int] = Field(default=None, gt=0, le=1_000_000)
    forma: Optional[str] = Field(default=None, min_length=1, max_length=50)
    requiere_formula: bool = False
    precio: Decimal = Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)


class MedicamentoNuevo(MedicamentoIn):
    stock_inicial: int = Field(default=0, ge=0, le=1_000_000, strict=True)


class AjusteStock(Entrada):
    cantidad: int = Field(ge=-1_000_000, le=1_000_000, strict=True)
    motivo: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def no_cero(self):
        if self.cantidad == 0:
            raise ValueError("La cantidad del ajuste no puede ser cero.")
        return self


class LaboratorioIn(Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    pais: Optional[str] = Field(default=None, min_length=1, max_length=50)


class CategoriaIn(Entrada):
    nombre: str = Field(min_length=1, max_length=100)


INVENTARIO = """
SELECT m.id_medicamento,m.nombre,m.mg,m.forma,m.requiere_formula,m.precio,m.activo,
       m.id_laboratorio,l.nombre AS laboratorio,m.id_categoria,c.nombre AS categoria,
       m.stock AS stock_fisico,v.reservado,v.disponible
FROM medicamentos m JOIN laboratorios l USING (id_laboratorio)
JOIN categorias c USING (id_categoria) JOIN v_stock_disponible v USING (id_medicamento)
"""


def medicamento_admin(db, id_medicamento):
    row = db.execute(INVENTARIO + " WHERE m.id_medicamento=%s", (id_medicamento,)).fetchone()
    if not row:
        raise HTTPException(404, "Medicamento no encontrado.")
    return row


@app.get("/api/inventario")
def inventario(user=Depends(admin_only), db=Depends(get_db)):
    return db.execute(INVENTARIO + " ORDER BY m.activo DESC, m.nombre").fetchall()


@app.get("/api/inventario/movimientos")
def movimientos(id_medicamento: Optional[int] = None, user=Depends(admin_only), db=Depends(get_db)):
    return db.execute("SELECT mv.id_movimiento,mv.fecha,mv.tipo,mv.cantidad,mv.motivo,m.nombre AS medicamento,"
                      "u.correo AS usuario FROM movimientos_inventario mv JOIN medicamentos m USING (id_medicamento) "
                      "LEFT JOIN usuarios u ON u.id_usuario=mv.id_usuario "
                      "WHERE %s::INT IS NULL OR mv.id_medicamento=%s ORDER BY mv.id_movimiento DESC LIMIT 100",
                      (id_medicamento, id_medicamento)).fetchall()


@app.post("/api/medicamentos", status_code=201)
def crear_medicamento(m: MedicamentoNuevo, user=Depends(admin_only), db=Depends(get_db)):
    try:
        with db.transaction():
            mid = db.execute("INSERT INTO medicamentos (id_laboratorio,id_categoria,nombre,mg,forma,requiere_formula,"
                             "stock,precio) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_medicamento",
                             (m.id_laboratorio, m.id_categoria, m.nombre, m.mg, m.forma, m.requiere_formula,
                              m.stock_inicial, m.precio)).fetchone()["id_medicamento"]
            if m.stock_inicial:
                db.execute("INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo) "
                           "VALUES (%s,%s,'entrada',%s,'Stock inicial')", (mid, user["id_usuario"], m.stock_inicial))
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "El laboratorio o la categoría no existen.")
    return medicamento_admin(db, mid)


@app.put("/api/medicamentos/{id_medicamento}")
def editar_medicamento(id_medicamento: int, m: MedicamentoIn, user=Depends(admin_only), db=Depends(get_db)):
    # El stock no se edita aquí: solo mediante ajustes que quedan registrados.
    try:
        with db.transaction():
            r = db.execute("UPDATE medicamentos SET id_laboratorio=%s,id_categoria=%s,nombre=%s,mg=%s,forma=%s,"
                           "requiere_formula=%s,precio=%s WHERE id_medicamento=%s RETURNING id_medicamento",
                           (m.id_laboratorio, m.id_categoria, m.nombre, m.mg, m.forma, m.requiere_formula,
                            m.precio, id_medicamento)).fetchone()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "El laboratorio o la categoría no existen.")
    if not r:
        raise HTTPException(404, "Medicamento no encontrado.")
    return medicamento_admin(db, id_medicamento)


@app.patch("/api/medicamentos/{id_medicamento}/stock")
def ajustar_stock(id_medicamento: int, a: AjusteStock, user=Depends(admin_only), db=Depends(get_db)):
    with db.transaction():
        # Mismo bloqueo que reservar_stock(): un ajuste y una venta no se cruzan.
        m = db.execute("SELECT stock FROM medicamentos WHERE id_medicamento=%s FOR UPDATE", (id_medicamento,)).fetchone()
        if not m:
            raise HTTPException(404, "Medicamento no encontrado.")
        reservado = db.execute("SELECT reservado FROM v_stock_disponible WHERE id_medicamento=%s",
                               (id_medicamento,)).fetchone()["reservado"]
        if m["stock"] + a.cantidad < reservado:
            raise HTTPException(409, f"El stock no puede quedar negativo ni por debajo de lo reservado ({reservado}).")
        db.execute("UPDATE medicamentos SET stock=stock+%s WHERE id_medicamento=%s", (a.cantidad, id_medicamento))
        db.execute("INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo) "
                   "VALUES (%s,%s,%s,%s,%s)", (id_medicamento, user["id_usuario"],
                                              "entrada" if a.cantidad > 0 else "ajuste", a.cantidad, a.motivo))
    return medicamento_admin(db, id_medicamento)


def cambiar_estado(db, id_medicamento, activo):
    r = db.execute("UPDATE medicamentos SET activo=%s WHERE id_medicamento=%s RETURNING id_medicamento",
                   (activo, id_medicamento)).fetchone()
    if not r:
        raise HTTPException(404, "Medicamento no encontrado.")
    return medicamento_admin(db, id_medicamento)


@app.delete("/api/medicamentos/{id_medicamento}")
def retirar_medicamento(id_medicamento: int, user=Depends(admin_only), db=Depends(get_db)):
    # Retiro lógico: los pedidos y comprobantes anteriores conservan su referencia.
    return cambiar_estado(db, id_medicamento, False)


@app.post("/api/medicamentos/{id_medicamento}/reactivar")
def reactivar_medicamento(id_medicamento: int, user=Depends(admin_only), db=Depends(get_db)):
    return cambiar_estado(db, id_medicamento, True)


@app.get("/api/laboratorios")
def laboratorios(user=Depends(admin_only), db=Depends(get_db)):
    return db.execute("SELECT * FROM laboratorios ORDER BY nombre").fetchall()


@app.post("/api/laboratorios", status_code=201)
def crear_laboratorio(lab: LaboratorioIn, user=Depends(admin_only), db=Depends(get_db)):
    try:
        return db.execute("INSERT INTO laboratorios (nombre,pais) VALUES (%s,%s) RETURNING *",
                          (lab.nombre, lab.pais)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Ese laboratorio ya existe.")


@app.get("/api/categorias")
def categorias(user=Depends(admin_only), db=Depends(get_db)):
    return db.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()


@app.post("/api/categorias", status_code=201)
def crear_categoria(c: CategoriaIn, user=Depends(admin_only), db=Depends(get_db)):
    try:
        return db.execute("INSERT INTO categorias (nombre) VALUES (%s) RETURNING *", (c.nombre,)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Esa categoría ya existe.")


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
        raise HTTPException(403, "El administrador gestiona inventario; las ventas las registran empleado o cliente.")
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
