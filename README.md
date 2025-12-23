# OpenGeoCoder

[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Build Status](https://img.shields.io/github/actions/workflow/status/your-org/your-repo/ci.yml)]()

Dieses Projekt ist ein quelloffener Geocoder.

---

## Inhaltsverzeichnis

- [Features](#features)
- [Architektur](#architektur)
- [Anforderungen](#anforderungen)
- [Getting Started](#getting-started)
- [Nutzung](#nutzung)
- [Konfiguration](#konfiguration)
- [Lizenz](#lizenz)

---

## Features

- Python Webserver (Flask)
- Solr - Adressdatenbank
- docker compose zum Bündeln und deployen der Applikation

---

## Architektur

Das Projekt hat zwei Komponenten:

```
[Python Webserver] --> [Solr]
```

- **Python Webserver**: Stellt eine API bereit, die Adresskomponenten als Input nimmt und passende Ergebnisse zurückliefert.
- **Solr**: Dient als Dokumentdatenbank für die Adressdaten.

---

## Anforderungen

- docker compose
- git 

---

## Getting Started

### Klonen des repository

```bash
git clone https://github.com/your-org/myproject.git
cd myproject
```

### Setzen der Umgebungsvariablen

```bash
cp .env.example .env
# Edit .env if needed
```

### Starten der Applikation

```bash
docker compose up --build -d
```

### Daten

Das Repo kommt mit Demodaten zum Testen der Applikation. Für den konkreten Anwendungsfall müssen anwendungsspezifische Daten in solr importiert werden.
Zu diesem Zweck sind Beispielskripte im Ordner helper_functions hinterlegt die genutzt werden können, aber vermutlich individuell je nach Anwendungsfall angepasst werden müssen.

### Erreichbarkeit der Applikationen

- **Geokoder**: [https://localhost](https://localhost)
- **Solr Admin UI**: [http://localhost:8983/solr](http://localhost:8983/solr)

Wenn die Anwendung produktive gestellt wird, sollte solr nicht exposed werden.

### Stoppen der services:

```bash
docker compose down
```

---

## Nutzung

- API-Dokumentation:

[swagger](https://opengeocoder.dai.institute/swagger/)

- Solr core `addresses`: Der Port sollte im Produktivbetrieb nicht verwendet werden. Dazu muss die entsprechende Zeile im docker-compose.yml einfach auskommentiert werden.

```
http://localhost:8983/solr/addresses
```

- Example API usage (replace with your endpoints):

https://opengeocoder.dai.institute/geocode?ort=wedel&plz=22880&hnr=2a&stn=rathaus

Die verwendeten Daten unterliegen unterschiedlicher [Lizenzen](https://github.com/data-analytics-institute-AG/dai_open_geocoder/blob/main/Lizenzvereinbarung_OGC_19122025-V1.pdf)


---

## Konfiguration

### Umgebungsvariablen

Der Geokoder ist konfigurierbar ohne den Code selbst ändern zu müssen. Dazu ist in der .env.example eine beispielhafte Konfiguration vorhanden. Die Konfiguration unterstützt momentan 3 Parameter:

- GEOCODER_PARAMS: eine einfach kommaseparierte Liste von durchsuchbaren Parametern. Die Parameter müssen namentlich mit indizierten Feldern im Solr-Core übereinstimmen.
- GEOCODER_STRATEGIES: Ein JSON, welches kontrolliert in welcher Reihenfolge welche Art von Anfragen gemacht werden. Dabei können die durchsuchten Felder und die Strategie (Exakt oder Fuzzy) festgelegt werden.
- GEOCODER_DEFINITION: Konfiguration für die Übersetzung von technischen Namen aus solr in das json-Ergebnis.

---

## Lizenz

Das Projekt läuft unter der MIT Lizenz — siehe [LICENSE](LICENSE) für Details.



