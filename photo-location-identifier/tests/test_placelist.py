"""Import places from a list (pli/placelist.py and the places from lists in pli/myplaces.py): pasted chat text in
every usual form, CSV, Excel, SQLite databases and .sql files (read safely), finding addresses in a made-up place
pack, duplicates, the grid index, the naming of pictures, and exports (SQLite, .sql, CSV, JSON) that import back
the same. Every business, address and position here is made up."""

import json
import os
import sqlite3
import time

import pytest

import listpack
from pli import myplaces as mp
from pli import placelist as pl
from pli.places import Places


def by_name(rows):
    """{name: row} of rows."""
    return {r.name: r for r in rows}


# ------------------------------------------------------------------------------------------- pasted text

def test_markdown_table_with_the_address_in_one_column():
    """A chat's table: header names recognised, Markdown and links removed, phone numbers left out, the address in
    one column split into its parts."""
    text = """Here are the schools you asked for:

| # | School | Address | Phone |
|---|--------|---------|-------|
| 1 | **Maple Grove School for the Blind** | 123 Main St, Springfield, IL 62701 | (217) 555-0100 |
| 2 | [Oak Hill Academy](https://example.com/oak) | 45 North Elm Avenue, Springfield, Illinois 62702 | 217-555-0199 |
"""
    rows = pl.parse_pasted(text)
    assert [r.name for r in rows] == ["Maple Grove School for the Blind", "Oak Hill Academy"]
    maple, oak = rows
    assert (maple.street, maple.city, maple.state, maple.zip) == ("123 Main St", "Springfield", "IL", "62701")
    assert (oak.street, oak.state, oak.zip) == ("45 North Elm Avenue", "IL", "62702")
    assert maple.where == "line 5"
    assert "555" not in maple.line() and "example.com" not in oak.line()


def test_markdown_table_with_separate_columns_and_positions():
    """A table with Name, City, State and Latitude/Longitude columns: the positions are used as they are."""
    text = ("| Name | City | State | Latitude | Longitude |\n|:--|:--|:--|--:|--:|\n"
            "| Hilltop Center | Springfield | IL | 39.7817 | -89.6501 |\n")
    row = pl.parse_pasted(text)[0]
    assert (row.name, row.city, row.state, row.lat, row.lon) == ("Hilltop Center", "Springfield", "IL", 39.7817,
                                                                -89.6501)


def test_bulleted_and_numbered_lists_in_every_usual_form():
    """"Name, address", "**Name**: address", "Name — address", "Name - address", numbered items, a state written
    out, an address without commas, and the sentences around the list left out."""
    text = """Sure! Here are some places in Springfield, IL:

- Maple Grove School for the Blind, 123 Main St, Springfield, IL 62701
- **Oak Hill Academy**: 45 N. Elm Ave, Springfield, IL 62702
- Riverside Diner — 9 River Road, Springfield, Illinois 62703 (website: https://example.com)
1. *Lincoln Reading Room* - 326 S 7th St, Springfield, IL
2. Corner Bakery 77 Baker Street Springfield IL 62704

Let me know if you would like more!
"""
    rows = by_name(pl.parse_pasted(text))
    assert set(rows) == {"Maple Grove School for the Blind", "Oak Hill Academy", "Riverside Diner",
                         "Lincoln Reading Room", "Corner Bakery"}
    assert rows["Oak Hill Academy"].street == "45 N. Elm Ave"
    assert (rows["Riverside Diner"].street, rows["Riverside Diner"].state, rows["Riverside Diner"].zip) == \
        ("9 River Road", "IL", "62703")
    assert rows["Lincoln Reading Room"].street == "326 S 7th St"
    assert (rows["Corner Bakery"].street, rows["Corner Bakery"].city) == ("77 Baker Street", "Springfield")


