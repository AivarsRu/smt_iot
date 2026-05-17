# analytics_usage.md

## Dokumenta mērķis

Šis dokuments apraksta SMT digitālā risinājuma analītikas slāni — sliekšņu (`threshold_anomaly`) anomāliju noteikšanu un komunikācijas pārtraukumu (`communication_timeout`) noteikšanu. Tas ir paredzēts izstrādātājiem un operatoriem, kas konfigurē noteikumus, palaiž periodisko pārbaudi un veic manuālo verifikāciju.

Analītika ir tīšām vienkāršota: nav mašīnmācīšanās, nav prognozēšanas, nav statistiskās modelēšanas. Visa loģika ir konfigurējama datubāzē vai ar nelielu skaitu vides mainīgo.

## Analītikas divi pīlāri

### 1. Sliekšņu anomālijas (`threshold_anomaly`)

Sliekšņu pārbaude tiek veikta **uzreiz pēc** tam, kad MQTT ingestion serviss ir saglabājis `Measurement` ierakstu. Konfigurācija atrodas `apps.analytics.ThresholdRule` modelī un to uztur Django administrācijā vai ar `seed_demo_data` komandu.

Katrs noteikums definē:

- `metric` — kura `iot_config.MetricDefinition` tiek uzraudzīta;
- `lower_bound`, `upper_bound` — viena vai abas robežas;
- `severity` — `warning`, `error` vai `critical`;
- **`scope_level`** — viens no `global`, `site`, `asset`, `device`, `sensor`. Skatīt sadaļu *“Eksplicītā `scope_level` semantika”* zemāk;
- attiecīgo `site`, `asset`, `device` vai `sensor` FK, atbilstoši `scope_level` izvēlei;
- `close_when_normal` — vai automātiski slēgt notikumu, kad vērtība atgriežas robežās.

Ja kāda mērījuma vērtība pārkāpj robežu, tiek izveidots vai atjaunināts atvērts `events.Event` ar `event_type="threshold_anomaly"`. Atkārtoti pārkāpumi atjaunina to pašu notikumu, bet **nemaina sākotnējo `detected_at`**, lai operators redzētu, cik ilgi anomālija ir aktīva.

### Eksplicītā `scope_level` semantika (Phase 7 bugfix)

Iepriekšējā ieviesumā `ThresholdRule` ar `NULL` `sensor` (vai `device`/`asset`/`site`) lauku tika uzskatīts par “wildcard”, kas atbilst jebkuram mērījumam ar to pašu metriku. **Tas bija bīstami reālā domēnā**:

- ārtelpu temperatūras sensors: `-40..+40 °C` ir normāls,
- motora temperatūras sensors: `0..+100 °C` ir normāls.

Ja viens noteikums tika izveidots ar `upper_bound=40 °C` un bez `sensor` FK, tas pārvērtās par neapzinātu globālu noteikumu un nepamatoti aktivizējās uz motora sensora `+80 °C` mērījumu.

No Phase 7 sākot, katram `ThresholdRule` ir obligāts `scope_level` ar precīzu semantiku:

| `scope_level` | Kad piemērojas mērījumam | Obligātais FK | Aizliegtie FK |
| --- | --- | --- | --- |
| `global` | jebkuram mērījumam ar to pašu `metric` | — | `site`, `asset`, `device`, `sensor` jābūt tukšiem |
| `site`   | `measurement.site == rule.site` | `site` | `asset`, `device`, `sensor` jābūt tukšiem |
| `asset`  | `measurement.asset == rule.asset` | `asset` | `device`, `sensor` jābūt tukšiem; `site`, ja iestatīts, jāatbilst `asset.site` |
| `device` | `measurement.device == rule.device` | `device` | `sensor` jābūt tukšam; `asset`/`site`, ja iestatīti, jāatbilst `device.asset`/`device.site` |
| `sensor` | `measurement.sensor == rule.sensor` | `sensor` | augstāka līmeņa FK (`device`/`asset`/`site`), ja iestatīti, jāatbilst sensora ķēdei |

Validācija notiek `ThresholdRule.clean()` (skat. `apps/analytics/models.py`). `clean()`:

