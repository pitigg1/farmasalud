import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Literal, Optional
from uuid import UUID

import jwt
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

DSN = os.getenv("DATABASE_URL", "postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia")
log = logging.getLogger("uvicorn.error")

# Clave para firmar los tokens JWT. Sin variable de entorno se genera una aleatoria
# (las sesiones se cierran al reiniciar la API). Nunca se usa un valor fijo del código.
SECRET = os.getenv("JWT_SECRET", "")
if not SECRET:
    SECRET = secrets.token_urlsafe(32)
    log.warning("JWT_SECRET no está definida: se usa una clave temporal aleatoria.")
elif len(SECRET) < 32:
    raise RuntimeError("JWT_SECRET debe tener al menos 32 caracteres. Genera una con: "
                       "python -c \"import secrets; print(secrets.token_urlsafe(32))\"")

# Contraseña inicial de las cuentas precargadas (marcador REEMPLAZAR_POR_HASH en schema.sql).
CLAVE_INICIAL = os.getenv("CLAVE_INICIAL", "")
CLAVE_DEMO_ANTIGUA = "farmacia123"  # solo para advertir si una cuenta aún la usa
# Contraseñas iniciales fijas de las cuentas precargadas (documentadas en el README).
# Se asignan una sola vez, sobre una base nueva; cada usuario debe cambiarla después.
CLAVES_INICIALES = {
    "admin@farmacia.com": "Admin2026*",
    "empleado@farmacia.com": "Empleado2026*",
    "cliente@mail.com": "Cliente2026*",
}
CLAVE_INICIAL_GENERAL = "FarmaSalud2026*"  # cualquier otra cuenta precargada con el marcador
app = FastAPI(title="API FarmaSalud", version="0.3.0")
# Orígenes permitidos (separados por comas). En producción el frontend lo sirve esta misma API,
# así que solo hace falta si el frontend se publica en otro dominio.
ORIGENES = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGENES, allow_methods=["*"], allow_headers=["*"])


def connect():
    # Las escrituras usan transacciones explícitas: commit ANTES de responder éxito.
    # search_path y zona horaria se fijan con SET (el pooler de Supabase no acepta "options").
    conn = psycopg.connect(DSN, autocommit=True, row_factory=dict_row, prepare_threshold=None)
    try:
        conn.execute("SET search_path TO farmacia, public; SET timezone TO 'America/Bogota'")
    except Exception:
        conn.close()
        raise
    return conn


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
    # Solo sustituye los marcadores de las cuentas precargadas; no toca contraseñas ya definidas.
    with connect() as db, db.transaction():
        db.execute("SELECT clave_operacion, comprobante FROM pedidos LIMIT 0")
        pendientes = db.execute("SELECT id_usuario,correo FROM usuarios "
                                "WHERE password_hash='REEMPLAZAR_POR_HASH'").fetchall()
        if CLAVE_INICIAL and (len(CLAVE_INICIAL) < 8 or CLAVE_INICIAL.lower() == CLAVE_DEMO_ANTIGUA):
            raise RuntimeError("CLAVE_INICIAL debe tener al menos 8 caracteres y no ser farmacia123.")
        for u in pendientes:
            # CLAVE_INICIAL (si se configura) reemplaza las contraseñas iniciales documentadas.
            clave = CLAVE_INICIAL or CLAVES_INICIALES.get(u["correo"], CLAVE_INICIAL_GENERAL)
            db.execute("UPDATE usuarios SET password_hash=%s WHERE id_usuario=%s", (hash_pw(clave), u["id_usuario"]))
        if pendientes and not CLAVE_INICIAL:
            log.warning("Cuentas %s creadas con las contraseñas iniciales del README: cámbialas al iniciar sesión.",
                        ", ".join(u["correo"] for u in pendientes))
        for u in db.execute("SELECT correo,password_hash FROM usuarios WHERE activo "
                            "AND (rol IN ('admin','empleado') OR correo='cliente@mail.com')").fetchall():
            if check_pw(CLAVE_DEMO_ANTIGUA, u["password_hash"]):
                log.warning("La cuenta %s todavía usa la contraseña de demostración: cámbiala.", u["correo"])


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
    password: str = Field(min_length=1, max_length=128)


class Registro(Credenciales):
    password: str = Field(min_length=8, max_length=128)


