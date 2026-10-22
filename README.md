# Golmar G2Call+ para Home Assistant

Integración personalizada de Home Assistant para el **porterillo Golmar ART4HW/G2+** (familia Art 4W, app oficial **G2Call+** sobre el stack Qualvision). Permite abrir las cerraduras del portal y de la puerta principal desde Home Assistant y recibir los avisos de timbre y llamada.

> ⚠️ **Proyecto no oficial**: no está afiliado ni respaldado por Golmar ni por Qualvision. Úsalo bajo tu responsabilidad. Las aperturas accionan la cerradura **real**: asegúrate de que es seguro antes de probar.

## Funcionalidades

| Función | Estado |
|---|---|
| Abrir por **cloud** | ✅ |
| Abrir por **CGI local** como respaldo (sin Internet, monitor despierto) | ✅ |
| Estado online, modelo y firmware | ✅ |
| Timbre y llamadas (polling, sin FCM) | ✅ |
| Snapshot del evento | ✅ opcional (si la nube lo incluye) |
| Vídeo en vivo | ❌ no soportado (protocolo QUII propietario) |

## Requisitos

- Home Assistant **2026.10.0** o superior.
- Cuenta de la app **G2Call+** (email o teléfono).
- **Etiqueta/QR del monitor**: UID de 12 caracteres y contraseña del equipo de 8 mayúsculas.
- Código de apertura: el que hayas fijado en la app (**Seguridad → Cambiar contraseña**). Solo se usa en la vía local.

## Instalación

### HACS (recomendado)

1. HACS → **Integraciones** → menú de tres puntos → **Repositorios personalizados**.
2. Añade `https://github.com/Sunek0/golmar-g2call` con categoría **Integration**.
3. Busca **Golmar G2Call+** e instálalo.
4. Reinicia Home Assistant.

### Manual

Copia la carpeta `custom_components/golmar_g2call/` de este repositorio en `<config>/custom_components/` y reinicia Home Assistant.

## Configuración

1. **Ajustes → Dispositivos y servicios → Añadir integración → Golmar G2Call+**.
2. Rellena:

| Campo | Descripción |
|---|---|
| Cuenta | Email/teléfono de tu cuenta G2Call+. |
| Contraseña de la cuenta | Se guarda **solo su SHA-256**, nunca la contraseña en claro. |
| UID del equipo | 12 caracteres de la etiqueta del monitor. |
| Contraseña del equipo | 8 mayúsculas de la etiqueta. |
| Código de apertura | El fijado en la app (vía local). |
| Host / puerto / esquema | IP del monitor (puede cambiar), `443` y `https`. |
| Verificar TLS | Desactivado: el monitor usa un certificado autofirmado. |

3. En el paso **Puertas** elige qué cerraduras exponer. La integración consulta `get.device.attachInfo` cuando el monitor está despierto y muestra cada par door/lock descubierto: la **Puerta principal** viene activada y el **Portal** desactivado (puedes cambiarlo después en Opciones).
4. Si el monitor está dormido (el CGI solo se abre unos segundos al entrar en "Información" en la app), el alta continúa igualmente: la vía cloud no necesita el monitor.

### Reconfigurar y opciones

- **Reconfigurar**: cambia host/puerto/esquema, credenciales y el mapa de cerraduras sin borrar la entrada (las entidades se conservan).
- **Configurar (Opciones)**: activa o desactiva Puerta principal y Portal, actualiza el código de apertura y la contraseña del equipo, y ajusta el **intervalo de eventos** (15-120 s, 30 s por defecto). Los secretos guardados aparecen precargados; vacío = mantener el actual.
- **Reautenticación**: se lanza sola si el monitor rechaza la contraseña del equipo (401) o si la cadena de tokens cloud muere.

## Cómo funciona

```
┌──────────────────────────── Home Assistant ────────────────────────────┐
│  entrada de configuración ──► coordinador (identidad local cada 15 min) │
│      │                                                                  │
│      ├── vía PRIMARIA: cloud Qualvision                                 │
│      │     OAuth (r1-2.qvcloud.net) → token 1 h / refresh 24 h          │
│      │     POST tdkopenapir1.qvcloud.net/openapi-tdk/devctr/            │
│      │          synccontrol/singledev  (deviceId = UID de la etiqueta)  │
│      │                                                                  │
│      ├── vía SECUNDARIA: CGI local del monitor                          │
│      │     POST https://<monitor>/tdkcgi  (TLS autofirmado)             │
│      │     set.device.opendoor  (door, lock, SHA256(código))            │
│      │                                                                  │
│      └── eventos: sesión JUS + servidor de alarmas (polling 30 s)       │
└─────────────────────────────────────────────────────────────────────────┘
```

