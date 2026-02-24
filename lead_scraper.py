import asyncio
import logging
import os
import random
import re
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter to prevent request spam."""

    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time = 0.0

    async def wait(self) -> None:
        """Wait appropriate time before next request."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_delay:
            wait_time = (
                self.min_delay
                - elapsed
                + random.uniform(0, self.max_delay - self.min_delay)
            )
            await asyncio.sleep(wait_time)
        self.last_request_time = time.time()


def retry_on_failure(max_retries: int = 3, delay: float = 1.0) -> Callable[[F], F]:
    """Decorator to retry async functions on failure."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying..."
                        )
                        await asyncio.sleep(delay * (attempt + 1))
                    else:
                        logger.error(f"All {max_retries} attempts failed")
            raise last_exception  # type: ignore[arg-type]

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


SEARCH_CONFIG = {
    "keywords": "",
    "client_type": "",
    "location": "",
    "max_scrolls": 15,
    "results_limit": 100,
    "search_type": "maps",
    "dork_query": "",
    "target": "email",
}

PHONE_REGEX = r"(\+[\d\u00C0-\u00FF\u2070-\u209F\u2080-\u208F]{1,3}[-.\s]?\(?[\d\u00C0-\u00FF\u2070-\u209F\u2080-\u208F]{3}\)?[-.\s]?[\d\u00C0-\u00FF\u2070-\u209F\u2080-\u208F]{3}[-.\s]?[\d\u00C0-\u00FF\u2070-\u209F\u2080-\u208F]{4})"
EMAIL_REGEX = r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"

UNICODE_DIGITS = str.maketrans(
    "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵０１２３４５６７８９₀₁₂₃₄₅₆₇₈₉⓪①②③④⑤⑥⑦⑧⑨",
    "0123456789012345678901234567890123456789012345678901234567890123456789",
)

BD_PHONE_REGEX = r"(?:\+?88)?[01][\d\u00C0-\u00FF\u2070-\u209F\u2080-\u208F]{9}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}  # type: ignore[assignment]

rate_limiter = RateLimiter(min_delay=2.0, max_delay=5.0)


def is_valid_profile_url(url: str) -> bool:
    """Check if URL is a valid social media profile (not generic pages)."""
    if not url:
        return False

    url_lower = url.lower()

    if "facebook.com" in url_lower or "fb.com" in url_lower:
        invalid = [
            "/help/",
            "/login",
            "/accounts/",
            "/photo",
            "/video",
            "/story",
            "/groups/",
            "/pages/",
            "/apps/",
            "/events/",
        ]
        if any(x in url_lower for x in invalid):
            return False
        return True

    if "instagram.com" in url_lower:
        invalid_patterns = [
            "/help/",
            "/login",
            "/accounts/",
            "/reels/",
            "/reel/",
            "/p/",
            "/popular/",
            "/explore/",
            "/about-us/",
            "/?hl=",
            "/tags/",
            "/stories/",
            "/direct/",
            "/settings/",
            "/notifications/",
            "/search/",
            "/activity/",
            "/archive/",
            "/fundraiser/",
            "/ads/",
            "/business/",
            "/developers/",
            "/legal/",
            "/about/",
        ]
        if any(pattern in url_lower for pattern in invalid_patterns):
            return False
        match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)/?$", url_lower)
        if match:
            username = match.group(1)
            if len(username) > 2 and "/" not in username:
                return True
        return False

    return False


async def human_like_scroll(
    page: Any, scroll_pauses: list[float] | None = None
) -> None:
    """Perform human-like scrolling behavior on a page."""
    if scroll_pauses is None:
        scroll_pauses = [0.3, 0.5, 0.8, 0.4, 0.6, 0.7, 0.3, 0.5, 0.9]

    for i, pause in enumerate(scroll_pauses):
        scroll_amount = 300 + (i * 73) % 500
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(pause)
        if i % 3 == 0:
            await page.evaluate("window.scrollBy(0, -100)")
            await asyncio.sleep(0.2)


async def scrape_listing_details(
    page: Any, context: Any, listing_element: Any
) -> dict[str, str] | None:
    """Open listing in new tab and extract details."""
    business_data: dict[str, str] = {
        "Business Name": "",
        "Phone Number": "",
        "Website": "",
        "Address": "",
    }

    try:
        aria_label = await listing_element.get_attribute("aria-label")
        if aria_label:
            business_data["Business Name"] = aria_label.split(" - ")[0].strip()[:100]
    except Exception:
        logger.debug("Failed to get aria-label from listing element")

    if not business_data["Business Name"]:
        return None

    try:
        href = await listing_element.get_attribute("href")
        if not href:
            return None

        # Check if context is still valid
        if hasattr(context, "new_page"):
            new_page = await context.new_page()
        else:
            logger.debug("Context is not valid for creating new page")
            return business_data

        try:
            await new_page.goto(href, timeout=30000)
            await asyncio.sleep(2)
            
            try:
                await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Failed to navigate to {href}: {e}")
            await new_page.close()
            return business_data

        try:
            phone_button = await new_page.query_selector(
                'button[data-item-id^="phone:"]'
            )
            if phone_button:
                data_item = await phone_button.get_attribute("data-item-id")
                if data_item and "tel:" in data_item:
                    phone = data_item.split("tel:")[-1].strip()
                    if phone:
                        business_data["Phone Number"] = phone
                if not business_data["Phone Number"]:
                    aria = await phone_button.get_attribute("aria-label")
                    if aria and ":" in aria:
                        phone_part = aria.split(":")[-1].strip()
                        if phone_part:
                            business_data["Phone Number"] = phone_part
        except Exception:
            logger.debug("Failed to extract phone from button")

        try:
            # Most reliable: look for the Website button specifically
            website_button = await new_page.query_selector('a[data-item-id="authority"]')
            if website_button:
                href = await website_button.get_attribute("href")
                if href:
                    business_data["Website"] = href

            if not business_data["Website"]:
                website_links = await new_page.query_selector_all("a[href]")
                for link in website_links:
                    try:
                        href = await link.get_attribute("href")
                        if href and href.startswith("http"):
                            href_lower = href.lower()
                            # Filter out common non-business URLs
                            if all(x not in href_lower for x in ["google.com", "maps.google", "apple.com", "microsoft.com"]):
                                business_data["Website"] = href
                                break
                    except Exception:
                        pass
        except Exception:
            logger.debug("Failed to extract website from links")

        try:
            address_button = await new_page.query_selector(
                'button[data-item-id="address"]'
            )
            if address_button:
                aria = await address_button.get_attribute("aria-label")
                if aria and "ঠিকানা:" in aria:
                    address = aria.split("ঠিকানা:")[-1].strip()
                    if address:
                        business_data["Address"] = address[:200]
                elif aria:
                    business_data["Address"] = aria[:200]
        except Exception:
            logger.debug("Failed to extract address")

        try:
            body_text = await new_page.evaluate("() => document.body.innerText")
            body_text_normalized = body_text.translate(UNICODE_DIGITS)

            if not business_data["Phone Number"]:
                phone_match = re.search(PHONE_REGEX, body_text)
                if not phone_match:
                    phone_match = re.search(PHONE_REGEX, body_text_normalized)
                if phone_match:
                    business_data["Phone Number"] = phone_match.group(1).strip()

            if not business_data["Phone Number"]:
                bd_phone_match = re.search(BD_PHONE_REGEX, body_text_normalized)
                if bd_phone_match:
                    phone_val = bd_phone_match.group(0).strip()
                    if not phone_val.startswith("+"):
                        phone_val = "+88" + phone_val
                    business_data["Phone Number"] = phone_val

            if not business_data["Phone Number"]:
                all_phones = re.findall(r"01[3-9][\d]{8}", body_text_normalized)
                if all_phones:
                    business_data["Phone Number"] = "+88" + all_phones[0]

            if not business_data["Website"]:
                website_match = re.search(
                    r"(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?!\s*\d)",
                    body_text,
                )
                if website_match:
                    website = website_match.group(0)
                    if not website.startswith("http"):
                        website = "https://" + website
                    if "google" not in website.lower():
                        business_data["Website"] = website

            if not business_data["Address"]:
                address_match = re.search(
                    r"\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln)[,\s]+[A-Za-z\s]+,?\s*(?:NY|NJ|CT|PA)?\s*\d{5}",
                    body_text,
                )
                if address_match:
                    business_data["Address"] = address_match.group(0).strip()[:200]

                bd_address_match = re.search(
                    r"House-?\d+[\s,]+[A-Za-z]+(?:Road|Rd|Street|St|Avenue|Ave|Banani|Gulshan|Dhanmondi|Mirpur|Baridhara)[,\s]*,?\s*Dhaka\s*\d*",
                    body_text,
                    re.IGNORECASE,
                )
                if bd_address_match:
                    business_data["Address"] = bd_address_match.group(0).strip()[:200]

        except Exception:
            logger.debug("Failed to extract details from listing page")

        await new_page.close()

    except Exception:
        logger.debug("Failed to navigate to listing")

    return business_data


async def _initialize_browser(
    headless: bool = True, use_stealth: bool = True
) -> tuple[Any, Any, Any]:
    """Initialize Playwright browser with stealth settings."""
    p = await async_playwright().start()
    user_agent = random.choice(USER_AGENTS)
    browser = await p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
        ],
    )
    context = await browser.new_context(
        viewport=random.choice(
            [
                {"width": 1920, "height": 1080},
                {"width": 1366, "height": 768},
                {"width": 1536, "height": 864},
                {"width": 1440, "height": 900},
            ]
        ),
        user_agent=user_agent,
        locale="en-US,en-GB,en-BD",
        timezone_id="Asia/Dhaka",
        permissions=["geolocation"],
        geolocation={"latitude": 23.8103, "longitude": 90.4125},
    )
    page = await context.new_page()

    if use_stealth:
        try:
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
        except Exception:
            logger.debug("Stealth failed, continuing without it")

    return p, browser, page


async def scrape_google_maps(
    keywords: str,
    location: str,
    max_scrolls: int = 15,
    results_limit: int = 100,
    headless: bool = False,
) -> list[dict[str, str]]:
    """Scrape business listings from Google Maps."""
    results: list[dict[str, str]] = []

    p, browser, page = await _initialize_browser(headless=headless)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} in {location}"
        logger.info(f"Navigating to Google Maps: {search_query}")

        try:
            await page.goto(
                f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Page loaded successfully")
        except Exception as e:
            logger.warning(f"Initial load issue: {e}")
            await page.wait_for_timeout(5000)

        await asyncio.sleep(3)
        logger.info(f"Starting scroll loop (max: {max_scrolls} scrolls)")

        scroll_count = 0
        seen_businesses: set[str] = set()
        processed_hrefs: set[str] = set()

        # Find the scrollable container
        feed_selector = 'div[role="feed"]'
        
        while scroll_count < max_scrolls:
            if page.is_closed():
                logger.error("Main page closed unexpectedly")
                break

            logger.info(
                f"[SCROLL {scroll_count + 1}/{max_scrolls}] Finding listings..."
            )

            # Scroll the feed container instead of the window
            try:
                await page.evaluate(f"""
                    (selector) => {{
                        const el = document.querySelector(selector);
                        if (el) {{
                            el.scrollBy(0, 2000);
                        }}
                    }}
                """, feed_selector)
            except Exception as e:
                logger.debug(f"Scroll evaluation failed: {e}")
                # Fallback to window scroll if feed not found
                await human_like_scroll(page)
            
            await asyncio.sleep(3)

            try:
                # Refresh listings after scroll
                listings = await page.query_selector_all('a[href*="/maps/place"]')
                new_listings = []
                for listing in listings:
                    try:
                        href = await listing.get_attribute("href")
                        if href and href not in processed_hrefs:
                            new_listings.append(listing)
                            processed_hrefs.add(href)
                    except Exception:
                        continue

                logger.info(f"Found {len(listings)} listings, {len(new_listings)} are new")

                for listing in new_listings:
                    if page.is_closed():
                        break
                        
                    try:
                        business_data = await scrape_listing_details(
                            page, page.context, listing
                        )

                        if business_data and business_data.get("Business Name"):
                            business_key = (
                                business_data["Business Name"].strip().lower()
                            )
                            if business_key not in seen_businesses:
                                seen_businesses.add(business_key)
                                results.append(business_data)
                                logger.info(
                                    f"  + {business_data['Business Name'][:40]:<40} | "
                                    f"Phone: {business_data.get('Phone Number', 'N/A')[:15]}"
                                )
                    except Exception as e:
                        logger.debug(f"Failed to process listing: {e}")

                    # Check limit after each listing
                    if len(results) >= SEARCH_CONFIG["results_limit"]:
                        break

            except Exception as e:
                logger.debug(f"Failed to find listings: {e}")

            scroll_count += 1
            logger.info(f"  Total collected so far: {len(results)}")

            if len(results) >= results_limit:
                logger.info(f"Reached results limit: {results_limit}")
                break
            
            # Check if we reached the end of the list
            try:
                end_of_results = await page.query_selector("text=\"You've reached the end of the list.\"")
                if end_of_results:
                    logger.info("Reached end of Google Maps results")
                    break
            except Exception:
                pass

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_yahoo_dork(
    keywords: str,
    dork_query: str,
    max_scrolls: int = 15,
    headless: bool = False,
    target: str = "email",
) -> list[dict[str, str]]:
    """Scrape using Google Dorking - searches for emails/contacts via Yahoo."""
    results: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    seen_profiles: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} {dork_query}".strip()
        logger.info(f"Searching Yahoo: {search_query}")

        try:
            await page.goto(
                f"https://search.yahoo.com/search?p={search_query.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Search results loaded")
        except Exception as e:
            logger.warning(f"Load issue: {e}")
            await page.wait_for_timeout(10000)

        await asyncio.sleep(3)
        logger.info(f"Scraping results (max: {max_scrolls} scrolls)")

        scroll_count = 0
        page_num = 1

        while scroll_count < max_scrolls:
            logger.info(f"[PAGE {page_num}/{max_scrolls}] Processing results...")

            await human_like_scroll(page)
            await asyncio.sleep(2)

            try:
                result_blocks = await page.query_selector_all("div.algo, li.algo")
                new_count = 0

                for block in result_blocks:
                    try:
                        text = await block.inner_text()

                        if target == "profile":
                            link = await block.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if is_valid_profile_url(href):
                                    profile_key = href
                                    if profile_key not in seen_profiles:
                                        seen_profiles.add(profile_key)
                                        result = {
                                            "Business Name": "",
                                            "Phone Number": "",
                                            "Website": "",
                                            "Email": "",
                                            "Source": "Yahoo Search",
                                        }
                                        result["Website"] = href
                                        try:
                                            title = await block.query_selector("h3")
                                            if title:
                                                result["Business Name"] = (
                                                    await title.inner_text()
                                                ).strip()[:100]
                                        except Exception:
                                            logger.debug(
                                                "Failed to extract title from result"
                                            )

                                        emails = re.findall(EMAIL_REGEX, text)
                                        for email in emails:
                                            email_lower = email.lower()
                                            if not email_lower.endswith("@example.com"):
                                                result["Email"] = email_lower
                                                break

                                        phones = re.findall(PHONE_REGEX, text)
                                        if phones:
                                            result["Phone Number"] = phones[0].strip()

                                        results.append(result)
                                        new_count += 1
                                        logger.info(f"  + Profile: {href[:50]}")
                        else:
                            emails = re.findall(EMAIL_REGEX, text)
                            for email in emails:
                                email_lower = email.lower()
                                if (
                                    email_lower not in seen_emails
                                    and not email_lower.endswith("@example.com")
                                ):
                                    seen_emails.add(email_lower)

                                    result = {
                                        "Business Name": "",
                                        "Phone Number": "",
                                        "Website": "",
                                        "Email": email,
                                        "Source": "Yahoo Search",
                                    }

                                    try:
                                        link = await block.query_selector("a")
                                        if link:
                                            href = await link.get_attribute("href")
                                            if (
                                                href
                                                and href.startswith("http")
                                                and "yahoo" not in href
                                            ):
                                                result["Website"] = href
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract website from result"
                                        )

                                    try:
                                        title = await block.query_selector("h3")
                                        if title:
                                            result["Business Name"] = (
                                                await title.inner_text()
                                            ).strip()[:100]
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract title from result"
                                        )

                                    phone_match = re.search(PHONE_REGEX, text)
                                    if phone_match:
                                        result["Phone Number"] = phone_match.group(
                                            1
                                        ).strip()

                                    results.append(result)
                                    new_count += 1
                                    logger.info(f"  + {email[:40]}")

                    except Exception:
                        logger.debug("Failed to process result block")

                logger.info(f" | New: {new_count} | Total: {len(results)}")

            except Exception:
                logger.debug("Failed to find result blocks")

            next_clicked = False
            if scroll_count < max_scrolls - 1:
                next_button = (
                    await page.query_selector('a[href*="b="]')
                    or await page.query_selector('a[aria-label="Next"]')
                    or await page.query_selector("a[aria-label='Next page']")
                    or await page.query_selector("button[aria-label='Next']")
                    or await page.query_selector("a.next")
                )
                if next_button:
                    try:
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        next_clicked = True
                        page_num += 1
                        logger.info(f"Moved to page {page_num}")
                    except Exception:
                        logger.debug(
                            "Failed to click next button, trying URL navigation"
                        )
                        try:
                            current_url = page.url
                            if "b=" in current_url:
                                match = re.search(r"b=(\d+)", current_url)
                                if match:
                                    new_b = int(match.group(1)) + 10
                                    new_url = re.sub(
                                        r"b=\d+", f"b={new_b}", current_url
                                    )
                                else:
                                    new_url = f"{current_url}&b=10"
                            else:
                                new_url = f"{current_url}&b=10"
                            await page.goto(
                                new_url, wait_until="networkidle", timeout=60000
                            )
                            page_num += 1
                            next_clicked = True
                            logger.info(f"Moved to page {page_num} via URL")
                        except Exception as e:
                            logger.debug(f"URL navigation also failed: {e}")
                else:
                    logger.debug("Next button not found, trying URL navigation")
                    try:
                        current_url = page.url
                        if "b=" in current_url:
                            match = re.search(r"b=(\d+)", current_url)
                            if match:
                                new_b = int(match.group(1)) + 10
                                new_url = re.sub(r"b=\d+", f"b={new_b}", current_url)
                            else:
                                new_url = f"{current_url}&b=10"
                        else:
                            new_url = f"{current_url}&b=10"
                        await page.goto(
                            new_url, wait_until="networkidle", timeout=60000
                        )
                        page_num += 1
                        next_clicked = True
                        logger.info(f"Moved to page {page_num} via URL")
                    except Exception as e:
                        logger.debug(f"URL navigation failed: {e}")

            scroll_count += 1

            if len(results) >= SEARCH_CONFIG["results_limit"]:
                logger.info(f"Reached results limit: {SEARCH_CONFIG['results_limit']}")
                break

            if not next_clicked:
                if scroll_count >= max_scrolls:
                    logger.info("No more pages available")
                    break
                else:
                    logger.warning(
                        f"Failed to navigate to next page from page {page_num}, stopping"
                    )
                    break

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_bing_dork(
    keywords: str,
    dork_query: str,
    max_scrolls: int = 15,
    headless: bool = False,
    target: str = "email",
) -> list[dict[str, str]]:
    """Scrape using Bing Dorking - searches for emails/contacts via Bing."""
    results: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    seen_profiles: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} {dork_query}".strip()
        logger.info(f"Searching Bing: {search_query}")

        try:
            await page.goto(
                f"https://www.bing.com/search?q={search_query.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Search results loaded")
        except Exception as e:
            logger.warning(f"Load issue: {e}")
            await page.wait_for_timeout(10000)

        await asyncio.sleep(3)
        logger.info(f"Scraping results (max: {max_scrolls} scrolls)")

        scroll_count = 0
        page_num = 1

        while scroll_count < max_scrolls:
            logger.info(f"[PAGE {page_num}/{max_scrolls}] Processing results...")

            await human_like_scroll(page)
            await asyncio.sleep(2)

            try:
                result_blocks = await page.query_selector_all("li.b_algo")
                new_count = 0

                for block in result_blocks:
                    try:
                        text = await block.inner_text()

                        if target == "profile":
                            link = await block.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if is_valid_profile_url(href):
                                    profile_key = href
                                    if profile_key not in seen_profiles:
                                        seen_profiles.add(profile_key)
                                        result = {
                                            "Business Name": "",
                                            "Phone Number": "",
                                            "Website": "",
                                            "Email": "",
                                            "Source": "Bing Search",
                                        }
                                        result["Website"] = href
                                        try:
                                            title = await block.query_selector("h3")
                                            if title:
                                                result["Business Name"] = (
                                                    await title.inner_text()
                                                ).strip()[:100]
                                            else:
                                                result["Business Name"] = href
                                        except Exception:
                                            logger.debug(
                                                "Failed to extract title from result"
                                            )
                                            result["Business Name"] = href

                                        emails = re.findall(EMAIL_REGEX, text)
                                        for email in emails:
                                            email_lower = email.lower()
                                            if not email_lower.endswith("@example.com"):
                                                result["Email"] = email_lower
                                                break

                                        phones = re.findall(PHONE_REGEX, text)
                                        if phones:
                                            result["Phone Number"] = phones[0].strip()

                                        results.append(result)
                                        new_count += 1
                                        logger.info(f"  + Profile: {href[:50]}")
                        else:
                            emails = re.findall(EMAIL_REGEX, text)
                            for email in emails:
                                email_lower = email.lower()
                                if (
                                    email_lower not in seen_emails
                                    and not email_lower.endswith("@example.com")
                                ):
                                    seen_emails.add(email_lower)

                                    result = {
                                        "Business Name": "",
                                        "Phone Number": "",
                                        "Website": "",
                                        "Email": email,
                                        "Source": "Bing Search",
                                    }

                                    try:
                                        link = await block.query_selector("a")
                                        if link:
                                            href = await link.get_attribute("href")
                                            if href and href.startswith("http"):
                                                result["Website"] = href
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract website from result"
                                        )

                                    try:
                                        title = await block.query_selector("h2")
                                        if title:
                                            result["Business Name"] = (
                                                await title.inner_text()
                                            ).strip()[:100]
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract title from result"
                                        )

                                    phone_match = re.search(PHONE_REGEX, text)
                                    if phone_match:
                                        result["Phone Number"] = phone_match.group(
                                            1
                                        ).strip()

                                    results.append(result)
                                    new_count += 1
                                    logger.info(f"  + {email[:40]}")

                    except Exception:
                        logger.debug("Failed to process result block")

                logger.info(f" | New: {new_count} | Total: {len(results)}")

            except Exception:
                logger.debug("Failed to find result blocks")

            next_clicked = False
            if scroll_count < max_scrolls - 1:
                next_button = (
                    await page.query_selector("a.sb_pagNext")
                    or await page.query_selector("a[aria-label='Next page']")
                    or await page.query_selector("a[title='Next page']")
                )
                if next_button:
                    try:
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        next_clicked = True
                        page_num += 1
                        logger.info(f"Moved to page {page_num}")
                    except Exception:
                        logger.debug(
                            "Failed to click next button, trying URL navigation"
                        )
                        try:
                            current_url = page.url
                            if "first=" in current_url:
                                new_url = re.sub(
                                    r"first=\d+",
                                    f"first={page_num * 10 + 1}",
                                    current_url,
                                )
                            else:
                                new_url = f"{current_url}&first={page_num * 10 + 1}"
                            await page.goto(
                                new_url, wait_until="networkidle", timeout=60000
                            )
                            page_num += 1
                            next_clicked = True
                            logger.info(f"Moved to page {page_num} via URL")
                        except Exception as e:
                            logger.debug(f"URL navigation also failed: {e}")
                else:
                    logger.debug("Next button not found with any selector")
                    try:
                        current_url = page.url
                        if "first=" in current_url:
                            new_url = re.sub(
                                r"first=\d+", f"first={page_num * 10 + 1}", current_url
                            )
                        else:
                            new_url = f"{current_url}&first={page_num * 10 + 1}"
                        await page.goto(
                            new_url, wait_until="networkidle", timeout=60000
                        )
                        page_num += 1
                        next_clicked = True
                        logger.info(f"Moved to page {page_num} via URL")
                    except Exception as e:
                        logger.debug(f"URL navigation failed: {e}")

            scroll_count += 1

            if len(results) >= SEARCH_CONFIG["results_limit"]:
                logger.info(f"Reached results limit: {SEARCH_CONFIG['results_limit']}")
                break

            if not next_clicked and scroll_count >= max_scrolls:
                logger.info("No more pages available")
                break

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_google_dork(
    keywords: str,
    dork_query: str,
    max_scrolls: int = 15,
    headless: bool = False,
    target: str = "email",
) -> list[dict[str, str]]:
    """Scrape using Google Dorking - searches for emails/contacts via Google."""
    results: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    seen_profiles: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} {dork_query}".strip()
        logger.info(f"Searching Google: {search_query}")

        try:
            await page.goto(
                f"https://www.google.com/search?q={search_query.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Search results loaded")
        except Exception as e:
            logger.warning(f"Load issue: {e}")
            await page.wait_for_timeout(10000)

        await asyncio.sleep(3)

        try:
            captcha = await page.query_selector("form#captcha-form")
            if captcha:
                logger.warning(
                    "Google CAPTCHA detected! Try using headed mode or another search engine."
                )
        except Exception:
            pass

        logger.info(f"Scraping results (max: {max_scrolls} scrolls)")

        scroll_count = 0
        page_num = 1

        while scroll_count < max_scrolls:
            logger.info(f"[PAGE {page_num}/{max_scrolls}] Processing results...")

            await human_like_scroll(page)
            await asyncio.sleep(2)

            try:
                result_blocks = await page.query_selector_all("div.g")
                new_count = 0

                for block in result_blocks:
                    try:
                        text = await block.inner_text()

                        if target == "profile":
                            link = await block.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if is_valid_profile_url(href):
                                    profile_key = href
                                    if profile_key not in seen_profiles:
                                        seen_profiles.add(profile_key)
                                        result = {
                                            "Business Name": "",
                                            "Phone Number": "",
                                            "Website": "",
                                            "Email": "",
                                            "Source": "Google Search",
                                        }
                                        result["Website"] = href
                                        try:
                                            title = await block.query_selector("h3")
                                            if title:
                                                result["Business Name"] = (
                                                    await title.inner_text()
                                                ).strip()[:100]
                                            else:
                                                result["Business Name"] = href
                                        except Exception:
                                            logger.debug(
                                                "Failed to extract title from result"
                                            )
                                            result["Business Name"] = href

                                        emails = re.findall(EMAIL_REGEX, text)
                                        for email in emails:
                                            email_lower = email.lower()
                                            if not email_lower.endswith("@example.com"):
                                                result["Email"] = email_lower
                                                break

                                        phones = re.findall(PHONE_REGEX, text)
                                        if phones:
                                            result["Phone Number"] = phones[0].strip()

                                        results.append(result)
                                        new_count += 1
                                        logger.info(f"  + Profile: {href[:50]}")
                        else:
                            emails = re.findall(EMAIL_REGEX, text)
                            for email in emails:
                                email_lower = email.lower()
                                if (
                                    email_lower not in seen_emails
                                    and not email_lower.endswith("@example.com")
                                ):
                                    seen_emails.add(email_lower)

                                    result = {
                                        "Business Name": "",
                                        "Phone Number": "",
                                        "Website": "",
                                        "Email": email,
                                        "Source": "Google Search",
                                    }

                                    try:
                                        link = await block.query_selector("a")
                                        if link:
                                            href = await link.get_attribute("href")
                                            if href and href.startswith("http"):
                                                result["Website"] = href
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract website from result"
                                        )

                                    try:
                                        title = await block.query_selector("h3")
                                        if title:
                                            result["Business Name"] = (
                                                await title.inner_text()
                                            ).strip()[:100]
                                    except Exception:
                                        logger.debug(
                                            "Failed to extract title from result"
                                        )

                                    phone_match = re.search(PHONE_REGEX, text)
                                    if phone_match:
                                        result["Phone Number"] = phone_match.group(
                                            1
                                        ).strip()

                                    results.append(result)
                                    new_count += 1
                                    logger.info(f"  + {email[:40]}")

                    except Exception:
                        logger.debug("Failed to process result block")

                logger.info(f" | New: {new_count} | Total: {len(results)}")

            except Exception:
                logger.debug("Failed to find result blocks")

            next_clicked = False
            if scroll_count < max_scrolls - 1:
                next_button = (
                    await page.query_selector("a#pnnext")
                    or await page.query_selector("td.d6ravFHbMDH__button")
                    or await page.query_selector("button[aria-label='Next page']")
                    or await page.query_selector("a[aria-label='Next page']")
                )
                if next_button:
                    try:
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        next_clicked = True
                        page_num += 1
                        logger.info(f"Moved to page {page_num}")
                    except Exception:
                        logger.debug(
                            "Failed to click next button, trying URL navigation"
                        )
                        try:
                            current_url = page.url
                            if "start=" in current_url:
                                new_url = re.sub(
                                    r"start=\d+", f"start={page_num * 10}", current_url
                                )
                            else:
                                new_url = f"{current_url}&start={page_num * 10}"
                            await page.goto(
                                new_url, wait_until="networkidle", timeout=60000
                            )
                            page_num += 1
                            next_clicked = True
                            logger.info(f"Moved to page {page_num} via URL")
                        except Exception as e:
                            logger.debug(f"URL navigation also failed: {e}")
                else:
                    logger.debug("Next button not found with any selector")
                    try:
                        current_url = page.url
                        if "start=" in current_url:
                            new_url = re.sub(
                                r"start=\d+", f"start={page_num * 10}", current_url
                            )
                        else:
                            new_url = f"{current_url}&start={page_num * 10}"
                        await page.goto(
                            new_url, wait_until="networkidle", timeout=60000
                        )
                        page_num += 1
                        next_clicked = True
                        logger.info(f"Moved to page {page_num} via URL")
                    except Exception as e:
                        logger.debug(f"URL navigation failed: {e}")

            scroll_count += 1

            if len(results) >= SEARCH_CONFIG["results_limit"]:
                logger.info(f"Reached results limit: {SEARCH_CONFIG['results_limit']}")
                break

            if not next_clicked and scroll_count >= max_scrolls:
                logger.info("No more pages available")
                break

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_duckduckgo_dork(
    keywords: str,
    dork_query: str,
    max_scrolls: int = 15,
    headless: bool = False,
    target: str = "email",
) -> list[dict[str, str]]:
    """Scrape using DuckDuckGo - less blocking than Google."""
    results: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    seen_profiles: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} {dork_query}".strip()
        logger.info(f"Searching DuckDuckGo: {search_query}")

        try:
            await page.goto(
                f"https://duckduckgo.com/?q={search_query.replace(' ', '+')}&ia=web",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Search results loaded")
        except Exception as e:
            logger.warning(f"Load issue: {e}")
            await page.wait_for_timeout(10000)

        await asyncio.sleep(random.uniform(2, 4))
        logger.info(f"Scraping results (max: {max_scrolls} scrolls)")

        scroll_count = 0
        page_num = 1

        while scroll_count < max_scrolls:
            logger.info(f"[PAGE {page_num}/{max_scrolls}] Processing results...")

            await human_like_scroll(page)
            await asyncio.sleep(random.uniform(1, 3))

            try:
                result_blocks = await page.query_selector_all("div.result, li.result")
                new_count = 0

                for block in result_blocks:
                    try:
                        text = await block.inner_text()

                        if target == "profile":
                            link = await block.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if is_valid_profile_url(href):
                                    profile_key = href
                                    if profile_key not in seen_profiles:
                                        seen_profiles.add(profile_key)
                                        result = {
                                            "Business Name": "",
                                            "Phone Number": "",
                                            "Website": "",
                                            "Email": "",
                                            "Source": "DuckDuckGo Search",
                                        }
                                        result["Website"] = href
                                        try:
                                            title = await block.query_selector("h2")
                                            if title:
                                                result["Business Name"] = (
                                                    await title.inner_text()
                                                ).strip()[:100]
                                            else:
                                                result["Business Name"] = href
                                        except Exception:
                                            result["Business Name"] = href

                                        emails = re.findall(EMAIL_REGEX, text)
                                        for email in emails:
                                            email_lower = email.lower()
                                            if not email_lower.endswith("@example.com"):
                                                result["Email"] = email_lower
                                                break

                                        phones = re.findall(PHONE_REGEX, text)
                                        if phones:
                                            result["Phone Number"] = phones[0].strip()

                                        results.append(result)
                                        new_count += 1
                                        logger.info(f"  + Profile: {href[:50]}")
                        else:
                            emails = re.findall(EMAIL_REGEX, text)
                            for email in emails:
                                email_lower = email.lower()
                                if (
                                    email_lower not in seen_emails
                                    and not email_lower.endswith("@example.com")
                                ):
                                    seen_emails.add(email_lower)
                                    result = {
                                        "Business Name": "",
                                        "Phone Number": "",
                                        "Website": "",
                                        "Email": email,
                                        "Source": "DuckDuckGo Search",
                                    }
                                    try:
                                        link = await block.query_selector("a")
                                        if link:
                                            href = await link.get_attribute("href")
                                            if href and href.startswith("http"):
                                                result["Website"] = href
                                    except Exception:
                                        pass
                                    try:
                                        title = await block.query_selector("h2")
                                        if title:
                                            result["Business Name"] = (
                                                await title.inner_text()
                                            ).strip()[:100]
                                    except Exception:
                                        pass
                                    results.append(result)
                                    new_count += 1
                                    logger.info(f"  + {email[:40]}")

                    except Exception:
                        logger.debug("Failed to process result block")

                logger.info(f" | New: {new_count} | Total: {len(results)}")

            except Exception:
                logger.debug("Failed to find result blocks")

            next_clicked = False
            if scroll_count < max_scrolls - 1:
                next_button = (
                    await page.query_selector("a.result__a[href*='uddg']")
                    or await page.query_selector("a[aria-label='Next']")
                    or await page.query_selector("button[aria-label='Next Page']")
                )
                if next_button:
                    try:
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        next_clicked = True
                        page_num += 1
                        logger.info(f"Moved to page {page_num}")
                    except Exception:
                        logger.debug("Failed to click next button")
                else:
                    try:
                        current_url = page.url
                        if "s=" in current_url:
                            match = re.search(r"s=(\d+)", current_url)
                            if match:
                                new_s = int(match.group(1)) + 20
                                new_url = re.sub(r"s=\d+", f"s={new_s}", current_url)
                            else:
                                new_url = f"{current_url}&s=20"
                        else:
                            new_url = f"{current_url}&s=20"
                        await page.goto(
                            new_url, wait_until="networkidle", timeout=60000
                        )
                        page_num += 1
                        next_clicked = True
                        logger.info(f"Moved to page {page_num} via URL")
                    except Exception as e:
                        logger.debug(f"URL navigation failed: {e}")

            scroll_count += 1

            if len(results) >= SEARCH_CONFIG["results_limit"]:
                logger.info(f"Reached results limit: {SEARCH_CONFIG['results_limit']}")
                break

            if not next_clicked and scroll_count >= max_scrolls:
                logger.info("No more pages available")
                break

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_yandex_dork(
    keywords: str,
    dork_query: str,
    max_scrolls: int = 15,
    headless: bool = False,
    target: str = "email",
) -> list[dict[str, str]]:
    """Scrape using Yandex - good for Bangladesh region."""
    results: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    seen_profiles: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    try:
        search_query = f"{keywords} {dork_query}".strip()
        logger.info(f"Searching Yandex: {search_query}")

        try:
            await page.goto(
                f"https://yandex.com/search/?text={search_query.replace(' ', '+')}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            logger.info("Search results loaded")
        except Exception as e:
            logger.warning(f"Load issue: {e}")
            await page.wait_for_timeout(10000)

        await asyncio.sleep(random.uniform(3, 5))

        captcha = await page.query_selector(
            "form#captcha-form, input[name='keystroke'], div.captcha"
        )
        if captcha:
            logger.warning("Yandex CAPTCHA detected! Try DuckDuckGo instead.")

        logger.info(f"Scraping results (max: {max_scrolls} scrolls)")

        scroll_count = 0
        page_num = 1

        while scroll_count < max_scrolls:
            logger.info(f"[PAGE {page_num}/{max_scrolls}] Processing results...")

            await asyncio.sleep(random.uniform(1, 2))

            try:
                result_blocks = await page.query_selector_all(
                    "li.serp-item, div.organic, div serp__item, article"
                )
                new_count = 0

                for block in result_blocks:
                    try:
                        try:
                            text = await block.inner_text()
                        except Exception:
                            continue

                        if target == "profile":
                            link = await block.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if is_valid_profile_url(href):
                                    profile_key = href
                                    if profile_key not in seen_profiles:
                                        seen_profiles.add(profile_key)
                                        result = {
                                            "Business Name": "",
                                            "Phone Number": "",
                                            "Website": "",
                                            "Email": "",
                                            "Source": "Yandex Search",
                                        }
                                        result["Website"] = href
                                        try:
                                            title = await block.query_selector("h2")
                                            if title:
                                                result["Business Name"] = (
                                                    await title.inner_text()
                                                ).strip()[:100]
                                            else:
                                                result["Business Name"] = href
                                        except Exception:
                                            result["Business Name"] = href

                                        emails = re.findall(EMAIL_REGEX, text)
                                        for email in emails:
                                            email_lower = email.lower()
                                            if not email_lower.endswith("@example.com"):
                                                result["Email"] = email_lower
                                                break

                                        phones = re.findall(PHONE_REGEX, text)
                                        if phones:
                                            result["Phone Number"] = phones[0].strip()

                                        results.append(result)
                                        new_count += 1
                                        logger.info(f"  + Profile: {href[:50]}")
                        else:
                            emails = re.findall(EMAIL_REGEX, text)
                            for email in emails:
                                email_lower = email.lower()
                                if (
                                    email_lower not in seen_emails
                                    and not email_lower.endswith("@example.com")
                                ):
                                    seen_emails.add(email_lower)
                                    result = {
                                        "Business Name": "",
                                        "Phone Number": "",
                                        "Website": "",
                                        "Email": email,
                                        "Source": "Yandex Search",
                                    }
                                    try:
                                        link = await block.query_selector("a")
                                        if link:
                                            href = await link.get_attribute("href")
                                            if href and href.startswith("http"):
                                                result["Website"] = href
                                    except Exception:
                                        pass
                                    try:
                                        title = await block.query_selector("h2")
                                        if title:
                                            result["Business Name"] = (
                                                await title.inner_text()
                                            ).strip()[:100]
                                    except Exception:
                                        pass
                                    results.append(result)
                                    new_count += 1
                                    logger.info(f"  + {email[:40]}")

                    except Exception:
                        logger.debug("Failed to process result block")

                logger.info(f" | New: {new_count} | Total: {len(results)}")

            except Exception:
                logger.debug("Failed to find result blocks")

            next_clicked = False
            if scroll_count < max_scrolls - 1:
                next_button = (
                    await page.query_selector("a.pager__next")
                    or await page.query_selector("a[aria-label='next']")
                    or await page.query_selector("div.pager a:last-child")
                )
                if next_button:
                    try:
                        await next_button.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        next_clicked = True
                        page_num += 1
                        logger.info(f"Moved to page {page_num}")
                    except Exception:
                        logger.debug("Failed to click next button")
                else:
                    try:
                        current_url = page.url
                        if "p=" in current_url:
                            match = re.search(r"p=(\d+)", current_url)
                            if match:
                                new_p = int(match.group(1)) + 1
                                new_url = re.sub(r"p=\d+", f"p={new_p}", current_url)
                            else:
                                new_url = f"{current_url}&p=1"
                        else:
                            new_url = f"{current_url}&p=1"
                        await page.goto(
                            new_url, wait_until="networkidle", timeout=60000
                        )
                        page_num += 1
                        next_clicked = True
                        logger.info(f"Moved to page {page_num} via URL")
                    except Exception as e:
                        logger.debug(f"URL navigation failed: {e}")

            scroll_count += 1

            if len(results) >= SEARCH_CONFIG["results_limit"]:
                logger.info(f"Reached results limit: {SEARCH_CONFIG['results_limit']}")
                break

            if not next_clicked and scroll_count >= max_scrolls:
                logger.info("No more pages available")
                break

        logger.info(f"Scraping complete! Total results: {len(results)}")

    finally:
        await browser.close()
        await p.stop()

    return results


async def scrape_bangladesh_directories(
    keywords: str,
    max_scrolls: int = 15,
    headless: bool = False,
) -> list[dict[str, str]]:
    """Scrape Bangladesh local business directories."""
    results: list[dict[str, str]] = []
    seen_businesses: set[str] = set()

    p, browser, page = await _initialize_browser(headless=headless, use_stealth=False)
    logger.info(f"Browser initialized (headless={headless})")

    directories = [
        (
            "bikroy",
            f"https://bikroy.com/en/ads/{keywords.replace(' ', '-')}/?query={keywords.replace(' ', '+')}",
        ),
        (
            "clicktechi",
            f"https://www.clicktechi.com/search?search={keywords.replace(' ', '+')}",
        ),
    ]

    for dir_name, base_url in directories:
        logger.info(f"Scraping {dir_name}...")

        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(2, 4))

            scroll_count = 0
            while scroll_count < max_scrolls // 3:
                logger.info(
                    f"[{dir_name} SCROLL {scroll_count + 1}] Finding listings..."
                )

                await human_like_scroll(page)
                await asyncio.sleep(random.uniform(1, 2))

                try:
                    if dir_name == "bikroy":
                        listings = await page.query_selector_all(
                            "div.listing-item, a.listing-link"
                        )
                    else:
                        listings = await page.query_selector_all(
                            "div.business-card, div.listing-item"
                        )

                    for listing in listings:
                        try:
                            if dir_name == "bikroy":
                                name_elem = await listing.query_selector("h2, .title")
                            else:
                                name_elem = await listing.query_selector(
                                    "h3, .business-name, .title"
                                )

                            if name_elem:
                                business_name = (await name_elem.inner_text()).strip()[
                                    :100
                                ]
                            else:
                                business_name = ""

                            link = await listing.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if href and not href.startswith("http"):
                                    href = f"https://{dir_name}.com{href}"
                            else:
                                href = ""

                            if business_name:
                                business_key = business_name.lower()
                                if business_key not in seen_businesses:
                                    seen_businesses.add(business_key)
                                    result = {
                                        "Business Name": business_name,
                                        "Phone Number": "",
                                        "Website": href or "",
                                        "Email": "",
                                        "Source": f"{dir_name.capitalize()} BD",
                                    }

                                    listing_text = await listing.inner_text()
                                    emails = re.findall(EMAIL_REGEX, listing_text)
                                    if emails:
                                        result["Email"] = emails[0].lower()

                                    phones = re.findall(PHONE_REGEX, listing_text)
                                    if phones:
                                        result["Phone Number"] = phones[0].strip()

                                    results.append(result)
                                    logger.info(f"  + {business_name[:40]}")

                        except Exception:
                            logger.debug(f"Failed to process {dir_name} listing")

                except Exception:
                    logger.debug(f"Failed to find listings on {dir_name}")

                scroll_count += 1

                if len(results) >= SEARCH_CONFIG["results_limit"]:
                    break

            logger.info(f"Finished {dir_name}, total: {len(results)}")

        except Exception as e:
            logger.warning(f"Failed to scrape {dir_name}: {e}")
            continue

    logger.info(f"Scraping complete! Total results: {len(results)}")

    await browser.close()
    await p.stop()

    return results


def process_and_clean_data(raw_data: list[dict[str, Any]]) -> pd.DataFrame:
    """Process and clean scraped data."""
    if not raw_data:
        return pd.DataFrame(
            columns=["Business Name", "Phone Number", "Website", "Address", "Email"]
        )

    df = pd.DataFrame(raw_data)

    # Ensure all expected columns exist
    required_cols = ["Business Name", "Phone Number", "Website", "Address", "Email"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    if (
        "Email" in df.columns
        and df["Email"].notna().any()
        and (df["Email"] != "").any()
    ):
        df = df.drop_duplicates(subset=["Email"], keep="first")
    else:
        df = df.drop_duplicates(subset=["Website"], keep="first")

    df["has_contact"] = (
        (df["Phone Number"].fillna("").str.len() > 0)
        | (df["Website"].fillna("").str.len() > 0)
        | (df["Email"].fillna("").str.len() > 0)
    )

    df = df[df["has_contact"]].drop(columns=["has_contact"])

    def validate_phone(phone: Any) -> str:
        if pd.isna(phone) or phone == "":
            return str(phone)
        cleaned = re.sub(r"[^\d\+]", "", str(phone))
        if 10 <= len(cleaned) <= 15:
            return str(phone)
        return ""

    df["Phone Number"] = df["Phone Number"].apply(validate_phone)  # type: ignore[union-attr]
    business_names = df["Business Name"].fillna("")  # type: ignore[union-attr]
    df = df[business_names.str.len() > 0]

    return df  # type: ignore[return-value]


def parse_search_prompt(search_prompt: str) -> dict[str, str]:
    """Parse user search prompt to determine search type and parameters."""
    config = {
        "search_type": "maps",
        "keywords": "",
        "location": "",
        "target": "email",
    }

    email_indicators = [
        "@gmail.com",
        "@yahoo.com",
        "@hotmail.com",
        "@outlook.com",
        "contact@",
        "site:",
    ]

    social_indicators = [
        "facebook.com",
        "instagram.com",
        "fb.com",
        "fb.me",
    ]

    prompt_lower = search_prompt.lower()

    if any(indicator in prompt_lower for indicator in social_indicators):
        config["search_type"] = "dork"
        config["keywords"] = search_prompt
        config["target"] = "profile"
    elif any(indicator in prompt_lower for indicator in email_indicators):
        config["search_type"] = "dork"
        config["keywords"] = search_prompt
        config["target"] = "email"
    else:
        config["search_type"] = "maps"
        if " in " in prompt_lower:
            parts = search_prompt.split(" in ", 1)
            config["keywords"] = parts[0].strip()
            config["location"] = parts[1].strip()
        elif " near " in prompt_lower:
            parts = search_prompt.split(" near ", 1)
            config["keywords"] = parts[0].strip()
            config["location"] = parts[1].strip()
        else:
            config["keywords"] = search_prompt
            config["location"] = os.getenv("DEFAULT_LOCATION", "New York")

    return config


async def main() -> None:
    """Main entry point for the lead scraper."""
    print("=" * 60)
    print("              LEAD SCRAPING AGENT")
    print("=" * 60)

    print("\n[SELECT SEARCH ENGINE]")
    print("  1. Google Maps   - Find businesses by location")
    print("  2. Google Dork   - Search for emails/contacts (may get CAPTCHA)")
    print("  3. Yahoo Dork    - Search for emails/contacts")
    print("  4. Bing Dork     - Search for emails/contacts")
    print("  5. DuckDuckGo   - Search for emails/contacts (less blocking)")
    print("  6. Yandex       - Search for emails/contacts (good for BD)")
    print("  7. Bangladesh   - Local directories (bikroy, clicktechi)")

    engine_choice = input("\nEnter choice (1/2/3/4/5/6/7): ").strip()

    engine_map = {
        "1": ("google_maps", "Google Maps"),
        "2": ("google_dork", "Google Dork"),
        "3": ("yahoo_dork", "Yahoo Dork"),
        "4": ("bing_dork", "Bing Dork"),
        "5": ("duckduckgo_dork", "DuckDuckGo Dork"),
        "6": ("yandex_dork", "Yandex Dork"),
        "7": ("bangladesh_dork", "Bangladesh Directory"),
    }

    if engine_choice not in engine_map:
        print("[ERROR] Invalid choice.")
        return

    SEARCH_CONFIG["search_type"], engine_name = engine_map[engine_choice]

    print(f"\n[SELECTED] {engine_name}")

    if SEARCH_CONFIG["search_type"] == "google_maps":
        print("\n[ENTER SEARCH PROMPT]")
        print("Examples:")
        print("  - 'restaurants in New York'")
        print("  - 'plumbers near Brooklyn'")
        print("  - 'coffee shops Los Angeles'")

        search_prompt = input("\nEnter search prompt: ").strip()

        if not search_prompt:
            print("[ERROR] No search prompt entered.")
            return

        if " in " in search_prompt.lower():
            parts = search_prompt.split(" in ", 1)
            SEARCH_CONFIG["keywords"] = parts[0].strip()
            SEARCH_CONFIG["location"] = parts[1].strip()
        elif " near " in search_prompt.lower():
            parts = search_prompt.split(" near ", 1)
            SEARCH_CONFIG["keywords"] = parts[0].strip()
            SEARCH_CONFIG["location"] = parts[1].strip()
        else:
            SEARCH_CONFIG["keywords"] = search_prompt
            SEARCH_CONFIG["location"] = os.getenv("DEFAULT_LOCATION", "New York")

    else:
        print("\n[ENTER SEARCH PROMPT]")
        print("Examples:")
        print("  - 'real estate @gmail.com'")
        print("  - 'plumbers @yahoo.com Los Angeles'")
        print("  - 'hotels contact@*.com'")
        print("  - 'influencers facebook.com'")
        print("  - 'creators instagram.com'")

        search_prompt = input("\nEnter search prompt: ").strip()

        if not search_prompt:
            print("[ERROR] No search prompt entered.")
            return

        parsed = parse_search_prompt(search_prompt)
        SEARCH_CONFIG["keywords"] = parsed["keywords"]
        SEARCH_CONFIG["target"] = parsed["target"]

    print("\n[HEADLESS MODE]")
    print("  y - Run in headless mode (faster, more likely blocked)")
    print("  n - Run with visible browser (slower, harder to detect)")

    headless_input = input(f"\nHeadless? (y/n, default n): ").strip().lower()
    headless_mode = headless_input == "y"

    if headless_input != "y" and headless_input != "n":
        headless_mode = False

    try:
        SEARCH_CONFIG["max_scrolls"] = int(
            input(f"\nMax scrolls/pages (default 15): ").strip() or "15"
        )
        SEARCH_CONFIG["results_limit"] = int(
            input("Results limit (default 100): ").strip() or "100"
        )
    except ValueError:
        logger.warning("Invalid numeric input, using defaults")

    print("\n" + "=" * 60)
    print(f"  Search Engine: {engine_name}")
    print(f"  Keywords:      {SEARCH_CONFIG['keywords']}")
    if SEARCH_CONFIG["search_type"] == "google_maps":
        print(f"  Location:      {SEARCH_CONFIG['location']}")
    else:
        target_type = SEARCH_CONFIG.get("target", "email")
        target_name = "Social Profiles" if target_type == "profile" else "Emails"
        print(f"  Target:        {target_name}")
    print(f"  Headless:      {'Yes' if headless_mode else 'No'}")
    print(f"  Max Scrolls:   {SEARCH_CONFIG['max_scrolls']}")
    print(f"  Results Limit: {SEARCH_CONFIG['results_limit']}")
    print("=" * 60 + "\n")

    logger.info("Initializing browser...")

    raw_results: list[dict[str, str]] = []
    try:
        if SEARCH_CONFIG["search_type"] == "google_maps":
            raw_results = await scrape_google_maps(
                keywords=SEARCH_CONFIG["keywords"],
                location=SEARCH_CONFIG["location"],
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                results_limit=SEARCH_CONFIG["results_limit"],
                headless=headless_mode,
            )
        elif SEARCH_CONFIG["search_type"] == "yahoo_dork":
            raw_results = await scrape_yahoo_dork(
                keywords=SEARCH_CONFIG["keywords"],
                dork_query="",
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
                target=SEARCH_CONFIG.get("target", "email"),
            )
        elif SEARCH_CONFIG["search_type"] == "google_dork":
            raw_results = await scrape_google_dork(
                keywords=SEARCH_CONFIG["keywords"],
                dork_query="",
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
                target=SEARCH_CONFIG.get("target", "email"),
            )
        elif SEARCH_CONFIG["search_type"] == "bing_dork":
            raw_results = await scrape_bing_dork(
                keywords=SEARCH_CONFIG["keywords"],
                dork_query="",
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
                target=SEARCH_CONFIG.get("target", "email"),
            )
        elif SEARCH_CONFIG["search_type"] == "duckduckgo_dork":
            raw_results = await scrape_duckduckgo_dork(
                keywords=SEARCH_CONFIG["keywords"],
                dork_query="",
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
                target=SEARCH_CONFIG.get("target", "email"),
            )
        elif SEARCH_CONFIG["search_type"] == "yandex_dork":
            raw_results = await scrape_yandex_dork(
                keywords=SEARCH_CONFIG["keywords"],
                dork_query="",
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
                target=SEARCH_CONFIG.get("target", "email"),
            )
        elif SEARCH_CONFIG["search_type"] == "bangladesh_dork":
            raw_results = await scrape_bangladesh_directories(
                keywords=SEARCH_CONFIG["keywords"],
                max_scrolls=SEARCH_CONFIG["max_scrolls"],
                headless=headless_mode,
            )
    except KeyboardInterrupt:
        print("\n[!] Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Error during scraping: {e}")

    logger.info(f"Scraping finished! Total raw results: {len(raw_results)}")

    if not raw_results:
        logger.warning("No results found. Check your search parameters.")
        return

    df = process_and_clean_data(raw_results)
    logger.info(f"After processing: {len(df)} valid leads")

    output_file = "leads_output.xlsx"
    df.to_excel(output_file, index=False, engine="openpyxl")

    logger.info(f"Results exported to {output_file}")
    print("=" * 60)
    print("\nSample results:")
    print(df.head(10).to_string())


if __name__ == "__main__":
    asyncio.run(main())
