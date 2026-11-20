"""Las 9 tablas de la base. Todas las fechas se guardan en UTC.

Los valores permitidos de cada estado están en CHECK de la base (migración 0007), así que
una fila con un estado inventado no se puede guardar."""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    false,
    true,
)
from sqlalchemy.orm import relationship

from ..database import Base, ahora_utc


def _en(columna: str, *valores: str) -> str:
    """Condición CHECK: la columna solo acepta esos valores."""
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(_en("estado", "pendiente", "activo", "suspendido", "borrada"), name="ck_usuarios_estado"),
        CheckConstraint(_en("proveedor", "email", "google", "facebook"), name="ck_usuarios_proveedor"),
    )

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20))
    foto = Column(String(64))  # nombre del archivo en DATA_DIR/fotos
    # Cómo se creó la cuenta: email | google | facebook
    proveedor = Column(String(20), nullable=False, default="email", server_default="email")
    email_verificado = Column(Boolean, nullable=False, default=False, server_default=false())
    # Verificación en dos pasos (TOTP): secreto en base32, si ya está activa, y códigos de respaldo (hashes)
    totp_secreto = Column(String(64))
    totp_activo = Column(Boolean, nullable=False, default=False, server_default=false())
    totp_respaldo = Column(Text)
    # Cuenta de Google conectada (el "sub" de Google): así se entra con Google sin depender del correo
    google_id = Column(String(64), unique=True, index=True)
    facebook_id = Column(String(64), unique=True, index=True)
    # False en cuentas creadas con Google o Facebook hasta que la persona crea su contraseña
    tiene_password = Column(Boolean, nullable=False, default=True, server_default=true())
    estado = Column(String(20), nullable=False, default="activo")  # pendiente | activo | suspendido | borrada
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)


class Sesion(Base):
    __tablename__ = "sesiones"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    expira_en = Column(DateTime, nullable=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)


class Plan(Base):
    __tablename__ = "planes"
    __table_args__ = (
        CheckConstraint("precio_mensual >= 0", name="ck_planes_precio"),
        CheckConstraint("trabajos_por_mes >= 0", name="ck_planes_trabajos"),  # 0 = ilimitados
        CheckConstraint("minutos_max_audio > 0", name="ck_planes_minutos"),
    )

    id = Column(Integer, primary_key=True)
    nombre = Column(String(20), unique=True, nullable=False)  # gratis | pro
    precio_mensual = Column(Numeric(10, 2), nullable=False)
    trabajos_por_mes = Column(Integer, nullable=False)
    minutos_max_audio = Column(Integer, nullable=False)
    mejor_calidad = Column(Boolean, nullable=False, default=False)


class Suscripcion(Base):
    __tablename__ = "suscripciones"
    __table_args__ = (
        CheckConstraint(_en("estado", "activa", "cancelada", "vencida"), name="ck_suscripciones_estado"),
        CheckConstraint("fin_periodo > inicio_periodo", name="ck_suscripciones_periodo"),
    )

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("planes.id"), nullable=False)
    estado = Column(String(20), nullable=False, default="activa")  # activa | cancelada | vencida
    # El usuario canceló: sigue con su plan hasta fin_periodo y después pasa a gratis
    cancelar_al_final = Column(Boolean, nullable=False, default=False, server_default=false())
    inicio_periodo = Column(DateTime, nullable=False)
    fin_periodo = Column(DateTime, nullable=False)

    plan = relationship("Plan")


class MetodoPago(Base):
    __tablename__ = "metodos_pago"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    marca = Column(String(30), nullable=False)
    ultimos4 = Column(String(4), nullable=False)
    token_pasarela = Column(String(64), nullable=False)  # simulado


class Pago(Base):
    __tablename__ = "pagos"
    __table_args__ = (
        CheckConstraint(_en("estado", "pagado", "fallido"), name="ck_pagos_estado"),
        CheckConstraint("monto >= 0", name="ck_pagos_monto"),
    )

    id = Column(Integer, primary_key=True)
    suscripcion_id = Column(Integer, ForeignKey("suscripciones.id"), nullable=False)
    metodo_pago_id = Column(Integer, ForeignKey("metodos_pago.id"), nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="MXN")
    estado = Column(String(20), nullable=False)  # pagado | fallido
    id_transaccion = Column(String(64), nullable=False)  # simulado
    fecha = Column(DateTime, nullable=False, default=ahora_utc)


class Trabajo(Base):
    __tablename__ = "trabajos"
    __table_args__ = (
        CheckConstraint(_en("estado", "en_cola", "procesando", "completado", "error"), name="ck_trabajos_estado"),
        CheckConstraint(_en("preset", "2stem", "4stem", "4stem_fast", "denoise"), name="ck_trabajos_preset"),
        CheckConstraint("progreso BETWEEN 0 AND 100", name="ck_trabajos_progreso"),
        CheckConstraint("tamano_bytes >= 0", name="ck_trabajos_tamano"),
    )

    id = Column(String(32), primary_key=True)  # el mismo id que genera jobs.py
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    nombre_original = Column(String(255), nullable=False)
    formato = Column(String(10))  # extensión del archivo subido: mp3, wav...
    tamano_bytes = Column(BigInteger, nullable=False)
    preset = Column(String(20), nullable=False)  # 2stem | 4stem | 4stem_fast | denoise
    estado = Column(String(20), nullable=False, default="en_cola")  # en_cola | procesando | completado | error
    progreso = Column(Integer, nullable=False, default=0)  # 0 a 100
    duracion_audio_seg = Column(Float)
    gpu_seconds = Column(Float)
    mensaje_error = Column(String(500))
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)
    terminado_en = Column(DateTime)

    resultados = relationship("Resultado", passive_deletes=True)
    # Las pistas que pidió el usuario, una fila por pista (antes era el texto "vocals,drums")
    pistas = relationship(
        "TrabajoPista", order_by="TrabajoPista.orden", lazy="selectin",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    @property
    def pistas_pedidas(self) -> str:
        """Las pistas como texto ("vocals,drums"), igual que las devuelve la API."""
        return ",".join(p.stem for p in self.pistas)

    @pistas_pedidas.setter
    def pistas_pedidas(self, valor: str) -> None:
        self.pistas = [TrabajoPista(stem=s, orden=i) for i, s in enumerate(valor.split(",")) if s]


class TrabajoPista(Base):
    __tablename__ = "trabajo_pistas"

    trabajo_id = Column(String(32), ForeignKey("trabajos.id", ondelete="CASCADE"), primary_key=True)
    stem = Column(String(30), primary_key=True)  # vocals, drums, bass...
    orden = Column(Integer, nullable=False)  # el orden en que se pidieron


class Resultado(Base):
    __tablename__ = "resultados"

    id = Column(Integer, primary_key=True)
    trabajo_id = Column(String(32), ForeignKey("trabajos.id", ondelete="CASCADE"), nullable=False)
    stem = Column(String(30), nullable=False)  # vocals, drums, bass...
    ruta_archivo = Column(String(500), nullable=False)  # el audio vive en disco
    expira_en = Column(DateTime, nullable=False)
