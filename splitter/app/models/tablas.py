"""Las 8 tablas de la base. Todas las fechas se guardan en UTC."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from ..database import Base, ahora_utc


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    estado = Column(String(20), nullable=False, default="activo")  # activo | suspendido
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)


class Sesion(Base):
    __tablename__ = "sesiones"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    expira_en = Column(DateTime, nullable=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)


class Plan(Base):
    __tablename__ = "planes"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(20), unique=True, nullable=False)  # gratis | pro
    precio_mensual = Column(Numeric(10, 2), nullable=False)
    trabajos_por_mes = Column(Integer, nullable=False)
    minutos_max_audio = Column(Integer, nullable=False)
    mejor_calidad = Column(Boolean, nullable=False, default=False)


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("planes.id"), nullable=False)
    estado = Column(String(20), nullable=False, default="activa")  # activa | cancelada | vencida
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

    id = Column(String(32), primary_key=True)  # el mismo id que genera jobs.py
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    nombre_original = Column(String(255), nullable=False)
    tamano_bytes = Column(BigInteger, nullable=False)
    preset = Column(String(20), nullable=False)  # 2stem | 4stem | 4stem_fast | denoise
    pistas_pedidas = Column(String(255), nullable=False)  # por ejemplo "vocals,drums"
    estado = Column(String(20), nullable=False, default="en_cola")  # en_cola | procesando | completado | error
    progreso = Column(Integer, nullable=False, default=0)  # 0 a 100
    duracion_audio_seg = Column(Float)
    gpu_seconds = Column(Float)
    mensaje_error = Column(String(500))
    creado_en = Column(DateTime, nullable=False, default=ahora_utc)
    terminado_en = Column(DateTime)

    resultados = relationship("Resultado")


class Resultado(Base):
    __tablename__ = "resultados"

    id = Column(Integer, primary_key=True)
    trabajo_id = Column(String(32), ForeignKey("trabajos.id"), nullable=False)
    stem = Column(String(30), nullable=False)  # vocals, drums, bass...
    ruta_archivo = Column(String(500), nullable=False)  # el audio vive en disco
    expira_en = Column(DateTime, nullable=False)