- Cada pulsación intenta primero el **cloud**; si falla, prueba **una sola vez** la vía local. Nunca se envían las dos.
- Límite de **una apertura cada 3 segundos** por entrada (evita dobles pulsaciones).
- **Tokens**: el access token dura 1 hora y el refresh 24 horas. La integración renueva **de forma proactiva** con 5 minutos de margen (nunca espera a un 401). Si la cadena muere (24 h sin conexión o revocación), Home Assistant pedirá la contraseña de la cuenta mediante reautenticación.

### Eventos (timbre y llamadas)

La integración mantiene una **sesión** contra el servicio de cuentas y consulta el **servidor de alarmas** cada 30 s (configurable entre 15 y 120 s). Cada evento nuevo se deduplica y alimenta las entidades de evento, timbre y último evento; si el evento trae imagen en la nube, también la cámara de último snapshot.

- **Sin FCM ni MQTT**: la latencia es la del intervalo de polling.
- El primer ciclo tras configurar solo marca el histórico como visto (no dispara automatizaciones).
- La sesión se renueva en silencio (cada ~25 min) usando el hash de la contraseña ya guardado; no hay que reautenticar.

## Entidades

| Entidad | Descripción |
|---|---|
| `button.puerta_principal` | Abre la puerta principal (door 9, lock 1). |
| `button.portal` | Abre el portal (door 1, lock 1). Deshabilitada por defecto. |
| `event.timbre` | Eventos de timbre/llamada (`ring`, `call`, `missed`, `unlock`) con canal y dispositivo. |
| `binary_sensor.timbre_activo` | Activo 30 s tras un timbre o llamada. |
| `sensor.ultimo_evento` | Timestamp del último evento + tipo, canal, dispositivo y si hay snapshot. |
| `camera.ultima_captura` | Último snapshot recibido (solo memoria; no disponible sin imagen). |
| `binary_sensor.conectividad` | El monitor responde a la identificación local. |
| `sensor.modelo` / `sensor.firmware` | Diagnóstico del equipo. |

Los identificadores únicos derivan del UID del equipo y del par door/lock, así que sobreviven a cambios de IP y reconfiguraciones.

## Limitaciones conocidas

- **El CGI local es transitorio**: solo se abre unos segundos al entrar en "Información" en la app. Si la vía cloud falla y el monitor duerme, el botón pedirá abrir G2Call+ → Información y reintentar. La vía cloud no tiene esta limitación.
- **La IP del monitor cambia** (MAC aleatoria). Recomendación: reserva DHCP en el router; si cambia, usa **Reconfigurar**.
- **TLS**: el monitor y los servidores cloud de Qualvision usan certificados **autofirmados**. La integración no verifica TLS por defecto; actívalo solo si los sustituyes.
- **Firmware validado**: `V200.R005.A011.00.G0053.B010` (2022-04-12). Otros firmwares podrían cambiar el protocolo.
- **Eventos**: se obtienen por polling (30 s por defecto); el snapshot solo aparece si el evento lo incluye en la nube. El **vídeo en vivo no está soportado**.

## Solución de problemas

| Síntoma | Qué hacer |
|---|---|
| La integración no aparece al añadir | Reinicia Home Assistant tras instalar/copiar el componente y revisa los logs. |
| `No se pudo conectar con el monitor` | Abre G2Call+ → Información del dispositivo y reintenta (despierta el CGI). |
| `Credenciales de la cuenta incorrectas` | Revisa email/contraseña de G2Call+. No se reintenta automáticamente para evitar bloqueos. |
| `Contraseña del equipo incorrecta` | Revisa las 8 mayúsculas de la etiqueta. |
| El botón falla y pide reautenticación | Cambiaste la contraseña del equipo en el hardware o caducó la cadena de tokens: completa el flujo de reautenticación. |
| Cambió la IP del monitor | **Reconfigurar** con la nueva IP (reserva DHCP recomendada). |
| No llegan eventos | Revisa que la cuenta siga siendo válida y el intervalo de eventos en Opciones; el primer ciclo solo marca el histórico. |

## Diagnóstico y privacidad

**Ajustes → Dispositivos y servicios → Golmar G2Call+ → Descargar diagnóstico**: incluye un resumen sin secretos (contraseñas, código de apertura, hash de la cuenta y tokens redactados; solo se indican booleanos de "configurado", el estado de la sesión de eventos y el último evento). La integración solo habla con tu monitor y con los servidores que ya usa la app oficial.

## Desinstalación

1. **Ajustes → Dispositivos y servicios → Golmar G2Call+ → Eliminar**.
2. Borra `custom_components/golmar_g2call/` y reinicia Home Assistant.

## Licencia

MIT — ver [LICENSE](LICENSE).
