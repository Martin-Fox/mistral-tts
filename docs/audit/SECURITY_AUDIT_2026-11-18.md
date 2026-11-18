# Audyt bezpieczeństwa i plan napraw — 18 listopada 2026

Status realizacji punktów 1–2: gałąź `fix/web-request-security` zawiera naprawę
S01/S03, wyłączenie domyślnego zaufania do nagłówków proxy oraz
[opis zabezpieczeń wdrożenia i wyniki testów](../SECURITY_DEPLOYMENT.md).
Poniższy audyt zachowuje stan pierwotnego commitu. Zmiany nie zostały wdrożone
na hoście LAN; jego digest i reguły sieciowe nadal wymagają weryfikacji operatora.

Kolejny etap: [zabezpieczenia plików i aktualizacja zależności](SECURITY_REMEDIATION_2_3_2026-11-18.md).
Zgodnie z późniejszym poleceniem nie budowano dla niego nowego obrazu Docker.

[Punkt 5: hasła, CSRF i XML](SECURITY_REMEDIATION_5_2026-11-18.md) jest zakończony
w kodzie i przetestowany także w Chromium. Raport zawiera pozostałe otwarte prace;
nie oznacza to zakończenia całego audytu ani wdrożenia zmian w obrazie.

[Aktualizacje SDK i zależności natywnych](SECURITY_DEPENDENCY_UPDATES_2026-11-18.md)
usuwają konflikt OpenTelemetry w aktualnych lockach i przygotowują FFmpeg 9.0.2
bez libxml2 dla przyszłego obrazu. W tym etapie nie budowano Dockera; ograniczenia
native CVE oraz akceptacja Windows/obrazu pozostają jawnie opisane w raporcie.

## Wniosek

Naprawy są potrzebne. Najpilniejsze są: ochrona kolejki przed nieuwierzytelnionymi uploadami, ograniczenie przetwarzania niezaufanego audio przez FFmpeg oraz odświeżenie obrazu i zależności. Nie wykazano obejścia logowania ani wykonania kodu atakującego. Wykazano możliwość zajęcia całego budżetu przyjmowania zadań bez logowania.

