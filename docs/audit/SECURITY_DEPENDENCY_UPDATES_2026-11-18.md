# Aktualizacje SDK i bibliotek natywnych

Zmiany na gałęzi `fix/web-request-security`, 2026-11-18. **Nie zbudowano ani nie
opublikowano obrazu Docker. Nie zmieniono systemowych pakietów hosta ani LAN.**

## Python i kontrakt SDK

- `mistralai 2.4.9 → 2.10.1`, OpenTelemetry API `1.39.1 → 1.45.2`,
  semantic-conventions `0.60b1 → 0.66b2`. Pozostajemy przy HTTPX i API SDK 2.x,
  bez migracji do SDK 3.x/HTTPX2.
- Odtworzono oba locki z hashami; graf nie potrzebuje już importlib-metadata
  ani zipp. Nowych pakietów Pythona nie dodano. PROJECT.md odzwierciedla nowy pin.
- Osobne czyste instalacje runtime/dev z hashami i wheel-only przeszły kontrolę
  zależności. Po usunięciu pip/setuptools/wheel świeży runtime importuje CLI,
  TUI, WebUI i obie fabryki klientów; nie wymaga bibliotek vendored instalatorów.
- Nowe testy używają rzeczywistego SDK z HTTPX MockTransport: serializacja
  głosu presetowego i referencji, odczyt audio, tłumaczenie i JSON batches,
  listy modeli/głosów, brak ukrytych retry i sanitizacja błędu HTTP. Bez płatnych
  żądań. V1 listy głosów działa, ale SDK ostrzega o przyszłym wycofaniu paginacji.
- Bieżący pip-audit: **0 znanych zgłoszeń w obu lockach**, zamiast dwóch CVE
  OpenTelemetry pozostawionych po poprzednim etapie. To wynik grafu Pythona,
  nie skan gotowego obrazu i nie gwarancja braku nieznanych podatności.

## FFmpeg i libxml2

- Sprawdzono aktualne źródła producentów i Debian Security Tracker. Stabilny
  trixie nadal nie ma wymaganych poprawek dla wskazanych dekoderów FFmpeg oraz
  nowszego libxml2. Nie mieszano stable z sid.
- Przygotowano wieloetapowy Dockerfile: kompilacja FFmpeg **9.0.2** z przypiętego
  źródła i SHA-256, profil audio, bez libxml2, sieci i kodeków wideo. Runtime
  instaluje LAME oraz dotychczasowe narzędzia, nie dystrybucyjny FFmpeg.
  Usunięcie niepotrzebnej zależności XML zastępuje próbę aktualizacji jej ABI.
- Pobrano archiwum i zweryfikowano podpis źródła FFmpeg, następnie skompilowano
  dokładnie ten profil **lokalnie poza Dockerem**. Wersja ffmpeg/ffprobe: 9.0.2.
  `ldd` pokazał tylko libc, libm, LAME i loader — bez libxml2. Lista protokołów
  zawiera wyłącznie file/pipe. SHA jest sprawdzane przed rozpakowaniem.
- W Windows workflow przypięto archiwum Gyan 9.0.2 i zweryfikowany SHA-256;
  usunięto fallback do zmiennego latest. Błąd hash kończy build. Nie uruchomiono
  Windows workflow ani EXE; ogólny build Windows nadal zawiera więcej funkcji
  i wymaga weryfikacji bibliotek osadzonych, w tym libxml2.
- Dokładne wersje, hashe, źródła, profil i granice opisuje
  [NATIVE_DEPENDENCIES.md](../NATIVE_DEPENDENCIES.md).

## Weryfikacja i pozostałe ryzyka

- **651 testów** przeszło na nowym SDK i lokalnym FFmpeg 9.0.2, 5 ostrzeżeń,
  86,09 s. Testy obejmują ciągłość/padding/decoded duration oraz MP3/WAV/M4B.
- Portable smoke z polskimi znakami: **223 passed**, 4 ostrzeżenia, 28,09 s
  (podzbiór testów). Ruff, składnia sh i `git diff --check` poprawne.
- Skrypt native-build odrzuca zmieniony tarball przed kompilacją. Nowy kontekst
  smoke Dockera zawiera helper budowania, ale samego smoke nie uruchamiano,
  ponieważ tworzyłby nowy obraz wbrew poleceniu operatora.
- 9.0.2 poprawia wcześniejsze CVE ADX/CAF, ale nie wszystkie znane CVE FFmpeg.
  Profil wyłącza wiele podatnych komponentów; pozostaje m.in. kod MOV dotyczący
  `CVE-2026-107678`, używany do odczytu własnego M4B, niedostępny dla uploadu
  referencji. Nie uznajemy go za naprawiony. Nadal potrzebna jest pełna izolacja
  procesów i okresowy przegląd nowszych poprawek.
- Po późniejszym zezwoleniu: build/smoke/skan gotowego obrazu i akceptacja LAN.
  Osobno: natywny Windows i jego biblioteki, łańcuch wydania/CI. Nie ogłaszamy
  obrazu ani całego projektu jako „zero CVE”.

Wyniki maszynowe: [dependency-updates.json](security-2026-11-18/dependency-updates.json).
Historyczne raporty pozostają zapisem wcześniejszych etapów; ich stare piny
nie opisują aktualnego locka. Wersja przygotowania głosu pozostaje 3: parametry
normalizacji się nie zmieniły, a tożsamość cache obejmuje przetworzone bajty.
Zmiana natywnego kodera może zmienić ten fingerprint i spowodować ponowną
generację dla referencji; gotowe audiobooki nie są usuwane.

Zgodność z PROJECT.md: zachowano kontrakt payloadów, modele, retry, ciągłość
audio i atomową publikację. Nowy kontrakt SDK jest zapisany w projekcie, oba
locki zaktualizowano razem, a wszystkie próby używały fikcyjnych kluczy/transportów.
