import os
import time
import requests

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID")
CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET")

TOKEN_URL = (
    "https://auth.opensky-network.org/"
    "auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)

API_URL = "https://opensky-network.org/api/states/all"

FLIGHTS_AIRCRAFT_URL = (
    "https://opensky-network.org/api/flights/aircraft"
)

token = None
token_expires = 0


REGIONS = {
    "nigeria": {
        "lamin": 4.0,
        "lomin": 2.5,
        "lamax": 14.0,
        "lomax": 15.0
    },

    "africa": {
        "lamin": -35.0,
        "lomin": -20.0,
        "lamax": 38.0,
        "lomax": 55.0
    },

    "world": None
}


AIRPORTS = {
    "DNAA": "Nnamdi Azikiwe International Airport",
    "DNMM": "Murtala Muhammed International Airport",
    "DNPO": "Port Harcourt International Airport",
    "DNEN": "Akanu Ibiam International Airport",
    "DNCA": "Margaret Ekpo International Airport",
    "DNGU": "Gombe Lawanti International Airport",

    "FAOR": "O. R. Tambo International Airport",
    "FACT": "Cape Town International Airport",
    "FALE": "King Shaka International Airport",

    "HECA": "Cairo International Airport",
    "HKJK": "Jomo Kenyatta International Airport",
    "HAAB": "Addis Ababa Bole International Airport",

    "EGLL": "London Heathrow Airport",
    "LFPG": "Paris Charles de Gaulle Airport",
    "EDDF": "Frankfurt Airport",
    "EHAM": "Amsterdam Airport Schiphol",
    "LEMD": "Madrid Barajas Airport",
    "LIRF": "Rome Fiumicino Airport",

    "OMDB": "Dubai International Airport",
    "OTHH": "Hamad International Airport",
    "OERK": "King Khalid International Airport",

    "KJFK": "John F. Kennedy International Airport",
    "KLAX": "Los Angeles International Airport",
    "KATL": "Hartsfield-Jackson Atlanta International Airport",
    "KORD": "Chicago O'Hare International Airport",

    "RJTT": "Tokyo Haneda Airport",
    "VHHH": "Hong Kong International Airport",
    "WSSS": "Singapore Changi Airport"
}


def get_token():
    global token
    global token_expires

    if token and time.time() < token_expires:
        return token

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "OpenSky credentials are missing from .env"
        )

    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET
                },
                timeout=60
            )
            response.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = e
            if attempt == 2:
                raise last_error
            time.sleep(3)

    response.raise_for_status()

    data = response.json()

    token = data["access_token"]

    token_expires = (
        time.time()
        + data.get("expires_in", 1800)
        - 60
    )

    return token


def auth_headers():
    return {
        "Authorization": f"Bearer {get_token()}"
    }


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/flights")
def flights():
    try:
        region = request.args.get(
            "region",
            "africa"
        ).lower()

        if region not in REGIONS:
            return jsonify({
                "success": False,
                "error": "Invalid region"
            }), 400

        params = {}

        if REGIONS[region] is not None:
            params = REGIONS[region]

        response = requests.get(
            API_URL,
            params=params,
            headers=auth_headers(),
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        aircraft = []

        for plane in data.get("states", []):

            if len(plane) < 18:
                continue

            latitude = plane[6]
            longitude = plane[5]

            if latitude is None or longitude is None:
                continue

            aircraft.append({
                "icao24": plane[0],
                "callsign": (
                    plane[1] or "UNKNOWN"
                ).strip(),
                "country": plane[2] or "UNKNOWN",
                "latitude": latitude,
                "longitude": longitude,
                "altitude": plane[7],
                "velocity": plane[9],
                "heading": plane[10],
                "vertical_rate": plane[11],
                "on_ground": plane[8]
            })

        return jsonify({
            "success": True,
            "region": region,
            "count": len(aircraft),
            "aircraft": aircraft
        })

    except requests.HTTPError as e:

        return jsonify({
            "success": False,
            "error": f"OpenSky HTTP error: {str(e)}"
        }), 502

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/route/<icao24>")
def route(icao24):
    """
    OpenSky's aircraft-flight endpoint provides estimated
    departure/arrival airports from its flight data.

    This is NOT guaranteed to be the aircraft's current
    live destination. The frontend therefore labels it
    accordingly.
    """

    try:
        now = int(time.time())

        begin = now - 24 * 60 * 60

        response = requests.get(
            FLIGHTS_AIRCRAFT_URL,
            params={
                "icao24": icao24.lower(),
                "begin": begin,
                "end": now
            },
            headers=auth_headers(),
            timeout=30
        )

        response.raise_for_status()

        flights_data = response.json()

        if not flights_data:
            return jsonify({
                "success": False,
                "message": (
                    "No route information is currently "
                    "available for this aircraft."
                )
            })

        best = None

        for flight in flights_data:

            if not flight:
                continue

            callsign = (
                flight.get("callsign")
                or ""
            ).strip()

            departure = flight.get(
                "estDepartureAirport"
            )

            arrival = flight.get(
                "estArrivalAirport"
            )

            if departure or arrival:

                best = {
                    "callsign": callsign,
                    "departure": departure,
                    "destination": arrival
                }

                if departure and arrival:
                    break

        if not best:
            return jsonify({
                "success": False,
                "message": (
                    "OpenSky has no departure/destination "
                    "airport information for this aircraft."
                )
            })

        departure = best["departure"]
        destination = best["destination"]

        return jsonify({
            "success": True,
            "route": {
                "departure": departure,
                "destination": destination,
                "departure_name": (
                    AIRPORTS.get(departure)
                    if departure
                    else None
                ),
                "destination_name": (
                    AIRPORTS.get(destination)
                    if destination
                    else None
                ),
                "note": (
                    "Estimated route information from "
                    "OpenSky flight data. It may not represent "
                    "the aircraft's current live destination."
                )
            }
        })

    except requests.HTTPError as e:

        return jsonify({
            "success": False,
            "message": (
                "OpenSky route service returned an error."
            ),
            "error": str(e)
        }), 502

    except Exception as e:

        return jsonify({
            "success": False,
            "message": "Could not retrieve route information.",
            "error": str(e)
        }), 500


@app.route("/api/health")
def health():
    return jsonify({
        "success": True,
        "service": "AEROVERSE Flight Radar",
        "live_radar": True,
        "route_system": True
    })


if __name__ == "__main__":

    print("===================================")
    print("       AEROVERSE FLIGHT RADAR")
    print("===================================")
    print("LIVE RADAR: ON")
    print("LIVE TRACK: ON")
    print("ROUTE SYSTEM: ON")
    print()
    print("Regions: NIGERIA / AFRICA / WORLD")
    print()
    print("Open:")
    print("http://127.0.0.1:5000")
    print()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
