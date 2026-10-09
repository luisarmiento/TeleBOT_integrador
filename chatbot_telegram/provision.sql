-- Ejecutar como administrador; contraseña suministrada por psql, no incluida aquí.
SELECT format('CREATE ROLE telebot_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telebot_app') \gexec
GRANT CONNECT ON DATABASE telebot TO telebot_app;
GRANT USAGE, CREATE ON SCHEMA public TO telebot_app;