1. Pārbauda, ka eksistē vismaz viena robeža un `lower_bound ≤ upper_bound`.
2. Auto-aizpilda augstāka līmeņa FK no zemāka līmeņa FK (piem., sensor-scope noteikumā aizpilda `device`, `asset`, `site` no `sensor`).
3. Atsakās saglabāt nekonsekventu rindu (piem., sensor-scope ar `device`, kas neatbilst `sensor.device`).
4. Sensor-scope noteikumiem pārbauda, vai eksistē `SensorMetric(sensor=…, metric=…, is_active=True)` — bez tā noteikums nekad neaktivizētos un to drošāk noraidīt jau formā.

### Piemēri

```python
# Sensor-scope: ārtelpu sensors
ThresholdRule.objects.create(
    code="outdoor_temp_range",
    name="Outdoor temperature normal range",
    metric=temperature_c,
    scope_level=ThresholdRuleScope.SENSOR,
    sensor=outdoor_sensor,        # device/asset/site auto-aizpildās
    lower_bound=-40.0, upper_bound=40.0,
    severity=Severity.WARNING,
)

# Sensor-scope: motora sensors uz tās pašas ierīces, tā paša metrika
ThresholdRule.objects.create(
    code="motor_temp_range",
    name="Motor temperature normal range",
    metric=temperature_c,
    scope_level=ThresholdRuleScope.SENSOR,
    sensor=motor_sensor,
    lower_bound=0.0, upper_bound=100.0,
)

# Global noteikums (rezervēt apzinātām situācijām!)
ThresholdRule.objects.create(
    code="global_temperature_critical",
    name="Any sensor: temperature above 150 °C",
    metric=temperature_c,
    scope_level=ThresholdRuleScope.GLOBAL,
    upper_bound=150.0,
    severity=Severity.CRITICAL,
)
```

### Notikumu izolēšana pēc tvēruma

Analītikas serviss `apps/analytics/services/thresholds.py` izmanto `scope_level`, lai:

1. **Atrast piemērojamos noteikumus** — `_applicable_rules(measurement)` veido savienoto querysetu no `ThresholdRule` ar precīzi tā tvēruma FK, ko atbilst mērījumam. Sensor-scope noteikums attiecas tikai uz savu sensoru — citu sensoru mērījumi to neredz.
2. **Atrast atvērtus notikumus dedup-am** un **slēgt atvērtus notikumus** — `_scope_filter(qs, rule, measurement)` papildina `payload__rule_code=…` atlasi ar tvēruma FK (sensor/device/asset/site), lai normāla vērtība no cita sensora neslēgtu cita sensora atvērtu notikumu. Globāliem noteikumiem notikumi tiek izolēti pēc stiprākā mērījuma līmeņa (sensor → device → asset → site), kas garantē, ka divi aktīvi ar globālu noteikumu neuztur viens otra notikumu.

### Notikuma `payload` lauki

`Event.payload` (`threshold_anomaly`) satur šādus diagnostikas laukus:

| Lauks | Apraksts |
| --- | --- |
| `rule_code` | `ThresholdRule.code` |
| `scope_level` | `global`/`site`/`asset`/`device`/`sensor` |
| `metric_key` | `MetricDefinition.key` |
| `sensor_code`, `sensor_id` | mērījuma sensora dati, ja pieejami |
| `device_uid` | mērījuma ierīces UID |
| `asset_code` | mērījuma aktīva kods |
| `site_code` | mērījuma site kods |
| `value` | konkrētā mērījuma vērtība |
| `lower_bound`, `upper_bound` | noteikuma robežas |
| `measurement_id` | mērījuma UUID stringā |

Operatora UI (`/dashboard/events/<id>/`) jau parāda visu šo informāciju tabulās un payload blokā.

### Notikumu automātiska aizvēršana, kad noteikums tiek deaktivēts

`ThresholdRule.is_enabled` ir pārslēdzams karogs: ja tas ir `False`, analītikas serviss noteikumu **neredz** (`_applicable_rules` filtrē pēc `is_enabled=True`). Tas nozīmē, ka pēc deaktivēšanas vairs neviens "atgriešanās normā" mērījums nevar sasniegt `_close_open_events` ceļu, un noteikuma atvērtie `threshold_anomaly` notikumi sēž dashboard-ā mūžīgi.

