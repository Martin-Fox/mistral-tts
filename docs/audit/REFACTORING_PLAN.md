# Plan refaktoryzacji mistral-tts

> Dokument historyczny: opisuje punkt wyjścia audytu/plan z 2026-11-02. Bieżące procedury wdrożenia, odzyskiwania i migracji są w [OPERATIONS.md](../OPERATIONS.md), a otwarta bramka Windows w [WINDOWS.md](../WINDOWS.md). Nie jest to ponowny audyt po poprawkach.

Punkt odniesienia: [raport audytu](AUDIT_REPORT.md), gałąź main, commit 86c38fe76680eed9ff158b2b19b1f86dbdfcfc6a. To plan, nie wdrożone poprawki.

## Zasady realizacji

Każdy poniższy wiersz to osobny, niewielki PR z własnymi testami. Nie łączyć zmian zachowania z dużym przenoszeniem kodu. Najpierw regresja odtwarzająca problem, potem minimalna poprawka. Dane istniejących użytkowników wymagają jawnej migracji; stare cache można bezpiecznie unieważnić, lecz trzeba uprzedzić o ponownym koszcie generacji. Nie zapisywać kluczy klienta w trwałym opisie zadania. Estymacje to orientacyjne dni robocze jednej osoby, obejmujące regresje, bez oczekiwania na review. Całość około 4–7 tygodni, zależnie od decyzji dotyczących resume i dystrybucji Windows.

## 1. Krytyczne błędy i bezpieczeństwo

| PR / priorytet / nakład | Zakres i ustalenia | Zależności | Ryzyko regresji | Testy i kryteria akceptacji |
| --- | --- | --- | --- | --- |
| P01 / High / 1 dzień | A01: odmowa startu przy admin/admin w trybie sieciowym, jasny błąd konfiguracji; lokalny onboarding opisany jawnie | brak | Średnie: dotychczasowy start bez konfiguracji przestanie działać | Start bez hasła nie wystawia chronionych API; poprawna konfiguracja uruchamia serwer; test bez rzeczywistych sekretów |
| P02 / High / 2 dni | A02,A04: hash hasła i migracja auth.json, poprawna obsługa Unicode, plik 0600; ograniczyć chmod entrypoint do wymaganych katalogów | brak; koordynacja z P01 | Średnie: migracja konta i bind mount | Stare konto migruje, nowe hasło Unicode działa, w pliku nie ma tekstu hasła, błąd zapisu nie zmienia runtime; start Docker zachowuje uprawnienia |
| P03 / High / 1–2 dni | A03,B01: TTL sesji, invalidacja po zmianie hasła, konfigurowalny Secure; początkowo jawny pojedynczy worker | P02 dla pełnej regresji password flow | Średnie: wylogowania i wdrożenia HTTP | Testy zegara, dwóch klientów i logout; stary token po zmianie hasła daje 401; produkcyjne cookie Secure; lokalny tryb udokumentowany |
| P04 / High / 1–2 dni | A01: limiter logowania per konto/źródło z ograniczoną pamięcią i poprawną polityką proxy | brak | Niskie/średnie: blokada legalnych klientów | Serie błędnych loginów dają 429, wygaśnięcie blokady działa, źródła nie blokują się wzajemnie bez potrzeby; nie ufać dowolnemu X-Forwarded-For |
| P05 / High / 1 dzień | A05: zachować poprzedni manifest przy porównywaniu segmentów; nie oznaczać nowego tekstu jako gotowe audio | brak | Niskie | Zmieniony segment regeneruje się, identyczny pomija API; częściowy manifest nie pomija nowych segmentów; pokryć WebUI i CLI |
| P06 / High / 2 dni | A06: kanoniczna tożsamość cache v2 z silnikiem, modelem, efektywną konfiguracją, hashem próbki i segmentacją | P05 | Średnie: invalidacja danych i koszt | Różne silniki/próbki/modele mają różne klucze, identyczne parametry ten sam; para ab+c/a+bc nie koliduje; stary cache nie jest bezwarunkowo używany |
| P07 / Medium / 0,5–1 dnia | B02: usunąć automatyczne trwałe zapisywanie kluczy, wyczyścić stare wpisy przy logout, ewentualny opt-in oddzielić | brak | Niskie: utrata wygody autofill | Syntetyczne klucze nie pozostają po logout; formularz i klucze serwerowe nadal działają; opis zmiany w help |

