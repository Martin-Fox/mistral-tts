# Audyt mistral-tts

Data: 2026-11-02. Gałąź: `main`, commit `86c38fe76680eed9ff158b2b19b1f86dbdfcfc6a`.
Audyt kodu i lokalna weryfikacja; bez zmian aplikacji, instalacji zależności, commitów, PR-ów i wywołań płatnych API. Nie odczytywano zawartości `.env` ani plików z sekretami.

## Zakres i ograniczenia

Przejrzano wszystkie 12 modułów Python w `src/`, trzy zasoby WebUI, 12 plików testowych, requirements, Dockerfile, entrypoint, konfiguracje pytest i ignorowania plików oraz README, DOCKER.md, PROJECT.md i dokumenty projektowe jako kontekst. Dokumenty projektowe nie stanowią dowodu wdrożenia funkcji. `/PROJECT.md` nie istnieje; wykorzystano repozytoryjny `PROJECT.md`. Na tej gałęzi brak śledzonych workflow CI/CD, lockfile oraz skryptów/specyfikacji pakowania Windows. Nie analizowano innych gałęzi ani zewnętrznych obrazów/release'ów, infrastruktury reverse proxy, historii sekretów lub jakości odpowiedzi rzeczywistych modeli.

Priorytety: Critical = bezpośrednie katastrofalne naruszenie bez dodatkowych założeń; High = utrata treści, naruszenie dostępu lub istotna awaria; Medium = ograniczona awaria/ryzyko operacyjne; Low = mały wpływ. Nie potwierdzono problemu Critical. Pewność dotyczy diagnozy mechanizmu, nie częstotliwości wystąpienia.

## Weryfikacja wykonana w środowisku

- Python 3.11.2, pytest 9.0.3, plugin anyio 4.13.0; FFmpeg/ffprobe dostępne. Testy async są uruchamiane przez anyio, brak pytest-asyncio sam w sobie nie oznacza, że obecne testy async nie działają.
- `ruff check src tests` oraz `ruff check src tests --isolated` i wybór E9/F63/F7/F82: bez uwag. `python3 -m pip check`: brak niespójności. Nie uruchamiano autofix/formatowania.
- `pytest --collect-only -q`: 163 testy. Pełne `pytest -q` przestało wykazywać postęp w części webowej i zostało przerwane. Osobna próba TestClient także utknęła; nie przypisano tego aplikacji bez rozstrzygnięcia wpływu środowiska.
- `timeout 60 pytest -q --ignore=tests/test_web.py`: limit czasu, wcześniej widoczny jeden failure. Osobne `timeout 15 pytest -vv tests/test_tui.py -x` utknęło na pierwszym teście inicjalizacji TUI, exit 124.
- `pytest -q --ignore=tests/test_web.py --ignore=tests/test_tui.py -x`: **94 passed, 1 failed** (21,80 s). `tests/test_translation.py:231` zakłada brak konfiguracji po usunięciu zmiennej, lecz `get_translation_model()` ponownie ładuje lokalny dotenv. To potwierdzona zależność testu od otoczenia; nie dowód nieprawidłowej hierarchii konfiguracji aplikacji. Rekomendacja: mock ścieżki dotenv lub izolowany cwd/konfiguracja w tym teście (C02/P20). Pewność wysoka, priorytet Medium.
- Ponowny przebieg z pominięciem WebUI/TUI i jednego zależnego od konfiguracji testu: **94 passed, 1 deselected**, 21,22 s. Polecenie: `timeout 60 pytest -q --ignore=tests/test_web.py --ignore=tests/test_tui.py --deselect=tests/test_translation.py::test_client_translation_model_fallback`. To nie jest zaliczenie pełnego suite.
- Próby z fake klientem i katalogiem tymczasowym: hasło Unicode -> TypeError; odczyt TXT UTF-16 nie zachowuje tekstu; token 6000 znaków trafia jako jeden request do mock translate_text. Bez sieci/API.
- Lokalny FFmpeg: poprawna próbka WAV i wyjście `.wav.denoised` -> exit 1, błąd wyboru formatu. CLI z nieistniejącym plikiem i fikcyjnym kluczem -> błąd wejścia, ale exit 0, przed wywołaniem API.
- Nie instalowano bandit, pip-audit ani narzędzi coverage; nie są dostępne. Nie przeprowadzono skanu baz CVE, budowy obrazu ani testu Windows. Wynik Ruff nie zastępuje audytu bezpieczeństwa i współbieżności.
- Stan Git po audycie: tylko nowy katalog docs/audit; testy mogą tworzyć ignorowane pliki storage i cache narzędzi. Nie zmieniano kodu ani poświadczeń użytkownika.

