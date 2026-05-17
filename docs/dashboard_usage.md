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

- `apps/dashboard/views.py` — `OverviewView` (TemplateView) un `health_view`;
- `apps/dashboard/urls.py` — `/dashboard/` un `/dashboard/health/`;
- `apps/dashboard/templates/dashboard/base.html` — galvenes/footera šablons;
- `apps/dashboard/templates/dashboard/overview.html` — pārskata lapa;
- `apps/dashboard/static/dashboard/dashboard.css` — minimālais stils;
- `apps/dashboard/static/dashboard/dashboard.js` — datu ielādes un atveidošanas loģika;
- `apps/dashboard/tests.py` — Django šablonu un maršrutu testi.

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
- **Pēdējie mērījumi** — tabula ar metriku, vērtību, vienību, laiku, kvalitāti;
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

## Kas šajā uzdevumā **nav** ieviests

Šie elementi apzināti paliek nākamajiem uzdevumiem:

- WebSocket / Django Channels reāllaika atjauninājumi — datu atsvaidzināšana ir tikai manuāla vai 30 s polls;
- simulatora vadības pogas (`start`/`stop`) — tas joprojām notiek caur `python manage.py run_simulator ...`;
- rakstīšanas darbības no dashboard — visi backend darījumi notiek caur Django administrāciju, simulatoru, MQTT ingestion vai management komandām;
- lietotāju lomu pārvaldība un konkrētas atļaujas dashboard lapām;
- vairākvalodu UI — pašlaik UI virsraksti ir latviešu valodā, jo dokumentācija arī ir latviski;
- pilna payload `RawMessage` skatīšana detail lapā — pieejama caur `/api/raw-messages/{id}/`;
- papildu metriku diagrammas (piem., `current_a`) — pievienojams nākotnē, papildinot `ASSET_DETAIL_CHART_METRICS` `apps/dashboard/views.py`.

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
