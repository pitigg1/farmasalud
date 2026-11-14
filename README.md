# FarmaSalud · catálogo, compras y ventas asistidas

Prototipo académico con React + Vite, FastAPI y PostgreSQL 16.
El catálogo y las ventas se leen de PostgreSQL. Las cuentas de empleado y
administrador se precargan. El administrador gestiona el inventario desde la
aplicación: registra, edita, ajusta el stock y retira medicamentos; cada cambio
de stock queda en `movimientos_inventario`.

## Estructura

```text
docker-compose.yml          PostgreSQL en localhost:5433; API opcional en Docker
backend/
  main.py                   API, autenticación y transacción de venta
  schema.sql                Instalación nueva, exclusivamente sobre una BD vacía
  migrations/001_ventas.sql Actualización sin borrar registros
  demo_consultas.sql        Consultas de evidencia para pgAdmin
  requirements.txt          Dependencias para Python 3.12
  requirements-dev.txt      Dependencias de pruebas
  tests/test_ventas.py      Pruebas con PostgreSQL real en farmacia_test
  Dockerfile                Alternativa a instalar Python en Windows
frontend/src/
  App.jsx                   Catálogo y acceso según rol
  Sales.jsx                 Cliente, venta asistida, historial y comprobante
  Inventario.jsx            Gestión de inventario del administrador
  Informe.jsx               Informe de inventario y ventas (imprimible)
  api.js                    Solicitudes a FastAPI
  styles.css                Diseño original y estilos de impresión
```

## Activar el proyecto en Windows (PowerShell)

Requisitos: Docker Desktop abierto y con el motor activo, Node.js 20.19 o superior con npm.
En los comandos, reemplaza `<carpeta del proyecto>` por la ruta donde descargaste el proyecto.
Para ejecutar la API directamente en Windows utiliza **Python 3.12**. El entorno
anterior creado con Python 3.14 no sirve para estas versiones fijadas; puedes
usar la alternativa Docker del paso 3 y conservar ese entorno anterior.

### 1. Abrir la carpeta y levantar PostgreSQL

```powershell
cd "<carpeta del proyecto>"
docker info
docker compose up -d db
docker compose ps
```

Debe aparecer `127.0.0.1:5433->5432/tcp`. El puerto 5433 es el que usan Windows,
pgAdmin y la API local; dentro de la red de Docker el servidor es `db:5432`.
No cambies el nombre del proyecto Compose ni el volumen si quieres usar la base
que ya tenías. En este equipo el volumen existente es `farmasalud-main_pgdata`.

### 2. Respaldar y aplicar la migración

Ejecuta desde la carpeta raíz. La migración se puede repetir y conserva los datos.
Si el cambio ya fue aplicado, puedes repetir únicamente los últimos dos comandos.

```powershell
New-Item -ItemType Directory -Path backups -Force
docker compose exec -T db pg_dump -U farmacia -d farmacia -Fc -f /tmp/antes-migracion.dump
docker compose cp db:/tmp/antes-migracion.dump ./backups/antes-migracion.dump
docker compose cp ./backend/migrations/001_ventas.sql db:/tmp/001_ventas.sql
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U farmacia -d farmacia -f /tmp/001_ventas.sql
```

En una instalación nueva, Docker ejecuta `schema.sql` una sola vez al crear el
volumen vacío. Si el volumen ya existe, cambiar ese archivo no modifica sus tablas:
se aplica la migración anterior. **No ejecutes `docker compose down -v`**, porque
elimina el volumen. Para apagar conservando registros usa `docker compose stop`.

### 3. Iniciar la API (elige una alternativa)

Antes, define las claves de seguridad. La API **no trae claves fijas**:

- `JWT_SECRET`: firma las sesiones; mínimo 32 caracteres. Si falta, la API usa una
  clave temporal y las sesiones se cierran cada vez que se reinicia.
