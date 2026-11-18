# Realizacja punktów 2–3: pliki wejściowe i zależności

Stan na 2026-11-18, gałąź `fix/web-request-security`. Numeracja odnosi się do
listy pozostałych prac po wdrożeniu ochrony żądań. **Nie budowano ani nie
publikowano obrazu Docker i nie zmieniano wdrożenia LAN**, zgodnie z poleceniem.

## Zabezpieczenia przetwarzania

- Próbki głosu: tylko MP3 lub PCM WAV, zgodne rozszerzenie i nagłówek, wymuszony
  demukser, lista dozwolonych kodeków i protokół `file`. Playlisty, CAF/ADX oraz
  kompresowane kodeki WAV nie przechodzą tej ścieżki.
- Limit domyślny 30 s. Dekodowany jest najwyżej dodatkowy sekundowy fragment,
  aby wykryć przekroczenie i odrzucić próbkę, zamiast wysłać obcięty dźwięk.
  Wynik: odszumione mono 24 kHz PCM s16 WAV. Oryginał nie jest modyfikowany.
- Usunięto fallback do oryginału. Błąd dekodowania, czasu lub limitu zasobów
  zatrzymuje przygotowanie głosu. Wywołanie TTS z samą niezweryfikowaną ścieżką
  też jest odrzucane. Nieudana próba usuwa poprzednią konfigurację głosu klienta.
- WebUI wykonuje preflight głosu przed zapisaniem zadania i rozpoczęciem płatnego
  tłumaczenia/TTS. Oryginał zachowuje się w prywatnym snapshotcie; przy wykonaniu
  zadania dekodowanie jest powtarzane tymi samymi regułami.
- Decoder otrzymuje prywatny katalog roboczy i środowisko bez kluczy API,
  konfiguracji proxy, `FFREPORT` i zmiennych loadera. Ma limit czasu, rozmiaru
  wyniku, 16 MiB na pojedynczą alokację i jeden wątek dekodera/filtra.
- Na Linuksie `prlimit` narzuca 512 MiB przestrzeni adresowej, limit CPU,
  rozmiaru pliku i zerowy limit core dump. Brak narzędzia blokuje dekodowanie.
  Dodano util-linux do Dockerfile. Limity nie obejmują całego długiego audiobooka.
- Asynchroniczny runner zachowuje najwyżej 64 KiB stdout i stderr na strumień.
  Przekroczenie zabija proces, opróżnia potoki i zbiera potomka. Zachowano obsługę
  timeoutów i wielokrotnego anulowania.
- WebUI odrzuca upload oraz resume MOBI (`415`) przed ekstrakcją lub claimem
  zadania. Pliki nie są usuwane; można je przekonwertować do EPUB/TXT.
  CLI/TUI zachowują MOBI wyłącznie dla zaufanych lokalnych plików.

Przetwarzanie referencji ma teraz wersję **3**. Presety i istniejące audiobooki
pozostają bez zmian. Stare cache i snapshoty klonowanego głosu nie są ponownie
używane; ponowne przesłanie takiego zadania może oznaczać nowe opłaty API.

## Zależności i przyszły build

- AnyIO `4.13.0 → 4.14.2`, python-dotenv `0.21.0 → 1.2.2`, dev-only uv
  `0.11.7 → 0.13.4`. Odtworzono oba locki z hashami. Bez nowych pakietów Pythona.
- Zachowano `mistralai==2.4.9` oraz wynikający z niego kontrakt OpenTelemetry.
  Skan locków: runtime **5 → 2**, dev **7 → 2** unikalne podatności. Pozostały
  `CVE-2026-114603` i `CVE-2026-126360` w opentelemetry-api. Aktualizacja SDK lub
  backport to następny osobny punkt, a nie pominięty konflikt resolvera.
- Dockerfile wskazuje jawną gałąź trixie i digest manifestu oficjalnej bazy,
  zweryfikowany odczytem rejestru. Instaluje zlib jawnie i sprawdza minimum
  `1:1.3.dfsg+really1.3.1-1+deb13u1`, aby przyszły build nie przyjął znanej
  podatnej wersji. Apt pozostaje źródłem aktualizacji pakietów systemowych.
- Po instalacji locka i `pip check` Dockerfile usuwa pip/setuptools/wheel razem
  z vendored bibliotekami. Odtworzono tę operację w czystym venv runtime i
  potwierdzono działanie importów CLI/TUI/WebUI oraz obu fabryk klientów.

## Weryfikacja

- Pełne testy offline w nowym venv: **561 passed**, 4 ostrzeżenia, 63,53 s.
- W tym **21 nowych przypadków** dla plików, kodeków, czasu, budżetów wyjścia,
  przepełnienia potoków, środowiska bez sekretów, braku fallbacku i blokady MOBI.
- Oba locki zainstalowano osobno z weryfikacją hashy/wheel-only; `pip check`
  przeszedł dla obu. Ruff i `git diff --check` przeszły.
- Portable smoke w katalogu z apostrofem i polskimi znakami: **133 passed**,
  3 ostrzeżenia, 22,70 s. To podzbiór powyższych testów, nie dodatkowe 133 przypadki.
- Testy używały prawdziwego lokalnego FFmpeg i syntetycznego audio, bez żądań
  do dostawców. [Wynik maszynowy](security-2026-11-18/remediation-2-3.json)
  zawiera hashe locków i pozostałe zgłoszenia.

## Granice i dalsza akceptacja

To ograniczenie powierzchni parserów i zasobów, **nie pełny sandbox systemowy**.
Proces ma uprawnienia użytkownika aplikacji do filesystemu. Samo usunięcie kluczy
ze środowiska nie powstrzyma dowolnego kodu natywnego przed odczytem plików tego
użytkownika. Pełna izolacja filesystemu/sieci oraz przywrócenie bezpiecznej
ekstrakcji MOBI pozostają osobną pracą. Windows/macOS nie mają linuksowego
twardego limitu całkowitej pamięci; wymagają własnej izolacji/akceptacji natywnej.

Nie twierdzimy, że zainstalowany FFmpeg/libxml2 jest już pozbawiony CVE.
Aktualizacja ich buildów to kolejny punkt. Zlib i usunięcie vendored instalatorów
w rzeczywistym obrazie wymagają późniejszego, jawnie zleconego buildu, smoke
kontenera i ponownego skanu. Nie uruchamiano `scripts/docker_smoke.py`, ponieważ
buduje nowy obraz. Istniejący tag `mistral-tts:security-1-2` nadal oznacza
wcześniejszy etap i nie zawiera obecnych zmian.

Zmiany odpowiadają PROJECT.md: ograniczają zasoby i chronią klucze, nie zmieniają
kompilacji audiobooka ani polityki retry, zachowują pin SDK i świadomie wersjonują
zmianę przygotowania głosu. Dokumentację zaktualizowano o ograniczenie MOBI i
platformowe granice zabezpieczeń.
