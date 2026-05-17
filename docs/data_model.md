# data_model.md

## Dokumenta mērķis

Šis dokuments apraksta SMT Digital Solution sensoru-centrēto datu modeli pēc
"sensor-metric ownership" korekcijas. Tas papildina `architecture_context.md` ar
precīzu modeļu un to atbildību sadalījumu, un kalpo kā vienota patiesības avots,
veidojot turpmākus aktīvu reģistrācijas UI un API formus.

## Pamatprincips

`Device` ir komunikācijas un agregēšanas vienība. Mērījumus rada **sensori**,
nevis pati ierīce. Tāpēc katra metrika, ko ierīce publicē, loģiski pieder
konkrētam sensoram, un sensora mērījumu spēja tiek deklarēta caur
`SensorMetric` rindām.

## Pamatentītes

- **Site** — fiziska vai loģiska lokācija (depo, saimniecība, demo stends).
- **Asset** — digitālā dvīņa objekts (lādētājs, panelis, baterija, sensoru
  mezgls u. tml.). Pieder `Site`.
- **Device** — fiziska vai simulēta IoT ierīce. Konteiners / komunikācijas
  vienība. Var piederēt `Asset`.
- **Sensor** — konkrēts mērījumu avots `Device` ietvaros. Šeit notiek
  loģiskā saikne ar metriku.
- **MetricDefinition** (`iot_config`) — globāls metrikas katalogs
  (`temperature_c`, `voltage_v`, `power_w`, `battery_soc_pct`, ...).
- **SensorMetric** (`assets`) — caur-modelis, kas savieno `Sensor` ar
  `MetricDefinition`. **Šī ir vienīgā autoritatīvā sensora mērījumu spēju
  karte.**
- **Measurement** (`telemetry`) — viens normalizēts mērījums; satur `sensor`
  un `metric` ārējās atslēgas.
- **ThresholdRule** (`analytics`) — sliekšņu noteikums; var būt globāls
  vai aprobežots ar `site`, `asset`, `device` un/vai `sensor`.
- **SimulatorMetricProfile** (`simulator`) — viena sensoram piesaistīta
  metrika konkrētā scenārija ierīcei; nosaka, kā simulators ģenerē šo
  vērtību.

## `SensorMetric`

Definēts `apps.assets.models.SensorMetric`. Atrašanās vieta `assets` aplikācijā
ir tāpēc, ka tas pieder `Sensor` dzīvescikla teritorijai (kas, savukārt,
nav `iot_config` template-level konfigurācija).

Lauki:

- `sensor` (FK → `assets.Sensor`, `CASCADE`, `related_name="sensor_metrics"`)
- `metric` (FK → `iot_config.MetricDefinition`, `PROTECT`,
  `related_name="sensor_metrics"`)
- `is_required` (`BooleanField`, noklusēti `False`) — vai metrika ir obligāta
  šim sensoram.
- `sort_order` (`IntegerField`, noklusēti `0`) — secība UI un noklusētajai
  kārtošanai.
- `is_active`, `metadata`, `created_at`, `updated_at` — manto no `BaseModel`.

Ierobežojumi:

- `UniqueConstraint(sensor, metric)` — viens metrikas ieraksts uz sensoru.

`Sensor.metrics` ir ērtības `ManyToManyField` caur `SensorMetric`:

```python
metrics = models.ManyToManyField(
    "iot_config.MetricDefinition",
    through="SensorMetric",
    related_name="sensors",
    blank=True,
)
```

`Sensor.sensor_metrics` ir tiešais reverse manager (lai administrators var
norādīt `is_required` un `sort_order`).

## `SimulatorMetricProfile`

Definēts `apps.simulator.models.SimulatorMetricProfile`.

Sensoru-centrētie pielāgojumi:

- Pievienots `sensor` lauks (FK → `assets.Sensor`, `CASCADE`,
  `related_name="simulator_metric_profiles"`). Datubāzē tas paliek
  `null=True` lai nesabojātu vēsturiskus datus; lietojumprogrammas
  loģika (`payload_generator.generate_payload`) atsakās ģenerēt
  payload, ja sensors trūkst.
- Uniqueness ir pārcelta uz `(scenario_device, sensor, metric)`. Tas
  ļauj diviem sensoriem viena `scenario_device` ietvaros teorētiski
  ražot vienu un to pašu metriku, bet payload ģenerēšana noraida
  tādus konfliktus (skat. zemāk).
- `clean()` validē, ka sensors pieder `scenario_device.device` un
  ka pastāv `SensorMetric` rinda metrikai.

### Payload ģenerēšana

`apps.simulator.services.payload_generator.generate_payload` tagad:

