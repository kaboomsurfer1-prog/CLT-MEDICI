# Legacy EMS Bot — Contracte, Demisii & Documente Medicale

Bot Discord pentru **Departamentul Medical Legacy EMS** din orașul **Legacy of CLT**.
Rulează pe două servere în același timp:

| Server | ID | Rol |
| --- | --- | --- |
| Legacy of CLT (principal) | `1505903653079351357` | angajări, contracte |
| Legacy EMS (medici) | `1518542545569976492` | arhivă contracte, demisii |

Versiune: `2.2.0-legacy-ems-medical`

---

## 1. Sistem de angajare cu contract

### Pasul 1 — conducerea emite contractul

În canalul `1548327664694333520` (serverul principal), un membru cu rolul
`1517181051288420372` folosește:

```text
/contract user:@membru nume_ic:Andrei Popescu cnp:1980512345678
          semnatura:Mihai Ionescu grad_angajator:Director Medical
          grad_angajat:Paramedic Nivel 2
```

Toate câmpurile sunt **obligatorii**:

| Câmp | Ce se scrie |
| --- | --- |
| `user` | membrul care este angajat |
| `nume_ic` | numele și prenumele IC al celui angajat |
| `cnp` | CNP-ul IC al celui angajat |
| `semnatura` | numele și prenumele IC al celui care angajează |
| `grad_angajator` | gradul celui care face contractul |
| `grad_angajat` | gradul pe care îl primește membrul angajat |

Botul postează în canal un mesaj care taghează membrul, cu datele contractului
și cu două butoane.

### Pasul 2 — membrul apasă un buton

Mesajul are două butoane, iar membrul taggat **nu trebuie să scrie nimic**:

- **✍️ Acceptă / Semnează** → semnează contractul. Semnătura lui este numele IC
  completat de angajator în `nume_ic`.
- **❌ Refuză contractul** → contractul nu intră în vigoare, nu se setează nicio
  dată de intrare, iar angajatorul este anunțat în canal și prin DM.

Butoanele funcționează doar pentru membrul din contract; oricine altcineva
primește un mesaj privat de refuz. După ce se apasă unul, ambele se dezactivează.

### Pasul 3 — botul face restul, automat

1. Generează **contractul ca imagine** (A4, în română) cu:
   - logo-ul orașului și logo-ul EMS
   - datele angajatului (nume IC, CNP, gradul acordat, cont Discord)
   - clauzele contractuale
   - **semnătura angajatorului + gradul lui** și **semnătura angajatului**
   - ștampila oficială a departamentului
2. Salvează automat **data și ora intrării** (momentul semnării).
3. Postează contractul în canalul de contracte din serverul principal.
4. Postează contractul în canalul `1548329089956581487` din serverul EMS.
5. Trimite membrului, prin DM, contractul + **invitația în serverul EMS**.
   Invitația apare și în răspunsul privat primit după apăsarea butonului.

---

## 2. Sistem de demisie

Modelul rămâne același. În canalul de demisii din serverul EMS, membrul scrie:

```text
Nume: Andrei Popescu
Ore: 120
Motiv: Nu mai am timp să activez în departament.
```

Conducerea primește butoane:

- **✅ Acceptă Demisia** → cere **semnătura și gradul** celui din conducere
  (gradul vine precompletat cu cel mai înalt rol Discord al lui, dar poate fi
  schimbat), apoi generează **Decizia de Încetare a Contractului** (imagine) cu:
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

1. data la care membrul a apăsat **Acceptă / Semnează**
2. o dată salvată anterior în baza de date
3. data la care membrul a intrat pe serverul Discord EMS

---

## 3. Documente medicale: `/radiografie` și `/analize`

Cele două comenzi merg **doar** în canalele medicale:

- `1553137969899114646`
- `1539978574864326737`

Botul află singur pe ce server este fiecare canal și înregistrează comenzile
acolo. Folosite în alt canal, răspund cu un mesaj privat de refuz.

### `/radiografie`

```text
/radiografie nume_medic:Mihai Ionescu nume_pacient:Andrei Popescu
             cnp_pacient:1980512345678 stare:Gravă zona:Picior
```

