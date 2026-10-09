import unittest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.error import TelegramError

import bot_corregido as bot


class FlujoTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.usuarios.clear()
        self.admin_patch = patch.object(bot, "ADMIN_CHAT_IDS", {222, 333})
        self.allowed_patch = patch.object(bot, "ALLOWED_USER_IDS", {111, 222, 333})
        self.admin_patch.start()
        self.allowed_patch.start()
        self.addCleanup(self.admin_patch.stop)
        self.addCleanup(self.allowed_patch.stop)
        for name, value in [('ACCESO_PUBLICO', False), ('repository', MagicMock())]:
            p = patch.object(bot, name, value)
            p.start()
            self.addCleanup(p.stop)
        bot.repository.catalog.return_value = [
            {'id': i, 'nombre': f'Producto {i}', 'descripcion': f'Descripción {i}', 'precio': '39.90'}
            for i in range(1, 4)]
        self.update = MagicMock()
        self.update.effective_chat.id = 111
        self.update.effective_chat.type = "private"
        self.update.effective_user.id = 111
        self.update.message.text = "Hola"
        self.update.message.reply_text = AsyncMock()
        self.context = MagicMock()
        self.context.bot.send_message = AsyncMock()

    async def mensaje(self, text):
        self.update.message.text = text
        await bot.on_message(self.update, self.context)

    def caso(self):
        session = bot.obtener_o_crear_sesion(111)
        session.update(modo="ASESOR", estado="ASESOR", asesor_id=222)
        self.update.effective_chat.id = 222
        self.context.args = ["111"]
        return session

    async def test_acceso_privado(self):
        await bot.controlar_acceso(self.update, self.context)
        for user_id, tipo in [(999, "private"), (111, "group")]:
            self.update.effective_user.id = user_id
            self.update.effective_chat.type = tipo
            with self.assertRaises(bot.ApplicationHandlerStop):
                await bot.controlar_acceso(self.update, self.context)
        self.assertFalse(bot.usuarios)
        self.context.bot.send_message.assert_not_awaited()

    async def test_catalogo_completo_y_navegacion(self):
        await self.mensaje("Hola")
        for numero, categoria in zip("1234", bot.CATALOGO):
            for producto in "123":
                await self.mensaje(numero)
                self.assertEqual(bot.usuarios[111]["estado"], categoria)
                await self.mensaje(producto)
                self.assertIn(f'Descripción {producto}',
                              self.update.message.reply_text.call_args.args[0])
                await self.mensaje("3")
                self.assertEqual(bot.usuarios[111]["estado"], categoria)
                await self.mensaje("4")
        await self.mensaje("incorrecto")
        self.assertEqual(bot.usuarios[111]["estado"], "MENU")
        await self.mensaje("1")
        await self.mensaje("1")
        await self.mensaje("1")
        self.assertEqual(bot.usuarios[111]["estado"], "MENU")
        await self.mensaje("1")
        await self.mensaje("1")
        await self.mensaje("2")
        self.assertNotIn(111, bot.usuarios)

    async def test_sin_asesores_disponibles(self):
        await self.mensaje("Hola")
        self.context.bot.send_message.side_effect = TelegramError("fallo simulado")
        await self.mensaje("5")
        self.assertEqual(bot.usuarios[111]["modo"], "BOT")
        self.assertEqual(bot.usuarios[111]["estado"], "MENU")

    async def test_fallo_tomar_revierte_asignacion(self):
        session = self.caso()
        session["asesor_id"] = None
        self.context.bot.send_message.side_effect = TelegramError("fallo simulado")
        await bot.cmd_tomar(self.update, self.context)
        self.assertIsNone(session["asesor_id"])

    async def test_fallo_cierre_conserva_caso(self):
        self.caso()
        self.context.bot.send_message.side_effect = TelegramError("fallo simulado")
        await bot.cmd_finalizar(self.update, self.context)
        self.assertIn(111, bot.usuarios)

    async def test_exclusividad_y_autorizacion(self):
        self.caso()
        self.update.effective_chat.id = 333
        for command in [bot.cmd_tomar, bot.cmd_reply, bot.cmd_finalizar]:
            self.context.args = ["111", "hola"]
            await command(self.update, self.context)
        self.context.bot.send_message.assert_not_awaited()
        self.assertEqual(bot.usuarios[111]["asesor_id"], 222)
        self.update.effective_chat.id = 111
        await bot.cmd_tomar(self.update, self.context)
        self.context.bot.send_message.assert_not_awaited()

    async def test_enrutamiento_y_texto_largo(self):
        self.caso()
        self.update.effective_chat.id = 111
        await self.mensaje("x" * 4096)
        calls = self.context.bot.send_message.await_args_list
        self.assertTrue(all(call.kwargs["chat_id"] == 222 for call in calls))
        self.assertTrue(all(len(call.kwargs["text"]) <= 2000 for call in calls))
        self.assertEqual("".join(call.kwargs["text"] for call in calls), "📩 Cliente 111: " + "x" * 4096)

    async def test_start_cancela_y_notifica(self):
        self.caso()
        self.update.effective_chat.id = 111
        await bot.cmd_start(self.update, self.context)
        self.assertEqual(bot.usuarios[111]["modo"], "BOT")
        self.assertEqual(self.context.bot.send_message.await_count, 2)

    def test_ids_invalidos(self):
        for value in ["abc", "0", "-12", "111,error"]:
            with self.assertRaises(ValueError):
                bot.parse_ids(value)
        self.assertEqual(bot.parse_ids("111, 222,111"), {111, 222})

    async def test_validacion_unicode_y_resumen_comercial(self):
        from commerce import process
        repo = MagicMock()
        repo.catalog.return_value = [{'id': 1, 'nombre': 'Plan Demo', 'precio': '49.90'}]
        repo.customer.return_value = {'id': 1}
        session = {'estado': 'GESTIONES'}
        async def input_(text):
            self.update.message.text = text
            await process(self.update, self.context, session, repo, AsyncMock())
        await input_('1')
        await input_('00001001')
        for bad in ['²', '١', '', '9' * 5000, '99', '-1']:
            await input_(bad)
            self.assertEqual(session['estado'], 'COM_PRODUCTO')
        await input_('1')
        summary = self.update.message.reply_text.call_args.args[0]
        self.assertIn('Gestión: Adquirir línea', summary)
        self.assertIn('Producto: Plan Demo', summary)
        self.assertNotIn('producto_id', summary)
        self.assertNotIn('linea_nueva', summary)

    async def test_consulta_lenta_no_bloquea_event_loop(self):
        from commerce import process
        repo = MagicMock()
        repo.catalog.side_effect = lambda kind: (time.sleep(0.15) or [])
        repo.customer.return_value = {'id': 1}
        session = {'estado': 'COM_DNI', 'formulario': {'tipo': 'linea_nueva'}}
        self.update.message.text = '00001001'
        started = time.perf_counter()
        task = asyncio.create_task(process(self.update, self.context, session, repo, AsyncMock()))
        await asyncio.sleep(0.02)
        self.assertFalse(task.done())
        self.assertLess(time.perf_counter() - started, 0.12)
        await task

    async def test_fallo_postgres_no_procesa_consulta(self):
        from persistence import audited
        from sqlalchemy.exc import OperationalError
        repo = MagicMock()
        repo.conversation.side_effect = OperationalError('SELECT', {}, Exception('simulado'))
        self.update.effective_message = self.update.message
        handler = AsyncMock()
        await audited(handler, repo, bot.usuarios)(self.update, self.context)
        handler.assert_not_awaited()
        self.assertIn('base de datos', self.update.message.reply_text.call_args.args[0])

    async def test_publico_acepta_otro_usuario_pero_no_grupos(self):
        with patch.object(bot, 'ACCESO_PUBLICO', True):
            self.update.effective_user.id = 999
            await bot.controlar_acceso(self.update, self.context)
            self.update.effective_chat.type = 'group'
            with self.assertRaises(bot.ApplicationHandlerStop):
                await bot.controlar_acceso(self.update, self.context)

    async def test_comandos_invalidos_y_contenido_no_admitido(self):
        self.update.effective_chat.id = 222
        for command in (bot.cmd_tomar, bot.cmd_reply, bot.cmd_finalizar):
            self.context.args = []
            await command(self.update, self.context)
            self.assertIn('Uso:', self.update.message.reply_text.call_args.args[0])
            self.context.args = ['incorrecto', 'mensaje']
            await command(self.update, self.context)
            self.assertIn('inválido', self.update.message.reply_text.call_args.args[0])
        self.update.effective_message = self.update.message
        await bot.entrada_no_admitida(self.update, self.context)
        self.assertIn('texto', self.update.message.reply_text.call_args.args[0])

    async def test_primer_contacto_y_derivacion(self):
        bot.usuarios.clear()
        update = MagicMock()
        update.effective_chat.id = 111
        update.message.text = "Hola"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        await bot.on_message(update, context)
        self.assertIn("Bienvenido", update.message.reply_text.call_args.args[0])
        update.message.text = "5"
        await bot.on_message(update, context)
        self.assertEqual(bot.usuarios[111]["modo"], "ASESOR")
        self.assertIsInstance(
            update.message.reply_text.call_args.kwargs["reply_markup"],
            bot.ReplyKeyboardRemove,
        )
        self.assertEqual(context.bot.send_message.await_count, len(bot.ADMIN_CHAT_IDS))
        if bot.ADMIN_CHAT_IDS:
            self.assertIn("/tomar 111", context.bot.send_message.call_args.kwargs["text"])
        advisor = next(iter(bot.ADMIN_CHAT_IDS), 0)
        update.effective_chat.id = advisor
        context.args = ["111"]
        await bot.cmd_tomar(update, context)
        if bot.ADMIN_CHAT_IDS:
            self.assertEqual(bot.usuarios[111]["asesor_id"], advisor)
            context.args = ["111", "Hola"]
            await bot.cmd_reply(update, context)
            self.assertEqual(context.bot.send_message.call_args.kwargs["chat_id"], 111)
            context.args = ["111"]
            await bot.cmd_finalizar(update, context)
            self.assertNotIn(111, bot.usuarios)


if __name__ == "__main__":
    unittest.main()
