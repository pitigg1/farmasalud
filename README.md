# Prototipo 1 — Farmacia (React + FastAPI + PostgreSQL)

```
prototipo_1_stack/
├── docker-compose.yml     # PostgreSQL 16 (carga schema.sql al crearse)
├── backend/               # Python + FastAPI
│   ├── main.py            # API: auth, medicamentos, pedidos (transacción)
│   ├── schema.sql         # Tablas + datos de ejemplo
│   └── requirements.txt
└── frontend/              # React + Vite
    └── src/ (App.jsx, api.js, styles.css)
```

## Cómo ejecutarlo (3 terminales)

**1. Base de datos** (requiere Docker)
```bash
docker compose up -d
```
Sin Docker: instala PostgreSQL, crea la BD `farmacia` y ejecuta `psql -f backend/schema.sql farmacia`.

**2. API** (Python 3.8 o superior)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Documentación automática: http://localhost:8000/docs

**3. Front**
```bash
cd frontend
npm install
npm run dev
```
Abre http://localhost:5173

## Variables de entorno (opcionales)
- `DATABASE_URL` (por defecto `postgresql://farmacia:farmacia@localhost:5432/farmacia`)
- `JWT_SECRET` (cámbiala fuera de desarrollo)

## Endpoints
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/auth/register` | Crea usuario (rol cliente) y devuelve token |
| POST | `/api/auth/login` | Devuelve token JWT |
| GET | `/api/medicamentos?q=` | Catálogo con stock |
| POST | `/api/pedidos` | Confirma pedido (requiere token) |

`POST /api/pedidos` replica la transacción de confirmación del diagrama de actividades: bloquea las filas con `FOR UPDATE`, valida fórmula y stock (stock − reservas activas), inserta `pedido` y `detalle_pedido` y descuenta stock; si algo falla, hace rollback.

## Pendiente para el Prototipo 2
- Endpoints de **reservas** (la tabla ya existe): reservar al agregar al carrito, expirar y liberar.
- Vista de **empleado** y **admin**, y endpoint para el **sistema externo**.
- Migraciones (Alembic) y pruebas (pytest / Vitest).

---

## Guía para macOS Catalina 10.15 (sin Docker)

**Instalar (una sola vez)**
1. **Python 3.11** desde python.org/downloads/macos (instalador `.pkg`). Si no instala, usa Python 3.8.10.
2. **Node.js 20 LTS** desde nodejs.org (instalador `.pkg`, versión 20.x).
3. **Postgres.app** desde postgresapp.com/downloads (PostgreSQL 16 o 15, requiere macOS 10.15).

**Base de datos** (Postgres.app abierto y con el servidor iniciado)
```bash
export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
psql -d postgres -c "CREATE USER farmacia WITH PASSWORD 'farmacia';"
psql -d postgres -c "CREATE DATABASE farmacia OWNER farmacia;"
cd ~/proyectos/prototipo_1_stack
psql -h localhost -U farmacia -d farmacia -f backend/schema.sql
```

**API**
```bash
cd ~/proyectos/prototipo_1_stack/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Front** (otra pestaña de Terminal)
```bash
cd ~/proyectos/prototipo_1_stack/frontend
npm install
npm run dev
```

---

## Rediseño FarmaSalud (vistas digitales)
La interfaz sigue las capturas del equipo (paleta morada/amarilla, tipografía Inter). El esquema ganó las columnas `categoria` y `etiqueta`, así que **si ya tenías la base creada** debes recrearla:
```bash
docker compose down -v
docker compose up -d
```
Las vistas **Vendedor** y **Admin** usan datos de ejemplo (aún sin API). El selector Cliente / Vendedor / Admin del encabezado es solo de demostración.

---

## Conexión con la base de datos del equipo (`backend/schema.sql` = `farmaciadb.sql`)
- Todas las tablas viven en el esquema **`farmacia`**; la API ya lo usa (`search_path`).
- El pedido llama a `reservar_stock()` y `confirmar_pedido()` de la base de datos, en una sola transacción.
- Al iniciar, la API asigna la contraseña de desarrollo **`farmacia123`** a los usuarios con `REEMPLAZAR_POR_HASH`:
  `admin@farmacia.com`, `empleado@farmacia.com` y `cliente@mail.com`.
- Administrador (`rol = admin`): puede agregar medicamentos, ajustar stock (se registra en `movimientos_inventario`) y quitarlos (baja lógica: `activo = FALSE`).
- Las fórmulas médicas quedan en la tabla `formulas` con `valida = FALSE` hasta que un empleado las verifique.

| Método | Ruta | Quién |
|---|---|---|
| GET | `/api/medicamentos`, `/api/catalogos` | Público |
| POST | `/api/medicamentos` | Admin |
| PATCH | `/api/medicamentos/{id}/stock` | Admin |
| DELETE | `/api/medicamentos/{id}` | Admin |
| POST | `/api/pedidos` | Usuario con sesión |

Si cambias `schema.sql`, recrea la base: `docker compose down -v && docker compose up -d`.
