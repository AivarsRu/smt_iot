# api_reference.md

## Dokumenta mērķis

Šis dokuments apraksta SMT digitālā risinājuma REST API pirmo versiju (Phase 6, Task 1). API ir paredzēts:

- nākotnes paneļa frontendam (operatoru uzraudzības skats);
- ārējiem izstrādātājiem un testētājiem manuālai diagnostikai;
- iekšējiem skriptiem un automatizētajiem testiem.

API darbojas ar Django REST Framework un ir reģistrēts zem `/api/`. Šajā fāzē tas ir **tikai lasīšanas (read-only)**: nav nekādu rakstīšanas galapunktu, izņemot `/api/health/` (kas ir tīrs `GET`). Simulatora pārvaldība, autentifikācijas pārveide un lomu kontrole netiek ieviesta šajā uzdevumā.

## Kāpēc tikai lasīšana

Mērķis ir nodrošināt stabilu monitoringa virsmu, neriskējot ar haotisku rakstīšanu pa REST līniju, kamēr kodola domēna modeļi turpina attīstīties. Visi datu mainījumi joprojām notiek caur Django administrāciju, MQTT ingestion plūsmu, simulatoru un management komandām.

## Galapunktu pārskats

Visi resursi atrodas zem `/api/`:

| Galapunkts                       | Apraksts                                       | Filtri (galvenie)                                                                |
| -------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------- |
| `GET /api/health/`               | dzīvīguma + DB pieejamības pārbaude            | —                                                                                |
| `GET /api/sites/`                | objekti (saimniecības/depo/stacijas)           | —                                                                                |
| `GET /api/assets/`               | aktīvi (lādētāji, paneļi, baterijas u. c.)     | `site`, `status`, `asset_type`                                                   |
| `GET /api/assets/{id}/state/`    | `AssetState` viens ieraksts šim aktīvam        | —                                                                                |
| `GET /api/assets/{id}/measurements/` | mērījumi šim aktīvam                       | tādi paši kā `/api/measurements/`                                                |
| `GET /api/assets/{id}/events/`   | notikumi šim aktīvam                           | tādi paši kā `/api/events/`                                                      |
| `GET /api/devices/`              | IoT ierīces                                    | `site`, `asset`, `status`, `is_simulated`                                        |
| `GET /api/sensors/`              | sensori, kas piesaistīti ierīcēm               | `device` (`device_uid` vai UUID)                                                 |
| `GET /api/sensor-metrics/`       | sensora–metrikas spēju karte (`SensorMetric`)  | `sensor`, `device`, `metric` (kodu vai UUID)                                     |
| `GET /api/metrics/`              | `MetricDefinition` katalogs                    | —                                                                                |
| `GET /api/asset-states/`         | aktīvu pēdējais zināmais stāvoklis             | `status`, `has_active_anomaly`, `site`                                           |
| `GET /api/measurements/`         | telemetrijas mērījumu vēsture                  | `asset`, `device`, `metric`, `from`, `to`, `limit`                               |
| `GET /api/events/`               | anomāliju un sistēmas notikumi                 | `status`, `event_type`, `severity`, `asset`, `device`, `from`, `to`, `limit`     |
| `GET /api/raw-messages/`         | neapstrādāti MQTT ziņojumi (diagnostikai)      | `device_uid`, `processing_status`, `source_type`, `from`, `to`, `limit`          |
| `GET /api/threshold-rules/`      | sliekšņu noteikumi (atklāj `scope_level`, `sensor_code`) | —                                                                       |
| `GET /api/simulator-scenarios/`  | simulatora scenāriji                           | —                                                                                |
| `GET /api/simulator-runs/`       | simulatora vēsturiskie palaidieni              | `scenario`, `status`, `from`, `to`, `limit`                                      |

Detaļas (`/api/<resource>/{id}/`) ir pieejamas visiem resursiem un atgriež viena ieraksta serializāciju.

## Vienotie principi

### Kārtošana (`ordering`)

