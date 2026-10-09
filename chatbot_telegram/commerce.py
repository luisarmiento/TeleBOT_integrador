"""Autogestiones por DNI; PostgreSQL es la fuente de datos comerciales."""
import asyncio
from uuid import uuid4

TIPOS = {'linea_nueva': 'Adquirir línea', 'portabilidad': 'Portabilidad', 'baja': 'Baja de línea',
         'equipo': 'Adquirir equipo', 'deuda': 'Consultar deuda', 'solicitudes': 'Mis solicitudes',
         'servicio': 'Contratar servicio'}
GESTIONES = ('AUTOGESTIONES\n1 Adquirir línea\n2 Portabilidad\n3 Solicitar baja\n'
             '4 Adquirir equipo\n5 Consultar deuda\n6 Mis solicitudes\n7 Contratar servicio\n0 Menú principal')


async def consultar(repo, method, *args):
    return await asyncio.to_thread(getattr(repo, method), *args)


def opcion_valida(text, count):
    return text.isascii() and text.isdigit() and len(text) <= 6 and 1 <= int(text) <= count


def digits(text, length):
    return len(text) == length and text.isascii() and text.isdigit()


async def confirm(session, say):
    session['estado'] = 'COM_CONFIRMAR'
    form = session['formulario']
    labels = {'dni': 'DNI', 'nombre': 'Nombre', 'telefono': 'Contacto', 'producto': 'Producto',
              'precio': 'Precio S/', 'linea': 'Número', 'numero': 'Número a portar',
              'operador': 'Operador de origen', 'motivo': 'Motivo', 'modalidad': 'Modalidad',
              'direccion': 'Dirección de instalación/entrega'}
    lines = [f"Gestión: {TIPOS[form['tipo']]}"]
    lines.extend(f'{label}: {form[key]}' for key, label in labels.items() if key in form)
    lines.append('Se registrará una línea con el plan elegido.' if form['tipo'] == 'linea_nueva'
                 else 'Se registrará una solicitud para atención. No se procesará un cobro.')
    await say('RESUMEN\n' + '\n'.join(lines) + '\n1 Confirmar\n2 Cancelar\n0 Menú')


async def begin(session, repo, say):
    form = session['formulario']
    kind = form['tipo']
    client = session.get('cliente_id')
    if kind == 'solicitudes':
        rows = await consultar(repo, 'requests', client)
        await say('\n'.join(f"#{r['id']} · {TIPOS.get(r['tipo'], r['tipo'])} · {r['estado']}" for r in rows) or 'No registra solicitudes.')
        session.update(estado='GESTIONES', formulario={})
        await say(GESTIONES)
    elif kind in ('baja', 'deuda'):
        rows = await consultar(repo, 'lines', client)
        if not rows:
            session.update(estado='GESTIONES', formulario={})
            await say('No hay números registrados para este DNI.\n' + GESTIONES)
            return
        session.update(estado='COM_LINEA', opciones=[dict(r) for r in rows])
        await say('¿De qué teléfono deseas realizar la gestión?\n' + '\n'.join(
            f"{i}. {r['numero']}" for i, r in enumerate(rows, 1)) + '\n0 Cancelar')
    else:
        table = {'equipo': 'equipos', 'servicio': 'SERVICIOS'}.get(kind, 'planes')
        rows = await consultar(repo, 'catalog', table)
        if not rows:
            session.update(estado='GESTIONES', formulario={})
            await say('No hay productos disponibles.\n' + GESTIONES)
            return
        session.update(estado='COM_PRODUCTO', opciones=[{**r, 'precio': str(r['precio'])} for r in rows])
        await say('Selecciona un producto:\n' + '\n'.join(
            f"{i}. {r['nombre']} · S/ {r['precio']}" for i, r in enumerate(rows, 1)) + '\n0 Cancelar')


