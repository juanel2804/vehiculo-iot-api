-- Usuario de MySQL con privilegios mínimos para la API (solo ejecuta Stored Procedures).
-- Ejecútalo con el usuario admin de RDS. Cambia la contraseña antes de correrlo.
CREATE USER IF NOT EXISTS 'api_iot'@'%' IDENTIFIED BY 'CAMBIA_ESTA_CONTRASENA';
GRANT EXECUTE ON vehiculo_iot.* TO 'api_iot'@'%';
FLUSH PRIVILEGES;
