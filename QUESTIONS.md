# Open questions — component history

Unresolved items from the 2026-07-28 history reconstruction. Each has the
evidence and the command (or SQL) to run once answered.

## 1. Did the gravel wheels do spring 2026 commute duty on the Firefly?

**Evidence:** ride titled "Gravel tires fit the fenders too" (2026-03-12),
three days after the fender install. The component log currently assumes
the ENVE 4.5s were mounted continuously from 2025-11-06 → now, so any
gravel-wheel days in Mar–Jun 2026 are being credited to the ENVEs
(wheelset, front tire, Pirelli rear, and cassette windows all inherit).

**To resolve:** if the gravel wheels went on ~Mar 12 and came off on date X:

```sql
-- close the ENVE window for the gravel interlude, reopen at X
UPDATE component_installs SET end_date='2026-03-12' WHERE component_id='enve-45' AND end_date IS NULL;
INSERT INTO component_installs (component_id,gear_id,start_date,end_date) VALUES
 ('classified-gravel','b11215203','2026-03-12','<X>'),
 ('enve-45','b11215203','<X>',NULL);
```

(Tires/cassette parented to each wheelset follow automatically. But note
the 2026-03-29 sealant blowout + Pirelli story is currently dated inside
this window on the ENVEs — if the blowout was actually on the gravel
wheels' tires, that sub-history needs re-parenting too.)

## 2. Is the trainer's 10sp cassette the Tarmac's HG500?

**Evidence:** Shimano HG500 10sp 11-34 bought 2025-04-11 ($52) for the
Tarmac's Wheeltop refresh; the Tacx got "a 10sp cassette (new-ish)" by
May 2026 when the Tarmac went on the trainer. Currently modeled as two
components: `hg500` (on Tarmac since 2025-05-03) and `cass-10sp` (on
tacx-neo since 2026-05-27).

**To resolve:** if they're the same cassette (moved wheel→trainer):

```sql
-- fold cass-10sp into hg500: close hg500 on the bike, move its trainer install
UPDATE component_installs SET end_date='2026-05-27' WHERE component_id='hg500' AND end_date IS NULL;
UPDATE component_installs SET component_id='hg500' WHERE component_id='cass-10sp';
DELETE FROM components WHERE id='cass-10sp';
```

If they're different cassettes, just delete this question.

## 3. Where did the Kazane's Ksyrium Elites go?

**Evidence:** "Kysrium elite break-in" (2016-04-25) — new wheelset six
days before the Kazane's last ride (2016-05-01) and two weeks before the
Tarmac's first (2016-05-09). The Chris King R45s are documented moving
Kazane→Tarmac, so the Tarmac may have run two wheelsets, or the Ksyriums
were sold/shelved.

**To resolve:** if they went to the Tarmac (or elsewhere), add:

```bash
uv run strava-db component install ksyrium:wheelset tarmac --date 2016-05-09
# ...and an end date / removal when they left service
```

## 4. Smaller loose ends

- **Metrofiets acquisition year** — notes say "bought from Alyson …2021?"
  but its first tagged ride is 2023-07-20. No component impact yet; only
  matters if cargo-bike parts ever get logged.
- **Peloton SPM2 power meter** (~$244, eBay) — no install date found.
  Peloton retired 2025-01-12, so this is history-only:
  `component install spm2:powermeter peleton --date <when>` then remove.
- **Firefly seat** — "new seat at some point", still undated; the Creo
  also has a seat swap pending (dropper is stock).
- **Firefly first-VirtualRide date** (2025-01-08) predates the Tacx setup
  note (2025-01-13) by five days; trainer install window currently trusts
  the ride data. Harmless unless the 1/8–1/12 Zwift rides were actually
  on the Peloton's power meter.
