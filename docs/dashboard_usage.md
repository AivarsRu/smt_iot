# dashboard_usage.md

## Dokumenta mērķis

Šis dokuments apraksta SMT digitālā risinājuma pirmo dashboard slāni — pārlūkprogrammā skatāmu pārskata lapu, kas demonstrē sistēmas stāvokli, aktīvus, telemetriju, notikumus un simulatora vēsturi.

Dashboard ir paredzēts:

- Proof-of-Concept demonstrācijām;
- ātrai sistēmas pārbaudei izstrādes laikā;
- iekšējai diagnostikai pirms backend datu eksportēšanas uz nākotnes ražošanas frontendu.

Tas **nav** paredzēts kā produkcijas līmeņa frontend. Tas apzināti ir vienkāršs, lasāms un viegli uzturams.

## Ko dashboard rāda

Pārskata lapa `/dashboard/` parāda piecas sadaļas:

1. **Sistēmas pārskats** — galvenās kartiņas (aktīvu kopsavilkums, atvērtie notikumi, sliekšņa anomālijas, komunikācijas pārtraukumi, pēdējais mērījums, pēdējais simulators);
2. **Aktīvu statuss** — tabula ar aktīva kodu, nosaukumu, vietu, tipu, statusu, pēdējiem mērījumiem (T, U, SoC) un anomāliju skaitu;
3. **Notikumi** — atvērto/aizvērto notikumu skaitļi, kā arī nesenais notikumu saraksts ar smaguma un statusa žetoniem;
4. **Telemetrija** — RawMessage statistika, jaunāko vērtību tabula pa metrikām, kā arī nesenie mērījumi;
5. **Simulators** — scenāriju un palaidienu skaitļi, pēdējais palaidiens un pēdējo palaidienu saraksts.

Lapas augšā ir:

- veselības rādītāja žetons;
- pēdējās atjaunošanas laiks;
- **Atsvaidzināt** poga (manuāls reload);
- **Auto 30 s** izvēles rūtiņa (pēc izvēles ieslēdzama auto-atsvaidzināšana ik pēc 30 sekundēm).

## Kurus API galapunktus dashboard izmanto

Dashboard ir tikai-lasīšanas un izmanto Phase 6 publiskos REST galapunktus:

- `GET /api/overview/` — sistēmas līmeņa kopsavilkums;
- `GET /api/overview/assets/` — aktīvu skaitļi un saraksts ar `AssetState`;
- `GET /api/overview/events/` — notikumu kopsavilkums un nesenais notikumu saraksts;
- `GET /api/overview/telemetry/` — telemetrijas pārskats un mērījumi;
- `GET /api/overview/simulator/` — simulatora scenāriju un palaidienu kopsavilkums.

Aktīva tabulas rindā poga “JSON” ved uz `GET /api/assets/{code}/summary/` — viena aktīva pilnu detalizēto kopsavilkumu. Detail dashboard lapas šajā uzdevumā netiek ieviestas.

Visi pieprasījumi notiek **klienta pusē** ar `fetch()`. Django serveris nekad nevērš HTTP zvanus pats uz savu API — tas vienkārši renderē šablonu ar URL adresēm un atstāj datu ielādi pārlūkprogrammai.

## Faili

- `apps/dashboard/views.py` — `OverviewView`, `AssetDetailView`,
  `assets_list_view`, staged workflow skati (`AssetCreateStageView`,
  `asset_configure_view`, `DeviceCreateStageView`,
  `DeviceAttachStageView`, `SensorCreateStageView`,
  `SensorMetricStageView`) un `health_view`;
- `apps/dashboard/forms.py` — staged formas:
  `AssetCreateStageForm`, `DeviceCreateStageForm`, `DeviceAttachStageForm`,
  `SensorCreateStageForm`, `SensorMetricStageForm` + curated
  `TIMEZONE_CHOICES`;
- `apps/dashboard/urls.py` — `/dashboard/`, `/dashboard/health/`,
  `/dashboard/assets/`, `/dashboard/assets/new/` (Stage 1),
  `/dashboard/assets/<code>/configure/` (centrmezgls),
  `/dashboard/assets/<code>/devices/new/` un `.../devices/attach/`
  (Stage 2), `/dashboard/assets/<code>/devices/<uid>/sensors/new/`
  (Stage 3), `/dashboard/assets/<code>/devices/<uid>/sensors/<code>/metrics/new/`
  (Stage 4), un `/dashboard/assets/<asset_identifier>/` (monitorings);
- `apps/assets/services/identifiers.py` — sistēmas ģenerētie kodi
  (`generate_asset_code`, `generate_device_uid`, `generate_sensor_code`,
  `generate_threshold_rule_code` un `create_*_with_unique_code`);
- `apps/dashboard/templates/dashboard/base.html` — galvenes, navigācijas
  un footera šablons; navigācija parādās tikai pieslēgtam lietotājam;
- `apps/dashboard/templates/dashboard/overview.html` — pārskata lapa;
- `apps/dashboard/templates/dashboard/asset_detail.html` — monitoringa
  detail lapa (ar saiti uz konfigurāciju);
- `apps/dashboard/templates/dashboard/assets_list.html` — aktīvu saraksts;
- `apps/dashboard/templates/dashboard/asset_create.html` — Stage 1 forma;
- `apps/dashboard/templates/dashboard/asset_configure.html` — staged
  workflow centrmezgls;
- `apps/dashboard/templates/dashboard/device_create.html`,
  `device_attach.html`, `sensor_create.html`,
  `sensor_metric_create.html` — Stage 2-4 formas;
- `apps/dashboard/static/dashboard/dashboard.css` — minimālais stils;
- `apps/dashboard/static/dashboard/dashboard.js` — datu ielādes un
  atveidošanas loģika;
- `apps/dashboard/static/dashboard/asset_create.js` — klienta puses
  show/hide loģika visām staged formām;
- `apps/dashboard/tests.py` — staged workflow, identifikatoru,
  preset, autentifikācijas un navigācijas testi;
- `apps/iot_config/models.py` — `SensorMetricPreset` modelis;
- `apps/analytics/models.py` — `ThresholdRulePreset` modelis;
- `apps/iot_config/admin.py`, `apps/analytics/admin.py` — presetu admin
  reģistrācija;
- `apps/core/views.py` — `root_view` (publiska welcome lapa /
  pārvirze pieslēgtam lietotājam);
- `apps/core/templates/core/welcome.html` — publiskā welcome lapa;
- `apps/accounts/urls.py` — `accounts:login` un `accounts:logout`
  maršruti;
- `apps/accounts/templates/registration/login.html` — pieslēgšanās
  forma.

## Lokāla atvēršana

### 1. Sagatavot demo datus

```bash
docker compose -f docker-compose.local.yml exec web python manage.py seed_demo_data
```

### 2. Ģenerēt vismaz vienu telemetrijas ziņojumu

Termināls 1 (worker noklausās MQTT vienu reizi):

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_mqtt_worker --once --timeout-seconds 120 --verbosity 2
```

Termināls 2 (simulators publicē vienu telemetriju):

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --once --verbosity 2
```

### 3. Atvērt dashboard

```
http://localhost:8000/dashboard/
```

> Ja `web` konteinera ports atšķiras, pārbaudiet `docker-compose.local.yml` (`ports:` sadaļu pie `web` servisa).

## Manuāla atjaunošana

- **Atsvaidzināt** poga lapas augšā vienlaikus pārlādē visas piecas API atbildes un atjaunina visas sadaļas.
- **Auto 30 s** izvēles rūtiņa, ja ir atzīmēta, palaiž taimeri, kas ik pēc 30 sekundēm atkārto pieprasījumus. Ja noņem ķeksi, taimeris tiek apturēts. Pēc noklusējuma auto-atsvaidzināšana ir izslēgta, lai izvairītos no liekas API slodzes.

## Kļūdu, ielādes un tukšu datu apstrāde

- Kamēr pieprasījums vēl ir gaidīšanā, sadaļas rāda “Ielādē…” paziņojumu.
- Ja pieprasījums neizdodas (HTTP kļūda vai timeout), sadaļa rāda sarkanu "Kļūda ielādējot: …" paziņojumu — pārējās sadaļas turpina darboties neatkarīgi.
- Ja API atgriež tukšu sarakstu (piem., nav notikumu vai nav simulatora palaidienu), sadaļa rāda “Nav neseno X” paziņojumu.
- Stack trace izvades **nav atspoguļotas** UI — pārlūka konsolē redzami tikai pamata HTTP statusi.

