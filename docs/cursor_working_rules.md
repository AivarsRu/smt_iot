# cursor_working_rules.md

## Dokumenta mērķis

Šis dokuments nosaka darba noteikumus Cursor un Opus 4.7 modeļa izmantošanai SMT digitālā risinājuma izstrādē. Noteikumi ir paredzēti, lai modelis strādātu kontrolēti, saglabātu apstiprināto arhitektūru un neveiktu plašas, nepamatotas vai grūti pārbaudāmas izmaiņas.

Šie noteikumi jāņem vērā katrā Cursor uzdevumā, kurā tiek ģenerēts, labots, refaktorēts vai pārskatīts projekta kods.

## Pamatprincips

Cursor un Opus 4.7 tiek izmantots kā izstrādes palīgs, nevis kā autonoms arhitekts. Modelis drīkst ģenerēt kodu, testus, konfigurācijas, dokumentāciju un refaktorēšanas ieteikumus, bet tam jāievēro esošā projekta arhitektūra, failu struktūra un konkrētā uzdevuma robežas.

Katra izmaiņa jāspēj pārbaudīt ar testiem, Django komandām vai manuālu demonstrācijas scenāriju.

## Darba valoda

Dokumentācija, komentāri, klientam paredzētie apraksti un projekta konteksta faili tiek rakstīti latviešu valodā.

Koda nosaukumi, modeļu nosaukumi, funkciju nosaukumi, mainīgie, API endpointi un datubāzes lauki tiek rakstīti angļu valodā, jo tas atbilst Django un Python izstrādes praksei.

Kodā komentāri jāizmanto tikai tad, ja tie paskaidro neacīmredzamu loģiku. Nav jākomentē pašsaprotamas Python vai Django darbības.

## Uzdevumu tvērums

Vienā Cursor iterācijā jārisina viens skaidrs uzdevums. Nav pieļaujams vienā uzdevumā vienlaikus izveidot datu modeli, MQTT worker, dashboard, API un Docker konfigurāciju, ja tas nav skaidri prasīts.

Pirms jebkādu izmaiņu veikšanas modelim jāidentificē, kuras aplikācijas un faili tiks mainīti. Ja uzdevuma veikšanai nepieciešamas papildu izmaiņas ārpus sākotnējā tvēruma, modelim tās jāpamato.

Modelis nedrīkst patvaļīgi pārdēvēt aplikācijas, pārkārtot projekta struktūru vai mainīt jau apstiprinātus arhitektūras principus.

## Neveikt plašas nepamatotas izmaiņas

Modelis nedrīkst veikt plašu refaktorēšanu, ja uzdevums prasa šauru labojumu. Modelis nedrīkst mainīt nesaistītus failus. Modelis nedrīkst pārrakstīt esošu strādājošu kodu tikai tāpēc, ka varētu to uzrakstīt citā stilā.

Ja nepieciešams refaktorings, tam jābūt skaidri pamatotam un sadalītam atsevišķā uzdevumā.

## Arhitektūras robežas

Jāsaglabā modulāra Django aplikāciju struktūra. Galvenās aplikācijas ir `core`, `accounts`, `assets`, `iot_config`, `simulator`, `mqtt_ingestion`, `telemetry`, `digital_twin`, `analytics`, `events`, `api`, `dashboard` un `reports`.

Nav pieļaujams izveidot vienu lielu aplikāciju, kurā sajaukta visa loģika.

Nav pieļaujams ievietot simulatora ilgstošo izpildi Django web view funkcijā vai background threadā, kas tiek palaists kopā ar web serveri.

Nav pieļaujams apiet MQTT datu ķēdi, rakstot simulatora ģenerētos mērījumus tieši `Measurement` tabulā, ja vien tas nav izolēts vienību tests.

Nav pieļaujams dublēt vēsturisko mērījumu datus `digital_twin` aplikācijā. Vēsturiskie dati pieder `telemetry` aplikācijai.

## Django aplikāciju atbildības

`assets` satur infrastruktūras objektus, ierīces un sensorus.

