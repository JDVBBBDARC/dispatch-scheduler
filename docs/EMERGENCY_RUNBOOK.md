# 🚨 EMERGENCY RUNBOOK — Dispatch Scheduler

> **Para kanino ito:** kahit sinong kailangang magpatakbo o mag-ayos ng
> system kapag wala ang regular na IT administrator. Hindi kailangang
> programmer — sundan lang ang mga hakbang.
>
> Huwag i-print na may password. Ang mga credential ay nasa mga lugar
> na nakalista sa Section 2 — wala ni isa sa dokumentong ito.

---

## 1. Ano ang sistemang ito

Web app para sa dispatch operations: schedule ng trips, breakdown
monitoring (auto-synced mula sa workshop ERP), GPS tracking ng trucks
(Cartrack), toll reference, at reports. May DALAWANG tumatakbong
proseso:

| Proseso | Ano ito | Saan tumatakbo |
|---|---|---|
| **Web app** | Yung website na ginagamit ng dispatchers | PythonAnywhere → Web tab |
| **Polling worker** | Background na kumukuha ng GPS data kada 60s | PythonAnywhere → Tasks tab (always-on task: `cartrack_poll.py`) |

Kapag patay ang web app — walang makaka-login. Kapag patay ang worker —
gumagana pa rin ang website pero hihinto ang GPS tracking, cycle
detection, toll detection, at breakdown sync.

## 2. Saan naka-lagay ang lahat

| Item | Lokasyon |
|---|---|
| Hosting | PythonAnywhere, account **jdvbbbdarc** |
| Code | https://github.com/JDVBBBDARC/dispatch-scheduler (branch: `main`) |
| App folder sa server | `~/dispatch-scheduler` |
| Database | `dispatch.db` — SQLite file sa mismong app folder (`~/dispatch-scheduler/dispatch.db`) |
| Mga backup ng database | `~/dispatch-scheduler/backups/` — gabi-gabing kopya, 14 araw (Section 7) |
| **Mga credential** | `.env` file sa app folder sa PythonAnywhere (HINDI kasama sa GitHub) + PythonAnywhere Web tab → Environment variables |
| Cartrack API password | Cartrack Fleet Web → Settings → API Settings (pwedeng i-regenerate doon) |
| ERP (workshop) | gainersand.ph — ang breakdown records ay galing dito |
| Google Sheets sync | Webhook URL naka-save sa app: Admin/Settings page |

## 3. Paano i-restart ang WEB APP

1. Login sa https://www.pythonanywhere.com
2. **Web** tab → pindutin ang malaking **Reload** button
3. Buksan ang app sa browser — dapat lumabas ang login page

## 4. Paano i-restart ang WORKER (GPS/sync)

1. PythonAnywhere → **Tasks** tab
2. Hanapin ang always-on task na may `cartrack_poll.py`
3. Pindutin ang **restart/refresh** na icon (o i-delete at i-add ulit
   ang parehong command)
4. I-click ang task para makita ang log — dapat may mga bagong linya
   na lumalabas kada minuto (hal. `[POLL]`, `[STOP]`, `[TOLL-GPS]`)

## 5. Paano mag-deploy ng fix / update

Sa PythonAnywhere **Bash console**:

```bash
cd ~/dispatch-scheduler
# BACKUP MUNA (laging gawin bago mag-pull):
python scripts/backup_db.py    # o manual: cp dispatch.db /tmp/db-backup-$(date +%Y%m%d-%H%M%S).db
git rev-parse HEAD > .last_safe_sha

git pull
touch /var/www/jdvbbbdarc_pythonanywhere_com_wsgi.py   # reload web app
```

Tapos i-restart ang worker (Section 4) kung may binago sa
`cartrack_poll.py`, `joborders_sync.py`, o `cartrack_trips_backfill.py`.

## 6. Paano mag-ROLLBACK kapag may sira pagkatapos ng deploy