## Aktīva detail lapa (`/dashboard/assets/{kods-vai-uuid}/`)

Phase 7, Task 2 pievienoja per-aktīva detail lapu. Tā ir tieši tādā pašā stilā kā pārskata lapa: server-side renderē tikai šablonu un padod API URL adreses, bet visus datus klients ielādē ar `fetch()`.

### Kā atvērt

Vienā no diviem veidiem:

1. No pārskata lapas: `/dashboard/` aktīvu tabulā kolonnā **Detaļas** noklikšķiniet uz "Atvērt".
2. Tieši pa URL — gan ar aktīva kodu, gan ar UUID:

   ```
   http://localhost:8000/dashboard/assets/charger-001/
   http://localhost:8000/dashboard/assets/9ab5e9e3-1392-4045-bc89-c8b6c49590e7/
   ```

`IdOrCodeLookupMixin` API līmenī jau atbalsta abus, tāpēc dashboard ceļa segments tiek tieši padots tālāk uz `/api/assets/<segment>/...`.

### Ko detail lapa rāda

- **Aktīva identitāte** — kods, nosaukums, vieta, tips, statusa žetons, pēdējoreiz redzēts, pēdējais mērījums, aktīvas anomālijas;
- **Digitālais dvīnis (state cards)** — temperatūra, spriegums, strāva, jauda, baterija (SoC %), anomāliju skaits, vai šobrīd ir aktīva anomālija;
- **Mērījumu diagrammas** — interaktīvas SVG līniju diagrammas četrām metrikām: `temperature_c`, `voltage_v`, `power_w`, `battery_soc_pct`. Phase 7 Task 4 turpinājumā tās tiek zīmētas ar to pašu `createSimulatorChart` palīgu kā simulatoru darba lapa, tāpēc katrai diagrammai ir Latvian virsraksts ar mērvienību, marķētas asis (X = `Laiks`, Y = `<Etiķete> (<Mērvienība>)`), tooltip, drag-to-zoom uz X ass, dubultklikšķis vai poga **Atiestatīt skatu**, lai atjaunotu pilnu skatu. Katra diagramma rāda līdz 100 mērījumiem un nezaudē zoom stāvokli starp atsvaidzinājumiem;
- **Pēdējie mērījumi** — tabula ar metriku, **sensoru** (`sensor_code`), vērtību, vienību, laiku, kvalitāti. Tabula tiek ietīta ritināmā kastītē ar fiksētu maksimālo augstumu (`measurements-scroll`), tāpēc lapa nepalielinās bezgalīgi, ja mērījumu skaits ir liels. Tabulas galva ir „lipīga” (sticky), lai kolonnu nosaukumi paliek redzami, ritinot;
- **Notikumi** — tabula ar tipu, smaguma žetonu, statusa žetonu, virsrakstu, atklāšanas laiku un aizvēršanas laiku;
- **Pēdējais MQTT ziņojums** — diagnostikas panelis ar `message_id`, `processing_status`, `received_at`, `topic`. Pilns payload netiek atspoguļots — tam kalpo `/api/raw-messages/`.

### Kurus API galapunktus detail lapa izmanto

- `GET /api/assets/{kods-vai-uuid}/summary/` — virsraksts, state cards, latest raw message;
- `GET /api/assets/{kods-vai-uuid}/measurements/?limit=20` — pēdējo mērījumu tabula;
- `GET /api/assets/{kods-vai-uuid}/events/?limit=20` — notikumu tabula;
- `GET /api/assets/{kods-vai-uuid}/measurements/?metric={metric_key}&limit=100` — pa vienai katras diagrammas datu kopai (`temperature_c`, `voltage_v`, `power_w`, `battery_soc_pct`).

### Atsvaidzināšana

- Galvenes **Atsvaidzināt** poga atkārtoti ielādē visas sekcijas (kopsavilkumu, mērījumu tabulu, notikumus un visas četras diagrammas paralēli).
- **Auto 30 s** izvēles rūtiņa darbojas tāpat kā pārskata lapā un izmanto to pašu globālo loģiku.

### Kļūdu, ielādes un tukšu datu apstrāde

- Katra sadaļa atsevišķi rāda "Ielādē…" / kļūdas / tukša stāvokļa paziņojumu.
- Ja `/api/assets/.../summary/` atgriež `404`, lapas augšā parādās lapas līmeņa kļūda **"Aktīvs ‘{kods}’ netika atrasts."** ar saiti atpakaļ uz `/dashboard/`. Pārējās sadaļas paliek tukšas — netiek mēģināts ielādēt mērījumus vai notikumus zudušam aktīvam.
- Ja diagrammas API atbild ar tukšu sarakstu, attiecīgā kartiņa rāda "Nav datu." nevis tukšu SVG.

### Atgriešanās uz pārskatu

Lapas augšā ir links **← Atpakaļ uz pārskatu**, kas ved uz `/dashboard/`.

## Autentifikācija un saknes lapa (Phase 7, Task 3)

Sākot ar Phase 7, Task 3, dashboard lapas ir pieejamas tikai pieslēgtam
lietotājam.

### Saknes (welcome) lapa

`GET /` rāda divus dažādus stāvokļus:

- Ja lietotājs **nav pieslēdzies**, tiek atveidota publiska sveiciena
  lapa (`apps/core/templates/core/welcome.html`) ar projekta nosaukumu,
  īsu prototipa aprakstu un pogu **Pieslēgties**, kas ved uz
  `/accounts/login/`.
- Ja lietotājs **ir pieslēdzies**, `/` veic 302 pārvirzīšanu uz
  `/dashboard/`.

### Pieslēgšanās un izlogošanās

Tiek izmantoti Django iebūvētie `LoginView` un `LogoutView` skati
(`apps/accounts/urls.py`):

- `GET /accounts/login/` — pieslēgšanās forma (`registration/login.html`);
- `POST /accounts/login/` — paroles pārbaude un sesijas izveide;
- `POST /accounts/logout/` — sesijas izbeigšana ar atpakaļatvirzi uz
  `/`.

Iestatījumi (`config/settings/base.py`):

```python
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:overview"
LOGOUT_REDIRECT_URL = "core:welcome"
```

`LoginView` saglabā `?next=...` parametru, tāpēc tieša saite uz
`/dashboard/assets/` pēc neatļauta pieprasījuma korekti atgriež
lietotāju uz tiem pašiem URL pēc veiksmīgas pieslēgšanās.

Lietotājus pārvalda Django administrācijā (`/admin/`). Šajā uzdevumā
netiek ieviesta reģistrācijas plūsma.

### Pieejas kontrole dashboard lapām

Šādi maršruti ir aizsargāti ar `LoginRequiredMixin` / `@login_required`:

- `GET /dashboard/` — pārskata lapa;
- `GET /dashboard/assets/` — aktīvu saraksts;
- `GET /dashboard/assets/new/` un `POST /dashboard/assets/new/` — aktīva
  izveides forma;
- `GET /dashboard/assets/<asset_identifier>/` — aktīva detail lapa.

Neautentificēts piekļuves mēģinājums vienmēr atgriež 302 uz
`/accounts/login/?next=<original-url>`.

## Navigācijas izvēlne

Pieslēgtiem lietotājiem `dashboard/base.html` apakšā parādās augšējā
navigācijas josla ar trim saitēm:

- **Pārskats** → `/dashboard/`;
- **Aktīvi** → `/dashboard/assets/`;
- **Izveidot jaunu aktīvu** → `/dashboard/assets/new/`.

Tāpat galvenes labajā stūrī parādās lietotājvārda žetons un poga
**Iziet**, kas iesniedz `POST /accounts/logout/` formu (Django 5
prasība GET izlogošanos vairs neatbalsta).

Publiskā welcome un login lapas šo izvēlni nerāda — tām ir tikai
projekta nosaukums un saite uz pieslēgšanos.

## Aktīvu saraksta (Analyse Assets) lapa