`iot_config` satur metrikas, tēmu šablonus, ierīču profilus, sagaidāmos komunikācijas intervālus un konfigurācijas parametrus.

`simulator` satur simulācijas scenāriju konfigurāciju un modeļus.

`mqtt_ingestion` satur MQTT ziņojumu parserus, validatorus un ingestion servisus.

`telemetry` satur raw ziņojumus un normalizētus mērījumus.

`digital_twin` satur aktuālo infrastruktūras objektu stāvokli.

`analytics` satur sliekšņu un vienkāršu anomāliju noteikšanas loģiku.

`events` satur notikumus, brīdinājumus un anomālijas.

`api` satur Django REST Framework serializerus, viewsetus, filtrus un maršrutus.

`dashboard` satur lietotāja saskarnes skatus, templates un frontend integrāciju.

`reports` satur eksportus un pārskatus.

Ja modelis nezina, kur izvietot jaunu funkcionalitāti, tam jāizvēlas aplikācija pēc šīm atbildībām, nevis jāizveido jauna aplikācija bez pamatojuma.

## Datu modeļu noteikumi

Modeļiem jābūt vienkāršiem, saprotamiem un migrējamiem. Jāizmanto Django ORM standarta iespējas.

Modeļu nosaukumiem jābūt angļu valodā un vienskaitlī, piemēram, `Site`, `Asset`, `Device`, `Sensor`, `MetricDefinition`, `RawMessage`, `Measurement`, `AssetState`, `ThresholdRule`, `AnomalyEvent`, `SimulatorScenario`, `SimulatorRun`.

Ārējām atslēgām jābūt skaidri definētām ar saprotamiem `related_name`.

Datuma un laika laukiem jāizmanto timezone-aware vērtības. Projekta datu līgumā MQTT timestamp jāinterpretē kā UTC laiks.

Raw payload jāglabā atsevišķi no normalizētiem mērījumiem. Parsera kļūdas jāspēj saglabāt diagnostikai.

Migrācijas nedrīkst dzēst datus vai mainīt esošu datu nozīmi bez skaidra pamatojuma.

## MQTT noteikumi

MQTT tēmu struktūra ir:

```text
smt/{environment}/{site_id}/{asset_type}/{device_id}/telemetry
smt/{environment}/{site_id}/{asset_type}/{device_id}/status
smt/{environment}/{site_id}/{asset_type}/{device_id}/event
smt/{environment}/{site_id}/{asset_type}/{device_id}/command
smt/{environment}/{site_id}/{asset_type}/{device_id}/command_ack
```

Pirmajā prototipā obligāti jāatbalsta `telemetry` un `status`. `command` un `command_ack` ir nākotnes paplašinājums, ja vien konkrētā uzdevumā nav prasīta to ieviešana.

MQTT payload jābūt JSON formātā. Obligātie telemetrijas lauki ir `message_id`, `device_id`, `timestamp` un `metrics`.

`message_id` jāizmanto idempotences kontrolei. Atkārtoti saņemts ziņojums ar to pašu `message_id` nedrīkst izveidot dublētus `Measurement` ierakstus.

Ja ziņojumu nevar validēt, tas jāsaglabā kā raw ziņojums ar kļūdas statusu, ja vien payload ir tehniski saglabājams.

## Simulatora noteikumi

Simulatora scenāriji tiek definēti Django datubāzē. Simulatora izpilde notiek ārpus Django web procesa.

Ieteicamā izpilde ir Django management command:

```bash
python manage.py run_simulator --scenario default_demo --once
```

vai ilgākas demonstrācijas gadījumā:

```bash
python manage.py run_simulator --scenario default_demo --duration-minutes 60
```

Simulatora management command nolasa konfigurāciju no datubāzes, ģenerē payload un publicē MQTT ziņojumu Mosquitto brokerī.

Simulatora kodam jābūt deterministiski testējamam. Ja tiek izmantots random troksnis, jāparedz iespēja norādīt seed testiem.

Simulatora konfigurācijai jāietver ierīces, metrikas, vērtību robežas, trokšņa parametri, intervāli un anomāliju scenāriji.