## A. Potwierdzone błędy i braki mechanizmów ochrony

### A01 — High: domyślne publicznie znane hasło i brak ograniczenia prób logowania
- Lokalizacja: `src/web.py:43`, `src/web.py:434`; `Dockerfile:46` (uruchomienie serwera na wszystkich interfejsach — dokładny CMD na końcu pliku).
- Dowód: brak konfiguracji oznacza `admin/admin`; aplikacja jedynie ostrzega. Login nie ma throttlingu. Docker publikuje aplikację, a uwierzytelniony użytkownik może korzystać z serwerowych kluczy API.
- Wpływ: przy domyślnym wdrożeniu przejęcie dostępu, plików audio oraz nieautoryzowane wydatki API. Ekspozycja internetowa zależy od operatora.
- Odtworzenie: w izolowanym środowisku bez konfiguracji poświadczeń zalogować się domyślnymi danymi; wielokrotnie wysłać błędne dane bez blokady.
- Poprawka: odmowa startu sieciowego bez jawnych bezpiecznych poświadczeń lub jednorazowa konfiguracja; limit prób per źródło i konto.
- Pewność: wysoka (kod).

### A02 — High: hasła zapisywane jawnie
- Lokalizacja: `src/web.py:46`, `src/web.py:416`; `docker-entrypoint.sh:6`.
- Dowód: JSON zawiera nowy tekst hasła, następnie jest odczytywany jako sekret do porównania. Entrypoint rekurencyjnie ustawia `775` na storage, także plikach.
- Wpływ: odczyt backupu/volume lub dostęp lokalnego konta do pliku ujawnia hasło; grupa może również zmieniać storage.
- Odtworzenie: przejrzeć przepływ `change_password` (nie trzeba odczytywać prawdziwego auth.json).
- Poprawka: adaptacyjny hash hasła, migracja istniejącego pliku, prawa 0600; nie wykonywać chmod 775 na wszystkich plikach.
- Pewność: wysoka.

### A03 — High: sesje bez TTL i bez unieważniania po zmianie hasła
- Lokalizacja: `src/web.py:60`, `src/web.py:67`, `src/web.py:420`, `src/web.py:448`.
- Dowód: set identyfikatorów nie przechowuje daty wygaśnięcia; zmiana hasła nie usuwa wcześniejszych sesji. Zamknięcie przeglądarki nie unieważnia tokenu na serwerze.
- Wpływ: wykradziony identyfikator działa do logout/restartu procesu nawet po zmianie hasła. Wiele workerów ma różne zbiory sesji i powoduje losowe 401.
- Odtworzenie: zalogować dwa klienty; zmienić hasło w pierwszym; drugi nadal ma dostęp. Rozdzielić ruch między dwa procesy.
- Poprawka: TTL, unieważnienie pozostałych sesji i wspólny magazyn albo jawnie wymuszony pojedynczy worker.
- Pewność: wysoka.

