# SMT IoT projekta palaišanas instrukcija ar Docker

## 1. Projekta konteksts

Šis dokuments apraksta pamata komandas, kas izmantojamas `smt_iot` projekta palaišanai ar Docker. Projekts ir Django balstīts IoT infrastruktūras monitoringa un digitālā dvīņa prototips, kurā lokālajā izstrādes vidē tiek izmantots Docker Compose. Sistēmā parasti darbojas Django web aplikācija, datubāze, Mosquitto MQTT brokeris, Redis un atsevišķi fona procesi, piemēram, MQTT datu uzņemšanas worker, simulatora process vai analītikas process.

Šajā projektā nav standarta `docker-compose.yml` faila nosaukuma. Tā vietā ir izmantoti atsevišķi Compose konfigurācijas faili lokālajai un produkcijas videi:

```bash
docker-compose.local.yml
docker-compose.prod.yml
```

Tādēļ komanda `docker compose up -d` viena pati šajā projektā nestrādā, jo Docker Compose pēc noklusējuma meklē failu ar standarta nosaukumu, piemēram, `compose.yml`, `compose.yaml`, `docker-compose.yml` vai `docker-compose.yaml`.

## 2. Pāriešana uz projekta mapi

Pirms Docker komandu izpildes jāatrodas projekta pamata mapē. Šajā projektā mapes nosaukums ir `smt_iot`.

Ja terminālis atrodas mapē, kurā atrodas projekts, jāizpilda:

```bash
cd smt_iot
```

Var pārbaudīt, vai atrodaties pareizajā mapē, apskatot failu sarakstu:

```bash
ls
```

Mapē vajadzētu būt redzamam vismaz vienam no šiem failiem:

```bash
docker-compose.local.yml
docker-compose.prod.yml
```

## 3. Docker Desktop palaišana Mac datorā

Ja, mēģinot palaist projektu, tiek parādīta kļūda:

```bash
Cannot connect to the Docker daemon at unix:///Users/aivarsrubenis/.docker/run/docker.sock.
Is the docker daemon running?
```

tas nozīmē, ka Docker komanda terminālī ir pieejama, bet Docker dzinējs jeb Docker daemon nav palaists. Mac vidē tas visbiežāk nozīmē, ka nav palaists Docker Desktop.

Docker Desktop var palaist grafiski no Applications mapes vai ar komandu:

```bash
open -a Docker
```

Pēc šīs komandas jāuzgaida, līdz Docker Desktop pilnībā ielādējas. Docker ikonai augšējā izvēlnes joslā jābūt aktīvai, un Docker Desktop jānorāda, ka Docker Engine darbojas.

Docker darbību var pārbaudīt ar komandu:

```bash
docker info
```

Ja Docker darbojas korekti, komanda parādīs informāciju par Docker serveri, konteineriem, image failiem un konfigurāciju. Ja Docker vēl nav palaists, tiks parādīta kļūda par nespēju pieslēgties Docker daemon.

Papildu pārbaudei var izmantot:

```bash
docker version
```

Ja viss ir kārtībā, rezultātā būs redzama gan `Client`, gan `Server` sadaļa. Ja redzama tikai `Client` sadaļa un kļūda par daemon, Docker Engine vēl nedarbojas.

## 4. Lokālās vides palaišana

Tā kā lokālajai videi tiek izmantots fails `docker-compose.local.yml`, projekts jāpalaiž ar `-f` parametru.

Pamata palaišanas komanda ir:

```bash
docker compose -f docker-compose.local.yml up -d
```

Ja nepieciešams pārbūvēt Docker image failus, jāizmanto:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Šī komanda palaiž konteinerus fonā. Parametrs `-d` nozīmē detached mode, tātad terminālis pēc konteineru palaišanas netiek piesaistīts to logu izvadei.

## 5. Konteineru statusa pārbaude

Pēc palaišanas jāpārbauda, vai visi servisi darbojas:

```bash
docker compose -f docker-compose.local.yml ps
```

Šī komanda parāda konteineru statusu. Darbojošiem servisiem vajadzētu būt statusā `running` vai līdzīgā aktīvā stāvoklī.

Lai redzētu, kādi servisi ir definēti Compose failā, var izmantot:

```bash
docker compose -f docker-compose.local.yml config --services
```

Šī komanda ir noderīga, ja nav skaidrs, kā precīzi saucas servisi. Piemēram, Django serviss var saukties `web`, bet tas var būt nosaukts arī citādi atkarībā no konkrētā Compose faila.

## 6. Logu skatīšana

Visu servisu logus var skatīties ar komandu:

```bash
docker compose -f docker-compose.local.yml logs -f
```

Ja jāskatās konkrēta servisa logi, komandas beigās jānorāda servisa nosaukums. Piemēram, ja Django serviss saucas `web`, tā logus var skatīties šādi:

```bash
docker compose -f docker-compose.local.yml logs -f web
```

MQTT brokera logus var skatīties šādi, ja serviss saucas `mqtt`:

```bash
docker compose -f docker-compose.local.yml logs -f mqtt
```

MQTT worker logus var skatīties šādi, ja serviss saucas `mqtt_worker`:

```bash
docker compose -f docker-compose.local.yml logs -f mqtt_worker
```

Logu skatīšanu var pārtraukt ar `Ctrl + C`. Tas neaptur konteinerus, bet tikai pārtrauc logu skatīšanos terminālī.

## 7. Django migrācijas

Pēc pirmās palaišanas vai pēc datu modeļu izmaiņām jāizpilda Django migrācijas. Ja Django serviss Compose failā saucas `web`, komanda ir:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py migrate
```

Ja ir izveidotas jaunas Django modeļu izmaiņas un nepieciešams ģenerēt migrācijas, izmanto:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py makemigrations
docker compose -f docker-compose.local.yml exec web python manage.py migrate
```

## 8. Django administratora lietotāja izveide

Lai piekļūtu Django administrācijas videi, jāizveido superuser lietotājs:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py createsuperuser
```

Komanda pieprasīs ievadīt lietotājvārdu, e-pasta adresi un paroli. Paroles ievades laikā terminālī rakstzīmes var netikt attēlotas. Tas ir normāli.

## 9. Django konfigurācijas pārbaude

Django projekta konfigurāciju var pārbaudīt ar:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py check
```

Ja konfigurācija ir korekta, komandai jābeidzas bez kļūdām.

## 10. Django shell palaišana

Ja nepieciešams manuāli pārbaudīt modeļus vai datubāzes ierakstus, var palaist Django shell:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py shell
```

No shell var iziet ar:

```python
exit()
```

## 11. Simulatora palaišana

Ja projektā ir izveidota simulatora management command komanda `run_simulator`, vienreizēju simulatora izpildi var palaist šādi:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --once
```

Šī komanda ir paredzēta, lai publicētu vienu simulatora datu soli MQTT brokerī. Pēc tam MQTT worker vajadzētu šo ziņojumu apstrādāt un saglabāt datubāzē.