## Ingestion noteikumi

Ingestion process sastāv no atsevišķiem soļiem: tēmas parsēšana, raw ziņojuma saglabāšana, payload validācija, device un asset atrašana, mērījumu normalizācija, digitālā dvīņa atjaunināšana un anomāliju pārbaude.

Šiem soļiem jābūt servisa funkcijās, kuras var testēt atsevišķi. Nav vēlams visu loģiku ievietot vienā garā management command failā.

Ja kāds solis neizdodas, kļūdai jābūt reģistrētai raw ziņojuma statusā vai notikumu žurnālā.

## Digitālā dvīņa noteikumi

`AssetState` atspoguļo pēdējo zināmo stāvokli. Tas nedrīkst aizstāt `Measurement` vēsturi.

Katrs veiksmīgi apstrādāts telemetrijas ziņojums, ja tas satur attiecīgās metrikas, atjaunina attiecīgo `AssetState`.

`AssetState` jāglabā pēdējais komunikācijas laiks, pēdējais statuss, pēdējās būtiskās metrikas un aktīvo anomāliju indikators vai kopsavilkums.

## Analītikas noteikumi

Pirmajā prototipā jāievieš vienkāršas pārbaudes. Sliekšņu noteikumi jāglabā datubāzē. Komunikācijas timeout jābalstās uz ierīces sagaidāmo komunikācijas intervālu vai noklusējuma konfigurāciju.

Nav jāievieš mākslīgā intelekta, dziļās mācīšanās vai sarežģīti prognozēšanas modeļi, ja vien tas nav atsevišķi uzdots.

Anomāliju ierakstiem jābūt sasaistītiem ar asset, device, metric un, ja iespējams, konkrētu measurement.

## API noteikumi

API jāveido ar Django REST Framework.

Endpointiem jābūt konsekventiem un saprotamiem. Pamatendpointi ir:

```text
GET /api/sites/
GET /api/assets/
GET /api/assets/{id}/
GET /api/assets/{id}/state/
GET /api/assets/{id}/measurements/
GET /api/devices/
GET /api/anomalies/
GET /api/raw-messages/
GET /api/simulator/scenarios/
```

Mērījumu endpointam jāatbalsta filtrēšana pēc asset, metric un laika intervāla.

API koda ģenerēšanā jāiekļauj serializeri, skati, maršruti un testi, ja konkrētajā uzdevumā tiek pievienots jauns endpoint.

## Dashboard noteikumi

Dashboard jābūt vienkāršam un demonstrējamam. Nav jāveido sarežģīta SPA aplikācija, ja vien tas nav atsevišķi nolemts.

Pirmajai versijai pietiek ar Django templates un vieglu JavaScript vai HTMX/Alpine.js.

Dashboardam jāparāda pilna datu ķēde: objekti, aktuālais stāvoklis, pēdējie mērījumi, vēsturiskais grafiks, aktīvās anomālijas un simulatora statuss.

Dashboard nedrīkst saturēt biznesa loģiku, kas būtu jāatrodas servisos vai modeļu slānī.

## Testēšanas noteikumi

Katram būtiskam modulim jābūt testiem. Vismaz jāparedz testi modeļiem, MQTT payload validācijai, idempotencei, normalizācijai, digitālā dvīņa atjaunināšanai, anomāliju izveidei un API endpointiem.

End-to-end pārbaudē jāspēj demonstrēt šādu ķēdi: simulatora komanda publicē MQTT ziņojumu; brokeris to pieņem; worker to apstrādā; raw ziņojums un mērījumi tiek saglabāti; `AssetState` tiek atjaunināts; anomālija tiek izveidota, ja tiek pārsniegts slieksnis; dashboard vai API parāda rezultātu.

Testi nedrīkst būt atkarīgi no publiska interneta pieslēguma.

Testiem jāizmanto izolēta testu datubāze un deterministiski dati.

## Docker un konfigurācijas noteikumi

Konfigurācijai jāizmanto `.env` vai vides mainīgie. Paroles, tokeni un slepenās atslēgas nedrīkst būt pirmkodā.