class CambioClave(Entrada):
    actual: str = Field(min_length=1, max_length=128)
    nueva: str = Field(min_length=8, max_length=128)


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
def register(c: Registro, db=Depends(get_db)):
    if c.password.lower() == CLAVE_DEMO_ANTIGUA:
        raise HTTPException(422, "Elige una contraseña diferente.")
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


@app.post("/api/auth/cambiar-clave", status_code=204)
def cambiar_clave(c: CambioClave, user=Depends(current_user), db=Depends(get_db)):
    actual = db.execute("SELECT password_hash FROM usuarios WHERE id_usuario=%s", (user["id_usuario"],)).fetchone()
    if not check_pw(c.actual, actual["password_hash"]):
        raise HTTPException(400, "La contraseña actual no es correcta.")
    if c.nueva == c.actual or c.nueva.lower() == CLAVE_DEMO_ANTIGUA:
        raise HTTPException(422, "Elige una contraseña nueva y diferente.")
    db.execute("UPDATE usuarios SET password_hash=%s WHERE id_usuario=%s", (hash_pw(c.nueva), user["id_usuario"]))


@app.get("/api/salud")
def salud(db=Depends(get_db)):
    return db.execute("SELECT current_database() AS base_datos,current_schema() AS esquema, "
                      "(SELECT count(*) FROM medicamentos) AS medicamentos").fetchone()


