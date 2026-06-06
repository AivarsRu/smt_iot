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
- `SimulatorMetricProfile` — metrikas ģenerēšanas parametri (`base_value`, `min_value`, `max_value`, `noise_amplitude`, `generation_mode`). **Katrai rindai ir obligāts `sensor` lauks**, kas saista profilu ar konkrētu `assets.Sensor`; sensoram ir jāpieder tai pašai `Device`, kuru norāda `SimulatorScenarioDevice`, un metrikai ir jābūt deklarētai sensoram caur `SensorMetric` (sk. `docs/data_model.md`).
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

## Simulatora vadība no dashboard / API (Phase 7, Task 3A + 3B)

Papildus `python manage.py run_simulator …` komandai simulatoru var vadīt
no dashboarda paneļa vai tieši caur HTTP. Visi četri galapunkti dalās ar
vienu un to pašu JSON formu (sk. `docs/api_reference.md`):

```bash
# Pieejams visiem (arī anonīmiem) klientiem; atbilde satur ``can_control``.
curl http://localhost:8000/api/simulator/status/

# POST darbības tagad prasa autentifikāciju + ``simulator.can_control_simulator``
# (vai superuser). Anonīms POST atgriež HTTP 401 ar Latvian message.
curl -X POST http://localhost:8000/api/simulator/start/
curl -X POST http://localhost:8000/api/simulator/stop/
curl -X POST http://localhost:8000/api/simulator/run-once/
```

Aizmugures arhitektūra:

- `apps/simulator/services/control.py` satur servisu funkcijas
  `get_simulator_status`, `start_simulator`, `stop_simulator`,
  `run_simulator_once`. Tās atgriež plain Python `dict` ar stabiliem laukiem
  un nekad neizraisa izņēmumu uz HTTP slāni. **Atļauju pārbaude tajā netiek
  veikta** — servisa slānis paliek atkārtoti izmantojams (management
  komandas, testi, importēšana no citiem servisiem). Atļauju pārbauda
  `apps/api/views.py` līmenī, izmantojot
  `apps/api/permissions.py:CanControlSimulator`.
- DRF `views` `apps/api/views.py` ietver šīs servisu funkcijas un atgriež
  `Response`. Tie ir vienīgais rakstāmais izņēmums uz citādi tikai-lasīšanas
  REST API.

Svarīgi:

- **Sākt** un **Apturēt** **netaisa** ilgstošu Django web procesa darbu.
  Tie tikai atjaunina `SimulatorScenario.is_active`. Patiesa ģenerācija
  joprojām notiek ārpus web procesa caur `run_simulator` cron komandu vai
  manuāli.
- **Palaist vienu reizi** sinhroni izpilda **vienu** ciklu (vienu MQTT
  publikāciju katrai aktīvajai `SimulatorScenarioDevice`) un atgriež rezultātu.
  Tas ir noderīgi lokālai demonstrācijai, jo jaunais mērījums dashboardā
  parādās uzreiz, ja MQTT worker arī tiek palaists.

Kad simulatora vadība tiek izsaukta (jebkurā variantā), tiek raidīts
`simulator_status_changed` notikums uz Channels grupu `dashboard.overview`,
tāpēc dashboarda simulatora panelis atjauninās bez nepieciešamības
gaidīt 30 s polling.

### Autentifikācija un atļaujas (Phase 7, Task 3B)

Phase 7, Task 3B aizvieto pagaidu “bez autentifikācijas” režīmu ar
minimālu Django autentifikāciju + atļauju pārbaudi:

- Atļaujas kods: `simulator.can_control_simulator`
  (definēts `SimulatorScenario.Meta.permissions`).
- Tiek piemērots tikai trim POST darbībām (`start`, `stop`, `run-once`).
- `GET /api/simulator/status/` paliek lasāms visiem; atbilde tagad satur
  `can_control: bool` un `is_authenticated: bool`, lai dashboarda JS varētu
  pareizi atspoguļot pogu pieejamību bez papildu pieprasījumiem.
- Superusers (`is_superuser=True`) iet apkārt atļaujas pārbaudei.
- Atteikuma atbildes (`401 unauthenticated` / `403 forbidden`) saglabā
  parasto simulatora vadības JSON formu (ar `ok=false`,
  `scenario=null`, `errors=["not_authenticated"|"permission_denied"]`)
  un satur latviskus paziņojumus, nevis DRF noklusēto `detail`.

