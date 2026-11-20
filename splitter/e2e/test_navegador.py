"""Recorridos completos en el navegador: lo que haría una persona."""
import re
import uuid

from playwright.sync_api import expect


PASSWORD = "clave-e2e-segura"


def _ultimo_enlace(servidor, ancla: str) -> str:
    texto = servidor["log"].read_text()
    return re.findall(rf"/#{ancla}=\S+", texto)[-1]


def _ultimo_codigo(servidor) -> str:
    return re.findall(r"Tu código de Splitter: (\d{6})", servidor["log"].read_text())[-1]


def _registrarse(pagina, email):
    pagina.goto("/")
    pagina.get_by_role("button", name="Regístrate").click()
    pagina.get_by_label("Nombre").fill("Persona E2E")
    pagina.locator("#login-email").fill(email)
    pagina.locator("#login-password").fill(PASSWORD)
    pagina.locator("#login-confirm").fill(PASSWORD)
    pagina.get_by_role("button", name="Crear cuenta").click()
    # Llega un código al correo (en las pruebas se escribe en el log del servidor)
    expect(pagina.locator("#code-field")).to_be_visible()
    expect(pagina.locator("#login-message")).to_contain_text("Te enviamos un código")
    pagina.locator("#login-code").fill(_ultimo_codigo(pagina.servidor))
    pagina.locator("#login-submit").click()
    expect(pagina.locator("#login-dialog")).not_to_be_visible()


def _abrir_menu(pagina):
    pagina.locator("#profile-button").click()
    expect(pagina.locator("#profile-menu")).to_be_visible()


def test_registro_con_codigo_y_separar(pagina, servidor, audio_wav):
    email = f"e2e_{uuid.uuid4().hex[:8]}@ejemplo.test"
    _registrarse(pagina, email)

    # La sesión vive en una cookie que el JavaScript no puede leer
    assert pagina.evaluate("document.cookie") == ""
    cookie = next(c for c in pagina.context.cookies() if c["name"] == "splitter_sesion")
    assert cookie["httpOnly"] and cookie["sameSite"] == "Lax"

    _abrir_menu(pagina)
    expect(pagina.locator("#menu-email")).to_have_text(email)
    # El código del registro ya confirmó el correo: no aparece el aviso de confirmarlo
    expect(pagina.locator("#menu-verificar")).to_be_hidden()
    pagina.keyboard.press("Escape")

    # El paso 03 solo aparece al separar instrumentos
    expect(pagina.locator("#tracks-heading")).to_be_hidden()
    pagina.locator("input[name=mode][value=instruments]").check(force=True)
    expect(pagina.locator("#tracks-heading")).to_be_visible()
    pagina.locator("input[name=mode][value=clean]").check(force=True)
    expect(pagina.locator("#tracks-heading")).to_be_hidden()

    # Separar un audio y descargar el ZIP
    pagina.locator("input[name=mode][value=vocals]").check(force=True)
    expect(pagina.locator("#tracks-heading")).to_be_hidden()
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


def test_cuenta_sin_confirmar_pide_el_codigo_al_entrar(pagina, servidor):
    email = f"e2epend_{uuid.uuid4().hex[:8]}@ejemplo.test"
    pagina.goto("/")
    pagina.get_by_role("button", name="Regístrate").click()
    pagina.get_by_label("Nombre").fill("Pendiente E2E")
    pagina.locator("#login-email").fill(email)
    pagina.locator("#login-password").fill(PASSWORD)
    pagina.locator("#login-confirm").fill(PASSWORD)
    pagina.get_by_role("button", name="Crear cuenta").click()
    expect(pagina.locator("#code-field")).to_be_visible()
    # Cierra sin escribir el código y luego intenta entrar
    pagina.reload()
    pagina.get_by_role("button", name="Inicia sesión").click()
    pagina.locator("#login-email").fill(email)
    pagina.locator("#login-password").fill(PASSWORD)
    pagina.locator("#login-submit").click()
    expect(pagina.locator("#code-field")).to_be_visible()
    pagina.locator("#login-code").fill(_ultimo_codigo(servidor))
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


def test_foto_de_perfil(pagina, tmp_path):
    email = f"e2efoto_{uuid.uuid4().hex[:8]}@ejemplo.test"
    _registrarse(pagina, email)
    # PNG de 1x1
    foto = tmp_path / "yo.png"
    foto.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2a1a3"
        "e40000000049454e44ae426082"))
    _abrir_menu(pagina)
    pagina.locator("#menu-profile").click()
    # Se guarda sola al elegirla, sin pulsar "Guardar"
    pagina.locator("#perfil-archivo").set_input_files(str(foto))
    expect(pagina.locator("#perfil-guardar-foto")).to_be_hidden()
    expect(pagina.locator("#perfil-mensaje")).to_be_hidden()
    expect(pagina.locator("#perfil-foto")).to_have_attribute("src", re.compile(r"/auth/fotos/"))


def test_atras_y_adelante_entre_pantallas(pagina, audio_wav):
    pagina.goto("/")
    pagina.locator("input[name=mode][value=vocals]").check(force=True)
    pagina.locator("#audio-file").set_input_files(str(audio_wav))
    pagina.locator("#start-button").click()
    expect(pagina.locator("#results-panel")).to_be_visible(timeout=60_000)
    # Atrás: vuelve al inicio sin perder el trabajo
    pagina.go_back()
    expect(pagina.locator("#splitter-form")).to_be_visible()
    expect(pagina.locator("#results-panel")).to_be_hidden()
    # Adelante: reabre los resultados
    pagina.go_forward()
    expect(pagina.locator("#results-panel")).to_be_visible(timeout=15_000)
    # "Cómo funciona" en resultados abre la explicación
    pagina.locator(".nav-how", has_text="Cómo funciona").click()
    expect(pagina.locator("#how-dialog")).to_be_visible()
