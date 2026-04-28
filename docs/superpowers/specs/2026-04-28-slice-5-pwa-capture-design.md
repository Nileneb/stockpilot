# Slice 5 — Mobile / PWA Capture

**Date:** 2026-04-28

## Goal

Mitarbeiter geht durchs Lager, öffnet `/capture/` auf dem Handy (oder Add-to-Homescreen-PWA), tippt auf "Foto aufnehmen", Kamera startet, Foto hochladen → Inferenz läuft automatisch → Detections und Match-Status werden angezeigt → ein Tap auf "Apply to stock" bucht Stock-Counts.

## Routen

```
GET  /capture/            — login required, zeigt Upload-Form
POST /capture/            — entgegen-nimmt Foto, legt InventoryPhoto an,
                            ruft run_inference() inline auf, redirect → detail
GET  /capture/<photo_id>/ — zeigt Foto, Detection-Liste mit Match-Status, Button "Apply"
POST /capture/<photo_id>/apply/ — ruft apply_to_stock(), redirect → list
GET  /capture/list/       — Übersicht der eigenen Fotos

GET  /manifest.webmanifest — PWA-Manifest
GET  /sw.js               — Service Worker (basic offline-shell)
```

Alle View-Endpunkte hinter `@login_required`. Foto-Detail prüft, dass `photo.organization == request.organization` (sonst 404).

## Templates

- `vision/base.html` — minimaler PWA-Shell (Manifest-Link, Theme-Color, mobile viewport, Tailwind-CDN)
- `vision/capture.html` — Upload-Form mit `<input type=file accept=image/* capture=environment>`
- `vision/photo_detail.html` — Foto-Preview, Detection-Tabelle, Apply-Button
- `vision/photo_list.html` — Liste mit Statuschip pro Foto

## PWA

- `manifest.webmanifest`: name, short_name, start_url=`/capture/`, display=`standalone`, theme_color
- `sw.js`: basic install + fetch passthrough; cached App-Shell für Offline-Fallback (POST-Request läuft nur online)

## Tests

- GET /capture/ unauthenticated → redirect to login
- GET /capture/ authenticated → 200 + form
- POST /capture/ mit valid PNG → erzeugt InventoryPhoto in der aktiven Org, läuft inference, redirect zu detail
- POST /capture/ mit anderem User aus anderer Org → eigene Org wird gesetzt
- GET /capture/<id>/ von User mit fremder Org → 404
- POST /capture/<id>/apply/ ändert Photo-Status auf APPLIED

## Out of scope

- Push-Notifications
- Offline-Upload-Queue (Mailing-Stub für später)
- Bbox-Visualisierung over the image
- Dark-mode / accessibility polish
