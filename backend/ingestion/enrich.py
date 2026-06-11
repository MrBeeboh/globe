"""
Enrichment pipeline: raw_items -> events + entities.
NER, geocoding, categorization, severity scoring, entity extraction.
"""
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

# Try to load spaCy, graceful fallback
try:
    import spacy
    NLP = spacy.load("en_core_web_sm")
    SPACY_AVAILABLE = True
except Exception:
    NLP = None
    SPACY_AVAILABLE = False
    print("[Enrich] spaCy not available, using regex fallback")

from backend.db import get_conn, query, query_one, insert, transaction

# --- Category & Severity Rules ---

CATEGORY_KEYWORDS = {
    "conflict": [
        "attack", "strike", "bomb", "missile", "rocket", "shelling", "artillery",
        "clash", "battle", "fight", "combat", "offensive", "invasion", "incursion",
        "raid", "ambush", "assault", "firefight", "shooting", "killed", "dead",
        "casualty", "fatality", "martyr", "militant", "insurgent", "rebel",
        "terrorist", "jihadist", "islamic state", "isis", "al-qaeda", "hezbollah",
        "hamas", "houthi", "taliban", "al-shabaab", "boko haram",
        "airstrike", "drone strike", "artillery", "tank", "armored",
        "ceasefire", "truce", "hostage", "prisoner", "capture", "surrender"
    ],
    "diplomatic": [
        "summit", "meeting", "talks", "negotiation", "agreement", "accord", "treaty",
        "deal", "pact", "alliance", "partnership", "cooperation", "dialogue",
        "visit", "trip", "envoy", "mediator", "arbitration", "un security council",
        "un general assembly", "nato", "eu", "african union", "arab league",
        "sanctions", "embargo", "resolution", "condemn", "support", "recognize",
        "diplomatic", "ambassador", "foreign minister", "secretary of state"
    ],
    "humanitarian": [
        "refugee", "displaced", "idp", "camp", "shelter", "aid", "assistance",
        "food security", "malnutrition", "famine", "starvation", "cholera",
        "epidemic", "pandemic", "vaccine", "medical", "hospital", "clinic",
        "unhcr", "unicef", "wfp", "icrc", "msf", "doctors without borders",
        "humanitarian", "relief", "evacuation", "corridor", "access",
        "protection", "gender-based violence", "child soldier", "trafficking"
    ],
    "political": [
        "election", "vote", "referendum", "parliament", "congress", "legislature",
        "government", "cabinet", "minister", "president", "prime minister",
        "coup", "mutiny", "protest", "demonstration", "rally", "strike",
        "unrest", "riot", "uprising", "revolution", "impeachment", "resignation",
        "corruption", "scandal", "investigation", "arrest", "detention",
        "opposition", "party", "coalition", "no confidence", "budget",
        "constitution", "amendment", "law", "bill", "decree", "emergency"
    ],
    "disaster": [
        "earthquake", "tsunami", "hurricane", "typhoon", "cyclone", "tornado",
        "flood", "landslide", "avalanche", "wildfire", "bushfire", "forest fire",
        "volcano", "eruption", "drought", "heatwave", "cold wave",
        "industrial accident", "explosion", "collapse", "derailment",
        "shipwreck", "plane crash", "train crash", "building collapse",
        "chemical spill", "radiation", "nuclear", "pandemic", "outbreak",
        "gdacs", "disaster", "emergency", "evacuation", "casualty"
    ],
    "economic": [
        "economy", "gdp", "inflation", "recession", "trade", "tariff", "sanctions",
        "oil", "gas", "energy", "pipeline", "currency", "devaluation", "default",
        "debt", "imf", "world bank", "bailout", "austerity", "budget deficit",
        "unemployment", "poverty", "inequality", "investment", "fdi",
        "stock market", "exchange rate", "central bank", "interest rate",
        "commodity", "wheat", "grain", "food price", "supply chain"
    ]
}

# Severity scoring weights
SEVERITY_BASE = {
    "conflict": 40,
    "diplomatic": 10,
    "humanitarian": 25,
    "political": 15,
    "disaster": 35,
    "economic": 10
}