- `CLAVE_INICIAL` (opcional): si se define, reemplaza las contraseñas iniciales de las
  cuentas precargadas en una base **nueva**; mínimo 8 caracteres. Si falta, se usan las
  contraseñas fijas de la tabla de [cuentas precargadas](#5-cuentas-precargadas).

Para generar una clave segura: `py -3.12 -c "import secrets; print(secrets.token_urlsafe(32))"`.

**A. Docker: no requiere instalar Python en Windows.**

Copia `.env.example` como `.env` en la carpeta raíz y completa los dos valores
(Docker Compose lee ese archivo; `.env` no se sube a Git).

```powershell
Copy-Item .env.example .env
notepad .env
docker compose --profile app up -d --build api
docker compose logs --tail 30 api
```

La primera vez necesita descargar la imagen de Python y las dependencias.
Después de cambiar código, repite el comando con `--build`.

**B. Python 3.12 local: en una segunda terminal.**

Instala Python 3.12 si no está disponible y verifica `py -3.12 --version`.
La carpeta `.venv312` evita reemplazar tu entorno anterior.

```powershell
cd "<carpeta del proyecto>\backend"
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia"
$env:JWT_SECRET = .\.venv312\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv312\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

No es necesario activar el entorno ni cambiar la política de ejecución de PowerShell.
No ejecutes A y B al mismo tiempo: ambas usan el puerto 8000.

Verifica [salud de la API](http://localhost:8000/api/salud),
[catálogo JSON](http://localhost:8000/api/medicamentos) y
[Swagger](http://localhost:8000/docs). Salud debe indicar base `farmacia` y esquema
`farmacia`. Si faltan columnas, aplica la migración y reinicia la API.

### 4. Iniciar React en otra terminal

```powershell
cd "<carpeta del proyecto>\frontend"
npm.cmd ci
npm.cmd run dev
```

Abre [FarmaSalud](http://localhost:5173). Vite envía `/api` a FastAPI en el puerto
8000. Si el 5173 está ocupado, cierra el servidor anterior; Vite no cambiará de
puerto silenciosamente.

### 5. Cuentas precargadas

| Correo | Contraseña inicial | Función |
|---|---|---|
| cliente@mail.com | `Cliente2026*` | Compra propia e historial |
| empleado@farmacia.com | `Empleado2026*` | Registro de clientes y venta presencial |
| admin@farmacia.com | `Admin2026*` | Gestión de inventario, ventas, informes e integración UDS |

Estas contraseñas están en `CLAVES_INICIALES` de `backend/main.py` y siempre son las
mismas (no se generan al azar). Si defines `CLAVE_INICIAL`, esa reemplaza a las tres.
La API asigna la contraseña inicial únicamente a registros que todavía tengan
`REEMPLAZAR_POR_HASH`; no reemplaza contraseñas ya establecidas. Cada usuario puede
cambiar su contraseña con el botón 🔑 junto a su nombre (mínimo 8 caracteres).
El rol se verifica contra PostgreSQL en cada solicitud autenticada.

**Si tu base ya existía** con la contraseña antigua de demostración (`farmacia123`),
esa contraseña sigue funcionando hasta que la cambies: la API muestra una advertencia
al iniciar por cada cuenta que todavía la usa. Inicia sesión con ella y cámbiala con 🔑.

## Conectar pgAdmin 4 instalado en Windows

1. Abre pgAdmin. En **Servers**, clic derecho → **Register → Server**.
2. En **General**, escribe `FarmaSalud local` como nombre.
3. En **Connection**, completa:

| Campo | Valor |
|---|---|
| Host name/address | 127.0.0.1 |
| Port | 5433 |
| Maintenance database | farmacia |
| Username | farmacia |
| Password | farmacia |

4. Guarda y abre **Databases → farmacia → Schemas → farmacia → Tables**.
5. Selecciona la base `farmacia` y abre **Tools → Query Tool**.
6. Abre `backend/demo_consultas.sql` y ejecuta las consultas. Después de cada venta,
   vuelve a ejecutar el `SELECT`: una cuadrícula abierta no se actualiza sola.

Estas instrucciones usan pgAdmin instalado en Windows, no dentro de otro contenedor.
No necesitas instalar otro servidor PostgreSQL ni importar una copia de la base.

## Guion para demostrarlo al profesor (5–10 minutos)

### A. Evidencia inicial

Abre la web y pgAdmin lado a lado. Ejecuta la consulta de existencias y muestra
que las cantidades del catálogo coinciden. Explica: **React consulta FastAPI y
FastAPI consulta el esquema farmacia de PostgreSQL; React no accede directamente
a la base**. Puedes mostrar también `/api/salud` y la solicitud `/api/medicamentos`
en la pestaña Network del navegador.

### B. Compra del cliente

1. Entra con `cliente@mail.com`.
2. Agrega dos unidades de Acetaminofén, abre el carrito y procede a la compra.
3. Los datos de Laura se cargan desde la BD. Completa la dirección y confirma.
4. Se abre el comprobante leído de la API; muestra número, fecha y total.
5. En pgAdmin, comprueba pedido, detalle, salida de inventario y stock reducido
   exactamente en dos. No presupongas un stock inicial de 200 si ya hiciste ventas.
6. Recarga la página, inicia sesión y entra a **Mis compras y comprobantes**:
   la venta y su comprobante permanecen guardados.

### C. Venta del empleado y cliente nuevo

1. Cierra sesión y entra con `empleado@farmacia.com`.
2. Busca un documento de prueba que no exista, por ejemplo CC `900000001`.
3. Registra nombre, apellido, correo y celular. Si ya existe, úsalo o elige otro.
4. En pgAdmin muestra el nuevo cliente: puede tener `id_usuario=NULL`, porque
   registrar un cliente presencial no crea una cuenta de acceso.
5. Selecciona una cantidad de un medicamento existente y confirma la venta.
6. Muestra que el pedido guarda el `id_cliente` seleccionado y `id_empleado=2`
   en la base original de ejemplo. Lo importante es que coincida con el usuario
   empleado real, no asumir siempre ese número en otras instalaciones.
7. Abre el comprobante y usa **Imprimir / Guardar PDF**.

### D. Estados del pedido: entregar y cancelar

Toda venta nace **confirmada**. En **Ventas registradas** (empleado o administrador):

1. **Marcar entregado** pasa el pedido a `entregado`; desde ahí ya no se puede cancelar.
2. **Cancelar** pide un motivo, pasa el pedido a `cancelado` y **devuelve las unidades al
   inventario**, registrando un movimiento de entrada «Cancelación del pedido #n».
3. El comprobante conserva la copia de la venta y muestra el estado, quién lo canceló y el motivo.

El cliente puede cancelar desde **Mis compras** solo sus compras en línea que sigan confirmadas.
Los pedidos cancelados no cuentan en el informe de ventas. En pgAdmin revisa `pedidos.estado`,
`medicamentos.stock` y `movimientos_inventario`.

### E. Fórmula médica

El cliente ve Amoxicilina como **Venta asistida**. Para venderla, el empleado
selecciona el cliente, indica cantidad, número de fórmula, médico, fechas vigentes
y marca que la revisó. La API y SQL validan estos datos antes del descuento.
La tabla `formulas` guarda `valida=TRUE`; el pedido identifica al empleado.
El sistema registra la revisión humana: no verifica automáticamente documentos
médicos ni se conecta con un sistema externo.

### F. Gestión de inventario (administrador)

1. Entra con `admin@farmacia.com`.
2. Pulsa **+ Nuevo medicamento**: completa nombre, mg, forma, laboratorio,
   categoría, precio y stock inicial, y opcionalmente una foto (JPG, PNG o WebP,
   máximo 2 MB). Si falta un laboratorio o una categoría, créalo con **+ nuevo**
   dentro del mismo formulario. El medicamento aparece de inmediato en el catálogo.
3. Usa **Ajustar stock** con una entrada (compra a proveedor) o una salida
   (vencidos, conteo físico) y un motivo. Abre **Movimientos** para ver el registro
   con fecha, tipo, cantidad, motivo y usuario.
4. **Editar** cambia datos y precio, pero no el stock: el stock solo cambia
   con ajustes registrados o con ventas.
5. **Retirar** oculta el medicamento del catálogo y bloquea nuevas ventas, pero
   conserva los pedidos y comprobantes anteriores. **Reactivar** lo devuelve.
6. En pgAdmin, revisa `medicamentos` y `movimientos_inventario`.

### G. Informe de inventario y ventas (administrador)

1. Con la sesión de administrador, pulsa **Generar informe**.
2. Elige el periodo (por defecto, los últimos 30 días) y el umbral de stock bajo.
3. El informe muestra el total vendido, los pedidos, las unidades, el ticket promedio,
   los más vendidos, las ventas por canal (en línea o presencial), por método de
   pago y por día, y el inventario actual con su valor y alertas de stock bajo.
4. Usa **Imprimir / Guardar PDF**. Todas las cifras salen de una sola consulta
   consistente a PostgreSQL y solo cuentan pedidos confirmados o entregados.

### H. Rollback y concurrencia

No alteres el stock de la BD principal para preparar la demostración. Ejecuta las
pruebas de la sección siguiente en `farmacia_test`. Muestra especialmente:

- Un pedido con un producto suficiente y otro insuficiente deja todo sin cambios.
- Dos solicitudes simultáneas por la última unidad: una venta confirma y otra
  responde 409; el stock termina en cero.
- Dos envíos simultáneos con la misma clave devuelven la misma venta y descuentan una vez.
- Dos ventas del mismo cliente no mezclan reservas.
- Un cliente no puede consultar comprobantes ajenos ni registrar clientes.
- Un ajuste de stock y una venta simultáneos por la última unidad: solo uno se aplica.
- Dos cancelaciones simultáneas del mismo pedido devuelven el stock una sola vez.

## Ejecutar pruebas con PostgreSQL real

En la raíz crea la base separada una sola vez:

```powershell
docker compose exec -T db createdb -U farmacia farmacia_test
```

Si ya existe, continúa; no es necesario volver a crearla. En una terminal con
Python 3.12, desde `backend`:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:TEST_DATABASE_URL = "postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia_test"
.\.venv312\Scripts\python.exe -m pytest -q tests
```

Cada prueba reinicia exclusivamente el esquema de esa base de pruebas. El ejecutor
rechaza bases cuyos nombres no terminan en `_test`. Nunca uses datos reales en esa BD.
Para revisar el frontend: `cd frontend` y `npm.cmd run build`.

## Contrato de la API y garantías

| Método | Ruta | Acceso |
|---|---|---|
| GET | /api/salud, /api/medicamentos | Público |
| POST | /api/auth/login, /api/auth/register | Público; registro solo crea rol cliente |
| GET | /api/clientes/yo | Cliente: su propio perfil |
| GET | /api/clientes?tipo_documento=CC&documento=... | Empleado |
| POST | /api/clientes | Empleado |
| GET | /api/pedidos | Cliente: propios; empleado/admin: todas las ventas |
| POST | /api/pedidos | Cliente o empleado |
| GET | /api/pedidos/{id}/comprobante | Propietario, empleado o admin |
| PATCH | /api/pedidos/{id}/estado | Empleado/admin: `entregado` o `cancelado` (con motivo). Cliente: solo cancelar sus compras en línea |
| GET | /api/inventario, /api/inventario/movimientos | Administrador |
| POST | /api/medicamentos | Administrador: registrar (con stock inicial) |
| PUT | /api/medicamentos/{id} | Administrador: editar datos y precio |
| PATCH | /api/medicamentos/{id}/stock | Administrador: entrada o ajuste con motivo |
| DELETE | /api/medicamentos/{id} | Administrador: retiro lógico |
| POST | /api/medicamentos/{id}/reactivar | Administrador |
| GET, POST | /api/laboratorios, /api/categorias | Administrador |
| PUT, DELETE | /api/medicamentos/{id}/imagen | Administrador: subir (cuerpo = archivo) o quitar la foto |
| GET | /api/imagenes/{nombre} | Público: foto del medicamento |
| GET | /api/informes?desde=&hasta=&umbral= | Administrador: informe de inventario y ventas |

`POST /api/pedidos` requiere `clave_operacion` (UUID), `metodo_pago` e `items`.
El cliente envía sus datos en `cliente`; el empleado envía el `id_cliente`
seleccionado. Nunca se acepta `id_empleado`, precio ni total desde el navegador.
Los ítems incluyen `id_medicamento`, `cantidad` y, cuando aplica, los datos de fórmula.
Una clave repetida con igual usuario y contenido devuelve el resultado original;
la misma clave con otro contenido se rechaza. El frontend conserva la clave al
reintentar el mismo envío. Ante una desconexión después de confirmar, consulta
el historial antes de iniciar una venta distinta.

Se reutilizan reservas y funciones SQL: bloqueo por cliente, medicamentos en orden
fijo, validación de stock, detalles, fórmulas, movimientos y comprobante en una
transacción. El commit ocurre antes de responder éxito. Los comprobantes nuevos
guardan una copia de los datos al vender; los anteriores reciben una copia de los
datos disponibles al migrar. Son comprobantes académicos, no facturas electrónicas.
Los métodos de pago son registros informativos, no integraciones de cobro.

## macOS / Linux

Usa los mismos comandos Docker y npm desde la carpeta del proyecto. Para la API:

```bash
cd backend
python3.12 -m venv .venv312
source .venv312/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia'
export JWT_SECRET="$(python3.12 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CLAVE_INICIAL='elige-una-clave-segura'
uvicorn main:app --reload --port 8000
```

Las fotos de los medicamentos se guardan como archivos en `backend/imagenes/`
(variable `IMAGENES_DIR`; en Docker, en el volumen `imagenes`) y la base guarda su
dirección en `medicamentos.imagen_url`. La carpeta está excluida de Git.

Las credenciales de PostgreSQL de `docker-compose.yml` son solo para desarrollo local
(el puerto se publica únicamente en 127.0.0.1). Conserva los
respaldos fuera del repositorio; `backups/` está excluido por `.gitignore`.

