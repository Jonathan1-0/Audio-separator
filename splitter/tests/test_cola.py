"""La cola da prioridad a Pro: sus trabajos pasan antes que los de Gratis y sin cuenta."""
from pathlib import Path

from app.engine import build_engine
from app.jobs import Job, JobManager


def _job(nombre: str, prioridad: int) -> Job:
    return Job(id=nombre, usuario_id=None, original_name=nombre, preset="2stem", wanted_stems=["vocals"],
               input_path=Path("/tmp/x.wav"), out_dir=Path("/tmp/x"), prioridad=prioridad)


def test_pro_pasa_antes_que_gratis():
    cola = JobManager(build_engine())  # sin arrancar: nadie saca trabajos
    for nombre, prioridad in [("gratis1", 1), ("gratis2", 1), ("pro1", 0), ("gratis3", 1), ("pro2", 0)]:
        cola._encolar(_job(nombre, prioridad))
    # Lo que ve la página
    assert [cola.queue_position(n) for n in ("pro1", "pro2", "gratis1", "gratis2", "gratis3")] == [1, 2, 3, 4, 5]
    # Lo que sacan los trabajadores, en ese mismo orden
    sacados = [cola._queue.get_nowait()[2] for _ in range(5)]
    assert sacados == ["pro1", "pro2", "gratis1", "gratis2", "gratis3"]