`GET /dashboard/assets/` ir vienkāršs server-side renderēts aktīvu
saraksts, kas paredzēts operatora pārskatam pirms detail lapas
atvēršanas. Tas neizmanto JS / API — Django views nolasa datus tieši
no ORM, lai saraksts būtu pieejams arī tad, kad API ir aizņemts.

Kolonnas:

- aktīva **kods** ar saiti uz detail lapu;
- nosaukums;
- objekta kods (`site.code`);
- aktīva tips;
- statusa žetons;
- piesaistīto ierīču skaits;
- aktīvo anomāliju skaits (no `AssetState`, ja eksistē);
- darbības (saite uz detail lapu, saite uz JSON `/api/assets/.../summary/`).

Lapas augšā ir prominenta poga **+ Izveidot jaunu aktīvu**, kas ved uz
`/dashboard/assets/new/`. Ja vēl nav neviena aktīva, sadaļā tiek rādīts
tukšs stāvoklis ar to pašu saiti.

## Aktīva konfigurācijas plūsma (Phase 7, Task 3B)

> **Svarīga izmaiņa salīdzinājumā ar Task 3.** Iepriekšējais vienlapas
> "mega-form" tika aizvietots ar **staged workflow** — katrs solis ir
> atsevišķa lapa un atsevišķa atomāra transakcija. Tehniskie
> identifikatori (`Asset.code`, `Device.device_uid`, `Sensor.code`,
> `ThresholdRule.code`) **vairs netiek ievadīti manuāli** — tos ģenerē
> sistēma. Tas atspoguļo praktisko realitāti, kur operatoram pietiek
> ar lietotājam draudzīgu nosaukumu un tipu.

### Monitorings vs konfigurācija

Diviem aktīva URL-iem ir skaidri nodalītas atbildības:

| URL                                                       | Mērķis                                                |
|-----------------------------------------------------------|-------------------------------------------------------|
| `/dashboard/assets/{kods-vai-uuid}/`                      | **Monitorings** — digitālā dvīņa stāvoklis, diagrammas, notikumi. Tikai lasīšanai. |
| `/dashboard/assets/{asset_code}/configure/`               | **Konfigurācija** — staged workflow centrmezgls. Te pievieno ierīces, sensorus, metrikas un sliekšņus. |

### Sistēmas ģenerētie identifikatori

`apps/assets/services/identifiers.py` satur `generate_*` un
`create_*_with_unique_code` palīgfunkcijas. Formāts:

- `Asset.code` → `asset-000001`, `asset-000002`, …
- `Device.device_uid` → `device-000001`, `device-000002`, …
- `Sensor.code` → `sensor-000001`, `sensor-000002`, …
- `ThresholdRule.code` → `rule-000001`, `rule-000002`, …

Algoritms ir vienkāršs: skenē esošos ierakstus ar attiecīgo prefiksu,
ņem maksimālo skaitlisko sufiksu un palielina par 1. Ja vienlaicīgi
notiek divi INSERT-i un rodas unikalitātes konflikts, `create_with_unique_code`
mēģina vēlreiz iekšējā savepoint (līdz 25 mēģinājumiem). Operatora formas
**neizvada `code` lauku**; pat ja klients tampering ar HTML un nosūta
`code=evil`, skats to ignorē un izmanto ģenerēto vērtību.

### Staged workflow soļi

1. **1. solis — izveidot aktīvu** (`GET/POST /dashboard/assets/new/`).
   Atrisina Site (esošs vai jauns) un izveido tikai `Asset`. **Neviens**
   `Device`, `Sensor`, `MetricDefinition`, `SensorMetric` vai
   `ThresholdRule` šajā solī netiek izveidots. `Site.timezone` izmanto
   ierobežotu **nolaižamo izvēlni** (UTC, Europe/Riga, Europe/London,
   Europe/Tallinn, Europe/Vilnius, Europe/Helsinki, Europe/Stockholm,
   Europe/Berlin); brīvtekstu serveris noraida.
   Veiksmīgais POST → 302 uz `/dashboard/assets/{generated_code}/configure/`.

2. **2. solis — pievienot ierīci**:
   - `GET/POST /dashboard/assets/{code}/devices/new/` — izveido jaunu
     ierīci ar ģenerētu `device_uid`. Ierīce automātiski tiek piesaistīta
     aktīva `Site` un `Asset`.
   - `GET/POST /dashboard/assets/{code}/devices/attach/` — piesaista
     esošu nepiesaistītu ierīci no tā paša `Site`. Forma noraida ierīces
     no cita Site un jau piesaistītas ierīces.

3. **3. solis — pievienot sensoru** (`GET/POST /dashboard/assets/{code}/devices/{device_uid}/sensors/new/`).
   Izveido vienu sensoru ar ģenerētu `code`. Pēc izveides notiek pārvirze
   uz **4. soli** šim sensoram. Lai pievienotu nākamo sensoru, pēc 4. soļa
   atgriežas uz konfigurācijas centrmezglu un klikšķina "+ Pievienot
   sensoru" pie tās pašas ierīces.

4. **4. solis — pievienot metriku un (pēc izvēles) sliekšņa noteikumu**
   (`GET/POST /dashboard/assets/{code}/devices/{device_uid}/sensors/{sensor_code}/metrics/new/`).
   `metric_mode` izvēle:
   - `preset` — izmantot `SensorMetricPreset`;
   - `existing` — izvēlēties esošu `MetricDefinition`;
   - `new` — izveidot jaunu `MetricDefinition`.

   Pēc tam tiek izveidots `SensorMetric` (autoritatīvā saite starp
   sensoru un metriku). `threshold_mode` izvēle:
   - `none` — neveidot sliekšņa noteikumu;
   - `preset` — materializēt `ThresholdRulePreset` kā konkrētu
     `ThresholdRule`, kas piesaistīts šim Site/Asset/Device/Sensor/Metric;
   - `manual` — definēt slieksni manuāli (vismaz viena no `lower_bound` /
     `upper_bound` ir obligāta; apgrieztas robežas noraidītas).

   **Phase 7 bugfix:** Stage 4 izveidotie `ThresholdRule` pēc noklusējuma
   ir ar `scope_level=sensor`. Operators tagad formā redz arī
   `threshold_scope_level` izvēli, kur var paplašināt tvērumu uz
   `device` / `asset` / `site` / `global`. Sensor-scope ir drošākais
   variants un atbilst "viens slieksnis vienam sensoram"; plašāks tvērums
   attiecas uz vairākiem sensoriem ar to pašu metriku, tāpēc to izvēlēties
   apzināti. Skat. `docs/analytics_usage.md` sadaļu *“Eksplicītā
   `scope_level` semantika”*.

   Veiksmīgais POST → 302 atpakaļ uz `/dashboard/assets/{code}/configure/`.

5. **Rediģēt esošu sliekšņa noteikumu** (`GET/POST
   /dashboard/assets/{code}/rules/{rule_code}/edit/`).

   Konfigurācijas centrmezgla sliekšņu tabulā katrai rindai ir
   "Rediģēt" saite. Atvērtajā formā var mainīt:

   - `name`, `description`, `message_template`;
   - `scope_level` (sensor / device / asset / site — **globāls** šeit
     nav pieejams; to mainīt drīkst tikai administrators caur Django
     admin);
   - sensor/device mērķi (no šajā aktīvā pieejamiem);
   - `lower_bound`, `upper_bound`, `severity`, `sort_order`;
   - `close_when_normal`, `is_enabled` (slēdzene noteikuma deaktivēšanai
     bez dzēšanas).

   **Svarīga blakusietekme — automātiska notikumu aizvēršana.**
   Noņemot `is_enabled` ķeksīti un saglabājot, `ThresholdRule.save()`
   modeļa līmenī uzreiz aizver visus šī noteikuma atvērtos
   `threshold_anomaly` notikumus (`closed_reason='rule_disabled'`,
   `closed_at=tagad`). Tas notiek tāpēc, ka deaktivēts noteikums vairs
   netiek izvērtēts analītikas servisā, tāpēc parastais
   "atgriešanās normā" → close ceļš to vairs nesasniegs. Detaļas skatīt
   `docs/analytics_usage.md`, sadaļā *“Notikumu automātiska aizvēršana,
   kad noteikums tiek deaktivēts”*.

   Lapa atļauj rediģēt tikai noteikumus, kas ir **sasniedzami no šī
   aktīva**:

   - sensor-scope noteikumi, kuru sensors atrodas zem aktīva ierīcēm;
   - device-scope noteikumi, kuru ierīce atrodas zem aktīva;
   - asset-scope noteikumi, kuru aktīvs ir šis aktīvs;
   - site-scope noteikumi, kuru objekts ir aktīva objekts.

   Cita aktīva noteikuma URL → 404. Veiksmīgais POST → 302 atpakaļ uz
   konfigurācijas centrmezglu.

