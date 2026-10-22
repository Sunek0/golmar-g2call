# Golmar G2Call+ para Home Assistant

Integración personalizada (HACS) para el **porterillo Golmar ART4HW/G2+** (familia Art 4W, app G2Call+ / stack Qualvision). Abre las cerraduras del portal y de la puerta principal desde Home Assistant.

> Proyecto de interoperabilidad con el equipo propio. No se distribuyen secretos ni material del APK.

## Qué hace

| Función | Estado |
|---|---|
| Abrir **Puerta principal** (door 9, lock 1) por **cloud** | ✅ validado (apertura física real) |
| Abrir **Portal** (door 1, lock 1) | ✅ validado por cloud; entidad deshabilitada por defecto hasta validarla en tu instalación |
| Abrir por **CGI local** como respaldo (sin Internet, monitor despierto) | ✅ validado con el equipo real |
| Apertura fiable sin abrir la app | ✅ vía cloud (OAuth → OpenAPI `synccontrol`) |
| Estado online / modelo / firmware | ✅ (identificación local cada 15 min) |
| Timbre, eventos y cámara | ✅ Timbre/llamadas por polling (sin FCM) + snapshot opcional |
| Vídeo en vivo | ❌ no soportado (protocolo QUII propietario) |

## Arquitectura

```
┌──────────────────────────── Home Assistant ────────────────────────────┐
│  config entry  ──►  coordinador (identidad local 15 min + tokens)      │
│      │                                                                 │
│      ├── vía PRIMARIA: cloud Qualvision                                │
│      │     OAuth (r1-2.qvcloud.net) → token 1 h / refresh 24 h         │
│      │     POST tdkopenapir1.qvcloud.net /openapi-tdk/devctr/          │
│      │          synccontrol/singledev  (deviceId = UID de etiqueta)    │
│      │                                                                 │
│      └── vía SECUNDARIA: CGI local del monitor                         │
│            POST https://<monitor>/tdkcgi   (TLS autofirmado)           │
│            set.device.opendoor  (door, lock, SHA256(código))           │
└────────────────────────────────────────────────────────────────────────┘
```

Cada pulsación intenta primero el cloud; si falla, prueba una sola vez la vía local. Nunca se envían las dos. Límite: una apertura cada 3 segundos por entrada.

## Instalación

1. Copia `custom_components/golmar_g2call/` en `<config>/custom_components/` (o instala el repo por HACS como integración personalizada).
2. Reinicia Home Assistant.
3. **Ajustes → Dispositivos y servicios → Añadir integración → Golmar G2Call+**.

### Datos que necesitas

- **Cuenta G2Call+** (email/teléfono) y su contraseña. La integración guarda **solo el SHA-256** de la contraseña, nunca la contraseña en claro.
- **Etiqueta/QR del monitor**: UID de 12 caracteres y contraseña del equipo de 8 mayúsculas.
- **Código de apertura**: el que fijaste en la app (Seguridad → Cambiar contraseña). Se usa en la vía local.
- IP/host del monitor (opcional: la vía cloud no lo necesita).

## Cómo se comporta

### Tokens (por qué no falla cada hora)

- `access_token` dura **1 hora**; `refresh_token` dura **24 horas** y cada renovación emite uno nuevo.
- La integración renueva **de forma proactiva** con 5 minutos de margen (en cada ciclo del coordinador y antes de cada apertura). Nunca espera a un 401.
- Si la cadena muere (24 h sin conexión o revocación), Home Assistant pedirá la **contraseña de la cuenta** mediante el flujo de reautenticación.

### Eventos (timbre y llamadas)

La integración mantiene una **sesión JUS** (login duplex, renovada en silencio con el hash guardado) y consulta el servidor de alarmas cada **30 s** (15-120 s configurable en Opciones). Cada evento nuevo se deduplica por `alarmid` y alimenta:

- `event.timbre` (tipos `ring`/`call`/`missed`/`unlock`),
- `binary_sensor.timbre_activo` (30 s),
- `sensor.ultimo_evento` y `camera.ultima_captura` (si el evento trae imagen).

Sin FCM ni MQTT: la latencia es la del polling. El primer ciclo tras configurar solo marca el histórico como visto (no dispara automatizaciones).

### Limitaciones conocidas

- **El CGI local del monitor es transitorio**: solo se abre unos segundos al entrar en "Información" en la app G2Call+. Si la vía cloud falla y el monitor está dormido, el botón te pedirá abrir G2Call+ → Información del dispositivo y reintentar. La vía cloud no tiene esta limitación.
- **La IP del monitor cambia** (MAC aleatoria). Recomendación: reserva DHCP por MAC/hostname en el router; si cambia, usa **Reconfigurar** en la integración (las entidades se conservan).
- **TLS**: tanto el monitor como los servidores cloud de Qualvision usan certificados **autofirmados**. La integración no verifica TLS por defecto; actívalo solo si sustituyes los certificados.
- **Eventos/timbre**: se obtienen por **polling** contra el servidor de alarmas (30 s por defecto, 15-120 s configurable en Opciones); **sin FCM**. El timbre/llamada llega con esa latencia.
- **Snapshot**: solo si el evento trae imagen en la nube; en caso contrario la cámara queda no disponible (no afecta al resto).
- **Firmware validado**: `V200.R005.A011.00.G0053.B010` (2022-04-12). Otros firmwares podrían cambiar el protocolo.

## Entidades

| Entidad | Descripción |
|---|---|
| `button.puerta_principal` | Abre la puerta principal (door 9, lock 1). |
| `button.portal` | Abre el portal (door 1, lock 1). Deshabilitada por defecto. |
| `event.timbre` | Eventos de timbre/llamada (`ring`, `call`, `missed`, `unlock`) con atributos de canal y dispositivo. |
| `binary_sensor.timbre_activo` | Activo 30 s tras un timbre o llamada. |
| `sensor.ultimo_evento` | Timestamp del último evento + tipo, canal, dispositivo y si hay snapshot. |
| `camera.ultima_captura` | Último snapshot recibido por evento (solo memoria; no disponible sin imagen). |
| `binary_sensor.conectividad` | Monitor alcanzable por la vía local (última identificación). |
| `sensor.modelo` / `sensor.firmware` | Diagnóstico del equipo. |

## Diagnóstico y privacidad

- Descarga de diagnóstico: **Ajustes → Dispositivos y servicios → Golmar G2Call+ → Descargar diagnóstico**. Redacta contraseñas, código de apertura, hash de la cuenta y tokens.
- No se envían datos a terceros. La integración habla únicamente con tu monitor y con los servidores de Golmar/Qualvision que ya usa la app oficial.

## Desinstalación

1. **Ajustes → Dispositivos y servicios → Golmar G2Call+ → Eliminar**.
2. Borra `custom_components/golmar_g2call/` y reinicia.

## Desarrollo

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python pytest pytest-homeassistant-custom-component
.venv/bin/python -m pytest
uvx ruff check custom_components tests
```

Los clientes (`oauth.py`, `cloud_api.py`, `api.py`) no dependen de Home Assistant y se prueban contra servidores simulados. El protocolo está documentado en `docs/` (en español).