- `sites` — pēc `code`;
- `assets` — pēc `site.code, code`;
- `devices` — pēc `site.code, device_uid`;
- `asset-states` — pēc `site.code, asset.code`;
- `measurements` — pēc `-timestamp` (jaunākie pirmie);
- `events` — pēc `-detected_at`;
- `raw-messages` — pēc `-received_at`;
- `simulator-runs` — pēc `-started_at`.

### Limits

Visi saraksta galapunkti atbalsta `?limit=N`:

- noklusētais limits, ja parametrs nav norādīts: **100**;
- maksimālais atļautais: **1000**.

Ja `limit` ir nederīgs (nav vesels skaitlis, mazāks par 1, lielāks par maksimumu), galapunkts atgriež `400 Bad Request` ar skaidru kļūdas paziņojumu. Detaļu (`retrieve`) galapunktos `limit` netiek piemērots.

### `id`-vai-`code` lookups

Filtros, kas pieņem aktīvu/objektu/ierīci/metriku/scenāriju (piem., `?asset=...`), vērtība var būt:

- UUID identifikators (`?asset=9ab5e9e3-1392-4045-bc89-c8b6c49590e7`);
- vai resursam atbilstošs cilvēklasāms kods/UID (`?asset=charger-001`).

Implementācija mēģina parsēt UUID; ja tas neizdodas, tiek izmantots koda lauks (piem., `Asset.code`, `Device.device_uid`, `MetricDefinition.key`, `SimulatorScenario.code`).

Tāda pati `id`-vai-`code` izšķirtspēja darbojas arī **ceļa segmentā** šādiem resursiem:

- `Site` — pēc `code` (piem., `/api/sites/default_demo/`);
- `Asset` — pēc `code` (piem., `/api/assets/charger-001/`, `/api/assets/charger-001/state/`);
- `Device` — pēc `device_uid` (piem., `/api/devices/charger-001/`).

Pārējie resursi (sensors, metrics, asset-states, measurements, events, raw-messages, threshold-rules, simulator-scenarios, simulator-runs) ceļā joprojām pieņem tikai UUID, jo tiem nav cilvēklasāma stabila koda vai tos primāri lieto pēc UUID.

### Datumi/laiki

`from` un `to` parametri pieņem ISO 8601 formātu. Bez laika joslas tiek pieņemts servera lokālais laiks (`make_aware`). Nederīgs datumu/laiku formāts atgriež `400 Bad Request`.

### Atļaujas

Šajā fāzē tiek izmantotas DRF noklusētās atļaujas. Lokāli + iekšēji tas ir pieejams visiem; testos un attīstībā netiek pieprasīta autentifikācija. Lomu un rakstīšanas atļauju kontrole tiks pievienota nākamajā fāzē, kad tiks ieviesti rakstīšanas un dashboard galapunkti.

### Kļūdu apstrāde

Nederīgi filtri (piem., nezināms `status`, `event_type`, `severity`, `processing_status`, `source_type`, neparsējams `from`/`to`, neparsējams `limit`) atgriež `HTTP 400` un JSON ar parametra nosaukumu kā atslēgu, piemēram:

```json
{ "limit": "must be <= 1000, got 99999" }
```

Klusa filtru ignorēšana **nav atļauta**.

## Mērījumu (`measurements`) galapunkts

### Filtri

| Parametrs | Piemērs                          | Apraksts                                           |
| --------- | -------------------------------- | -------------------------------------------------- |
| `asset`   | `charger-001` vai UUID           | filtrēt pēc aktīva                                 |
| `device`  | `charger-001` vai UUID           | filtrēt pēc ierīces (`device_uid` vai UUID)        |
| `sensor`  | `sensor-000001` vai UUID         | filtrēt pēc sensora (`code` vai UUID) — Phase 7    |
| `metric`  | `temperature_c` vai UUID         | filtrēt pēc metrikas atslēgas                      |
| `from`    | `2026-05-17T08:00:00+00:00`      | apakšējā robeža `timestamp` laukā (ieskaitot)      |
| `to`      | `2026-05-17T09:00:00+00:00`      | augšējā robeža `timestamp` laukā (ieskaitot)       |
| `limit`   | `1..1000`                        | rezultātu skaits (noklusētais 100)                 |

