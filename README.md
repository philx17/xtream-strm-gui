# xtream-strm-gui (GHCR-ready)

Dieses ZIP ist ein **fertiges GitHub-Repo**:
- FastAPI Web-GUI (Xtream Credentials, Auswahl, Sync, Cleanup)
- Speichert Playlist + Catalog lokal in `/data`
- Erzeugt `.strm` Dateien nach `/output`
- GitHub Actions Workflow baut & published nach **GHCR** (`ghcr.io/<user>/<repo>:latest`)
- Dockerfile enthält **vim**

## Ordner-Mounts (Unraid)
- Host: `/mnt/user/appdata/xtream-strm-gui`  -> Container: `/data`
- Host: `/mnt/user/Media/JellyfinPlugin`     -> Container: `/output`

## GitHub Setup (kurz)
1. Neues Repo auf GitHub anlegen (z.B. `xtream-strm-gui`)
2. Inhalt dieses ZIP ins Repo hochladen (oder `git add/commit/push`)
3. In GitHub: **Actions** müssen erlaubt sein (default OK)
4. Nach dem ersten Push auf `main` wird gebaut:
   - `ghcr.io/<github-user>/<repo>:latest`

> Für Public-Repos ist GHCR Pull ohne Login möglich.

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

