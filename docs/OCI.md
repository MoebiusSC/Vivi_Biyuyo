# Vivi Biyuyo en OCI

## Arquitectura y garantías

Una VM Ubuntu 24.04 ARM64/AMD64 ejecuta un servicio Python modular y Caddy opcional.
No se implementan firmas, wallets privadas ni ejecución real. `VIVI_MODE` acepta
solo `shadow` y `paper`; una petición de trading real impide iniciar el proceso.

```
FOMO WebSocket -> collector -> inbox SQLite persistente -> cola acotada
                                          |
                        intelligence -> strategies A/B/C/D
                                          |
                                 trading/paper + research
                                          |
                         snapshot/effects SQLite -> web/dashboard
                                              Caddy HTTPS + basic auth
```

- Collector confirma cada recepción en SQLite antes de ponerla en la cola.
  Al reiniciar se reproducen los elementos pendientes. La cola aplica backpressure;
  no garantiza recuperar eventos que FOMO nunca entregó durante una desconexión.
- Inbox procesado, eventId visto, efectos y snapshot se confirman en una transacción.
  SQLite WAL con `synchronous=FULL` es la fuente autoritativa. Conservar también
  los archivos WAL/SHM al copiar una base activa, o usar un backup consistente.
- JSONL y `state.json` son exportaciones auxiliares: una caída entre el commit y
  la exportación puede dejarlas incompletas. Para investigación usar SQLite o
  regenerarlas con `python -m vivi_biyuyo.export --output /tmp/export`.
- Un único escritor por volumen. No escalar réplicas sobre la misma base.
- La caché del guard dura 300 segundos. Los datos faltantes y la ausencia de
  developer/insider holdings bloquean D; no equivalen a evidencia de seguridad.
- Carteras paper independientes A/B/C/D: USD 10.000 iniciales, USD 100 por entrada,
  30 bps de comisión y 100 bps de slippage por lado. Máximo una posición por
  token/cadena/lane; cierre completo cuando vende el mismo userId que abrió.
  Son supuestos experimentales, no rendimientos ejecutables.
- `priceUsd` válido del evento o una observación de `/v2/users/{userId}/positions`
  con token y networkId coincidentes permite un fill. Sin precio no hay fill.
  Los marks de posiciones no son quotes de un DEX y pueden estar atrasados.
- El stream on-chain requiere su entitlement y no siempre incluye userId: los
  eventos sin identidad estable se archivan en el inbox pero no generan copia.
- `feed_age_ms` mide recepción local menos timestamp del proveedor: no mide
  inclusión en bloque; un valor negativo revela diferencias de reloj. Sincronizar NTP.

## VM y red

Para la fase inicial: `VM.Standard.A1.Flex`, 1 OCPU / 6 GB RAM y Ubuntu 24.04 ARM64.
La VM autorizada durante este trabajo es `instance-20261003-1104`, Ashburn,
IP `129.213.41.132`, usuario `ubuntu`. No crear recursos duplicados si sigue disponible.

Si es necesario crear otra VM desde la consola:

1. Elegir la región principal de la tenencia, la imagen Ubuntu ARM64 y una shape
   que la consola identifique como elegible según la cuota disponible.
2. Usar una VCN/subred con Internet Gateway y ruta `0.0.0.0/0`; guardar la clave SSH
   fuera del repo. Restringir TCP 22 al CIDR del administrador.
3. Iniciar con 50 GB de boot volume persistente, cifrado. Configurar backups;
   comprobar capacidad y precio antes de crear un volumen adicional.
4. Para HTTPS abrir TCP 80/443 en NSG/security list y firewall del SO.
   Nunca abrir 8080: Compose lo publica exclusivamente en loopback.
5. No confundir cuota gratis con disponibilidad de capacidad ni prometer coste cero.