1. Izlasa `SimulatorMetricProfile.objects.filter(is_enabled=True)`, ieskaitot
   `sensor` un `metric` `select_related`.
2. Katrai aktīvai rindai pārbauda:
   * `sensor` nav `None` — citādi `SimulatorMetricProfileConfigError`;
   * `sensor.device == scenario_device.device` — citādi konfigurācijas
     kļūda;
   * šī rinda neražo duplikātu metrikas atslēgu citā sensorā uz tā
     paša `scenario_device`. Flat MQTT payload struktūra neļauj
     pārstāvēt vienu metriku no diviem sensoriem, tāpēc šis ir
     `SimulatorMetricProfileConfigError`.
3. Pārējais ģenerēšanas process (noise, modi, clamping) paliek nemainīgs.

## Ingestion — `Measurement.sensor` izšķirtspēja

`apps.mqtt_ingestion.services.ingestion_service` ievieš jaunu palīgu
`resolve_sensor_for_metric(device, metric)`, kas atgriež
`(sensor_or_None, warning)`:

1. Meklē aktīvas `SensorMetric` rindas, kur `sensor.device == device`,
   `sensor.is_active` un `SensorMetric.is_active`. Ja **tieši viena** atbilst,
   to izmanto.
2. Ja nav neviena `SensorMetric` ieraksta, bet ierīcei ir tieši viens
   aktīvs sensors, tas tiek izmantots kā atpakaļsavietojamība, un tiek
   reģistrēts brīdinājuma `Event` (`event_type=VALIDATION_ERROR`,
   `severity=WARNING`).
3. Ja vairāki `SensorMetric` atbilst, tiek izvēlēta pirmā deterministiski
   (pēc `sort_order, created_at, id`), un tiek reģistrēts brīdinājuma
   `Event` ar tekstu `Ambiguous sensor mapping...`.
4. Ja nav `SensorMetric` un ierīcei ir nulle vai vairāki aktīvi sensori,
   `Measurement` tiek saglabāts ar `sensor=None`, un tiek reģistrēts
   `Cannot resolve sensor` brīdinājums. Telemetrijas dati netiek zaudēti.
5. Sensors no citas ierīces **nekad** netiek piešķirts.

## `ThresholdRule` — eksplicītais `scope_level` (Phase 7 bugfix)

`apps.analytics.models.ThresholdRule`:

- Pievienots `sensor` (FK → `assets.Sensor`, `null=True, blank=True,
  SET_NULL`).
- Pievienots `scope_level` (`CharField`, choices `global | site | asset |
  device | sensor`, default `sensor`, `db_index=True`).
- Indekss `(sensor, metric)` un `(scope_level, metric)`.
- `clean()` veic validāciju katrai izvēlei (skat. `docs/analytics_usage.md`,
  sadaļa *“Eksplicītā `scope_level` semantika”*) un auto-aizpilda augstāka
  līmeņa FK no zemāka līmeņa FK, lai nodrošinātu rindas iekšējo konsistenci.

Iepriekšējais ieviesums ar `NULL` lauku kā wildcard tika **noņemts** kā
domēna kļūda — viens noteikums, kas paredzēts vienam sensoram, nedrīkst
klusi aktivizēties uz nesaistīta sensora mērījumu (piem., ārtelpu
temperatūras `-40..40 °C` slieksnis nedrīkst spēlēt uz motora sensora
`+80 °C` rādījumu).

`apps.analytics.services.thresholds._applicable_rules` izmanto eksplicīto
`scope_level`:

| `scope_level` | Atrod noteikumu, ja… |
| --- | --- |
| `global` | `measurement.metric == rule.metric` |
| `site` | `measurement.site == rule.site` |
| `asset` | `measurement.asset == rule.asset` |
| `device` | `measurement.device == rule.device` |
| `sensor` | `measurement.sensor == rule.sensor` |

Notikumu dedup-am un slēgšanai analītikas serviss izmanto papildu
`_scope_filter` palīgu, kas nodrošina, ka normāla vērtība no cita sensora
neslēdz cita sensora atvērtu notikumu (skat. `apps/analytics/services/thresholds.py`).

### Datu migrācija

`analytics/0004_thresholdrule_scope_level_and_more` pievieno
`scope_level` kolonnu ar `default='sensor'`, un
`analytics/0005_backfill_threshold_rule_scope_level` aizpilda esošos
ierakstus pēc šādas inference loģikas:

```
sensor_id  set → scope_level = 'sensor'
device_id  set → scope_level = 'device'
asset_id   set → scope_level = 'asset'
site_id    set → scope_level = 'site'
visi NULL      → scope_level = 'global'
```

