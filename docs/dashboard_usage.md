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

## Kas šajā uzdevumā **nav** ieviests

Šis uzdevums apzināti ir ierobežots dashboard "shell" un pārskata lapas līmenī. Šie elementi paliek nākamajiem uzdevumiem:

- pilnas aktīva detail lapas (`/dashboard/assets/<code>/`);
- diagrammas (līniju diagrammas mērījumiem, joslu diagrammas notikumiem);
- WebSocket / Django Channels reāllaika atjauninājumi — pašlaik datu atsvaidzināšana ir tikai manuāla vai 30 s polls;
- simulatora vadības pogas (`start`/`stop`) — tas joprojām notiek caur `python manage.py run_simulator ...`;
- rakstīšanas darbības no dashboard — visi backend darījumi notiek caur Django administrāciju, simulatoru, MQTT ingestion vai management komandām;
- lietotāju lomu pārvaldība un konkrētas atļaujas dashboard lapām;
- vairākvalodu UI — pašlaik UI virsraksti ir latviešu valodā, jo dokumentācija arī ir latviski.

## Manuāla verifikācija

### Pārbaudīt `/dashboard/` no Django Test Client

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='localhost')
r = c.get('/dashboard/')
print('status:', r.status_code)
print('contains title:', 'SMT Digital Solution' in r.content.decode())
print('contains refresh:', 'data-role=\"refresh-btn\"' in r.content.decode())
print('contains overview API:', '/api/overview/' in r.content.decode())
"
```

Sagaidāmais izvads:

```
status: 200
contains title: True
contains refresh: True
contains overview API: True
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

Atveriet `http://localhost:8000/dashboard/`. Sagaidāmais skats:

- lapa ielādējas bez servera kļūdas;
- redzamas piecas sadaļas (pārskata kartiņas, aktīvu tabula, notikumi, telemetrija, simulators);
- pēc dažām sekundēm sadaļas pāriet no “Ielādē…” uz reāliem datiem;
- **Atsvaidzināt** poga atkārtoti ielādē visas sadaļas;
- pārlūka konsole nerāda kritiskas JavaScript kļūdas;
- ja kāds API galapunkts atbild ar kļūdu, attiecīgā sadaļa parāda lasāmu paziņojumu, neapstājot pārējo lapu.