SEVERITY_BOOSTERS = {
    # Casualty indicators
    "killed": 15, "dead": 15, "fatalities": 15, "casualties": 10,
    "wounded": 5, "injured": 5, "martyr": 8,
    # Scale indicators
    "mass": 20, "large-scale": 15, "major": 10, "massive": 20,
    "hundreds": 15, "thousands": 25, "tens of thousands": 30,
    # Weapon/type indicators
    "airstrike": 15, "drone strike": 12, "missile": 15, "ballistic": 18,
    "chemical": 30, "nuclear": 50, "biological": 40,
    "artillery": 10, "barrage": 12, "salvo": 10,
    # Strategic targets
    "capital": 10, "nuclear facility": 25, "airport": 8, "port": 8,
    "hospital": 15, "school": 15, "un compound": 12, "embassy": 12,
    # Urgency
    "breaking": 5, "urgent": 5, "developing": 3, "escalation": 10,
    "spillover": 12, "regional war": 25, "world war": 40
}

# Region mapping by country code
REGION_MAP = {
    # Middle East
    "ISR": "Middle East", "PSE": "Middle East", "LBN": "Middle East",
    "SYR": "Middle East", "IRQ": "Middle East", "IRN": "Middle East",
    "JOR": "Middle East", "YEM": "Middle East", "SAU": "Middle East",
    "ARE": "Middle East", "QAT": "Middle East", "BHR": "Middle East",
    "KWT": "Middle East", "OMN": "Middle East", "TUR": "Middle East",
    # Europe
    "UKR": "Europe", "RUS": "Europe", "BLR": "Europe", "MDA": "Europe",
    "POL": "Europe", "ROU": "Europe", "HUN": "Europe", "SVK": "Europe",
    "CZE": "Europe", "DEU": "Europe", "FRA": "Europe", "GBR": "Europe",
    "ITA": "Europe", "ESP": "Europe", "NLD": "Europe", "BEL": "Europe",
    "CHE": "Europe", "AUT": "Europe", "NOR": "Europe", "SWE": "Europe",
    "FIN": "Europe", "DNK": "Europe", "GRC": "Europe", "TUR": "Europe",
    # Asia-Pacific
    "CHN": "Asia-Pacific", "JPN": "Asia-Pacific", "KOR": "Asia-Pacific",
    "PRK": "Asia-Pacific", "TWN": "Asia-Pacific", "HKG": "Asia-Pacific",
    "VNM": "Asia-Pacific", "THA": "Asia-Pacific", "MYS": "Asia-Pacific",
    "SGP": "Asia-Pacific", "IDN": "Asia-Pacific", "PHL": "Asia-Pacific",
    "IND": "Asia-Pacific", "PAK": "Asia-Pacific", "BGD": "Asia-Pacific",
    "LKA": "Asia-Pacific", "MMR": "Asia-Pacific", "AFG": "Asia-Pacific",
    "AUS": "Asia-Pacific", "NZL": "Asia-Pacific",
    # Americas
    "USA": "Americas", "CAN": "Americas", "MEX": "Americas",
    "CUB": "Americas", "HTI": "Americas", "DOM": "Americas",
    "VEN": "Americas", "COL": "Americas", "ECU": "Americas",
    "PER": "Americas", "BOL": "Americas", "CHL": "Americas",
    "ARG": "Americas", "BRA": "Americas", "URY": "Americas", "PRY": "Americas",
    # Africa
    "EGY": "Africa", "LBY": "Africa", "TUN": "Africa", "DZA": "Africa",
    "MAR": "Africa", "SDN": "Africa", "SSD": "Africa", "ETH": "Africa",
    "ERI": "Africa", "DJI": "Africa", "SOM": "Africa", "KEN": "Africa",
    "UGA": "Africa", "TZA": "Africa", "RWA": "Africa", "BDI": "Africa",
    "COD": "Africa", "CAF": "Africa", "CMR": "Africa", "NGA": "Africa",
    "GHA": "Africa", "SEN": "Africa", "MLI": "Africa", "BFA": "Africa",
    "NER": "Africa", "TCD": "Africa", "ZAF": "Africa", "MOZ": "Africa",
    "AGO": "Africa", "ZWE": "Africa", "ZMB": "Africa", "MWI": "Africa",
}