Lai novērstu šo trūkumu, `ThresholdRule.save()` reģistrē pāreju `is_enabled: True → False` un sinhroni aizver visus tā atvērtos notikumus, kas atbilst `payload.rule_code == self.code`:

- `event.status = closed`;
- `event.closed_at = timezone.now()`;
- `event.payload['closed_reason'] = 'rule_disabled'`;
- `event.payload['closed_at'] = ISO laiks`.

Detaļas un garantijas:

1. **Tikai pāreja, nevis stāvoklis.** Ja noteikums tiek izveidots ar `is_enabled=False` (vai saglabāts atkārtoti, paliekot izslēgtam), aizvēršanas loģika netiek izsaukta. Hooks reaģē tieši uz `True → False` maiņu, izmantojot `_state.adding` un instanču līmeņa `_prev_is_enabled` snapshotu, nevis papildu DB roundtrip.
2. **Izolēts pēc `rule_code`.** Tiek aizvērti tikai tie atvērtie notikumi, kas piederēja tieši šim noteikumam. Cita noteikuma atvērtie notikumi paliek neaiztikti, pat ja tie ir uz to pašu sensoru/metriku.
3. **Idempotents.** Jau aizvērti notikumi netiek modificēti — `closed_at` un `closed_reason` ir uzlikti tikai pirmajā pārejā.
4. **Atkārtota aktivizēšana neatver notikumus.** Iestatot `is_enabled=True` atpakaļ, aizvērtie notikumi paliek aizvērti. Nākamais pārkāpums izveido jaunu, svaigu notikumu.
5. **Pieejams arī kā primitīvs.** Metode `ThresholdRule._close_open_events_on_disable()` ir izmantojama tieši — piemēram, vienreizējai datu uzkopšanai (atgriež aizvērto notikumu skaitu).

Operatora skats: deaktivēšana ir pieejama vai nu no Django administrācijas (`/admin/analytics/thresholdrule/`), vai no dashboard rediģēšanas lapas `/dashboard/assets/<asset_code>/rules/<rule_code>/edit/` (skat. `docs/dashboard_usage.md`, sadaļa “Rediģēt esošu sliekšņa noteikumu”).

Pamatdetaļas un ievadprasības skatīt iepriekšējā darba uzdevuma dokumentā un pirmkodā:

- pakalpojums: `apps/analytics/services/thresholds.py`;
- modelis: `apps/analytics/models.py`;
- integrācija: `apps/mqtt_ingestion/services/ingestion_service.py`.

### 2. Komunikācijas pārtraukumi (`communication_timeout`)

Komunikācijas pārtraukuma noteikšana ir **periodiska**. Tā atbild uz jautājumu: vai ierīce vēl komunicē atbilstoši savam sagaidāmajam intervālam?

Šī pārbaude **netiek veikta** MQTT worker procesā un **netiek veikta** Django web procesā. Tā tiek palaista kā Django management komanda no cron, systemd timer vai `analytics_worker` Docker servisa.

Šajā pārbaudē tiek izmantoti tikai esoši dati:

- `assets.Device.last_seen_at` — to atjaunina ingestion serviss pēc katra veiksmīgā telemetrijas ziņojuma;
- `assets.Device.expected_interval_seconds` — sagaidāmais ziņojumu intervāls;
- `assets.Device.is_active` — neaktīvas ierīces tiek izlaistas;
- atkāpes scenārijā `digital_twin.AssetState.last_seen_at`, ja `Device.last_seen_at` vēl nav iestatīts.

## Iestatījumi

Abus iestatījumus var pārrakstīt ar vides mainīgajiem `.env` vai `.env.local`:

| Iestatījums | Noklusētā vērtība | Apraksts |
| --- | --- | --- |
| `COMMUNICATION_TIMEOUT_GRACE_MULTIPLIER` | `3.0` | Reizinātājs `expected_interval_seconds` vērtībai. Kavēšanās robeža = `expected_interval_seconds × multiplier`. |
| `COMMUNICATION_TIMEOUT_DEFAULT_SECONDS` | `300` | Drošā noklusētā robeža (sekundes), ko izmanto, ja `expected_interval_seconds` nav iestatīts vai ir `0`. |