### Konfigurācijas centrmezgls

`GET /dashboard/assets/{code}/configure/` rāda:

- aktīva identitāti un statusu;
- piesaistīto `Site`;
- visas ierīces ar to sensoriem un SensorMetric piesaistēm;
- visus aktīvam piesaistītos `ThresholdRule` ierakstus;
- darbības: pievienot/piesaistīt ierīci, pievienot sensoru ierīcei,
  pievienot metriku/slieksni sensoram, atvērt monitoringa skatu.

Lapa ir tīri server-rendered un nemaina datus pati — visas izmaiņas
notiek caur 2.–4. soļa formām.

### Presets (Phase 7, Task 3B)

Lai paātrinātu atkārtotu konfigurāciju, prototipā ir divi presetu modeļi:

- **`SensorMetricPreset`** (`apps.iot_config`) — definē tipisku sensora
  un metrikas kombināciju (piem., temperatūras sensors → `temperature_c`).
  Tiek izmantots:
  - 3. solī kā "sensora preset" — automātiski aizpilda sensora
    nosaukumu/tipu un pārvirza uz 4. soli ar preset jau atzīmētu;
  - 4. solī kā `metric_mode=preset` — `SensorMetric` tiek izveidots ar
    preseta `metric`.
- **`ThresholdRulePreset`** (`apps.analytics`) — definē atkārtoti
  izmantojamus sliekšņu noteikumus (piem., "āra temperatūra -40..+40°C").
  4. solī kā `threshold_mode=preset` tas tiek materializēts kā konkrēts
  `ThresholdRule` ieraksts ar `site/asset/device/sensor/metric` tvērumu.
  **Preset nav noteikums** — tas ir veidne, kuru var izmantot vairākiem
  konkrētiem `ThresholdRule` ierakstiem.

`seed_demo_data` idempotenti izveido šādus demo presetus:

```
SensorMetricPreset:
  temperature_sensor_preset        → temperature_c
  voltage_sensor_preset            → voltage_v
  power_sensor_preset              → power_w
  battery_soc_sensor_preset        → battery_soc_pct

ThresholdRulePreset:
  outdoor_temperature_range        → temperature_c, -40..40, warning
  high_temperature_warning         → temperature_c, ..60, warning
  battery_soc_low_warning_preset   → battery_soc_pct, 20.., warning
```

Abus presetu modeļus var pārvaldīt Django administrācijā (Iot Config un
Analytics sadaļās).

### Validācija un per-stage transakcijas

Katrs solis darbojas savā atomārā transakcijā:

| Solis | Transakcijas saturs                                        |
|-------|------------------------------------------------------------|
| 1     | (Site) + Asset                                             |
| 2a/2b | Device izveide / piesaiste                                 |
| 3     | Sensor izveide                                             |
| 4     | (MetricDefinition) + SensorMetric + (ThresholdRule)        |

Ja 4. solis neizdodas (piem., apgrieztas robežas), tiek atritināts
**tikai** šis solis — `Asset`, `Device` un `Sensor` no iepriekšējiem
soļiem paliek saglabāti. Tas ir apzināta izmaiņa salīdzinājumā ar
Task 3 vienlapas all-in-one transakciju.

Validācija notiek serverī. Klienta JS (`asset_create.js`) tikai slēpj
nederīgās laukus, lai operatoram nebūtu redzami nepiemēroti lauki, bet
visu validē Django formas un serveris.

### Klienta puses uzvedība

`apps/dashboard/static/dashboard/asset_create.js` darbojas uz katras
staged formas (atzīmētas ar `data-stage-form` vai vecā id
`asset-create-form`): tas izlasa `data-show-when` un `data-show-value`
atribūtus un slēpj rindas, kuru kontroles vērtība neatbilst gaidītajai.
Forma darbojas arī bez JS — visi lauki vienkārši paliek redzami.

### Pašreizējais ierobežojums

- 3. solī formā tiek izveidots **viens** sensors uz vienu POST; lai
  pievienotu vēl, atgriežas uz centrmezglu un atkārto.
- Rakstāmu REST API nav — viss rakstīšanas darbs notiek caur server-side
  rendered Django formām.
- Lomu pārvaldība nav — visi pieslēgtie lietotāji redz vienu un to pašu
  konfigurācijas plūsmu.

> Atgādinājums datu modelim: metrikas pieder sensoriem, nevis tieši
> ierīcēm. Visa metriku piešķiršana notiek caur `Sensor → SensorMetric
> → MetricDefinition`. Skat. `docs/data_model.md`.

## Manuāla verifikācija (Phase 7, Task 3B)

1. Izveidot vai izmantot esošu lietotāju:

   ```bash
   docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
   from django.contrib.auth import get_user_model
   U = get_user_model()
   U.objects.filter(username='operator').delete()
   U.objects.create_user(username='operator', password='op-secret-123!')
   "
   ```

2. Atvērt `http://localhost:8000/` → welcome lapa, klikšķināt **Pieslēgties**.
3. Pieslēgties (`operator` / `op-secret-123!`).
4. Atvērt **Aktīvi** → klikšķināt **+ Izveidot jaunu aktīvu**.
5. **1. solis:** izvēlēties esošu Site un nospiest "Izveidot un turpināt".
   Apstiprināt, ka aktīva kods (piem., `asset-000003`) ir **automātiski
   ģenerēts** un parādās konfigurācijas centrmezgla virsrakstā.
6. Centrmezglā klikšķināt **+ Izveidot jaunu ierīci** → ievadīt tikai
   nosaukumu un sagaidāmo intervālu → submitēt. Apstiprināt, ka
   `device_uid` (piem., `device-000004`) ir ģenerēts.
7. Pie ierīces klikšķināt **+ Pievienot sensoru** → izvēlēties
   "Temperatūras sensors" presetu → submitēt. Tiek izveidots `sensor-000001`
   un automātiski atvērta 4. soļa lapa.
8. 4. solī izvēlēties `threshold_mode=preset` → "Āra temperatūras
   diapazons" → submitēt. Apstiprināt, ka `ThresholdRule` ar kodu
   `rule-000001` parādās centrmezgla sliekšņu tabulā.
9. Centrmezglā atkārtoti klikšķināt **+ Pievienot sensoru**, lai
   pievienotu otru sensoru bez preseta (piem., manuāls nosaukums
   "Sprieguma sensors"). Apstiprināt, ka abi sensori parādās centrmezglā
   ar dažādiem ģenerētiem `code` vērtībām.
10. Atvērt **Monitorings** saiti (`/dashboard/assets/{kods}/`) un
    pārliecināties, ka tā ir nodalīta no konfigurācijas lapas.
11. Klikšķināt **Iziet** → atgriešanās uz welcome lapu.

