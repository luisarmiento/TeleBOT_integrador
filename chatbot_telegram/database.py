"""Esquema y repositorio transaccional. No contacta a Telegram."""
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import (MetaData, Table, Column, Integer, BigInteger, String,
                        Text, DateTime, Numeric, ForeignKey, JSON, Boolean,
                        create_engine, select, func, insert, update)
from sqlalchemy.engine import URL
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import CheckConstraint

load_dotenv(Path(__file__).with_name('.env'))

metadata = MetaData()
contactos = Table('contactos', metadata,
    Column('id', BigInteger, primary_key=True), Column('nombre', String(200)),
    Column('creado', DateTime(timezone=True), server_default=func.now()))
clientes = Table('clientes', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('dni', String(8), unique=True, nullable=False),
    Column('nombre', String(200), nullable=False),
    Column('telefono', String(9), nullable=False),
    Column('creado', DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("dni ~ '^[0-9]{8}$'", name='cliente_dni_formato'),
    CheckConstraint("telefono ~ '^9[0-9]{8}$'", name='cliente_contacto_formato'))
asesores = Table('asesores', metadata, Column('id', BigInteger, primary_key=True))
conversaciones = Table('conversaciones', metadata,
    Column('id', Integer, primary_key=True),
    Column('chat_id', BigInteger, ForeignKey('contactos.id'), nullable=False),
    Column('estado', String(30), nullable=False, default='abierta'),
    Column('inicio', DateTime(timezone=True), server_default=func.now()),
    Column('fin', DateTime(timezone=True)))
mensajes = Table('mensajes', metadata, Column('id', Integer, primary_key=True),
    Column('conversacion_id', Integer, ForeignKey('conversaciones.id'), nullable=False),
    Column('autor_id', BigInteger), Column('rol', String(20), nullable=False),
    Column('texto', Text, nullable=False),
    Column('fecha', DateTime(timezone=True), server_default=func.now()))
sesiones = Table('sesiones', metadata,
    Column('chat_id', BigInteger, ForeignKey('contactos.id'), primary_key=True),
    Column('datos', JSON, nullable=False))
asignaciones = Table('asignaciones', metadata, Column('id', Integer, primary_key=True),
    Column('conversacion_id', Integer, ForeignKey('conversaciones.id'), nullable=False),
    Column('asesor_id', BigInteger, ForeignKey('asesores.id'), nullable=False),
    Column('inicio', DateTime(timezone=True), server_default=func.now()),
    Column('fin', DateTime(timezone=True)))
planes = Table('planes', metadata, Column('id', Integer, primary_key=True),
    Column('nombre', String(100), nullable=False), Column('precio', Numeric(12, 2), nullable=False),
    Column('descripcion', Text, nullable=False, server_default=''))
equipos = Table('equipos', metadata, Column('id', Integer, primary_key=True),
    Column('nombre', String(100), nullable=False), Column('precio', Numeric(12, 2), nullable=False))
catalogo = Table('catalogo', metadata, Column('id', Integer, primary_key=True),
    Column('categoria', String(30), nullable=False), Column('nombre', String(100), nullable=False),
    Column('descripcion', Text, nullable=False), Column('precio', Numeric(12, 2)),
    Column('requiere_direccion', Boolean, nullable=False, server_default='false'))
lineas = Table('lineas', metadata, Column('id', Integer, primary_key=True),
    Column('cliente_id', BigInteger, ForeignKey('clientes.id'), nullable=False),
    Column('numero', String(30), unique=True, nullable=False),
    Column('plan_id', Integer, ForeignKey('planes.id'), nullable=False),
    Column('activa', Boolean, nullable=False, default=True))
deudas = Table('deudas', metadata, Column('id', Integer, primary_key=True),
    Column('linea_id', Integer, ForeignKey('lineas.id'), nullable=False),
    Column('importe', Numeric(12, 2), nullable=False), Column('vencimiento', String(10)),
    Column('pagada', Boolean, nullable=False, default=False))
solicitudes = Table('solicitudes', metadata, Column('id', Integer, primary_key=True),
    Column('cliente_id', BigInteger, ForeignKey('clientes.id'), nullable=False),
    Column('tipo', String(30), nullable=False), Column('datos', JSON, nullable=False),
    Column('chat_id', BigInteger), Column('operacion', String(36), unique=True),
    Column('estado', String(30), nullable=False, default='pendiente'),
    Column('asesor_id', BigInteger, ForeignKey('asesores.id')),
    Column('fecha', DateTime(timezone=True), server_default=func.now()))
historial = Table('historial_solicitudes', metadata,
    Column('id', Integer, primary_key=True),
    Column('solicitud_id', Integer, ForeignKey('solicitudes.id'), nullable=False),
    Column('estado', String(30), nullable=False), Column('responsable_id', BigInteger),
    Column('fecha', DateTime(timezone=True), server_default=func.now()))


def engine_config():
    return create_engine(os.getenv('DATABASE_URL') or URL.create(
        'postgresql+psycopg', username=os.getenv('DB_USER', 'telebot_app'),
        password=os.getenv('DB_PASSWORD') or os.environ['DB_APP_PASSWORD'], host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')), database=os.getenv('DB_NAME', 'telebot')),
        pool_pre_ping=True, pool_timeout=5,
        connect_args={'connect_timeout': 5, 'options': '-c statement_timeout=5000'})


class Repository:
    def __init__(self, engine):
        self.engine = engine

    def seed(self, admins):
        with self.engine.begin() as c:
            for id_ in admins:
                if not c.execute(select(asesores.c.id).where(asesores.c.id == id_)).first():
                    c.execute(insert(asesores).values(id=id_))

    def reset(self):
        with self.engine.begin() as c:
            c.execute(update(conversaciones).where(conversaciones.c.estado == 'abierta').values(estado='reiniciada', fin=func.now()))
            c.execute(update(asignaciones).where(asignaciones.c.fin.is_(None)).values(fin=func.now()))
            c.execute(sesiones.delete())

    def conversation(self, client, name=''):
        with self.engine.begin() as c:
            c.execute(pg_insert(contactos).values(id=client, nombre=str(name)).on_conflict_do_nothing())
            row = c.execute(select(conversaciones.c.id).where(
                conversaciones.c.chat_id == client, conversaciones.c.estado == 'abierta')).first()
            if row:
                return row[0]
            return c.execute(insert(conversaciones).values(chat_id=client, estado='abierta').returning(conversaciones.c.id)).scalar_one()

    def message(self, client, role, text, author=None):
        conv = self.conversation(client)
        with self.engine.begin() as c:
            c.execute(insert(mensajes).values(conversacion_id=conv, autor_id=author,
                                              rol=role, texto=text))

    def session(self, client, data):
        with self.engine.begin() as c:
            c.execute(sesiones.delete().where(sesiones.c.chat_id == client))
            if data is not None:
                c.execute(insert(sesiones).values(chat_id=client, datos=data))
            else:
                c.execute(update(conversaciones).where(conversaciones.c.chat_id == client,
                    conversaciones.c.estado == 'abierta').values(estado='cerrada', fin=func.now()))
                ids = select(conversaciones.c.id).where(conversaciones.c.chat_id == client)
                c.execute(update(asignaciones).where(asignaciones.c.conversacion_id.in_(ids),
                    asignaciones.c.fin.is_(None)).values(fin=func.now()))

    def assign(self, client, admin):
        conv = self.conversation(client)
        with self.engine.begin() as c:
            c.execute(insert(asignaciones).values(conversacion_id=conv, asesor_id=admin))

    def catalog(self, kind):
        table = {'planes': planes, 'equipos': equipos}.get(kind, catalogo)
        query = select(table).order_by(table.c.id)
        if table is catalogo:
            query = query.where(catalogo.c.categoria == kind.upper())
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(query).mappings()]

    def lines(self, client):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(lineas).where(lineas.c.cliente_id == client).order_by(lineas.c.id)).mappings()]

    def debt(self, client, line):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(deudas).join(lineas).where(
                lineas.c.cliente_id == client, lineas.c.id == line,
                deudas.c.pagada.is_(False))).mappings()]

    def requests(self, client=None):
        query = select(solicitudes).order_by(solicitudes.c.id.desc()).limit(20)
        if client is not None:
            query = query.where(solicitudes.c.cliente_id == client)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(query).mappings()]

    def status(self, id_, admin, state):
        transitions = {'pendiente': {'en_atencion', 'cancelada'},
                       'en_atencion': {'completada', 'cancelada'}}
        with self.engine.begin() as c:
            row = c.execute(select(solicitudes).where(solicitudes.c.id == id_).with_for_update()).mappings().first()
            if not row or (row['asesor_id'] is not None and row['asesor_id'] != admin):
                raise ValueError('Solicitud inexistente o asignada a otro asesor.')
            if state not in transitions.get(row['estado'], set()):
                raise ValueError('Transición inválida. Primero usa en_atencion; luego completada o cancelada.')
            c.execute(update(solicitudes).where(solicitudes.c.id == id_).values(estado=state, asesor_id=admin))
            c.execute(insert(historial).values(solicitud_id=id_, estado=state, responsable_id=admin))
            return row['chat_id']

    def customer(self, dni):
        with self.engine.connect() as c:
            row = c.execute(select(clientes).where(clientes.c.dni == dni)).mappings().first()
            return dict(row) if row else None

    def number(self):
        return '9' + str(secrets.randbelow(100000000)).zfill(8)

    def new_line(self, c, client, plan):
        for _ in range(30):
            number = self.number()
            row = c.execute(pg_insert(lineas).values(cliente_id=client, plan_id=plan,
                numero=number, activa=True).on_conflict_do_nothing(index_elements=['numero'])
                .returning(lineas.c.id, lineas.c.numero)).first()
            if row:
                return row
        raise ValueError('No se pudo asignar un número libre. Intenta nuevamente.')

    def contract(self, chat, form):
        """Confirmación atómica e idempotente; nunca genera una deuda."""
        with self.engine.begin() as c:
            # Serializa confirmaciones del mismo DNI, también desde distintos chats.
            c.execute(select(func.pg_advisory_xact_lock(int(form['dni']))))
            previous = c.execute(select(solicitudes).where(
                solicitudes.c.operacion == form['operacion'])).mappings().first()
            if previous:
                return dict(previous)
            customer = c.execute(select(clientes).where(clientes.c.dni == form['dni'])).mappings().first()
            kind = form['tipo']
            if kind == 'linea_nueva':
                product_table = planes
            elif kind == 'equipo':
                product_table = equipos
            elif kind == 'servicio':
                product_table = catalogo
            elif kind == 'portabilidad':
                product_table = planes
            else:
                product_table = None
            if product_table is not None:
                product = c.execute(select(product_table).where(product_table.c.id == form['producto_id'])).mappings().first()
                if not product or str(product['precio']) != form['precio']:
                    raise ValueError('El producto o su precio cambió. Vuelve al menú y elígelo nuevamente.')
                if kind == 'servicio' and product['categoria'] != 'SERVICIOS':
                    raise ValueError('Servicio inválido.')
            if customer is None:
                if kind != 'linea_nueva':
                    raise ValueError('Primero debes contratar tu primera línea.')
                client = c.execute(insert(clientes).values(dni=form['dni'],
                    nombre=form['nombre'], telefono=form['telefono']).returning(clientes.c.id)).scalar_one()
            else:
                client = customer['id']
            if 'linea_id' in form:
                owned = c.execute(select(lineas.c.id).where(lineas.c.id == form['linea_id'],
                    lineas.c.cliente_id == client)).first()
                if not owned:
                    raise ValueError('El número no pertenece al DNI indicado.')
            data = dict(form)
            state = 'pendiente'
            if kind == 'linea_nueva':
                line = self.new_line(c, client, form['producto_id'])
                data.update(linea_id=line.id, numero_asignado=line.numero)
                state = 'completada'
            id_ = c.execute(insert(solicitudes).values(cliente_id=client, chat_id=chat,
                tipo=kind, datos=data, estado=state, operacion=form['operacion'])
                .returning(solicitudes.c.id)).scalar_one()
            c.execute(insert(historial).values(solicitud_id=id_, estado=state, responsable_id=chat))
            return {'id': id_, 'estado': state, 'datos': data}
