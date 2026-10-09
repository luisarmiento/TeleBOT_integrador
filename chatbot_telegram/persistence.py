"""Adaptadores para registrar entradas, respuestas y sesiones de los handlers."""
import asyncio
import logging
from copy import deepcopy
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class Proxy:
    def __init__(self, target, **overrides):
        self.target = target
        self.overrides = overrides

    def __getattr__(self, name):
        return self.overrides[name] if name in self.overrides else getattr(self.target, name)


def audited(handler, repo, sessions):
    async def execute(update, context):
        client = update.effective_chat.id
        user = update.effective_user
        restart = handler.__name__ == 'cmd_start' or (
            handler.__name__ == 'on_message' and
            (update.effective_message.text or '').strip().casefold() in ('menú', 'menu', 'inicio'))
        if restart and client in sessions:
            await asyncio.to_thread(repo.session, client, None)
        await asyncio.to_thread(repo.conversation, client, user.full_name)
        await asyncio.to_thread(repo.message, client, 'cliente', update.effective_message.text or '[contenido no textual]', user.id)

        async def reply(text, **kwargs):
            result = await update.effective_message.reply_text(text, **kwargs)
            await asyncio.to_thread(repo.message, client, 'bot', text)
            return result

        async def send_message(chat_id, text, **kwargs):
            result = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
            role = 'asesor' if handler.__name__ == 'cmd_reply' else 'bot'
            await asyncio.to_thread(repo.message, chat_id, role, text, user.id if role == 'asesor' else None)
            return result

        previous = deepcopy(sessions)
        adapted_message = Proxy(update.effective_message, reply_text=reply)
        adapted_update = Proxy(update, message=adapted_message, effective_message=adapted_message)
        adapted_context = Proxy(context, bot=Proxy(context.bot, send_message=send_message))
        try:
            await handler(adapted_update, adapted_context)
        finally:
            affected = {client} | {
                key for key in set(previous) | set(sessions)
                if previous.get(key) != sessions.get(key)
            }
            for key in affected:
                data = sessions.get(key)
                if data and data.get('asesor_id') and previous.get(key, {}).get('asesor_id') != data['asesor_id']:
                    await asyncio.to_thread(repo.assign, key, data['asesor_id'])
                await asyncio.to_thread(repo.session, key, data)

    async def run(update, context):
        try:
            await execute(update, context)
        except SQLAlchemyError:
            logger.error('No fue posible completar el registro en PostgreSQL.')
            try:
                await update.effective_message.reply_text(
                    'La base de datos no está disponible o no pudo completar el registro. '
                    'Intenta más tarde. Si estabas confirmando una solicitud, consulta '
                    'Mis solicitudes antes de volver a enviarla.'
                )
            except Exception:
                logger.error('No se pudo entregar el aviso de base de datos.')
    return run
