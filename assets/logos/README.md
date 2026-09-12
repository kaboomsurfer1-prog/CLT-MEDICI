# Logo-uri pentru documente

Botul caută logo-urile în această ordine:

1. Fișier local în acest folder:
   - `main.png` → logo-ul orașului **Legacy of CLT** (stânga sus pe document)
   - `ems.png` → logo-ul **Legacy EMS** (dreapta sus pe document)
   - se acceptă și `.jpg`, `.jpeg`, `.webp`
2. Variabilele de mediu `MAIN_LOGO_URL` și `EMS_LOGO_URL` (link direct către imagine)
3. Iconița serverului Discord (`MAIN_GUILD_ID` și `EMS_GUILD_ID`)

Dacă nu găsește nimic, pe document apare un cerc cu textul `CLT` / `EMS`.

Recomandare: PNG pătrat, minim 512×512, cu fundal transparent.
Fundalul alb din jurul logo-ului este eliminat automat.
