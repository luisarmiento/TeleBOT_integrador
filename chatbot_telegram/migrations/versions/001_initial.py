"""Esquema inicial del prototipo."""
from alembic import op

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Esquema histórico congelado: no importar el modelo mutable de la aplicación.
    statements = [
        'CREATE TABLE clientes (id BIGSERIAL PRIMARY KEY, nombre VARCHAR(200), creado TIMESTAMPTZ DEFAULT now())',
        'CREATE TABLE asesores (id BIGSERIAL PRIMARY KEY)',
        "CREATE TABLE conversaciones (id SERIAL PRIMARY KEY, cliente_id BIGINT NOT NULL REFERENCES clientes(id), estado VARCHAR(30) NOT NULL, inicio TIMESTAMPTZ DEFAULT now(), fin TIMESTAMPTZ)",
        'CREATE TABLE mensajes (id SERIAL PRIMARY KEY, conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id), autor_id BIGINT, rol VARCHAR(20) NOT NULL, texto TEXT NOT NULL, fecha TIMESTAMPTZ DEFAULT now())',
        'CREATE TABLE sesiones (cliente_id BIGINT PRIMARY KEY REFERENCES clientes(id), datos JSON NOT NULL)',
        'CREATE TABLE asignaciones (id SERIAL PRIMARY KEY, conversacion_id INTEGER NOT NULL REFERENCES conversaciones(id), asesor_id BIGINT NOT NULL REFERENCES asesores(id), inicio TIMESTAMPTZ DEFAULT now(), fin TIMESTAMPTZ)',
        'CREATE TABLE planes (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, precio NUMERIC(12,2) NOT NULL)',
        'CREATE TABLE equipos (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, precio NUMERIC(12,2) NOT NULL)',
        'CREATE TABLE lineas (id SERIAL PRIMARY KEY, cliente_id BIGINT NOT NULL REFERENCES clientes(id), numero VARCHAR(30) UNIQUE NOT NULL, plan_id INTEGER NOT NULL REFERENCES planes(id), activa BOOLEAN NOT NULL)',
        'CREATE TABLE deudas (id SERIAL PRIMARY KEY, linea_id INTEGER NOT NULL REFERENCES lineas(id), importe NUMERIC(12,2) NOT NULL, vencimiento VARCHAR(10), pagada BOOLEAN NOT NULL)',
        'CREATE TABLE solicitudes (id SERIAL PRIMARY KEY, cliente_id BIGINT NOT NULL REFERENCES clientes(id), tipo VARCHAR(30) NOT NULL, datos JSON NOT NULL, estado VARCHAR(30) NOT NULL, asesor_id BIGINT REFERENCES asesores(id), fecha TIMESTAMPTZ DEFAULT now())',
        'CREATE TABLE historial_solicitudes (id SERIAL PRIMARY KEY, solicitud_id INTEGER NOT NULL REFERENCES solicitudes(id), estado VARCHAR(30) NOT NULL, responsable_id BIGINT, fecha TIMESTAMPTZ DEFAULT now())'
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    for name in ('historial_solicitudes', 'solicitudes', 'deudas', 'lineas', 'equipos', 'planes',
                 'asignaciones', 'sesiones', 'mensajes', 'conversaciones', 'asesores', 'clientes'):
        op.drop_table(name)
