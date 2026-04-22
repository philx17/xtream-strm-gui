# 📺 xtream-strm-gui

Ein kombiniertes Tool für zwei zentrale Anwendungsfälle im IPTV/Jellyfin Umfeld.

---

## 🔥 Zwei Kernfunktionen der Anwendung

### 🧩 1. Xtream Proxy für Jellyfin

Die Anwendung fungiert als Xtream API Server, der Inhalte aus Jellyfin bereitstellt.

**Ziel:**
- Nutzung von IPTV Apps (z. B. UHF, Tivimate, IPTV Smarters)
- Zugriff auf Jellyfin Inhalte über Xtream API

**Funktionsweise:**

IPTV App → xtream-strm-gui (/proxy) → Jellyfin → Stream

**Features:**
- Auswahl bestimmter Jellyfin Bibliotheken
- Ausgabe als:
  - LiveTV
  - Filme (VOD)
  - Serien
- Automatische Stream-URLs (lokal / extern)
- XMLTV / EPG Unterstützung

---

### 📦 2. STRM Export Tool (Xtream → Jellyfin)

Die Anwendung kann Inhalte aus einer Xtream API importieren und als .strm Struktur für Jellyfin exportieren.

**Ziel:**
- IPTV Inhalte dauerhaft in Jellyfin einbinden
- Saubere Bibliotheksstruktur erzeugen

**Funktionsweise:**

Xtream API → xtream-strm-gui → STRM Files → Jellyfin Bibliothek

**Exportierte Inhalte:**
- 🎬 Filme → `.strm`
- 📺 Serien → Staffel/Episoden Struktur
- 📡 LiveTV → `.m3u` Datei

---

## 🎯 Zusammenspiel beider Funktionen

| Funktion       | Richtung                     | Zweck                    |
|----------------|----------------------------|-------------------------|
| Xtream Proxy   | Jellyfin → IPTV App        | Streaming               |
| STRM Export    | Xtream → Jellyfin          | Bibliothek aufbauen     |

---

## 🚀 Features

- Xtream API Integration (LiveTV / VOD / Series)
- Jellyfin Integration
- STRM Export:
  - Filme
  - Serien (inkl. Episodenstruktur)
- LiveTV Export als M3U
- Xtream Proxy API
- XMLTV / EPG Support
- Scheduler (Automatisierung)
- Profile-System
- Web GUI

---

## ⚙️ Konfiguration & Nutzung

---

### 🔹 Funktion 1: Xtream Proxy (Jellyfin → IPTV)

#### 📚 Bibliotheken auswählen

In der GUI:

Proxy → Bibliotheken laden

Dann auswählen:
- Filme Bibliotheken
- Serien Bibliotheken

Diese werden über Xtream bereitgestellt.

---

#### 📡 Zugriff aus IPTV App

Server URL:
http://<host>:8787/proxy/player_api.php

Username / Passwort:
→ aus GUI (Proxy Einstellungen)

---

#### 📺 Streams

LiveTV:
/proxy/live/{username}/{password}/{id}.ts

Filme:
/proxy/movie/{username}/{password}/{id}.mp4

Serien:
/proxy/series/{username}/{password}/{id}.mp4

---

### 🔹 Funktion 2: STRM Export (Xtream → Jellyfin)

#### 📥 Quelle konfigurieren

- Xtream Server URL
- Username
- Passwort

---

#### 🎯 Auswahl treffen

Kategorien auswählen:
- LiveTV Kategorien
- Movie Kategorien
- Serien Kategorien

Optional:
- Einzelne Inhalte ausschließen

---

#### 📁 Output Struktur

Beispiel:

   /output/
├── Movies/
│   └── Filmname (Jahr)/
│       └── Filmname.strm
├── Series/
│   └── Serienname/
│       └── Season 01/
│           └── S01E01.strm
└── livetv.m3u

------------------------------------------------------------------------

---

#### 📡 LiveTV Integration in Jellyfin

LiveTV wird als M3U erzeugt:

/output/livetv.m3u

Einbindung in Jellyfin:
- Live TV → Tuner → M3U hinzufügen

---

## 🌐 Endpunkte

### GUI

http://<host>:8787/

---

### Xtream Proxy

http://<host>:8787/proxy/player_api.php

---

### XMLTV / EPG

http://<host>:8787/xmltv.php

---

### Healthcheck

http://<host>:8787/healthz

---

## 🧠 Funktionsweise im Detail

---

### 📡 Proxy Flow

IPTV App  
↓  
/proxy/player_api.php  
↓  
Jellyfin API  
↓  
Stream URL  

---

### 📦 Export Flow

Xtream API  
↓  
Kategorien laden  
↓  
Items filtern  
↓  
STRM / M3U erzeugen  
↓  
Jellyfin scannt Bibliothek  

---

### 📊 EPG Flow

IPTV App  
↓  
/xmltv.php  
↓  
Tvheadend XMLTV  

---

## 📦 Projektstruktur

app/
├── main.py
├── xtream_api.py
├── jellyfin_api.py
├── proxy_core.py
├── export_core.py
├── state_core.py
├── templates/
│   ├── index.html
│   └── login.html
├── static/
│   ├── css/
│   ├── js/
│   │   ├── main.js
│   │   ├── api.js
│   │   ├── ui.js
│   │   ├── proxy.js
│   │   ├── export.js
│   │   └── schedule.js

---

## 📁 Benötigte Dateien

### Backend

- main.py
- xtream_api.py
- jellyfin_api.py
- proxy_core.py
- export_core.py
- state_core.py

---

### Frontend

- templates/index.html
- templates/login.html

JS:
- main.js
- api.js
- ui.js
- proxy.js
- export.js
- schedule.js

---

## 🔐 Sicherheit

- GUI nur im lokalen Netzwerk erreichbar
- Proxy öffentlich nutzbar
- Login-System für GUI
- Jellyfin API Key geschützt

Empfohlen:
- Reverse Proxy (NGINX)
- HTTPS
- Rate Limiting / IP Ban

---

## 🧪 Debug / Testing

curl http://localhost:8787/healthz
curl “http://host:8787/proxy/player_api.php?username=xxx&password=xxx&action=get_live_streams”
---

## 🐳 Docker
docker run -d 
-p 8787:8787 
-v /mnt/user/appdata/xtream:/data 
xtream-strm-gui

---

## 💡 Roadmap

- EPG Mapping verbessern
- Multi-User Proxy
- Rate Limiting + Ban
- Websocket Logs
- Backup / Restore

---

## ❤️ Fazit

Dieses Projekt vereint:

- Xtream Proxy  
- Jellyfin Bridge  
- STRM Generator  
- IPTV Backend  

in einer einzigen Anwendung.