## 2. Niezawodność i odporność na awarie

| PR / priorytet / nakład | Zakres i ustalenia | Zależności | Ryzyko regresji | Testy i kryteria akceptacji |
| --- | --- | --- | --- | --- |
| P08 / High / 2–3 dni | A07,A17: unikalne staging i output per task, atomowe publish; serializer concat paths | brak; P06 ułatwia cache | Średnie: zmiana nazw pobieranych wyników | Dwa zadania z tym samym filename zachowują dwa poprawne wyniki; apostrof/spacje/Unicode działają; brak publikacji po błędzie walidacji |
| P09 / High / 2–3 dni | A07: blokada per cache, unikalne tmp i atomowy zapis chunk; dokumentacja zachowania CLI/WebUI między procesami | P06 | Średnie/wysokie: deadlock i porzucone locki | Test dwóch procesów i awarii właściciela blokady; manifest nie traci wpisów, reader nie widzi częściowego pliku; brak globalnej blokady różnych książek |
| P10 / High / 2 dni | A09: limity upload/text/rozpakowanych EPUB, bounded queue i liczba jednoczesnych kompilacji/generacji | brak | Średnie: odrzucenie dużych książek | Konfigurowalne granice, 413/429 i małe syntetyczne ZIP; odrzucone wejście nie wywołuje klienta API; pamięć nie rośnie liniowo z nieograniczoną liczbą zadań |
| P11a / High / 1 dzień | A08,A10: oznaczyć osierocone zadania Interrupted na starcie; purger tylko terminalne po finished_at | brak | Niskie/średnie: migracja SQLite | Restart nie zostawia pozornego Running; aktywny rekord starszy niż doba pozostaje; terminalny jest usuwany zgodnie z TTL |
| P11b / High / 3–5 dni | A08,A05: trwały opis zadania i wynik tłumaczenia; jawny endpoint/akcja resume z ponownym podaniem klucza, jeśli potrzebny | P06,P09,P11a | Wysokie: migracja i stan przejściowy | Kill/restart w tłumaczeniu/generacji/kompilacji; resume nie zmienia treści ani głosu i nie powtarza ukończonego API; stany/idempotencja jednoznaczne |
| P12 / Medium / 2 dni | A11,A12: poprawny suffix denoise; runner procesów z timeout, terminate/kill, cleanup i thread offload w TUI | brak | Średnie: dobór timeout do długiego audio | Test lokalnego odszumienia, zawieszonego procesu, cancellation i heartbeat UI; child process nie pozostaje; długie audio ma adekwatny budżet walidacji |
| P13 / Medium / 1–2 dni | A15,C01: klasyfikacja błędów retry (429/5xx/network), Retry-After z limitem i jitter; deadline operacji API | brak | Średnie: zmiana liczby retry | Fake 401 nie jest ponawiany, 429/503 są; deterministyczny zegar/random; brak oczekiwania rzeczywistych długich timeoutów i żadnych płatnych wywołań |
| P14 / Medium / 2 dni | A14,A15: strict ingestion i jawne kodowanie, błędy braków EPUB; bounded translation i walidacja pustych/niepoprawnych wyników | brak | Średnie: wcześniej tolerowane dane będą odrzucane | UTF-8/BOM/UTF-16/cp1250 z jawną polityką; brakujący spine; token 6000 znaków, długie cue, pusty content i błędne JSON; bez cichej utraty treści |
| P15 / Medium / 0,5 dnia | A13: niezerowy kod zakończenia CLI | brak | Niskie | Subprocess CLI: brak pliku -> !=0 przed API; udany mock pipeline -> 0 |
| P16 / Medium / 1–2 dni | A10: retencja plików powiązana ze stanem i quota dysku; sprzątanie staging po awarii | P08,P11a | Średnie/wysokie: ryzyko usunięcia cache | Dry-run, pliki aktywnego/resumable zadania zachowane, osierocone po grace period usunięte, nie wychodzi poza storage; domyślnie zachowawcza polityka |

## 3. Architektura i eliminacja długu technicznego