### Piemēri

```bash
curl "http://localhost:8000/api/measurements/?asset=charger-001&limit=5"

curl "http://localhost:8000/api/measurements/?metric=temperature_c&from=2026-05-17T08:00:00%2B00:00"

curl "http://localhost:8000/api/measurements/?device=charger-001&metric=voltage_v&limit=1"

# Phase 7, Task 4A: precīza sensor + metric timeline
curl "http://localhost:8000/api/measurements/?sensor=sensor-000001&metric=temperature_c&from=2026-05-17T08:00:00Z&to=2026-05-17T10:00:00Z&limit=1000"
```

### Atbildes piemērs (saīsināts)

```json
[
  {
    "id": "6984c965-8564-4861-8ff9-483ebbe5010b",
    "site_code": "default_demo",
    "asset_code": "charger-001",
    "device_uid": "charger-001",
    "sensor_code": "main",
    "metric_key": "battery_soc_pct",
    "metric_unit": "%",
    "timestamp": "2026-05-17T06:43:33Z",
    "value": 78.96,
    "unit": "%",
    "quality": "good",
    "is_anomalous": false
  }
]
```

`value` lauks izmanto `Measurement.value` rekvizītu, atgriežot pirmo no `value_float`, `value_int`, `value_bool`, `value_text` vērtībām, kas nav `null`/tukša.

## Notikumu (`events`) galapunkts

### Filtri

| Parametrs    | Piemērs                          | Apraksts                                                 |
| ------------ | -------------------------------- | -------------------------------------------------------- |
| `status`     | `open`, `closed`, `acknowledged`, `ignored` | notikuma stāvoklis                            |
| `event_type` | `threshold_anomaly`, `communication_timeout`, ... | notikuma tips                          |
| `severity`   | `info`, `warning`, `error`, `critical` | nopietnības līmenis                                |
| `asset`      | `charger-001` vai UUID           | filtrēt pēc aktīva                                       |
| `device`     | `charger-001` vai UUID           | filtrēt pēc ierīces                                      |
| `sensor`     | `sensor-000001` vai UUID         | filtrēt pēc sensora — Phase 7, Task 4A                   |
| `metric`     | `temperature_c` vai UUID         | filtrēt pēc metrikas — Phase 7, Task 4A                  |
| `from`       | `2026-05-17T08:00:00+00:00`      | apakšējā robeža `detected_at` laukā                      |
| `to`         | `2026-05-17T09:00:00+00:00`      | augšējā robeža `detected_at` laukā                       |
| `limit`      | `1..1000`                        | rezultātu skaits (noklusētais 100)                       |

Visi filtri ir AND kombinējami. Nederīgs `severity`, `status`, `event_type`,
`from`, `to` vai `limit` atgriež HTTP `400` ar lasāmu JSON ziņu, piem.,
`{"severity": "invalid value 'bogus'. Allowed: ['critical', 'error', 'info', 'warning']"}`.

### Piemēri

```bash
curl "http://localhost:8000/api/events/?status=open"

curl "http://localhost:8000/api/events/?event_type=threshold_anomaly&severity=warning&limit=20"

curl "http://localhost:8000/api/events/?asset=charger-001&from=2026-05-17T00:00:00%2B00:00"

# Phase 7, Task 4A: pin to one sensor + metric
curl "http://localhost:8000/api/events/?sensor=sensor-000001&metric=temperature_c&status=open"
```

### EventSerializer lauki

Notikumu galapunkti (`/api/events/`, `/api/events/{id}/` un
`/api/assets/{id}/events/`) atgriež šādus laukus:

```
id, event_type, severity, status,
site, site_code,
asset, asset_code,
device, device_uid,
sensor, sensor_code,
metric, metric_key,
measurement, raw_message,
title, description,
detected_at, acknowledged_at, closed_at,
source, payload,
created_at, updated_at
```

