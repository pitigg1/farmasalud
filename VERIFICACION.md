# Verificación de FarmaSalud — 20 de octubre de 2026

## Resultado

Se verificó el recorrido React → proxy de Vite → FastAPI → PostgreSQL → comprobante.
Los archivos actualizados también se copiaron a la carpeta original del proyecto.
La migración se aplicó al volumen existente, después de respaldarlo.

## Datos de la base principal conservados

| Dato | Antes | Después |
|---|---:|---:|
| Medicamentos | 5 | 5 |
| Clientes | 1 | 1 |
| Pedidos | 0 | 0 |

Las compras de prueba se ejecutaron exclusivamente en `farmacia_test`.
Se conservó el volumen `farmasalud-main_pgdata`; no se eliminó ni se reinició su stock.
La API convierte los marcadores de contraseña de las cuentas de demostración en hashes,
tal como hacía el prototipo original. El respaldo previo conserva el estado anterior.

## Evidencia automatizada

```text
15 passed, 15 warnings in 247.28s
```

Las advertencias proceden del adaptador TestClient/httpx de las versiones fijadas;
no son fallos de las ventas. Las pruebas comprobaron:

- Cliente presencial sin crear cuenta de acceso y venta atribuida al empleado.
- Ventas a dos clientes diferentes sin asociarlos con la cuenta del empleado.
- Compra propia del cliente y permisos por rol.
- Rechazo de apropiación de un documento ya registrado.
- Rollback de todos los productos ante stock insuficiente.
- Fórmula obligatoria y verificada para la venta asistida.
- Rechazo de verificación de fórmula por el cliente.
- Reintento de una operación sin duplicar descuento; cambio de contenido rechazado.
- Última unidad con solicitudes simultáneas de clientes diferentes.
- Última unidad con solicitudes simultáneas del mismo cliente.
- Reenvíos simultáneos de la misma operación.
- Protección de comprobantes ajenos e independencia del comprobante ante cambios posteriores.
- Retiro de endpoints de alta, baja y ajuste de medicamentos.
- Rechazo de usuarios desactivados.
- Migración repetible que conserva stock y comprobante.

## Evidencia en navegador y SQL

En `http://localhost:5174`, conectado únicamente a `farmacia_test`:

1. Se inició sesión como empleado y se buscó un documento inexistente.
2. Se registró el cliente ficticio Demo Navegador, documento `900000099`.
3. Se vendieron dos unidades de Loratadina desde la interfaz.
4. La web consultó `/api/pedidos/2/comprobante` y mostró `FS-2`, empleado y total.
5. PostgreSQL confirmó:

```text
id_pedido=2, id_cliente=2, id_empleado=2, total=9600.00, cantidad=2, stock=118
```

Después se recargó la página, se inició sesión como cliente y se compró una Aspirina:

```text
id_pedido=3, id_cliente=1, id_empleado=NULL, total=5200.00, cantidad=1, stock=149
```

Los logs confirmaron POST de ventas con estado 201 y GET de comprobantes con estado 200.
La captura `comprobante-prueba.png` de la entrega muestra el comprobante del empleado.
Los servidores temporales 5174/8001 se cerraron después de las comprobaciones.

## Compilación y ejecución final

- `npm ci` completado y `npm run build` correcto: 33 módulos transformados.
- Imagen de API construida correctamente con `python:3.12-slim`.
- API definitiva iniciada mediante Docker Compose y consultada por HTTP.
- `/api/salud`: `base_datos=farmacia`, `esquema=farmacia`, `medicamentos=5`.
- Proxy `/api/medicamentos` del frontend: 5 medicamentos.
- PostgreSQL publicado únicamente en `127.0.0.1:5433`.
- API publicada únicamente en `127.0.0.1:8000`.
- Frontend iniciado desde la carpeta original en `127.0.0.1:5173`.

## Actualización — 9 de noviembre de 2026: gestión de inventario e informe

Se implementaron los casos de uso **Gestionar Inventario** y **Generar Informe de
Inventario/Ventas** del administrador. Gestionar Inventario permite registrar,
editar, ajustar stock con motivo, retirar y reactivar medicamentos, y crear
laboratorios y categorías. La prueba que verificaba el retiro de esas rutas se
sustituyó por pruebas de la nueva funcionalidad.

```text
21 passed   (PostgreSQL 16.2, base farmacia_test)
```

Nuevas comprobaciones:

- Solo el administrador gestiona el inventario: empleado y cliente reciben 403; sin sesión, 401.
- Alta con stock inicial registrada como movimiento `entrada`; visible en el catálogo.
- Edición de datos y precio sin modificar el stock.
- Ajustes registrados con usuario y motivo; rechazo de stock negativo o menor que lo reservado.
- Medicamento retirado: fuera del catálogo y sin ventas nuevas, conservando comprobantes.
- Ajuste y venta simultáneos sobre la última unidad: solo uno se aplica y el stock queda en cero.
- Informe: totales, unidades, ticket promedio, canal, método de pago, más vendidos e inventario
  coinciden con las ventas registradas; respeta el periodo, el umbral y los retiros.
- Informe: solo para el administrador; rechaza periodos invertidos, mayores a un año o fechas inválidas.

También se revisó en navegador (Microsoft Edge): alta, ajuste y movimientos de un medicamento,
y generación e impresión a PDF del informe, sin errores de JavaScript.

## Actualización — 9 de noviembre de 2026: seguridad

- **Clave JWT:** se eliminó el valor fijo del código. La API exige `JWT_SECRET` de 32 o más
  caracteres (si es más corta no arranca); si falta, usa una clave aleatoria temporal.
- **Contraseñas:** se eliminó `farmacia123`. Las cuentas precargadas reciben `CLAVE_INICIAL`
  o una contraseña aleatoria que se muestra en el registro de la API. La API advierte al
  iniciar si alguna cuenta todavía usa la contraseña antigua. Se agregó el cambio de
  contraseña (botón 🔑, `POST /api/auth/cambiar-clave`) y el registro exige 8 caracteres.
- **Dependencias:** Vite 5.4 → 7.3.8 y @vitejs/plugin-react 4 → 5.2. `npm audit`:
  **0 vulnerabilidades** (antes 1 moderada y 1 alta, en esbuild y Vite). Requiere Node 20.19+.
- **Configuración:** `.env.example` documenta las variables; `.env` no se sube a Git.
  El README ya no contiene rutas de un equipo particular.

```text
24 passed   (PostgreSQL 16.2, base farmacia_test)
```

En el navegador (Edge, Vite 7.3.8): `farmacia123` fue rechazada, se ingresó con la
contraseña aleatoria generada, se cambió la contraseña y se ingresó con la nueva,
sin errores de JavaScript.

## Alcance y pendientes

El comprobante es académico e imprimible; no es facturación electrónica ni un cobro.
La revisión de fórmula es una declaración del empleado, validada por rol y fechas;
no existe integración con un verificador médico externo.
pgAdmin no se instaló ni configuró en el equipo: los pasos y credenciales de conexión
están en README y las consultas preparadas en `backend/demo_consultas.sql`.
La impresión tiene estilos específicos; no se realizó una impresión física.

Los dos avisos de seguridad de `npm ci` se corrigieron el 9 de noviembre de 2026
(ver la actualización de seguridad).