**Atļaujas piešķiršana Django admin.** Atveriet *Users* (vai *Groups*),
izvēlieties lietotāju → sadaļā **User permissions** atrodiet
`simulator | simulator scenario | Var vadīt simulatoru`, pievienojiet
to lietotāja sarakstam un saglabājiet.

**Atļaujas piešķiršana caur Django shell** (lokālai testēšanai):

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell
```

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
user = get_user_model().objects.get(username="operator")
perm = Permission.objects.get(content_type__app_label="simulator",
                              codename="can_control_simulator")
user.user_permissions.add(perm)
# Vai izveidojiet grupu un piešķiriet to vairākiem lietotājiem:
# from django.contrib.auth.models import Group
# group, _ = Group.objects.get_or_create(name="simulator-operators")
# group.permissions.add(perm)
# user.groups.add(group)
```

**Migrācija.** Atļauja ir pievienota `apps.simulator.models.SimulatorScenario`
modeļa `Meta.permissions` opcijās (sk. migrāciju
`apps/simulator/migrations/0003_alter_simulatorscenario_options.py`).
Migrācija ir tīrs `migrations.AlterModelOptions` — tā **nemaina** tabulas,
kolonnas vai indeksus; tikai aktivizē Django `post_migrate` signālu, kas
izveido attiecīgo `auth.Permission` ierakstu.

**CSRF.** POST darbības iet caur Django `SessionAuthentication`, tāpēc
pieprasījumiem ir jāsatur `X-CSRFToken` galvene un atbilstošs `csrftoken`
cookie. Dashboarda JS to risina automātiski; ārējie CLI klienti var iegūt
CSRF cookie, veicot autentificētu GET pieprasījumu (piem., `/admin/`) un
izmantot to kopā ar sesijas cookie. CSRF nav atspējots ne globāli, ne
konkrēti šiem galapunktiem.

## Simulatoru darba lapa un profila redaktors (Phase 7, Task 4)

Sākot ar Phase 7 Task 4 simulatora vadība un profila konfigurācija ir
**pārvietota no dashboarda pārskata uz atsevišķu darba lapu**:

- `GET /dashboard/simulator/` (route name: `dashboard:simulator`)
- Augšējās navigācijas izvēlne: **Simulators**
- Pieejas kontrole: tā pati `LoginRequiredMixin` kā pārējām dashboarda
  lapām. Vadības darbības (Sākt, Apturēt, Palaist vienu reizi) un
  profila rediģēšana prasa atļauju `simulator.can_control_simulator`
  (vai `is_superuser=True`).

### Modelu lietojums

Phase 7 Task 4 **nepievieno jaunus modeļus un nerada jaunas
migrācijas**. Esošie modeļi jau pārstāv pilnīgu profilu:

- `simulator.SimulatorScenario` — profila pamats: `code`, `name`,
  `description`, `site_code`, `interval_seconds`, `default_status`,
  `is_active`, `last_run_at`, atļauja `can_control_simulator`.
- `simulator.SimulatorScenarioDevice` — sasaiste ar konkrētu
  `iot_config.Device` (un caur to ar `assets.Asset`), kā arī ar tās
  ierīces metriku profilu.
- `simulator.SimulatorMetricProfile` — `metric_key`, `unit`,
  `min_value`, `base_value`, `max_value`, `noise_amplitude`,
  `is_enabled`, `sort_order`. Ja nav iestatīta sava etiķete vai
  mērvienība, tas ir mantots no `iot_config.MetricDefinition`.

### Profila API

Sk. `docs/api_reference.md` sadaļu *Simulatora profilu galapunkti
(Phase 7, Task 4)*. Īsumā:

- `GET /api/simulator/profiles/` — saraksts (publisks lasījums);
- `POST /api/simulator/profiles/` — izveido profilu (write-protected);
- `GET /api/simulator/profiles/<code>/` — profila detaļas;
- `PUT/PATCH /api/simulator/profiles/<code>/` — atjaunina profilu
  (write-protected).

Visi rakstīšanas pieprasījumi prasa autentificētu sesiju, atļauju
`simulator.can_control_simulator` un derīgu CSRF token.

