import logging
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    TypeHandler,
    ApplicationHandlerStop,
)

load_dotenv(Path(__file__).with_name(".env"))


def parse_ids(value: str) -> set[int]:
    try:
        ids = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise ValueError("Los IDs deben ser números enteros separados por comas.") from exc
    if any(item <= 0 for item in ids):
        raise ValueError("Los IDs de usuarios deben ser positivos.")
    return ids

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_IDS_STR = os.getenv("ADMIN_CHAT_IDS", "") or os.getenv("ADMIN_CHAT_ID", "")
ADMIN_CHAT_IDS = parse_ids(ADMIN_CHAT_IDS_STR)
ALLOWED_USER_IDS = parse_ids(os.getenv("ALLOWED_USER_IDS", "")) | ADMIN_CHAT_IDS
ACCESO_PUBLICO = os.getenv('ACCESO_PUBLICO', 'True').strip().lower() == 'true'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

usuarios: dict[int, dict] = {}
repository = None


async def controlar_acceso(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if (
        update.effective_chat is None
        or update.effective_user is None
        or update.effective_chat.type != "private"
        or (not ACCESO_PUBLICO and update.effective_user.id not in ALLOWED_USER_IDS)
    ):
        # No responder ni crear sesiones para cuentas externas.
        raise ApplicationHandlerStop


async def enviar_texto(context, chat_id: int, texto: str) -> None:
    # Margen suficiente para caracteres suplementarios de Unicode.
    for offset in range(0, len(texto), 2000):
        await context.bot.send_message(chat_id=chat_id, text=texto[offset:offset + 2000])

CATALOGO = ('PLANES', 'PROMOCIONES', 'SERVICIOS', 'PAQUETES')

TEXTO_BIENVENIDA = (
    "¡Bienvenido al Chatbot Bitel! 🌐\n"
    "Selecciona una opción del menú principal:"
)

TEXTO_MENU_PRINCIPAL = (
    "MENÚ PRINCIPAL\n"
    "1️⃣ Planes\n"
    "2️⃣ Promociones\n"
    "3️⃣ Servicios\n"
    "4️⃣ Paquetes\n"
    "5️⃣ Hablar con un asesor"
    "\n6️⃣ Autogestiones: líneas, equipos, deudas y servicios"
)

TEXTO_OPCION_INVALIDA = (
    "❌ Opción no válida. Por favor, selecciona una opción del menú con los números mostrados."
)

TEXTO_DESPUES_DESCRIPCION = (
    "¿Qué deseas hacer ahora?\n"
    "1️⃣ Nueva consulta (menú principal)\n"
    "2️⃣ Finalizar\n"
    "3️⃣ Regresar"
)

TEXTO_MODO_ASESOR = (
    "👤 Un asesor tomará tu caso en breve. "
    "Puedes seguir escribiendo tus consultas mientras esperas."
)

TEXTO_ESPERANDO_ASESOR = (
    "⏳ Tu caso está pendiente de ser tomado por un asesor. "
    "Gracias por tu paciencia."
)


def teclado_numerico(opciones: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[o] for o in opciones], resize_keyboard=True, one_time_keyboard=False)


TECLADO_MENU = teclado_numerico(["1", "2", "3", "4", "5", "6"])
TECLADO_SUBMENU = teclado_numerico(["1", "2", "3", "4"])
TECLADO_OTRA_CONSULTA = teclado_numerico(["1", "2", "3"])


def obtener_o_crear_sesion(chat_id: int) -> dict:
    if chat_id not in usuarios:
        usuarios[chat_id] = {
            "estado": "MENU",
            "modo": "BOT",
            "asesor_id": None,
            "menu_anterior": None,
        }
    return usuarios[chat_id]


