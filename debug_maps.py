import asyncio
import os
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=USER_AGENTS[0],
        )
        page = await context.new_page()

        stealth = Stealth()
        await stealth.apply_stealth_async(page)

        print("Navigating to Google Maps search...")
        await page.goto(
            "https://www.google.com/maps/search/real+estate+in+dhaka",
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(3)

        print("Looking for listing...")
        listings = await page.query_selector_all('a[href*="/maps/place"]')
        print(f"Found {len(listings)} listings")

        if listings:
            listing = listings[0]
            href = await listing.get_attribute("href")
            print(f"Clicking first listing: {href[:50]}...")

            new_page = await context.new_page()
            await new_page.goto(href)
            await asyncio.sleep(4)

            print("\n=== PAGE URL ===")
            print(new_page.url)

            print("\n=== ALL BUTTONS (aria-label) ===")
            buttons = await new_page.query_selector_all("button")
            for btn in buttons[:20]:
                try:
                    aria = await btn.get_attribute("aria-label")
                    text = await btn.inner_text()
                    data_item = await btn.get_attribute("data-item-id")
                    if aria or text or data_item:
                        print(
                            f"  aria-label: {aria}, text: {text[:30]}, data-item-id: {data_item}"
                        )
                except:
                    pass

            print("\n=== ALL LINKS (href) ===")
            links = await new_page.query_selector_all("a[href]")
            for link in links[:30]:
                try:
                    href = await link.get_attribute("href")
                    if href and "http" in href and "google" not in href.lower():
                        print(f"  {href[:80]}")
                except:
                    pass

            print("\n=== ELEMENTS WITH PHONE-RELATED ATTRIBUTES ===")
            phone_elements = await new_page.query_selector_all(
                '[data-item-id*="phone"], [aria-label*="phone"], [aria-label*="Copy"]'
            )
            for el in phone_elements:
                try:
                    aria = await el.get_attribute("aria-label")
                    data_item = await el.get_attribute("data-item-id")
                    text = await el.inner_text()
                    print(
                        f"  aria-label: {aria}, data-item-id: {data_item}, text: {text[:30]}"
                    )
                except:
                    pass

            print("\n=== BODY TEXT (first 2000 chars) ===")
            body = await new_page.evaluate("() => document.body.innerText")
            print(body[:2000])

            html_file = "maps_listing_debug.html"
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(await new_page.content())
            print(f"\nFull HTML saved to {html_file}")

            await new_page.close()

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
