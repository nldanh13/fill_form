from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from db import ROOT


def main():
    with sync_playwright() as playwright:
        context=playwright.chromium.launch_persistent_context(
            user_data_dir=str(ROOT/"data"/"browser_profile"),
            headless=False,
            viewport={"width":1200,"height":820},
        )
        page=context.pages[0] if context.pages else context.new_page()
        page.goto("https://accounts.google.com/",wait_until="domcontentloaded")
        while context.pages:
            time.sleep(1)


if __name__=="__main__":
    main()
