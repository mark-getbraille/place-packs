"""Hospital and clinic accessibility (the owner's request of 27 November 2026, notes/helper-rules.txt: queue item
Q2). Source "health-access" (the details and notes of hospitals and clinics already in the packs; placepacks/
features.py reads the rows, "site" rows only).

  fhir.py            health insurers' public FHIR provider directories (CMS Interoperability rule; Da Vinci PDex
                     Plan-Net): Location records' accessibility extensions, hours and phone; never practitioners
  hospital_pages.py  hospitals' own patients-and-visitors and accessibility pages: the accessibility services they
                     say they offer, as a list of facts, and the accessibility desk's phone

Hospital and clinic campus maps (accessible entrances, parking, elevators, restrooms) come through the map vendor
registry and its collectors (placepacks/mapvendors) and OpenStreetMap (placepacks/readers/osm_features.py).
Section 1557 nondiscrimination notices were looked for as data and not found (sources.json "candidates").

The monthly workflow (.github/workflows/health-access.yml) runs one job per unit of UNITS through placepacks/
directories/run.py (collection "healthaccess") and publishes the month's set in the release "health-access".
Only the Python standard library is used.
"""

import importlib

from placepacks import features
from placepacks.health_access import fhir, hospital_pages

USER_AGENT = fhir.USER_AGENT
PAUSE = 1.5
FIELDS = features.FEATURE_FIELDS
TAG = "health-access"
# The FHIR directories: up to FHIR_BUDGET pages a month (polite paged reads, PAUSE apart); in practice the job's
# time (timeout, less run.py's margin) ends a big directory first: the first run (27 November 2026) read 4,000
# pages in 2 hours (Humana) and 5 hours (Molina). They are "resumable": the next run starts where this one stopped.
FHIR_BUDGET = 20000
UNITS = {unit: {"title": f"{spec['payer']} provider directory (FHIR)", "expected": 50000, "budget": FHIR_BUDGET,
                "timeout": 340, "resumable": True, "module": "placepacks.health_access.fhir"}
         for unit, spec in fhir.PAYERS.items()}
UNITS.update({f"hospital-pages-{i}": {"title": f"Hospitals' own accessibility pages ({i} of {hospital_pages.SHARDS})",
                                      "expected": 300, "budget": 6000, "timeout": 340,
                                      "module": "placepacks.health_access.hospital_pages"}
              for i in range(1, hospital_pages.SHARDS + 1)})


def collect(client, unit, stats):
    """One unit's rows: its module's collect(client, unit, stats)."""
    yield from importlib.import_module(UNITS[unit]["module"]).collect(client, unit, stats)
