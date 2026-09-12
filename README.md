# Legacy EMS Bot — Contracte & Demisii

Bot Discord pentru **Departamentul Medical Legacy EMS** din orașul **Legacy of CLT**.
Rulează pe două servere în același timp:

| Server | ID | Rol |
| --- | --- | --- |
| Legacy of CLT (principal) | `1505903653079351357` | angajări, contracte |
| Legacy EMS (medici) | `1518542545569976492` | arhivă contracte, demisii |

Versiune: `2.0.0-legacy-ems-contracte`

---

## 1. Sistem de angajare cu contract

### Pasul 1 — conducerea emite contractul

În canalul `1548327664694333520` (serverul principal), un membru cu rolul
`1517181051288420372` folosește:

```text
/contract user:@membru nume_ic:Andrei Popescu cnp:1980512345678 semnatura:Mihai Ionescu
```

| Câmp | Obligatoriu | Ce se scrie |
| --- | --- | --- |
| `user` | da | membrul care este angajat |
| `nume_ic` | da | numele și prenumele IC al celui angajat |
| `cnp` | da | CNP-ul IC al celui angajat |
| `semnatura` | da | **numele și prenumele IC al celui care angajează** |
| `functie` | nu | funcția pe care este angajat (implicit `Paramedic Stagiar`) |

Gradul angajatorului este preluat automat din **cel mai înalt rol Discord** al acestuia.

Botul postează un mesaj care taghează membrul și îi cere să semneze.

### Pasul 2 — membrul semnează

Membrul taggat scrie:

```text
/semneaza
```

sau apasă butonul **✍️ Semnează contractul**. Se deschide o fereastră unde își
scrie semnătura (nume și prenume IC).

### Pasul 3 — botul face restul, automat

1. Generează **contractul ca imagine** (A4, în română) cu:
   - logo-ul orașului și logo-ul EMS
   - datele angajatului (nume IC, CNP, funcție, cont Discord)
   - clauzele contractuale
   - **semnătura angajatorului + gradul lui** și **semnătura angajatului**
   - ștampila oficială a departamentului
2. Salvează automat **data și ora intrării** (momentul semnării).
3. Postează contractul în canalul de contracte din serverul principal.
4. Postează contractul în canalul `1548329089956581487` din serverul EMS.
5. Trimite membrului, prin DM, contractul + **invitația în serverul EMS**.
   Invitația apare și în răspunsul privat al comenzii `/semneaza`.

---

## 2. Sistem de demisie

Modelul rămâne același. În canalul de demisii din serverul EMS, membrul scrie:

```text
Nume: Andrei Popescu
Ore: 120
Motiv: Nu mai am timp să activez în departament.
```

Conducerea primește butoane:

- **✅ Acceptă Demisia** → cere semnătura conducerii, apoi generează
  **Decizia de Încetare a Contractului** (imagine) cu:
  - textul că persoana **nu mai face parte din departamentul EMS**
  - data intrării, data încetării, perioada lucrată (zile, ore, minute) și totalul de zile
  - semnătura conducerii cu gradul ei și semnătura fostului angajat
  - ștampila de arhivă

  Documentul se trimite în canalul de demisii, în canalul `1548329089956581487`,
  în logurile EMS și principal, și prin DM fostului angajat.

- **❌ Refuză Demisia** → cere motivul refuzului și anunță membrul.

Rolurile Discord se elimină în continuare **manual** de către conducere.

### Data intrării

Nu mai există `/setintrare`. Data intrării este determinată automat, în ordinea:

1. data semnării contractului (`/semneaza`)
2. o dată salvată anterior în baza de date
3. data la care membrul a intrat pe serverul Discord EMS

---

## 3. Comenzi

| Comandă | Unde | Cine |
| --- | --- | --- |
| `/contract` | canalul de contracte, serverul principal | rolurile din `RECRUITER_ROLE_IDS` + administratori |
| `/semneaza` | serverul principal | membrul care are un contract în așteptare |

Comenzile vechi (`/setintrare`, `/intrare`, `/demisii`) au fost **șterse**
și sunt eliminate automat de pe Discord la prima pornire.

---

## 4. Variabile Railway

Obligatorii:

```env
DISCORD_TOKEN=TOKEN_BOT
MAIN_GUILD_ID=1505903653079351357
EMS_GUILD_ID=1518542545569976492
CONTRACT_CHANNEL_ID=1548327664694333520
CONTRACT_LOG_CHANNEL_ID=1548329089956581487
RECRUITER_ROLE_IDS=1517181051288420372
```

Pentru demisii:

```env
DEMISIE_CHANNEL_ID=ID_CANAL_DEMISII
EMS_LOG_CHANNEL_ID=ID_CANAL_LOG_EMS
MAIN_LOG_CHANNEL_ID=ID_CANAL_LOG_MAIN
STAFF_ROLE_IDS=ID_ROL_1,ID_ROL_2
```

Opționale:

```env
EMS_INVITE_CHANNEL_ID=
INVITE_MAX_AGE=604800
INVITE_MAX_USES=1
MAIN_LOGO_URL=
EMS_LOGO_URL=
CITY_NAME=Legacy of CLT
DEPARTMENT_NAME=Legacy EMS
DEPARTMENT_SUBTITLE=Departamentul Medical
DEFAULT_FUNCTION=Paramedic Stagiar
DB_PATH=/data/legacy_ems.db
TIMEZONE=Europe/Bucharest
DELETE_TRIGGER_MESSAGE=false
```

Dacă lipsesc variabilele de demisie, botul pornește oricum, dar sistemul de
demisie este dezactivat (apare un avertisment în loguri).

---

## 5. Permisiuni Discord necesare

**Developer Portal — Intents:**

- `MESSAGE CONTENT INTENT`
- `SERVER MEMBERS INTENT`

**Serverul principal:** citire mesaje, trimitere mesaje, atașare fișiere, comenzi slash.

**Serverul EMS:** citire/trimitere mesaje, atașare fișiere și **Creare invitație**
(altfel botul nu poate genera linkul de invitație).

---

## 6. Logo-uri pe documente

Vezi [`assets/logos/README.md`](assets/logos/README.md).
Ordinea: fișier local → `MAIN_LOGO_URL` / `EMS_LOGO_URL` → iconița serverului Discord.

Fonturile sunt incluse în repo (`assets/fonts`), deci documentele arată identic
local și pe Railway.

---

## 7. Storage Railway

Pentru ca contractele și demisiile să nu se piardă la redeploy, montează un
Railway Volume pe:

```text
/data
```

Fără volum, botul scrie într-un fișier local `legacy_ems.db` care se pierde la restart.

---

## 8. Structura proiectului

```text
main.py        comenzi, butoane, ferestre, fluxuri
config.py      variabile de mediu si validare la pornire
database.py    SQLite: contracte, demisii, date de intrare
documents.py   generarea imaginilor (contract + decizie de incetare)
utils.py       date, durate, validari, formatari
assets/fonts   fonturile documentelor (DejaVu + Great Vibes)
assets/logos   logo-urile folosite pe documente
```