### A04 — High: porównywanie Unicode powoduje błąd logowania/zmiany hasła
- Lokalizacja: `src/web.py:401`, `src/web.py:439`.
- Dowód: `secrets.compare_digest(str, str)` odrzuca znaki spoza ASCII. Nowe hasło może zawierać polskie znaki, lecz późniejsze porównanie podniesie TypeError.
- Wpływ: 500 dla legalnego hasła, możliwość zablokowania sobie konta po zmianie hasła.
- Odtworzenie: login z username `żółw` lub ustawienie hasła z polskimi znakami i próba ponownego logowania.
- Poprawka: weryfikacja hasha hasła, dla porównań tekstowych jawne UTF-8 bytes.
- Pewność: wysoka (kontrakt funkcji i przepływ kodu).

### A05 — High: błędne sprawdzanie zgodności manifestu WebUI
- Lokalizacja: `src/web.py:299`, `src/web.py:311`.
- Dowód: `manifest["chunks"] = chunks` wykonuje się przed sprawdzeniem `manifest["chunks"][i] == chunk`; porównanie zawsze dotyczy nowego tekstu.
- Wpływ: po zmianie segmentacji lub ponownym, różnym tłumaczeniu odtworzone zostaje stare audio, także mieszanina nowych i starych segmentów. Tłumaczenie jest ponawiane przed odczytem cache.
- Odtworzenie: zachować completed i plik >100 B, zmienić wynik tłumaczenia przy tych samych danych wejściowych; stary segment zostaje pominięty jako cached.
- Poprawka: porównywać niezmieniony poprzedni manifest, zapisywać hash tekstu i parametrów każdego segmentu; utrwalać wynik tłumaczenia.
- Pewność: wysoka.

### A06 — High: niepełna i niejednoznaczna tożsamość cache
- Lokalizacja: `src/web.py:133`, `src/web.py:239`; `src/cli.py:133`.
- Dowód: klucze nie obejmują silnika/modelu TTS; CLI identyfikuje próbkę ścieżką zamiast treścią. Web hashuje konkatenację pól bez separatorów: text=`ab`, preset=`c` oraz text=`a`, preset=`bc` dają ten sam klucz. Web przy braku jawnego translation_model pomija faktyczny model z konfiguracji.
- Wpływ: ponowne wykorzystanie audio innego silnika, zmienionej próbki głosu lub konfiguracji tłumaczenia.
- Odtworzenie: ten sam tekst i ręczny voice ID między silnikami; podmiana zawartości próbki pod tą samą ścieżką CLI; powyższa para konkatenacji.
- Poprawka: wersjonowany, kanoniczny JSON z efektywnymi parametrami, hashem próbki i wersją segmentacji; bezpieczna invalidacja starego cache.
- Pewność: wysoka.

### A07 — High: współbieżne zadania zapisują wspólny cache i ten sam plik wyniku
- Lokalizacja: `src/web.py:248`, `src/web.py:161`, `src/web.py:305`, `src/web.py:344`; `src/cli.py:61`; `src/api/mistral_client.py:500`.
- Dowód: identyczne zadania używają jednego manifest.tmp i chunk_N.mp3 bez blokad. Domyślny output to audiobook.mp3; FFmpeg używa `-y`. Tłumaczenia o tej samej nazwie mają wspólny `.tmp`.
- Wpływ: utrata zapisów manifestu, race przy replace, odczyt częściowo zapisanego audio oraz nadpisanie wyniku wcześniejszego zadania. Stary completed wskazuje na plik nowego zadania.
- Odtworzenie: uruchomić dwa równoległe zadania z tymi samymi wejściami/nazwą wyjścia; przeplatać write/replace w mockach.
- Poprawka: blokada per cache obejmująca procesy, unikalne tmp; wyniki per task i atomowa publikacja po weryfikacji.
- Pewność: wysoka (brak izolacji w kodzie; nie wykonywano testu obciążeniowego).

