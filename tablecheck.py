"""
TableCheck availability scraper
Reads URL, PARTY_SIZE, START_DATE, END_DATE from environment variables.
Always runs headless.

Usage (standalone):
  export TABLECHECK_URL="https://www.tablecheck.com/en/shops/hatsunezushi/reserve"
  export PARTY_SIZE=2
  export START_DATE=2026-05-09
  export END_DATE=2026-05-21
  python tablecheck.py
"""

import asyncio
import json
import os
import re
import calendar
import sys
from datetime import date
from playwright.async_api import async_playwright

# ── Config from environment ────────────────────────────────────────
URL        = os.environ.get("TABLECHECK_URL", "")
PARTY_SIZE = int(os.environ.get("PARTY_SIZE", "2"))
START_DATE = date.fromisoformat(os.environ.get("START_DATE", "2026-05-09"))
END_DATE   = date.fromisoformat(os.environ.get("END_DATE", "2026-05-21"))

# Output file path (Jenkins reads this to decide whether to email)
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "results.json")


async def main():
    if not URL:
        print("ERROR: TABLECHECK_URL not set")
        sys.exit(1)

    print("=" * 55)
    print(f"TableCheck scraper | party {PARTY_SIZE}")
    print(f"Dates: {START_DATE} → {END_DATE}")
    print(f"URL:   {URL}")
    print("=" * 55)

    available = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=100)
        page = await browser.new_page(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # ── Load page ──────────────────────────────────────────────
        print(f"\nLoading {URL}...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1500)

        # ── Step 1: Accept venue message checkbox ──────────────────
        print("[1] Accepting venue message...")
        cb = page.locator("#reservation_confirm_shop_note")
        try:
            await cb.wait_for(state="visible", timeout=10000)
            await cb.check()
            print("    ✓ Checkbox checked")
        except Exception:
            print("    — No checkbox found, skipping")
        await page.wait_for_timeout(500)

        # ── Step 2: Select party size ──────────────────────────────
        print(f"[2] Setting party size to {PARTY_SIZE}...")
        party_select = page.locator("#reservation_num_people_adult")
        await party_select.select_option(str(PARTY_SIZE))
        print(f"    ✓ Party size = {PARTY_SIZE}")
        await page.wait_for_timeout(2000)

        # ── Step 3: Navigate timetable week-by-week ────────────────
        print("[3] Scanning timetable...")

        try:
            await page.locator("#timetable-body").wait_for(
                state="attached", timeout=8000
            )
            print("    ✓ Timetable body found")
        except Exception:
            print("    ! Timetable body not found, continuing anyway...")

        next_week_btn = page.locator("th.time-right a.next-week").first
        max_weeks = 16

        for week_num in range(max_weeks):
            week_data = await parse_timetable_week(page)
            if not week_data:
                print(f"    week {week_num + 1}: empty, advancing...")
                await next_week_btn.click()
                await page.wait_for_timeout(1200)
                continue

            week_dates = list(week_data.keys())
            week_start = min(week_dates)
            week_end = max(week_dates)

            if week_end < START_DATE:
                await next_week_btn.click()
                await page.wait_for_timeout(1200)
                continue

            if week_start > END_DATE:
                break

            for d in sorted(week_data):
                if not (START_DATE <= d <= END_DATE):
                    continue
                slots = week_data[d]
                if slots:
                    available[d] = slots
                    print(
                        f"  ✓ {d.strftime('%Y-%m-%d %A')}: "
                        f"{', '.join(slots)}"
                    )
                else:
                    print(f"  — {d.strftime('%Y-%m-%d %A')}: no slots")

            if week_end >= END_DATE:
                break

            await next_week_btn.click()
            await page.wait_for_timeout(1200)

        await browser.close()

    # ── Write results to JSON ──────────────────────────────────────
    output = {
        "url": URL,
        "party_size": PARTY_SIZE,
        "start_date": str(START_DATE),
        "end_date": str(END_DATE),
        "available": {
            d.strftime("%Y-%m-%d %A"): slots
            for d, slots in sorted(available.items())
        },
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("RESULTS")
    print("=" * 55)
    if available:
        print("\n*** AVAILABILITY FOUND ***\n")
        for d in sorted(available):
            print(f"  {d.strftime('%Y-%m-%d %A')}: {', '.join(available[d])}")
    else:
        print("\nNo availability found.")

    print(f"\nResults written to {OUTPUT_FILE}")

    # Exit code: 0 = slots found, 1 = no slots
    sys.exit(0 if available else 1)


def _parse_month_num(text: str) -> int:
    """Convert month text like 'May' or 'Jun' to month number."""
    text = text.strip()
    try:
        return list(calendar.month_abbr).index(text[:3].capitalize())
    except ValueError:
        pass
    try:
        return list(calendar.month_name).index(text.capitalize())
    except ValueError:
        return 0


async def parse_timetable_week(page) -> dict:
    """
    Read the timetable and return {date: [slot_texts]} for each day.
    Handles weeks spanning two months via colspan on <th class="month">.
    """
    result = {}
    try:
        # ── Per-column month mapping via colspan ───────────────────
        month_headers = page.locator("th.month")
        num_month_headers = await month_headers.count()
        if num_month_headers == 0:
            return {}

        col_months = []
        for mi in range(num_month_headers):
            th = month_headers.nth(mi)
            m_text = (await th.inner_text()).strip()
            m_num = _parse_month_num(m_text)
            if m_num == 0:
                continue
            colspan = int((await th.get_attribute("colspan")) or "1")
            col_months.extend([m_num] * colspan)

        # ── Day-header cells ───────────────────────────────────────
        day_cells = page.locator("#timetable-body td.wday")
        num_days = await day_cells.count()
        if num_days == 0:
            return {}

        # Infer year from START_DATE (handles Dec→Jan rollover)
        base_year = START_DATE.year

        col_dates = []
        col_closed = []
        for i in range(num_days):
            cell = day_cells.nth(i)
            cls = await cell.get_attribute("class") or ""
            closed = "day-closed" in cls

            date_div = cell.locator(".date-num")
            day_text = (
                (await date_div.inner_text()).strip()
                if await date_div.count()
                else ""
            )
            m = re.search(r"\d+", day_text)
            if m:
                month_for_col = (
                    col_months[i] if i < len(col_months) else 1
                )
                year = base_year
                # Handle year rollover (Dec → Jan)
                if i > 0 and i - 1 < len(col_months):
                    prev_month = col_months[i - 1]
                    if prev_month == 12 and month_for_col == 1:
                        year = base_year + 1
                try:
                    d = date(year, month_for_col, int(m.group()))
                    col_dates.append(d)
                    col_closed.append(closed)
                    result[d] = []
                    continue
                except ValueError:
                    pass

            col_dates.append(None)
            col_closed.append(True)

        # ── Time-slot rows ─────────────────────────────────────────
        time_rows = page.locator("tr.timetable-row")
        num_rows = await time_rows.count()

        for ri in range(num_rows):
            row = time_rows.nth(ri)

            time_th = row.locator("th.time").first
            time_text = (
                (await time_th.inner_text()).strip()
                if await time_th.count()
                else ""
            )

            data_cells = row.locator("td")
            num_cells = await data_cells.count()

            for ci in range(min(num_cells, num_days)):
                if col_closed[ci] or col_dates[ci] is None:
                    continue
                td = data_cells.nth(ci)
                td_cls = (
                    (await td.get_attribute("class") or "").lower()
                )
                # Exact class token match — avoids "not_available"
                if "available" not in td_cls.split():
                    continue
                d = col_dates[ci]
                if time_text:
                    result[d].append(time_text)

    except Exception as e:
        print(f"      [parse error: {e}]")

    return result


if __name__ == "__main__":
    asyncio.run(main())
