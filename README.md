# xtream-strm-gui (GHCR-ready)

Dieses ZIP ist ein **fertiges GitHub-Repo**:
- FastAPI Web-GUI (Xtream Credentials, Auswahl, Sync, Cleanup)
- Speichert Playlist + Catalog lokal in `/data`
- Erzeugt `.strm` Dateien nach `/output`
- GitHub Actions Workflow baut & published nach **GHCR** (`ghcr.io/philx17/xtream-strm-gui:latest`)
- Dockerfile enthält **vim**

## Ordner-Mounts (Unraid)
- Host: `/mnt/user/appdata/xtream-strm-gui`  -> Container: `/data`
- Host: `/mnt/user/Media/JellyfinPlugin`     -> Container: `/output`

## Unraid
Repository im Container:
`ghcr.io/<github-user>/<repo>:latest`

Port:
- Container: 8787
- Host: 8787 (oder frei)

ENV (optional):
- `TZ=Europe/Berlin`
- `GUI_USER=admin`
- `GUI_PASS=deinpasswort`

## Lokal testen
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```
GUI: http://localhost:8787

# 📺 Xtream STRM Sync Tool

**Xtream → STRM Export mit LiveTV-Picons, Backdrops, Dedupe, Cleanup &
Jellyfin-Support**

Dieses Tool verarbeitet Xtream-/M3U-Playlists und erzeugt strukturierte
**.strm-Dateien** für **LiveTV, Movies und Series** -- optimiert für
**Jellyfin**, **Plex** oder **Kodi**.

------------------------------------------------------------------------

## ✨ Features

### LiveTV

-   Automatisches Picon-Matching\
-   Erstellt `poster.png` **und** `backdrop.png`

### Movies

-   Genre-Ordnerstruktur\
-   **Dedupe nach normalisiertem Titel**\
-   Verhindert doppelte Filme aus mehreren Kategorien

### Series

-   Show- & Season-Struktur\
-   Korrekte Episoden-Namen (`SxxEyy`)

### Cleanup & Delete

Wenn ein `.strm` entfernt wird: - Entfernt Artwork (`poster`,
`backdrop`, `logo`, `landscape`) - Optional `.nfo`, `.srt`, `.jpg` -
Entfernt leere Ordner & Folder-Art

------------------------------------------------------------------------

## 📁 Ausgabe-Struktur

    Output/
     ├─ LiveTV/
     │   └─ Category/
     │       └─ Channel Name/
     │           ├─ Channel.strm
     │           ├─ poster.png
     │           └─ backdrop.png
     ├─ Movies/
     ├─ Series/
     └─ .xtream_state/
         └─ manifest.json

------------------------------------------------------------------------

## 🧠 Picon Support

Place your Picons here:

    /output/picons/*.png

Automatisches Matching mit Fuzzy-Logik.

------------------------------------------------------------------------

## 🎬 Movie Dedupe

Entfernt doppelte Filme automatisch anhand normalisierter Titel\
(z. B. HD/FHD/UHD Varianten)

------------------------------------------------------------------------

## 🧹 Cleanup Behavior

Beim Löschen einer STRM werden automatisch entfernt:

    *-poster.jpg
    *-backdrop.jpg
    *-logo.png
    *.nfo
    *.srt

------------------------------------------------------------------------

## ⚙️ Core Function

``` python
run_sync(
    m3u_text: str,
    out_dir: Path,
    allow_cfg: dict,
    sync_delete: bool = True,
    prune_sidecars: bool = False
)
```

------------------------------------------------------------------------

## 🧠 Manifest System

State-Datei:

    .xtream_state/manifest.json

------------------------------------------------------------------------

## 🚀 Recommended Flow

1.  Playlist laden\
2.  Kategorien auswählen\
3.  Sync starten\
4.  Jellyfin scannt Medien

------------------------------------------------------------------------

## ❤️ Credits

Built for Jellyfin + Xtream + Docker + Unraid power users.
