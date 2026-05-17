# architecture_context.md

## Dokumenta mērķis

Šis dokuments definē stabilo arhitektūras kontekstu SMT digitālā risinājuma izstrādei Cursor vidē, izmantojot Opus 4.7 modeli. Dokuments ir paredzēts kā pastāvīgs tehniskais konteksts, kas jāņem vērā, ģenerējot, pārveidojot vai pārskatot projekta pirmkodu.

Šajā projektā netiek veidots pilna produkta līmeņa komerciāls risinājums. Tiek izstrādāts Proof-of-Concept prototips, kas demonstrē pilnu IoT datu plūsmu no reālas vai simulētas ierīces līdz datubāzei, digitālā dvīņa stāvoklim, anomāliju notikumiem un tīmekļa dashboardam.

## Projekta pamatinformācija

Projekta nosaukums ir SMT digitālais risinājums. Pasūtītājs ir SIA “Sustainable Mobility Technologies”. Izpildītājs ir SIA “Baltic Open Solutions Center”.

Risinājuma tips ir IoT infrastruktūras monitoringa un digitālā dvīņa platformas prototips. Sistēmai jādemonstrē IoT datu savākšana, strukturēta datu uzglabāšana, API piekļuve, lietotāja saskarne, vienkāršots digitālais dvīnis un pamata anomāliju noteikšana.

Tehnoloģiskais pamats ir Django balstīta tīmekļa aplikācija, Mosquitto MQTT brokeris, PostgreSQL ar TimescaleDB paplašinājumu, Redis, Django REST Framework un Docker Compose izvietošanas vide.

## Galvenais arhitektūras mērķis

Arhitektūras mērķis ir izveidot modulāru, demonstrējamu un paplašināmu programmatūras prototipu, kas nodrošina vienotu datu ķēdi.

Datu ķēdei jāstrādā šādā secībā: IoT ierīce vai simulators publicē MQTT ziņojumu; Mosquitto brokeris pieņem ziņojumu; Django MQTT worker to nolasa un validē; sākotnējais raw ziņojums tiek saglabāts datubāzē; ziņojums tiek normalizēts mērījumu datos; digitālā dvīņa aktuālais stāvoklis tiek atjaunināts; analītikas slānis pārbauda sliekšņus un komunikācijas statusu; notikumi un anomālijas tiek saglabātas datubāzē; API un dashboard parāda datus lietotājam.

## Būtiskākie arhitektūras principi

### Modularitāte

Django projekts ir sadalīts skaidrās aplikācijās. Katrai aplikācijai ir viena galvenā atbildība. Nav pieļaujams izveidot lielu monolītu aplikāciju, kurā sajaukta IoT konfigurācija, telemetrija, simulatora loģika, dashboard un analītika.

### Vienota datu ķēde

Simulatoram un reālām IoT ierīcēm jāizmanto vienāds MQTT tēmu un payload modelis. Simulatora dati nedrīkst tikt rakstīti tieši `Measurement` tabulā, apejot MQTT datu uzņemšanas ķēdi, izņemot atsevišķus testus, kuros tas ir skaidri pamatots.

### Atsevišķi izpildprocesi

Django web process, MQTT datu uzņemšanas process, simulatora process un periodiskās analītikas process ir loģiski atdalīti. Ilgstošas vai periodiskas darbības nedrīkst tikt palaistas Django HTTP request/response ciklā.

### Konfigurācija datubāzē

Simulatora scenāriji, ierīču profili, mērījumu robežas, anomāliju scenāriji, MQTT tēmu šabloni un sliekšņu noteikumi tiek definēti Django datubāzē. Kods nodrošina izpildi, bet scenāriju parametri nedrīkst būt tikai hard-coded Python konstantēs.

### Raw datu un normalizētu datu nodalīšana

Sākotnējais MQTT vai REST payload tiek saglabāts raw ziņojumu tabulā. Normalizēti mērījumi tiek glabāti atsevišķā laika rindu modelī. Šis nodalījums ir obligāts, jo tas nodrošina auditu, atkļūdošanu un iespēju vēlāk mainīt parsera loģiku.

### Vienkāršots digitālais dvīnis

Digitālais dvīnis šajā prototipā ir loģiska objektu un to aktuālo stāvokļu reprezentācija. Tas nav fizikāls simulācijas modelis. Tam jāuztur infrastruktūras objekta pēdējais zināmais statuss, pēdējās komunikācijas laiks, pēdējās būtiskās mērījumu vērtības un anomāliju indikatori.

