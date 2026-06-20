"""Map the feed's city-level `ground` strings to full venue details.

The openfootball feed only carries a host-city label; this fills in the stadium
name plus city / state-or-province / country for display.
"""

VENUES = {
    "Atlanta": ("Mercedes-Benz Stadium", "Atlanta", "Georgia", "USA"),
    "Boston (Foxborough)": ("Gillette Stadium", "Foxborough", "Massachusetts", "USA"),
    "Dallas (Arlington)": ("AT&T Stadium", "Arlington", "Texas", "USA"),
    "Guadalajara (Zapopan)": ("Estadio Akron", "Zapopan", "Jalisco", "Mexico"),
    "Houston": ("NRG Stadium", "Houston", "Texas", "USA"),
    "Kansas City": ("Arrowhead Stadium", "Kansas City", "Missouri", "USA"),
    "Los Angeles (Inglewood)": ("SoFi Stadium", "Inglewood", "California", "USA"),
    "Mexico City": ("Estadio Azteca", "Mexico City", None, "Mexico"),
    "Miami (Miami Gardens)": ("Hard Rock Stadium", "Miami Gardens", "Florida", "USA"),
    "Monterrey (Guadalupe)": ("Estadio BBVA", "Guadalupe", "Nuevo León", "Mexico"),
    "New York/New Jersey (East Rutherford)": ("MetLife Stadium", "East Rutherford", "New Jersey", "USA"),
    "Philadelphia": ("Lincoln Financial Field", "Philadelphia", "Pennsylvania", "USA"),
    "San Francisco Bay Area (Santa Clara)": ("Levi's Stadium", "Santa Clara", "California", "USA"),
    "Seattle": ("Lumen Field", "Seattle", "Washington", "USA"),
    "Toronto": ("BMO Field", "Toronto", "Ontario", "Canada"),
    "Vancouver": ("BC Place", "Vancouver", "British Columbia", "Canada"),
}


def venue(ground: str):
    """Return (stadium, location) where location is 'City, State, Country'."""
    v = VENUES.get(ground)
    if not v:
        return ground, ""
    stadium, city, region, country = v
    parts = [p for p in (city, region, country) if p]
    return stadium, ", ".join(parts)


def venue_str(ground: str) -> str:
    stadium, loc = venue(ground)
    return f"{stadium} · {loc}" if loc else stadium