def test_name_on_one_line_and_the_address_on_the_next():
    """Plain lines and numbered items with the address (and details) on the following lines; phone numbers, e-mail
    addresses and people's names (Principal: ...) are never kept."""
    text = """1. **Maple Grove School for the Blind**
   - Address: 123 Main St, Springfield, IL 62701
   - Phone: (217) 555-0100
   - Email: office@example.org
   - Principal: Pat Example
2. **Oak Hill Academy**
   45 Elm Ave
   Springfield, IL 62702

3. **Hilltop Center**
   Coordinates: 39.7817, -89.6501
"""
    rows = pl.parse_pasted(text)
    assert [r.name for r in rows] == ["Maple Grove School for the Blind", "Oak Hill Academy", "Hilltop Center"]
    assert rows[0].address() == "123 Main St, Springfield, IL 62701"
    assert rows[1].address() == "45 Elm Ave, Springfield, IL 62702"
    assert (rows[2].lat, rows[2].lon) == (39.7817, -89.6501)
    kept = " ".join(f"{r.name} {r.address()}" for r in rows)
    for gone in ("555", "office@", "Pat Example"):
        assert gone not in kept
    plain = pl.parse_pasted("Maple Grove School\n123 Main St, Springfield, IL 62701\n\nOak Hill Academy\n"
                            "45 Elm Ave, Springfield, IL 62702\n")
    assert [(r.name, r.street) for r in plain] == [("Maple Grove School", "123 Main St"),
                                                   ("Oak Hill Academy", "45 Elm Ave")]


def test_pasted_csv_and_tab_separated_text():
    """CSV text with a header (a quoted name with a comma) and tab-separated text copied from a spreadsheet (a ZIP
    code that lost its leading zero gets it back)."""
    rows = pl.parse_pasted('Business Name,Street,City,State,ZIP,Phone\n"Maple Grove, Inc.",123 Main St,'
                           'Springfield,IL,62701,555-0100\n')
    assert [(r.name, r.street, r.zip) for r in rows] == [("Maple Grove, Inc.", "123 Main St", "62701")]
    rows = pl.parse_pasted("Name\tAddress\tCity\tState\tZip\nPine School\t5 Pine St\tAmherst\tMA\t1002\n")
    assert [(r.name, r.street, r.city, r.state, r.zip) for r in rows] == [
        ("Pine School", "5 Pine St", "Amherst", "MA", "01002")]


def test_headers_recognised_in_any_layout():
    """Common header names in any capitals and spacing; a list exporter's own names; a contacts file's "Name" (a
    person) loses to its company column."""
    m = pl.map_headers(["Company_Name", "ADDRESS1", "Town", "Region", "Postal Code", "Lat", "Lng"])
    assert m == {"name": 0, "street": 1, "city": 2, "state": 3, "zip": 4, "lat": 5, "lon": 6}
    m = pl.map_headers(["Business Name", "Operating Name (Alt)", "Legal Name", "Street", "City", "State", "ZIP",
                        "Phone", "Website", "Latitude", "Longitude"])
    assert (m["name"], m["street"], m["zip"], m["lat"], m["lon"]) == (0, 3, 6, 9, 10)
    m = pl.map_headers(["email", "first_name", "last_name", "company_name", "website", "phone", "city", "state"])
    assert (m["name"], m["city"], m["state"]) == (3, 6, 7)
    m = pl.map_headers(["Name", "Given Name", "Family Name", "Organization 1 - Name"])
    assert m["name"] == 3
    m = pl.map_headers(["id", "name", "operating_name_alt", "street", "city", "state", "zip", "lat", "lon"])
    assert (m["name"], m["street"], m["lat"], m["lon"]) == (1, 3, 7, 8)


# ------------------------------------------------------------------------------------------- files

def test_csv_and_excel_files(tmp_path):
    """A CSV file (any column order) and an .xlsx workbook whose header is not on the first row."""
    path = tmp_path / "list.csv"
    path.write_text("ZIP,City,Name,Address,State\n62701,Springfield,Maple Grove School,123 Main St,IL\n",
                    encoding="utf-8")
    rows = list(pl.read_file(str(path)))
    assert [(r.name, r.street, r.city, r.state, r.zip, r.where) for r in rows] == [
        ("Maple Grove School", "123 Main St", "Springfield", "IL", "62701", "line 2")]
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["My schools"])
    sheet.append(["School", "Address", "City", "State"])
    sheet.append(["Oak Hill Academy", "45 Elm Ave", "Springfield", "Illinois"])
    book.save(tmp_path / "list.xlsx")
    rows = list(pl.read_file(str(tmp_path / "list.xlsx")))
    assert [(r.name, r.street, r.state) for r in rows] == [("Oak Hill Academy", "45 Elm Ave", "IL")]


