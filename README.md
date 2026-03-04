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
git clone https://github.com/data-analytics-institute-AG/dai_open_geocoder
cd dai_open_geocoder
```

### Setzen der Umgebungsvariablen

```bash
nano backend/conf.json
# Anpassen an die eigenen Bedürfnisse
```

### Importieren der Daten in den SolrCore

Das Ziel des Geokoders ist es möglichst flexibel zu sein und ohne Änderungen im Code mit jedem beliebigen Solr-Core zu arbeiten. Für die direkte Geokodierung gibt es daher keine Einschränkungen, mit welchen Feldern der Solr Core befüllt wird. Für die Reversegeokodierung ist es aber unbedingt erforderlich ein Feld "koordinate" vom Typ "location" zu haben. Die Daten müssen momentan in einem Core mit dem Namen "addresses" liegen. In einer zukünftigen Version des Geokoders ist es denkbar, dass dieser Name auch konfigurierbar gemacht wird.
Die Feldnamen im SolrCore, die durchsuchbar sein sollen müssen identisch zu den durchsuchbaren Feldnamen in der conf.json sein.

### Starten der Applikation

```bash
docker compose up --build -d
```

### Daten

Das Repo kommt mit Demodaten zum Testen der Applikation. Für den konkreten Anwendungsfall müssen anwendungsspezifische Daten in solr importiert werden.
Zu diesem Zweck sind Beispielskripte im Ordner helper_functions hinterlegt die genutzt werden können, aber vermutlich individuell je nach Anwendungsfall angepasst werden müssen.

### Erreichbarkeit der Applikationen

- **Geokoder**: [https://localhost](http://localhost:5000)
- **Solr Admin UI**: [http://localhost:8983/solr](http://localhost:8983/solr)

Wenn die Anwendung produktive gestellt wird, sollte solr nicht exposed werden.

### Stoppen der services:

```bash
docker compose down
```

### Reverseproxy / https

In Produktion ist es empfehlenswert die Anwendung hinter einen ReverseProxy, wie z.B. einen NGinx zu legen. Es gibt online viele Beispiele, wie das direkt in einem docker compose Setup integriert werden kann. Daher wird dieses Thema nicht direkt in diesem Repo behandelt.

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

Der Geokoder ist konfigurierbar ohne den Code selbst ändern zu müssen. Dazu ist in der conf.json eine beispielhafte Konfiguration vorhanden. Die Konfiguration unterstützt momentan 2 Parameter:

- params: eine einfach kommaseparierte Liste von durchsuchbaren Parametern. Die Parameter müssen namentlich mit indizierten Feldern im Solr-Core übereinstimmen.
- strategies: Ein JSON, welches kontrolliert in welcher Reihenfolge welche Art von Anfragen gemacht werden. Dabei können die durchsuchten Felder und die Strategie (Exakt oder Fuzzy) festgelegt werden.

---

## Lizenz

Das Projekt läuft unter der MIT Lizenz — siehe [LICENSE](LICENSE) für Details.