Shell pārbaude (kā specificēts uzdevumā):

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from apps.assets.models import Asset, Device, Sensor, SensorMetric
from apps.analytics.models import ThresholdRule
a = Asset.objects.order_by('-created_at').first()
print('Asset:', a.code, a.name)
print('Devices:', list(a.devices.values_list('device_uid', flat=True)))
print('Sensors:', list(Sensor.objects.filter(device__asset=a).values_list('code','name')))
print('SensorMetrics:', list(SensorMetric.objects.filter(sensor__device__asset=a).values_list('sensor__code','metric__key')))
print('Rules:', list(ThresholdRule.objects.filter(asset=a).values_list('code','sensor__code','metric__key')))
"
```

## Notikumu un anomāliju pārskats (Phase 7, Task 4A)

Operatoram ir divas jaunas tikai-lasāmas lapas notikumu un anomāliju
caurskatīšanai. Tās izmanto esošo `/api/events/` un `/api/measurements/`
infrastruktūru un neievieš nekādu rakstīšanu — pat notikumu apstiprināšana
(`acknowledge`) un slēgšana ir apzināti atstātas nākamajiem uzdevumiem.

### Notikumu saraksta lapa: `GET /dashboard/events/`

- Pieejama pa navigācijas saiti **Notikumi**.
- Lapas serveris atveido tikai filtra formu, tabulas šablonu un tukšus
  stāvokļus; rindas tiek ielādētas ar `fetch()` no `/api/events/`.
- Filtri:
  - `status` — atvērts / apstiprināts / slēgts / ignorēts (`EventStatus`);
  - `event_type` — `threshold_anomaly`, `communication_timeout`,
    `device_status`, `validation_error`, `ingestion_error`,
    `simulator_event`, `system`;
  - `severity` — `info`, `warning`, `error`, `critical`;
  - `asset` — aktīva kods vai UUID;
  - `device` — `device_uid` vai UUID;
  - `sensor` — sensora kods vai UUID;
  - `metric` — metrikas atslēga vai UUID;
  - `from` / `to` — ISO 8601 datums un laiks (`Event.detected_at` robežas);
  - `limit` — 1..1000, noklusētais 100.
- Tabula rāda: `event_type`, `severity`, `status`, `title`, `asset_code`,
  `device_uid`, `sensor_code`, `metric_key`, `detected_at`, `closed_at`,
  `source` un saiti uz detail lapu.
- Tukšs stāvoklis: "Nav notikumu, kas atbilst filtra kritērijiem."
- Kļūdas stāvoklis: ielādes kļūda tiek parādīta sarkanā joslā ar
  HTTP statusa kodu, ja API atgriež `4xx` vai `5xx`.

### Notikuma detail lapa: `GET /dashboard/events/<uuid:event_id>/`

- Sākotnējais šablons ielādē tikai notikuma identitāti — pārējais saturs
  nāk no `/api/events/<id>/`.
- Lapā ir sekojoši bloki:
  - **Notikuma identitāte un statuss** — `event_type`, `severity` badge,
    `status` badge, virsraksts, apraksts, `source`, `detected_at`,
    `acknowledged_at`, `closed_at`.
  - **Konteksts** — `site_code`, `asset_code` (kā saite uz
    `/dashboard/assets/{asset_code}/`), `device_uid`, `sensor_code`,
    `metric_key`, `measurement` UUID un `raw_message` UUID, ja pieejami.
  - **Saistītais mērījums** — ja notikumam ir `measurement` FK, no
    `/api/measurements/<id>/` tiek ielādēts laiks, vērtība, vienība,
    kvalitāte, sensora kods, metrikas atslēga un `raw_message` UUID.
  - **Sensora un metrikas timeline** — parādās, ja notikumam ir gan
    `sensor_code`, gan `metric_key`. Apraksts zemāk.
  - **Payload** — JSON, kas formatēts ar atstarpēm un saturīgu treknrakstu,
    bez jebkādiem iekšējiem stack trace.
- Nezināms UUID atgriež HTTP `404`. POST uz `/dashboard/events/<id>/`
  atgriež `405 Method Not Allowed`.

### Sensora un metrikas timeline

- Diagramma ir minimāla inline SVG līniju diagramma (viens
  `polyline` + apļīts pēdējās vērtības marker), kas tiek zīmēta ar to pašu
  `renderSparkline()` palīgu kā aktīva detail lapā.
- Datus zīmē no `/api/measurements/?sensor=<code>&metric=<key>&from=...&to=...&limit=1000`.
  Sensora kods nāk no `event.sensor_code`, metrikas atslēga no
  `event.metric_key`.
- Pieejamas šādas perioda pogas:
  - `1h`, `6h`, `24h`, `7d` — diagramma tiek pārvilkta ap notikuma
    `detected_at` brīdi (logs ir centrēts, bet `to` puse netiek
    projektēta nākotnē tālāk par šobrīd);
  - `Visi` — sūta pieprasījumu bez `from`/`to` (saglabājot tikai
    `limit=1000`), tādējādi parādot visu pieejamo sensoru/metrikas
    vēsturi.
- "Pielāgots" diapazons: divi `datetime-local` ievades lauki + poga
  *"Pielietot"*. Tiklīdz pielietots, aktīvā poga kļūst neaktīva, un
  diagramma tiek pārzīmēta.
- Apakšā tiek parādīts kopsavilkums: pēdējā vērtība un laika zīmogs,
  `min`, `max` un kopējais punktu skaits.
- Tukšs stāvoklis ("Nav mērījumu izvēlētajā periodā.") un kļūdas
  stāvoklis (`"Kļūda ielādējot timeline: ..."`) tiek izgaismoti SVG
  diagrammas vietā.

### Klienta puses kods

Visa loģika atrodas `apps/dashboard/static/dashboard/dashboard.js` (jau
esošajā loaderī). Skripts izvēlas atbilstošo inicializētāju, atkarībā
no klāt esošā JSON konfigurācijas bloka:

- `events-list-config` → `initEventsList(...)`
- `event-detail-config` → `initEventDetail(...)`
- `asset-detail-config` → `initAssetDetail(...)`
- `dashboard-config` → `initOverview(...)`

Esošās pārskata un aktīva detail lapas darbojas bez izmaiņām, jo
loaderis iet caur dispatcheri prioritārā kārtībā.

### Tikai-lasošā daba

Šajā uzdevumā (Phase 7, Task 4A) **netiek** ieviestas šādas darbības:

- notikumu apstiprināšana (`acknowledge`) — nav pogas, nav viewset;
- notikumu manuāla slēgšana (`close`) — nav pogas, nav viewset;
- notikumu rediģēšana — `Event` pārvaldība tiek atstāta Django admin;
- "drag-to-zoom" diagrammā — tikai pogas un manuāli no/līdz lauki;
- masveida atlase un eksports — tikai filtri + 1000-rindu limits.

## Simulatoru darba lapa (Phase 7, Task 4)

Sākot ar Phase 7 Task 4 simulatora vadība un konfigurācija **vairs
neatrodas** uz dashboarda pārskata (`/dashboard/`). Tā tagad ir
atsevišķa darba lapa.

- URL: `GET /dashboard/simulator/`
- Route name: `dashboard:simulator`
- Augšējā navigācijā: ikona/link **Simulators**
  (blakus `Pārskats`, `Aktīvi`, `Notikumi`, `Izveidot jaunu aktīvu`)
- Pieejas kontrole: tā pati `LoginRequiredMixin` kā pārējām dashboarda
  lapām. Lapu redz **visi** autentificētie lietotāji, bet vadības un
  rediģēšanas darbības ir aktīvas tikai tiem, kam ir
  `simulator.can_control_simulator` (vai `is_superuser`).

### Lapas sadaļas

1. **Statusa un vadības panelis** — scenārija/profila kods, aktīvs/
   neaktīvs, pēdējais palaidiens, ziņojumu skaits, **Sākt** / **Apturēt** /
   **Palaist vienu reizi** pogas un tiešraides indikators (tas pats kā
   3A/3B fāzē, tikai uz darba lapas).
2. **Profila izvēle un redaktors** — profila izvēles drop-down,
   *Izveidot jaunu*, lauki (nosaukums, kods, intervāls sekundēs,
   apraksts), metriku konfigurācijas tabula un *Saglabāt profilu*. Sk.
   sadaļu *Simulatora profila redaktors* zemāk.
3. **Tiešraides diagrammas** — viena diagramma uz katru ieslēgto metriku,
   ar Latvian virsrakstu, X asi `Laiks`, Y asi `<Etiķete> (<Mērvienība>)`,
   tooltip un mēģbutonu/atloka zoom režīmu. Sk. sadaļu *Diagrammas*
   zemāk.
4. **MQTT ziņojumu plūsmas tabula** — tiešraides tabula ar laiku,
   profila kodu, aktīva kodu, MQTT topic, metriku kopsavilkumu, payload
   priekšskatījumu, statusu un kļūdu (ja bijusi).

### Simulatora profila redaktors

Profils ir pamata `SimulatorScenario` ieraksts plus tā
`SimulatorScenarioDevice` saistības un katras ierīces
`SimulatorMetricProfile` rindas. Phase 7 Task 4 ietvaros **netika**
pievienoti jauni modeļi — esošā shēma jau pārstāvēja visus vajadzīgos
laukus. Šī iemesla dēļ jaunas migrācijas šajā uzdevumā netika veidotas.

Lietotājs ar `can_control_simulator` var:

- atvērt esošu profilu izvēles sarakstā un to rediģēt;
- nospiest **Izveidot jaunu** un sākt no tukša profila;
- aizpildīt profila vārdu, kodu (`code`), intervālu sekundēs,
  aprakstu un opcionālu *site code*;
- konfigurēt katras metrikas atslēgu (`temperature_c`, `voltage_v`,
  `power_w`, `battery_soc_pct` u.c.), Latvian etiķeti, mērvienību
  (`°C`, `V`, `W`, `%`, `A`, …), `min`, `bāze`, `max`, `noise_amplitude`,
  ieslēgt/izslēgt un sort order;
- nospiest **Saglabāt profilu**, kas izsauc
  `POST /api/simulator/profiles/` (jaunam profilam) vai
  `PATCH /api/simulator/profiles/<code>/` (esošam profilam) ar CSRF un
  sesijas autentifikāciju.

Validācija (gan klienta, gan servera pusē):

- `code` obligāts un unikāls;
- `interval_seconds` ir pozitīvs vesels skaitlis;
- katrai metrikai ir `metric_key` un `unit`;
- `min < max`;
- `bāze ∈ [min, max]`;
- `noise_amplitude ≥ 0`;
- vismaz vienai metrikai jābūt ieslēgtai.

Servera pusē neveiksmes atgriežas kā `400 Bad Request` ar
`field_errors` un latvisku kopsavilkuma paziņojumu, kas redzams
profila redaktorā kā kļūdu kartiņa.

### Diagrammas

Phase 7 Task 4 nepievieno trešās puses charting bibliotēku. Tās vietā
tiek izmantots **iekšējs vienkāršs SVG diagrammas helperis**
(`createSimulatorChart` failā
`apps/dashboard/static/dashboard/dashboard.js`). Šī izvēle ir
tāpēc, ka:

- projekts apzināti izmanto vanilla JS bez Node build pipeline;
- helperis ir mazs, vienā failā, bez ārējām CDN atkarībām un strādā
  produktīvajā Docker vidē, kur ārējais tīkls nav obligāts;
- atbalsta to, ko prasa specifikācija — Latvian virsraksts,
  marķētas asis, mērvienība, tooltip, dzīva punktu pievienošana un
  zooms / laika perioda izvēle ar peli vai pieskaršanos.

**Zoom / laika perioda mijiedarbība:**

- klikšķis un vilkšana pa diagrammu izvēlas X-axis intervālu, kas
  pietuvojas tikai šai diagrammai;
- dubultklikšķis vai poga **Atlikt zoom** atjauno pilnu skatu;
- pieejama poga **Auto-scroll**, kas, ja ieslēgta, automātiski seko
  jaunākajiem WebSocket punktiem;
- katra diagramma neatkarīgi pārvalda savu zoom stāvokli, tā ka
  ieslīpšanās temperatūrā netraucē strāvai vai jaudai.

Ja par konkrētu metriku vēl nav datu, parādās latvisks tukšā stāvokļa
paziņojums **“Nav vēl datu šai metrikai.”** vienkārši tukšā SVG vietā.

### MQTT ziņojumu plūsmas tabula

Tabula uz simulatoru darba lapas attēlo reālus ziņojumus, ko nosūtījis
simulators. Datu avots ir notikums `simulator_mqtt_message_sent`, ko
`apps/simulator/services/control.py` publicē caur
`apps.dashboard.live_updates.publish_simulator_mqtt_message` katram
ciklam (gan reālajai publicēšanai, gan dry-run un publicēšanas
neveiksmes gadījumā).

Notikuma payload:

- `topic` (MQTT tēma);
- saīsināts `payload_preview` (truncēts pārlūkā, lai DOM neaugtu);
- profila/scenārija `code`;
- aktīva `asset_code`/`device_code`;
- timestamp;
- `status` (`ok` / `failed` / `dry_run`);
- `error` (ja statuss `failed`).

Tabula ir **FIFO buferis pārlūkā ar maksimumu 100 rindām**, lai
ilgstoša lapas atvēršana neradītu DOM ekspansiju. Tabula tiek ietīta
ritināmā kastītē (`mqtt-stream-scroll`) ar fiksētu maksimālo augstumu;
ja jaunas rindas pārpilda redzamo apgabalu, kastītē parādās ritjosla,
un tabulas galva ir „lipīga” (sticky), lai kolonnu nosaukumi paliek
redzami, ritinot. Atverot lapu pirmo reizi, tabula sākotnēji ir tukša
un piepildās ar tiešraides notikumiem; tas ir apzināts ierobežojums,
jo simulatora ziņojumi patlaban netiek atsevišķi serializēti par
sākotnējo backfill atbildi šim galapunktam.

### Atļaujas un CSRF

Tā pati uzvedība, ko apraksta Phase 7 Task 3B sadaļa zemāk, attiecas
arī uz darba lapu:

- `simulator.can_control_simulator` (vai `is_superuser=True`) ir
  vajadzīgs, lai aktivizētu **Sākt**, **Apturēt**, **Palaist vienu
  reizi** pogas, **Saglabāt profilu** un metrikas rediģēšanas laukus;
- bez šīs atļaujas pogas un lauki ir vizuāli atspējoti
  (`disabled`, `aria-disabled="true"`), un parādās latvisks paziņojums
  **“Jums nav tiesību vadīt simulatoru.”** / *“Lai vadītu simulatoru,
  lietotājam jābūt pierakstītam sistēmā.”*;
- visas POST/PATCH darbības pievieno `X-CSRFToken` no
  `simulator_config` JSON bloka un `credentials: "same-origin"`.

### Lai grafiki un MQTT plūsma faktiski atjauninātos

> **Uzmanību.** Pogas **Sākt** / **Apturēt** tikai pārslēdz
> `SimulatorScenario.is_active` datubāzē — tās **NEPALAIŽ** periodisko
> ziņojumu emisiju pašā web procesā. Lai grafiki un MQTT plūsma
> regulāri atjauninātos (interval seconds), papildus jādarbojas
> simulatora servisam.

`docker-compose.local.yml` (un `docker-compose.prod.yml`) iekļauj
atsevišķu **`simulator`** servisu, kas palaiž
`python manage.py run_simulator --duration-seconds 86400 --sleep-seconds 5`
ar Bash retry-cilpu. Šis process:

1. Pēc katra cikla pārlasa `is_active` no datubāzes — nospiežot
   **Apturēt** uz dashboarda, nākamais cikls tiek izlaists; nospiežot
   **Sākt** atkal, emisija atsākas bez konteinera restarta.
2. Pēc katra cikla publicē `simulator_mqtt_message_sent` notikumu, ko
   `/dashboard/simulator/` lapa saņem caur WebSocket un izmanto, lai
   pievienotu rindu MQTT plūsmas tabulai un punktu katrā ieslēgtajā
   grafikā.
3. Pēc katra cikla atjauno `last_run_at`, tāpēc “Pēdējais palaidiens”
   UI vērtība paliek aktuāla.

Lai palaistu vai apturētu šo servisu:

```bash
# palaist
docker compose -f docker-compose.local.yml up -d simulator