Esošās rindas netiek dzēstas — tikai precizēta to nozīme. Globāli noteikumi
ir izlasāmi `python manage.py shell` ar `docs/analytics_usage.md` snippetiem.

### Seed un Stage 4 workflow

`seed_demo_data` tagad veido **sensor-scope** demonstrācijas noteikumus
(`temperature_c_high_warning`, `temperature_c_high_error`,
`battery_soc_low_warning`), kas piesaistīti `default_demo` charger-001
`main` sensoram. Globāli demo noteikumi netiek veidoti.

Operatora UI Stage 4 (`/dashboard/assets/{code}/devices/{uid}/sensors/{code}/metrics/new/`)
gan manuāli, gan no `ThresholdRulePreset` materiālizētie noteikumi tagad
**vienmēr** ir sensor-scope ar `sensor`, `device`, `asset`, `site`
korekti aizpildītiem. Globālu/asseta/ierīces tvēruma noteikumus var izveidot
tikai caur Django administrāciju vai shell.

## `DeviceProfileMetric`

`iot_config.DeviceProfileMetric` paliek koda bāzē, bet **vairs nav** dzīvā
spēju saskaņojuma avots. Tas tagad kalpo tikai kā template-/profil-līmeņa
katalogs. Visas izpildlaika lēmumi par sensoriem un metrikām notiek caur
`SensorMetric`.

Tam komentāri kodā un dokumentācijā tagad atspoguļo šo lomu. Nākotnē šo
modeli var izņemt atsevišķā cleanup posmā, ja izmantošanas vietas tiek
pārceltas.

## API

Lasāmais API (`apps.api`):

- `SensorSerializer` ietver iekļauto `sensor_metrics` sarakstu ar
  `metric_key`, `metric_unit`, `metric_data_type`, `is_required`,
  `sort_order`.
- Jauns `GET /api/sensor-metrics/` galapunkts atgriež saplacinātu
  `SensorMetric` skatu. Filtri: `sensor`, `device`, `metric` (kods vai
  UUID).
- `ThresholdRuleSerializer` izsauc `sensor` un `sensor_code` laukus.

## Migrāciju stratēģija

Trīs migrācijas pievieno strukturālās izmaiņas:

- `assets/0002_sensormetric_sensor_metrics_and_more` — pievieno
  `SensorMetric` modeli, indeksu, unique constraint un `Sensor.metrics`
  M2M.
- `simulator/0002_simulatormetricprofile_sensor` — atjauno unique
  constraint, pievieno `sensor` (`null=True`), data-migrē esošās
  rindas, piešķirot pirmo aktīvo sensoru ierīcei
  (`order_by("created_at", "id")`).
- `analytics/0002_thresholdrule_sensor_and_more` — pievieno
  `sensor` un `(sensor, metric)` indeksu.

## Seed demo data izmaiņas

`apps.core.management.commands.seed_demo_data`:

1. Izveido `SensorMetric` rindas demo sensoram visām 5 demo metrikām
   (`voltage_v`, `current_a`, `power_w`, `temperature_c`,
   `battery_soc_pct`).
2. Pārvieto eksistējošas `SimulatorMetricProfile` rindas uz demo
   sensoru (idempotenti).
3. Pievieno demonstrācijas sensoram-apjomotu `ThresholdRule`.

Komanda joprojām ir idempotenta — atkārtotie izpildi tikai atjauno
`updated_at` zīmogus.

## Operatora staged konfigurācijas plūsma (Phase 7, Task 3B)

Sākot ar Phase 7, Task 3B, operatora UI vairs nav vienlapas mega-forma.
`apps/dashboard/views.py` un `apps/dashboard/forms.py` to aizvieto ar
**staged workflow**, kur katrs solis ir atsevišķa lapa, atsevišķa
forma un atsevišķa atomāra transakcija. Pilnu UX aprakstu skat.
`docs/dashboard_usage.md`. Šeit ir tikai datu modeļa kontrakts:

### Sistēmas ģenerētie identifikatori

`Asset.code`, `Device.device_uid`, `Sensor.code` un `ThresholdRule.code`
**operatora UI vairs netiek ievadīti manuāli**. Tos ģenerē
`apps/assets/services/identifiers.py` ar formātu `<prefix>-NNNNNN`
(piem., `asset-000001`, `device-000001`, `sensor-000001`, `rule-000001`).
Tehniski lauki modelī paliek `unique=True` `CharField`, lai esošie
ieraksti (`charger-001` no seed datiem) un manuāli ievadītie kodi caur
Django administrāciju turpina darboties. Galvenā atslēga joprojām ir
`BaseModel.id` (UUID).

