"""Pruebas con PostgreSQL real. SOLO se permite una BD cuyo nombre termine en _test."""
import copy
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main

CLAVE_PRUEBAS = "clave-de-pruebas-segura"
TEST_DSN = os.getenv("TEST_DATABASE_URL", "postgresql://farmacia:farmacia@127.0.0.1:5433/farmacia_test")


def db():
    return psycopg.connect(TEST_DSN, autocommit=True, row_factory=dict_row,
                           options="-c search_path=farmacia,public")


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    with db() as conn:
        name = conn.execute("SELECT current_database() AS name").fetchone()["name"]
        if not name.endswith("_test"):
            pytest.fail("Protección: las pruebas solo pueden reiniciar una BD terminada en _test.")
        # Nunca apunta a farmacia: este reinicio pertenece únicamente a la BD de pruebas.
        conn.execute("DROP SCHEMA IF EXISTS farmacia CASCADE")
        conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8-sig"))
    monkeypatch.setattr(main, "DSN", TEST_DSN)
    monkeypatch.setattr(main, "CLAVE_INICIAL", CLAVE_PRUEBAS)


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def headers(client, correo="empleado@farmacia.com"):
    response = client.post("/api/auth/login", json={"correo": correo, "password": CLAVE_PRUEBAS})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def new_customer(client, auth, document="12345"):
    data = {"tipo_documento": "CC", "documento": document, "nombre": "Ana", "apellido": "Prueba",
            "correo": "ana@example.com", "celular": "3001234567"}
    response = client.post("/api/clientes", headers=auth, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def order(cid=1, mid=1, qty=2):
    return {"clave_operacion": str(uuid4()), "id_cliente": cid, "metodo_pago": "Efectivo",
            "items": [{"id_medicamento": mid, "cantidad": qty}]}


def scalar(query, params=()):
    with db() as conn:
        return next(iter(conn.execute(query, params).fetchone().values()))


def test_employee_sale_customer_and_receipt(client):
    auth = headers(client)
    customer = new_customer(client, auth)
    assert customer["id_usuario"] is None
    found = client.get("/api/clientes?tipo_documento=CC&documento=12345", headers=auth).json()
    assert found[0]["id_cliente"] == customer["id_cliente"]
    response = client.post("/api/pedidos", headers=auth, json=order(customer["id_cliente"]))
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["empleado"] == "empleado@farmacia.com"
    assert receipt["cliente"]["nombre"] == "Ana Prueba"
    assert receipt["total"] == "7000.00"
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 198
    assert scalar("SELECT id_empleado FROM pedidos") == 2
    assert scalar("SELECT cantidad FROM movimientos_inventario") == 2
    assert client.get(f"/api/pedidos/{receipt['id_pedido']}/comprobante", headers=auth).json() == receipt


def test_two_customers_do_not_become_employee(client):
    auth = headers(client)
    ids = [new_customer(client, auth, d)["id_cliente"] for d in ("123", "456")]
    for cid in ids:
        assert client.post("/api/pedidos", headers=auth, json=order(cid)).status_code == 201
    assert scalar("SELECT count(DISTINCT id_cliente) FROM pedidos") == 2
    assert scalar("SELECT count(*) FROM clientes WHERE id_usuario=2") == 0


def test_customer_purchase_and_permissions(client):
    auth = headers(client, "cliente@mail.com")
    profile = client.get("/api/clientes/yo", headers=auth).json()
    body = order()
    del body["id_cliente"]
    body["cliente"] = {k: profile[k] for k in main.ClienteIn.model_fields}
    response = client.post("/api/pedidos", headers=auth, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["empleado"] is None
    assert client.get("/api/clientes?documento=123", headers=auth).status_code == 403
    assert client.post("/api/clientes", headers=auth, json=body["cliente"]).status_code == 403
    assert client.post("/api/pedidos", headers=auth, json=order()).status_code == 422


def test_customer_cannot_overwrite_existing_document(client):
    login = client.post("/api/auth/register", json={"correo": "otra@example.com", "password": "clave-otra-123"}).json()
    auth = {"Authorization": "Bearer " + login["token"]}
    body = order()
    del body["id_cliente"]
    body["cliente"] = {"tipo_documento": "CC", "documento": "1098765432", "nombre": "Otra",
                       "apellido": "Persona", "correo": "otra@example.com", "celular": "123"}
    assert client.post("/api/pedidos", headers=auth, json=body).status_code == 409
    assert scalar("SELECT nombre FROM clientes WHERE id_cliente=1") == "Laura"
    assert scalar("SELECT count(*) FROM pedidos") == 0


def test_rollback_all_items(client):
    auth = headers(client)
    body = order()
    body["items"].append({"id_medicamento": 2, "cantidad": 999999})
    response = client.post("/api/pedidos", headers=auth, json=body)
    assert response.status_code == 409, response.text
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 200
    for table in ("pedidos", "detalles_pedido", "movimientos_inventario", "reservas"):
        assert scalar(f"SELECT count(*) FROM {table}") == 0


def test_formula_checked_before_sale(client):
    auth = headers(client)
    body = order(mid=3, qty=1)
    assert client.post("/api/pedidos", headers=auth, json=body).status_code == 422
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=3") == 80
    body["items"][0].update(numero_formula="RX-123", medico="Médico de prueba", formula_verificada=True,
                            fecha_emision=str(date.today()), fecha_vence=str(date.today() + timedelta(days=10)))
    response = client.post("/api/pedidos", headers=auth, json=body)
    assert response.status_code == 201, response.text
    assert scalar("SELECT valida FROM formulas") is True
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=3") == 79


def test_customer_cannot_verify_formula(client):
    auth = headers(client, "cliente@mail.com")
    profile = client.get("/api/clientes/yo", headers=auth).json()
    body = order(mid=3)
    del body["id_cliente"]
    body["cliente"] = {k: profile[k] for k in main.ClienteIn.model_fields}
    body["items"][0].update(formula_verificada=True, numero_formula="RX", medico="Prueba",
                            fecha_emision=str(date.today()), fecha_vence=str(date.today()))
    assert client.post("/api/pedidos", headers=auth, json=body).status_code == 422
    assert scalar("SELECT count(*) FROM formulas") == 0


def test_repeated_operation_and_changed_body(client):
    auth = headers(client)
    body = order()
    first = client.post("/api/pedidos", headers=auth, json=body)
    second = client.post("/api/pedidos", headers=auth, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    body["items"][0]["cantidad"] = 3
    assert client.post("/api/pedidos", headers=auth, json=body).status_code == 409
    assert scalar("SELECT count(*) FROM pedidos") == 1
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 198


@pytest.mark.parametrize("same_customer", [False, True])
def test_concurrent_last_unit(client, same_customer):
    auth = headers(client)
    cid2 = 1 if same_customer else new_customer(client, auth)["id_cliente"]
    with db() as conn:
        conn.execute("UPDATE medicamentos SET stock=1 WHERE id_medicamento=1")
    barrier = Barrier(2)
    def buy(cid):
        barrier.wait(timeout=10)
        return client.post("/api/pedidos", headers=auth, json=order(cid, qty=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(buy, [1, cid2]))
    assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 0
    assert scalar("SELECT count(*) FROM pedidos") == 1


def test_concurrent_retry_only_one_discount(client):
    auth = headers(client)
    body = order()
    barrier = Barrier(2)
    def buy(_):
        barrier.wait(timeout=10)
        return client.post("/api/pedidos", headers=auth, json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(buy, range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 198
    assert scalar("SELECT count(*) FROM movimientos_inventario") == 1


def test_receipt_access_and_snapshot(client):
    auth = headers(client)
    cid = new_customer(client, auth)["id_cliente"]
    receipt = client.post("/api/pedidos", headers=auth, json=order(cid)).json()
    route = f"/api/pedidos/{receipt['id_pedido']}/comprobante"
    assert client.get(route, headers=headers(client, "cliente@mail.com")).status_code == 404
    with db() as conn:
        conn.execute("UPDATE clientes SET nombre='Cambiado' WHERE id_cliente=%s", (cid,))
        conn.execute("UPDATE medicamentos SET nombre='Cambiado',precio=1 WHERE id_medicamento=1")
    assert client.get(route, headers=auth).json() == receipt
    assert client.get(route, headers=headers(client, "admin@farmacia.com")).status_code == 200


def test_only_admin_manages_inventory_and_duplicate_items(client):
    nuevo = {"id_laboratorio": 1, "id_categoria": 1, "nombre": "Ibuprofeno", "precio": 6000}
    for correo in ("empleado@farmacia.com", "cliente@mail.com"):
        auth = headers(client, correo)
        assert client.post("/api/medicamentos", headers=auth, json=nuevo).status_code == 403
        assert client.patch("/api/medicamentos/1/stock", headers=auth,
                            json={"cantidad": 10, "motivo": "Compra"}).status_code == 403
        assert client.delete("/api/medicamentos/1", headers=auth).status_code == 403
        assert client.get("/api/inventario", headers=auth).status_code == 403
    assert client.post("/api/medicamentos", json=nuevo).status_code == 401
    admin = headers(client, "admin@farmacia.com")
    body = order()
    assert client.post("/api/pedidos", headers=admin, json=body).status_code == 403
    body["items"].append(copy.deepcopy(body["items"][0]))
    assert client.post("/api/pedidos", headers=headers(client), json=body).status_code == 422


def test_admin_creates_and_edits_medication(client):
    admin = headers(client, "admin@farmacia.com")
    lab = client.post("/api/laboratorios", headers=admin, json={"nombre": "Tecnoquímicas", "pais": "Colombia"})
    cat = client.post("/api/categorias", headers=admin, json={"nombre": "Antiinflamatorios"})
    assert lab.status_code == 201 and cat.status_code == 201
    assert client.post("/api/categorias", headers=admin, json={"nombre": "Antiinflamatorios"}).status_code == 409
    nuevo = {"id_laboratorio": lab.json()["id_laboratorio"], "id_categoria": cat.json()["id_categoria"],
             "nombre": "Ibuprofeno", "mg": 400, "forma": "Tableta", "requiere_formula": False,
             "precio": 6000, "stock_inicial": 30}
    r = client.post("/api/medicamentos", headers=admin, json=nuevo)
    assert r.status_code == 201, r.text
    med = r.json()
    assert (med["stock_fisico"], med["disponible"], med["laboratorio"]) == (30, 30, "Tecnoquímicas")
    assert scalar("SELECT cantidad FROM movimientos_inventario WHERE id_medicamento=%s AND tipo='entrada'",
                  (med["id_medicamento"],)) == 30
    catalogo = client.get("/api/medicamentos", params={"q": "Ibuprofeno"}).json()
    assert catalogo[0]["nombre"] == "Ibuprofeno 400mg" and catalogo[0]["stock"] == 30
    # Editar no cambia el stock; solo los datos descriptivos y el precio.
    edit = {k: v for k, v in nuevo.items() if k != "stock_inicial"} | {"precio": 6500, "requiere_formula": True}
    r = client.put(f"/api/medicamentos/{med['id_medicamento']}", headers=admin, json=edit)
    assert r.status_code == 200 and float(r.json()["precio"]) == 6500 and r.json()["stock_fisico"] == 30
    assert r.json()["requiere_formula"] is True
    assert client.put("/api/medicamentos/9999", headers=admin, json=edit).status_code == 404
    assert client.post("/api/medicamentos", headers=admin, json=nuevo | {"id_laboratorio": 9999}).status_code == 422
    assert client.post("/api/medicamentos", headers=admin, json=nuevo | {"precio": -1}).status_code == 422


def test_stock_adjustment_is_logged_and_respects_reservations(client):
    admin = headers(client, "admin@farmacia.com")
    r = client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": 25, "motivo": "Compra a proveedor"})
    assert r.status_code == 200 and r.json()["stock_fisico"] == 225
    r = client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": -5, "motivo": "Vencidos"})
    assert r.status_code == 200 and r.json()["stock_fisico"] == 220
    movs = client.get("/api/inventario/movimientos", headers=admin, params={"id_medicamento": 1}).json()
    assert [(m["tipo"], m["cantidad"], m["usuario"]) for m in movs[:2]] == [
        ("ajuste", -5, "admin@farmacia.com"), ("entrada", 25, "admin@farmacia.com")]
    with db() as conn:
        conn.execute("INSERT INTO reservas (id_cliente,id_medicamento,cantidad) VALUES (1,1,200)")
    r = client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": -30, "motivo": "Merma"})
    assert r.status_code == 409
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 220
    assert client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": 0, "motivo": "Nada"}).status_code == 422
    assert client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": 5}).status_code == 422
    assert client.patch("/api/medicamentos/9999/stock", headers=admin, json={"cantidad": 5, "motivo": "X12"}).status_code == 404


def test_retired_medication_not_sold_and_receipts_kept(client):
    auth, admin = headers(client), headers(client, "admin@farmacia.com")
    sale = client.post("/api/pedidos", headers=auth, json=order(qty=1))
    assert sale.status_code == 201
    assert client.delete("/api/medicamentos/1", headers=admin).json()["activo"] is False
    assert all(m["id_medicamento"] != 1 for m in client.get("/api/medicamentos").json())
    assert client.post("/api/pedidos", headers=auth, json=order(qty=1)).status_code == 404
    receipt = client.get(f"/api/pedidos/{sale.json()['id_pedido']}/comprobante", headers=auth)
    assert receipt.status_code == 200 and receipt.json()["items"][0]["id_medicamento"] == 1
    inv = client.get("/api/inventario", headers=admin).json()
    assert [m["activo"] for m in inv if m["id_medicamento"] == 1] == [False]
    assert client.post("/api/medicamentos/1/reactivar", headers=admin).json()["activo"] is True
    assert client.post("/api/pedidos", headers=auth, json=order(qty=1)).status_code == 201


def test_concurrent_adjustment_and_sale_keep_stock_consistent(client):
    auth, admin = headers(client), headers(client, "admin@farmacia.com")
    with db() as conn:
        conn.execute("UPDATE medicamentos SET stock=1 WHERE id_medicamento=1")
    barrier = Barrier(2)
    def sell():
        barrier.wait(timeout=10)
        return client.post("/api/pedidos", headers=auth, json=order(qty=1))
    def adjust():
        barrier.wait(timeout=10)
        return client.patch("/api/medicamentos/1/stock", headers=admin, json={"cantidad": -1, "motivo": "Dañado"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        s, a = pool.submit(sell), pool.submit(adjust)
        codes = sorted([s.result().status_code, a.result().status_code])
    # Solo una operación puede usar la última unidad; el stock nunca queda negativo.
    assert codes in ([200, 409], [201, 409]), codes
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 0


def test_disabled_account_rejected(client):
    auth = headers(client)
    with db() as conn:
        conn.execute("UPDATE usuarios SET activo=FALSE WHERE id_usuario=2")
    assert client.get("/api/pedidos", headers=auth).status_code == 401


def test_migration_preserves_data_and_is_repeatable(client):
    auth = headers(client)
    receipt = client.post("/api/pedidos", headers=auth, json=order()).json()
    migration = (ROOT / "migrations" / "001_ventas.sql").read_text(encoding="utf-8")
    with db() as conn:
        conn.execute(migration)
        conn.execute(migration)
    assert scalar("SELECT count(*) FROM medicamentos") == 5
    assert scalar("SELECT stock FROM medicamentos WHERE id_medicamento=1") == 198
    assert scalar("SELECT comprobante FROM pedidos") == receipt


def test_report_sales_and_inventory(client):
    auth, admin = headers(client), headers(client, "admin@farmacia.com")
    cli = headers(client, "cliente@mail.com")
    empty = client.get("/api/informes", headers=admin).json()
    assert empty["ventas"]["resumen"]["pedidos"] == 0 and empty["ventas"]["mas_vendidos"] == []
    assert empty["inventario"]["productos"] == 5 and empty["inventario"]["unidades"] == 610
    # Venta presencial: 2 Acetaminofén (3500) + compra en línea: 1 Aspirina (5200).
    assert client.post("/api/pedidos", headers=auth, json=order(qty=2)).status_code == 201
    online = {"clave_operacion": str(uuid4()), "metodo_pago": "Nequi/PSE", "direccion": "Calle 1",
              "cliente": {"tipo_documento": "CC", "documento": "1098765432", "nombre": "Laura", "apellido": "Gómez",
                          "correo": "cliente@mail.com", "celular": "3001234567"},
              "items": [{"id_medicamento": 2, "cantidad": 1}]}
    assert client.post("/api/pedidos", headers=cli, json=online).status_code == 201, "compra en línea"
    r = client.get("/api/informes", headers=admin, params={"umbral": 100})
    assert r.status_code == 200, r.text
    data = r.json()
    res = data["ventas"]["resumen"]
    assert (res["pedidos"], res["unidades"], res["clientes"]) == (2, 3, 1)
    assert float(res["total_vendido"]) == 12200 and float(res["ticket_promedio"]) == 6100
    canales = {c["canal"]: float(c["total"]) for c in data["ventas"]["por_canal"]}
    assert canales == {"Presencial (empleado)": 7000, "En línea (cliente)": 5200}
    assert {m["metodo_pago"] for m in data["ventas"]["por_metodo_pago"]} == {"Efectivo", "Nequi/PSE"}
    top = data["ventas"]["mas_vendidos"][0]
    assert (top["nombre"], top["unidades"], float(top["ingresos"])) == ("Acetaminofén 500mg", 2, 7000)
    inv = data["inventario"]
    assert inv["unidades"] == 607 and inv["bajo_stock"] == 2  # Amoxicilina (80) y Vitamina C (60)
    assert sum(float(d["total"]) for d in data["ventas"]["por_dia"]) == 12200
    # Un periodo sin ventas no cuenta los pedidos de hoy.
    old = client.get("/api/informes", headers=admin, params={"desde": "2020-01-01", "hasta": "2020-01-31"}).json()
    assert old["ventas"]["resumen"]["pedidos"] == 0 and old["inventario"]["unidades"] == 607
    # Un medicamento retirado sale del inventario del informe, pero no de las ventas.
    client.delete("/api/medicamentos/1", headers=admin)
    after = client.get("/api/informes", headers=admin).json()
    assert after["inventario"]["productos"] == 4 and after["ventas"]["resumen"]["unidades"] == 3


def test_report_validation_and_permissions(client):
    admin = headers(client, "admin@farmacia.com")
    assert client.get("/api/informes", headers=headers(client)).status_code == 403
    assert client.get("/api/informes", headers=headers(client, "cliente@mail.com")).status_code == 403
    assert client.get("/api/informes").status_code == 401
    bad = [{"desde": "2026-02-01", "hasta": "2026-01-01"}, {"desde": "2020-01-01", "hasta": "2026-01-01"},
           {"umbral": -1}, {"desde": "no-es-fecha"}]
    for params in bad:
        assert client.get("/api/informes", headers=admin, params=params).status_code == 422, params


def test_initial_password_and_password_change(client):
    # La contraseña antigua de demostración ya no da acceso a las cuentas precargadas.
    old = client.post("/api/auth/login", json={"correo": "admin@farmacia.com", "password": "farmacia123"})
    assert old.status_code == 401
    auth = headers(client, "admin@farmacia.com")
    url = "/api/auth/cambiar-clave"
    assert client.post(url, json={"actual": CLAVE_PRUEBAS, "nueva": "otra-clave-123"}).status_code == 401
    assert client.post(url, headers=auth, json={"actual": "incorrecta", "nueva": "otra-clave-123"}).status_code == 400
    for nueva in ("corta", "farmacia123", CLAVE_PRUEBAS):
        assert client.post(url, headers=auth, json={"actual": CLAVE_PRUEBAS, "nueva": nueva}).status_code == 422, nueva
    assert client.post(url, headers=auth, json={"actual": CLAVE_PRUEBAS, "nueva": "otra-clave-123"}).status_code == 204
    login = lambda pw: client.post("/api/auth/login", json={"correo": "admin@farmacia.com", "password": pw}).status_code
    assert (login(CLAVE_PRUEBAS), login("otra-clave-123")) == (401, 200)
    # Registro de clientes: mínimo 8 caracteres.
    reg = lambda pw: client.post("/api/auth/register", json={"correo": "nuevo@mail.com", "password": pw}).status_code
    assert (reg("1234"), reg("farmacia123"), reg("clave-cliente-1")) == (422, 422, 201)


def test_random_initial_password_when_not_configured(monkeypatch, caplog):
    monkeypatch.setattr(main, "CLAVE_INICIAL", "")
    with caplog.at_level("WARNING", logger="uvicorn.error"), TestClient(main.app) as c:
        line = next(r.getMessage() for r in caplog.records if "Contraseña inicial" in r.getMessage())
        clave = line.split(": ")[1].split("  ")[0]
        assert len(clave) >= 12 and clave != "farmacia123"
        r = c.post("/api/auth/login", json={"correo": "empleado@farmacia.com", "password": clave})
        assert r.status_code == 200


def test_warns_accounts_still_using_demo_password(caplog):
    with db() as conn:
        conn.execute("UPDATE usuarios SET password_hash=%s WHERE correo='admin@farmacia.com'", (main.hash_pw("farmacia123"),))
    with caplog.at_level("WARNING", logger="uvicorn.error"), TestClient(main.app):
        pass
    assert any("admin@farmacia.com todavía usa" in r.getMessage() for r in caplog.records)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def test_medication_photo_upload_replace_and_remove(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "IMAGENES_DIR", tmp_path)
    admin = headers(client, "admin@farmacia.com")
    up = lambda data, ctype="image/png", h=admin, mid=1: client.put(
        f"/api/medicamentos/{mid}/imagen", headers={**h, "Content-Type": ctype}, content=data)
    r = up(PNG)
    assert r.status_code == 200, r.text
    url = r.json()["imagen_url"]
    assert url.startswith("/api/imagenes/1-") and url.endswith(".png")
    img = client.get(url)  # pública, como el catálogo
    assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
    assert [m["imagen_url"] for m in client.get("/api/medicamentos").json() if m["id_medicamento"] == 1] == [url]
    # Reemplazar borra el archivo anterior.
    url2 = up(JPG, "image/jpeg").json()["imagen_url"]
    assert url2.endswith(".jpg") and client.get(url).status_code == 404 and len(list(tmp_path.iterdir())) == 1
    # Quitar la foto deja el campo vacío y borra el archivo.
    r = client.delete("/api/medicamentos/1/imagen", headers=admin)
    assert r.status_code == 200 and r.json()["imagen_url"] is None and not list(tmp_path.iterdir())


def test_medication_photo_validation(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "IMAGENES_DIR", tmp_path)
    admin = headers(client, "admin@farmacia.com")
    up = lambda data, h=admin, mid=1: client.put(
        f"/api/medicamentos/{mid}/imagen", headers={**h, "Content-Type": "image/png"}, content=data)
    assert up(b"<svg onload=alert(1)>").status_code == 415           # no es una imagen permitida
    assert up(b"GIF89a" + b"\x00" * 20).status_code == 415
    assert up(PNG + b"\x00" * (2 * 1024 * 1024)).status_code == 413  # más de 2 MB
    assert up(PNG, mid=9999).status_code == 404
    assert up(PNG, h=headers(client)).status_code == 403             # empleado
    assert client.put("/api/medicamentos/1/imagen", content=PNG).status_code == 401
    assert not list(tmp_path.iterdir())
    for nombre in ("..%2F..%2Fmain.py", "main.py", "1-zz.png"):
        assert client.get(f"/api/imagenes/{nombre}").status_code == 404