CATALOGO = """
SELECT m.id_medicamento,m.nombre || COALESCE(' ' || m.mg || 'mg', '') AS nombre,
       m.forma AS presentacion,m.imagen_url,m.precio,m.requiere_formula,m.stock AS stock_fisico,
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
SELECT m.id_medicamento,m.nombre,m.mg,m.forma,m.requiere_formula,m.precio,m.activo,m.imagen_url,
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


# ---------- Foto del medicamento (columna imagen_url) ----------
# Con SUPABASE_URL y SUPABASE_SERVICE_KEY el archivo va a Supabase Storage (bucket público);
# sin ellas se guarda en IMAGENES_DIR (desarrollo local y pruebas).
IMAGENES_DIR = Path(os.getenv("IMAGENES_DIR", str(Path(__file__).resolve().parent / "imagenes")))
IMAGEN_MAX_BYTES = 2 * 1024 * 1024
IMAGEN_URL = "/api/imagenes/"
IMAGEN_NOMBRE = re.compile(r"^\d+-[0-9a-f]{16}\.(jpg|png|webp)$")
IMAGEN_TIPOS = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "medicamentos")


def usa_storage() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def url_publica_storage() -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/"


def storage(metodo: str, nombre: str, data: Optional[bytes] = None, tipo: Optional[str] = None):
    req = urllib.request.Request(f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{nombre}",
                                 data=data, method=metodo)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("apikey", SUPABASE_KEY)
    if tipo:
        req.add_header("Content-Type", tipo)
        req.add_header("Cache-Control", "86400")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def escribir_archivo(nombre: str, data: bytes) -> str:
    if usa_storage():
        try:
            storage("POST", nombre, data, IMAGEN_TIPOS[nombre.rsplit(".", 1)[1]])
        except (urllib.error.URLError, TimeoutError) as e:
            log.error("No se pudo subir la foto a Supabase Storage: %s", e)
            raise HTTPException(502, "No se pudo guardar la foto. Intenta de nuevo.")
        return url_publica_storage() + nombre
    IMAGENES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGENES_DIR / nombre).write_bytes(data)
    return IMAGEN_URL + nombre


def borrar_nombre(nombre: str):
    if not IMAGEN_NOMBRE.match(nombre):
        return
    if usa_storage():
        try:
            storage("DELETE", nombre)
        except (urllib.error.URLError, TimeoutError) as e:
            log.warning("No se pudo borrar %s de Supabase Storage: %s", nombre, e)
    else:
        (IMAGENES_DIR / nombre).unlink(missing_ok=True)


def tipo_imagen(data: bytes) -> Optional[str]:
    # Se identifica por el contenido real del archivo, no por su nombre ni por el encabezado.
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def borrar_archivo_imagen(url: Optional[str]):
    prefijo = url_publica_storage() if usa_storage() else IMAGEN_URL
    borrar_nombre(url[len(prefijo):] if url and url.startswith(prefijo) else "")


def guardar_imagen(db, id_medicamento: int, data: bytes, ext: str):
    nombre = f"{id_medicamento}-{secrets.token_hex(8)}.{ext}"
    with db.transaction():
        actual = db.execute("SELECT imagen_url FROM medicamentos WHERE id_medicamento=%s FOR UPDATE",
                            (id_medicamento,)).fetchone()
        if not actual:
            raise HTTPException(404, "Medicamento no encontrado.")
        url = escribir_archivo(nombre, data)
        try:
            db.execute("UPDATE medicamentos SET imagen_url=%s WHERE id_medicamento=%s", (url, id_medicamento))
        except Exception:
            borrar_nombre(nombre)
            raise
    borrar_archivo_imagen(actual["imagen_url"])  # solo después de confirmar el cambio
    return medicamento_admin(db, id_medicamento)


@app.put("/api/medicamentos/{id_medicamento}/imagen")
async def subir_imagen(id_medicamento: int, request: Request, user=Depends(admin_only), db=Depends(get_db)):
    data = bytearray()
    async for parte in request.stream():
        data += parte
        if len(data) > IMAGEN_MAX_BYTES:
            raise HTTPException(413, "La foto no puede superar 2 MB.")
    ext = tipo_imagen(bytes(data[:16]))
    if not ext:
        raise HTTPException(415, "La foto debe ser JPG, PNG o WebP.")
    return await run_in_threadpool(guardar_imagen, db, id_medicamento, bytes(data), ext)


@app.delete("/api/medicamentos/{id_medicamento}/imagen")
def quitar_imagen(id_medicamento: int, user=Depends(admin_only), db=Depends(get_db)):
    with db.transaction():
        actual = db.execute("SELECT imagen_url FROM medicamentos WHERE id_medicamento=%s FOR UPDATE",
                            (id_medicamento,)).fetchone()
        if not actual:
            raise HTTPException(404, "Medicamento no encontrado.")
        db.execute("UPDATE medicamentos SET imagen_url=NULL WHERE id_medicamento=%s", (id_medicamento,))
    borrar_archivo_imagen(actual["imagen_url"])
    return medicamento_admin(db, id_medicamento)


@app.get("/api/imagenes/{nombre}")
def ver_imagen(nombre: str):
    ruta = IMAGENES_DIR / nombre
    if not IMAGEN_NOMBRE.match(nombre) or not ruta.is_file():
        raise HTTPException(404, "Imagen no encontrada.")
    return FileResponse(ruta, media_type=IMAGEN_TIPOS[nombre.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


# ---------- Generar informe de inventario y ventas (caso de uso del Administrador) ----------
VENDIDOS = "p.estado IN ('confirmado','entregado') AND p.fecha_pedido BETWEEN %(desde)s AND %(hasta)s"


@app.get("/api/informes")
def informe(desde: Optional[date] = None, hasta: Optional[date] = None,
            umbral: int = Query(default=10, ge=0, le=100_000), user=Depends(admin_only), db=Depends(get_db)):
    hoy = db.execute("SELECT CURRENT_DATE AS hoy").fetchone()["hoy"]
    hasta = hasta or hoy
    desde = desde or hasta - timedelta(days=29)
    if desde > hasta:
        raise HTTPException(422, "La fecha inicial no puede ser posterior a la final.")
    if (hasta - desde).days > 366:
        raise HTTPException(422, "El periodo del informe no puede superar un año.")
    q = {"desde": desde, "hasta": hasta, "umbral": umbral}
    with db.transaction():
        # Una sola instantánea de la BD para que todas las cifras del informe cuadren entre sí.
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        resumen = db.execute(
            "SELECT COUNT(*) AS pedidos, COALESCE(SUM(p.total),0) AS total_vendido, "
            "COALESCE(ROUND(AVG(p.total),2),0) AS ticket_promedio, "
            "COALESCE((SELECT SUM(d.cantidad) FROM detalles_pedido d JOIN pedidos p USING (id_pedido) WHERE " + VENDIDOS + "),0) AS unidades, "
            "COUNT(DISTINCT p.id_cliente) AS clientes "
            "FROM pedidos p WHERE " + VENDIDOS, q).fetchone()
        por_dia = db.execute(
            "SELECT p.fecha_pedido AS fecha, COUNT(*) AS pedidos, SUM(p.total) AS total "
            "FROM pedidos p WHERE " + VENDIDOS + " GROUP BY p.fecha_pedido ORDER BY p.fecha_pedido", q).fetchall()
        por_canal = db.execute(
            "SELECT CASE WHEN p.id_empleado IS NULL THEN 'En línea (cliente)' ELSE 'Presencial (empleado)' END AS canal, "
            "COUNT(*) AS pedidos, SUM(p.total) AS total FROM pedidos p WHERE " + VENDIDOS +
            " GROUP BY 1 ORDER BY total DESC", q).fetchall()
        por_metodo = db.execute(
            "SELECT COALESCE(p.metodo_pago,'Sin registrar') AS metodo_pago, COUNT(*) AS pedidos, SUM(p.total) AS total "
            "FROM pedidos p WHERE " + VENDIDOS + " GROUP BY 1 ORDER BY total DESC", q).fetchall()
        mas_vendidos = db.execute(
            "SELECT m.id_medicamento, m.nombre || COALESCE(' ' || m.mg || 'mg','') AS nombre, "
            "SUM(d.cantidad) AS unidades, SUM(d.cantidad*d.precio_unitario) AS ingresos "
            "FROM detalles_pedido d JOIN pedidos p USING (id_pedido) JOIN medicamentos m USING (id_medicamento) "
            "WHERE " + VENDIDOS + " GROUP BY m.id_medicamento ORDER BY unidades DESC, ingresos DESC LIMIT 10", q).fetchall()
        inventario = db.execute(
            "SELECT m.id_medicamento, m.nombre || COALESCE(' ' || m.mg || 'mg','') AS nombre, c.nombre AS categoria, "
            "m.precio, v.stock_fisico, v.reservado, v.disponible, m.stock*m.precio AS valor, "
            "v.disponible <= %(umbral)s AS bajo_stock "
            "FROM medicamentos m JOIN categorias c USING (id_categoria) JOIN v_stock_disponible v USING (id_medicamento) "
            "WHERE m.activo ORDER BY v.disponible, m.nombre", q).fetchall()
    return {
        "periodo": {"desde": desde, "hasta": hasta}, "umbral_bajo_stock": umbral,
        "generado_en": datetime.now(timezone.utc), "generado_por": user["correo"],
        "ventas": {"resumen": resumen, "por_dia": por_dia, "por_canal": por_canal,
                   "por_metodo_pago": por_metodo, "mas_vendidos": mas_vendidos},
        "inventario": {
            "productos": len(inventario),
            "unidades": sum(i["stock_fisico"] for i in inventario),
            "valor_total": sum((i["valor"] for i in inventario), Decimal(0)),
            "bajo_stock": sum(1 for i in inventario if i["bajo_stock"]),
            "detalle": inventario,
        },
    }


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


# ---------- Actualizar estado de pedido / Cancelar pedido ----------
class CambioEstado(Entrada):
    estado: Literal["entregado", "cancelado"]
    motivo: Optional[str] = Field(default=None, min_length=3, max_length=150)

    @model_validator(mode="after")
    def motivo_al_cancelar(self):
        if self.estado == "cancelado" and not self.motivo:
            raise ValueError("Indica el motivo de la cancelación.")
        return self


@app.patch("/api/pedidos/{id_pedido}/estado")
def cambiar_estado_pedido(id_pedido: int, c: CambioEstado, user=Depends(current_user), db=Depends(get_db)):
    with db.transaction():
        p = db.execute("SELECT p.id_pedido,p.estado,p.id_empleado,c.id_usuario AS dueno FROM pedidos p "
                       "JOIN clientes c USING (id_cliente) WHERE p.id_pedido=%s FOR UPDATE OF p",
                       (id_pedido,)).fetchone()
        # Un cliente solo ve (y solo puede cancelar) sus propios pedidos.
        if not p or (user["rol"] == "cliente" and p["dueno"] != user["id_usuario"]):
            raise HTTPException(404, "Pedido no encontrado.")
        if user["rol"] == "cliente":
            if c.estado != "cancelado":
                raise HTTPException(403, "Solo el empleado o el administrador marcan un pedido como entregado.")
            if p["id_empleado"] is not None:
                raise HTTPException(403, "Una venta presencial solo la puede cancelar el empleado o el administrador.")
        if p["estado"] != "confirmado":
            raise HTTPException(409, f"El pedido ya está {p['estado']}; solo se actualizan pedidos confirmados.")
        if c.estado == "cancelado":
            # Devuelve las unidades al inventario, en el mismo orden de bloqueo que las ventas.
            for d in db.execute("SELECT d.id_medicamento,d.cantidad FROM detalles_pedido d "
                                "JOIN medicamentos m USING (id_medicamento) WHERE d.id_pedido=%s "
                                "ORDER BY d.id_medicamento FOR UPDATE OF m", (id_pedido,)).fetchall():
                db.execute("UPDATE medicamentos SET stock=stock+%s WHERE id_medicamento=%s",
                           (d["cantidad"], d["id_medicamento"]))
                db.execute("INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo) "
                           "VALUES (%s,%s,'entrada',%s,%s)",
                           (d["id_medicamento"], user["id_usuario"], d["cantidad"],
                            f"Cancelación del pedido #{id_pedido}: {c.motivo}"[:200]))
        extra = {"estado": c.estado, "actualizado_por": user["correo"]}
        if c.motivo:
            extra["motivo_cancelacion"] = c.motivo
        # El comprobante conserva la copia de la venta y registra el nuevo estado.
        return db.execute("UPDATE pedidos SET estado=%s, comprobante=COALESCE(comprobante,'{}'::jsonb) || %s "
                          "WHERE id_pedido=%s RETURNING comprobante",
                          (c.estado, Jsonb(extra), id_pedido)).fetchone()["comprobante"]


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


# ---------- Integración con otras UDS (UC12 exponer inventario · UC13 consultar otras UDS) ----------
# Formato de intercambio común: ProductoGenerico. Versión en la ruta (/v1) para poder cambiarlo sin romper a nadie.
UDS_NOMBRE = os.getenv("UDS_NOMBRE", "FarmaSalud")
# Claves que pueden usar otras UDS para consultarnos (separadas por comas). Vacía = API abierta.
UDS_API_KEYS = [k.strip() for k in os.getenv("UDS_API_KEYS", "").split(",") if k.strip()]
# Otras UDS que podemos consultar, en JSON: [{"nombre": "...", "url": ".../productos", "api_key": "..."}]
try:
    UDS_EXTERNAS = {u["nombre"].strip().lower(): u for u in json.loads(os.getenv("UDS_EXTERNAS", "") or "[]")}
except (ValueError, KeyError, TypeError, AttributeError):
    raise RuntimeError('UDS_EXTERNAS debe ser JSON: [{"nombre": "...", "url": "https://...", "api_key": "..."}]')
UDS_TIMEOUT = 10


class ProductoGenerico(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    codigo: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=1, max_length=200)
    concentracion_mg: Optional[int] = None
    presentacion: Optional[str] = None
    categoria: Optional[str] = None
    laboratorio: Optional[str] = None
    precio: float = Field(ge=0)  # número JSON (no texto) para que cualquier lenguaje lo lea igual
    moneda: str = "COP"
    stock_disponible: int = Field(ge=0)
    requiere_formula: bool = False
    imagen_url: Optional[str] = None
    uds_origen: str = Field(min_length=1, max_length=100)


class RespuestaUDS(BaseModel):
    uds: str
    version: str = "1.0"
    generado_en: datetime
    total: int
    productos: List[ProductoGenerico]


def cliente_uds(x_api_key: str = Header(default="")):
    # Las UDS se identifican con una clave (cabecera X-API-Key), no con usuario y contraseña.
    if UDS_API_KEYS and not any(hmac.compare_digest(x_api_key, k) for k in UDS_API_KEYS):
        raise HTTPException(401, "Falta la cabecera X-API-Key o la clave no es válida.")


PRODUCTOS_UDS = """
SELECT 'FS-' || m.id_medicamento AS codigo, m.nombre, m.mg AS concentracion_mg, m.forma AS presentacion,
       c.nombre AS categoria, l.nombre AS laboratorio, m.precio, GREATEST(v.disponible, 0) AS stock_disponible,
       m.requiere_formula, m.imagen_url
