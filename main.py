import html
import logging
import os
import ssl
from datetime import datetime
import locale
import sqlite3
import smtplib
from email.message import EmailMessage

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
async def migrate():
    conn = sqlite3.connect("database/db.sqlite")
    sql_file_paths = ["migrations/001_initial.sql"]
    for sql_file_path in sql_file_paths:
        with open(sql_file_path, "r") as sql_file:
            sql = sql_file.read()
            conn.executescript(sql)
    conn.commit()
    conn.close()


@app.on_event("startup")
@repeat_every(seconds=3600, wait_first=False, logger=logger)
async def refresh_events():
    global rss

    logger.info("Refreshing events...")

    events = get_events()
    if not events:
        logger.error("Error getting events")
        return

    # Convert event list to RSS
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
        <channel>
            <title>Wuppertal Live</title>
            <link>https://www.wuppertal-live.de</link>
            <description>Wuppertal Live Kinderveranstaltungen</description>
            <language>de</language>
            <lastBuildDate>{datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S")} GMT</lastBuildDate>
            <ttl>60</ttl>
            <atom:link href="https://wuppertal-live.thelfensdrfer.de/rss.xml" rel="self" type="application/rss+xml" />
            {convert_events_to_xml_items(events)}
        </channel>
    </rss>"""

    # Save events in database
    save_to_db(events)


def notify_new_events(events: list[dict]) -> bool:
    """
    Email the configured receivers.

    :param events:
    :return:
    """
    if not events:
        logger.info("No new events")
        return True

    # Email configuration
    sender_email = os.environ.get("MAIL_SENDER")
    receiver_emails = os.environ.get("MAIL_RECEIVERS", "").split(",")
    smtp_server = os.environ.get("MAIL_SMTP_SERVER")
    smtp_port = os.environ.get("MAIL_SMTP_PORT")
    smtp_user = os.environ.get("MAIL_SMTP_USERNAME")
    smtp_password = os.environ.get("MAIL_SMTP_PASSWORD")

    if (
        not sender_email
        or not receiver_emails
        or not smtp_server
        or not smtp_port
        or not smtp_user
        or not smtp_password
    ):
        logger.error("Email configuration is not set")
        logger.error(f"sender_email: {sender_email}")
        logger.error(f"receiver_emails: {receiver_emails}")
        logger.error(f"smtp_server: {smtp_server}")
        logger.error(f"smtp_port: {smtp_port}")
        logger.error(f"smtp_user: {smtp_user}")
        logger.error(f"smtp_password: {'set' if smtp_password else 'not set'}")
        return False

    # Email content
    subject = f"Neue Veranstaltungen bei Wuppertal Live"
    body = "<h1>Neue Veranstaltungen bei Wuppertal Live</h1>"

    for event in events:
        body += f"""
        <h2 style="margin-bottom: 4;">{event['title']}</h2>
        <h3>{event['date'].strftime("%A, %d. %B %Y")}</h3>
        <p style="margin-bottom: 4px;">{event['start']} {('-' + event['end']) if event['end'] else ''}</p>
        <p>{event['location']}</p>
        <img style="margin-bottom: 30px;" src="{event['foto']}" />
        """

    # Send email
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = receiver_emails
    message["Subject"] = subject
    message.set_content(body, subtype="html")

    try:
        logger.debug(f"Sending email to {', '.join(receiver_emails)}")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        server = smtplib.SMTP(host=smtp_server, port=smtp_port)
        server.ehlo()
        server.starttls(context=context)
        server.login(smtp_user, smtp_password)
        server.send_message(message)
        server.quit()
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False

    return True


def save_to_db(events: list):
    """
    Save events to database.

    :param events: List of events
    """
    logger.info(f"Saving {len(events)} events to database...")

    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()

    new_events = []

    # Insert events into database
    for event in events:
        # Check if event already exists
        cursor.execute("SELECT * FROM events WHERE id = ?", (event["id"],))
        if cursor.fetchone():
            continue
        else:
            logger.info(f"New event: {event['title']} (#{event['id']})")
            new_events.append(event)
            cursor.execute(
                "INSERT INTO events (id, title, date, start, end, location, foto) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["id"],
                    event["title"],
                    event["date"],
                    event["start"],
                    event["end"],
                    event["location"],
                    event["foto"],
                ),
            )

    conn.commit()
    conn.close()

    notify_new_events(new_events)


def get_events() -> list or False:
    """
    Get events from wuppertal-live.de
    """
    logger.info("Getting events...")

    # Download html from wuppertal-live.de
    response = requests.get(WUPPERTAL_LIVE_FILTER_URL)
    if not response.ok:
        logger.error(
            f"Error downloading {WUPPERTAL_LIVE_FILTER_URL}: {response.text} ({response.status_code})"
        )
        return False

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
            if end == "Uhr":
                end = None

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

    return events
