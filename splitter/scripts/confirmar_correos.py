"""Cuentas que existían antes de pedir confirmar el correo.

    .venv/bin/python -m scripts.confirmar_correos                     lista las cuentas sin confirmar (no envía nada)
    .venv/bin/python -m scripts.confirmar_correos --enviar            les manda el correo para confirmar
    .venv/bin/python -m scripts.confirmar_correos --marcar a@b.com    marca como confirmadas esas cuentas (de confianza)

Para --enviar hacen falta SPLITTER_PUBLIC_URL (los enlaces apuntan ahí) y el SMTP en .env.
Se manda un correo por segundo para no saturar el servidor de correo.
"""
import argparse
import time

from sqlalchemy import select

from app import config
from app.database import SessionLocal
from app.models.tablas import Usuario
from app.repositories import usuarios as repo_usuarios
from app.seed import migrar
from app.services import verificacion


def sin_confirmar() -> list:
    with SessionLocal() as db:
        return list(db.scalars(
            select(Usuario)
            .where(Usuario.email_verificado.is_(False), Usuario.estado == "activo")
            .order_by(Usuario.creado_en)
        ))


def _oculto(email: str) -> str:
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:2]}***@{dominio}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--enviar", action="store_true", help="enviar el correo de confirmación")
    parser.add_argument("--marcar", nargs="+", metavar="EMAIL", help="marcar estas cuentas como confirmadas")
    args = parser.parse_args()
    migrar()  # por si la base aún no tiene las columnas nuevas

    if args.marcar:
        with SessionLocal() as db:
            for email in args.marcar:
                usuario = repo_usuarios.buscar_por_email(db, email.strip().lower())
                if usuario is None:
                    print(f"No existe: {email}")
                    continue
                usuario.email_verificado = True
                print(f"Confirmada: {usuario.email}")
            db.commit()
        return

    cuentas = sin_confirmar()
    print(f"{len(cuentas)} cuenta(s) sin confirmar el correo:")
    for u in cuentas:
        print(f"  {_oculto(u.email):30} creada {u.creado_en:%d/%m/%Y}")
    if not cuentas:
        return
    if not args.enviar:
        print("\nNo se envió nada. Usa --enviar para mandarles el correo.")
        return
    if not config.PUBLIC_URL:
        raise SystemExit("Falta SPLITTER_PUBLIC_URL en .env: los enlaces del correo deben apuntar a la página pública.")
    if not config.SMTP_USER:
        raise SystemExit("Falta SPLITTER_SMTP_USER en .env: sin SMTP los correos no salen.")
    enviados = 0
    for u in cuentas:
        try:
            verificacion.enviar_confirmacion(u, config.PUBLIC_URL)
            enviados += 1
            print(f"Enviado: {_oculto(u.email)}")
        except Exception as error:  # límite por cuenta u otro fallo: se sigue con los demás
            print(f"No se envió a {_oculto(u.email)}: {getattr(error, 'detail', error)}")
        time.sleep(1)
    print(f"\n{enviados} de {len(cuentas)} correos enviados.")


if __name__ == "__main__":
    main()
