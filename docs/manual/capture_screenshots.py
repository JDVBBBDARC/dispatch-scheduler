"""Capture screenshots of every module page in the locally-running
Flask app, save them to docs/manual/screenshots/.

Prerequisites:
    1. Flask app running on http://localhost:5001 (or set LOCAL_URL).
    2. admin user password reset to MANUAL_PASSWORD.
    3. playwright + chromium installed (see install commands above).

Usage:
    python docs/manual/capture_screenshots.py
"""
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

LOCAL_URL = os.environ.get('LOCAL_URL', 'http://localhost:5001')
MANUAL_USER = 'admin'
MANUAL_PASSWORD = 'manual-capture-2026'   # set by the reset helper

ROOT = Path(__file__).resolve().parent.parent.parent
OUT  = Path(__file__).resolve().parent / 'screenshots'
OUT.mkdir(exist_ok=True)


# (filename, path, description, full_page?, post-load wait sec)
TODAY = date.today().isoformat()
PAGES = [
    ('dashboard.png',     '/',                       'Dashboard',                   True,  4),
    ('schedule.png',      f'/schedule/{TODAY}',      'Schedule (today)',            True,  3),
    ('master.png',        '/master',                 'Master Data',                 True,  3),
    ('breakdown.png',     '/breakdown',              'Breakdown',                   True,  3),
    ('toll_calculator.png','/toll-calculator',       'Toll Calculator',             True,  2),
    ('toll_log.png',      '/toll-log',               'Toll Log',                    True,  3),
    ('truck_cycle.png',   '/truck-cycle-time',       'Truck Cycle Time',            True,  4),
    ('reports.png',       '/reports',                'Reports',                     True,  3),
]


async def capture():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            device_scale_factor=2,            # retina-sharp PNGs
        )
        page = await context.new_page()

        # ── Login first so the session cookie carries to every page ──
        print(f'[login] -> {LOCAL_URL}/login')
        await page.goto(f'{LOCAL_URL}/login', wait_until='networkidle')
        # Capture the login page itself BEFORE submitting credentials.
        await page.wait_for_timeout(1500)
        out_path = OUT / 'login.png'
        await page.screenshot(path=str(out_path), full_page=False)
        print(f'  -> {out_path.name}')

        # Fill the login form. The auth template uses name="username" and
        # name="password".
        await page.fill('input[name="username"]', MANUAL_USER)
        await page.fill('input[name="password"]', MANUAL_PASSWORD)
        await page.click('button[type="submit"]')
        try:
            await page.wait_for_url(f'{LOCAL_URL}/', timeout=10000)
        except Exception:
            await page.wait_for_timeout(2000)
        print(f'  logged in as {MANUAL_USER}')

        # ── Capture each authenticated page ──
        for filename, path, desc, full_page, wait_s in PAGES:
            if filename == 'login.png':
                continue   # already captured
            url = LOCAL_URL.rstrip('/') + path
            print(f'[{desc}] -> {url}')
            try:
                await page.goto(url, wait_until='networkidle', timeout=20000)
            except Exception as e:
                print(f'  navigation slow: {e}; continuing anyway')
            await page.wait_for_timeout(int(wait_s * 1000))
            out_path = OUT / filename
            try:
                await page.screenshot(path=str(out_path),
                                       full_page=full_page,
                                       timeout=15000)
                size_kb = out_path.stat().st_size / 1024
                print(f'  -> {out_path.name} ({size_kb:,.0f} KB, full_page={full_page})')
            except Exception as e:
                print(f'  CAPTURE FAILED: {e}')

        await browser.close()


if __name__ == '__main__':
    asyncio.run(capture())
    print()
    print(f'All screenshots written to: {OUT}')
    for f in sorted(OUT.glob('*.png')):
        print(f'  {f.name}  ({f.stat().st_size/1024:,.0f} KB)')
