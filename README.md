# TeleBOT Integrador

Chatbot de Telegram para atención y autogestiones telefónicas con Python,
PostgreSQL, Alembic y Docker Compose.

## Funciones

- Inicio con cualquier primer mensaje de texto.
- Acceso público o privado configurable.
- Catálogos consultados desde PostgreSQL.
- Identificación por DNI, clientes con varias líneas y deuda por teléfono.
- Registro de clientes y líneas con confirmación transaccional.
- Solicitudes de portabilidad, baja, equipos y servicios con seguimiento por asesor.

## Instalación

Desde `chatbot_telegram`, copiar `.env.example` a `.env`, completar las variables
y ejecutar con Docker Desktop activo:

```powershell
docker compose up -d --build
```

Para cargar los 15 clientes de ejemplo y sus 30 líneas en una instalación nueva:

```powershell
docker compose run --rm --no-deps bot python cargar_ejemplos.py
```

La carga es explícita y no se repite al arrancar. Los datos de ejemplo no
representan personas verificadas ni servicios activados por una operadora.

## Documentación

- [Guía completa de configuración, autogestiones y pruebas](chatbot_telegram/README.md).
- [Documentación técnica v3 en Markdown](chatbot_telegram/docs_generados/documentacion_v3.md).
- `Documentacion Tecnica Chatbot Bitel v3.docx`: Word con diccionario y diagramas.
- [Modelo de datos Mermaid](chatbot_telegram/docs_generados/modelo_datos.mmd).

Las versiones anteriores del Word se conservan como referencias históricas.
Las pruebas utilizan una base aislada `telebot_test` y Telegram simulado.

## Configuración

El repositorio incluye la plantilla `.env.example`. El archivo `.env` real,
respaldos, logs y entornos virtuales quedan excluidos del control de versiones.
No existe integración externa con una operadora ni procesamiento de cobros.