### Soļu invariantes

1. **1. solis (Asset)** — izveido tikai `Site` (opt.) + `Asset`. Site
   `timezone` ir ierobežots ar `TIMEZONE_CHOICES`.
2. **2. solis (Device)** — vai nu izveido jaunu `Device` ar ģenerētu
   `device_uid` un piesaista `asset.site` + `asset`, vai piesaista esošu
   nepiesaistītu ierīci no tā paša `Site`.
3. **3. solis (Sensor)** — izveido vienu `Sensor` ar ģenerētu `code`,
   piesaistītu `Device`. Var izmantot `SensorMetricPreset`, lai
   automātiski iestatītu sensora nosaukumu/tipu.
4. **4. solis (SensorMetric + ThresholdRule)** — izveido `SensorMetric`
   rindu (autoritatīvo saiti starp sensoru un metriku) ar trim metrikas
   režīmiem (preset / existing / new) un pēc izvēles `ThresholdRule` ar
   trim režīmiem (none / preset / manual). Sliekšņa noteikums
   automātiski tiek piesaistīts visiem trim tvērumiem
   (`site/asset/device/sensor/metric`).

### Per-stage transakcijas

Atšķirībā no Task 3 viena `transaction.atomic()` bloka, **katram solim
ir sava atomārā transakcija**. Tas nozīmē, ka 4. soļa kļūda neatritinā
1.–3. soļā izveidotos ierakstus — operators var labot tikai problemātisko
soli. Tas atspoguļo realitāti, kurā fizisks aktīvs/ierīce var pastāvēt
arī bez sliekšņa noteikumiem.

## `SensorMetricPreset` un `ThresholdRulePreset`

Lai operators nepārrakstītu tos pašus sensora/sliekšņa nosacījumus
katram aktīvam atsevišķi, prototipā ir divi presetu modeļi:

- **`apps.iot_config.models.SensorMetricPreset`** — definē sensora tipa
  + `MetricDefinition` kombināciju (piem., temperatūras sensors →
  `temperature_c`). Tiek izmantots tikai operatora UI; ingestion un
  analytics to nepieskaras.
- **`apps.analytics.models.ThresholdRulePreset`** — definē sliekšņa
  veidni ar `metric`, `lower_bound`/`upper_bound` (vismaz viens),
  `severity` un `close_when_normal`. 4. solis to materializē kā
  konkrētu `ThresholdRule` ierakstu ar pilnu `site/asset/device/sensor/metric`
  tvērumu. **Preset nav noteikums** — to var izmantot vairākiem
  konkrētiem `ThresholdRule` ierakstiem.

Abi modeļi izmanto `BaseModel`, ir reģistrēti Django admin un ir
iekļauti `seed_demo_data` idempotentajā plūsmā.

## Saistītie pirmkoda faili

- `apps/assets/models.py` — `Sensor`, `SensorMetric`.
- `apps/assets/admin.py` — `SensorMetricInline`, `SensorMetricAdmin`.
- `apps/assets/services/identifiers.py` — sistēmas ģenerētie `code` /
  `device_uid` ar collision-loop retry.
- `apps/simulator/models.py` — `SimulatorMetricProfile.sensor` + clean.
- `apps/simulator/services/payload_generator.py` — sensor validācija un
  duplikātu metriku noraidīšana.
- `apps/mqtt_ingestion/services/ingestion_service.py` —
  `resolve_sensor_for_metric`, `_create_sensor_warning_event`.
- `apps/analytics/models.py` — `ThresholdRule.sensor`,
  `ThresholdRulePreset`.
- `apps/analytics/services/thresholds.py` — papildinātais
  applicability filtrs.
- `apps/iot_config/models.py` — `SensorMetricPreset`.
- `apps/iot_config/admin.py`, `apps/analytics/admin.py` — presetu admin
  reģistrācija.
- `apps/api/serializers.py` — `SensorSerializer` ar
  `sensor_metrics`, `SensorMetricSerializer`.
- `apps/api/views.py` — `SensorMetricViewSet`.
- `apps/api/urls.py` — `/api/sensor-metrics/` route.
- `apps/dashboard/static/dashboard/dashboard.js` —
  `Sensors` kolonna mērījumu tabulā.
- `apps/dashboard/forms.py`, `apps/dashboard/views.py`,
  `apps/dashboard/urls.py` — staged workflow formas, skati un maršruti.
- `apps/core/management/commands/seed_demo_data.py` — seed papildināts ar
  presetiem un demo `ThresholdRule` ierakstiem.
- `docs/data_model.md` — šis dokuments.
- `docs/dashboard_usage.md` — staged workflow UX apraksts.