FROM medicamentos m JOIN categorias c USING (id_categoria)
JOIN laboratorios l USING (id_laboratorio) JOIN v_stock_disponible v USING (id_medicamento)
WHERE m.activo AND m.nombre ILIKE %(q)s AND (%(categoria)s = '' OR c.nombre ILIKE %(categoria)s)
  AND (NOT %(solo)s OR v.disponible > 0) AND (%(id)s::INT IS NULL OR m.id_medicamento = %(id)s)
ORDER BY m.nombre
"""


def productos_uds(db, request: Request, q="", categoria="", solo=False, id_med=None) -> List[dict]:
    base = str(request.base_url).rstrip("/")
    filas = db.execute(PRODUCTOS_UDS, {"q": f"%{q}%", "categoria": categoria, "solo": solo, "id": id_med}).fetchall()
    for f in filas:
        f["uds_origen"] = UDS_NOMBRE
        f["moneda"] = "COP"
        if f["imagen_url"] and f["imagen_url"].startswith("/"):
            f["imagen_url"] = base + f["imagen_url"]  # URL completa para que la otra app pueda mostrarla
    return filas


@app.get("/api/uds/v1/productos", response_model=RespuestaUDS, tags=["Integración UDS"],
         summary="UC12 · Exponer inventario a otras UDS")
def uds_productos(request: Request, q: str = Query(default="", max_length=100),
                  categoria: str = Query(default="", max_length=100), solo_disponibles: bool = False,
                  _=Depends(cliente_uds), db=Depends(get_db)):
    productos = productos_uds(db, request, q, categoria, solo_disponibles)
    return {"uds": UDS_NOMBRE, "generado_en": datetime.now(timezone.utc), "total": len(productos),
            "productos": productos}


@app.get("/api/uds/v1/productos/{codigo}", response_model=ProductoGenerico, tags=["Integración UDS"],
         summary="UC12 · Consultar un producto por código (FS-<id>)")
def uds_producto(codigo: str, request: Request, _=Depends(cliente_uds), db=Depends(get_db)):
    m = re.fullmatch(r"FS-(\d{1,9})", codigo.strip().upper())
    filas = productos_uds(db, request, id_med=int(m.group(1))) if m else []
    if not filas:
        raise HTTPException(404, f"No existe el producto {codigo}.")
    return filas[0]


def leer_uds_externa(uds: dict, q: str) -> dict:
    url = uds["url"] + ("&" if "?" in uds["url"] else "?") + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"{UDS_NOMBRE}-UDS/1.0"})
    if uds.get("api_key"):
        req.add_header("X-API-Key", uds["api_key"])
    try:
        with urllib.request.urlopen(req, timeout=UDS_TIMEOUT) as r:
            datos = json.loads(r.read(5 * 1024 * 1024))
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"La UDS {uds['nombre']} respondió con error {e.code}.")
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(504, f"No se pudo conectar con la UDS {uds['nombre']}.")
    except ValueError:
        raise HTTPException(502, f"La UDS {uds['nombre']} no respondió con JSON válido.")
    # Se acepta {"productos": [...]} o una lista directa; los productos con formato inválido se descartan.
    lista = datos.get("productos") if isinstance(datos, dict) else datos
    if not isinstance(lista, list):
        raise HTTPException(502, f"La UDS {uds['nombre']} no respondió con el formato ProductoGenerico.")
    validos, descartados = [], 0
    for p in lista:
        try:
            if isinstance(p, dict):
                p = {"uds_origen": uds["nombre"], **p}
            validos.append(ProductoGenerico.model_validate(p))
        except ValueError:
            descartados += 1
    return {"uds": uds["nombre"], "consultado_en": datetime.now(timezone.utc), "total": len(validos),
            "descartados": descartados, "productos": validos}


@app.get("/api/uds/externas", tags=["Integración UDS"], summary="UC13 · Listar las UDS configuradas")
def uds_externas(user=Depends(admin_only)):
    return [{"nombre": u["nombre"], "url": u["url"]} for u in UDS_EXTERNAS.values()]


@app.get("/api/uds/externas/{nombre}/productos", tags=["Integración UDS"],
         summary="UC13 · Consultar el inventario de otra UDS")
def uds_externa_productos(nombre: str, q: str = Query(default="", max_length=100), user=Depends(admin_only)):
    uds = UDS_EXTERNAS.get(nombre.strip().lower())
    if not uds:
        raise HTTPException(404, f"La UDS '{nombre}' no está configurada. Revisa GET /api/uds/externas.")
    return leer_uds_externa(uds, q)


# ---------- Frontend compilado (producción) ----------
# El Dockerfile copia frontend/dist en FRONTEND_DIR; así API y página comparten dominio (sin CORS).
# Se monta al final para que las rutas /api tengan prioridad.
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(Path(__file__).resolve().parent / "static")))
if (FRONTEND_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
