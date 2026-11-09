"""A tiny made-up place pack for Illinois (us-illinois), written with placepacks' own PackWriter, for the tests of
"Import places from a list": made-up address points (as the NAD gives them), made-up address ranges (as TIGER/Line
gives them), two made-up towns (Springfield and Riverton, both with a Main Street) and a made-up named place. The
address range and the named place are in the pack's "extra" part, as in the published packs. No real business or
address is in it."""

import os

REGION = "us-illinois"
SPRINGFIELD = (39.780, -89.680, 39.840, -89.600)       # south, west, north, east (a made-up square)
RIVERTON = (39.830, -89.560, 39.860, -89.520)
MAPLE = (39.80120, -89.64410)                          # 123 Main St, Springfield (an address point)
ELM_START, ELM_END = (39.81000, -89.65000), (39.81000, -89.64000)   # 100-198 Elm Ave (a range, Springfield)
RIVERTON_MAIN = (39.84500, -89.54000)                  # 123 Main St, Riverton (an address point)
PARK = (39.79500, -89.62000)                           # Pinecrest Park (a named place in Springfield)


def build(folder):
    """Write the pack into folder; returns its path."""
    from placepacks.download import local_name
    from placepacks.manifest import key_of
    from placepacks.writer import PackWriter
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, local_name(key_of(REGION, "core")))
    w = PackWriter(path, month=202610)
    w.add_source(id="test", name="Made-up test data", short="Test", attribution="Made up for the tests")

    def box(b):
        s, west, n, e = b
        return [[(s, west), (s, e), (n, e), (n, west), (s, west)]]
    w.add_area("t:springfield", "test", "Springfield", "town", "test", box(SPRINGFIELD))
    w.add_area("t:riverton", "test", "Riverton", "town", "test", box(RIVERTON))
    w.add_area("t:62701", "test", "62701", "zip", "test", box((39.795, -89.650, 39.805, -89.640)))
    w.add_address("test", "123", "Main Street", "Springfield", *MAPLE)
    w.add_address("test", "125", "Main Street", "Springfield", MAPLE[0], MAPLE[1] + 0.0002)
    w.add_address("test", "123", "Main Street", "Riverton", *RIVERTON_MAIN)
    w.add_address("test", "9", "River Road", "Springfield", 39.79000, -89.66000)
    meta = {"region_id": REGION, "region_name": "Illinois", "state": "Illinois", "country": "United States"}
    w.finish({**meta, "part": "core"})
    x = PackWriter(os.path.join(folder, local_name(key_of(REGION, "extra"))), month=202610)
    x.add_source(id="test", name="Made-up test data", short="Test", attribution="Made up for the tests")
    x.add_range("r:elm", "test", "Elm Avenue", 100, 198, 101, 199, "62702", [ELM_START, ELM_END])
    x.add_point("p:park", "test", "Pinecrest Park", "park", "leisure=park", *PARK)
    x.finish({**meta, "part": "extra"})
    return path
