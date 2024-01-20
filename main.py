import html
import logging
from datetime import datetime
import locale

import requests
from fastapi import FastAPI, Response
from fastapi_utils.tasks import repeat_every
from bs4 import BeautifulSoup

app = FastAPI()
rss: str or None = None

locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

WUPPERTAL_LIVE_BASE_URL = "https://www.wuppertal-live.de"
WUPPERTAL_LIVE_FILTER_URL = f"{WUPPERTAL_LIVE_BASE_URL}/events/mode=utf8;client=;what=rubrik;show=21;shop=0;cal=wuppertal"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class XMLResponse(Response):
    media_type = "application/rss+xml"


@app.get("/rss.xml", response_class=XMLResponse)
async def rss():
    global rss

    return rss


@app.get("/api/v1/status")
async def status():
    return {"status": f"ok"}


def convert_events_to_xml_items(events: list) -> str:
    return "".join(
        [
            f"""
        <item>
            <guid>https://www.wuppertal-live.de/{event["id"]}</guid>
            <title>{html.escape(event["title"])}</title>
            <link>https://www.wuppertal-live.de/{event["id"]}</link>
            <description>
                <![CDATA[
                    <img src="{event["foto"]}" />
                    <p>{event["date"].strftime("%A, %d. %B %Y")}</p>
                    <p>{event["start"]} - {event["end"]}</p>
                    <p>{event["location"]}</p>
                ]]>
            </description>
            <pubDate>{event["date"].strftime("%a, %d %b %Y %H:%M:%S %z")}</pubDate>
        </item>
        """
            for event in events
        ]
    )


@app.on_event("startup")
@repeat_every(seconds=3600, wait_first=False, logger=logger)
async def refresh_rss():
    global rss

    logger.info("Refreshing RSS")

    # Download html from wuppertal-live.de
    response = requests.get(WUPPERTAL_LIVE_FILTER_URL)
    if not response.ok:
        logger.error(
            f"Error downloading {WUPPERTAL_LIVE_FILTER_URL}: {response.text} ({response.status_code})"
        )
        return

    soup = BeautifulSoup(response.text, "html.parser")

    year = None
    events = []

    for child in soup.children:
        # Skip non div tags
        if (
            child.name != "div"
            or not child.has_attr("id")
            or not child["id"].startswith("event")
        ):
            continue

        event_id = int(child["id"].replace("event", "").strip())

        # At the beginning of each new month, the year is displayed
        # Format is e.g. "Januar 2024"
        year_wrapper = child.find(class_="zeitraum")
        if year_wrapper:
            year = int(year_wrapper.text.split(" ")[1].strip())

        datum_wrapper = child.find(class_="datum-veranstaltungen")
        if not datum_wrapper:
            continue

        month = datum_wrapper.find(class_="monat").text.strip()
        day = datum_wrapper.find(class_="tag").text.replace(".", "").strip()
        try:
            date = datetime.strptime(f"{year}-{month}-{day}", "%Y-%B-%d").date()
        except ValueError:
            logger.error(f"Error parsing date {datum_wrapper.text.strip()}")
            continue

        foto = child.find("img", class_="lazy")
        if foto and foto.has_attr("data-src"):
            foto = f"{WUPPERTAL_LIVE_BASE_URL}{foto['data-src']}"
        else:
            foto = None

        uhrzeit_wrapper = child.find(class_="genre-uhrzeit")
        start = None
        end = None
        if uhrzeit_wrapper:
            start = uhrzeit_wrapper.find(class_="beginn").text.strip()
            end = uhrzeit_wrapper.find(class_="ende").text.split(" ")[1].strip()

        title = child.find("h1").text.strip()
        location = child.find(class_="location").text.strip()

        events.append(
            {
                "id": event_id,
                "title": title,
                "date": date,
                "start": start,
                "end": end,
                "location": location,
                "foto": foto,
            }
        )

    # Convert event list to RSS
    rss = f"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
        <channel>
            <title>Wuppertal Live</title>
            <link>https://www.wuppertal-live.de</link>
            <description>Wuppertal Live</description>
            <language>de-de</language>
            <lastBuildDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S")} GMT</lastBuildDate>
            <ttl>60</ttl>
            <atom:link href="https://wuppertal-live.thelfensdrfer.de/rss.xml" rel="self" type="application/rss+xml" />
            {convert_events_to_xml_items(events)}
        </channel>
    </rss>"""
