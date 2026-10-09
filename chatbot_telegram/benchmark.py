"""Medición local secuencial del prototipo; no mide red Telegram ni usuarios reales."""
import asyncio
import json
import os
import platform
import statistics
import time
from unittest.mock import AsyncMock, MagicMock
from alembic import command
from alembic.config import Config
from sqlalchemy import select, func
import bot_corregido as bot
from database import Repository, engine_config, metadata, mensajes, clientes, contactos
from cargar_ejemplos import cargar
from persistence import audited


async def main():
    if os.getenv('DB_NAME') != 'telebot_test':
        raise SystemExit('Esta medición requiere DB_NAME=telebot_test.')
    engine = engine_config()
    if engine.url.database != 'telebot_test':
        engine.dispose()
        raise SystemExit('La URL efectiva debe apuntar a telebot_test.')
    command.upgrade(Config('alembic.ini'), 'head')
    with engine.begin() as connection:
        for table in reversed(metadata.sorted_tables):
            connection.execute(table.delete())
    bot.repository = Repository(engine)
    cargar(bot.repository)
    bot.ADMIN_CHAT_IDS = {222, 333}
    bot.ALLOWED_USER_IDS = set(range(10000, 10050)) | bot.ADMIN_CHAT_IDS
    bot.repository.seed(bot.ADMIN_CHAT_IDS)
    bot.usuarios.clear()
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    timings = []
    started = time.perf_counter()
    # Dejar las 50 sesiones abiertas verifica que el costo por mensaje no reescribe todas.
    for client in range(10000, 10050):
        for text in ('Hola', '1', '2', '3', '4', '6'):
            update = MagicMock()
            update.effective_chat.id = client
            update.effective_chat.type = 'private'
            update.effective_user.id = client
            update.effective_user.full_name = f'Cliente simulado {client}'
            update.message.text = text
            update.message.reply_text = AsyncMock()
            update.effective_message = update.message
            tick = time.perf_counter()
            await bot.controlar_acceso(update, context)
            await audited(bot.on_message, bot.repository, bot.usuarios)(update, context)
            timings.append((time.perf_counter() - tick) * 1000)
    elapsed = time.perf_counter() - started
    with engine.connect() as connection:
        recorded = connection.scalar(select(func.count()).select_from(mensajes))
        client_count = connection.scalar(select(func.count()).select_from(clientes))
        contact_count = connection.scalar(select(func.count()).select_from(contactos))
    report = {
        'python': platform.python_version(), 'base': 'telebot_test',
        'chats_simulados': 50, 'actualizaciones_secuenciales': len(timings),
        'contactos_guardados': contact_count,
        'mensajes_guardados': recorded, 'clientes_guardados': client_count,
        'duracion_s': round(elapsed, 3), 'media_ms': round(statistics.mean(timings), 3),
        'p95_ms': round(sorted(timings)[int(len(timings) * .95) - 1], 3),
        'max_ms': round(max(timings), 3),
        'objetivo_p95_ms': 1000,
        'cumple_objetivo_local': sorted(timings)[int(len(timings) * .95) - 1] < 1000,
        'alcance': 'Telegram simulado; PostgreSQL real; carga secuencial, una instancia; no prueba de concurrencia ni SLA real.'
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert recorded == 600 and client_count == 15 and contact_count == 50
    assert report['cumple_objetivo_local']
    engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
