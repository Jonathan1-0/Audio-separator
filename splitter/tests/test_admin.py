"""Pruebas del panel de administración."""
from .conftest import registrar
import uuid

PASSWORD = "clave-segura-1"


def _token(cliente, email, password):
    return {"Authorization": f"Bearer {cliente.post('/auth/login', json={'email': email, 'password': password}).cookies['splitter_sesion']}"}


def _admin(cliente):
    return _token(cliente, "admin@pruebas.com", "admin-pruebas-1")


def _usuario(cliente):
    email = f"adm_{uuid.uuid4().hex[:10]}@example.com"
    registrar(cliente, json={"email": email, "nombre": "Usuario Panel", "password": PASSWORD})
    return email, _token(cliente, email, PASSWORD)


def test_solo_el_admin_entra(cliente):
    _, cab = _usuario(cliente)
    for ruta in ("/admin/resumen", "/admin/usuarios", "/admin/trabajos", "/admin/pagos"):
        assert cliente.get(ruta, headers=cab).status_code == 403, ruta
        assert cliente.get(ruta).status_code == 401, ruta


def test_resumen(cliente):
    datos = cliente.get("/admin/resumen", headers=_admin(cliente)).json()
    assert datos["usuarios"]["total"] >= 1
    assert "admin" in datos["usuarios"]["por_plan"]
    assert set(datos["cola"]) == {"en_cola", "procesando", "trabajos_en_memoria"}


def test_buscar_y_suspender(cliente):
    email, cab = _usuario(cliente)
    adm = _admin(cliente)
    encontrados = cliente.get("/admin/usuarios", params={"q": email.upper()}, headers=adm).json()
    assert encontrados["total"] == 1
    fila = encontrados["usuarios"][0]
    assert fila["email"] == email and fila["plan"] == "gratis" and fila["trabajos"] == 0

    assert cliente.post(f"/admin/usuarios/{fila['id']}/estado", json={"estado": "suspendido"}, headers=adm).status_code == 200
    assert cliente.get("/suscripcion", headers=cab).status_code == 401  # sus sesiones se cerraron
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 403
    cliente.post(f"/admin/usuarios/{fila['id']}/estado", json={"estado": "activo"}, headers=adm)
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_admin_no_se_suspende_a_si_mismo(cliente):
    adm = _admin(cliente)
    yo = cliente.get("/admin/usuarios", params={"q": "admin@pruebas.com"}, headers=adm).json()["usuarios"][0]
    assert cliente.post(f"/admin/usuarios/{yo['id']}/estado", json={"estado": "suspendido"}, headers=adm).status_code == 400
    assert cliente.post(f"/admin/usuarios/{yo['id']}/estado", json={"estado": "raro"}, headers=adm).status_code == 400


def test_listas_de_trabajos_y_pagos(cliente):
    adm = _admin(cliente)
    assert "trabajos" in cliente.get("/admin/trabajos", params={"estado": "completado"}, headers=adm).json()
    assert "pagos" in cliente.get("/admin/pagos", headers=adm).json()


def test_base_de_datos(cliente):
    email, cab = _usuario(cliente)
    adm = _admin(cliente)
    assert cliente.get("/admin/base", headers=cab).status_code == 403
    assert cliente.get("/admin/base/usuarios", headers=cab).status_code == 403
    tablas = {t["nombre"]: t["filas"] for t in cliente.get("/admin/base", headers=adm).json()}
    assert tablas["usuarios"] >= 2 and "resultados" in tablas
    datos = cliente.get("/admin/base/usuarios", headers=adm).json()
    fila = next(f for f in datos["filas"] if email in f)
    clave = datos["columnas"].index("password_hash")
    assert fila[clave] == "••••"
    sesiones = cliente.get("/admin/base/sesiones", headers=adm).json()
    assert all(f[sesiones["columnas"].index("token")] == "••••" for f in sesiones["filas"])
    assert cliente.get("/admin/base/no_existe", headers=adm).status_code == 404
