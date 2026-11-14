"""Integración con otras UDS: UC12 (exponer inventario) y UC13 (consultar otras UDS)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import main
from test_ventas import client, headers, isolated_database, scalar  # noqa: F401 (fixtures)

CLAVE_UDS = "clave-uds-de-prueba"


@pytest.fixture
def con_clave(monkeypatch):
    monkeypatch.setattr(main, "UDS_API_KEYS", [CLAVE_UDS])
    return {"X-API-Key": CLAVE_UDS}


def test_expone_inventario_en_formato_generico(client, con_clave):
    r = client.get("/api/uds/v1/productos", headers=con_clave)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["uds"] == "FarmaSalud" and body["version"] == "1.0"
    assert body["total"] == len(body["productos"]) == scalar("SELECT count(*) FROM medicamentos WHERE activo")
    p = body["productos"][0]
    assert set(p) == {"codigo", "nombre", "concentracion_mg", "presentacion", "categoria", "laboratorio", "precio",
                      "moneda", "stock_disponible", "requiere_formula", "imagen_url", "uds_origen"}
    assert p["codigo"].startswith("FS-") and p["moneda"] == "COP" and p["uds_origen"] == "FarmaSalud"
    assert "stock_fisico" not in p  # solo se publica lo disponible, no el stock interno


def test_filtros_y_producto_por_codigo(client, con_clave):
    todos = client.get("/api/uds/v1/productos", headers=con_clave).json()["productos"]
    nombre = todos[0]["nombre"]
    filtrados = client.get("/api/uds/v1/productos", params={"q": nombre[:4]}, headers=con_clave).json()
    assert filtrados["total"] >= 1 and all(nombre[:4].lower() in p["nombre"].lower() for p in filtrados["productos"])
    uno = client.get(f"/api/uds/v1/productos/{todos[0]['codigo'].lower()}", headers=con_clave)
    assert uno.status_code == 200 and uno.json()["codigo"] == todos[0]["codigo"]
    assert client.get("/api/uds/v1/productos/FS-999999", headers=con_clave).status_code == 404
    assert client.get("/api/uds/v1/productos/abc", headers=con_clave).status_code == 404


def test_api_publica_exige_clave(client, con_clave):
    assert client.get("/api/uds/v1/productos").status_code == 401
    assert client.get("/api/uds/v1/productos", headers={"X-API-Key": "otra"}).status_code == 401


def test_sin_claves_configuradas_es_abierta(client, monkeypatch):
    monkeypatch.setattr(main, "UDS_API_KEYS", [])
    assert client.get("/api/uds/v1/productos").status_code == 200


class _OtraUDS(BaseHTTPRequestHandler):
    respuesta = b"{}"
    recibido = {}

    def do_GET(self):
        _OtraUDS.recibido = {"ruta": self.path, "clave": self.headers.get("X-API-Key")}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_OtraUDS.respuesta)

    def log_message(self, *args):
        pass


@pytest.fixture
def otra_uds(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _OtraUDS)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/api/productos"
    monkeypatch.setattr(main, "UDS_EXTERNAS", {"drogueria norte": {"nombre": "Drogueria Norte", "url": url,
                                                                    "api_key": "k-norte"}})
    yield _OtraUDS
    srv.shutdown()


def test_consulta_otra_uds(client, otra_uds):
    otra_uds.respuesta = json.dumps({"productos": [
        {"codigo": "DN-1", "nombre": "Ibuprofeno", "precio": 4500, "stock_disponible": 12, "campo_extra": 1},
        {"nombre": "sin codigo ni precio"},
    ]}).encode()
    admin = headers(client, "admin@farmacia.com")
    assert client.get("/api/uds/externas", headers=admin).json()[0]["nombre"] == "Drogueria Norte"
    r = client.get("/api/uds/externas/Drogueria Norte/productos", params={"q": "ibu"}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and body["descartados"] == 1
    assert body["productos"][0]["uds_origen"] == "Drogueria Norte" and body["productos"][0]["moneda"] == "COP"
    assert otra_uds.recibido == {"ruta": "/api/productos?q=ibu", "clave": "k-norte"}


def test_consulta_otra_uds_errores(client, otra_uds):
    admin = headers(client, "admin@farmacia.com")
    otra_uds.respuesta = b"<html>no es json</html>"
    assert client.get("/api/uds/externas/drogueria norte/productos", headers=admin).status_code == 502
    assert client.get("/api/uds/externas/no-existe/productos", headers=admin).status_code == 404
    assert client.get("/api/uds/externas/drogueria norte/productos",
                      headers=headers(client)).status_code == 403  # empleado: solo el administrador