Obraz **nie bazuje na Alpine**. Dockerfile używa `python:3.11-slim`; zbadany lokalny artefakt `marcinlis82/mistral-tts:1.0.3` zawiera **Debiana 13.7 (trixie), glibc i Python 3.11.18**. Nie ma `sshd` ani musl. Listopadowy [komunikat Alpine o obejściu logowania SSH](https://www.alpinelinux.org/posts/2026-11-05-openssh-password-authentication-bypass/) nie dotyczy tego artefaktu. Nie należy jednak ignorować wspólnych bibliotek, np. zlib, tylko dlatego, że komunikat dotyczył Alpine.

## Zakres i wiarygodność

- Kod: commit `676b62ec2e782cdf38ac8caad923726945ef2343`, początkowo czyste drzewo na `fix/audit-remediation`. Raport powstał na `docs/security-audit-2026-11-18`.
- Obraz lokalny: `sha256:6f28e53cb126b1470a01c64448aa31489906f7eb4cbaa3e69ec10fae3f0e0c52`, zbudowany `2026-11-16T13:35:28Z`; RepoDigest `marcinlis82/mistral-tts@sha256:32eed86acb52cc7b61191052a5b31ea0d47fd0d4598f09766704f2e6ba8fc9b2`.
- Wszystkie pliki `.py` i `.js` obecne w `src/` obrazu porównano hashami z checkoutem: brak różnic. Zainstalowany `packaging` w obrazie ma wersję 26.3, podczas gdy aktualny lock ma 26.2; nie potwierdzono zgodności całego procesu budowania wyłącznie na podstawie zgodnego kodu.
- Trivy **0.76.2**, baza z **2026-11-18 07:15 UTC**: 293 pakiety OS oraz metadane Pythona, w tym zależności vendored instalatorów.
- pip-audit **2.10.1**, bieżąca baza PyPI: osobno oba kompletne locki, bez instalowania zależności w systemie. Bandit **1.9.4** i ręczny przegląd backendu, parserów, subprocessów, frontendowych ujść danych, storage, Dockera i CI.
- Dokumentację CVE zweryfikowano również w Debian Security Tracker i komunikatach opiekunów bibliotek. Liczba zgłoszeń skanera nie jest liczbą działających exploitów.
- **185 testów przeszło**, 4 ostrzeżenia, 19,61 s, czyste środowisko CPython 3.11.2 z `requirements-dev.txt` instalowanym z hashami. To wybrany zestaw regresji, nie pełne testy ani test akceptacyjny Windows.
- Reprodukcje ASGI wykonano w tymczasowym storage, bez prawdziwych kluczy i bez płatnych żądań. Inwentaryzację uruchamiano w jednorazowych kontenerach, bez montowania danych produkcyjnych. `apt-get update`/`apt-cache policy` wykonano w osobnym jednorazowym kontenerze; nie aktualizowano wdrożenia.
- Nie ustalono, jaki digest działa na produkcji ani co obecnie wskazują zdalne tagi `latest`/`1.0.3`. Nie badano konfiguracji hosta, kernela, działającego reverse proxy, historii sekretów w Git ani gotowego pliku EXE. Skan pakietów nie jest pełnym audytem CVE samodzielnie zbudowanego interpretera CPython w `/usr/local`.

## Wyniki baz podatności

| Zakres | Wiersze skanera | Unikalne identyfikatory | Critical / High / Medium / Low / Unknown |
| --- | ---: | ---: | --- |
| Pakiety Debiana w obrazie | 1675 | 403 | 1 / 73 / 116 / 113 / 100 |
| Python w obrazie, także instalatory i vendored | 15 | 15 | 1 / 2 / 10 / 2 / 0 |
| Lock runtime, pip-audit | 6 | 5 | 3 pakiety z podatnościami |
| Lock dev wraz z runtime, pip-audit | 8 | 7 | 4 pakiety z podatnościami |

Powtórzone zgłoszenie python-dotenv w pip-audit policzono tylko raz przy deduplikacji. Wyników Trivy i pip-audit nie należy dodawać: obejmują wspólne podatności. W Debianie jeden CVE często powtarza się dla wielu bibliotek FFmpeg. `Unknown` oznacza brak oceny, a nie potwierdzoną niską wagę.

Pełne 1690 wierszy Trivy zawiera [image-findings.csv](security-2026-11-18/image-findings.csv), a wersje narzędzi, datę bazy i wyniki locków — [scan-summary.json](security-2026-11-18/scan-summary.json).

### Pakiety wymagające decyzji

| Pakiet i wersja | CVE / advisory | Poprawka i zastosowanie w projekcie |
| --- | --- | --- |
| FFmpeg `7:7.1.5-0+deb13u1` | [CVE-2026-64835](https://security-tracker.debian.org/tracker/CVE-2026-64835), [CVE-2026-66039](https://security-tracker.debian.org/tracker/CVE-2026-66039), m.in. High | Błędy pamięci dekoderów ADX/AAX i CAF/MACE6. W trixie poprawki odroczone; kandydat apt jest taki sam jak wersja zainstalowana. Upload próbki głosu dochodzi do automatycznego dekodowania. To istotniejsza ścieżka niż CVE dotyczące nieużywanych enkoderów wideo. Nie wykonano exploita pamięci. |
| zlib `1:1.3.dfsg+really1.3.1-1+b1` | [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091) High; CVE-2026-27171 Medium | Dostępny pakiet Debiana `1:1.3.dfsg+really1.3.1-1+deb13u1` usuwa oba zgłoszenia. Weryfikacja `apt-cache policy` potwierdza dostępność. Nie wykazano, że aplikacja wywołuje podatny scenariusz zapisu `gz*`; obecność biblioteki uzasadnia aktualizację, nie twierdzenie o RCE przez EPUB. |
| libxml2 `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | [CVE-2026-6653](https://security-tracker.debian.org/tracker/CVE-2026-6653), Critical wg Trivy | Debian potwierdza podatny pakiet, ale opisuje problem jako `Minor issue`, `no-dsa`; brak nowszego kandydata trixie. Numer `really2.9.14` ma znaczenie. EPUB korzysta z ElementTree/Expat, nie libxml2. Biblioteka jest częścią powierzchni zależności FFmpeg; nie wykazano osiągalności konkretnej funkcji. |
| AnyIO `4.13.0` | [CVE-2026-63374 / GHSA-82r6-8w77-94w6](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6), Critical; CVE-2026-64847 Medium | Cel: co najmniej `4.14.2`. Critical dotyczy TLS i domen non-ASCII; domyślne endpointy Mistral/OpenAI są ASCII. Drugie zgłoszenie wymaga process pool AnyIO, którego kod projektu nie używa. Nie wykazano tych ataków na domyślnej ścieżce aplikacji. |
| python-dotenv `0.21.0` | [CVE-2026-28684 / GHSA-mf9w-mj56-hr94](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94), Medium | Cel: co najmniej `1.2.2`. Używamy podatnego `set_key()` w `src/core/config.py:70`. Warunki obejmują lokalną kontrolę nad symlinkiem `.env` i przenoszenie między systemami plików. Nie jest to samodzielny zdalny zapis dowolnego pliku przez endpoint konfiguracji. |
| OpenTelemetry API `1.39.1` | [CVE-2026-114603](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h), [CVE-2026-126360](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg), Medium | Cel: co najmniej `1.45.2`. DoS przy parsowaniu kontekstu śledzenia. Nie znaleziono w aplikacji instrumentacji serwera ani przekazywania niezaufanego kontekstu do tych parserów. **Aktualizacja jest blokowana przez kontrakt zależności opisany poniżej.** |
| uv `0.11.7`, tylko dev | [GHSA-hq85-5cpj-mr62 / CVE-2026-119327](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62), [GHSA-4gg8-gxpx-9rph](https://github.com/astral-sh/uv/security/advisories/GHSA-4gg8-gxpx-9rph) | Cel: co najmniej `0.13.4`; usuwa niebezpieczny korzeń CA i obejmuje poprawkę zapisu poza katalogiem skryptów. Dotyczy narzędzia utrzymującego locki, nie usługi w obrazie. |
| pip `24.0`, setuptools `79.0.1` i jego vendored wheel `0.45.1`, jaraco.context `5.3.0` | m.in. CVE-2026-8643, CVE-2026-24049, CVE-2026-23949 | Znajdują się w obrazie poza grafem aplikacji. Nie instaluje się pakietów przez WebUI, więc bezpośrednia ekspozycja jest mniejsza. Usunąć zbędne instalatory z finalnego runtime albo zaktualizować wraz z vendored zależnościami i przeskanować ponownie. Osobno zainstalowany wheel `0.46.3` **nie usuwa** kopii wheel `0.45.1` wewnątrz setuptools. |

Pełna lista obejmuje także Expat, SQLite, OpenSSL i biblioteki multimedialne. Runtime zgłasza Expat 2.9.0, OpenSSL 3.5.7, zlib 1.3.1 i SQLite 3.46.1. Zgłoszeń dotyczących KDC/kadmind, systemd-homed, klientów X11, FTS5 czy session changesets nie uznano automatycznie za osiągalne przez WebUI: brak odpowiadających im usług/funkcji aplikacji. Lista CSV pozostaje wejściem do przeglądu pozostałych CVE, a nie zatwierdzoną listą wyjątków. Dla Expat potrzebna jest szczególna ostrożność, ponieważ parsowanie EPUB faktycznie używa tej biblioteki.

### Konflikt aktualizacji OpenTelemetry

Metadane faktycznie zainstalowanych pakietów potwierdzają:

```text
mistralai 2.4.9 -> opentelemetry-semantic-conventions >=0.60b1,<0.61
opentelemetry-semantic-conventions 0.60b1 -> opentelemetry-api ==1.39.1
poprawki dwóch CVE -> opentelemetry-api >=1.45.2
```

Nie można po prostu zmienić pinu API na 1.45.2 ani użyć `--no-deps`, by ominąć konflikt. W ramach osobnej decyzji bezpieczeństwa należy sprawdzić nowszy SDK Mistrala i zgodność Voxtral/translation albo utrzymywać zweryfikowany backport. `PROJECT.md` obecnie wymaga SDK 2.4.9, więc jego zmiana wymaga jawnej zmiany tego kontraktu i testów. Do tego czasu wyjątek powinien być ograniczony do tych dwóch CVE, udokumentowany brakiem instrumentacji/ekstrakcji niezaufanego kontekstu, z właścicielem i terminem ponownego przeglądu.

## Ustalenia z kodu

Priorytety poniżej opisują ryzyko projektu; nie są przepisanym CVSS biblioteki.

### S01 — High: anonimowy klient może zablokować przyjmowanie generacji

- Miejsce: `src/web_limits.py:48`, `src/web_limits.py:52`, `src/web_limits.py:77`, `src/web.py:560`.
- Middleware rezerwuje miejsce i czyta cały request przed wykonaniem zależności `verify_session`. `receive()` nie ma deadline. Domyślnie są cztery miejsca, wspólne dla uploadów, kolejki i trwających zadań.
- Reprodukcja na rzeczywistym ASGI app: cztery nieuwierzytelnione, niedokończone requesty zajęły cztery miejsca; piąty otrzymał `429`. Wynik: [reproduce.txt](security-2026-11-18/reproduce.txt). Nie wykonano ataku na port produkcyjny; reverse proxy buforujące requesty może ograniczać tę ścieżkę.
- Naprawa: wczesne sprawdzenie sesji przed zajęciem budżetu i spoolingiem, zachowanie późniejszej walidacji sesji, deadline całego uploadu i limit bezczynności. Wszystkie błędy/cancel/disconnect muszą zwalniać miejsce. Dodać regresję powyższego przypadku.

### S02 — High: zbyt szerokie dekodowanie próbek głosu przez podatny FFmpeg

- Miejsce: `src/api/mistral_client.py:103`, szczególnie `:119`; `src/web.py:661`.
- Backend ogranicza liczbę bajtów, ale nie zawęża demukserów i dekoderów. Rozszerzenie pliku i frontendowy filtr uploadu nie stanowią kontroli formatu — FFmpeg wykrywa go z zawartości.
- Dwa wymienione CVE dekoderów audio dotyczą zainstalowanej wersji. Nie dowiedziono wykonania kodu; skuteczny exploit działałby z uprawnieniami użytkownika aplikacji i mógłby naruszyć jego dane oraz klucze.
- Limit czasu subprocessu jest korzystny, ale nie zatrzymuje błędu pamięci. Brak twardego budżetu pamięci i rozmiaru generowanego pliku; kontrola pliku wyjściowego występuje po przetwarzaniu. `communicate()` buforuje stdout/stderr w RAM.
- Naprawa: zaakceptować w backendzie mały zestaw formatów głosu, wymuszać kompatybilne demuksery/dekodery i protokoły, odrzucać playlisty/kontenery spoza kontraktu; ograniczyć czas audio, pamięć, plik wyjściowy i zbierane logi. Docelowo parser audio uruchamiać bez kluczy, bez sieci i bez dostępu do całego storage. Zweryfikować poprawiony FFmpeg; samo `apt upgrade` obecnie nie usuwa tych dwóch CVE. Nie potwierdzono SSRF i nie należy przedstawiać go jako gotowego exploita.

### S03 — Medium: limity body nie obejmują loginu i zmiany hasła

- Miejsce: `src/web_limits.py:49`, `src/web.py:319`, `src/web.py:366`, `src/web.py:456`.
- `MAX_REQUEST_BYTES` obejmuje tylko generate/resume. JSON loginu jest dekodowany przed limiterem prób logowania. Modele haseł nie mają maksymalnej długości; `update_config` także odczytuje pełny JSON.
- Reprodukcja: przy `MAX_REQUEST_BYTES=1024` login przyjął do walidacji body 16421 B i odpowiedział `401`, nie `413`. To potwierdza brak tej granicy; nie wykonano testu wyczerpującego RAM.
- Naprawa: mały globalny limit body dla JSON/auth/config przed parsowaniem i limity długości pól. Zachować osobny większy budżet uploadów oraz obsługę requestów chunked. Ochrona reverse proxy jest uzupełnieniem.

### S04 — Medium: MOBI nie ma izolowanego budżetu ekstrakcji

- Miejsce: `src/core/epub_parser.py:219`; wywołanie preflight w `src/web.py:674`.
- Limit wejścia jest sprawdzany przed ekstrakcją, ale limit wyniku dopiero po `mobi.extract()`. Biblioteka pracuje w procesie aplikacji, bez zabijalnego workera i limitu RAM/dysku/czasu. Sam thread nie jest izolacją zasobów. To udokumentowane ograniczenie również w README; audyt go potwierdza.
- Naprawa: ograniczony proces ekstrakcji z kontrolowanym katalogiem i cleanupem, albo przełącznik wyłączający MOBI w dostępie zdalnym do czasu wdrożenia izolacji. Nie wykazano traversal ani konkretnego exploita MOBI.

### S05 — Medium: dopuszczane są bardzo słabe hasła

- Miejsce: `src/core/auth.py:74`, `src/web.py:345`. Start blokuje puste hasło i `admin`, lecz akceptuje `a`; zmiana hasła dopuszcza cztery znaki.
- Reprodukcja `load_credentials()` z nieistniejącym tymczasowym plikiem potwierdziła akceptację `a`. PBKDF2 i limity prób są poprawnymi zabezpieczeniami, ale nie zapewniają entropii hasła.
- Naprawa: spójna polityka długiej frazy, np. minimum 12 znaków dla nowej konfiguracji i zmiany hasła, rozsądny limit długości, jasna procedura migracji istniejących kont. Nie blokować bez zapowiedzi istniejącego wdrożenia po restarcie.

### S06 — Medium: Windows build pobiera zmienne artefakty bez kontroli integralności

- Miejsce: `.gitea/workflows/build-windows.yml:17`, `:29`, `:38`, `:41`.
- Akcje są przypięte tagami, PyInstaller bez wersji/hashy, FFmpeg pobierany ze zmiennych URL bez sprawdzanego SHA-256. HTTPS chroni transport, ale nie ustala zatwierdzonej tożsamości artefaktu.
- Samo `pip install -r requirements.txt` korzysta z hashów obecnych w locku; problemem jest niespójność pełnej ścieżki z dodatkowym PyInstallerem i bootstrapem, nie automatyczny brak weryfikacji każdego pakietu z locka.
- Naprawa: SHA akcji, osobny lock narzędzi pakujących, konkretna wersja/źródło FFmpeg i niezależnie zatwierdzony hash archiwum, ta sama weryfikacja dla fallbacku. Zachować natywny test finalnego EXE.

### S07 — Low/Medium: brak ochrony Origin/CSRF i nagłówków ochronnych

- Miejsce: konfiguracja app i cookie w `src/web.py:124`, `:401`, zapis konfiguracji przez form w `:456`.
- `HttpOnly` i `SameSite=Lax` ograniczają ryzyko. Brakuje jednak sprawdzania Origin/CSRF przy operacjach zmieniających stan, CSP i ochrony przed osadzaniem strony w ramce. Lax nie chroni przed każdym scenariuszem z niezaufaną subdomeną tej samej witryny. Nie wykazano zwykłego cross-site POST z automatycznie wysłaną sesją w prawdziwej przeglądarce.
- Naprawa: jawny kontrakt pochodzenia i ochrona żądań zmieniających stan, `frame-ancestors 'none'`, `nosniff`, dopasowana CSP; HSTS ustawić na terminatorze TLS. Sprawdzić wpływ CSP na istniejące skrypty i style. Wymóg HTTPS dla zdalnego dostępu jest już opisany i nie jest nowo odkrytym błędem.

## Co działa poprawnie / wyniki skanera wymagające interpretacji

- PBKDF2-HMAC-SHA256, 600000 iteracji, losowa sól, stałoczasowe porównanie; atomowy zapis credentiali i tryb 0600. Domyślne `admin` blokuje start.
- Sesje mają TTL, HttpOnly, Lax i opcjonalne Secure; logout i zmiana hasła odwołują sesje, SSE ponownie sprawdza sesję. Budżet prób logowania ma ograniczoną pamięć. To model jednego wspólnego konta, zgodny z PROJECT.md, bez obietnicy izolacji wielu użytkowników.
- Pobieranie audio sprawdza `resolve()` i położenie w katalogu; wartości SQL są parametryzowane. Bandit B608 na `task_db.py:107` jest tu fałszywym alarmem: dynamiczne są wyłącznie stałe fragmenty nazw kolumn, dane trafiają do parametrów.
- Subprocessy używają argv, bez `shell=True`. B603/B404 nie dowodzą command injection. Losowość w retry służy jitterowi, nie tokenom sesji — B311 nie jest podatnością kryptograficzną w tym zastosowaniu.
- Frontend używa `textContent` dla logów, nazw plików i statusów. Znalezione `innerHTML` dotyczą stałych fragmentów UI lub czyszczenia elementów. Nie znaleziono ujścia XSS dla tych danych.
- Klucze klienta nie trafiają do localStorage ani trwałych snapshotów; `.env` i storage są wyłączone z kontekstu Dockera. Parser EPUB czyta elementy ZIP bez rozpakowywania ich ścieżek na dysk i ma limity rozmiaru/liczby elementów.
- Bandit: 15 zgłoszeń, w tym 4 Medium, 0 High. Trzy Medium dotyczą ElementTree. **Nie potwierdzono XXE ani odczytu dowolnych plików przez XML**. Odrzucanie DTD/entities i testy złośliwego XML są uzasadnionym wzmocnieniem, zwłaszcza przy obecnych zgłoszeniach Expat, ale nie należy utożsamiać ElementTree z libxml2.
- Entrypoint po przygotowaniu storage opuszcza uprawnienia przez gosu. Brak `USER` w Dockerfile oznacza start jako root, nie stałe działanie Uvicorna jako root. Warto docelowo przygotowywać wolumen osobno i wspierać uruchomienie bez root/capabilities; nie stwierdzono ucieczki z kontenera.

## Plan napraw w kolejności realizacji

1. **P0 — zabezpieczyć zdalną ekspozycję i ustalić artefakt.** Zapisać digest faktycznie wdrożonego obrazu i porównać go z audytem. Sprawdzić HTTPS, Secure cookies, prywatny backend, zaufane adresy proxy, limity body i upload timeout. Do czasu S01/S02 nie wystawiać bezpośrednio Uvicorna publicznie ani nie przetwarzać próbek audio z niezaufanych źródeł. Kryterium: brak publicznego obejścia proxy; logowanie/SSE/audio działają przez HTTPS.
2. **P1 — naprawić S01 i S03 minimalnymi zmianami WebUI.** Wczesne uwierzytelnienie, deadline uploadu, limity JSON i pól. Kryterium: anonimowe wolne uploady nie zużywają kolejki; timeout zwalnia miejsce; duże JSON są odrzucane przed parsowaniem; prawidłowy upload i resume nadal działają.
3. **P1 — zamknąć S02 i ograniczyć S04.** Wprowadzić faktyczne formaty/codec allowlist i budżety dekodowania. Odrzucenie nieobsługiwanego pliku musi nastąpić przed wysłaniem go do dostawcy i nie może przechodzić w fallback używający oryginału. Dla MOBI izolowany worker lub czasowe wyłączenie w dostępie zdalnym. Kryterium: nieobsługiwane kontenery, playlisty i nadmierny czas/rozmiar są odrzucane; proces nie ma dostępu do kluczy i nie może wyczerpać zasobów hosta. Sprawdzić ciągłość, głośność i długość poprawnego audio.
4. **P1 — odświeżyć obraz i łatwe zależności bez zmiany SDK.** Jawna gałąź Debiana i digest bazy, regularny rebuild z pobraniem świeżej bazy, jawna aktualizacja zlib do pakietu z poprawką. Samo ponowne `apt install ffmpeg gosu` nie gwarantuje aktualizacji bibliotek odziedziczonych z bazy. Zaktualizować AnyIO do wersji z poprawką, python-dotenv >=1.2.2 i uv >=0.13.4; odtworzyć oba locki z hashami. Usunąć niepotrzebne instalatory z finalnego obrazu lub naprawić również ich vendored kopie. Kryterium: `pip check`, instalacja obu locków z hashami, pełne testy offline i Docker smoke, ponowny skan obrazu po digest; brak wskazanych usuwalnych CVE. Nie obiecywać zera CVE przez sam rebuild.
5. **P1/P2 — osobno rozwiązać OpenTelemetry i FFmpeg/libxml2 bez dostępnej poprawki trixie.** Dla Mistrala przetestować zgodny nowszy SDK i uzgodnić zmianę pinu w PROJECT.md albo backport. Dla FFmpeg wybrać utrzymywany pakiet/build zawierający konkretne poprawki, z ustalonym pochodzeniem i hashami; nie mieszać Debiana stable z sid. Dla libxml2 ustalić osiągalność używanych parserów, możliwość ograniczenia zależności lub poprawiony wspierany build. Kryterium: usunięte CVE albo wąskie wyjątki z dowodem, właścicielem, zabezpieczeniem kompensującym i terminem przeglądu. Testować importy, translation/voice/cache i generację fake klientami; płatne wywołania nie są wymagane do regresji.
6. **P2 — spójne hasła, CSRF i XML.** Zamknąć S05/S07, zapewnić migrację haseł i testy przeglądarkowe. Dla EPUB odrzucać zbędne DTD/entities, kontrolować budżet parsowania, śledzić poprawki Expat. Kryterium: odrzucenie obcego Origin bez regresji desktop/CLI, niedopuszczenie słabych nowych haseł, kontrolowane odrzucenie złośliwego XML bez pobrań sieciowych.
7. **P2 — uporządkować łańcuch Windows i bieżące skany.** Zamknąć S06; dodać pip-audit obu locków, Trivy gotowego obrazu i SBOM do CI oraz skany cykliczne niezależne od commitów. Zgłoszenia oceniać po funkcji i wersji dystrybucyjnej; wyjątki muszą mieć datę wygaśnięcia. Kryterium: regresje blokują wydanie, artefakt jest identyfikowalny przez hash/digest, a natywny Windows smoke sprawdza faktycznie spakowany FFmpeg i aplikację.

## Odtwarzanie i dowody

```bash
# Narzędzia w osobnym środowisku; nie dodawano ich do zależności aplikacji.
pip-audit -r requirements.txt --disable-pip --no-deps --progress-spinner off --format json
pip-audit -r requirements-dev.txt --disable-pip --no-deps --progress-spinner off --format json
trivy image --scanners vuln --image-src docker --format json marcinlis82/mistral-tts:1.0.3
bandit -r src -f json
python -m pytest -q tests/test_auth.py tests/test_sessions.py tests/test_login_limiter.py \
  tests/test_resource_limits.py tests/test_epub.py tests/test_config.py tests/test_web.py \
  tests/test_process_runner.py tests/test_task_recovery.py
```

Locki zawierają kompletny graf. `--no-deps --disable-pip` wyłącza rozwiązywanie/instalowanie zależności, nie zapytania do bazy podatności. Wynik zależy od aktualności bazy i platformowych markerów; skan obrazu uzupełnia audyt locków. Przy powtórzeniu skanu wskazać zapisany digest/ID, aby uniknąć dryfu tagu.

- [Inwentaryzacja obrazu](security-2026-11-18/image-inventory.txt)
- [Dostępne wersje apt](security-2026-11-18/apt-policy.txt)
- [Wynik testów](security-2026-11-18/tests.txt)
- [Wyniki reprodukcji](security-2026-11-18/reproduce.txt)
- [Wszystkie ustalenia Trivy](security-2026-11-18/image-findings.csv)
- [Podsumowanie maszynowe](security-2026-11-18/scan-summary.json)

Surowe JSON skanerów i skrypt reprodukcji pozostawiono lokalnie w `/tmp/mistral-security-audit/`; jest to katalog tymczasowy, nie trwałe archiwum. CSV zachowuje wszystkie wiersze podatności obrazu. Nie dodawano pełnych treści cudzych advisories do repozytorium.

## Zgodność z PROJECT.md

Audyt uwzględnia jeden worker i jedno konto, ochronę kluczy, małe zużycie zasobów oraz ciągłość audio. Plan przewiduje małe, oddzielne zmiany, odtwarzanie obu locków i testy bez powtarzania płatnych operacji. Nie zmieniono kontraktu SDK 2.4.9 ani kodu produkcyjnego; konflikt jego zależności jest jawnie opisany. Testy lokalne nie zastępują akceptacji HTTPS/proxy, natywnego Windows ani gotowego artefaktu wydania.