### Vienkārša analītika

Anomāliju noteikšana tiek balstīta uz sliekšņiem, komunikācijas timeout pārbaudēm un vienkāršām statistiskām pārbaudēm. Šajā prototipā nav jāievieš mākslīgā intelekta vai mašīnmācīšanās modeļi.

## Ieteicamā repozitorija struktūra

```text
smt_digital_solution/
  manage.py
  config/
    settings/
      __init__.py
      base.py
      local.py
      production.py
      test.py
    urls.py
    asgi.py
    wsgi.py
  apps/
    core/
    accounts/
    assets/
    iot_config/
    simulator/
    mqtt_ingestion/
    telemetry/
    digital_twin/
    analytics/
    events/
    api/
    dashboard/
    reports/
  scripts/
    simulator_cron_job.py
    mqtt_diagnostics.py
  docker/
    mosquitto/
      mosquitto.conf
      passwords.example
      acl.example
    nginx/
      default.conf
  docs/
    architecture_context.md
    cursor_working_rules.md
    mqtt_contract.md
    api_reference.md
    deployment_guide.md
  tests/
  docker-compose.yml
  requirements.txt
  .env.example
  README.md
```

Repozitorija struktūru drīkst precizēt atbilstoši faktiski izvēlētajai Django projekta ģenerēšanas metodei, bet aplikāciju loģiskais sadalījums un izpildprocesu nodalījums ir jāsaglabā.

## Django aplikāciju atbildības

### `core`

Aplikācija satur kopīgās utilītas, bāzes modeļus, statusu izvēlnes, laika funkcijas, UUID palīgfunkcijas, health check skatus un citas kopīgas komponentes, kas nepieder specifiskam domēna modulim.

Šajā aplikācijā nedrīkst ievietot specifisku telemetrijas, simulatora vai dashboard biznesa loģiku.

### `accounts`

Aplikācija satur vienkāršotu lietotāju un piekļuves pārvaldību. Prototipā pietiek ar Django standarta autentifikāciju, admin lietotājiem un dashboard piekļuves kontroli.

Pilna lomu un tiesību sistēma nav obligāta prototipa pirmajā versijā, bet struktūrai jāļauj to pievienot vēlāk.

### `assets`

Aplikācija ir infrastruktūras objektu reģistrs. Tajā tiek definēti `Site`, `Asset`, `Device`, `Sensor` un saistītie modeļi.

`Site` apraksta testēšanas vai demonstrācijas vietu. `Asset` apraksta digitālā dvīņa objektu, piemēram, uzlādes vietu, infrastruktūras mezglu, baterijas moduli vai sensoru grupu. `Device` apraksta fizisku vai simulētu IoT ierīci. `Sensor` apraksta konkrētu mērījumu avotu ierīcē.

Šī aplikācija nosaka, kas sistēmā eksistē.

### `iot_config`

Aplikācija satur IoT un mērījumu konfigurāciju. Tajā jāglabā `MetricDefinition`, MQTT tēmu šabloni, ierīču profili, sagaidāmie komunikācijas intervāli, normālās vērtību robežas un konfigurācijas parametri, kurus izmanto gan ingestion, gan simulatora, gan analītikas moduļi.

Šī aplikācija nosaka, kādus datus sistēma saprot.

### `simulator`

Aplikācija satur simulācijas scenāriju konfigurāciju. Tajā jāglabā `SimulatorScenario`, `SimulatorRun`, `DeviceProfile`, `MetricProfile` un `AnomalyScenario`.

Svarīgs arhitektūras noteikums: `simulator` aplikācija definē simulācijas parametrus Django datubāzē, bet nepārtrauktu datu ģenerēšanu neveic Django web procesā.

Faktiskā izpilde jārealizē kā Django management command, piemēram:

```bash
python manage.py run_simulator --scenario default_demo --once
python manage.py run_simulator --scenario default_demo --duration-minutes 60
```

Šo komandu var izsaukt cron, systemd timer vai cits plānotājs.

### `mqtt_ingestion`

Aplikācija satur MQTT ziņojumu uzņemšanas un apstrādes loģiku. Tajā jābūt tēmu parserim, payload validatoram, idempotences pārbaudei, raw ziņojumu saglabāšanas servisam un normalizētu mērījumu izveides servisam.

