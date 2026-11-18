# Punkt 5: hasła, CSRF i metadane XML

Stan kodu na 2026-11-18, gałąź `fix/web-request-security`. Numeracja pochodzi
z listy pozostałych prac po ochronie żądań. Nie budowano, nie publikowano ani
nie wdrażano obrazu Docker. Wdrożenie LAN pozostaje bez zmian.

## Hasła i migracja

- Nowa konfiguracja bez `storage/auth.json` oraz zmiana hasła wymagają
  12–1024 znaków, w tym co najmniej 12 po pominięciu otaczających białych znaków.
  Hasło jest przechowywane i weryfikowane bez przycinania, z obsługą Unicode.
  Nie wprowadzono obowiązkowych klas znaków ani nowej biblioteki kryptograficznej.
- Istniejący zapisany krótki sekret nadal pozwala zweryfikować właściciela.
  Dotyczy to również atomowej migracji dawnych plików z plaintextem do PBKDF2.
  Taki login daje wyłącznie sesję zmiany hasła: status/logowanie/wylogowanie
  oraz formularz zmiany hasła. Dostęp do danych, konfiguracji, generacji i resume
  jest blokowany kodem `403`, dla uploadów także przed body i rezerwacją kolejki.
- Login i status zwracają `requires_password_change`. UI otwiera ustawienia
  i blokuje generator; odświeżenie strony nie omija ograniczenia serwera.
  Zmiana wymaga starego hasła i poprawnego pochodzenia żądania, zapisuje tylko
  hash i odwołuje wszystkie sesje. Po błędzie zapisu sesja pozostaje ograniczona,
  lecz pozwala ponowić zmianę. Logout/expiry usuwają też stan ograniczenia.
- Jeśli dotychczasowe krótkie hasło pochodzi tylko z `.env`/środowiska i nie ma
  auth file, należy wydłużyć `APP_PASSWORD` przed aktualizacją — nowy start
  zostanie w przeciwnym razie odrzucony. Zapisany auth file ma pierwszeństwo.

## Pochodzenie żądań i przeglądarka

- Zmiany stanu, w tym login/logout, wymagają zgodnego `Origin`: protokół,
  hostname i port, z normalizacją portów domyślnych. Obca subdomena, inny port,
  `null` i zduplikowany Origin są odrzucane przed parsowaniem lub pracą dostawcy.
- Przy braku Origin klient musi podać `X-Requested-With: Booksmith`; frontend
  robi to automatycznie. To nagłówek niesimple, którego obca strona nie może
  dodać z JavaScript bez preflight CORS. Aplikacja nie włącza CORS. Nagłówek nie
  nadpisuje błędnego Origin, a originless `Sec-Fetch-Site: same-site/cross-site`
  również jest blokowane. Aktualizacji wymagają własne headerless klienty HTTP;
  CLI/TUI nie korzystają z tych endpointów.
- Kontrola nie ufa surowym `X-Forwarded-*`. HTTPS proxy musi poprawnie zachować
  Host i przekazywać schemat przez jawnie zaufane ustawienia Uvicorna.
- CSP dopuszcza skrypty i połączenia aplikacji tylko z własnego origin,
  blokuje obiekty, zmianę base URL i osadzanie w ramkach. Zachowano inline CSS
  i istniejące źródła Google Fonts. Dodano DENY, nosniff, no-referrer i no-store
  dla root/API. HSTS i rzeczywisty TLS nadal należą do terminatora HTTPS.
- Domyślne interaktywne Swagger/ReDoc zostały wyłączone, ponieważ ich CDN
  i skrypty inline naruszałyby CSP. Schemat `/openapi.json` pozostaje dostępny.

## EPUB XML

- Parser container/OPF odrzuca DTD w callbacku parsera przed jego podzbiorem
  wewnętrznym i ekspansją encji. Nie jest to regex zależny od kodowania bajtów.
- Dodano `MAX_EPUB_XML_DEPTH=64` i `MAX_EPUB_XML_ELEMENTS=10000` na dokument
  metadanych. Pozostałe limity ZIP/bajtów/tekstu działają jak wcześniej.
- Zwykły doctype HTML/XHTML rozdziałów pozostaje obsługiwany przez HTMLParser,
  bez pobierania zewnętrznych DTD i ekspansji niestandardowych encji XML.
- To zabezpieczenia aplikacji, nie poprawki natywnych CVE Expat/libxml2.

## Dowody i testy

- Pełna izolowana regresja: **645 passed**, 4 ostrzeżenia, 72,06 s.
- Nowy zestaw bezpieczeństwa: **84 passed**; obejmuje odrzucenie Origin przed
  odczytem body, IPv6/default ports, granice haseł, migrację obu formatów auth,
  błąd zapisu, odwołanie sesji, DTD w UTF-8/UTF-16 i granice kształtu drzewa.
- Ruff, kontrola składni JavaScript i `git diff --check`: poprawne.
- Rzeczywisty Chromium **143.0.7499.4**, jednorazowy lokalny serwer i fikcyjne
  konto: krótki login, wymuszona zmiana po odświeżeniu, zapis nowego hasła,
  ponowne pełne logowanie oraz blokada wykonania skryptu inline przeszły.
- Przeglądarka wysłała formularz z innego portu tego samego site **razem z cookie
  ofiary**. Serwer zwrócił `403`, a konfiguracja pozostała bez zmian. To potwierdza
  ochronę także wtedy, gdy samo SameSite nie blokuje wysłania ciasteczka.
  Brak nieobsłużonych błędów JavaScript; nie wykonywano płatnych żądań.
- Brak nowych zależności aplikacji. Przeglądarkę i brakujące biblioteki testowe
  uruchomiono wyłącznie z katalogu tymczasowego, bez instalacji w systemie.

Wyniki maszynowe: [remediation-5.json](security-2026-11-18/remediation-5.json).
Skrypty/logi lokalnych prób pozostały w `/tmp/mistral-security-audit/`; nie jest
to trwałe archiwum. Test Chromium nie zastępuje natywnego Windows/macOS,
Firefox/Safari ani akceptacji certyfikatu i proxy we wdrożeniu.

## Co jeszcze pozostało

Punkt 5 jest zakończony w kodzie, ale nie zamyka całego planu:

1. Aktualizacja kontraktu SDK/OpenTelemetry i właściwe poprawione buildy
   FFmpeg/libxml2 — dwa CVE OpenTelemetry pozostają w lockach.
2. Pełna izolacja filesystemu/sieci procesów i bezpieczna ekstrakcja MOBI;
   natywne limity/akceptacja poza Linuksem.
3. Łańcuch wydania Windows, integralność binariów i cykliczne skany CVE w CI.
4. Dopiero po osobnym poleceniu: build, smoke i skan nowego obrazu, a następnie
   wdrożenie/akceptacja LAN z zapisanym digestem i regułami dostępu.

Zgodność z PROJECT.md: zachowano jedno konto i worker, pin SDK, format hashy,
politykę retry, cache oraz pipeline audio. Migracja ogranicza stare konta bez
ich cichego usuwania, a testy używają prywatnego tymczasowego storage.