### Definējamās metrikas

Profila redaktorā lietotājs definē vismaz šādus laukus katrai metrikai:

- atslēga (`metric_key`), piemēram `temperature_c`, `voltage_v`,
  `power_w`, `battery_soc_pct`;
- displeja etiķete (latviski);
- mērvienība (`°C`, `V`, `W`, `%`, `A`, …);
- minimālā vērtība, bāzes vērtība, maksimālā vērtība;
- trokšņa amplitūda (`noise_amplitude ≥ 0`);
- ieslēgts/izslēgts (`is_enabled`);
- opcionāla kārtošanas vērtība (`sort_order`).

Validācija: `min < max`, `bāze ∈ [min, max]`, vismaz vienai metrikai
jābūt ieslēgtai, kad metriku saraksts tiek nosūtīts.

### Tiešraides diagrammas un MQTT plūsma

Diagrammas tiek zīmētas ar iekšēju vienkāršu SVG diagrammas helperi
(bez ārējām CDN bibliotēkām), un tās atbalsta zoom ar peli (vilkšana
pa X asi), atlikšanu un auto-scroll. WebSocket pieslēgums
`ws://<host>/ws/dashboard/simulator/` saņem
`simulator_mqtt_message_sent`, `simulator_run_completed`,
`simulator_status_changed`, `telemetry_received` un saistītos
notikumus, lai diagrammas un MQTT ziņojumu plūsmas tabula
atjauninātos bez pilnas lapas pārlādes.

MQTT ziņojumu plūsmas tabula uzglabā **maksimums 100 jaunākās rindas**
pārlūkā (FIFO buferis). Tabula sākotnēji ir tukša un piepildās ar
notikumiem, kas tiek emitēti pēc lapas atvēršanas — tas ir apzināts
ierobežojums: `apps.simulator.services.control._execute_single_cycle`
publicē notikumu pēc katra ziņojuma (ieskaitot dry-run un publicēšanas
neveiksmes), bet sākotnēja vēsture netiek backfilled REST API
atbildē.

Ja WebSocket nav pieejams, lapa paliek lietojama: indikators rāda
**Tiešraide atvienota** vai **Tiešraide atspējota**, profilu saraksts
un statuss tiek atjaunināts caur REST polling, un **Palaist vienu
reizi** turpina darboties (pēc REST atbildes lapa pievienos jauno
punktu lokāli, ja iespējams).

Detalizēta lietošanas instrukcija — sk.
`docs/dashboard_usage.md` sadaļu *Simulatoru darba lapa (Phase 7, Task
4)*.

### Manuāla verifikācija

1. `python manage.py seed_demo_data` (vai jau ielādēta demo vide).
2. Atvērt `/dashboard/` un apstiprināt, ka simulatora paneļa,
   palaidienu tabulas un “Pēdējais simulators” kartes uz pārskata
   **vairs nav**.
3. Augšējā navigācijā jābūt `Simulators` linkam.
4. `/dashboard/simulator/` parāda statusu, profila redaktoru, diagrammu
   režģi un MQTT plūsmas tabulu.
5. Lietotājs ar `can_control_simulator` var:
   - izveidot vai labot profilu (vārds, kods, intervāls, metrikas);
   - saglabāt profilu (`POST` vai `PATCH /api/simulator/profiles/`);
   - nospiest **Palaist vienu reizi** un redzēt jaunu rindu MQTT
     tabulā un jaunu punktu diagrammā.
6. Lietotājs bez atļaujas redz lapu, bet pogas un metriku lauki ir
   atspējoti, un parādās latvisks paziņojums.

## Ilgi darbojošais simulatora konteiners (Phase 7, Task 4 turpinājums)