def made_up_database(path):
    """A database with a table of businesses, a table of people (not places) and a table of notes."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE business (id INTEGER PRIMARY KEY, name TEXT, street TEXT, city TEXT, state TEXT, zip TEXT,
                               lat REAL, lon REAL);
        INSERT INTO business VALUES (1, 'Maple Grove School', '123 Main St', 'Springfield', 'IL', '62701', NULL, NULL);
        INSERT INTO business VALUES (2, 'Hilltop Center', '', 'Springfield', 'IL', '', 39.7817, -89.6501);
        CREATE TABLE person (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, email TEXT);
        INSERT INTO person VALUES (1, 'Pat', 'Example', 'pat@example.org');
        CREATE TABLE branch (branch_name TEXT, city TEXT, state TEXT);
        INSERT INTO branch VALUES ('Oak Hill Branch', 'Springfield', 'IL');
        CREATE TABLE notes (body TEXT);
    """)
    con.commit()
    con.close()


def test_sqlite_database_read_only_with_a_choice_of_tables(tmp_path):
    """The tables with places are offered (best first); people and notes are not; the file is never changed."""
    path = str(tmp_path / "list.db")
    made_up_database(path)
    before = (os.path.getmtime(path), os.path.getsize(path))
    tables = pl.sqlite_tables(path)
    assert [t.name for t in tables] == ["business", "branch"]
    assert tables[0].label().startswith("business (2 rows: name, street, city, state, zip, lat, lon)")
    rows = list(pl.read_file(path))
    assert [(r.name, r.street, r.located) for r in rows] == [("Maple Grove School", "123 Main St", False),
                                                             ("Hilltop Center", "", True)]
    assert [r.name for r in pl.read_file(path, "branch")] == ["Oak Hill Branch"]
    con = pl.open_database(path)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO notes VALUES ('x')")
    con.close()
    assert (os.path.getmtime(path), os.path.getsize(path)) == before


def test_sql_file_is_loaded_safely(tmp_path):
    """Only CREATE TABLE and INSERT run; ATTACH, PRAGMA, triggers, DROP, DELETE and UPDATE are skipped and
    counted, and nothing outside the in-memory database is touched."""
    target = tmp_path / "attached.db"
    sql = tmp_path / "list.sql"
    sql.write_text(f"""-- made-up places
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE places (name TEXT, address TEXT, lat REAL, lon REAL);
INSERT INTO places VALUES ('O''Malley''s Corner; Store', '1 Pine St, Springfield, IL', 39.79, -89.63);
INSERT INTO places VALUES ('Hilltop Center', '', 39.7817, -89.6501);
ATTACH DATABASE '{target}' AS other;
CREATE TRIGGER t AFTER INSERT ON places BEGIN DELETE FROM places; END;
DROP TABLE places;
DELETE FROM places;
UPDATE places SET name = 'changed';
INSERT INTO places SELECT name, address, lat, lon FROM places WHERE load_extension('x') IS NULL;
COMMIT;
""", encoding="utf-8")
    con, stats = pl.load_sql(str(sql))
    assert stats == {"run": 3, "skipped": 6, "failed": 1}
    assert not target.exists()
    assert [r[0] for r in con.execute("SELECT name FROM places")] == ["O'Malley's Corner; Store", "Hilltop Center"]
    con.close()
    rows = list(pl.read_file(str(sql)))
    assert [r.name for r in rows] == ["O'Malley's Corner; Store", "Hilltop Center"]


# ------------------------------------------------------------------------------------------- finding places

@pytest.fixture
def pack_folder(tmp_path):
    """A folder with the made-up Illinois pack."""
    folder = tmp_path / "packs"
    listpack.build(str(folder))
    return str(folder)


