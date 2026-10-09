# TeleBOT Integrador — autogestiones telefónicas

Telegram + Python + PostgreSQL + Docker. El bot consulta los catálogos y las
cuentas en PostgreSQL: no inventa respuestas comerciales ni crea datos demo al
arrancar. La carga inicial contiene **15 clientes sintéticos y 30 líneas** para
probar las autogestiones. No hay conexión a los sistemas de una operadora.

## Inicio y acceso

Escribir **Hola**, o cualquier primer mensaje de texto, muestra bienvenida y menú.
No es necesario escribir un comando. `menú`, `menu` o `inicio` vuelve al inicio,
cancela el formulario y cancela el chat de asesor en curso. `/start` conserva la
misma función como reinicio opcional. No cancela solicitudes ya confirmadas.

En `.env`:

```dotenv
ACCESO_PUBLICO=True
ADMIN_CHAT_IDS=123456789,987654321
ALLOWED_USER_IDS=111111111,222222222
```

- `ACCESO_PUBLICO=True`: cualquier cuenta puede usar el bot en chat privado.
- `ACCESO_PUBLICO=False`: solo ALLOWED_USER_IDS y los asesores configurados.
- ADMIN_CHAT_IDS controla los permisos de asesor en ambos modos.
- IDs positivos, separados por comas. Los grupos se ignoran en ambos modos.
- `/id` devuelve el ID de quien escribe; en privado solo responde a autorizados.
- Para obtener IDs nuevos, abrir temporalmente el acceso público, pedir `/id`,
  añadir los IDs a la lista y cerrar el acceso si se desea.
- Cada asesor debe escribirle al bot primero para poder recibir notificaciones.

Después de cambiar configuración:

```powershell
docker compose up -d --force-recreate bot
```

## Configuración y Docker

