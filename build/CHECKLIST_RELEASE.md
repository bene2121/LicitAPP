# Checklist de Release — SECOP Automatizador v1.0

## Antes de hacer el build

- [ ] Versión actualizada en build/setup.iss (AppVersion)
- [ ] .env configurado con URL de API central real (SECOP_API_URL)
- [ ] Licencia de prueba generada y válida (licencias/licencias_generadas/)
- [ ] Ícono icon.ico presente en build/
- [ ] API central corriendo en VPS con HTTPS
- [ ] SSL válido en api.secop-automatizador.com
- [ ] Ingestor SECOP ejecutado al menos una vez (datos en PostgreSQL)

## Build

- [ ] Ejecutar build/build_windows.bat sin errores
- [ ] Verificar dist/SECOP_Automatizador/SECOP_Automatizador.exe existe
- [ ] Probar .exe directamente (sin instalador): doble clic en el .exe
- [ ] Splash aparece correctamente
- [ ] Dashboard carga en ventana nativa (no en navegador)
- [ ] Datos demo muestran en el Explorador
- [ ] Calculadora de fórmulas funciona
- [ ] Tab Bot muestra el formulario correctamente

## Instalador

- [ ] Abrir build/setup.iss en Inno Setup 6
- [ ] Compilar sin errores (F9)
- [ ] dist/installer/SECOP_Automatizador_Setup_v1.0.exe existe
- [ ] Instalar en Windows limpio (o VM)
- [ ] Icono en escritorio creado correctamente
- [ ] App abre desde el icono del escritorio
- [ ] Desinstalación limpia (sin archivos residuales en Archivos de programa)

## Distribución

- [ ] Subir instalador a servidor de distribución
- [ ] Generar licencia para el primer cliente
- [ ] Documentar contraseña/usuario del cliente
- [ ] Enviar instalador + licencia + LEAME_CLIENTE.txt al cliente
- [ ] Confirmar que el cliente pudo instalar y activar
