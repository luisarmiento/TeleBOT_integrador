"""Integración: solo telebot_test; no envía mensajes reales a Telegram."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from sqlalchemy import select, func, update
from alembic import command
from alembic.config import Config
import bot_corregido as bot
from database import (Repository, engine_config, metadata, clientes, contactos, lineas,
                      planes, deudas, solicitudes, historial)
from persistence import audited
from cargar_ejemplos import cargar


@unittest.skipUnless(os.getenv('DB_NAME') == 'telebot_test', 'Requiere DB_NAME=telebot_test')
class PostgreSQLTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = engine_config()
        if cls.engine.url.database != 'telebot_test':
            cls.engine.dispose()
            raise RuntimeError('La URL efectiva debe apuntar a telebot_test, no solo DB_NAME.')
        command.upgrade(Config('alembic.ini'), 'head')

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as c:
            for table in reversed(metadata.sorted_tables):
                c.execute(table.delete())
        self.repo = Repository(self.engine)
        cargar(self.repo)
        self.repo.seed({222, 333})
        self.customer = self.repo.customer('00001011')
        bot.usuarios.clear()
        for name, value in [('repository', self.repo), ('ACCESO_PUBLICO', True),
                            ('ADMIN_CHAT_IDS', {222, 333})]:
            p = patch.object(bot, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.context = MagicMock()
        self.context.bot.send_message = AsyncMock()
        self.outputs = []

    def count(self, table):
        with self.engine.connect() as c:
            return c.scalar(select(func.count()).select_from(table))

    async def dispatch(self, chat, text, handler=None, args=None):
        u = MagicMock()
        u.effective_chat.id = u.effective_user.id = chat
        u.effective_chat.type = 'private'
        u.effective_user.full_name = 'Visitante de prueba'
        u.message.text = text
        u.message.reply_text = AsyncMock(side_effect=lambda text, **kw: self.outputs.append(text))
        u.effective_message = u.message
        self.context.args = args or []
        await bot.controlar_acceso(u, self.context)
        await audited(handler or bot.on_message, self.repo, bot.usuarios)(u, self.context)

    async def path(self, *texts, chat=111):
        for text in texts:
            await self.dispatch(chat, text)

    def form(self, dni='00001011'):
        plan = self.repo.catalog('planes')[0]
        return dict(tipo='linea_nueva', dni=dni, producto_id=plan['id'],
                    precio=str(plan['precio']), operacion=str(uuid4()),
                    nombre='Persona Nueva', telefono='912345678')

    async def test_carga_y_consulta_publica_sin_crear_cliente(self):
        self.assertEqual(self.count(clientes), 15)
        self.assertEqual(self.count(lineas), 30)
        self.assertFalse(cargar(self.repo))
        await self.path('Buenos días', '1', '1', '3', '0', '3', '1')
        self.assertEqual(self.count(clientes), 15)
        self.assertEqual(self.count(contactos), 1)
        self.assertTrue(any('Fibra óptica' in text for text in self.outputs))
        before = self.count(deudas)
        self.repo.seed({222})
        self.repo.reset()
        self.assertEqual(self.count(lineas), 30)
        self.assertEqual(self.count(deudas), before)

    async def test_deuda_solo_del_numero_seleccionado(self):
        lines = self.repo.lines(self.customer['id'])
        self.assertEqual(len(lines), 3)
        await self.path('Hola', '6', '5', '00001011', '3')
        response = next(t for t in self.outputs if 'Total pendiente:' in t)
        self.assertIn(lines[2]['numero'], response)
        self.assertIn('49.90', response)
        self.assertNotIn(lines[0]['numero'], response)
        await self.path('5', '00001011', '1')
        self.assertTrue(any('no registra deudas' in t for t in self.outputs))
        other = self.repo.customer('00001001')
        self.assertEqual(self.repo.debt(other['id'], lines[2]['id']), [])

    async def test_alta_atomica_cancelacion_y_validacion(self):
        await self.path('Hola', '6', '1', '²²²²²²²²')
        self.assertEqual(bot.usuarios[111]['estado'], 'COM_DNI')
        await self.path('12345678', '1', '1', 'Persona Nueva', '123', '912345678', '2')
        self.assertIsNone(self.repo.customer('12345678'))
        debts = self.count(deudas)
        await self.path('1', '12345678', '1', '1', 'Persona Nueva', '912345678', '1')
        customer = self.repo.customer('12345678')
        self.assertIsNotNone(customer)
        self.assertEqual(len(self.repo.lines(customer['id'])), 1)
        self.assertEqual(self.count(deudas), debts)

    async def test_mismo_dni_otro_chat_y_linea_adicional(self):
        await self.path('Hola', '6', '1', '00001011', '1', '1', chat=999)
        self.assertEqual(len(self.repo.lines(self.customer['id'])), 4)
        self.assertEqual(self.count(clientes), 15)
        await self.path('Hola', '6', '6', '00001011', chat=888)
        self.assertTrue(any('Adquirir línea' in t and 'completada' in t for t in self.outputs))

    async def test_confirmacion_concurrente_y_colision(self):
        existing = self.repo.lines(self.customer['id'])[0]['numero']
        with patch.object(self.repo, 'number', side_effect=[existing, '900000001']):
            form = self.form()
            result = self.repo.contract(111, form)
        self.assertEqual(result['datos']['numero_asignado'], '900000001')
        self.assertEqual(self.repo.contract(111, form)['id'], result['id'])
        form = self.form('12345678')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.repo.contract(111, form), range(2)))
        self.assertEqual(results[0]['id'], results[1]['id'])
        self.assertEqual(len(self.repo.lines(self.repo.customer('12345678')['id'])), 1)

    async def test_fallo_al_asignar_revierte_alta_y_precio_cambia(self):
        existing = self.repo.lines(self.customer['id'])[0]['numero']
        with patch.object(self.repo, 'number', return_value=existing):
            with self.assertRaises(ValueError):
                self.repo.contract(111, self.form('12345678'))
        self.assertIsNone(self.repo.customer('12345678'))
        form = self.form()
        with self.engine.begin() as c:
            c.execute(update(planes).where(planes.c.id == form['producto_id']).values(precio='99.00'))
        with self.assertRaises(ValueError):
            self.repo.contract(111, form)

    async def test_portabilidad_equipo_servicio_baja_y_asesor(self):
        await self.path('Hola', '6', '2', '00001011', '1', '912345678', 'Operador origen', '1')
        await self.path('4', '00001011', '1', '2', 'Lima, Calle de prueba 123', '1')
        await self.path('7', '00001011', '1', 'Lima, Calle de prueba 123', '1')
        await self.path('7', '00001011', '2', '2', '1')
        service = self.repo.requests(self.customer['id'])[0]
        self.assertEqual(service['datos']['linea_id'], self.repo.lines(self.customer['id'])[1]['id'])
        await self.path('3', '00001011', '1', '3', 'abc')
        self.assertEqual(bot.usuarios[111]['estado'], 'COM_DETALLE')
        await self.path('Cambio de domicilio', '1')
        await self.path('3', '00001011', '1', '2', '1')
        rows = self.repo.requests(self.customer['id'])
        self.assertEqual({r['tipo'] for r in rows}, {'portabilidad', 'equipo', 'servicio', 'baja'})
        id_ = rows[0]['id']
        await self.dispatch(222, '/estado', bot.cmd_estado, [str(id_), 'en_atencion'])
        await self.dispatch(333, '/estado', bot.cmd_estado, [str(id_), 'completada'])
        self.assertIn('otro asesor', self.outputs[-1])
        await self.dispatch(222, '/estado', bot.cmd_estado, [str(id_), 'completada'])
        self.assertEqual(self.context.bot.send_message.call_args.kwargs['chat_id'], 111)
        self.assertEqual(self.count(historial), 8)


if __name__ == '__main__':
    unittest.main()