Copiar `.env.example` a `.env` y completar TELEGRAM_BOT_TOKEN, ADMIN_CHAT_IDS,
ALLOWED_USER_IDS, ACCESO_PUBLICO, POSTGRES_PASSWORD, DB_APP_PASSWORD y
PGADMIN_PASSWORD. `.env` está excluido de Git y de la imagen. Compose entrega
solo las variables necesarias a cada servicio. No se utiliza `.env.docker`.

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 bot
docker compose stop bot
docker compose start bot
```

El bot tiene `restart: no`. No ejecutar simultáneamente otra instancia con el
mismo token. Tras cambiar código: `docker compose up -d --build bot`.
PostgreSQL y pgAdmin tienen volúmenes persistentes. `docker compose down -v`
elimina esos volúmenes: no utilizarlo para detener normalmente.
Cambiar contraseñas en `.env` no actualiza las almacenadas en un volumen existente.

## Menú y DNI

Menú principal: 1 Planes, 2 Promociones, 3 Servicios, 4 Paquetes, 5 Asesor,
6 Autogestiones. Los cuatro catálogos se consultan desde PostgreSQL; no requieren
DNI. En cada catálogo, 0 vuelve al menú. Tras una descripción: 1 nueva consulta,
2 finalizar, 3 regresar. También se acepta 4 para volver en catálogos con menos
de cuatro productos, por compatibilidad con el flujo anterior.

Cada nueva operación de Autogestiones solicita DNI (ocho dígitos ASCII). Un DNI
registrado puede utilizarse desde cualquier cuenta Telegram, según el diseño
acordado. **El DNI identifica un registro; no verifica la identidad del titular.**
El cliente comercial no guarda un ID de Telegram. El chat de origen de una
solicitud se guarda solo para enviar su seguimiento.

| Opción | Preguntas y resultado |
|---|---|
| 1 Adquirir línea | DNI → plan → resumen → confirmar. Asigna un número único y registra la línea con su plan. |
| 2 Portabilidad | DNI → plan → número a portar → operador actual → confirmar solicitud pendiente. |
| 3 Baja | DNI → teléfono entre los asociados → motivo; si es Otro, descripción → confirmar solicitud pendiente. |
| 4 Equipo | DNI → equipo → contado/evaluación de cuotas → dirección de entrega → confirmar solicitud pendiente. |
| 5 Deuda | DNI → seleccionar teléfono → importes y vencimientos registrados, total pendiente. |
| 6 Mis solicitudes | DNI → últimas 20 solicitudes de ese cliente, desde cualquier chat. |
| 7 Contratar servicio | DNI → servicio → dirección si requiere instalación o teléfono asociado → confirmar solicitud pendiente. |
| 0 | Cancelar el formulario y volver al menú principal. |

Si el DNI no existe, se ofrece adquirir la primera línea. Si acepta: elegir plan,
nombre completo y teléfono de contacto → resumen → confirmar. **Cliente y primera
línea se crean en una misma transacción**, sin registrar nada si cancela o falla.
El contacto es distinto del número nuevo que asignará el sistema.

Un cliente puede tener muchas líneas. Cada una tiene un número único de nueve
dígitos comenzando en 9 y un plan. La base garantiza la unicidad; se reintenta
la asignación si hay una colisión. El estado activo/inactivo no filtra los flujos.
Adquirir una línea adicional no duplica el cliente y no genera ninguna deuda.
La misma confirmación tiene un UUID de operación para evitar registros duplicados
al reintentar. Una nueva adquisición iniciada por el usuario es otra operación.

Deuda muestra únicamente registros **no pagados del número elegido**, comprobando
que pertenece al DNI. Si no hay registros pendientes, lo informa; no crea importes.
Registrar una línea asigna un número en esta base, no activa un servicio de operadora.
Portabilidad, baja, equipos y servicios requieren atención posterior; no hay cobros.

## Base de datos y carga inicial

- pgAdmin: http://localhost:5050, `admin@telebot.com`, PGADMIN_PASSWORD de `.env`.
- Servidor preconfigurado TeleBOT PostgreSQL: usuario `telebot`, POSTGRES_PASSWORD.
- Base `telebot`, puerto 5432. Host `postgres` en Docker, `localhost` en Windows.
- Bot: `telebot_app`, sin permisos de superusuario, creación de bases o roles.
- Alembic aplica la revisión 002 al arrancar. Hay **14 tablas de aplicación** más
  alembic_version. `contactos` representa chats; `clientes` representa titulares
  por DNI. Conversaciones/sesiones usan chat_id; líneas usan cliente_id.
- Sesiones y chats de asesor se reinician al arrancar; mensajes, clientes, líneas,
  deudas y solicitudes permanecen. Los updates pendientes de Telegram se descartan.

La migración 002 retiró el negocio demo anterior con autorización y preservó
conversaciones/mensajes/contactos. Respaldo previo: `respaldos/telebot_antes_dni.dump`
(no versionado ni incluido en la imagen). No volver a aplicar una limpieza manual.

En una instalación nueva, después de aplicar las migraciones:

```powershell
docker compose run --rm --no-deps bot python -m alembic upgrade head
docker compose run --rm --no-deps bot python cargar_ejemplos.py
```

La carga es una transacción separada y no forma parte del arranque. Si encuentra
la carga de ejemplo existente, no la duplica; no sirve para reparar filas borradas.
Si hay otros planes sin esta carga, se detiene para no mezclar catálogos.

- DNI de prueba: **00001001 a 00001015**; mantener ceros iniciales.
- Cinco clientes con una línea, cinco con dos y cinco con tres: 30 números únicos.
- Hay teléfonos sin deuda, con deuda pagada y con una o varias deudas pendientes.
- `00001011` tiene tres líneas: elegir la tercera muestra dos deudas pendientes.
- DNI no registrado para probar alta: `12345678`, si no se ha registrado antes.
- Datos sintéticos: no representan clientes identificados ni contratos externos.

Consultar números cargados desde pgAdmin:

```sql
SELECT c.dni, c.nombre, l.numero, p.nombre AS plan
FROM clientes c JOIN lineas l ON l.cliente_id = c.id
JOIN planes p ON p.id = l.plan_id
ORDER BY c.dni, l.id;
```

## Asesores

```text
/tomar ID_CHAT
/reply ID_CHAT mensaje
/finalizar ID_CHAT
/solicitudes
/estado ID_SOLICITUD en_atencion
/estado ID_SOLICITUD completada
/estado ID_SOLICITUD cancelada
```

La toma de chat es exclusiva; solo su asesor puede responder/cerrar. Las
asignaciones de solicitud son independientes y guardan historial de cambios.
Estados: pendiente → en_atencion → completada/cancelada; pendiente → cancelada.
Las líneas contratadas directamente se registran como completadas y no pasan
por estas transiciones. El aviso de cambio de una solicitud va al chat que la creó.
Cambiar un estado no ejecuta por sí mismo una portabilidad, baja ni instalación.

## Pruebas y medición

Crear telebot_test si no existe y ejecutar:

```powershell
docker compose exec -T postgres psql -U telebot -d telebot -c "CREATE DATABASE telebot_test OWNER telebot_app;"
docker compose run --rm --no-deps -e DB_NAME=telebot_test bot python -m unittest -v test_flujo test_postgres
docker compose run --rm --no-deps -e DB_NAME=telebot_test bot python benchmark.py
```

Estos scripts limpian solo telebot_test. Se simula Telegram, no PostgreSQL.
Los resultados de la versión actual están en resultados_verificacion.json.
El benchmark utiliza 50 chats y 300 entradas secuenciales; no mide la latencia
de Telegram. Las pruebas incluyen concurrencia de confirmación y colisión de
números. Las consultas de handlers se ejecutan fuera del event loop.

## Documentación

El generador conserva los Word anteriores y crea **Documentacion Tecnica Chatbot
Bitel v3.docx** en la carpeta superior, junto con PNG y Mermaid en docs_generados.
El diccionario y las relaciones se derivan del modelo SQLAlchemy actual.

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-docs.txt
.\venv\Scripts\python.exe generar_documentacion.py
```

Los diagramas son figuras técnicas. Las capturas de Telegram y una prueba con
dos cuentas reales se incorporan cuando se obtengan. Para ejecutar localmente:
PostgreSQL activo, bot Docker detenido, requirements.txt instalado y
`python bot_corregido.py`; usa .env y localhost:5432 por defecto.