`grace_multiplier` mērķis ir nepieļaut viltus trauksmes, ja viens ziņojums kavējas. Piemēram, ja `expected_interval_seconds = 60` un `grace_multiplier = 3.0`, ierīce tiek uzskatīta par “timed out” tikai pēc 180 sekunžu klusuma.

## Komunikācijas pārtraukuma loģika

Katram aktīvam, asseta saistītam `Device`:

1. Tiek aprēķināts `timeout_seconds = expected_interval_seconds × grace_multiplier`. Ja `expected_interval_seconds` ir `0`, tiek izmantota `COMMUNICATION_TIMEOUT_DEFAULT_SECONDS` vērtība.
2. Tiek nolasīts `last_seen_at` (vai `AssetState.last_seen_at`, ja primārais ir `None`).
3. Ja `now() - last_seen_at > timeout_seconds`, ierīce ir `timed_out`.
4. Ja `last_seen_at` nav nemaz, ierīce ir `never_seen` un tiek uzskatīta par timeout kandidātu.
5. Ja viss kārtībā, ierīces statuss ir `ok`.

Pārbaudes rezultāts:

- **timeout** — tiek izveidots vai atjaunināts atvērts `events.Event` ar `event_type="communication_timeout"`, `severity=warning`, `source="analytics"`. Esošā atvērtā notikuma `detected_at` netiek pārrakstīts. `payload` satur `device_uid`, `asset_code`, `last_seen_at`, `expected_interval_seconds`, `grace_multiplier`, `timeout_seconds`, `checked_at`. Saistītais `AssetState` tiek atzīmēts kā `offline`.
- **recovery** — atvērtais timeout notikums tiek aizvērts (`status=closed`, `closed_at=now()`), `payload` papildināts ar `recovered_at`. Ja `AssetState` patlaban ir `offline` un nav citu atvērtu notikumu šim assetam, tā statuss tiek atjaunots uz `active`. Citu anomāliju (piemēram, `threshold_anomaly`) izraisīts `error` vai `warning` statuss netiek pārrakstīts.

Atkārtoti palaidumi ir idempotenti — tie nedublē atvērtus notikumus, un atvērto notikumu skaits `AssetState.active_anomaly_count` tiek pārrēķināts no atvērto `events.Event` skaita asetam.

## Eligibility kritēriji

Ierīce tiek pārbaudīta tikai tad, ja:

- `Device.is_active = True`;
- `Device.site_id` nav `NULL`;
- `Device.asset_id` nav `NULL`.

Pārējās ierīces tiek atzīmētas kā `skipped` ar paskaidrojumu (`device_inactive`, `device_has_no_site`, `device_has_no_asset`).

## Komandas palaišana

### Sausā palaišana (dry-run)

Saraksts ar to, kas notiktu, bez izmaiņām datubāzē:

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --dry-run --verbosity 2
```

Sausā palaišana:

- nepalaiž MQTT savienojumus;
- neraksta vai neslēdz `Event` ierakstus;
- neatjaunina `AssetState`;
- izdrukā kopsavilkumu un, pie `--verbosity 2`, katras ierīces statusu (`ok`, `timed_out`, `never_seen`, `skipped`).

### Reālā palaišana

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts
```

Filtri:

```bash
# Tikai vienai vietai
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --site default_demo

# Tikai vienai ierīcei
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --device charger-001

# Detalizēts izvads
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --verbosity 2
```

Komandai nav interaktīvas saskarnes. Tā beidzas ar `exit code 0`, ja viss kārtībā, vai `CommandError`, ja `--site` vai `--device` neeksistē.

### Cron piemērs

```cron
*/2 * * * * /srv/smt/.venv/bin/python /srv/smt/manage.py check_communication_timeouts >> /var/log/smt/communication_timeouts.log 2>&1
```

Vai pa Docker Compose:

```cron
*/2 * * * * docker compose -f /srv/smt/docker-compose.local.yml exec -T web python manage.py check_communication_timeouts >> /var/log/smt/communication_timeouts.log 2>&1
```

