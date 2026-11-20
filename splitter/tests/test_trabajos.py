"""Pruebas de la separación con el motor simulado."""
import time


def _crear_trabajo(cliente, audio_wav, nombre="cancion.wav", preset="2stem"):
    return cliente.post("/api/jobs", files={"file": (nombre, audio_wav, "audio/wav")}, data={"preset": preset})


def _esperar(cliente, job_id, segundos=60):
    """Espera a que el trabajo termine."""
    limite = time.time() + segundos
    while time.time() < limite:
        datos = cliente.get(f"/api/jobs/{job_id}").json()
        if datos["status"] in ("done", "error"):
            return datos
        time.sleep(0.3)
    raise AssertionError("El trabajo no terminó a tiempo")


def test_rechaza_archivo_que_no_es_audio(cliente):
    res = cliente.post("/api/jobs", files={"file": ("notas.txt", b"hola", "text/plain")}, data={"preset": "2stem"})
    assert res.status_code == 415


def test_trabajo_que_no_existe(cliente):
    assert cliente.get("/api/jobs/noexiste").status_code == 404


def test_separacion_completa_dos_pistas(cliente, audio_wav):
    res = _crear_trabajo(cliente, audio_wav)
    assert res.status_code == 202
    job_id = res.json()["id"]

    final = _esperar(cliente, job_id)
    assert final["status"] == "done"
    assert final["progress"] == 1
    nombres = [pista["name"] for pista in final["stems"]]
    assert nombres == ["vocals", "instrumental"]

    # Vista previa y descarga
    assert cliente.get(f"/api/jobs/{job_id}/stems/vocals/preview").status_code == 200
    descarga = cliente.get(f"/api/jobs/{job_id}/stems/vocals/download", params={"format": "mp3"})
    assert descarga.status_code == 200
    assert len(descarga.content) > 0

    # Formato que no existe
    assert cliente.get(f"/api/jobs/{job_id}/stems/vocals/download", params={"format": "xyz"}).status_code == 400

    # Al borrarlo deja de existir
    assert cliente.delete(f"/api/jobs/{job_id}").status_code == 204
    assert cliente.get(f"/api/jobs/{job_id}").status_code == 404


def test_separacion_de_cuatro_pistas(cliente, audio_wav):
    res = _crear_trabajo(cliente, audio_wav, preset="4stem_fast")
    assert res.status_code == 202
    final = _esperar(cliente, res.json()["id"])
    assert final["status"] == "done"
    assert [p["name"] for p in final["stems"]] == ["vocals", "drums", "bass", "guitar", "piano", "other"]


def test_limpiar_ruido_incluye_ruido_solo_para_escuchar(cliente, audio_wav):
    import io
    import zipfile

    res = _crear_trabajo(cliente, audio_wav, preset="denoise")
    assert res.status_code == 202
    job_id = res.json()["id"]
    final = _esperar(cliente, job_id)
    assert final["status"] == "done"
    pistas = {p["name"]: p for p in final["stems"]}
    assert list(pistas) == ["voice", "noise"]
    assert "download_url" in pistas["voice"]
    assert pistas["noise"].get("solo_escucha") is True and "download_url" not in pistas["noise"]

    # El ruido se escucha, pero no se descarga ni va en el ZIP
    assert cliente.get(f"/api/jobs/{job_id}/stems/noise/preview").status_code == 200
    assert cliente.get(f"/api/jobs/{job_id}/stems/noise/download").status_code == 403
    zip_res = cliente.get(f"/api/jobs/{job_id}/download")
    assert zip_res.status_code == 200
    assert [n for n in zipfile.ZipFile(io.BytesIO(zip_res.content)).namelist()] == ["cancion - voice.wav"]
