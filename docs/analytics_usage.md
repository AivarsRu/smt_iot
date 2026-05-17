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
- izvēles tvērumu pēc `site`, `asset` vai `device`;
- `close_when_normal` — vai automātiski slēgt notikumu, kad vērtība atgriežas robežās.

Ja kāda mērījuma vērtība pārkāpj robežu, tiek izveidots vai atjaunināts atvērts `events.Event` ar `event_type="threshold_anomaly"`. Atkārtoti pārkāpumi atjaunina to pašu notikumu, bet **nemaina sākotnējo `detected_at`**, lai operators redzētu, cik ilgi anomālija ir aktīva.

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

## Tālākie soļi

Šajā uzdevumā netika ieviesti REST API endpointi, dashboard skati, WebSocket paziņojumi vai pārskatu eksporti — tie pieder vēlākiem darba uzdevumiem. Sliekšņu noteikumu redakcija pagaidām notiek tikai Django administrācijā vai ar `seed_demo_data`. Komunikācijas timeout nepiedāvā pielāgojamu severity vai message_template — tā ir vienkāršota prototipa versija.