def test_addresses_found_in_the_place_pack(pack_folder):
    """Address points (in the right town when two towns have the street), address ranges, a name in its town,
    positions given in the list, and a short report of what could not be located (never silently dropped)."""
    text = """- Maple Grove School, 123 Main St, Springfield, IL 62701
- Oak Hill Academy, 150 Elm Avenue, Springfield, IL 62702
- River Shop, 123 Main Street, Riverton, IL
- Pinecrest Park, Springfield, IL
- Riverside Diner — 9 River Rd., Springfield, Illinois
- Hilltop Center: 39.7817, -89.6501
- Nowhere Cafe, 77 Nowhere Lane, Springfield, IL
- Lost Place
- Faraway Shop, 1 Main St, Smalltown, VT
"""
    rows = pl.parse_pasted(text)
    locator = pl.Locator(pack_folder)
    assert locator.regions_needed(rows) == {"us-illinois": 6, "us-vermont": 1}
    locator.locate(rows)
    got = by_name(rows)
    assert (got["Maple Grove School"].lat, got["Maple Grove School"].lon) == listpack.MAPLE
    assert got["Maple Grove School"].found_by == "address point"
    assert (got["River Shop"].lat, got["River Shop"].lon) == listpack.RIVERTON_MAIN
    oak = got["Oak Hill Academy"]
    assert oak.found_by == "address range" and abs(oak.lat - 39.81) < 1e-6 and -89.646 < oak.lon < -89.644
    assert got["Pinecrest Park"].found_by == "name in the town"
    assert pl.metres(got["Pinecrest Park"].lat, got["Pinecrest Park"].lon, *listpack.PARK) < 1
    assert got["Riverside Diner"].located
    assert got["Hilltop Center"].found_by == "position in the list"
    assert got["Nowhere Cafe"].why == "the address was not found in the place pack"
    assert got["Lost Place"].why == "no address or position"
    assert got["Faraway Shop"].why == "the place pack for VT is not on this computer"
    assert pl.summary(rows) == {"found": 9, "located": 6, "not located": 3, "duplicates": 0}
    report = pl.report_lines(rows)
    assert len(report) == 3 and report[0].startswith("line 7: Nowhere Cafe — 77 Nowhere Lane")


def test_duplicates_and_the_summary():
    """A place already in My places (the same name within 100 m) and a place twice in the list are duplicates."""
    rows = pl.parse_pasted("- Hilltop Center: 39.7817, -89.6501\n- Pine Shop: 39.80, -89.60\n"
                           "- Pine Shop: 39.8001, -89.6001\n- Pine Shop: 39.90, -89.60\n")
    pl.Locator(None).locate(rows)
    assert pl.find_duplicates(rows, [("HILLTOP center", 39.7818, -89.6502)]) == 2
    assert [r.status for r in rows] == ["duplicate", "located", "duplicate", "located"]
    assert pl.summary_text(rows) == ("4 places found; 2 located; 0 could not be located; 2 duplicates of My places "
                                     "(or repeated in the list)")