| PR / priorytet / nakład | Zakres i ustalenia | Zależności | Ryzyko regresji | Testy i kryteria akceptacji |
| --- | --- | --- | --- | --- |
| P17 / Medium / 2 dni | C01,A16: wyodrębnić cache/manifest/validator do core; TUI korzysta z tego samego kontraktu | P05,P06,P09 | Średnie | Ta sama książka w CLI/WebUI/TUI ma zgodne parametry i semantykę resume; dwie instancje TUI nie mieszają chunków |
| P18 / Medium / 2–3 dni | C01: mały serwis pipeline z callbackami progress, adapterami wejść i jawnym kontraktem set_voice_id; bez zmiany zachowania | P17 oraz regresje etapów 1–2 | Średnie/wysokie: zakres przenosin | Contract tests dla obu silników, porównanie kolejności segmentów i output między interfejsami; brak zależności core od FastAPI/Textual |
| P19 / Medium / 1 dzień | B03: runtime/dev deps, bezpośrednie httpx, plugin async, usunięcie zbędnych zależności po sprawdzeniu importów; lock/constraints | brak | Średnie: kompatybilność SDK | Świeży build i suite z ustalonymi wersjami; import CLI/WebUI/TUI; pip check; proces świadomej aktualizacji. Nowe zależności tylko z uzasadnieniem (np. hashowanie hasła/blokada) |

## 4. Testy, CI/CD i dokumentacja

| PR / priorytet / nakład | Zakres i ustalenia | Zależności | Ryzyko regresji | Testy i kryteria akceptacji |
| --- | --- | --- | --- | --- |
| P20 / High / 1–2 dni | C02: izolowana baza i storage testów; auth override jako fixture; CI pytest + Ruff + pip check z FFmpeg i fake API | P19 dla powtarzalności; izolację można zrobić wcześniej | Niskie | Suite nie dotyka użytkowego state.db/.env, nie potrzebuje kluczy ani sieci, ma timeout i ujawnia wiszący test; udokumentowane komendy i wersje |
| P21 / Medium / 1–2 dni | Docker smoke: start non-root, bind mount, sesja/upload syntetyczny, permission failure; brak publikacji obrazu w testach PR | P02,P19,P20 | Niskie/średnie | Obraz buduje się, proces aplikacji non-root, mount pozostaje zapisywalny, sekret nie trafia do image layer, start z niedostępnym storage daje jasny błąd |
| P22 / Medium / 2–4 dni | Windows: najpierw Python+FFmpeg smoke i ścieżki, następnie osobny PR bundlera, jeśli dystrybucja exe pozostaje celem | P08,P12,P19,P20; wymaga ustalenia kontraktu wydania | Średnie | Windows/Linux matrix; spacje/apostrof/Unicode, lokalizacja static i storage, działanie ffmpeg/ffprobe. Nie deklarować exe jako gotowego bez artefaktu sprawdzonego na czystym systemie |
| P23 / Medium / 0,5–1 dnia | README/DOCKER/PROJECT: faktyczne resume, TLS, limity, retencja, backup/migracja i różnice interfejsów; instrukcja testów | odpowiednie wdrożone PR-y | Niskie | Każda deklarowana funkcja odpowiada testowanemu zachowaniu; instrukcja odzyskania zadania po restarcie nie obiecuje niewdrożonej funkcji |

## Zalecana kolejność i bramki

1. Od razu P01–P05, P07 i P15; przygotować P20 (izolacja testów). To zamyka proste luki i daje szybkie korzyści.
2. P06, P08–P10 i P11a: nie udostępniać równoległej pracy jako niezawodnej przed izolacją plików i cache.
3. P12–P14, P11b i P16: odporność restartu, poprawność tekstu i kontrola zasobów.
4. P17–P18 dopiero po stabilizacji zachowania. P19–P21 prowadzić wcześniej równolegle organizacyjnie, bez zmiany wersji SDK w tym samym PR co naprawa pipeline.
5. P22 jako odrębna inicjatywa wydaniowa; P23 aktualizować przy każdej istotnej zmianie.

Wydanie sieciowe wymaga zaliczonych regresji auth, TTL, limitów i output isolation. Wydanie deklarujące bezpieczne resume wymaga restart testu oraz testów zgodności manifestu. Zielone mocki nie zastępują lokalnego FFmpeg smoke i odsłuchu syntetycznych segmentów. Procentowe coverage traktować pomocniczo; najpierw objąć ryzyka opisane w raporcie.

Plan realizuje PROJECT.md: kompletność audio/tekstu przed reorganizacją modułów, mały narzut zasobów, bezpieczne resume i ochrona kluczy. Nie wymaga od razu brokera zadań, mikroserwisów, OIDC ani przepisywania projektu.