### A08 — High: zadania nie są odtwarzalne po restarcie
- Lokalizacja: `src/web.py:699`, `src/web.py:719`, `src/web.py:371`; `src/core/task_db.py:27`.
- Dowód: BackgroundTasks i argumenty istnieją tylko w procesie; tabela zawiera postęp, ale nie wejścia/parametry potrzebne do odtworzenia. Startup uruchamia wyłącznie purger.
- Wpływ: po restarcie zadanie pozostaje na starym etapie; SSE czeka bez końca. Resubmit może wykorzystać audio cache, ale nie jest automatycznym resume tego zadania.
- Odtworzenie: przerwać worker podczas generacji, uruchomić ponownie i odpytać task_id.
- Poprawka: na start oznaczyć osierocone zadania Interrupted; następnie trwała specyfikacja i jawny resume, bez utrwalania kluczy klienta w plaintext.
- Pewność: wysoka.

### A09 — High: brak limitów przyjęcia pracy i wielkości danych
- Lokalizacja: `src/web.py:687`, `src/web.py:719`; `src/core/epub_parser.py:88`, `src/core/epub_parser.py:158`.
- Dowód: `UploadFile.read()` bez limitu ładuje cały plik, nie ma limitu zadań ani budżetu znaków; odczyty ZIP nie kontrolują rozpakowanej wielkości. Dotyczy użytkowników uwierzytelnionych; framework/proxy mogą narzucać własne limity.
- Wpływ: wyczerpanie RAM/dysku/CPU i budżetu API przez duże lub liczne zadania, małe silnie skompresowane EPUB.
- Odtworzenie: analiza ścieżki danych; nie wykonywano destrukcyjnego OOM ani bomby ZIP.
- Poprawka: limit strumieniowy uploadu, limit długości tekstu i sumy ZIP, bounded queue/semafor, odpowiedzi 413/429.
- Pewność: wysoka co do braku limitów aplikacji; skala zależy od wdrożenia.

### A10 — Medium: purger usuwa także aktywne zadania, ale nie sprząta plików
- Lokalizacja: `src/core/task_db.py:145`; `src/web.py:733`.
- Dowód: DELETE filtruje tylko created_at, nie status. Brak retencji cache/output/translations.
- Wpływ: zadanie trwające ponad dobę traci stan/logi, późniejsze update nic nie zapisuje; dysk rośnie mimo deklarowanego cleanup.
- Odtworzenie: aktywny rekord z created_at sprzed 25 h znika przy delete_old_tasks.
- Poprawka: usuwać tylko terminalne stany po finished_at, retencja plików z ochroną aktywnych referencji.
- Pewność: wysoka.

### A11 — Medium: denoising próbki FFmpeg faktycznie nie działa
- Lokalizacja: `src/api/mistral_client.py:93`.
- Dowód: wynik ma rozszerzenie `.mp3.denoised` lub `.wav.denoised`, bez jawnego `-f`; FFmpeg nie rozpoznaje muxera. Niezerowy returncode nie jest logowany, używana jest oryginalna próbka.
- Wpływ: deklarowane odszumianie nie poprawia klonowania, brak informacji o nieskuteczności operacji.
- Odtworzenie: uruchomić lokalny FFmpeg na poprawnej próbce z taką nazwą wyjścia; błąd wyboru formatu.
- Poprawka: zachować prawidłowe rozszerzenie albo wskazać muxer, raportować stderr przy błędzie.
- Pewność: wysoka.

### A12 — Medium: brak timeoutów procesów i blokowanie event loop
- Lokalizacja: `src/api/mistral_client.py:101`, `src/api/mistral_client.py:176`; `src/core/audio_compiler.py:74`, `src/core/audio_compiler.py:104`, `src/core/audio_compiler.py:175`; `src/tui.py:302`.
- Dowód: communicate/run bez timeoutów poza `_probe_duration` (30 s); synchroniczny ffprobe działa w async generate_audio; TUI synchronicznie kompiluje całą książkę.
- Wpływ: zawieszony proces blokuje etap bez końca; ffprobe blokuje obsługę WebUI, kompilacja zamraża TUI. Pełne dekodowanie długiego wyniku ma sztywny limit 30 s, niezależny od rozmiaru.
- Odtworzenie: mock procesu niekończącego działania i heartbeat event loop; duży wynik na wolnym CPU.
- Poprawka: wspólny runner z timeout/terminate/kill i obsługą cancellation; blocking I/O do thread; budżet walidacji zależny od czasu audio.
- Pewność: wysoka; nie zmierzono maksymalnej długości książki na sprzęcie użytkownika.