Lai dashboarda **/dashboard/simulator/** lapas tiešraides grafiki un
MQTT plūsmas tabula tiktu piepildīti automātiski (nevis tikai pēc
katra **Palaist vienu reizi** klikšķa), `docker-compose.local.yml`
un `docker-compose.prod.yml` tagad satur atsevišķu **`simulator`**
servisu.

### Kas šis serviss dara

- Palaiž `python manage.py run_simulator --scenario default_demo
  --duration-seconds 86400 --sleep-seconds 5` ar Bash retry-cilpu, kas
  pašatjaunojas pēc katra procesa iziešanas.
- Pēc katra cikla **publicē `simulator_mqtt_message_sent`
  notikumu** uz dashboarda kanāla; dashboards saņem to caur
  `ws/dashboard/simulator/` un atjaunina grafikus + MQTT plūsmas
  tabulu reālajā laikā.
- Pēc katra cikla **pārlasa `SimulatorScenario.is_active` no
  datubāzes**. Ja scenārijs ir apturēts (`is_active=False`, t.i.
  lietotājs ir nospiedis **Apturēt** uz dashboarda), serviss
  **netaisa nevienu ciklu**, bet turpina darboties un atsāk
  publicēšanu, kad scenārijs atkal kļūst aktīvs.
- `last_run_at` tiek atjaunots pēc katra cikla, tāpēc **“Pēdējais
  palaidiens”** UI vērtība ir vienmēr svaiga.

### Kā palaist

```bash
docker compose -f docker-compose.local.yml up -d simulator
docker compose -f docker-compose.local.yml logs -f simulator
```

Lai uz laiku apturētu emisiju, izmanto dashboardu (
**Apturēt**) — nav nepieciešams apturēt konteineri. Lai pilnīgi
izslēgtu emisiju, apturi servisu:

```bash
docker compose -f docker-compose.local.yml stop simulator
```

### Kā pārliecināties, ka tas strādā

1. Atver `/dashboard/simulator/` un ielogojies kā lietotājs ar
   `simulator.can_control_simulator` atļauju.
2. Pārliecinies, ka **scenārijs ir aktīvs** (statusa kartīte rāda
   “Aktīvs”). Ja nē, nospied **Sākt**.
3. Aptuveni 5 sekunžu laikā vajadzētu parādīties:
   - jaunai rindai sadaļā **MQTT ziņojumu plūsma** ar laiku, profilu,
     ierīci, MQTT topic, metriku kopsavilkumu un statusu **`ok`**;
   - jaunam punktam katras ieslēgtās metrikas grafikā sadaļā
     **Tiešraides grafiki**.
4. Nospied **Apturēt**. Nākamie 5–10 s grafiki pārstāj saņemt jaunus
   punktus — tas ir gaidīts, jo simulatora serviss atklāja
   `is_active=False` un izlaida ciklu.
5. Nospied **Sākt** vēlreiz un pārbaudi, vai punkti atsāk parādīties.

### Manuāla MQTT verifikācija ārpus dashboarda

```bash
docker compose -f docker-compose.local.yml exec mqtt \
  mosquitto_sub -h localhost \
                -u smt_ingestion \
                -P "$MQTT_INGESTION_PASSWORD" \
                -t 'smt/+/+/+/+/telemetry'
```

Ja `is_active=True`, jaunie ziņojumi parādīsies aptuveni reizi
`interval_seconds` sekundēs (noklusējumā 5).

### Ierobežojumi

- Pārkāpjamais (override) `--scenario` ir “hard-coded” compose failā
  uz `default_demo`. Lai testētu citu scenāriju, pielāgo compose vai
  palaiž `python manage.py run_simulator --scenario <code> --duration-seconds 60`
  ārpus servisa.
- `--iterations` un `--once` režīmi **NEgodina** `is_active` (tie
  izpilda fiksētu skaitu ciklu); tikai `--duration-seconds` režīms
  reaģē uz `Sākt`/`Apturēt` UI darbībām, jo tas ir paredzēts ilgi
  darbojošamies servisam.

## Galvenie drošības principi

- Mosquitto parole netiek logēta. Publisher diagnostikas izvadē redzami tikai `topic`, `payload_bytes`, `host:port` un karogs `authenticated=True/False`.
- `MQTT_SIMULATOR_PASSWORD` glabājama `.env.local` (gitignored) vai vides mainīgajos. Repozitorijā paroles nedrīkst nokļūt.
- Simulators publicē ziņojumus tikai pēc tam, kad Mosquitto ir apstiprinājis CONNECT (CONNACK) un PUBLISH (PUBACK) ar `wait_for_publish`. Šī uzvedība jāsaglabā — to nedrīkst regresēt uz „fire-and-forget” `client.publish()` bez tīkla cilpas un publicēšanas apstiprinājuma.