Šī aplikācija nav web dashboard modulis. Tā primāri tiek izmantota `mqtt_worker` izpildprocesā.

### `telemetry`

Aplikācija satur mērījumu datu modeļus. Tajā jābūt raw ziņojumu un normalizētu mērījumu modeļiem.

`RawMessage` saglabā pilnu sākotnējo MQTT vai REST ziņojumu, tēmu, saņemšanas laiku, parsera statusu un kļūdas informāciju.

`Measurement` saglabā normalizētu laika rindas ierakstu ar saiti uz asset, device, sensor, metric, timestamp, value un datu kvalitātes indikatoriem.

### `digital_twin`

Aplikācija uztur digitālā dvīņa aktuālo stāvokli. Galvenais modelis ir `AssetState`.

`AssetState` satur pēdējo zināmo statusu, pēdējās komunikācijas laiku, pēdējās būtiskās metrikas, aktīvo anomāliju indikatorus un saiti uz infrastruktūras objektu.

Šī aplikācija nedrīkst dublēt pilnu mērījumu vēsturi. Vēsturiskie dati paliek `telemetry` aplikācijā.

### `analytics`

Aplikācija satur vienkāršu analītikas un anomāliju noteikšanas loģiku.

Obligātās pārbaudes ir sliekšņu pārsniegums, komunikācijas timeout un, ja tiek ieviests, vienkārša statistiska novirze. Noteikumiem jābūt konfigurējamiem datubāzē, nevis tikai hard-coded kodā.

### `events`

Aplikācija satur notikumus, brīdinājumus, validācijas kļūdas, anomālijas un auditācijas ierakstus.

Galvenais modelis ir `AnomalyEvent` vai līdzvērtīgs notikumu modelis. Tam jāglabā notikuma tips, smaguma pakāpe, statuss, izveides laiks, noslēgšanas laiks, avota objekts, avota ierīce un, ja iespējams, saistītais mērījums.

### `api`

Aplikācija satur Django REST Framework serializerus, ViewSet struktūru, filtrus un API maršrutus.

API jānodrošina piekļuve vietām, objektiem, ierīcēm, mērījumiem, digitālā dvīņa stāvokļiem, anomālijām, raw ziņojumiem un simulatora konfigurācijai.

### `dashboard`

Aplikācija satur lietotāja saskarni. Sākotnējā prototipā ieteicams izmantot Django templates ar vieglu JavaScript, HTMX, Alpine.js, Chart.js, Plotly.js vai līdzvērtīgu bibliotēku.

Dashboard jānodrošina galvenais pārskats, objektu saraksts, objekta detalizētais skats, mērījumu grafiki, anomāliju pārskats un simulatora statusa skats.

### `reports`

Aplikācija satur vienkāršus eksportus un pārskatus, piemēram, CSV vai Excel eksportu mērījumiem, anomālijām un demonstrācijas datiem.

Šī aplikācija nav kritiska pirmās datu ķēdes ieviešanai, tādēļ to drīkst ieviest vēlāk.

## Galvenie datu modeļi

### Infrastruktūras un ierīču modeļi

`Site` apraksta fizisku vai loģisku lokāciju. `Asset` apraksta digitālā dvīņa objektu. `Device` apraksta fizisku vai simulētu IoT ierīci. `Sensor` apraksta mērījumu avotu ierīcē. `MetricDefinition` apraksta atļauto metriku, mērvienību, datu tipu un normālās vērtības intervālu. `SensorMetric` (caur-modelis `apps.assets`) deklarē, kuras `MetricDefinition` rindas konkrēts `Sensor` spēj ražot — tas ir vienīgais autoritatīvais sensora–metrikas saskaņojuma avots ingestion, simulatora un analītikas slāņos. Sk. arī `docs/data_model.md`.

### Telemetrijas modeļi

`RawMessage` saglabā sākotnējo ienākošo ziņojumu. `Measurement` saglabā normalizētu mērījumu, kas piemērots grafikām, filtrēšanai, digitālā dvīņa atjaunināšanai un anomāliju noteikšanai.

### Digitālā dvīņa modeļi

`AssetState` uztur infrastruktūras objekta aktuālo stāvokli. Tas nav pilns vēsturisko datu dublējums, bet pēdējā zināmā stāvokļa projekcija.