# pārliecināties, vai darbojas
docker compose -f docker-compose.local.yml ps simulator

# apturēt (UI Sākt/Apturēt nestrādās bez šī servisa)
docker compose -f docker-compose.local.yml stop simulator
```

Bez šī servisa darba lapa joprojām strādā (statusa kartīte, profila
redaktors, **Palaist vienu reizi** poga), bet `Tiešraides grafiki`
un `MQTT ziņojumu plūsma` paliek tukši, līdz lietotājs nospiež
**Palaist vienu reizi** vai kāds cits process publicē MQTT ziņojumus
ar simulatora topic struktūru.

### WebSocket fallback

Lapa atver `ws://<host>/ws/dashboard/simulator/`
(route name: `ws-dashboard-simulator`). Šis WebSocket abonē gan
`SIMULATOR_GROUP`, gan `OVERVIEW_GROUP`, lai diagrammas un MQTT plūsma
atjauninātos no `simulator_mqtt_message_sent`,
`simulator_run_completed`, `simulator_status_changed`,
`telemetry_received`, `raw_message_received`, `asset_state_updated`,
`anomaly_created` notikumiem.

Ja `WebSocket` API nav pieejams vai pieslēgums tiek pārtraukts:

- tiešraides indikators rāda **Tiešraide atvienota** vai **Tiešraide
  atspējota**;
