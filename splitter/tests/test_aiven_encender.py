"""El script que vuelve a encender la base de Aiven, con la API simulada."""
import pytest

from scripts import aiven_encender as aiven


@pytest.fixture
def api(monkeypatch):
    """Aiven de mentira: devuelve los estados de la lista, en orden, y anota las llamadas."""
    llamadas, estados = [], []

    def llamar(metodo, ruta, cuerpo=None):
        llamadas.append((metodo, ruta, cuerpo))
        return {"service": {"state": estados.pop(0) if len(estados) > 1 else estados[0]}} if metodo == "GET" else {}

    for variable, valor in (("AIVEN_TOKEN", "t"), ("AIVEN_PROYECTO", "p"), ("AIVEN_SERVICIO", "s")):
        monkeypatch.setenv(variable, valor)
    monkeypatch.setattr(aiven, "_llamar", llamar)
    monkeypatch.setattr(aiven.time, "sleep", lambda _s: None)
    monkeypatch.setattr(aiven, "_tocar_base", lambda: llamadas.append(("SELECT 1",)))
    return llamadas, estados


def test_encendida_solo_hace_una_consulta(api):
    llamadas, estados = api
    estados += ["RUNNING"]
    assert aiven.revisar() == 0
    assert llamadas == [("GET", "/project/p/service/s", None), ("SELECT 1",)]


def test_apagada_se_enciende_y_espera(api):
    llamadas, estados = api
    estados += ["POWEROFF", "REBUILDING", "REBUILDING", "RUNNING"]
    assert aiven.revisar() == 0
    assert ("PUT", "/project/p/service/s", {"powered": True}) in llamadas
    assert llamadas[-1] == ("SELECT 1",)


def test_mientras_aiven_la_prepara_no_hace_nada(api):
    llamadas, estados = api
    estados += ["REBALANCING"]
    assert aiven.revisar() == 0
    assert [ll[0] for ll in llamadas] == ["GET"]


def test_sin_claves_avisa(monkeypatch):
    monkeypatch.setenv("AIVEN_TOKEN", "")
    with pytest.raises(SystemExit, match="AIVEN_TOKEN"):
        aiven.estado()
