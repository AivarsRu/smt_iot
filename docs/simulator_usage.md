# simulator_usage.md

## Dokumenta mērķis

Šis dokuments apraksta SMT digitālā risinājuma simulatora lietošanu — kā konfigurēt scenāriju, kā palaist `run_simulator` Django management komandu un kā pārliecināties, ka publicētie ziņojumi pareizi nonāk līdz datubāzei caur jau pārbaudīto MQTT datu uzņemšanas ķēdi.

## Ko simulators dara un ko ne

Simulators ir Django management komanda, kas:

- nolasa scenāriju no Django datubāzes;
- ģenerē telemetrijas payload katrai aktīvajai ierīcei scenārijā;
- publicē payload Mosquitto brokerī kā JSON ziņojumu QoS 1 līmenī;
- atjaunina `SimulatorRun` ierakstu ar izpildes statusu un publicēto ziņojumu skaitu;
- atjaunina `SimulatorScenario.last_run_at`.

Simulators **nerakstī**:

- `RawMessage`, `Measurement`, `AssetState` vai `Event` ierakstus tieši — visa telemetrijas saglabāšana notiek tikai ceļā:

  `run_simulator → Mosquitto → run_mqtt_worker → process_mqtt_message → datubāze`.

Šis arhitektūras princips ir nemainīgs: simulatora un reālo IoT ierīču datu plūsma izmanto vienādu MQTT līgumu un vienādu datu uzņemšanas servisu.

## Konfigurācija datubāzē

Simulatora scenāriju konfigurācija atrodas `apps.simulator.models`:

- `SimulatorScenario` — augstākā līmeņa scenārijs (kods, sait, noklusētais statuss, intervāls).
- `SimulatorScenarioDevice` — saite uz konkrētu `assets.Device`, ko scenārijs simulē.
- `SimulatorMetricProfile` — metrikas ģenerēšanas parametri (`base_value`, `min_value`, `max_value`, `noise_amplitude`, `generation_mode`).
- `SimulatorRun` — vienas komandas izpildes audita ieraksts.

Scenāriju var konfigurēt Django administrācijā vai ar `seed_demo_data` komandu.

## MQTT vide un tēmas

Simulators veido tēmas pēc šāda parauga:

```
smt/{settings.SMT_ENV}/{site.code}/{asset.asset_type}/{device.device_uid}/telemetry
```

`SMT_ENV` ir vienīgais avots vides segmenta veidošanai. Vērtība tiek lasīta no `.env.local` vai vides mainīgā.

Pašreizējā lokālajā vidē:

- `SMT_ENV=dev`
- piemērs: `smt/dev/default_demo/charger/charger-001/telemetry`

Mosquitto ACL pašreiz atļauj lietotājam `smt_simulator` publicēt tikai uz `smt/dev/...` tēmām. Ja `SMT_ENV` tiek mainīts uz citu vērtību, ACL un Mosquitto konfigurācija arī jāpielāgo.

Simulators autentificējas Mosquitto brokerī ar:

- `MQTT_SIMULATOR_USERNAME` (noklusējuma `smt_simulator`)
- `MQTT_SIMULATOR_PASSWORD`

Šīs vērtības **nedrīkst** pārklāties ar ingestion worker akreditācijas datiem (`MQTT_USERNAME` / `MQTT_PASSWORD`).

## Demo datu sagatavošana

Pirms simulatora lietošanas nepieciešams sagatavot demo datus (Site, Asset, Device, MetricDefinitions, scenārijs un metric profili). Komanda ir idempotenta — to var palaist vairākas reizes.

```bash
docker compose -f docker-compose.local.yml exec web python manage.py seed_demo_data
```

Pēc šīs komandas datubāzē eksistē `default_demo` scenārijs, kas saistīts ar `charger-001` ierīci un piecām metrikām.

## `run_simulator` komandas izpildes režīmi

### Sausais izmēģinājums

Sausais režīms ģenerē payload un izvada to standarta izvadē, bet **nepublicē** uz MQTT.

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --once --dry-run --verbosity 2
```

Izvades pēdējā rinda izmanto vārdu **generated**, nevis **published**:

```
run_simulator: generated 1 message(s) across 1 cycle(s) for scenario 'default_demo' [dry-run, not published]
```

### Vienreizēja izpilde

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --once
```

Tiek izpildīts tieši viens cikls (viens ziņojums katrai aktīvai `SimulatorScenarioDevice` ierīcei) un komanda izbeidzas.

### Atkārtotas iterācijas (`--iterations`)

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --iterations 5 --sleep-seconds 10 --verbosity 2
```

Izpilda tieši `N` ciklus un pēc tam izbeidzas. Starp cikliem tiek gulēts `--sleep-seconds` sekundes (vai `SimulatorScenario.interval_seconds`, ja `--sleep-seconds` netiek norādīts). Pēc pēdējā cikla pauze nenotiek.

`--iterations` jābūt pozitīvs vesels skaitlis. Nulle vai negatīva vērtība izraisa `CommandError`.

### Ilguma režīms (`--duration-seconds`)

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --duration-seconds 60 --sleep-seconds 10 --verbosity 2
```

Izpilda atkārtotus ciklus, līdz norādītais ilgums sekundēs ir pagājis. Tiek izmantots `time.monotonic()` — laika pārbaude notiek pēc katra cikla un pēc katras pauzes. Pēdējais cikls drīkst nedaudz pārsniegt termiņu, ja tas jau bija sācies.

### Pauze starp cikliem (`--sleep-seconds`)

`--sleep-seconds N` pārklāj `SimulatorScenario.interval_seconds`. Vērtība var būt nulle (pauzes nav). Negatīva vērtība izraisa `CommandError`.