Phase 7, Task 4A dashboardam ir nepieciešami visi `*_code`/`*_uid` lauki
un `measurement`/`raw_message` FK ID — tie ir pieejami visos notikumu
saraksta ierakstos.

## Aktīva stāvokļa (`asset state`) ielase

Lai iegūtu vienu konkrētu `AssetState`, ceļā var izmantot vai nu UUID, vai aktīva kodu:

```bash
curl "http://127.0.0.1:8000/api/assets/charger-001/state/"
curl "http://127.0.0.1:8000/api/assets/9ab5e9e3-1392-4045-bc89-c8b6c49590e7/state/"
```

Sarakstam pa visiem aktīviem:

```bash
curl "http://127.0.0.1:8000/api/asset-states/?has_active_anomaly=true"
```

## Neapstrādāto ziņojumu (`raw-messages`) diagnostika

Šis galapunkts ir paredzēts atkļūdošanai un diagnostikai. Tas atgriež neapstrādātos MQTT ziņojumus tā, kā tie nokļuva sistēmā.

```bash
curl "http://localhost:8000/api/raw-messages/?device_uid=charger-001&processing_status=parsed&limit=10"

curl "http://localhost:8000/api/raw-messages/?processing_status=failed&limit=5"
```

## Simulatora vēsture

```bash
curl "http://localhost:8000/api/simulator-scenarios/"

curl "http://localhost:8000/api/simulator-runs/?scenario=default_demo&status=completed"
```

> **Piezīme:** šajā fāzē **netiek** ieviestas simulatora `start` / `stop` API darbības. Simulatora palaišana joprojām notiek caur `python manage.py run_simulator ...`. Tas tiek darīts apzināti, lai REST līnija paliek stabila un tikai-lasīšanas.

## Veselības pārbaude

```bash
curl http://localhost:8000/api/health/
```

```json
{
  "status": "ok",
  "service": "smt-digital-solution",
  "database": "ok"
}
```

Galapunkts izpilda `SELECT 1;` pret datubāzi. Ja DB nav pieejama, tas atgriež `503` un `database` laukā ir kļūdas paziņojums. Konfidenciāli iestatījumi (paroles, vides mainīgie) **netiek** atklāti.

## Manuāla verifikācija

### 1. Sagatavot demo datus

```bash
docker compose -f docker-compose.local.yml exec web python manage.py seed_demo_data
```

### 2. Pārliecināties, ka ir vismaz viens telemetrijas mērījums

Termināls 1:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_mqtt_worker --once --timeout-seconds 120 --verbosity 2
```

Termināls 2:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --once --verbosity 2
```

### 3. Pārbaudīt API no `web` konteinera

`Client` izmanto `testserver` kā Host, kas neatrodas `ALLOWED_HOSTS`, tāpēc nepieciešams `SERVER_NAME='localhost'`:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='localhost')
print(c.get('/api/health/').json())
print(c.get('/api/assets/').status_code)
print(c.get('/api/measurements/?asset=charger-001&limit=5').json())
"
```

### 4. Pārbaude no resursdatora ar `curl`

Ja `web` konteiners ir pieejams uz `http://localhost:8000`:

```bash
curl http://localhost:8000/api/health/
curl "http://localhost:8000/api/assets/"
curl "http://localhost:8000/api/measurements/?asset=charger-001&limit=5"
curl "http://localhost:8000/api/events/?status=open"
```

## Dashboard kopsavilkuma galapunkti (Phase 6, Task 2)

Lai nākotnes dashboard frontendam nebūtu jāveic vairāki atsevišķi pieprasījumi un klienta pusē jāveido kopsavilkumu agregācija, API piedāvā piecus dashboard-orientētus kopsavilkuma galapunktus un viena aktīva detalizēto kopsavilkumu. Tie:

- ir **tikai lasīšanai** (POST/PUT/etc. atgriež `405`);
- vienmēr atgriež `generated_at` lauku ar `timezone.now()`, lai dashboard varētu parādīt datu svaigumu;
- atbalsta tādus pašus filtrus kā Phase 6, Task 1 saraksta galapunkti, izmantojot `apps/api/filters.py` palīgfunkcijas;
- piemēro drošus noklusētos un maksimālos limitus visiem "recent" sarakstiem;
- **neaizvieto** detalizētos saraksta galapunktus (`/api/measurements/`, `/api/events/` u. tml.) — tie joprojām ir labākais izvēles variants vēsturisko datu pārlūkošanai.

### Galapunktu kopsavilkums

| Galapunkts                                  | Mērķis                                                                                          |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `GET /api/overview/`                        | sistēmas līmeņa kopsavilkums (aktīvi, ierīces, telemetrija, notikumi, simulators)               |
| `GET /api/overview/assets/`                 | aktīvu skaitļi pēc statusa, pa tipiem un detalizēts saraksts ar `AssetState` snapshot           |
| `GET /api/overview/events/`                 | notikumu skaitļi pēc statusa/severity un nesenais notikumu saraksts                             |
| `GET /api/overview/telemetry/`              | RawMessage statistika, mērījumu apkopojums pa metrikām un nesenais mērījumu saraksts             |
| `GET /api/overview/simulator/`              | simulatora scenāriju un palaidienu kopsavilkums                                                 |
| `GET /api/assets/{id-or-code}/summary/`     | viena aktīva pilns dashboard skats (state, atvērtie notikumi, jaunākie mērījumi pa metrikām)    |

`/api/assets/{id-or-code}/summary/` ceļa segmentā — tāpat kā citos `Asset` detail galapunktos — pieņem gan UUID, gan kodu (`charger-001`), izmantojot `IdOrCodeLookupMixin`.

### Limiti

| Galapunkts                                  | Lauks         | Noklusētais | Maksimums |
| ------------------------------------------- | ------------- | ----------- | --------- |
| `GET /api/overview/assets/`                 | `limit`       | 100         | 1000      |
| `GET /api/overview/events/`                 | `limit`       | 20          | 200       |
| `GET /api/overview/telemetry/`              | `limit`       | 20          | 200       |
| `GET /api/overview/simulator/`              | `limit`       | 20          | 200       |
| `GET /api/assets/.../summary/`              | `metrics_limit` | 20        | 100       |
| `GET /api/assets/.../summary/`              | `events_limit`  | 20        | 100       |

Nederīgs limits (ne vesels skaitlis, < 1 vai > maksimuma) atgriež `400`.

### `/api/overview/`

Sistēmas līmeņa kopsavilkums. Bez parametriem.

```bash
curl http://127.0.0.1:8000/api/overview/
```

Atbildes paraugs (saīsināts):

```json
{
  "status": "ok",
  "generated_at": "2026-05-17T07:32:11.123456Z",
  "assets":     {"total": 1, "active": 1, "offline": 0, "warning": 0, "error": 0, "with_active_anomaly": 0},
  "devices":    {"total": 1, "simulated": 1, "active": 1, "offline": 0, "never_seen": 0},
  "telemetry":  {"raw_messages_total": 10, "measurements_total": 50,
                 "latest_measurement_at": "...", "latest_raw_message_at": "..."},
  "events":     {"open_total": 1, "open_threshold_anomaly": 1, "open_communication_timeout": 0,
                 "warning_open": 1, "error_open": 0, "critical_open": 0},
  "simulator":  {"scenarios_total": 1, "active_scenarios": 1,
                 "last_run_status": "completed", "last_run_at": "...",
                 "last_messages_published": 1}
}
```

### `/api/overview/assets/`

Filtri:

| Parametrs              | Apraksts                                                              |
| ---------------------- | --------------------------------------------------------------------- |
| `site`                 | `id`-vai-`code`                                                       |
| `asset_type`           | `charger`, `battery`, `sensor_node`, `infrastructure_node`, `other`   |
| `status`               | `OperationalStatus.values` izvēle                                     |
| `has_active_anomaly`   | `true` / `false`                                                      |
| `limit`                | `1..1000` (noklusētais 100)                                           |

