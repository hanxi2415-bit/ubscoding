import tiktoken

EXAM_PASSAGES = [
    """Meridian Trench Research Station: habitat 6214m; storage annex 6050m; director Dr. Ansel Kovrith. Callsign Umbral Seven; backup Umbral Two. Residents 41; safety ceiling 52. Primary submersible Halcyon Drift; reserve Halberd Drift. Resupply every 19 days. Oxygen scrubber failure 2 Nov; annex flooding 9 Nov. Kesterline array recalibrated 14 Mar; Halberd sub-array maintained 12 Mar. Hydrophone gasket 12Nm; >0.5Nm deviation requires re-seat. Dive max 47min; first-month 35min. STOP_01 Sablefin Vent Field; STOP_02 Wraithmoor Escarpment; STOP_03 Corbel Slide; STOP_04 Pellucid Shelf.""",

    """Ashgrove Metropolitan Transit Authority: Director-General Dorian Fenwick. 68 certified drivers; minimum 50. Lines Amber, Cobalt, Russet, Willowmere, Foxglove. Cobalt Line 34.2km. Premium train Wrenfield-Class; Wrenwood prototype. Brake torque 9Nm; >0.5Nm deviation requires recheck. Daily fare cap £4.90. Russet relay fault 5 Jan; maintenance-vehicle near-miss 3 Jan. Driving limit 58min; first-month 40min. Callsign Fantail Nine; backup Fantail Two. STOP_05 Verity Observatory; STOP_06 Ashgrove Botanical Conservatory; STOP_07 Marrowgate Market; STOP_08 Halloway Aquatic Centre.""",

    """Velmara Phase II Trial: sponsor Thornquist Biotherapeutics; lead Dr. Reva Sandoval. Site 4 Bellhaven; Site 9 Corrimal Bay; Site 12 hub. Site 9 enrolled 37. Amended dosing began 3 Jun. Maintenance dose 240mg subcutaneous; pilot 180mg; proposed 210mg never used. Bloodwork every 21 days. Grade-3 hepatic event Site 9 on 11 Aug; injection-site reaction Site 4 on 4 Aug. ALT >260U/L stops dosing. Observation 90min; 60min after 3 uneventful visits. Code VLM-204-B; former VLM-204-A. STOP_09 Bellhaven Infusion Suite; STOP_10 Corrimal Bay Screening Annex; STOP_11 Thornquist Central Pharmacy; STOP_12 Velmara Sample Repository.""",

    """Hollowlight Engine: lead architect Perrin Ashwicke; 32 engineers; minimum 18. Duskcast Renderer uses Emberline deferred lighting, first Release 14; Release 13 forward lighting; Release 15 stability fixes. Texture ceilings console 512MB, desktop 768MB, mobile 256MB. Physics Ferrolight Solver; scripting Larkspur VM; audio Cindertide Audio; networking Tallowmere Netcode; assets Mossgate Pipeline; builds Ashfall Build System. Regression every 6h during milestones, otherwise 12h. Skeleton max 90 bones; environment 40000 triangles/cell. Console render budget 11ms; desktop 14ms. Streaming stall >9s; warning >3s. Stable tag Driftglass Nine; emergency Driftglass Two. STOP_13 Capture Stage; STOP_14 Determinism Test Rig; STOP_15 Asset Pipeline Farm; STOP_16 Audio Vault.""",

    """Thornmere Growers Cooperative: chair Cordelia Vance; 54 households; dissolution floor 30. Josiah Pell farms 42 acres at Cross Furlong; Josiah Pelling is different. Bellwether Drier for late-season root crops; Bellwether Two reserve. Potato harvester rotates every 11 days. Grain >18% moisture downgraded one grade. Unused cold-storage bay forfeited after 90 days. Compressor failure 6 Apr; door-seal failure 4 Apr. Drier rota adopted 21 May unanimously by 7 board members. Every crate leaving the packing shed is stamped Thornmere Nine; Thornmere Two only for consignments held for internal grading disputes, never released sale produce. STOP_17 Thornmere Grading Hall; STOP_18 Netherfield Cold Store; STOP_19 Cooperative Machinery Yard; STOP_20 Harrowbeck Weighbridge."""
]

encoding = tiktoken.get_encoding("o200k_base")

total = sum(
    len(encoding.encode(x))
    for x in EXAM_PASSAGES
)

print(total)