async def mostrar_catalogo(update, session, nombre):
    rows = await asyncio.to_thread(repository.catalog, nombre.lower() if nombre == 'PLANES' else nombre)
    session.update(estado=nombre, catalogo_actual=[{
        'nombre': r['nombre'], 'descripcion': r.get('descripcion', ''),
        'precio': str(r['precio']) if r.get('precio') is not None else None} for r in rows])
    text = f'{nombre}\n' + ('\n'.join(f"{i}. {r['nombre']}" for i, r in enumerate(rows, 1))
        if rows else 'No hay opciones disponibles.') + '\n0 Menú principal'
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    anterior = usuarios.get(chat_id)
    if anterior and anterior["modo"] == "ASESOR":
        await notificar_asesores(context, f"ℹ️ Cliente {chat_id} reinició con /start; su caso fue cancelado.")
    session = obtener_o_crear_sesion(chat_id)
    session.update(
        estado="MENU",
        modo="BOT",
        asesor_id=None,
        menu_anterior=None,
        formulario={},
    )
    await update.message.reply_text(
        f"{TEXTO_BIENVENIDA}\n\n{TEXTO_MENU_PRINCIPAL}",
        reply_markup=TECLADO_MENU,
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Tu chat_id es: `{chat_id}`", parse_mode="Markdown")


def es_asesor(chat_id: int) -> bool:
    return chat_id in ADMIN_CHAT_IDS


async def notificar_asesores(context: ContextTypes.DEFAULT_TYPE, texto: str) -> int:
    entregados = 0
    for admin_id in ADMIN_CHAT_IDS:
        try:
            await enviar_texto(context, admin_id, texto)
            entregados += 1
        except TelegramError:
            logger.error("No se pudo notificar al asesor %s", admin_id)
    return entregados


async def cmd_tomar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not es_asesor(chat_id):
        await update.message.reply_text("❌ No estás autorizado para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /tomar CHAT_ID")
        return
    try:
        cliente_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ CHAT_ID inválido. Debe ser un número.")
        return
    session = usuarios.get(cliente_id)
    if session is None:
        await update.message.reply_text("❌ No existe un caso activo para ese CHAT_ID.")
        return
    if session["modo"] != "ASESOR":
        await update.message.reply_text("❌ Ese cliente no está en modo asesor.")
        return
    if session["asesor_id"] is not None:
        await update.message.reply_text(
            f"⚠️ El caso de {cliente_id} ya fue tomado por el asesor {session['asesor_id']}."
        )
        return
    session["asesor_id"] = chat_id
    try:
        await context.bot.send_message(
            chat_id=cliente_id,
            text="✅ Un asesor se ha unido a la conversación. Te atenderá en breve.",
        )
    except TelegramError:
        session["asesor_id"] = None
        await update.message.reply_text("No se pudo contactar al cliente. El caso continúa pendiente.")
        return
    await notificar_asesores(
        context,
        f"ℹ️ El caso de {cliente_id} fue tomado por el asesor {chat_id}.",
    )
    await update.message.reply_text(f"✅ Caso de {cliente_id} asignado a ti.")


async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not es_asesor(chat_id):
        await update.message.reply_text("❌ No estás autorizado para usar este comando.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /reply CHAT_ID mensaje")
        return
    try:
        cliente_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ CHAT_ID inválido. Debe ser un número.")
        return
    session = usuarios.get(cliente_id)
    if session is None:
        await update.message.reply_text("❌ No existe un caso activo para ese CHAT_ID.")
        return
    if session["asesor_id"] != chat_id:
        await update.message.reply_text("❌ Este caso no está asignado a ti.")
        return
    mensaje = " ".join(context.args[1:])
    try:
        await enviar_texto(context, cliente_id, f"👤 Asesor: {mensaje}")
    except TelegramError:
        await update.message.reply_text("No se pudo completar el envío. El caso continúa activo.")
        return
    await update.message.reply_text("✅ Mensaje enviado al cliente.")


async def cmd_finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not es_asesor(chat_id):
        await update.message.reply_text("❌ No estás autorizado para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /finalizar CHAT_ID")
        return
    try:
        cliente_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ CHAT_ID inválido. Debe ser un número.")
        return
    session = usuarios.get(cliente_id)
    if session is None:
        await update.message.reply_text("❌ No existe un caso activo para ese CHAT_ID.")
        return
    if session["asesor_id"] != chat_id:
        await update.message.reply_text("❌ Este caso no está asignado a ti.")
        return
    try:
        await context.bot.send_message(
            chat_id=cliente_id,
            text="✅ Tu atención ha finalizado. Escribe /start si deseas iniciar una nueva consulta.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except TelegramError:
        await update.message.reply_text("No se pudo comunicar el cierre. El caso continúa activo; reintenta.")
        return
    del usuarios[cliente_id]
    await notificar_asesores(
        context,
        f"ℹ️ El caso de {cliente_id} fue finalizado por el asesor {chat_id}.",
    )
    await update.message.reply_text(f"✅ Caso de {cliente_id} finalizado y cerrado.")


async def procesar_mensaje_cliente(
    update: Update, session: dict, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()
    estado = session["estado"]
    if estado == 'GESTIONES' or estado.startswith('COM_'):
        from commerce import process
        if await process(update, context, session, repository, notificar_asesores):
            return
        await update.message.reply_text(TEXTO_MENU_PRINCIPAL, reply_markup=TECLADO_MENU)
        return

    if estado == "MENU":
        if texto not in ("1", "2", "3", "4", "5", "6"):
            await update.message.reply_text(TEXTO_OPCION_INVALIDA, reply_markup=TECLADO_MENU)
            return
        if texto == '6':
            if repository is None:
                await update.message.reply_text('La base de datos no está configurada.')
                return
            from commerce import GESTIONES
            session['estado'] = 'GESTIONES'
            await update.message.reply_text(GESTIONES, reply_markup=ReplyKeyboardRemove())
            return
        if texto == "5":
            session["modo"] = "ASESOR"
            session["estado"] = "ASESOR"
            entregados = await notificar_asesores(
                context,
                f"📩 Nuevo caso pendiente: cliente {chat_id}.\n"
                f"Para atenderlo: /tomar {chat_id}\n"
                f"Para responder: /reply {chat_id} mensaje\n"
                f"Para cerrar: /finalizar {chat_id}",
            )
            if not entregados:
                session.update(modo="BOT", estado="MENU")
                await update.message.reply_text(
                    "No fue posible contactar a un asesor. Puedes reintentar o continuar en el menú.\n\n"
                    + TEXTO_MENU_PRINCIPAL, reply_markup=TECLADO_MENU,
                )
                return
            await update.message.reply_text(
                TEXTO_MODO_ASESOR, reply_markup=ReplyKeyboardRemove()
            )
            return
        mapa_menu = {"1": "PLANES", "2": "PROMOCIONES", "3": "SERVICIOS", "4": "PAQUETES"}
        session["estado"] = mapa_menu[texto]
        session["menu_anterior"] = None
        await mostrar_catalogo(update, session, session['estado'])
        return

    if estado in CATALOGO:
        from commerce import opcion_valida
        rows = session.get('catalogo_actual', [])
        if texto != '0' and not (texto == '4' and len(rows) < 4) and not opcion_valida(texto, len(rows)):
            await update.message.reply_text(TEXTO_OPCION_INVALIDA, reply_markup=TECLADO_SUBMENU)
            return
        if texto == '0' or (texto == '4' and len(rows) < 4):
            session["estado"] = "MENU"
            session["menu_anterior"] = None
            await update.message.reply_text(TEXTO_MENU_PRINCIPAL, reply_markup=TECLADO_MENU)
            return
        row = rows[int(texto)-1]
        descripcion = row['nombre'] + '\n' + row['descripcion']
        if row['precio'] is not None:
            descripcion += '\nPrecio: S/ ' + row['precio']
        session["menu_anterior"] = estado
        session["estado"] = "OTRA_CONSULTA"
        await update.message.reply_text(
            f"{descripcion}\n\n{TEXTO_DESPUES_DESCRIPCION}",
            reply_markup=TECLADO_OTRA_CONSULTA,
        )
        return

    if estado == "OTRA_CONSULTA":
        if texto not in ("1", "2", "3"):
            await update.message.reply_text(TEXTO_OPCION_INVALIDA, reply_markup=TECLADO_OTRA_CONSULTA)
            return
        if texto == "1":
            session["estado"] = "MENU"
            session["menu_anterior"] = None
            await update.message.reply_text(TEXTO_MENU_PRINCIPAL, reply_markup=TECLADO_MENU)
        elif texto == "2":
            del usuarios[chat_id]
            await update.message.reply_text(
                "Gracias por consultarnos. ¡Hasta pronto! 👋",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            volver = session.get("menu_anterior") or "MENU"
            session["estado"] = volver
            if volver in CATALOGO:
                await mostrar_catalogo(update, session, volver)
            else:
                await update.message.reply_text(TEXTO_MENU_PRINCIPAL, reply_markup=TECLADO_MENU)
        return

    await update.message.reply_text(TEXTO_OPCION_INVALIDA)


async def procesar_mensaje_asesor(update: Update, session: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    texto = update.message.text
    if session["asesor_id"] is not None:
        try:
            await enviar_texto(context, session["asesor_id"], f"📩 Cliente {chat_id}: {texto}")
        except TelegramError:
            await update.message.reply_text("No se pudo completar el envío al asesor. Intenta nuevamente.")
    else:
        enviados = await notificar_asesores(context, f"📩 Cliente {chat_id} (sin asignar): {texto}")
        await update.message.reply_text(
            TEXTO_ESPERANDO_ASESOR if enviados else "No se pudo entregar tu mensaje. Reintenta o escribe menú."
        )


async def entrada_no_admitida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Este prototipo acepta mensajes de texto y opciones numéricas. "
        "Escribe Hola para comenzar o menú para volver al inicio."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return
    chat_id = update.effective_chat.id
    if update.message.text.strip().casefold() in ('menú', 'menu', 'inicio'):
        await cmd_start(update, context)
        return
    if chat_id not in usuarios:
        await cmd_start(update, context)
        return
    session = obtener_o_crear_sesion(chat_id)
    if session["modo"] == "ASESOR":
        await procesar_mensaje_asesor(update, session, context)
    else:
        await procesar_mensaje_cliente(update, session, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Excepción no controlada", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocurrió un error inesperado. Por favor, intenta de nuevo."
            )
        except TelegramError:
            logger.error("No fue posible enviar el aviso de error.")


async def cmd_solicitudes(update, context):
    if not es_asesor(update.effective_chat.id):
        await update.message.reply_text('No autorizado.')
        return
    rows = await asyncio.to_thread(repository.requests)
    await enviar_texto(context, update.effective_chat.id,
        '\n'.join(f"#{r['id']} · cliente {r['cliente_id']} · {r['tipo']} · {r['estado']}" for r in rows) or 'Sin solicitudes.')


async def cmd_estado(update, context):
    if not es_asesor(update.effective_chat.id):
        await update.message.reply_text('No autorizado.')
        return
    if len(context.args) != 2:
        await update.message.reply_text('Uso: /estado ID_SOLICITUD en_atencion|completada|cancelada')
        return
    try:
        client = await asyncio.to_thread(repository.status, int(context.args[0]),
                                         update.effective_chat.id, context.args[1])
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text('Estado de solicitud actualizado.')
    if client is None:
        return
    try:
        await enviar_texto(context, client, f'Solicitud #{context.args[0]}: {context.args[1]}.')
    except TelegramError:
        await update.message.reply_text('El cambio quedó guardado, pero el aviso al cliente no pudo entregarse.')


def main() -> None:
    global repository
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el archivo .env")
    if not ADMIN_CHAT_IDS:
        logger.warning("No hay asesores configurados (ADMIN_CHAT_IDS vacío).")

    from database import Repository, engine_config
    from alembic.config import Config
    from alembic import command
    from persistence import audited
    command.upgrade(Config(str(Path(__file__).with_name('alembic.ini'))), 'head')
    repository = Repository(engine_config())
    repository.seed(ADMIN_CHAT_IDS)
    repository.reset()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(TypeHandler(Update, controlar_acceso), group=-1)

    for name, handler in [('start', cmd_start), ('id', cmd_id), ('tomar', cmd_tomar),
                          ('reply', cmd_reply), ('finalizar', cmd_finalizar),
                          ('solicitudes', cmd_solicitudes), ('estado', cmd_estado)]:
        app.add_handler(CommandHandler(name, audited(handler, repository, usuarios)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, audited(on_message, repository, usuarios)))
    app.add_handler(MessageHandler(filters.ALL, audited(entrada_no_admitida, repository, usuarios)))
    app.add_error_handler(error_handler)

    print("Ruta del archivo ejecutado:", __file__)
    print("Asesores configurados:", sorted(ADMIN_CHAT_IDS))
    print('Acceso público:', ACCESO_PUBLICO)
    print("CHATBOT BITEL INICIADO")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