async def process(update, context, session, repo, notify):
    chat = update.effective_chat.id
    text = update.message.text.strip()
    state = session['estado']

    async def say(msg):
        for offset in range(0, len(msg), 2000):
            await update.message.reply_text(msg[offset:offset+2000])

    if text.casefold() in ('0', 'menú', 'menu', 'cancelar'):
        session.update(estado='MENU', formulario={})
        session.pop('cliente_id', None)
        return False
    if state == 'GESTIONES':
        kinds = {'1': 'linea_nueva', '2': 'portabilidad', '3': 'baja', '4': 'equipo',
                 '5': 'deuda', '6': 'solicitudes', '7': 'servicio'}
        if text not in kinds:
            await say('Selecciona una opción.\n' + GESTIONES)
            return True
        session.pop('cliente_id', None)
        session.update(estado='COM_DNI', formulario={'tipo': kinds[text], 'operacion': str(uuid4())})
        await say('Ingresa tu DNI de 8 dígitos.\n0 Cancelar')
        return True
    form = session['formulario']
    if state == 'COM_DNI':
        if not digits(text, 8):
            await say('El DNI debe tener exactamente 8 dígitos.\n0 Cancelar')
        else:
            form['dni'] = text
            customer = await consultar(repo, 'customer', text)
            if customer:
                session['cliente_id'] = customer['id']
                await begin(session, repo, say)
            else:
                session['estado'] = 'COM_ALTA'
                await say('No encontramos un cliente con ese DNI. ¿Deseas adquirir tu primera línea?\n1 Ver planes\n2 Volver\n0 Menú')
    elif state == 'COM_ALTA':
        if text == '1':
            form['tipo'] = 'linea_nueva'
            await begin(session, repo, say)
        elif text == '2':
            session.update(estado='GESTIONES', formulario={})
            await say(GESTIONES)
        else:
            await say('1 Ver planes · 2 Volver · 0 Menú')
    elif state == 'COM_PRODUCTO':
        if not opcion_valida(text, len(session['opciones'])):
            await say('Selecciona una opción válida.\n0 Cancelar')
            return True
        row = session['opciones'][int(text)-1]
        form.update(producto_id=row['id'], producto=row['nombre'], precio=row['precio'])
        if not session.get('cliente_id'):
            session['estado'] = 'COM_NOMBRE'
            await say('Ingresa tus nombres y apellidos completos.\n0 Cancelar')
        elif form['tipo'] == 'portabilidad':
            session['estado'] = 'COM_NUMERO'
            await say('¿Qué número deseas portar? Ingresa 9 dígitos comenzando por 9.\n0 Cancelar')
        elif form['tipo'] == 'equipo':
            session['estado'] = 'COM_MODALIDAD'
            await say('¿Cómo deseas adquirir el equipo?\n1 Contado\n2 Evaluación de cuotas\n0 Cancelar')
        elif form['tipo'] == 'servicio':
            if row['requiere_direccion']:
                session['estado'] = 'COM_DIRECCION'
                await say('Indica distrito, calle y número para evaluar la instalación.\n0 Cancelar')
            else:
                rows = await consultar(repo, 'lines', session['cliente_id'])
                if not rows:
                    session.update(estado='GESTIONES', formulario={})
                    await say('No hay números registrados para asociar el servicio.\n' + GESTIONES)
                else:
                    session.update(estado='COM_LINEA', opciones=rows)
                    await say('¿A qué número deseas asociarlo?\n' + '\n'.join(
                        f"{i}. {r['numero']}" for i, r in enumerate(rows, 1)) + '\n0 Cancelar')
        else:
            await confirm(session, say)
    elif state == 'COM_NOMBRE':
        if not 5 <= len(text) <= 200 or len(text.split()) < 2 or not all(c.isalpha() or c in " '-" for c in text):
            await say('Ingresa nombres y apellidos completos (5 a 200 caracteres).')
        else:
            form['nombre'] = text
            session['estado'] = 'COM_CONTACTO'
            await say('Ingresa un teléfono de contacto de 9 dígitos que comience por 9. Es distinto de la línea que se asignará.\n0 Cancelar')
    elif state in ('COM_CONTACTO', 'COM_NUMERO'):
        if not digits(text, 9) or not text.startswith('9'):
            await say('Usa 9 dígitos comenzando por 9.\n0 Cancelar')
        elif state == 'COM_CONTACTO':
            form['telefono'] = text
            await confirm(session, say)
        else:
            form['numero'] = text
            session['estado'] = 'COM_OPERADOR'
            await say('¿Cuál es tu operador actual?\n0 Cancelar')
    elif state in ('COM_OPERADOR', 'COM_DIRECCION'):
        minimum = 10 if state == 'COM_DIRECCION' else 2
        if not minimum <= len(text) <= 250:
            await say(f'Ingresa entre {minimum} y 250 caracteres.\n0 Cancelar')
        else:
            form['direccion' if state == 'COM_DIRECCION' else 'operador'] = text
            await confirm(session, say)
    elif state == 'COM_DETALLE':
        if not 5 <= len(text) <= 250:
            await say('Describe el motivo en 5 a 250 caracteres.\n0 Cancelar')
        else:
            form['motivo'] = text
            await confirm(session, say)
    elif state == 'COM_LINEA':
        if not opcion_valida(text, len(session['opciones'])):
            await say('Selecciona uno de los números mostrados.\n0 Cancelar')
            return True
        row = session['opciones'][int(text)-1]
        form.update(linea_id=row['id'], linea=row['numero'])
        if form['tipo'] == 'deuda':
            rows = await consultar(repo, 'debt', session['cliente_id'], row['id'])
            await say(f"Número: {row['numero']}\n" + ('\n'.join(
                f"S/ {r['importe']:.2f} · vence {r['vencimiento'] or 'sin fecha'}" for r in rows)
                + f"\nTotal pendiente: S/ {sum(r['importe'] for r in rows):.2f}" if rows
                else 'Este número no registra deudas pendientes.'))
            session.update(estado='GESTIONES', formulario={})
            await say(GESTIONES)
        elif form['tipo'] == 'baja':
            session['estado'] = 'COM_MOTIVO'
            await say('¿Cuál es el motivo?\n1 Costo\n2 Cobertura\n3 Otro\n0 Cancelar')
        else:
            await confirm(session, say)
    elif state in ('COM_MOTIVO', 'COM_MODALIDAD'):
        options = {'1': 'Costo', '2': 'Cobertura', '3': 'Otro'} if state == 'COM_MOTIVO' else {'1': 'Contado', '2': 'Evaluación de cuotas'}
        if text not in options:
            await say('Selecciona una opción válida.\n0 Cancelar')
        else:
            form['motivo' if state == 'COM_MOTIVO' else 'modalidad'] = options[text]
            if state == 'COM_MODALIDAD':
                session['estado'] = 'COM_DIRECCION'
                await say('Indica distrito, calle y número para la entrega del equipo.\n0 Cancelar')
            elif text == '3':
                session['estado'] = 'COM_DETALLE'
                await say('Describe el motivo de la baja.\n0 Cancelar')
            else:
                await confirm(session, say)
    elif state == 'COM_CONFIRMAR':
        if text == '2':
            session.update(estado='GESTIONES', formulario={})
            await say('Operación cancelada.\n' + GESTIONES)
        elif text == '1':
            try:
                result = await consultar(repo, 'contract', chat, form)
            except ValueError as exc:
                await say(str(exc) + '\n0 Menú')
                return True
            number = result['datos'].get('numero_asignado')
            session.update(estado='GESTIONES', formulario={})
            await say(f"Registro #{result['id']} · {result['estado']}." +
                (f'\nTu número asignado: {number}' if number else '\nLa solicitud será atendida por un asesor.') + '\n' + GESTIONES)
            if result['estado'] == 'pendiente':
                await notify(context, f"Nueva solicitud #{result['id']}.\n/estado {result['id']} en_atencion")
        else:
            await say('1 Confirmar · 2 Cancelar · 0 Menú')
    return True