```bash
cd ~/dispatch-scheduler
git checkout $(cat .last_safe_sha)
# kung kailangan ibalik ang database — tingnan ang Section 7 sa baba
touch /var/www/jdvbbbdarc_pythonanywhere_com_wsgi.py
```

Tapos restart ang worker.

## 7. Awtomatikong BACKUP gabi-gabi + paano mag-RESTORE

May **scheduled task** na tumatakbo **2:00 AM (PHT) gabi-gabi**
(Tasks tab, naka-set sa 18:00 UTC) na kumukuha ng kopya ng database:

- Naka-save sa `~/dispatch-scheduler/backups/` bilang
  `dispatch-YYYY-MM-DD.db.gz`
- Awtomatikong binubura ang mas luma sa **14 araw**
- Para i-check kung tumatakbo: `ls -lh ~/dispatch-scheduler/backups/`
  — dapat may file na may petsa ng kagabi

**Paano mag-restore kapag nasira o nabura ang database:**

```bash
cd ~/dispatch-scheduler
ls backups/                                    # piliin ang pinakabagong maayos na petsa
gunzip -k backups/dispatch-YYYY-MM-DD.db.gz    # i-unzip (mananatili ang .gz)
cp dispatch.db dispatch.db.broken              # itabi ang sira para sa diagnosis
mv backups/dispatch-YYYY-MM-DD.db dispatch.db  # ipalit ang snapshot
touch /var/www/jdvbbbdarc_pythonanywhere_com_wsgi.py   # reload web
```

Tapos restart ang worker (Section 4). **Tandaan:** ang mga na-encode
PAGKATAPOS ng snapshot (hanggang isang araw) ay kailangang i-encode
ulit mula sa papel.

## 8. Mga karaniwang sira at lunas

| Sintomas | Malamang na dahilan | Lunas |
|---|---|---|
| "Something went wrong" / 502 sa website | Web app crashed | Web tab → Reload. Kung ayaw pa rin: tingnan ang **error log** sa Web tab, ipadala sa IT contact |
| Trucks hindi gumagalaw sa Truck Cycle Time / walang bagong GPS data | Worker patay o expired ang Cartrack password | Restart worker (Sec. 4). Kung log ay puro `401`: i-regenerate ang API password sa Cartrack Fleet Web, i-update sa `.env`, restart |
| Walang bagong breakdown mula ERP | ERP sync error | Buksan ang /breakdown page → pindutin **Sync from ERP** → basahin ang error message. Kung credential issue: i-check ang `.env` |
| "Database is locked" errors | Sabay na nagsusulat ang web at worker | Karaniwang self-healing. Kung tuloy-tuloy: restart worker muna, tapos Reload ng web app |
| Login ayaw tumanggap kahit tama | Account inactive o na-lock | Ibang admin account ang gamitin → Admin page → i-activate ulit |

## 9. Daily health check (1 minuto)

1. Buksan ang Dashboard — may laman ba ang KPIs ngayong araw?
2. Truck Cycle Time — may "last updated" ba na bago (hindi ilang oras na)?
3. Breakdown page — tumutugma ba sa alam mong nasa shop?

Kapag lahat ng tatlo ay OK — buhay ang buong sistema.

## 10. Mga kontak

| Sino | Para saan | Detalye |
|---|---|---|
| IT Administrator (primary) | Lahat ng nasa itaas | *[ ILAGAY: pangalan + numero ]* |
| Cartrack support | GPS device / API issues | *[ ILAGAY: account manager / hotline ]* |
| ERP / gainersand contact | Breakdown sync source | *[ ILAGAY ]* |
| PythonAnywhere | Hosting issues | help@pythonanywhere.com (login via account owner) |

> **Huling payo:** kapag hindi sigurado, HUWAG mag-delete ng kahit ano.
> Ang lahat ng problema sa itaas ay naaayos ng restart o rollback —
> walang sitwasyong kailangan ng pag-delete ng data.
