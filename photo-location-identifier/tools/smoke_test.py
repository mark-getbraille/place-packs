"""The installer's smoke test (Windows, run by the workflow after the installer is built):

    python tools/smoke_test.py dist/PhotoLocationIdentifier-1.3.0-setup.exe

1. Installs the program silently for the current user into a temporary folder.
2. Checks File Explorer's "Sort pictures by location" entries (folder and folder background) are in the registry.
3. Starts the window and checks it is still running after a few seconds (then closes it).
4. Builds a tiny made-up place pack with placepacks' own builder (tools/make_test_pack.py) and writes made-up photos
   with EXIF GPS: the Outer Banks in July 2005 and July 2006, and Wrightsville Beach (another beach) in 2007.
5. Runs the installed program's command-line sort on them (no internet: --packs never) and checks the folders are
   exactly "Outer Banks 2005", "Outer Banks 2006" and "Wrightsville Beach 2007", and that the report was written.
6. Runs --undo-last and checks every photo is back.
7. Uninstalls silently and checks the menu entries are gone.
Exit code 0 when everything passed.
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_test_pack  # noqa: E402

KEYS = [r"Software\Classes\Directory\shell\PhotoLocationIdentifier\command",
        r"Software\Classes\Directory\Background\shell\PhotoLocationIdentifier\command"]


def step(text):
    """Print a step heading."""
    print(f"\n== {text}", flush=True)


def check(condition, text):
    """Fail with text unless condition."""
    if not condition:
        print(f"FAILED: {text}", flush=True)
        sys.exit(1)
    print(f"ok: {text}", flush=True)


def registry_value(key):
    """The default value of HKEY_CURRENT_USER\\key, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def run(cmd, timeout=600):
    """Run a program and wait; returns its exit code (output shown)."""
    print("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    return subprocess.run(cmd, timeout=timeout).returncode


def main(setup):
    """The smoke test (see the module docstring)."""
    work = tempfile.mkdtemp(prefix="pli-smoke-")
    app_dir = os.path.join(work, "app")
    exe = os.path.join(app_dir, "PhotoLocationIdentifier.exe")
    step("Install silently")
    code = run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", f"/DIR={app_dir}",
                f"/LOG={os.path.join(work, 'install.log')}"])
    check(code == 0 and os.path.exists(exe), f"installed (exit code {code})")
    for key in KEYS:
        value = registry_value(key)
        check(value is not None and exe.lower() in value.lower() and "--open" in value, f"menu entry {key}: {value}")

    step("The window starts on a folder, as File Explorer's menu entry starts it")
    proc = subprocess.Popen([exe, "--open", work], env={**os.environ, "PLI_HOME": os.path.join(work, "home")})
    time.sleep(8)
    check(proc.poll() is None, "the window is still running after 8 seconds")
    proc.kill()
    proc.wait()

    step("Command-line sort of made-up photos with a made-up place pack")
    packs = os.path.join(work, "packs")
    photos = os.path.join(work, "Family photos")
    make_test_pack.build(packs)
    make_test_pack.write_photos(photos)
    env = {**os.environ, "PLI_HOME": os.path.join(work, "home"), "PLACEPACKS_DIR": packs}
    cmd = [exe, "--folder", photos, "--detail", "trip-area", "--time", "year", "--template", "{place} {year}",
           "--packs", "never", "--packs-folder", packs]
    print("> " + " ".join(cmd), flush=True)
    code = subprocess.run(cmd + ["--dry-run"], env=env, timeout=300).returncode
    check(code == 0, f"dry run (exit code {code})")
    check(len(os.listdir(photos)) == len(make_test_pack.PHOTOS), "the dry run moved nothing")
    code = subprocess.run(cmd, env=env, timeout=300).returncode
    check(code == 0, f"sort (exit code {code})")
    made = sorted(d for d in os.listdir(photos) if os.path.isdir(os.path.join(photos, d)))
    print("Folders made:", made)
    check(made == make_test_pack.EXPECTED_FOLDERS, f"the folders are {make_test_pack.EXPECTED_FOLDERS}")
    for folder, count in (("Outer Banks 2005", 3), ("Outer Banks 2006", 2), ("Wrightsville Beach 2007", 2)):
        check(len(os.listdir(os.path.join(photos, folder))) == count, f"{folder} has {count} photos")
    reports = [f for f in os.listdir(photos) if f.endswith(".txt")]
    check(len(reports) == 1, f"the report was written: {reports}")
    text = open(os.path.join(photos, reports[0]), encoding="utf-8-sig").read()
    check("OpenStreetMap" in text, "the report has the OpenStreetMap attribution")

    step("Undo the last sort")
    code = subprocess.run([exe, "--undo-last"], env=env, timeout=300).returncode
    back = sorted(f for f in os.listdir(photos) if f.endswith(".jpg"))
    check(code == 0 and back == sorted(n for n, *_ in make_test_pack.PHOTOS), "every photo is back")

    step("Uninstall silently")
    uninstaller = os.path.join(app_dir, "unins000.exe")
    code = run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    for _ in range(30):
        if not os.path.exists(exe):
            break
        time.sleep(1)
    check(not os.path.exists(exe), f"uninstalled (exit code {code})")
    for key in KEYS:
        check(registry_value(key) is None, f"menu entry removed: {key}")
    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(os.path.abspath(sys.argv[1])))
