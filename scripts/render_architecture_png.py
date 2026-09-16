from pathlib import Path
from PIL import Image
import subprocess
import shutil

root = Path(__file__).resolve().parents[1]
svg = root / "docs" / "mori-system-architecture-2026.svg"
png = root / "docs" / "mori-system-architecture-2026.png"
browser = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
if not browser.exists():
    browser = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
profile = root / ".tmp-edge-architecture"
subprocess.run([str(browser), "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars", f"--user-data-dir={profile}", "--window-size=1800,1125", f"--screenshot={png}", svg.as_uri()], check=True)
shutil.rmtree(profile, ignore_errors=True)
with Image.open(png) as image:
    assert image.size == (1800, 1125), image.size
print(png)
