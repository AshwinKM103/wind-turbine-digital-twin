# Steam Turbine Frame Dimension Tables

## Source 1: Dresser-Rand RLHA Single-Stage API 611 Steam Turbines

**Source URL:** https://www.mcraeeng.com/files/single-stage-turbine-603159.pdf  
**Source Type:** PDF (Successfully fetched and extracted)

### Maximum Capabilities Table

| Model | Power HP (kW) | Inlet Pressure PSIG (BARG) | Inlet Temp °F (°C) | Exhaust PSIG (BARG) | RPM | Inlet Dia. In (mm) | Exhaust Dia. In (mm) |
|-------|---------------|--------------------------|------------------|-------------------|-----|-------------------|----------------------|
| RLHA-15 | 450 (335) | 600 (41) | 750 (400) | 105 (7) | 6000 | 3 (75) | 6 (150) |
| RLHA-24 | 2500 (1865) | 900 (62) | 950 (510) | 300 (20) | 6300 | 6 (150) | 10 (250) |

**Notes from source:**
- Steam inlet locations are fixed as illustrated in the document.
- Steam exhaust locations available as right or left hand orientation.

### Overall Dimensions Table

| Dimension | RLHA-15 | RLHA-24 |
|-----------|---------|---------|
| A | 46 in (1166 mm) | 57 in (1454 mm) |
| B | 5 in (136 mm) | 5 in (136 mm) |
| C | 13 in (324 mm) | 22 in (552 mm) |
| D | 35.5 in (902 mm) | 44 in (1110 mm) |
| E | 22 in (562 mm) | 42 in (1075 mm) |

*Note: Dimension letters A–E refer to overall machine measurements. See source document for dimensional diagram and detailed component specifications.*

**Total frame sizes extracted from Dresser-Rand RLHA:** 2 models (RLHA-15, RLHA-24)

---

## Source 2: Elliott YR Single-Stage Steam Turbines

**Source URL:** https://www.scribd.com/document/470007770/yr-steam-turbines  
**Source Type:** PDF (Scribd-hosted)

### Fetch Status

**FAILED TO EXTRACT (verbatim table)** — The Scribd URL requires authentication/login. Two alternate public-domain host copies were located (Elliott's own site, and mirrors pdf4pro.com / pdfcoffee.com), but all were unreachable from this environment (blocked/connection refused on direct download, WebFetch returned "Socket is closed" or ECONNREFUSED on repeated attempts). Public URLs found for future retry:
- https://www.elliott-turbo.com/files/admin/literature/updated%20cover%20092019/yr-steam-turbines.pdf (official Elliott Group source, no login required — blocked bot/script access when tested)
- https://pdf4pro.com/view/yr-steam-turbines-elliott-turbo-com-5b5011.html
- https://pdfcoffee.com/download/elliott-yr-specifications-pdf-free.html

### Partial data (from search-result snippets only — NOT verified against the source table, do not treat as final)

Frame designations and wheel pitch diameters surfaced by search snippets:

| Frame | Wheel Pitch Diameter |
|-------|----------------------|
| PYR | 12 in (305 mm) |
| AYR | 14 in (360 mm) |
| BYR | 18 in (460 mm) |
| BYRH | 18 in (460 mm) |
| BYRHH | 18 in (460 mm) |
| DYR | 28 in (710 mm) |
| DYRH | 28 in (710 mm) |
| DYRM | 28 in (710 mm) |
| DYRN | 28 in (710 mm) |

Snippets also indicate the full table includes columns for initial pressure, initial temperature, exhaust pressure, number of stages, inlet size, exhaust size, speed (rpm), capacity range, and shipping weight — per frame — but these column values were not retrievable from snippets and need the actual table.

**Expected overall range (from blueprint reference, unverified):** 12–28 in (305–710 mm) wheel pitch diameter, 3–10 in inlet, 6–14 in exhaust, 5,000–8,500 rpm, 150–4,027 kW power range.

**To complete this source:** open one of the three URLs above in a real browser (not a script) and copy the specifications table manually, or try WebFetch again later — the failures looked transient/bot-protection related rather than permanent.

---

## Summary

| Source | Status | Frame Sizes Extracted |
|--------|--------|----------------------|
| Dresser-Rand RLHA | Success (verbatim) | 2 models (RLHA-15, RLHA-24) |
| Elliott YR | Partial (frame names + wheel diameters only, from search snippets, unverified) | 9 frame names identified, full spec columns missing |

**Total verified dimension rows extracted:** 2 (Dresser-Rand only). Elliott YR needs a manual browser pull to finish.