### A13 — Medium: CLI sygnalizuje sukces systemowi po błędzie pipeline
- Lokalizacja: `src/cli.py:245`.
- Dowód: wyjątek jest drukowany i połykany, main kończy się normalnie.
- Wpływ: skrypty/automatyzacja uznają nieudaną generację za sukces (exit 0).
- Odtworzenie: CLI z fikcyjnym kluczem i nieistniejącym plikiem tekstu; błąd następuje przed wywołaniem API.
- Poprawka: kod zakończenia !=0 po błędzie, zachować czytelny komunikat.
- Pewność: wysoka.

### A14 — Medium: utrata treści przy błędach odczytu książki
- Lokalizacja: `src/core/epub_parser.py:160`, `src/core/epub_parser.py:164`, `src/core/epub_parser.py:238`.
- Dowód: nieznany idref lub brak rozdziału jest pomijany; UTF-8 errors=ignore usuwa niepasujące bajty. Częściowo poprawny EPUB nadal zwraca sukces; UTF-16/cp1250 nie są jawnie odrzucane.
- Wpływ: audiobook bez rozdziału lub polskich znaków mimo zakończenia zadania.
- Odtworzenie: EPUB z jednym istniejącym i jednym brakującym rozdziałem; TXT UTF-16/cp1250.
- Poprawka: domyślnie fail-closed dla braków spine, jawne kodowanie/komunikat i świadomy tryb częściowego importu.
- Pewność: wysoka.

### A15 — Medium: niepełna walidacja tłumaczenia i limitów
- Lokalizacja: `src/api/mistral_client.py:235`, `src/api/mistral_client.py:390`, `src/api/mistral_client.py:467`.
- Dowód: whitespace-only message zwraca pusty tekst; JSON sprawdza długość translations, nie typ listy i niepustość elementów. Token bez spacji dłuższy niż 2500 znaków nie jest dzielony; SRT batch liczy 25 cue bez budżetu znaków.
- Wpływ: pominięcie przetłumaczonej treści lub zbyt duży request; powtarzanie identycznego requestu po finish_reason=length nie usuwa przyczyny.
- Odtworzenie: mock odpowiedzi content='   '; translations=[''] przy jednym cue; TXT='x'*6000 rejestruje translate_text z 6000 znaków.
- Poprawka: walidacja schematu i niepustości, wspólny bounded splitter, batch według rozmiaru i adaptacyjne dzielenie po truncation.
- Pewność: wysoka.

### A16 — Medium: TUI ma wspólne pliki chunk i nie wznawia pracy
- Lokalizacja: `src/tui.py:238`, `src/tui.py:294`.
- Dowód: wszystkie książki korzystają z storage/cache/chunk_N.mp3; brak manifestu i pomijania gotowych segmentów.
- Wpływ: dwa procesy TUI mieszają audio, restart ponosi pełny koszt generacji. Rozbieżność wobec deklaracji trwałości postępu projektu.
- Odtworzenie: równoległe TUI z różnymi książkami, potem kompilacja pierwszego procesu.
- Poprawka: izolowany cache i późniejsze wykorzystanie wspólnego serwisu pipeline.
- Pewność: wysoka.

