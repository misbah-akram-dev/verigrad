# Programmes — eval / golden-set list

> Used for the golden set (spec §8) and as real tracker data. Target ~30 programmes by v1 step 6; mostly ones I'm applying to. Initial 3 below resolve the "golden-set programmes" open question (spec §11).

| Programme | Sources (URL — role) | Country | Applying? | What's tricky |
|---|---|---|---|---|
| KAUST MS CS | `https://cs.kaust.edu.sa/` — program; `https://admissions.kaust.edu.sa/how-to-apply/admission-timelines` — admissions | Saudi Arabia | Yes | Deadlines live on a separate admissions page, not the programme page; the Spring round is PhD-only — MS applicants use Fall Round 2. |
| EDISS Erasmus Mundus | `https://www.master-ediss.eu/` — program; `/admission/` — admissions; `/admission-requirements/` — admissions; `/scholarship/` — scholarship | EU (Finland-led consortium) | Yes | Three rounds split by funding route (scholarship vs self-funded); the admissions page can still show the previous year's intake; deadlines are given in Helsinki time. |
| KFUPM MS Data Science & Analytics | `https://ms.kfupm.edu.sa/` — program (self-funded route); `https://cgis.kfupm.edu.sa/admission/kfupm-scholarship` — scholarship (not yet open) | Saudi Arabia | Yes | Deadlines TBA for the scholarship route; the page also shows another programme's deadline; tuition has discount tiers; the real rules sit in a linked PDF. |

## Rejected

Kept as examples of `eligibility_restrictions` (spec §4.1, §6.1) that flag a programme "not eligible" for my profile — not added to the tracker.

| Programme | Country | Restriction type | Why rejected |
|---|---|---|---|
| KSU MSc AI | Saudi Arabia | Nationality | Residents/nationals only — excludes my (international) profile. |
| (generic example) | Saudi Arabia | Gender | Single-gender admission — excludes my profile. |

## Notes
- Each applying-programme row becomes a `program_sources` set (spec §4.2): one row per URL, tagged with its `role`.
- "Tricky" column exists to stress-test extraction (multi-page sources, wrong-programme contamination, non-English pages, PDFs, TBA/unpublished funding, mixed grading scales) — not just to pick easy wins.
- Remaining ~27 programmes to be added before step 6 (spec §8.1), continuing to favour programmes I'm actually applying to over purely "hard" test cases.