Ja gribi novērst pārklāšanos starp ilgākiem palaidieniem, izmanto `flock`:

```cron
*/2 * * * * /usr/bin/flock -n /tmp/smt_timeout.lock docker compose -f /srv/smt/docker-compose.local.yml exec -T web python manage.py check_communication_timeouts
```

## Atveseļošanās ingestion ceļā (best-effort)

Papildus periodiskajai pārbaudei, MQTT ingestion serviss izsauc nelielu palīgfunkciju `apps.analytics.services.communication_timeouts.close_communication_timeout_for_device(device)` pēc tam, kad telemetrijas ziņojums ir veiksmīgi saglabāts. Šī funkcija:

- nekādā gadījumā **neveido** jaunus `communication_timeout` notikumus;
- aizver atvērtos `communication_timeout` notikumus konkrētai ierīcei;
- pārrēķina `AssetState.active_anomaly_count` un `has_active_anomaly`;
- nekad nepārtrauc telemetrijas saglabāšanu — kļūdas tiek reģistrētas `IngestionResult.errors` un izveidots `ingestion_error` notikums diagnostikai.

Tas nozīmē, ka anomālija parasti tiek aizvērta uzreiz, tiklīdz ierīce atsāk komunikāciju, nevis tikai pēc nākamā `check_communication_timeouts` palaiduma. Periodiskā komanda joprojām ir nepieciešama, lai noteiktu **atvēršanu** (timeout); šeit tikai aizvērsana ir paātrināta.

## Manuālā verifikācija

### Tests A — normāla ierīce nedrīkst radīt timeout

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --dry-run --verbosity 2
```

Sagaidāmais rezultāts: ja `charger-001` nesen ir komunicējis, tā statuss ir `ok` un nav izveidoti jauni `communication_timeout` notikumi.

### Tests B — piespiedu timeout

Iestati `charger-001` `last_seen_at` stundu pagātnē:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from django.utils import timezone
from datetime import timedelta
from apps.assets.models import Device
d = Device.objects.get(device_uid='charger-001')
d.last_seen_at = timezone.now() - timedelta(hours=1)
d.save(update_fields=['last_seen_at'])
print(d.device_uid, d.last_seen_at)
"
```

Palaid pārbaudi:

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --verbosity 2
```

Pārbaudi notikumus:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.events.models import Event
print(list(Event.objects.filter(event_type='communication_timeout').order_by('-detected_at').values('event_type','severity','status','title','source','description')[:5]))
"
```

Sagaidāmais rezultāts: viens atvērts `communication_timeout` notikums ar `severity=warning` un `source=analytics`. Saistītais `AssetState.status` ir `offline`.

### Tests C — atveseļošanās

Termināls 1:

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py run_mqtt_worker --once --timeout-seconds 120 --verbosity 2
```

Termināls 2:

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py run_simulator --scenario default_demo --once --verbosity 2
```

Pēc tam:

```bash
docker compose -f docker-compose.local.yml exec web \
    python manage.py check_communication_timeouts --verbosity 2
```

