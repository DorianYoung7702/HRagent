# Dump Liepin LPT search-page filter labels for lpt_adapter calibration.
# Requires logged-in browser profile (same as login_liepin.ps1).
param(
    [string]$ProfileDir = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_encoding.ps1"
. "$PSScriptRoot\_resolve_python.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$Py = Get-ProjectPythonPath $Root
if (-not $ProfileDir) {
    $ProfileDir = Join-Path $Root "data\browser_profiles\hr_default"
}

$script = @'
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    profile = Path(r"__PROFILE__")
    out = Path(r"__OUT__")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://lpt.liepin.com/search", wait_until="load", timeout=60000)
        await page.wait_for_timeout(3000)
        labels = await page.evaluate("""() => {
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 4 && r.height > 4 && r.top > 40 && r.top < 480;
            };
            const texts = new Set();
            for (const el of document.querySelectorAll('span, label, div, button, li, a, p')) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || '').trim();
                if (!t || t.length > 24) continue;
                texts.add(t);
            }
            return Array.from(texts).sort();
        }""")
        shot = out / "lpt_filters_debug.png"
        await page.screenshot(path=str(shot), full_page=False)
        (out / "lpt_filter_labels.json").write_text(
            json.dumps(labels, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved {len(labels)} labels -> {out / 'lpt_filter_labels.json'}")
        print(f"Screenshot -> {shot}")
        await ctx.close()

asyncio.run(main())
'@

$outDir = Join-Path $Root "data\debug"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$pyScript = Join-Path $env:TEMP "debug_lpt_filters_run.py"
$script.Replace("__PROFILE__", $ProfileDir.Replace("\", "\\")).Replace("__OUT__", $outDir.Replace("\", "\\")) | Set-Content $pyScript -Encoding UTF8
& $Py $pyScript