### Noklusējuma režīms

Ja netiek norādīts neviens no `--once`, `--iterations` vai `--duration-seconds`, komanda izpilda **vienu ciklu** un izvada brīdinājumu:

```
WARNING: No --once / --iterations / --duration-seconds specified — running a single cycle.
Use --iterations N or --duration-seconds N for repeated execution.
```

Tas ir drošības noklusējums, lai nejauši nepalaistu bezgalīgu ciklu cron uzdevumā.

### Savstarpēja izslēgšana

`--once`, `--iterations` un `--duration-seconds` ir savstarpēji izslēdzoši. Vienlaikus drīkst norādīt tikai vienu no tiem.

## `SimulatorRun` ieraksts

Katra `run_simulator` izpilde izveido **vienu** `SimulatorRun` ierakstu (ne vienu uz katru ciklu).

- Sākumā `status="running"`.
- Pēc veiksmīgas pabeigšanas: `status="completed"`, `finished_at` un `messages_published` aizpildīti ar kopējo skaitu pa visiem cikliem.
- Pēc neveiksmīgas izpildes: `status="failed"`, `error_message` aizpildīts, un `messages_published` saglabā daļējo skaitu (cik ziņojumi tika apstiprināti pirms kļūdas).

## Verifikācija

### Tieša MQTT publicēšana ar `mosquitto_sub`

Termināls 1 — abonēt visas tēmas:

```bash
docker compose -f docker-compose.local.yml exec mqtt mosquitto_sub -d \
  -h localhost -p 1883 -u smt_ingestion -P local_ingestion_password \
  -t "smt/#" -v
```

Termināls 2 — palaist trīs iterācijas ar 5 sekunžu pauzi:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --iterations 3 --sleep-seconds 5 --verbosity 2
```

Sagaidāmais rezultāts: `mosquitto_sub` saņem trīs ziņojumus ar atšķirīgiem `message_id` UUID uz tēmas:

```
smt/dev/default_demo/charger/charger-001/telemetry
```

### Pilnas datu ķēdes pārbaude ar `run_mqtt_worker`

Termināls 1 — palaist worker vienreizēja režīmā:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_mqtt_worker --once --timeout-seconds 120 --verbosity 2
```

Termināls 2 — palaist simulatoru:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py \
  run_simulator --scenario default_demo --once --verbosity 2
```

Sagaidāmais rezultāts: `run_mqtt_worker` izvada `--once: message processed successfully` un izbeidzas.

Datubāzes pārbaude:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.telemetry.models import RawMessage, Measurement
rm = RawMessage.objects.order_by('-received_at').first()
print('RawMessage:', rm.message_id, rm.device_uid, rm.processing_status, rm.topic)
print('Measurements:', Measurement.objects.filter(raw_message=rm).count())
"
```

Sagaidāmais rezultāts:

- `RawMessage.processing_status` = `parsed`
- `Measurement` skaits = `5`
- `AssetState` ir atjaunināts ar jaunākajām simulētajām vērtībām.

## Cron izpilde

`run_simulator` ir veidots tā, lai būtu drošs cron uzdevumiem:

- iziet ar kodu `0` veiksmīgas izpildes gadījumā;
- izvirza `CommandError` neatkopjamas kļūdas gadījumā (cron logos redzams `Simulator failed: ...`);
- nepieprasa termināla mijiedarbību;
- bez `--iterations` vai `--duration-seconds` izpilda tikai vienu ciklu, nevis bezgalīgu ciklu.

### Piemērs (lokāla Docker Compose vide)

```cron
* * * * * cd /srv/smt_iot && \
  docker compose -f docker-compose.local.yml exec -T web \
    python manage.py run_simulator --scenario default_demo --once \
    >> /var/log/smt/simulator.log 2>&1
```

### Pārklājuma novēršana ar `flock`

Lai izvairītos no vairākām vienlaicīgām izpildēm (piemēram, ja iepriekšējā izpilde joprojām nav pabeigta), ieteicams ietīt komandu `flock` slēdzī:

```cron
* * * * * /usr/bin/flock -n /tmp/smt_simulator.lock \
  /usr/bin/docker compose -f /srv/smt_iot/docker-compose.local.yml exec -T web \
    python manage.py run_simulator --scenario default_demo --once \
    >> /var/log/smt/simulator.log 2>&1
```

Iekšēja faila slēdzene komandā šajā prototipa kārtā nav iekļauta — tā tiek atstāta izvietošanas līmenim.

### Produktīvā vide

Produktīvā vidē jāizmanto atbilstošais Compose fails (`docker-compose.prod.yml`), pareizs scenārijs, ja tas atšķiras no `default_demo`, un atbilstoša konfigurācija `.env` vai vides mainīgajos. `SMT_ENV` jābūt iestatītam tā, lai tas atbilstu Mosquitto ACL atļautajām tēmām.

## Galvenie drošības principi

- Mosquitto parole netiek logēta. Publisher diagnostikas izvadē redzami tikai `topic`, `payload_bytes`, `host:port` un karogs `authenticated=True/False`.
- `MQTT_SIMULATOR_PASSWORD` glabājama `.env.local` (gitignored) vai vides mainīgajos. Repozitorijā paroles nedrīkst nokļūt.
- Simulators publicē ziņojumus tikai pēc tam, kad Mosquitto ir apstiprinājis CONNECT (CONNACK) un PUBLISH (PUBACK) ar `wait_for_publish`. Šī uzvedība jāsaglabā — to nedrīkst regresēt uz „fire-and-forget” `client.publish()` bez tīkla cilpas un publicēšanas apstiprinājuma.
