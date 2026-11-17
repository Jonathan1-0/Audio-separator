"""Recorridos completos en el navegador: lo que haría una persona."""
import re
import uuid

from playwright.sync_api import expect

from app.services import dos_pasos

PASSWORD = "clave-e2e-segura"


def _ultimo_enlace(servidor, ancla: str) -> str:
    texto = servidor["log"].read_text()
    return re.findall(rf"/#{ancla}=\S+", texto)[-1]


def _registrarse(pagina, email):
    pagina.goto("/")
    pagina.get_by_role("button", name="Regístrate").click()
    pagina.get_by_label("Nombre").fill("Persona E2E")
    pagina.locator("#login-email").fill(email)
    pagina.locator("#login-password").fill(PASSWORD)
    pagina.locator("#login-confirm").fill(PASSWORD)
    pagina.get_by_role("button", name="Crear cuenta").click()
    expect(pagina.locator("#login-dialog")).not_to_be_visible()


def _abrir_menu(pagina):
    pagina.locator("#profile-button").click()
    expect(pagina.locator("#profile-menu")).to_be_visible()


def test_registro_confirmar_correo_y_separar(pagina, servidor, audio_wav):
    email = f"e2e_{uuid.uuid4().hex[:8]}@ejemplo.test"
    _registrarse(pagina, email)

    # La sesión vive en una cookie que el JavaScript no puede leer
    assert pagina.evaluate("document.cookie") == ""
    cookie = next(c for c in pagina.context.cookies() if c["name"] == "splitter_sesion")
    assert cookie["httpOnly"] and cookie["sameSite"] == "Lax"

    _abrir_menu(pagina)
    expect(pagina.locator("#menu-email")).to_have_text(email)
    expect(pagina.locator("#menu-verificar")).to_be_visible()

    # Abrir el enlace del correo confirma la cuenta
    pagina.goto(_ultimo_enlace(servidor, "verificar"))
    expect(pagina.get_by_role("heading", name="Correo confirmado")).to_be_visible()
    pagina.get_by_role("button", name="Entendido").click()
    _abrir_menu(pagina)
    expect(pagina.locator("#menu-verificar")).to_be_hidden()
    pagina.keyboard.press("Escape")

    # Separar un audio y descargar el ZIP
    pagina.locator("input[name=mode][value=vocals]").check(force=True)
    pagina.locator("#audio-file").set_input_files(str(audio_wav))
    pagina.locator("#start-button").click()
    expect(pagina.locator("#results-panel")).to_be_visible(timeout=60_000)
    with pagina.expect_download() as descarga:
        pagina.locator("#download-all").click()
    assert descarga.value.suggested_filename.endswith(".zip")

    # Mis audios (plan Gratis) muestra el trabajo
    _abrir_menu(pagina)
    pagina.locator("#menu-audios").click()
    expect(pagina.get_by_role("dialog", name="Mis audios").get_by_text("tono", exact=True)).to_be_visible()


def test_dos_pasos_desde_el_perfil(pagina, servidor):
    email = f"e2e2fa_{uuid.uuid4().hex[:8]}@ejemplo.test"
    _registrarse(pagina, email)
    _abrir_menu(pagina)
    pagina.locator("#menu-profile").click()
    pagina.locator("#boton-dos-pasos").click()
    expect(pagina.locator("#dos-qr")).to_have_attribute("src", re.compile("^data:image/svg"))
    secreto = pagina.locator("#dos-secreto").inner_text().replace(" ", "")
    pagina.locator("#dos-codigo").fill(dos_pasos.codigo_actual(secreto))
    pagina.locator("#dos-guardar").click()
    expect(pagina.locator("#dos-respaldo li")).to_have_count(8)
    respaldo = pagina.locator("#dos-respaldo li").first.inner_text()
    pagina.locator("#dos-guardar").click()
    expect(pagina.locator("#valor-dos-pasos")).to_have_text("Activada")
    pagina.keyboard.press("Escape")

    # Al volver a entrar se pide el código
    _abrir_menu(pagina)
    pagina.locator("#menu-logout").click()
    pagina.get_by_role("button", name="Inicia sesión").click()
    pagina.locator("#login-email").fill(email)
    pagina.locator("#login-password").fill(PASSWORD)
    pagina.locator("#login-submit").click()
    expect(pagina.locator("#code-field")).to_be_visible()
    pagina.locator("#login-code").fill(respaldo)
    pagina.locator("#login-submit").click()
    expect(pagina.locator("#login-dialog")).not_to_be_visible()
    _abrir_menu(pagina)
    expect(pagina.locator("#menu-email")).to_have_text(email)


def test_paginas_publicas(pagina):
    for ruta, titulo in [("/ayuda.html", "Ayuda"), ("/privacidad.html", "Aviso de privacidad"), ("/terminos.html", "Términos y condiciones")]:
        pagina.goto(ruta)
        expect(pagina.get_by_role("heading", level=1)).to_have_text(titulo)
    respuesta = pagina.goto("/no-existe")
    assert respuesta.status == 404
    expect(pagina.get_by_role("heading", name="Aquí no suena nada")).to_be_visible()


def test_panel_pide_ser_admin(pagina):
    pagina.goto("/admin.html")
    expect(pagina.locator("#admin-aviso")).to_contain_text("Inicia sesión")


def test_todo_el_recuadro_abre_el_selector(pagina, audio_wav):
    pagina.goto("/")
    recuadro = pagina.locator("#dropzone")
    recuadro.scroll_into_view_if_needed()
    caja = recuadro.bounding_box()
    # Un clic en una esquina vacía, lejos de "elige uno"
    with pagina.expect_file_chooser() as selector:
        pagina.mouse.click(caja["x"] + 40, caja["y"] + caja["height"] - 30)
    selector.value.set_files(str(audio_wav))
    expect(pagina.locator("#file-summary")).to_be_visible()
    expect(pagina.locator("#file-name")).to_contain_text("tono")
    # Con un archivo elegido, el clic ya no abre el selector (para no reemplazarlo sin querer)
    abiertos = []
    pagina.on("filechooser", lambda f: abiertos.append(f))
    pagina.mouse.click(caja["x"] + 40, caja["y"] + caja["height"] - 30)
    pagina.wait_for_timeout(500)
    assert abiertos == []
