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
- **Mērījumu diagrammas** — vienkāršas inline SVG līniju diagrammas četrām metrikām: `temperature_c`, `voltage_v`, `power_w`, `battery_soc_pct`. Katra diagramma rāda pēdējos līdz 100 mērījumus, jaunāko vērtību ar laiku, un min/max diapazonu apakšā;
- **Pēdējie mērījumi** — tabula ar metriku, **sensoru** (`sensor_code`), vērtību, vienību, laiku, kvalitāti;
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

## Kas šajā uzdevumā **nav** ieviests

Šie elementi apzināti paliek nākamajiem uzdevumiem:

- WebSocket / Django Channels reāllaika atjauninājumi — datu atsvaidzināšana ir tikai manuāla vai 30 s polls;
- simulatora vadības pogas (`start`/`stop`) — tas joprojām notiek caur `python manage.py run_simulator ...`;
- rakstāmi REST API endpointi — viss raksts notiek tikai caur server-side rendered Django formām;
- vairāku sensoru pievienošana vienlaikus aktīva izveides formā — vienā plūsmā atbalstīts viens sensors;
- lietotāju lomu pārvaldība un konkrētas atļaujas dashboard lapām — visi pieslēgti lietotāji redz vienu un to pašu izvēlni;
- vairākvalodu UI — pašlaik UI virsraksti ir latviešu valodā, jo dokumentācija arī ir latviski;
- pilna payload `RawMessage` skatīšana detail lapā — pieejama caur `/api/raw-messages/{id}/`;
- papildu metriku diagrammas (piem., `current_a`) — pievienojams nākotnē, papildinot `ASSET_DETAIL_CHART_METRICS` `apps/dashboard/views.py`;
- notikumu apstiprināšana / slēgšana / komentāri (Phase 7, Task 4A — apzināti tikai lasīšana).

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