Filtri attiecas uz **visiem** atbildes blokiem (`counts`, `by_type`, `items`), tāpēc dashboard skaitļi un saraksts vienmēr ir konsistenti ar lietotāja izvēli.

```bash
curl "http://127.0.0.1:8000/api/overview/assets/"
curl "http://127.0.0.1:8000/api/overview/assets/?status=active&limit=20"
curl "http://127.0.0.1:8000/api/overview/assets/?has_active_anomaly=true"
```

### `/api/overview/events/`

Filtri:

| Parametrs     | Apraksts                                                              |
| ------------- | --------------------------------------------------------------------- |
| `status`      | `EventStatus.values` izvēle                                           |
| `event_type`  | `EventType.values` izvēle                                             |
| `severity`    | `Severity.values` izvēle                                              |
| `asset`       | `id`-vai-`code`                                                       |
| `device`      | `id`-vai-`device_uid`                                                 |
| `from`        | ISO 8601 datums/laiks                                                 |
| `to`          | ISO 8601 datums/laiks                                                 |
| `limit`       | `1..200` (noklusētais 20)                                             |

**Tvēruma filtri** (`asset`, `device`, `from`, `to`) attiecas uz `counts`, `by_type` **un** `recent`. **Izvēles filtri** (`status`, `event_type`, `severity`) attiecas tikai uz `recent` — tas ļauj dashboard pieprasīt, piem., `status=open` recent sarakstam, taču `counts.closed_total` joprojām atspoguļo visu tvēruma kopumu. Tas ir dashboardam vēlamākais režīms.

```bash
curl "http://127.0.0.1:8000/api/overview/events/?status=open&limit=10"
curl "http://127.0.0.1:8000/api/overview/events/?asset=charger-001&from=2026-05-17T00:00:00%2B00:00"
curl "http://127.0.0.1:8000/api/overview/events/?event_type=threshold_anomaly"
```

### `/api/overview/telemetry/`

Filtri (visi attiecas uz `raw_messages`, `measurements` un `recent_measurements`):

| Parametrs | Apraksts                              |
| --------- | ------------------------------------- |
| `asset`   | `id`-vai-`code`                       |
| `device`  | `id`-vai-`device_uid`                 |
| `metric`  | `id`-vai-`key` (piem., `temperature_c`)|
| `from`    | ISO 8601 datums/laiks                 |
| `to`      | ISO 8601 datums/laiks                 |
| `limit`   | `1..200` (noklusētais 20)             |

`measurements.metrics[]` saturs ir _per-metric latest snapshot_: katrai metrikai, kurai tvērumā ir mērījumi, tiek atgriezts `latest_value`, `latest_timestamp` un `count`. Implementācijai nav vajadzīgs PostgreSQL `DISTINCT ON` — tā strādā uz jebkura datubāzes backenda.

```bash
curl "http://127.0.0.1:8000/api/overview/telemetry/?asset=charger-001&limit=10"
curl "http://127.0.0.1:8000/api/overview/telemetry/?metric=temperature_c"
```

### `/api/overview/simulator/`

Filtri attiecas uz `runs` un `recent_runs`. Scenāriju kopsavilkums ir vienmēr globāls.

| Parametrs | Apraksts                                              |
| --------- | ----------------------------------------------------- |
| `scenario`| `id`-vai-`code` (piem., `default_demo`)               |
| `status`  | `SimulatorRun.RUN_STATUS_CHOICES` izvēle              |
| `from`    | ISO 8601 datums/laiks (`started_at`)                  |
| `to`      | ISO 8601 datums/laiks (`started_at`)                  |
| `limit`   | `1..200` (noklusētais 20)                             |

```bash
curl "http://127.0.0.1:8000/api/overview/simulator/?scenario=default_demo"
curl "http://127.0.0.1:8000/api/overview/simulator/?status=failed"
```