- profilu saraksts un statusa kartīte joprojām tiek atjaunoti caur
  REST polling fallback;
- diagrammas paliek interaktīvas (zoom, tooltip), bet nesaņem jaunus
  punktus; **Palaist vienu reizi** poga turpina darboties — pēc
  REST atbildes lapa pati pievienos jauno mērījumu.

### Manuāla verifikācija

Pieņemot, ka demo dati ielādēti (`python manage.py seed_demo_data`):

1. `GET /dashboard/` atgriež 200; pārskats vairs **neattēlo**
   simulatora paneli, simulatora pogas, simulatora palaidienu tabulu
   un “Pēdējais simulators” karti.
2. Augšējā navigācijā ir saite **Simulators**.
3. `GET /dashboard/simulator/` atgriež 200 un parāda statusu, profila
   redaktoru, diagrammu režģi un MQTT plūsmas tabulu.
4. Lietotājs ar `can_control_simulator` var:
   - izveidot/labot profilu ar metrikām `temperature_c` (°C),
     `voltage_v` (V), `power_w` (W), `battery_soc_pct` (%);
   - iestatīt intervālu sekundēs;
   - nospiest **Sākt**, **Apturēt** un **Palaist vienu reizi**;
   - redzēt jaunu punktu diagrammās un jaunu rindu MQTT tabulā pēc
     **Palaist vienu reizi** (caur WebSocket).
5. Lietotājs bez atļaujas redz lapu, bet pogas un metriku rediģēšana ir
   atspējotas.
6. `GET /dashboard/assets/charger-001/` un `GET /dashboard/assets/<uuid>/`
   joprojām strādā.
7. `GET /dashboard/assets/does-not-exist/` atgriež 200 un dod JS rīcību
   parādīt “Aktīvs nav atrasts” stāvokli.

## Simulatora vadības panelis un tiešraides atjauninājumi (Phase 7, Task 3A + 3B)

> **Piezīme (Phase 7 Task 4):** šī sadaļa apraksta *vēsturisko* paneli,
> kas Phase 7 Task 3A/3B laikā atradās uz dashboarda pārskata. Sākot ar
> Phase 7 Task 4 panelis ir **pārvietots** uz atsevišķo
> `/dashboard/simulator/` darba lapu (sk. sadaļu *Simulatoru darba lapa*
> augstāk). Vadības galapunkti, tiešraides indikatora uzvedība un CSRF
> apstrāde paliek nemainīga.

Pārskata lapas apakšā, simulatora sadaļā, ir **simulatora vadības panelis** ar trīs
pogām un tiešraides statusa indikatoru:

- **Sākt** — izsauc `POST /api/simulator/start/`. Tas iezīmē izvēlēto scenāriju kā
  aktīvu (`is_active = True`) datubāzē. Pati ģenerēšana **netiek** uzsākta web
  procesā — to dara atsevišķa `python manage.py run_simulator …` cron komanda.
- **Apturēt** — izsauc `POST /api/simulator/stop/`. Iezīmē scenāriju kā neaktīvu.
- **Palaist vienu reizi** — izsauc `POST /api/simulator/run-once/`. Sinhroni
  izpilda **vienu** ciklu (vienu telemetrijas ziņojumu uz katru aktīvo
  `SimulatorScenarioDevice`) un atgriež rezultātu. Pēc tam pārskats automātiski
  pieprasa atjauninātos datus, lai jaunais mērījums ir uzreiz redzams.

### Atļaujas un autentifikācija (Phase 7, Task 3B)

Visas trīs vadības darbības (Sākt / Apturēt / Palaist vienu reizi) tagad prasa:

1. autentificētu Django sesiju, **un**
2. atļauju `simulator.can_control_simulator` **vai** `is_superuser=True`.

`GET /api/simulator/status/` atbilstoši paliek pieejams visiem klientiem
(arī anonīmiem), lai panelis varētu pareizi attēlot, kāpēc pogas ir atspējotas.
Atbildē tagad ir lauks `can_control` (`true` / `false`) un `is_authenticated`,
ko dashboarda JS izmanto, lai izvēlētos pareizo paziņojumu un pogu stāvokli.

**UI uzvedība**, kad lietotājam nav vadības tiesību:

- pogas **Sākt**, **Apturēt**, **Palaist vienu reizi** ir vizuāli atspējotas
  (`disabled`, `aria-disabled="true"`) un tām ir `title` ar latvisku
  paskaidrojumu;
- zem pogām parādās latvisks paziņojums:
  - autentificētam, bet bez atļaujas: **“Jums nav tiesību vadīt simulatoru.”**;
  - anonīmam (teorētiski — pārskata lapu reāli aizsargā `LoginRequiredMixin`,
    bet API atbilde to apkalpotu): **“Lai vadītu simulatoru, lietotājam jābūt
    pierakstītam sistēmā.”**;
- statusa pills, scenārija kods, pēdējais palaidiens, ziņojumu skaits un
  tiešraides indikators paliek redzami;
- WebSocket pieslēgums un periodiskais polling (kā fallback) turpina darboties
  bez izmaiņām.

**Kā piešķirt atļauju.**

- *Django admin*: lietotāja vai grupas formā sadaļā **User permissions** /
  **Group permissions** atrodi `simulator | simulator scenario | Var vadīt
  simulatoru` un saglabā.
- *Django shell* lokālai testēšanai:

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
  ```

- *Superusers* (`createsuperuser`) iet apkārt atļaujas pārbaudei un drīkst
  vadīt simulatoru jebkurā gadījumā.

### CSRF un POST pieprasījumi

Tā kā vadības galapunkti tagad strādā caur `SessionAuthentication`, Django
piemēro CSRF aizsardzību. Dashboarda JS:

- nolasa `csrfToken` no servera puses ielādēta `dashboard_config` JSON bloka;
- ja konfigurācijā tā nav (piem., aizpildīta sesija), izmanto `csrftoken`
  cookie kā rezervi;
- katram POST pieprasījumam pievieno galveni `X-CSRFToken: <token>` un
  `credentials: "same-origin"`.

Ārējiem CLI klientiem (piem., `curl`) jāautentificējas (sesijas cookie ar
`/admin/login/` vai cita projekta autentifikācijas plūsma) un jāpievieno
`X-CSRFToken` galvene, kas atbilst `csrftoken` cookie. CSRF nav globāli
atspējots un nav atspējots tieši simulatora galapunktiem.

Panelis rāda:

- pašreizējo statusa simbolu (Aktīvs / Apturēts / Nav scenārija);
- scenārija kodu;
- pēdējā palaidiena timestamp;
- ziņojumu skaitu pēdējā ciklā;
- tiešraides statusa indikatoru (sk. zemāk);
- pēdējo backenda atbildes paziņojumu (latviešu valodā).

Pogas pārbauda atbildi un parāda kompaktu sarkanu vai zilu ziņojumu
`simulator-feedback` zonā. Pogas tiek deaktivizētas (un pārveidotas par
"Strādā…"), kamēr darbība tiek izpildīta.

### Tiešraide caur WebSocket (Django Channels)

Pārskata un detail lapa atver WebSocket pieslēgumu:

- pārskats: `ws://<host>/ws/dashboard/`;
- detail lapa: `ws://<host>/ws/dashboard/assets/<id-vai-kods>/`.

Backenda servisu slānis (MQTT ingestion, analītika, simulatora vadība) caur
`apps/dashboard/live_updates.py` raida nelielas notikumu ziņas (`event_type`,
`asset_code`, `ts`). Lapa, saņemot ziņu, atjaunina tikai attiecīgo sadaļu —
piemēram, `simulator_status_changed` atjaunina simulatora paneli, bet
`telemetry_received` atjaunina pārskata kartiņas, aktīvu tabulu un
telemetrijas sadaļu.

Atbalstītie `event_type`:

- `simulator_status_changed`
- `telemetry_received`
- `asset_state_updated`
- `anomaly_created`
- `raw_message_received`

