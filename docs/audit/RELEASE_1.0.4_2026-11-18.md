# Wydanie Docker 1.0.4 — 2026-11-18

Opublikowano `marcinlis82/mistral-tts:1.0.4` dla **linux/amd64** z commita
`bf470cf9db2d5d241654f6ee6b7a66840d13185e`.
Dokumentacja wyników wydania jest dopisana osobnym commitem po publikacji;
nie zmienia kodu runtime obrazu. PR do main: [#30](https://gitea.marcin-lis.pl/fox/mistral-tts/pulls/30).
PR pozostaje otwarty; nie scalano go ani nie zmieniano wdrożenia LAN.

- Digest manifestu: `sha256:6a33ab36dcbe5a1b0d18878a1dc19646fda1eddaf2c30d66e416d1a47c4410a5`.
- Digest konfiguracji / lokalny image ID: `sha256:24f5b4c3c179799786f531f412d1fef7c7a66b88173f6705d00fd05d51a683ae`.
- Odczyt manifestu i konfiguracji bezpośrednio z Docker Registry potwierdził
  zgodność z lokalnie przetestowanym obrazem, platformą i etykietami OCI.
- Opublikowano tylko tag `1.0.4`; istniejące wersje oraz `latest` pozostawiono.

## Weryfikacja

- **7/7 Docker smoke**, w tym start jako UID 1000, bind mount, błędy uprawnień
  i niebezpiecznych danych logowania, prawdziwe HTTP upload/kompilacja/download,
  zachowanie pliku po restarcie oraz brak znaczników plików konfiguracyjnych
  w każdej warstwie obrazu. Testowany obraz otrzymał dokładnie publikowany tag.
- Python **3.11.18**, Mistral SDK **2.10.1**, OpenTelemetry API **1.45.2**,
  AnyIO **4.14.2**, python-dotenv **1.2.2**. Brak pip/setuptools/wheel w runtime.
- FFmpeg/ffprobe **9.0.2**. `ldd` potwierdził brak libxml2; brak pakietów libxml2
  i dystrybucyjnego ffmpeg. Protokoły tylko file/pipe; brak dekodera mp3adu.
  Domyślne polecenie Uvicorn ma `--no-proxy-headers`.
- Wcześniejsze testy tego kodu: **651 passed**, **223 portable smoke** (podzbiór),
  Ruff i kontrole zależności poprawne. Używano wyłącznie syntetycznych kluczy,
  lokalnego transportu i audio; brak płatnych wywołań API.

## Wynik CVE i granice

Trivy **0.76.2**, Debian **13.7**, baza z **2026-11-18**:

| Zakres | Wiersze | Unikalne CVE | Critical | High | Medium | Low | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pakiety systemowe | 218 | 96 | 0 | 11 | 44 | 35 | 6 |
| Wykryte pakiety Pythona | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Nie ma wierszy ze wskazaną poprawioną wersją w użytym źródle danych Debiana.
To nie oznacza, że wszystkie zgłoszenia są nieosiągalne lub że obraz jest
wolny od podatności. Dalszy przegląd obejmuje m.in. util-linux, SQLite i ncurses;
nie wyciszano ich szeroką allowlistą. Nie uruchamiać aplikacji jako privileged
ani z dodatkowymi uprawnieniami systemowymi.

Samodzielnie kompilowany FFmpeg nie jest kompletnie pokrywany skanem pakietów.
Znany kod MOV związany z CVE-2026-107678 nadal istnieje; służy do weryfikacji
własnego M4B, a nie referencji MP3/PCM WAV. Pozostają wymagania izolacji procesów
oraz śledzenia nowych poprawek; szczegóły i źródła w
[NATIVE_DEPENDENCIES.md](../NATIVE_DEPENDENCIES.md).

Zdalny Linux CI dla commita obrazu zakończył się przed testami: checkout wskazuje
`http://gitea:3000`, a runner zgłasza `Could not resolve host: gitea`.
Windows oczekuje na runner; natywna akceptacja nie została potwierdzona.
Nie zmieniano konfiguracji infrastruktury CI w ramach wydania.

Wyniki maszynowe: [release-1.0.4.json](security-2026-11-18/release-1.0.4.json),
[pełna lista wykrytych zgłoszeń](security-2026-11-18/release-1.0.4-findings.csv).
Starsze raporty zachowują wyniki z poszczególnych etapów, w tym wcześniejszy
zakaz budowania obrazu, odwołany późniejszą zgodą na to wydanie.

## Aktualizacja

Przed wymianą kontenera zatrzymać starą instancję i wykonać kopię całego storage.
Zmiany haseł, Origin/CSRF, MOBI i tożsamości referencji opisuje
[README](../RELEASE_NOTES.md#security-update--104). TLS i kontrola dostępu LAN
pozostają ustawieniami wdrożenia; publikacja na Docker Hub ich nie zmienia.

```bash
docker pull marcinlis82/mistral-tts:1.0.4
# Alternatywnie: pobranie po dokładnym digescie
docker pull marcinlis82/mistral-tts@sha256:6a33ab36dcbe5a1b0d18878a1dc19646fda1eddaf2c30d66e416d1a47c4410a5
```

Zgodność z PROJECT.md: oba locki sprawdzono razem; testy obejmują ciągłość audio,
kontrakty SDK i ograniczone retry. Publikowano wyłącznie przetestowany artefakt,
bez deklaracji natywnej akceptacji Windows ani braku wszystkich CVE.