Ja nepieciešams palaist simulatoru ilgākai demonstrācijai, var izmantot:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --duration-minutes 60
```

Ja Compose failā simulatoram ir atsevišķs serviss, piemēram, `simulator_cron_job`, to var palaist šādi:

```bash
docker compose -f docker-compose.local.yml up -d simulator_cron_job
```

Tā logus var skatīties ar:

```bash
docker compose -f docker-compose.local.yml logs -f simulator_cron_job
```

## 12. MQTT worker palaišana

Šajā projektā MQTT datu uzņemšana ir atdalīta no Django web procesa. Ja Compose failā ir atsevišķs `mqtt_worker` serviss, to var palaist šādi:

```bash
docker compose -f docker-compose.local.yml up -d mqtt_worker
```

Worker logus var skatīties ar:

```bash
docker compose -f docker-compose.local.yml logs -f mqtt_worker
```

Ja dati no simulatora nenonāk datubāzē, jāpārbauda vispirms Mosquitto brokeris un pēc tam MQTT worker logi.

## 13. Projekta apturēšana

Lokālo Docker vidi var apturēt ar:

```bash
docker compose -f docker-compose.local.yml down
```

Šī komanda aptur un noņem konteinerus, bet parasti saglabā Docker volumes, kuros atrodas datubāzes dati.

Ja nepieciešams apturēt projektu, bet nezaudēt datus, jāizmanto tieši šī komanda, nevis `down -v`.

## 14. Pilnīga lokālās vides dzēšana

Ja nepieciešams pilnībā notīrīt lokālo vidi, ieskaitot datubāzes volume, var izmantot:

```bash
docker compose -f docker-compose.local.yml down -v
```

Šī komanda jālieto uzmanīgi, jo tā izdzēš arī lokāli saglabātos datubāzes datus.

Pēc pilnīgas notīrīšanas vidi var palaist no jauna:

```bash
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml exec web python manage.py migrate
docker compose -f docker-compose.local.yml exec web python manage.py createsuperuser
```

## 15. Projekta pārstartēšana

Ja nepieciešams pārstartēt visus servisus, var izmantot:

```bash
docker compose -f docker-compose.local.yml restart
```

Ja jāpārstartē tikai Django web serviss:

```bash
docker compose -f docker-compose.local.yml restart web
```

Ja jāpārstartē tikai MQTT worker:

```bash
docker compose -f docker-compose.local.yml restart mqtt_worker
```

## 16. Koda izmaiņu gadījumā

Ja mainīts tikai Python kods un Docker image nav jāpārbūvē, bieži pietiek ar Django web servisa pārstartēšanu:

```bash
docker compose -f docker-compose.local.yml restart web
```

Ja mainīts `requirements.txt`, `Dockerfile` vai citas Docker image būvēšanai būtiskas lietas, jāpalaiž:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Ja nepieciešams pārbūvēt tikai konkrētu servisu, piemēram, `web`, var izmantot:

```bash
docker compose -f docker-compose.local.yml build web
docker compose -f docker-compose.local.yml up -d web
```

## 17. Produkcijas konfigurācija

Produkcijas videi paredzēts atsevišķs Compose fails:

```bash
docker-compose.prod.yml
```

Produkcijas vidi var palaist ar:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Ja nepieciešama pārbūve:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Lokālai izstrādei parasti jāizmanto tikai `docker-compose.local.yml`.

## 18. Ērtāks alias ikdienas darbam

Lai katru reizi nebūtu jāraksta garā komanda ar `-f docker-compose.local.yml`, var izveidot termināļa alias.

Pašreizējai termināļa sesijai:

```bash
alias dc='docker compose -f docker-compose.local.yml'
```

Pēc tam komandas var rakstīt īsāk:

```bash
dc up -d
dc ps
dc logs -f web
dc exec web python manage.py migrate
```

Lai alias saglabātos arī pēc termināļa aizvēršanas, to var pievienot `~/.zshrc` failam:

```bash
echo "alias dc='docker compose -f docker-compose.local.yml'" >> ~/.zshrc
source ~/.zshrc
```

Pēc tam, atrodoties `smt_iot` projekta mapē, var izmantot saīsināto `dc` komandu.

## 19. Biežākās kļūdas un to novēršana

### 19.1. Kļūda: no configuration file provided

Ja tiek parādīta kļūda:

```bash
no configuration file provided: not found
```

tas nozīmē, ka palaista komanda:

```bash
docker compose up -d
```

bet projektā nav standarta Compose faila nosaukuma. Pareizā komanda šim projektam ir:

```bash
docker compose -f docker-compose.local.yml up -d
```

### 19.2. Kļūda: Cannot connect to the Docker daemon

Ja tiek parādīta kļūda:

```bash
Cannot connect to the Docker daemon at unix:///Users/aivarsrubenis/.docker/run/docker.sock.
Is the docker daemon running?
```

tas nozīmē, ka Docker Desktop nav palaists vai Docker Engine vēl nav pilnībā startējis.

Risinājums Mac vidē:

```bash
open -a Docker
```

Pēc tam jāpārbauda:

```bash
docker info
```

Kad `docker info` darbojas bez kļūdas, var palaist projektu:

```bash
docker compose -f docker-compose.local.yml up -d
```

### 19.3. Docker Desktop ir palaists, bet kļūda paliek

Ja Docker Desktop ir palaists, bet kļūda par daemon saglabājas, var pārstartēt Docker Desktop:

```bash
osascript -e 'quit app "Docker"'
open -a Docker
```

Pēc tam vēlreiz pārbaudīt:

```bash
docker info
```

Ja nepieciešams, var pārbaudīt aktīvo Docker context:

```bash
docker context ls
```

Docker Desktop gadījumā parasti aktīvais context ir `desktop-linux`. Ja nepieciešams, to var pārslēgt:

```bash
docker context use desktop-linux
```

Pēc tam vēlreiz:

```bash
docker info
docker compose -f docker-compose.local.yml up -d
```

## 20. Ieteicamā pilnā lokālās palaišanas secība

Ja projekts tiek palaists no jauna lokālā Mac datorā, ieteicamā secība ir šāda:

```bash
cd smt_iot
open -a Docker
docker info
docker compose -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml exec web python manage.py migrate
docker compose -f docker-compose.local.yml exec web python manage.py createsuperuser
docker compose -f docker-compose.local.yml exec web python manage.py check
```

Ja nepieciešams pārbaudīt simulatora datu plūsmu:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --once
docker compose -f docker-compose.local.yml logs -f mqtt_worker
```

## 21. Ātrais komandu kopsavilkums

Lokālā palaišana:

```bash
docker compose -f docker-compose.local.yml up -d
```

Lokālā palaišana ar pārbūvi:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Statusa pārbaude:

```bash
docker compose -f docker-compose.local.yml ps
```

Logi:

```bash
docker compose -f docker-compose.local.yml logs -f
```

Django migrācijas:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py migrate
```

Superuser izveide:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py createsuperuser
```

Django pārbaude:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py check
```

Simulatora vienreizēja palaišana:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py run_simulator --scenario default_demo --once
```

Apturēšana:

```bash
docker compose -f docker-compose.local.yml down
```

Apturēšana ar datubāzes volume dzēšanu:

```bash
docker compose -f docker-compose.local.yml down -v
```

Produkcijas vides palaišana:

```bash
docker compose -f docker-compose.prod.yml up -d
```
