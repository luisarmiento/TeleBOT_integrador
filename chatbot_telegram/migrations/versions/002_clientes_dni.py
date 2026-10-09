"""Separar contacto Telegram del cliente comercial; retirar el negocio demo anterior.

La limpieza del esquema comercial anterior fue autorizada por el usuario.
Conserva conversaciones, mensajes, sesiones y asignaciones.
"""
from alembic import op
from sqlalchemy import inspect
from database import metadata

revision = '002'
down_revision = '001'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'contactos' not in inspect(bind).get_table_names():
        for table in ('historial_solicitudes', 'solicitudes', 'deudas', 'lineas', 'equipos', 'planes'):
            op.drop_table(table)
        op.rename_table('clientes', 'contactos')
        # El nombre físico del índice PK antiguo debe liberarse para clientes.
        op.execute('ALTER TABLE contactos RENAME CONSTRAINT clientes_pkey TO contactos_pkey')
        op.execute('ALTER SEQUENCE IF EXISTS clientes_id_seq RENAME TO contactos_id_seq')
        op.alter_column('conversaciones', 'cliente_id', new_column_name='chat_id')
        op.alter_column('sesiones', 'cliente_id', new_column_name='chat_id')
    metadata.create_all(bind)


def downgrade():
    raise RuntimeError('La identidad por DNI no puede volver a chat_id sin pérdida; restaurar respaldo.')