Docker Compose servisam jābūt skaidri nodalītam: `web`, `db`, `mqtt`, `redis`, `mqtt_worker`, `simulator_cron_job`, `analytics_worker` un `nginx` vai `caddy`, ja reverse proxy tiek ieviests.

Konfigurācijas izmaiņām jābūt dokumentētām `.env.example` un deployment dokumentācijā.

## Koda kvalitātes noteikumi

Kods jāveido vienkāršs un uzturams. Nav jāievieš sarežģītas abstrakcijas pirms tās ir nepieciešamas.

Funkcijām jābūt īsām un testējamām. Garas management command funkcijas jāsadala servisos.

Jāizmanto type hints, kur tas uzlabo saprotamību, īpaši servisa funkcijām un parseriem.

Jāizmanto Django transakcijas gadījumos, kur vienā apstrādes ķēdē tiek veidoti vairāki savstarpēji saistīti ieraksti.

Kļūdu apstrādei jābūt skaidrai. Nav pieļaujams klusām ignorēt validācijas vai datubāzes kļūdas.

## Cursor iterācijas darba secība

Katra Cursor darba iterācija jāveic šādā secībā.

1. Pārskatīt uzdevuma mērķi un arhitektūras kontekstu.
2. Identificēt maināmos failus un aplikācijas.
3. Veikt tikai konkrētajam uzdevumam nepieciešamās izmaiņas.
4. Pievienot vai atjaunināt testus, ja tiek mainīta loģika.
5. Pārbaudīt, vai nav mainīti nesaistīti faili.
6. Palaist atbilstošās pārbaudes vai norādīt, kuras pārbaudes jāpalaiž.
7. Īsi dokumentēt, kas tika mainīts un kā to pārbaudīt.

## Aizliegtās darbības

Modelis nedrīkst dzēst esošas aplikācijas bez skaidra uzdevuma.

Modelis nedrīkst mainīt datubāzes modeļu nozīmi bez migrāciju un ietekmes paskaidrojuma.

Modelis nedrīkst ieviest jaunu framework vai būtisku ārējo bibliotēku bez pamatojuma.

Modelis nedrīkst ievietot paroles, tokenus vai slepenās atslēgas repozitorijā.

Modelis nedrīkst veidot simulatoru kā web view vai nepārtrauktu threadu Django `runserver` procesā.

Modelis nedrīkst apiet raw ziņojumu saglabāšanu normālā MQTT ingestion plūsmā.

Modelis nedrīkst sākt ar dashboard izveidi, pirms nav izveidots datu modelis un vismaz minimāla datu ķēde.

Modelis nedrīkst ieviest mākslīgā intelekta modeļus pirmajā prototipa versijā, ja tas nav skaidri uzdots.

## Atļautās atkāpes

No šiem noteikumiem drīkst atkāpties tikai tad, ja konkrētajā darba uzdevumā tas ir skaidri prasīts vai ja esošā koda realitāte padara noteikumu nepiemērojamu. Šādā gadījumā izmaiņas jāpamato, un jānorāda, kāpēc atkāpe ir nepieciešama.

## Minimālais pārbaudes komplekts pēc izmaiņām

Pēc izmaiņām jāpalaiž vismaz šādas pārbaudes, ja attiecīgā projekta daļa jau eksistē:

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py test
```

Ja projektā tiek izmantots pytest, jāpalaiž:

```bash
pytest
```

Ja mainīta Docker konfigurācija, jāpārbauda:

```bash
docker compose config
docker compose up --build
```

Ja mainīta MQTT loģika, jāpārbauda vismaz viens testa publish/subscribe scenārijs.

## Koda nodošanas kritērijs

Izmaiņu kopums ir pieņemams tikai tad, ja tas atbilst arhitektūrai, risina konkrēto uzdevumu, neievieš nesaistītas izmaiņas, ir testējams, nerada acīmredzamas migrāciju problēmas un saglabā pilnu datu ķēdes principu no MQTT payload līdz dashboard vai API attēlojumam.