def test_the_grid_is_fast_with_a_very_large_list():
    """156,000 places: the grid finds the nearest place within 60 m in a few cells, quickly."""
    grid = pl.PlaceGrid()
    for i in range(156_000):
        grid.add(30 + (i % 400) * 0.01, -100 + (i // 400) * 0.01, i)
    start = time.time()
    for k in range(10_000):
        hit = grid.nearest(30 + (k % 400) * 0.01 + 0.0003, -100 + (k // 400) * 0.01, 60)
        assert hit is not None and hit[1] == k and 30 < hit[0] < 40
    assert grid.nearest(30.005, -99.995, 60) is None
    assert time.time() - start < 5


def test_a_very_large_csv_is_streamed(tmp_path):
    """A CSV of 156,000 rows with positions is read row by row, quickly."""
    path = tmp_path / "big.csv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("name,street,city,state,zip,latitude,longitude\n")
        for i in range(156_000):
            f.write(f"Shop {i},{i} Main St,Springfield,IL,62701,{30 + i % 400 * 0.01:.5f},"
                    f"{-100 + i // 400 * 0.01:.5f}\n")
    start = time.time()
    seen = []
    count = sum(1 for r in pl.read_file(str(path), progress=lambda d, t: seen.append((d, t))) if r.located)
    assert count == 156_000 and seen and seen[-1][1] == os.path.getsize(path)
    assert time.time() - start < 30


# ------------------------------------------------------------------------------------------- My places

def located(text):
    """Rows of pasted text, located (they have positions)."""
    rows = pl.parse_pasted(text)
    pl.Locator(None).locate(rows)
    return rows


def test_lists_are_saved_found_within_60_metres_and_removed_together(tmp_path):
    """Imported places keep their list's name, are saved compactly, name a position within 60 m only, and are
    removed together."""
    places = mp.MyPlaces(path=str(tmp_path / "my.json"))
    places.add(mp.MyPlace("Grandma's house", 36.0, -75.7))
    assert places.add_list("Schools list", located("- Maple Grove School: 39.80120, -89.64410\n"
                                                   "- Oak Hill Academy: 39.81, -89.645\n")) == 2
    places.save()
    again = mp.MyPlaces.load(str(tmp_path / "my.json"))
    assert again.list_names() == [("Schools list", 2)] and len(again.places) == 1
    assert again.find_listed(39.80120 + 0.0004, -89.64410).name == "Maple Grove School"   # about 45 m
    assert again.find_listed(39.80120 + 0.0009, -89.64410) is None                         # about 100 m
    assert again.find(39.8012, -89.6441) is None          # a list's place never names a folder
    assert again.remove_list("Schools list") == 2 and again.find_listed(39.8012, -89.6441) is None
    data = json.load(open(tmp_path / "my.json", encoding="utf-8"))
    assert data["lists"]["Schools list"][0] == ["Maple Grove School", 39.8012, -89.6441]


def test_a_place_from_a_list_names_the_picture(tmp_path, finder):
    """Places.exact: a place from a list within 60 m gives the picture's exact place; your own places still come
    first; farther away the packs' name is used."""
    mine = mp.MyPlaces()
    mine.add_list("Shops", located("- Dune Kite Shop: 35.9600, -75.6300\n- Grandma's Diner: 36.0300, -75.6700\n"))
    mine.add(mp.MyPlace("Grandma's house", 36.0300, -75.6700, 100))
    places = Places(finder=finder, my_places=mine)
    spot = places.exact(35.9603, -75.6300)
    assert spot.name == "Dune Kite Shop"
    assert places.exact(35.9650, -75.6300).name != "Dune Kite Shop"
    own = places.exact(36.0300, -75.6700)
    assert own.my_place == "Grandma's house"


@pytest.mark.parametrize("ending", [".db", ".sql", ".csv", ".json"])
def test_export_then_import_gives_the_same_places(tmp_path, ending):
    """Export (all) to a SQLite database, a .sql file, a CSV file or JSON, then import into an empty My places: the
    same places, the same distances and the same lists."""
    places = mp.MyPlaces()
    places.add(mp.MyPlace("Grandma's house", 36.0123, -75.6789, 250))
    places.add(mp.MyPlace("O'Brien's \"cabin\"; north", 44.1, -72.1))
    places.add_list("Schools list", located("- Maple Grove School: 39.8012, -89.6441\n"))
    places.add_list("Shops", located("- Dune Kite Shop: 35.96, -75.63\n"))
    path = str(tmp_path / f"out{ending}")
    assert places.export(path) == 4
    other = mp.MyPlaces()
    added, problems = other.import_file(path)
    assert (added, problems) == (4, [])
    assert [(p.name, p.lat, p.lon, p.radius_m) for p in other.places] == \
        [(p.name, p.lat, p.lon, p.radius_m) for p in places.places]
    assert other.export_rows() == places.export_rows()


def test_export_only_one_list_or_only_your_own(tmp_path):
    """Export can save only one list, or only the places you added yourself; the .sql is plain SQL."""
    places = mp.MyPlaces()
    places.add(mp.MyPlace("Grandma's house", 36.0123, -75.6789))
    places.add_list("Schools list", located("- Maple Grove School: 39.8012, -89.6441\n"))
    assert places.export(str(tmp_path / "one.sql"), "Schools list") == 1
    text = (tmp_path / "one.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE my_places" in text and "Grandma" not in text
    assert "INSERT INTO my_places (name, latitude, longitude, metres, list) VALUES ('Maple Grove School', 39.8012, " \
           "-89.6441, 60.0, 'Schools list');" in text
    assert places.export(str(tmp_path / "own.db"), "") == 1
    con = sqlite3.connect(str(tmp_path / "own.db"))
    assert con.execute("SELECT name, list FROM my_places").fetchall() == [("Grandma's house", "")]
    con.close()


def test_import_of_a_database_without_positions_says_so(tmp_path):
    """My places' Import reads only places with positions; the others are named (Import places from a list finds
    them by their address)."""
    path = str(tmp_path / "list.db")
    made_up_database(path)
    places = mp.MyPlaces()
    added, problems = places.import_file(path)
    assert added == 1 and places.places[0].name == "Hilltop Center"
    assert problems == ["business row 1: Maple Grove School has no position (Import places from a list can find "
                        "it by its address)"]