> **Piezīme:** simulatora `start` / `stop` API darbības **netiek** ieviestas šajā fāzē. Simulatora palaišana joprojām notiek caur `python manage.py run_simulator ...`.

### `/api/assets/{id-or-code}/summary/`

Atgriež viena aktīva pilnu dashboard skatu vienā pieprasījumā:

- `asset` — pamata identifikācija (kods, nosaukums, tips, `site_code`, `status`);
- `state` — visi `AssetState` lauki (vai `null`, ja `AssetState` vēl nav izveidots);
- `open_events` — līdz `events_limit` atvērtajiem notikumiem (jaunākie pirmie);
- `latest_measurements` — jaunākais mērījums katrai metrikai, ko šis aktīvs ir reģistrējis (līdz `metrics_limit`);
- `latest_raw_message` — jaunākais `RawMessage` šim aktīvam diagnostikai.

```bash
curl http://127.0.0.1:8000/api/assets/charger-001/summary/
curl "http://127.0.0.1:8000/api/assets/charger-001/summary/?metrics_limit=5&events_limit=10"
curl "http://127.0.0.1:8000/api/assets/9ab5e9e3-1392-4045-bc89-c8b6c49590e7/summary/"
```

Nezināms aktīva kods vai UUID atgriež `404`.

### Manuāla verifikācija — dashboard galapunkti

```bash
docker compose -f docker-compose.local.yml exec web python manage.py seed_demo_data

docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='localhost')
for path in [
    '/api/overview/',
    '/api/overview/assets/',
    '/api/overview/events/',
    '/api/overview/telemetry/',
    '/api/overview/simulator/',
    '/api/assets/charger-001/summary/',
]:
    r = c.get(path)
    print(path, r.status_code)
"
```

Ja `web` ir pieejams uz resursdatora `8000` portā:

```bash
curl http://localhost:8000/api/overview/
curl http://localhost:8000/api/overview/assets/
curl "http://localhost:8000/api/overview/events/?status=open&limit=10"
curl "http://localhost:8000/api/overview/telemetry/?asset=charger-001&limit=10"
curl http://localhost:8000/api/assets/charger-001/summary/
```

## Saistītie pirmkoda faili

- `apps/api/serializers.py` — visi DRF serializētāji;
- `apps/api/views.py` — `ReadOnlyModelViewSet` instances, `LimitedListMixin`, `IdOrCodeLookupMixin`, `health_view` un `Asset` ligzdotie galapunkti (`state`, `measurements`, `events`, `summary`);
- `apps/api/overview.py` — dashboard kopsavilkuma galapunkti un `build_asset_summary` palīgfunkcija;
- `apps/api/filters.py` — palīgfunkcijas (`parse_bool`, `parse_iso_datetime`, `parse_limit`, `filter_by_id_or_code`, `apply_datetime_range`, `validate_choice`);
- `apps/api/urls.py` — `DefaultRouter` reģistrācija, `health/` ceļš un `overview/...` ceļi;
- `apps/api/tests.py` — DRF `APITestCase` integrācijas testi (79 testi);
- `config/urls.py` — `/api/` integrācija galvenajā URL konfigurācijā.

## Salīdzinājums ar nākamajām fāzēm

| Tagad (Phase 6, Task 1)              | Nākamie posmi (nav iekļauti šajā uzdevumā)         |
| ------------------------------------ | --------------------------------------------------- |
| tikai-lasīšanas REST                 | rakstīšanas galapunkti, lomu atļaujas               |
| veselības pārbaude                   | simulatora `start`/`stop` API                       |
| sliekšņu un timeout notikumu nolasīšana | dashboard veidnes, WebSocket reāllaika ziņojumi  |
| `?limit` daļšana                     | DRF lapošana ar metadatu (`count`, `next`, `prev`)  |
| `seed_demo_data` testi               | autentifikācija pa lomām un API atslēgu pārvaldība  |