Pārbaudi notikumus:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.events.models import Event
print(list(Event.objects.filter(event_type='communication_timeout').order_by('-detected_at').values('event_type','severity','status','closed_at','title','source')[:5]))
"
```

Sagaidāmais rezultāts: iepriekš atvērtais `communication_timeout` notikums tagad ir `closed` ar aizpildītu `closed_at`. Patiesībā telemetrija jau ingestion ceļā aizver notikumu (skat. iepriekšējo sadaļu); `check_communication_timeouts` palaišana to apstiprina un pārrēķina `AssetState`.

## Atšķirība no sliekšņu anomāliju noteikšanas

| Aspekts | `threshold_anomaly` | `communication_timeout` |
| --- | --- | --- |
| Trigeris | Mērījuma vērtība pārkāpj robežu | Ierīce nesūta ziņojumus |
| Izsaukšanas ceļš | Sinhroni pēc `Measurement` saglabāšanas | Periodiska Django management komanda |
| Process | MQTT worker → ingestion → analytics | `analytics_worker` cron uzdevums |
| Avots | `apps.analytics.services.thresholds` | `apps.analytics.services.communication_timeouts` |
| Konfigurācija | `analytics.ThresholdRule` (DB) | `Device.expected_interval_seconds` + `COMMUNICATION_TIMEOUT_*` settings |
| Aizvēršana | Vērtība atgriežas robežās | Ierīce atsāk komunicēt (sinhroni pa ingestion ceļu vai pie nākamās periodiskās pārbaudes) |
| Severity | `warning` / `error` / `critical` no noteikuma | `warning` (vienkāršots prototips) |

## Saistītie pirmkoda faili

- `apps/analytics/services/communication_timeouts.py` — pakalpojums.
- `apps/analytics/management/commands/check_communication_timeouts.py` — komanda.
- `apps/mqtt_ingestion/services/ingestion_service.py` — atveseļošanās ingestion hook (`_close_communication_timeout_for_recovered_device`).
- `apps/assets/models.py` — `Device.last_seen_at`, `Device.expected_interval_seconds`.
- `apps/digital_twin/models.py` — `AssetState.has_active_anomaly`, `AssetState.active_anomaly_count`.
- `apps/events/models.py` — `EventType.COMMUNICATION_TIMEOUT`.
- `config/settings/base.py` — `COMMUNICATION_TIMEOUT_GRACE_MULTIPLIER`, `COMMUNICATION_TIMEOUT_DEFAULT_SECONDS`.

## Diagnostika: nevēlamu globālu noteikumu atrašana

Pēc Phase 7 bugfix ieteicams periodiski pārbaudīt, vai datubāzē neatrodas neapzināti `global` tvēruma noteikumi, kas varētu aktivizēties uz nesaistītu sensoru mērījumiem.

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.analytics.models import ThresholdRule, ThresholdRuleScope
print('Aktīvie globālie noteikumi (uzmanīgi izvērtēt!):')
for r in (
    ThresholdRule.objects
    .filter(is_enabled=True, scope_level=ThresholdRuleScope.GLOBAL)
    .select_related('metric')
    .order_by('metric__key', 'code')
):
    print(f'  {r.code}  metric={r.metric.key}  bounds=({r.lower_bound}, {r.upper_bound})  severity={r.severity}')
"
```

Pārbaude pārklājošajiem `temperature_c` noteikumiem:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.analytics.models import ThresholdRule
for r in (
    ThresholdRule.objects
    .filter(metric__key='temperature_c', is_enabled=True)
    .select_related('sensor', 'asset', 'device', 'site')
    .order_by('scope_level', 'code')
):
    print(f'  {r.code:40s} scope={r.scope_level:6s}  bounds=({r.lower_bound}, {r.upper_bound})  sensor={r.sensor.code if r.sensor else None}')
"
```

Manuāla labošana (piemēram, ja datu migrācija atklāj vēsturisku noteikumu, kas patiesībā bija domāts vienam sensoram):

```python
# Django shell — promote 'rule-000001' from inferred global to sensor scope.
from apps.analytics.models import ThresholdRule, ThresholdRuleScope
from apps.assets.models import Sensor

rule = ThresholdRule.objects.get(code='rule-000001')
sensor = Sensor.objects.get(code='sensor-000001')
rule.scope_level = ThresholdRuleScope.SENSOR
rule.sensor = sensor
# clean() auto-aizpildīs device/asset/site.
rule.save()
```

vai vienkārši deaktivizēt:

```python
ThresholdRule.objects.filter(code='rule-000001').update(is_enabled=False)
```

Šis darbs **netiek automatizēts migrācijās** — operatoram apzināti jāizlemj, ko darīt ar katru atrasto globālo noteikumu.

## Tālākie soļi

Šajā uzdevumā netika ieviesti REST API endpointi, dashboard skati, WebSocket paziņojumi vai pārskatu eksporti — tie pieder vēlākiem darba uzdevumiem. Sliekšņu noteikumu redakcija pagaidām notiek tikai Django administrācijā vai ar `seed_demo_data`. Komunikācijas timeout nepiedāvā pielāgojamu severity vai message_template — tā ir vienkāršota prototipa versija.