# Country name -> ISO3
COUNTRY_ISO3 = {
    "united states": "USA", "usa": "USA", "america": "USA",
    "russia": "RUS", "russian federation": "RUS",
    "china": "CHN", "prc": "CHN",
    "ukraine": "UKR",
    "israel": "ISR", "palestine": "PSE", "gaza": "PSE", "west bank": "PSE",
    "iran": "IRN", "iraq": "IRQ", "syria": "SYR", "lebanon": "LBN",
    "turkey": "TUR", "turkiye": "TUR",
    "saudi arabia": "SAU", "uae": "ARE", "united arab emirates": "ARE",
    "qatar": "QAT", "kuwait": "KWT", "bahrain": "BHR", "oman": "OMN",
    "yemen": "YEM", "jordan": "JOR",
    "united kingdom": "GBR", "uk": "GBR", "britain": "GBR",
    "france": "FRA", "germany": "DEU", "italy": "ITA", "spain": "ESP",
    "poland": "POL", "romania": "ROU", "netherlands": "NLD", "belgium": "BEL",
    "north korea": "PRK", "dprk": "PRK", "south korea": "KOR", "rok": "KOR",
    "japan": "JPN", "taiwan": "TWN",
    "india": "IND", "pakistan": "PAK", "bangladesh": "BGD",
    "afghanistan": "AFG", "myanmar": "MMR", "burma": "MMR",
    "egypt": "EGY", "libya": "LBY", "sudan": "SDN", "south sudan": "SSD",
    "ethiopia": "ETH", "eritrea": "ERI", "somalia": "SOM", "kenya": "KEN",
    "nigeria": "NGA", "dr congo": "COD", "congo": "COG",
    "south africa": "ZAF", "venezuela": "VEN", "colombia": "COL",
    "mexico": "MEX", "brazil": "BRA", "argentina": "ARG",
    "canada": "CAN", "australia": "AUS", "new zealand": "NZL",
}

# Major cities for geocoding fallback
MAJOR_CITIES = {
    "gaza": (31.5, 34.47, "PSE"), "jerusalem": (31.78, 35.22, "ISR"),
    "tel aviv": (32.08, 34.78, "ISR"), "haifa": (32.82, 34.98, "ISR"),
    "beirut": (33.89, 35.50, "LBN"), "damascus": (33.51, 36.29, "SYR"),
    "aleppo": (36.20, 37.16, "SYR"), "baghdad": (33.31, 44.37, "IRQ"),
    "mosul": (36.34, 43.13, "IRQ"), "basra": (30.51, 47.79, "IRQ"),
    "tehran": (35.69, 51.39, "IRN"), "kiev": (50.45, 30.52, "UKR"),
    "kyiv": (50.45, 30.52, "UKR"), "kharkiv": (49.99, 36.23, "UKR"),
    "odonetsk": (48.01, 37.80, "UKR"), "mariupol": (47.09, 37.55, "UKR"),
    "moscow": (55.75, 37.62, "RUS"), "st petersburg": (59.93, 30.34, "RUS"),
    "kabul": (34.56, 69.21, "AFG"), "baghdad": (33.31, 44.37, "IRQ"),
    "tripoli": (32.89, 13.19, "LBY"), "benghazi": (32.12, 20.07, "LBY"),
    "cairo": (30.04, 31.24, "EGY"), "alexandria": (31.20, 29.92, "EGY"),
    "khartoum": (15.50, 32.56, "SDN"), "juba": (4.85, 31.58, "SSD"),
    "mogadishu": (2.04, 45.34, "SOM"), "nairobi": (-1.29, 36.82, "KEN"),
    "addis ababa": (9.03, 38.74, "ETH"), "asmera": (15.33, 38.93, "ERI"),
    "djibouti": (11.59, 43.15, "DJI"), "kiev": (50.45, 30.52, "UKR"),
    "hanoi": (21.03, 105.85, "VNM"), "ho chi minh": (10.82, 106.63, "VNM"),
    "bangkok": (13.75, 100.50, "THA"), "kuala lumpur": (3.14, 101.69, "MYS"),
    "singapore": (1.35, 103.82, "SGP"), "jakarta": (-6.21, 106.85, "IDN"),
    "manila": (14.60, 120.98, "PHL"), "seoul": (37.57, 126.98, "KOR"),
    "pyongyang": (39.03, 125.75, "PRK"), "tokyo": (35.68, 139.69, "JPN"),
    "beijing": (39.91, 116.40, "CHN"), "shanghai": (31.23, 121.47, "CHN"),
    "hong kong": (22.32, 114.17, "HKG"), "taipei": (25.03, 121.56, "TWN"),
    "new delhi": (28.61, 77.21, "IND"), "mumbai": (19.08, 72.88, "IND"),
    "islamabad": (33.68, 73.05, "PAK"), "karachi": (24.86, 67.01, "PAK"),
    "dhaka": (23.81, 90.41, "BGD"), "colombo": (6.93, 79.86, "LKA"),
    "yangon": (16.84, 96.17, "MMR"), "naypyidaw": (19.75, 96.11, "MMR"),
}