### A17 — Medium: concat nie escapuje ścieżek, a wynik nie jest publikowany atomowo
- Lokalizacja: `src/core/audio_compiler.py:165`, `src/core/audio_compiler.py:175`.
- Dowód: apostrof ścieżki wstawiany jest bez escaping do składni concat. FFmpeg zapisuje bezpośrednio docelowy plik przed walidacją.
- Wpływ: katalog o nazwie zawierającej apostrof psuje kompilację (CLI, Windows/Linux); nieudana walidacja pozostawia dostępny plik częściowy. To błąd składni concat, nie dowód shell injection (subprocess otrzymuje listę).
- Odtworzenie: plik audio w katalogu `reader's`; wymusić błąd finalnej walidacji i sprawdzić istnienie output.
- Poprawka: bezpieczny serializer ścieżek/izolowany katalog roboczy, unikalny plik staging i replace po weryfikacji.
- Pewność: wysoka.

## B. Potencjalne zagrożenia zależne od środowiska

### B01 — High: transport cookie i kluczy przez HTTP
- Lokalizacja: `src/web.py:454`; `DOCKER.md:28`.
- Dowód: cookie secure=False, dokumentacja prowadzi do HTTP; aplikacja nie wymusza HTTPS.
- Wpływ: przechwycenie sesji/kluczy na niezaufanej sieci, jeśli wdrożenie nie zapewnia TLS. Nie potwierdzono konfiguracji serwera produkcyjnego.
- Weryfikacja: nagłówek Set-Cookie i konfiguracja reverse proxy.
- Poprawka: konfigurowalny Secure, dokumentacja TLS i localhost binding dla lokalnego trybu.
- Pewność: wysoka dla kodu, warunkowa dla ekspozycji.

### B02 — Medium: trwałe klucze w localStorage
- Lokalizacja: `src/web/static/app.js:41`, `src/web/static/app.js:378`, `src/web/static/app.js:385`, `src/web/static/app.js:770`.
- Dowód: klucze są zapisywane automatycznie, logout nie usuwa localStorage.
- Wpływ: następny użytkownik tego samego profilu przeglądarki może je odczytać; skrypt tego origin również. Nie wykryto potwierdzonego XSS: logi trafiają do textContent, a zaobserwowane innerHTML używa stałych.
- Weryfikacja: syntetyczny klucz, logout, kontrola storage w devtools.
- Poprawka: brak trwałego zapisu domyślnie, jawne opt-in i usuwanie przy logout.
- Pewność: wysoka dla przechowywania; brak dowodu zdalnej eksfiltracji.

### B03 — Medium: zależności i build nie są reprodukowalne
- Lokalizacja: `requirements.txt:1`, `requirements.txt:9`, `Dockerfile:2`, `Dockerfile:30`.
- Dowód: brak wersji/lockfile, brak zadeklarowanych bezpośrednio httpx i testowego anyio; narzędzia dev oraz zewnętrzne asyncio instalowane jako runtime. httpx obecnie dostępny tranzytywnie; nie twierdzimy, że import jest dziś zepsuty.
- Wpływ: zmiana resolvera/SDK może zepsuć fresh build, testy lub endpointy; zbędne pakiety zwiększają powierzchnię utrzymania.
- Weryfikacja: świeży izolowany build z ustalonymi wersjami; nie wykonywano instalacji ani skanu CVE online.
- Poprawka: osobne zależności runtime/dev, deklaracja importów i pluginów, constraints/lock z procesem aktualizacji.
- Pewność: wysoka dla braku pinów, nie ustalono podatności konkretnych wersji.

## C. Dług architektoniczny i luki w zapewnieniu jakości

### C01 — Medium: trzy implementacje pipeline i rozbieżne kontrakty
- Lokalizacja: `src/cli.py:75`, `src/web.py:174`, `src/tui.py:214`; `src/api/base_client.py:7`.
- Dowód: osobne reguły cache, resume, voice i kompilacji; set_voice_id używane przez wszystkie interfejsy nie należy do kontraktu bazowego. OpenAI sprawdza rozmiar audio, Mistral także ffprobe. Retry łapie wszystkie wyjątki, również trwałe 4xx, i nie stosuje Retry-After/jitter.
- Wpływ: poprawka w jednym interfejsie nie zapewnia zgodnego zachowania pozostałych; niepotrzebne retry i opóźnienia.
- Poprawka: dopiero po regresjach wydzielić małe współdzielone funkcje cache, walidacji i retry, następnie serwis pipeline; nie wprowadzać dużego frameworka zadań bez potrzeby.
- Pewność: wysoka (sugestia architektoniczna, nie osobna podatność).