### Tiešraides statusa indikators

Indikators rāda vienu no četriem stāvokļiem latviešu valodā:

- **Tiešraide pieslēgta** — WebSocket ir atvērts, lapa galvenokārt atjauninās ar notikumiem;
- **Mēģina pieslēgties** — sākotnējais vai atkārtotais pieslēgums;
- **Tiešraide atvienota** — pieslēgums zudis, lapa pārslēgusies uz periodisku
  atjaunošanu;
- **Izmanto periodisku atjaunošanu** — fallback, kad WebSocket nav pieejams.

Kad WebSocket ir veiksmīgi pieslēgts, polling intervāls tiek pagarināts no
30 s līdz 120 s (lapa kļūst notikumu vadīta, bet self-heal saglabājas).
Kad pieslēgums zūd, polling atgriežas pie agresīvākā 30 s režīma. Pieslēguma
atjaunošana izmanto eksponenciālu backoff (1 → 30 sekunžu maksimums).

### Ja Channels / WebSocket nav pieejams

Lapa paliek pilnīgi lietojama bez WebSocket. JavaScript:

- pirmajā mēģinājumā parāda **Mēģina pieslēgties**;
- ja `WebSocket` API nav (piem., kāda noslēgta vide), parāda **Tiešraide atspējota**;
- joprojām ielādē sākotnējos datus caur API `fetch`;
- saglabā 30 s polling kā fallback, ja `Auto 30 s` slēdzis ir ieslēgts.

## Kas šajā uzdevumā **nav** ieviests

Šie elementi apzināti paliek nākamajiem uzdevumiem:

- pieteikšanās lapas, reģistrācija, paroles atjaunošana, pielāgots `User`
  modelis, vairākklientu (multi-tenant) atbalsts vai jauns lomu pārvaldības UI —
  Phase 7, Task 3B izmanto Django esošo autentifikāciju un atļauju modeli;
- rakstāmi REST API endpointi ārpus simulatora vadības — pārējais raksts notiek
  tikai caur server-side rendered Django formām;
- vairāku sensoru pievienošana vienlaikus aktīva izveides formā — vienā plūsmā
  atbalstīts viens sensors;
- pilna payload `RawMessage` skatīšana detail lapā — pieejama caur
  `/api/raw-messages/{id}/`;
- papildu metriku diagrammas (piem., `current_a`) — pievienojams nākotnē,
  papildinot `ASSET_DETAIL_CHART_METRICS` `apps/dashboard/views.py`;
- notikumu apstiprināšana / slēgšana / komentāri (Phase 7, Task 4A — apzināti
  tikai lasīšana).

## Manuāla verifikācija

### Pārbaudīt `/dashboard/` un detail lapu no Django Test Client

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='localhost')
for path in ['/dashboard/', '/dashboard/assets/charger-001/']:
    r = c.get(path)
    print(path, r.status_code, 'SMT Digital Solution' in r.content.decode())
"
```

Sagaidāmais izvads:

```
/dashboard/ 200 True
/dashboard/assets/charger-001/ 200 True
```

### Pārbaudīt no resursdatora

Ja `web` ir uz `http://localhost:8000`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/dashboard/
curl -s http://localhost:8000/dashboard/health/
```

Sagaidāmais izvads:

```
200
ok
```

### Pārbaudīt UI pārlūkprogrammā

#### Pārskata lapa

Atveriet `http://localhost:8000/dashboard/`. Sagaidāmais skats:

- lapa ielādējas bez servera kļūdas;
- redzamas piecas sadaļas (pārskata kartiņas, aktīvu tabula, notikumi, telemetrija, simulators);
- pēc dažām sekundēm sadaļas pāriet no “Ielādē…” uz reāliem datiem;
- aktīvu tabulas kolonnā **Detaļas** ir saite "Atvērt" — klikšķis aizved uz `/dashboard/assets/{kods}/`;
- **Atsvaidzināt** poga atkārtoti ielādē visas sadaļas;
- pārlūka konsole nerāda kritiskas JavaScript kļūdas;
- ja kāds API galapunkts atbild ar kļūdu, attiecīgā sadaļa parāda lasāmu paziņojumu, neapstājot pārējo lapu.

#### Aktīva detail lapa

Atveriet `http://localhost:8000/dashboard/assets/charger-001/`. Sagaidāmais skats:

- redzams **← Atpakaļ uz pārskatu** links lapas augšā;
- aktīva identitātes kartiņas rāda kodu, nosaukumu, statusu utt.;
- digitālā dvīņa state cards rāda T, U, I, P, SoC, anomāliju skaitu;
- četras SVG diagrammas (`temperature_c`, `voltage_v`, `power_w`, `battery_soc_pct`) parādās; ja konkrētai metrikai nav datu — kartiņa saka "Nav datu.";
- pēdējo mērījumu un notikumu tabulas pildās;
- `Pēdējais MQTT ziņojums` panelis rāda `message_id`, `processing_status`, `received_at`, `topic`;
- nezināms kods (piem., `/dashboard/assets/does-not-exist/`) atver lapu, bet rāda sarkanu paziņojumu **"Aktīvs ‘does-not-exist’ netika atrasts."** ar saiti atpakaļ uz pārskatu;
- **Atsvaidzināt** atkārtoti ielādē kopsavilkumu, mērījumus, notikumus un visas četras diagrammas paralēli.

#### Simulatora vadības panelis un tiešraide

Atveriet `http://localhost:8000/dashboard/`. Sagaidāmais skats:

- simulatora sadaļā ir redzams panelis ar pogām **Sākt**, **Apturēt**, **Palaist vienu reizi**;
- tiešraides indikators sākumā rāda **Mēģina pieslēgties**, pēc neilga brīža **Tiešraide pieslēgta**;
- klikšķis uz **Sākt** maina indikatoru uz "Aktīvs" un ziņojuma laukā parādās "Simulators palaists scenārijam 'default_demo'.";
- klikšķis uz **Apturēt** maina indikatoru uz "Apturēts";
- klikšķis uz **Palaist vienu reizi** veic vienu MQTT publikāciju (vai ja
  mqtt_worker arī ir palaists, jaunais mērījums ātri parādās pārskata
  telemetrijas sadaļā un aktīva detail lapā **bez** 30 s polling gaidīšanas);
- ja Mosquitto nav sasniedzams, "Palaist vienu reizi" atgriež `ok=false` un
  paneļa zonā parādās lasāms latviešu kļūdas paziņojums; pati datubāze paliek
  konsekventā stāvoklī (`SimulatorRun` tiek atzīmēts kā `failed`);
- ja izslēdz Redis vai apstādina `daphne`, indikators pāriet uz **Tiešraide
  atvienota** un lapa turpina darboties ar 30 s polling.

#### Simulatora atļauju pārbaude (Phase 7, Task 3B)

1. Izveidojiet divus testa lietotājus, vienam piešķiriet
   `simulator.can_control_simulator`:

   ```bash
   docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
   from django.contrib.auth import get_user_model
   from django.contrib.auth.models import Permission
   U = get_user_model()
   viewer, _ = U.objects.get_or_create(username='viewer')
   viewer.set_password('demo'); viewer.save()
   ctrl, _ = U.objects.get_or_create(username='controller')
   ctrl.set_password('demo'); ctrl.save()
   p = Permission.objects.get(content_type__app_label='simulator', codename='can_control_simulator')
   ctrl.user_permissions.add(p)
   print('viewer/demo (no perm), controller/demo (with perm)')
   "
   ```
2. Pierakstieties kā `viewer` → `/dashboard/` rāda simulatora paneli, bet:
   - **Sākt**, **Apturēt**, **Palaist vienu reizi** ir atspējotas;
   - zem pogām redzams paziņojums “Jums nav tiesību vadīt simulatoru.”
3. Pierakstieties kā `controller` (vai `createsuperuser`) → tās pašas pogas
   ir aktīvas; klikšķis uz **Sākt**, **Apturēt** un **Palaist vienu reizi**
   strādā kā līdz šim, un atbilde ir veiksmīga (`ok=true`).
4. Atvērstā tabā pārbaudiet `Network` paneli — POST pieprasījumam ir
   `X-CSRFToken` galvene un `Cookie: csrftoken=…`. Atbilde ir 200.