| Câmp | Ce se scrie |
| --- | --- |
| `nume_medic` | numele medicului; apare ca semnătură și pe parafă |
| `nume_pacient` | numele și prenumele pacientului |
| `cnp_pacient` | CNP-ul pacientului |
| `stare` | `Bună`, `Normală`, `Rea` sau `Gravă` |
| `zona` | `Mână`, `Picior`, `Cap`, `Gât` sau `Genunchi` |

Botul generează **Buletinul de Investigație Radiologică** (imagine A4, în română):

- antetul Legacy of CLT / Legacy EMS cu ambele logo-uri
- **filmul radiografiei** zonei alese, cu datele pacientului pe margine
- leziunea desenată după stare: fără leziuni (`Bună`), tumefiere ușoară
  (`Normală`), fisură (`Rea`) sau fractură cu deplasare și eschile (`Gravă`),
  marcată cu un cerc roșu
- descrierea radiologică, concluzia și recomandările, în română
- semnătura și **parafa medicului**, plus ștampila unității

### `/analize`

Aceleași câmpuri, fără `zona`. Botul generează **Buletinul de Analize
Medicale**: hemogramă, biochimie și markeri inflamatori, cu valorile, intervalele
de referință și o bară de încadrare. Valorile urmează starea: toate normale la
`Bună`/`Normală`, 6 din 11 modificate la `Rea`, toate modificate la `Gravă`.

### Certificatul pentru asigurare

La stare **`Rea`** sau **`Gravă`**, ambele documente (și mesajul din Discord)
au o casetă care spune că spitalul oferă un certificat medical pentru
asigurarea pacientului, în caz de accident sau dacă pacientul a fost vătămat de
o altă persoană, cu obligația de despăgubire pentru îngrijirile medicale.

---

## 4. Comenzi

| Comandă | Unde | Cine |
| --- | --- | --- |
| `/contract` | canalul de contracte, serverul principal | rolurile din `RECRUITER_ROLE_IDS` + administratori |
| `/radiografie` | canalele din `MEDICAL_CHANNEL_IDS` | oricine scrie acolo (sau doar `MEDICAL_ROLE_IDS`, dacă e setat) |
| `/analize` | canalele din `MEDICAL_CHANNEL_IDS` | oricine scrie acolo (sau doar `MEDICAL_ROLE_IDS`, dacă e setat) |

Contractele și demisiile se fac în rest din butoane.
Comenzile vechi (`/setintrare`, `/intrare`, `/demisii`, `/semneaza`) au fost
**șterse** și sunt eliminate automat de pe Discord la pornire.

---

## 5. Variabile Railway

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

Pentru documentele medicale (implicit sunt deja cele două canale de mai sus):

```env
MEDICAL_CHANNEL_IDS=1553137969899114646,1539978574864326737
MEDICAL_ROLE_IDS=
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

## 6. Permisiuni Discord necesare

**Developer Portal — Intents:**

- `MESSAGE CONTENT INTENT`
- `SERVER MEMBERS INTENT`

**Serverul principal:** citire mesaje, trimitere mesaje, atașare fișiere, comenzi slash.

**Serverul EMS:** citire/trimitere mesaje, atașare fișiere și **Creare invitație**
(altfel botul nu poate genera linkul de invitație).

---

## 7. Logo-uri pe documente

Vezi [`assets/logos/README.md`](assets/logos/README.md).
Ordinea: fișier local → `MAIN_LOGO_URL` / `EMS_LOGO_URL` → iconița serverului Discord.

Fonturile sunt incluse în repo (`assets/fonts`), deci documentele arată identic
local și pe Railway.

---

## 8. Storage Railway

Serviciul `CLT-MEDICI` are deja un Railway Volume (`clt-medici-volume`) montat pe:

```text
/data
```

Așa rămân salvate contractele, semnăturile și datele de intrare la fiecare
redeploy. Fără volum, botul scrie într-un fișier local `legacy_ems.db` care se
pierde la restart.

---

## 9. Structura proiectului

```text
main.py        comenzi, butoane, ferestre, fluxuri
config.py      variabile de mediu si validare la pornire
database.py    SQLite: contracte, demisii, date de intrare
documents.py   generarea imaginilor (contract, decizie de incetare, radiografie, analize)
medical.py     texte medicale, stari, zone si valorile analizelor
xray.py        filmul radiografiei, desenat procedural pentru fiecare zona
utils.py       date, durate, validari, formatari
assets/fonts   fonturile documentelor (DejaVu + Great Vibes)
assets/logos   logo-urile folosite pe documente
```