### C02 — Medium: brak repozytoryjnych bramek CI i weryfikowalnej dystrybucji Windows
- Lokalizacja: katalog główny repozytorium (brak `.github/workflows` i odpowiedników), `requirements.txt:1`, `pytest.ini:1`.
- Dowód: git ls-files nie zawiera workflow, specyfikacji bundlera ani buildów Windows. Nie oznacza to braku zewnętrznego CI; nie oceniano innych gałęzi. Testy WebUI domyślnie omijają auth (`tests/test_web.py:11`) i importują produkcyjny moduł tworzący storage/state.db; są testy auth, lecz brakuje opisanych regresji TTL/Unicode/race/restart.
- Wpływ: regresje mogą trafiać do wydania; sam zielony suite nie daje gwarancji zachowania równoległego ani zgodności Windows. Nie zmierzono procentowego coverage.
- Poprawka: CI offline na fake clients, FFmpeg smoke, Windows/Linux matrix, osobne build smoke Docker/Windows, izolowana baza testowa.
- Pewność: wysoka dla zawartości gałęzi, nieznana dla zewnętrznej infrastruktury.

## Ocena pozytywnych zabezpieczeń

Endpointy danych/generacji/konfiguracji wymagają sesji; brak obejścia auth nie został wykazany. Pobieranie audio i ścieżka tłumaczeń stosują resolve oraz kontrolę katalogu. SQL wartości są parametryzowane. Subprocess używa argv, bez shell=True. Są retry, atomowe replace manifestów (ale bez blokad), trailing silence i pomiar czasu zdekodowanego audio. Tolerancja 4 s odpowiada PROJECT.md; nie zgłaszamy samego jej istnienia jako błędu. Pomiar czasu nie potwierdza semantycznej kompletności wypowiedzianego tekstu.

## Podsumowanie i kolejność

10 najważniejszych: A01 domyślne logowanie; A02 jawne hasła; A03 sesje; A05 walidacja manifestu; A06 tożsamość cache; A07 współbieżne zapisy; A08 restart; A09 limity pracy; A14 utrata tekstu; A04 Unicode w auth.

Najlepszy stosunek korzyści do nakładu: (1) zachować poprzednie chunks przy sprawdzaniu manifestu, (2) blokować niebezpieczne domyślne logowanie, (3) unieważniać sesje po zmianie hasła, (4) poprawić format wyniku denoise i logowanie błędu, (5) zwracać niezerowy exit code CLI. Każda zmiana wymaga małej regresji; pełne hash/session/cache migration mają większy zakres niż te szybkie poprawki.

Ocena: użyteczny projekt do lokalnej pracy jednej osoby, z istotnymi mechanizmami ochrony końca audio i rosnącym zestawem testów. Nie jest jeszcze gotowy na niekontrolowaną ekspozycję sieciową ani równoległe, trwałe przetwarzanie długich zadań. Największe ryzyko to ciche użycie niepasującego audio oraz rozbieżność trwałego statusu i rzeczywistego wykonania. Najpierw auth i poprawność cache, następnie izolacja zapisów i limity, potem restart/timeout/ingestion, na końcu konsolidacja architektury. CI i testy regresyjne powinny towarzyszyć wszystkim etapom.

Zgodność z PROJECT.md: rekomendacje chronią kompletność tekstu/audio, bezpieczne resume, oszczędność zasobów i prostotę. Nie zaproponowano przepisywania projektu, multi-user ani OIDC jako warunku napraw. Zmiany w tym audycie obejmują wyłącznie dwa dokumenty.