Oracle publica los límites actualizados en
[Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
La consola puede mostrar límites distintos; revisar elegibilidad y consumo de la tenencia.

## Instalar y desplegar

Desde SSH en la VM; usar un commit revisado o el SHA publicado en el PR:

```bash
git clone https://github.com/MoebiusSC/Vivi_Biyuyo.git /tmp/vivi-source
cd /tmp/vivi-source
git checkout <SHA_REVISADO>
sudo bash deploy/oci/provision.sh
sudo cp -a . /opt/vivi-biyuyo/
cd /opt/vivi-biyuyo
sudo cp .env.example .env
sudo install -d -m 0700 secrets
# Crear secrets/fomo_api_key de forma privada; no usar la clave como argumento CLI.
# Editar .env: VIVI_MODE=shadow para observación o paper para simulación.
sudo bash deploy/oci/deploy.sh
```

El secreto es un archivo montado de solo lectura; Compose local no lo cifra por sí
solo. `deploy.sh` aplica dueño UID 10001 y modo 0400. No ejecutar `docker compose
config` sin `--quiet` para no volcar variables sensibles. No guardar claves de
signing: no se requieren. `.env`, `secrets/` y la base quedan excluidos de Git/build.

`vivi_data` persiste en `/var/lib/docker/volumes` sobre el disco de la VM.
`docker compose down` conserva el volumen; **`down -v` elimina los datos**.
Para persistencia más allá de la terminación de la VM, conservar el boot/block
volume y restaurar desde backup. Una VM nueva no hereda automáticamente el volumen.

Para un Block Volume separado, adjuntarlo paravirtualizado y seguir las instrucciones
OCI del dispositivo. Confirmar identidad y ausencia de datos antes de formatear;
montar por UUID y copiar con el servicio detenido. Puede usarse un override que
cambie el volume de vivi a `/mnt/vivi-data:/data` (dueño 10001). No hay script que
formatee automáticamente un dispositivo para evitar pérdida de datos.

## HTTPS y acceso

Primero comprobar por túnel: `ssh -L 8080:127.0.0.1:8080 ubuntu@IP` y abrir
`http://localhost:8080`. Para el endpoint público hace falta un dominio cuyo
registro A apunte a la VM; no agregar AAAA si IPv6 no está configurado.

Generar el hash sin exponer una contraseña en argumentos:

```bash
sudo docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

Editar `.env` con `VIVI_DOMAIN`, `VIVI_DASHBOARD_USER` y el hash bcrypt entre comillas
simples para preservar `$`. Caddy protege **todos** los endpoints, incluidos health
y state. La clave FOMO no se usa para autenticar el dashboard.

```bash
sudo docker compose --profile https up -d --wait
curl --user research https://TU_DOMINIO/health
curl --user research https://TU_DOMINIO/ready
curl --user research https://TU_DOMINIO/
```

Sin credenciales el proxy debe responder 401. Caddy obtiene/renueva certificados
y guarda certificados en `caddy_data`. Verificar desde fuera de la VM, con validación
TLS normal. No declarar el despliegue terminado si faltan estas comprobaciones.

## Operación, reinicio y recuperación

- `/health`: proceso/event loop vivo, 503 tras 30 s sin heartbeat.
- `/ready`: además requiere welcome y recepción reciente (<120 s); sin clave devuelve
  503 aunque liveness esté OK. Un stream silencioso puede quedar no-ready sin ser un crash.
- `restart: unless-stopped` recupera salidas y reinicios del host. Docker **no reinicia
  por sí solo** un contenedor unhealthy. El watchdog incluido hace salir el proceso
  si el loop deja de avanzar durante 90 s; un supervisor externo debe alertar sobre readiness.
- Logs a stdout, rotados por Docker (5 x 10 MB). No incluir URLs autenticadas,
  cabeceras, claves ni bodies de errores. Ledgers de investigación no se rotan
  automáticamente: monitorizar espacio y archivar SQLite/effects según retención.
- Verificar `docker compose ps`, `docker compose logs --tail=100 vivi`, `df -h`, NTP.
  Alertar si disco >80%, no-ready prolongado, créditos FOMO agotados o reconexiones.
- `sudo bash deploy/oci/backup.sh /ruta/backup-separado` detiene el escritor durante
  el backup y lo reinicia mediante trap. Copiar backups a almacenamiento independiente
  y cifrado; backups locales no protegen contra pérdida de la VM.
- Restaurar con vivi detenido, extraer `data/` al volumen destino, comprobar dueño
  10001, iniciar, verificar health/readiness y cotejar cash/posiciones/eventos.
- Actualizar fijando un nuevo SHA, conservar el anterior para rollback. No reemplazar
  secretos ni eliminar volúmenes al actualizar. Antes de cambios de esquema hacer backup.

## Pruebas y límites pendientes

`python -m pip install -e '.[dev]' && pytest -q` prueba guard, carteras, dedupe,
recuperación transaccional y HTTP. CI también valida Compose y construye la imagen.
Las pruebas con fixtures no verifican el contrato real de FOMO ni su suscripción.
El despliegue final exige Docker Linux/ARM64, clave FOMO, conexión viva, DNS y TLS.

Si aún falta la clave FOMO, `sudo bash deploy/oci/deploy.sh --allow-unconfigured`
permite preparar el contenedor con un archivo secreto vacío y exige que `/ready`
responda 503. Esto es staging, no un despliegue operativo terminado.

Referencia del proveedor: [FOMO API](https://fomoapi.io/docs). `/stats` aporta flow,
no precio; `/devs` vacío no prueba seguridad. Documentación revisada el 2026-10-03.