### Analītikas un notikumu modeļi

`ThresholdRule` vai līdzvērtīgs modelis definē anomāliju sliekšņus. Sliekšņu apjoms var būt globāls, `Site`-, `Asset`-, `Device`-, vai **`Sensor`**-līmenī. `AnomalyEvent`/`Event` saglabā konstatētos notikumus, to statusu un saistību ar objektu, ierīci, sensoru vai mērījumu.

### Simulatora modeļi

`SimulatorScenario` definē simulācijas scenāriju. `SimulatorRun` glabā konkrētas izpildes diagnostiku. `DeviceProfile` un `MetricProfile` definē, ko simulators ģenerē. `SimulatorMetricProfile.sensor` saista katru ģenerējamo metriku ar konkrētu `Sensor` (tā lai vērtības atspoguļotu reālo sensoru-centrēto modeli). `AnomalyScenario` definē demonstrējamas novirzes.

## MQTT komunikāciju modelis

MQTT tēmu modelis ir šāds:

```text
smt/{environment}/{site_id}/{asset_type}/{device_id}/telemetry
smt/{environment}/{site_id}/{asset_type}/{device_id}/status
smt/{environment}/{site_id}/{asset_type}/{device_id}/event
smt/{environment}/{site_id}/{asset_type}/{device_id}/command
smt/{environment}/{site_id}/{asset_type}/{device_id}/command_ack
```

Pirmajā prototipa versijā obligāti jārealizē telemetrijas un statusa ziņojumu apstrāde. `command` un `command_ack` tēmas jāsaglabā arhitektūrā kā nākotnes paplašināšanas iespēja, bet pilna vadības loģika nav obligāta.

## Telemetrijas payload līgums

Pamata telemetrijas ziņojums ir JSON formātā.

```json
{
  "message_id": "7b5d6f6e-3b2f-4a61-9b55-1b2a2e7b0401",
  "device_id": "charger-001",
  "asset_id": "asset-001",
  "timestamp": "2026-05-16T10:00:00Z",
  "metrics": {
    "voltage_v": 52.3,
    "current_a": 1.8,
    "power_w": 94.1,
    "temperature_c": 31.5,
    "battery_soc_pct": 78.0
  },
  "status": "charging",
  "firmware_version": "0.1.0"
}
```

Obligātie lauki ir `message_id`, `device_id`, `timestamp` un `metrics`. `asset_id` ir vēlams lauks, bet sistēmai jādod iespēja atrast asset pēc device konfigurācijas, ja asset_id nav nosūtīts. `message_id` tiek izmantots idempotences kontrolei. `timestamp` jāinterpretē kā UTC laiks.

## Datu plūsma

Galvenā datu plūsma ir šāda.

1. Simulators vai reāla ierīce ģenerē telemetrijas ziņojumu.
2. Ziņojums tiek publicēts Mosquitto brokerī.
3. `mqtt_worker` abonē telemetrijas tēmas.
4. `mqtt_ingestion` saglabā sākotnējo ziņojumu kā `RawMessage`.
5. Ziņojums tiek validēts un parsēts.
6. No `metrics` objekta tiek izveidoti normalizēti `Measurement` ieraksti.
7. `digital_twin` atjaunina `AssetState`.
8. `analytics` pārbauda sliekšņus un komunikācijas stāvokli.
9. `events` izveido anomāliju vai notikumu ierakstus.
10. `api` un `dashboard` publicē datus lietotājam.

## Simulatora izpildes modelis

Simulators ir datubāzē konfigurējams, bet izpildes ziņā neatkarīgs process.

Django administrācijas vidē vai dashboardā tiek definēts scenārijs. Scenārijs satur aktīvo statusu, ierīču sarakstu, metrikas, vērtību robežas, ģenerēšanas intervālus un anomāliju uzvedību.

Cron vai systemd timer palaiž Django management command. Komanda nolasa aktīvo scenāriju, aprēķina nākamās vērtības un publicē MQTT ziņojumus Mosquitto brokerī. Komanda neatjaunina `Measurement` tabulu tieši.

Piemēra cron ieraksts:

```cron
*/1 * * * * /srv/smt/.venv/bin/python /srv/smt/manage.py run_simulator --scenario default_demo --once >> /var/log/smt/simulator.log 2>&1
```

## API pamatendpointi

Projektā jāparedz vismaz šādi API endpointi:

```text
GET /api/sites/
GET /api/assets/
GET /api/assets/{id}/
GET /api/assets/{id}/state/
GET /api/assets/{id}/measurements/?metric=temperature_c&from=...&to=...
GET /api/devices/
GET /api/anomalies/
GET /api/raw-messages/
GET /api/simulator/scenarios/
POST /api/simulator/start/
POST /api/simulator/stop/
```

API pirmajā versijā var būt vienkāršots, bet tam jābūt pietiekamam dashboard darbībai un demonstrācijai.

## Dashboard pamatfunkcijas

Dashboard jāietver galvenais pārskats, objektu saraksts, objekta detalizētais skats, mērījumu grafiki, anomāliju pārskats un simulatora statusa skats.

Galvenajā pārskatā jābūt redzamam objektu skaitam, aktīvo objektu skaitam, pēdējo mērījumu laikam, aktīvajām anomālijām un sistēmas darba statusam.

Objekta detalizētajā skatā jābūt redzamam digitālā dvīņa stāvoklim, pēdējiem mērījumiem, vēsturiskajiem grafikiem un saistītajiem notikumiem.

## Izvietošanas modelis

Prototips tiek izvietots ar Docker Compose. Galvenie servisi ir šādi:

```text
web
mqtt
db
redis
mqtt_worker
simulator_cron_job
analytics_worker
nginx vai caddy
```

`web` ir Django web aplikācija. `mqtt` ir Mosquitto brokeris. `db` ir PostgreSQL ar TimescaleDB. `redis` nodrošina Channels vai fona uzdevumu starpslāni. `mqtt_worker` apstrādā MQTT ziņojumus. `simulator_cron_job` periodiski ģenerē simulācijas ziņojumus. `analytics_worker` pārbauda periodiskas anomālijas, piemēram, komunikācijas timeout. `nginx` vai `caddy` nodrošina reverse proxy, statiskos failus un HTTPS, ja prototips tiek izvietots publiski.

## Drošības līmenis prototipā

Prototipam nav jāievieš pilna produkta līmeņa drošība, bet nedrīkst veidot pilnīgi atvērtu un nekontrolētu sistēmu. Django admin un dashboard jāaizsargā ar autentifikāciju. Mosquitto jāizmanto vismaz lietotājvārds un parole. Noslēpumi jāglabā `.env` failā vai vides mainīgajos, nevis pirmkodā.

Publiskas izvietošanas gadījumā jāizmanto HTTPS caur reverse proxy.

## Testēšanas fokuss

Svarīgākie testi ir end-to-end pārbaudes, kas apliecina pilnu datu ķēdi.

Jāpārbauda, ka simulatora komanda publicē MQTT ziņojumu, Mosquitto to pieņem, `mqtt_worker` to apstrādā, raw ziņojums tiek saglabāts, normalizēti mērījumi tiek izveidoti, `AssetState` tiek atjaunināts, sliekšņa pārsniegums izveido `AnomalyEvent`, un dashboard vai API parāda atbilstošos datus.

Papildus jāpārbauda idempotence, obligāto lauku validācija, nezināma device apstrāde, komunikācijas timeout un simulatora konfigurācijas ietekme uz ģenerētajiem datiem.

## Pirmās izstrādes prioritātes

Pirmajā kārtā jāizveido projekta karkass, Docker Compose vide un aplikāciju struktūra. Otrajā kārtā jāizveido datu modeļi. Trešajā kārtā jāievieš MQTT datu uzņemšana. Ceturtajā kārtā jāievieš simulatora konfigurācija un cron izpilde. Tikai pēc tam jāveido digitālais dvīnis, anomālijas, API un dashboard.

Dashboard nedrīkst kļūt par pirmo izstrādes uzdevumu, jo tam jābalstās uz reāli strādājošu datu ķēdi.

## Skaidri ārpus pirmā prototipa apjoma

Pirmajā prototipā nav jāievieš pilna lietotāju lomu sistēma, daudzklientu arhitektūra, pilns IoT komandu vadības modulis, ražošanas līmeņa mērogošana, sarežģīti ML modeļi, sarežģīta fiziska digitālā dvīņa simulācija vai pilna sertifikācijas līmeņa drošība.

Šīs lietas var atstāt kā nākotnes paplašināšanas virzienus, ja vien pasūtītājs vēlāk tās skaidri neiekļauj tvērumā.