@dataclass
class EnrichedEvent:
    title: str
    summary: str
    url: str
    category: str
    severity: int
    confidence: float
    lat: Optional[float]
    lng: Optional[float]
    location_name: str
    country_code: Optional[str]
    region: str
    actors: List[Dict[str, str]]
    casualties: Dict[str, int]
    tags: List[str]
    published_at: str
    raw_item_id: int

class Enricher:
    def __init__(self):
        self.nlp = NLP

    def categorize(self, text: str) -> Tuple[str, float]:
        """Return (category, confidence)."""
        text_lower = text.lower()
        scores = {}
        for cat, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[cat] = score
        if not scores:
            return "political", 0.3
        best = max(scores.items(), key=lambda x: x[1])
        confidence = min(0.9, 0.4 + best[1] * 0.1)
        return best[0], confidence

    def score_severity(self, category: str, text: str) -> int:
        """Score 0-100."""
        base = SEVERITY_BASE.get(category, 10)
        text_lower = text.lower()
        boost = 0
        for keyword, weight in SEVERITY_BOOSTERS.items():
            if keyword in text_lower:
                boost += weight
        # Casualty number extraction
        casualty_boost = self._extract_casualty_boost(text_lower)
        boost += casualty_boost
        return min(100, base + boost)

    def _extract_casualty_boost(self, text: str) -> int:
        """Extract casualty numbers from text, return boost."""
        boost = 0
        # Patterns: "X killed", "X dead", "X fatalities", "at least X", "more than X"
        patterns = [
            r"(?:at least|more than|over|nearly|around|about)\s+(\d{1,3}(?:,\d{3})*)\s+(?:killed|dead|fatalities|casualties)",
            r"(\d{1,3}(?:,\d{3})*)\s+(?:killed|dead|fatalities|casualties)",
            r"(?:dozens|scores)\s+(?:of\s+)?(?:killed|dead)",
            r"hundreds\s+(?:of\s+)?(?:killed|dead)",
            r"thousands\s+(?:of\s+)?(?:killed|dead)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if "dozens" in match.group(0) or "scores" in match.group(0):
                    boost += 10
                elif "hundreds" in match.group(0):
                    boost += 20
                elif "thousands" in match.group(0):
                    boost += 35
                else:
                    try:
                        num = int(match.group(1).replace(",", ""))
                        if num >= 1000:
                            boost += 30
                        elif num >= 100:
                            boost += 20
                        elif num >= 10:
                            boost += 10
                        elif num >= 3:
                            boost += 5
                    except (IndexError, ValueError):
                        pass
        return min(boost, 50)

    def extract_actors(self, text: str) -> List[Dict[str, str]]:
        """Extract actor entities: state, non-state, international."""
        actors = []
        text_lower = text.lower()

        # Known actor patterns
        state_actors = [
            ("IDF", "state", "Israel Defense Forces"),
            ("Israeli military", "state", "Israel Defense Forces"),
            ("Russian military", "state", "Russian Armed Forces"),
            ("Ukrainian military", "state", "Ukrainian Armed Forces"),
            ("US military", "state", "United States Armed Forces"),
            ("US forces", "state", "United States Armed Forces"),
            ("NATO", "international", "North Atlantic Treaty Organization"),
            ("UN", "international", "United Nations"),
            ("UNIFIL", "international", "UN Interim Force in Lebanon"),
        ]

        non_state_actors = [
            ("Hamas", "non-state", "Hamas"),
            ("Hezbollah", "non-state", "Hezbollah"),
            ("Houthis", "non-state", "Ansar Allah"),
            ("Houthi", "non-state", "Ansar Allah"),
            ("ISIS", "non-state", "Islamic State"),
            ("Islamic State", "non-state", "Islamic State"),
            ("Al-Qaeda", "non-state", "Al-Qaeda"),
            ("Taliban", "non-state", "Taliban"),
            ("Al-Shabaab", "non-state", "Al-Shabaab"),
            ("Boko Haram", "non-state", "Boko Haram"),
            ("PKK", "non-state", "Kurdistan Workers' Party"),
            ("YPG", "non-state", "People's Protection Units"),
            ("SDF", "non-state", "Syrian Democratic Forces"),
            ("FSA", "non-state", "Free Syrian Army"),
            ("NPA", "non-state", "New People's Army"),
            ("ELN", "non-state", "National Liberation Army"),
            ("FARC", "non-state", "FARC dissidents"),
            ("Cartel", "non-state", "Drug cartel"),
            ("Gang", "non-state", "Criminal gang"),
        ]

        seen = set()
        for name, atype, full in state_actors + non_state_actors:
            if name.lower() in text_lower and name not in seen:
                actors.append({"name": name, "type": atype, "full_name": full})
                seen.add(name)

        # spaCy NER for additional actors
        if self.nlp:
            doc = self.nlp(text)
            for ent in doc.ents:
                if ent.label_ in ("ORG", "GPE", "NORP") and len(ent.text) > 2:
                    if ent.text not in seen:
                        atype = "state" if ent.label_ == "GPE" else "org"
                        actors.append({"name": ent.text, "type": atype, "full_name": ent.text})
                        seen.add(ent.text)

        return actors[:10]  # Limit

    def extract_casualties(self, text: str) -> Dict[str, int]:
        """Extract casualty numbers."""
        casualties = {"killed": 0, "wounded": 0, "civilian": 0}
        text_lower = text.lower()

        # Killed
        for match in re.finditer(r"(\d{1,3}(?:,\d{3})*)\s+(?:killed|dead|fatalities)", text_lower):
            try:
                casualties["killed"] += int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Wounded/injured
        for match in re.finditer(r"(\d{1,3}(?:,\d{3})*)\s+(?:wounded|injured)", text_lower):
            try:
                casualties["wounded"] += int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Civilian
        for match in re.finditer(r"(\d{1,3}(?:,\d{3})*)\s+civilian", text_lower):
            try:
                casualties["civilian"] += int(match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Qualitative
        if "dozens" in text_lower or "scores" in text_lower:
            casualties["killed"] = max(casualties["killed"], 24)
        if "hundreds" in text_lower:
            casualties["killed"] = max(casualties["killed"], 200)
        if "thousands" in text_lower:
            casualties["killed"] = max(casualties["killed"], 1000)

        return casualties

    def extract_tags(self, text: str, category: str) -> List[str]:
        """Extract descriptive tags."""
        tags = [category]
        text_lower = text.lower()

        tag_patterns = {
            "airstrike": ["airstrike", "air strike", "air raid", "jet strike"],
            "drone_strike": ["drone strike", "uav strike", "drone attack"],
            "artillery": ["artillery", "shelling", "barrage", "rocket artillery"],
            "missile": ["missile", "ballistic missile", "cruise missile"],
            "ceasefire": ["ceasefire", "cease-fire", "truce", "halt"],
            "hostage": ["hostage", "captive", "abducted", "kidnapped"],
            "evacuation": ["evacuation", "evacuated", "flee", "displaced"],
            "sanctions": ["sanctions", "embargo", "restrictions"],
            "election": ["election", "vote", "poll", "ballot"],
            "protest": ["protest", "demonstration", "rally", "march"],
            "coup": ["coup", "mutiny", "putsch", "overthrow"],
            "earthquake": ["earthquake", "quake", "tremor", "seismic"],
            "flood": ["flood", "flooding", "inundation", "deluge"],
            "wildfire": ["wildfire", "bushfire", "forest fire"],
            "cyber": ["cyber", "hack", "ransomware", "malware", "ddos"],
            "nuclear": ["nuclear", "radiation", "reactor", "enrichment"],
            "chemical": ["chemical weapon", "sarin", "chlorine", "mustard gas"],
        }

        for tag, patterns in tag_patterns.items():
            if any(p in text_lower for p in patterns):
                tags.append(tag)

        return tags

    def geocode(self, text: str, raw_lat: Optional[float] = None, raw_lng: Optional[float] = None,
                raw_location: str = "") -> Tuple[Optional[float], Optional[float], str, Optional[str]]:
        """
        Returns (lat, lng, location_name, country_code).
        Priority: raw coords > city match > country match > None.
        """
        # Use raw GDELT coordinates if available and valid
        if raw_lat is not None and raw_lng is not None:
            if -90 <= raw_lat <= 90 and -180 <= raw_lng <= 180:
                country = self._reverse_geocode_country(raw_lat, raw_lng)
                return raw_lat, raw_lng, raw_location or f"{raw_lat:.2f}, {raw_lng:.2f}", country

        # Try city matches in text
        text_lower = text.lower()
        for city, (lat, lng, cc) in MAJOR_CITIES.items():
            if city in text_lower:
                return lat, lng, city.title(), cc

        # Try country matches
        best_country = None
        best_len = 0
        for name, cc in COUNTRY_ISO3.items():
            if name in text_lower and len(name) > best_len:
                best_country = cc
                best_len = len(name)

        if best_country:
            # Approximate country centroid (could be improved)
            country_centroids = {
                "ISR": (31.0, 35.0), "PSE": (31.5, 34.5), "LBN": (33.8, 35.8),
                "SYR": (35.0, 38.0), "IRQ": (33.0, 44.0), "IRN": (32.0, 53.0),
                "UKR": (49.0, 32.0), "RUS": (61.5, 95.0), "USA": (39.8, -98.5),
                "CHN": (35.0, 103.0), "AFG": (33.0, 65.0), "YEM": (15.5, 48.0),
                "SDN": (15.0, 30.0), "SOM": (5.0, 46.0), "ETH": (9.0, 40.0),
                "MMR": (22.0, 96.0), "VEN": (8.0, -66.0), "HTI": (19.0, -72.0),
            }
            lat, lng = country_centroids.get(best_country, (0.0, 0.0))
            return lat, lng, best_country, best_country

        return None, None, "", None

    def _reverse_geocode_country(self, lat: float, lng: float) -> Optional[str]:
        """Simple point-in-bbox for country."""
        bboxes = {
            "ISR": (29.5, 34.2, 33.3, 35.9), "PSE": (31.2, 34.2, 32.5, 35.6),
            "LBN": (33.0, 35.0, 34.7, 36.6), "SYR": (32.3, 35.7, 37.3, 42.4),
            "IRQ": (29.0, 38.8, 37.4, 48.6), "IRN": (25.0, 44.0, 39.8, 63.3),
            "UKR": (44.4, 22.1, 52.4, 40.2), "RUS": (41.2, 19.6, 81.9, 169.0),
            "USA": (24.4, -124.8, 49.4, -66.9), "CHN": (18.2, 73.5, 53.6, 134.8),
        }
        for cc, (min_lat, min_lng, max_lat, max_lng) in bboxes.items():
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                return cc
        return None

    def enrich(self, raw_item: Dict[str, Any]) -> Optional[EnrichedEvent]:
        """Main enrichment entry point."""
        raw = json.loads(raw_item["raw_json"])
        title = raw_item["title"]
        summary = raw.get("summary", "") or raw.get("description", "")
        text = f"{title}. {summary}"

        # Category
        category, cat_conf = self.categorize(text)

        # Severity
        severity = self.score_severity(category, text)

        # Actors, casualties, tags
        actors = self.extract_actors(text)
        casualties = self.extract_casualties(text)
        tags = self.extract_tags(text, category)

        # Geocode
        raw_lat = raw.get("ActionGeo_Lat")
        raw_lng = raw.get("ActionGeo_Long")
        raw_loc = raw.get("ActionGeo_FullName", "")
        if raw_lat:
            try:
                raw_lat = float(raw_lat)
            except (ValueError, TypeError):
                raw_lat = None
        if raw_lng:
            try:
                raw_lng = float(raw_lng)
            except (ValueError, TypeError):
                raw_lng = None

        lat, lng, loc_name, country_code = self.geocode(text, raw_lat, raw_lng, raw_loc)
        region = REGION_MAP.get(country_code, "Unknown") if country_code else "Unknown"

        # Confidence: combine category confidence with data completeness
        confidence = cat_conf
        if lat and lng:
            confidence += 0.15
        if actors:
            confidence += 0.1
        if casualties["killed"] > 0:
            confidence += 0.1
        if raw_item.get("url"):
            confidence += 0.05
        confidence = min(0.95, confidence)

        # Skip very low confidence
        if confidence < 0.35:
            return None

        return EnrichedEvent(
            title=title[:500],
            summary=summary[:2000],
            url=raw_item.get("url", "") or raw.get("SOURCEURL", "") or raw.get("link", ""),
            category=category,
            severity=severity,
            confidence=round(confidence, 2),
            lat=lat,
            lng=lng,
            location_name=loc_name or raw_loc or "Unknown location",
            country_code=country_code,
            region=region,
            actors=actors,
            casualties=casualties,
            tags=tags,
            published_at=raw_item["published_at"],
            raw_item_id=raw_item["id"]
        )

    def _country_exists(self, iso3: str) -> bool:
        """Check if a country ISO3 code exists in the countries table."""
        return bool(query_one("SELECT 1 FROM countries WHERE iso3 = ?", (iso3,)))

    def store_event(self, event: EnrichedEvent) -> int:
        """Store enriched event and its entities."""
        with transaction() as conn:
            # Insert event
            event_id = insert("events", {
                "raw_item_id": event.raw_item_id,
                "title": event.title,
                "summary": event.summary,
                "url": event.url,
                "category": event.category,
                "severity": event.severity,
                "confidence": event.confidence,
                "lat": event.lat,
                "lng": event.lng,
                "location_name": event.location_name,
                "country_code": event.country_code,
                "region": event.region,
                "actors_json": json.dumps(event.actors),
                "casualties_json": json.dumps(event.casualties),
                "tags_json": json.dumps(event.tags),
                "published_at": event.published_at
            })

            # Insert entities
            all_entities = []
            for actor in event.actors:
                all_entities.append({
                    "event_id": event_id,
                    "entity_type": "org" if actor["type"] != "state" else "state",
                    "name": actor["name"],
                    "aliases_json": json.dumps([]),
                    "metadata_json": json.dumps({"role": actor.get("type", ""), "full_name": actor.get("full_name", "")}),
                    "mention_count": 1
                })

            # Add casualty entities if significant
            if event.casualties["killed"] > 0:
                all_entities.append({
                    "event_id": event_id,
                    "entity_type": "casualty",
                    "name": f"{event.casualties['killed']} killed",
                    "aliases_json": "[]",
                    "metadata_json": json.dumps(event.casualties),
                    "mention_count": 1
                })

            # Add tag entities
            for tag in event.tags:
                all_entities.append({
                    "event_id": event_id,
                    "entity_type": "tag",
                    "name": tag,
                    "aliases_json": "[]",
                    "metadata_json": "{}",
                    "mention_count": 1
                })

            if all_entities:
                cols = ", ".join(all_entities[0].keys())
                placeholders = ", ".join(["?" for _ in all_entities[0]])
                sql = f"INSERT INTO entities ({cols}) VALUES ({placeholders})"
                conn.executemany(sql, [tuple(e.values()) for e in all_entities])

            # Link event to country (only if country exists in DB)
            if event.country_code and self._country_exists(event.country_code):
                conn.execute(
                    "INSERT OR IGNORE INTO event_countries (event_id, country_code, role) VALUES (?, ?, ?)",
                    (event_id, event.country_code, "primary")
                )

            # Add actor countries (only if country exists in DB)
            for actor in event.actors:
                actor_cc = COUNTRY_ISO3.get(actor["name"].lower())
                if actor_cc and actor_cc != event.country_code and self._country_exists(actor_cc):
                    conn.execute(
                        "INSERT OR IGNORE INTO event_countries (event_id, country_code, role) VALUES (?, ?, ?)",
                        (event_id, actor_cc, "actor")
                    )

            conn.commit()
            return event_id