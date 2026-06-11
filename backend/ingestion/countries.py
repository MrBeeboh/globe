"""
Country and City profile ingestion.
Fetches/merges data from World Bank, CIA Factbook, Global Firepower, V-Dem, UN.
Run once to populate initial profiles, then update periodically.
"""
import json
import csv
import io
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx
from backend.db import get_conn, insert, upsert, query_one, transaction

# World Bank API base
WB_API = "https://api.worldbank.org/v2"

# Major countries to prioritize (ISO3)
PRIORITY_COUNTRIES = [
    "USA", "CHN", "RUS", "IND", "JPN", "DEU", "GBR", "FRA", "BRA", "CAN",
    "AUS", "KOR", "MEX", "IDN", "TUR", "SAU", "IRN", "ISR", "UKR", "POL",
    "EGY", "NGA", "ZAF", "ARG", "VEN", "COL", "PER", "CHL", "PAK", "BGD",
    "VNM", "THA", "MYS", "SGP", "PHL", "TWN", "HKG", "ARE", "QAT", "KWT",
    "LBN", "SYR", "IRQ", "YEM", "JOR", "PSE", "AFG", "MMR", "LKA", "NPL",
    "ETH", "KEN", "TZA", "UGA", "GHA", "SEN", "CIV", "CMR", "COD", "SDN",
    "SSD", "SOM", "ERI", "DJI", "MDG", "MWI", "ZMB", "ZWE", "BWA", "NAM",
]

# Country name to ISO3 mapping (comprehensive)
COUNTRY_ISO3 = {
    "united states": "USA", "usa": "USA", "america": "USA",
    "china": "CHN", "prc": "CHN", "people's republic of china": "CHN",
    "russia": "RUS", "russian federation": "RUS",
    "india": "IND", "japan": "JPN", "germany": "DEU", "united kingdom": "GBR",
    "uk": "GBR", "britain": "GBR", "france": "FRA", "brazil": "BRA",
    "canada": "CAN", "australia": "AUS", "south korea": "KOR", "rok": "KOR",
    "mexico": "MEX", "indonesia": "IDN", "turkey": "TUR", "turkiye": "TUR",
    "saudi arabia": "SAU", "iran": "IRN", "israel": "ISR", "ukraine": "UKR",
    "poland": "POL", "egypt": "EGY", "nigeria": "NGA", "south africa": "ZAF",
    "argentina": "ARG", "venezuela": "VEN", "colombia": "COL", "peru": "PER",
    "chile": "CHL", "pakistan": "PAK", "bangladesh": "BGD", "vietnam": "VNM",
    "thailand": "THA", "malaysia": "MYS", "singapore": "SGP", "philippines": "PHL",
    "taiwan": "TWN", "hong kong": "HKG", "uae": "ARE", "united arab emirates": "ARE",
    "qatar": "QAT", "kuwait": "KWT", "lebanon": "LBN", "syria": "SYR",
    "iraq": "IRQ", "yemen": "YEM", "jordan": "JOR", "palestine": "PSE",
    "afghanistan": "AFG", "myanmar": "MMR", "burma": "MMR", "sri lanka": "LKA",
    "nepal": "NPL", "ethiopia": "ETH", "kenya": "KEN", "tanzania": "TZA",
    "uganda": "UGA", "ghana": "GHA", "senegal": "SEN", "ivory coast": "CIV",
    "cameroon": "CMR", "dr congo": "COD", "congo": "COG", "sudan": "SDN",
    "south sudan": "SSD", "somalia": "SOM", "eritrea": "ERI", "djibouti": "DJI",
    "madagascar": "MDG", "malawi": "MWI", "zambia": "ZMB", "zimbabwe": "ZWE",
    "botswana": "BWA", "namibia": "NAM", "morocco": "MAR", "algeria": "DZA",
    "tunisia": "TUN", "libya": "LBY", "niger": "NER", "mali": "MLI",
    "burkina faso": "BFA", "chad": "TCD", "mauritania": "MRT", "senegal": "SEN",
    "guinea": "GIN", "sierra leone": "SLE", "liberia": "LBR", "gabon": "GAB",
    "congo": "COG", "drc": "COD", "rwanda": "RWA", "burundi": "BDI",
    "mozambique": "MOZ", "angola": "AGO", "zambia": "ZMB", "malawi": "MWI",
    "zimbabwe": "ZWE", "botswana": "BWA", "namibia": "NAM", "eswatini": "SWZ",
    "lesotho": "LSO", "south africa": "ZAF", "namibia": "NAM",
    "italy": "ITA", "spain": "ESP", "netherlands": "NLD", "belgium": "BEL",
    "switzerland": "CHE", "austria": "AUT", "norway": "NOR", "sweden": "SWE",
    "finland": "FIN", "denmark": "DNK", "greece": "GRC", "portugal": "PRT",
    "ireland": "IRL", "czechia": "CZE", "hungary": "HUN", "romania": "ROU",
    "bulgaria": "BGR", "croatia": "HRV", "slovenia": "SVN", "slovakia": "SVK",
    "lithuania": "LTU", "latvia": "LVA", "estonia": "EST", "belarus": "BLR",
    "moldova": "MDA", "georgia": "GEO", "armenia": "ARM", "azerbaijan": "AZE",
    "kazakhstan": "KAZ", "uzbekistan": "UZB", "turkmenistan": "TKM",
    "kyrgyzstan": "KGZ", "tajikistan": "TJK", "mongolia": "MNG",
    "north korea": "PRK", "dprk": "PRK",
}

# Approximate country centroids for map display
COUNTRY_CENTROIDS = {
    "USA": (39.8, -98.5), "CHN": (35.0, 103.0), "RUS": (61.5, 95.0),
    "IND": (21.0, 78.0), "JPN": (36.2, 138.3), "DEU": (51.2, 10.4),
    "GBR": (55.4, -3.4), "FRA": (46.6, 2.2), "BRA": (-10.0, -55.0),
    "CAN": (56.1, -96.0), "AUS": (-25.3, 133.8), "KOR": (36.5, 127.8),
    "MEX": (23.6, -102.5), "IDN": (-2.5, 118.0), "TUR": (39.0, 35.0),
    "SAU": (23.9, 45.1), "IRN": (32.4, 53.7), "ISR": (31.4, 35.0),
    "UKR": (48.4, 31.2), "POL": (52.0, 19.0), "EGY": (26.8, 30.8),
    "NGA": (9.1, 8.7), "ZAF": (-30.6, 23.0), "ARG": (-38.4, -63.6),
    "VEN": (8.0, -66.0), "COL": (4.6, -74.1), "PER": (-9.2, -75.0),
    "CHL": (-35.7, -71.5), "PAK": (30.4, 69.3), "BGD": (23.7, 90.4),
    "VNM": (16.2, 107.8), "THA": (15.0, 101.0), "MYS": (3.1, 101.7),
    "SGP": (1.3, 103.8), "PHL": (12.9, 121.8), "TWN": (23.7, 121.0),
    "HKG": (22.3, 114.2), "ARE": (24.0, 54.0), "QAT": (25.3, 51.5),
    "KWT": (29.4, 48.0), "LBN": (33.9, 35.9), "SYR": (35.0, 38.5),
    "IRQ": (33.2, 43.7), "YEM": (15.6, 47.5), "JOR": (31.0, 36.5),
    "PSE": (31.5, 34.5), "AFG": (33.9, 67.0), "MMR": (21.9, 96.0),
    "LKA": (7.9, 80.8), "NPL": (28.4, 84.0), "ETH": (9.1, 40.5),
    "KEN": (-0.0, 38.0), "TZA": (-6.3, 34.8), "UGA": (1.4, 32.3),
    "GHA": (7.9, -1.0), "SEN": (14.5, -14.5), "CIV": (7.5, -5.5),
    "CMR": (3.8, 11.5), "COD": (-2.9, 23.7), "SDN": (15.0, 30.0),
    "SSD": (6.9, 31.0), "SOM": (5.2, 46.2), "ERI": (15.1, 39.8),
    "DJI": (11.8, 42.6), "MDG": (-18.8, 47.5), "MWI": (-13.3, 34.3),
    "ZMB": (-13.1, 27.8), "ZWE": (-19.0, 29.9), "BWA": (-22.3, 24.7),
    "NAM": (-22.9, 18.5), "MAR": (31.7, -7.1), "DZA": (28.0, 1.7),
    "TUN": (33.9, 9.5), "LBY": (26.3, 17.2), "NER": (17.6, 8.1),
    "MLI": (17.6, -4.0), "BFA": (12.2, -1.6), "TCD": (15.5, 18.7),
    "MRT": (21.0, -10.9), "GIN": (9.9, -9.7), "SLE": (8.5, -11.8),
    "LBR": (6.4, -9.4), "GAB": (-0.8, 11.6), "COG": (-0.7, 15.0),
    "RWA": (-1.9, 29.9), "BDI": (-3.4, 29.9), "MOZ": (-18.7, 35.6),
    "AGO": (-11.2, 17.9), "SWZ": (-26.5, 31.5), "LSO": (-29.6, 28.2),
    "ITA": (41.9, 12.6), "ESP": (40.4, -3.7), "NLD": (52.1, 5.3),
    "BEL": (50.8, 4.5), "CHE": (46.8, 8.2), "AUT": (47.5, 14.6),
    "NOR": (60.5, 8.5), "SWE": (60.1, 18.6), "FIN": (61.9, 25.7),
    "DNK": (56.3, 9.5), "GRC": (39.1, 21.8), "PRT": (39.4, -8.2),
    "IRL": (53.4, -8.2), "CZE": (49.8, 15.5), "HUN": (47.2, 19.5),
    "ROU": (45.9, 25.0), "BGR": (42.7, 25.5), "HRV": (45.1, 15.2),
    "SVN": (46.2, 14.6), "SVK": (48.7, 19.7), "LTU": (55.2, 23.9),
    "LVA": (56.9, 24.6), "EST": (58.6, 25.5), "BLR": (53.7, 27.9),
    "MDA": (47.0, 28.8), "GEO": (42.3, 43.4), "ARM": (40.1, 45.0),
    "AZE": (40.1, 47.6), "KAZ": (48.0, 66.9), "UZB": (41.4, 64.6),
    "TKM": (38.9, 59.6), "KGZ": (41.2, 74.8), "TJK": (39.0, 71.3),
    "MNG": (46.9, 103.8), "PRK": (40.3, 127.4),
}

class CountryIngester:
    def __init__(self):
        self.client = httpx.Client(timeout=60.0)

    def fetch_world_bank_indicators(self, iso3: str, indicators: List[str]) -> Dict[str, Any]:
        """Fetch multiple indicators from World Bank API for a country."""
        results = {}
        indicator_str = ",".join(indicators)
        url = f"{WB_API}/country/{iso3.lower()}/indicator/{indicator_str}"
        params = {"format": "json", "per_page": 100, "date": "2020:2024"}

        try:
            resp = self.client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if len(data) > 1:
                    for entry in data[1]:
                        ind_code = entry["indicator"]["id"]
                        year = entry["date"]
                        value = entry["value"]
                        if value is not None:
                            if ind_code not in results or int(year) > int(results[ind_code].get("year", 0)):
                                results[ind_code] = {"value": value, "year": year}
        except Exception as e:
            print(f"[WorldBank] {iso3}: {e}")

        return results

    def build_country_profile(self, iso3: str, name: str) -> Dict[str, Any]:
        """Build a comprehensive country profile from multiple sources."""
        lat, lng = COUNTRY_CENTROIDS.get(iso3, (0.0, 0.0))

        # World Bank indicators
        wb_indicators = {
            "SP.POP.TOTL": "population",
            "NY.GDP.MKTP.CD": "gdp_usd",
            "NY.GDP.PCAP.CD": "gdp_per_capita",
            "MS.MIL.XPND.GD.ZS": "military_pct_gdp",
            "AG.LND.TOTL.K2": "area_km2",
        }

        wb_data = self.fetch_world_bank_indicators(iso3, list(wb_indicators.keys()))

        # Military spending USD estimate
        mil_spending_usd = None
        if "MS.MIL.XPND.GD.ZS" in wb_data and "NY.GDP.MKTP.CD" in wb_data:
            mil_pct = wb_data["MS.MIL.XPND.GD.ZS"]["value"]
            gdp = wb_data["NY.GDP.MKTP.CD"]["value"]
            if mil_pct and gdp:
                mil_spending_usd = int(gdp * mil_pct / 100)

        # Regime type approximations (would use V-Dem in production)
        regime_types = {
            "USA": "democracy", "GBR": "democracy", "FRA": "democracy", "DEU": "democracy",
            "JPN": "democracy", "CAN": "democracy", "AUS": "democracy", "KOR": "democracy",
            "IND": "democracy", "BRA": "democracy", "POL": "democracy", "ZAF": "democracy",
            "CHN": "autocracy", "RUS": "autocracy", "IRN": "theocracy", "SAU": "monarchy",
            "PRK": "totalitarian", "CUB": "autocracy", "VEN": "hybrid", "TUR": "hybrid",
            "HUN": "hybrid", "PHL": "hybrid", "EGY": "autocracy", "ARE": "monarchy",
            "QAT": "monarchy", "KWT": "monarchy", "SGP": "hybrid", "VNM": "autocracy",
            "PAK": "hybrid", "BGD": "hybrid", "NGA": "hybrid", "ETH": "autocracy",
        }

        # Nuclear states
        nuclear_states = {"USA", "RUS", "CHN", "FRA", "GBR", "IND", "PAK", "PRK", "ISR"}

        # Trade partners (major) - placeholder
        trade_partners = self._get_major_trade_partners(iso3)

        # Risk indices (placeholder - would come from FSI, INFORM, etc.)
        risk_indices = self._get_risk_indices(iso3)

        # Leadership (placeholder - would come from CIA Factbook / Wikipedia)
        leadership = self._get_leadership(iso3)

        # Conflict history summary
        conflict_history = self._get_conflict_history(iso3)

        return {
            "iso3": iso3,
            "name": name,
            "capital": self._get_capital(iso3),
            "lat": lat,
            "lng": lng,
            "population": wb_data.get("SP.POP.TOTL", {}).get("value"),
            "area_km2": wb_data.get("AG.LND.TOTL.K2", {}).get("value"),
            "gdp_usd": wb_data.get("NY.GDP.MKTP.CD", {}).get("value"),
            "gdp_per_capita": wb_data.get("NY.GDP.PCAP.CD", {}).get("value"),
            "regime_type": regime_types.get(iso3, "unknown"),
            "regime_score": self._get_regime_score(iso3),
            "military_spending_usd": mil_spending_usd,
            "military_personnel": self._get_military_personnel(iso3),
            "nuclear": 1 if iso3 in nuclear_states else 0,
            "trade_partners_json": json.dumps(trade_partners),
            "risk_indices_json": json.dumps(risk_indices),
            "leadership_json": json.dumps(leadership),
            "recent_coups": self._count_recent_coups(iso3),
            "recent_protests": self._count_recent_protests(iso3),
            "conflict_history_json": json.dumps(conflict_history),
        }

    def _get_capital(self, iso3: str) -> Optional[str]:
        capitals = {
            "USA": "Washington DC", "CHN": "Beijing", "RUS": "Moscow",
            "IND": "New Delhi", "JPN": "Tokyo", "DEU": "Berlin",
            "GBR": "London", "FRA": "Paris", "BRA": "Brasilia",
            "CAN": "Ottawa", "AUS": "Canberra", "KOR": "Seoul",
            "MEX": "Mexico City", "IDN": "Jakarta", "TUR": "Ankara",
            "SAU": "Riyadh", "IRN": "Tehran", "ISR": "Jerusalem",
            "UKR": "Kyiv", "POL": "Warsaw", "EGY": "Cairo",
            "NGA": "Abuja", "ZAF": "Pretoria", "ARG": "Buenos Aires",
            "VEN": "Caracas", "COL": "Bogota", "PER": "Lima",
            "CHL": "Santiago", "PAK": "Islamabad", "BGD": "Dhaka",
            "VNM": "Hanoi", "THA": "Bangkok", "MYS": "Kuala Lumpur",
            "SGP": "Singapore", "PHL": "Manila", "TWN": "Taipei",
            "HKG": "Hong Kong", "ARE": "Abu Dhabi", "QAT": "Doha",
            "KWT": "Kuwait City", "LBN": "Beirut", "SYR": "Damascus",
            "IRQ": "Baghdad", "YEM": "Sanaa", "JOR": "Amman",
            "PSE": "Ramallah", "AFG": "Kabul", "MMR": "Naypyidaw",
            "LKA": "Sri Jayawardenepura", "NPL": "Kathmandu", "ETH": "Addis Ababa",
            "KEN": "Nairobi", "TZA": "Dodoma", "UGA": "Kampala",
            "GHA": "Accra", "SEN": "Dakar", "CIV": "Yamoussoukro",
            "CMR": "Yaounde", "COD": "Kinshasa", "SDN": "Khartoum",
            "SSD": "Juba", "SOM": "Mogadishu", "ERI": "Asmara",
            "DJI": "Djibouti", "MDG": "Antananarivo", "MWI": "Lilongwe",
            "ZMB": "Lusaka", "ZWE": "Harare", "BWA": "Gaborone",
            "NAM": "Windhoek", "MAR": "Rabat", "DZA": "Algiers",
            "TUN": "Tunis", "LBY": "Tripoli", "NER": "Niamey",
            "MLI": "Bamako", "BFA": "Ouagadougou", "TCD": "NDjamena",
            "MRT": "Nouakchott", "GIN": "Conakry", "SLE": "Freetown",
            "LBR": "Monrovia", "GAB": "Libreville", "COG": "Brazzaville",
            "RWA": "Kigali", "BDI": "Gitega", "MOZ": "Maputo",
            "AGO": "Luanda", "SWZ": "Mbabane", "LSO": "Maseru",
            "ITA": "Rome", "ESP": "Madrid", "NLD": "Amsterdam",
            "BEL": "Brussels", "CHE": "Bern", "AUT": "Vienna",
            "NOR": "Oslo", "SWE": "Stockholm", "FIN": "Helsinki",
            "DNK": "Copenhagen", "GRC": "Athens", "PRT": "Lisbon",
            "IRL": "Dublin", "CZE": "Prague", "HUN": "Budapest",
            "ROU": "Bucharest", "BGR": "Sofia", "HRV": "Zagreb",
            "SVN": "Ljubljana", "SVK": "Bratislava", "LTU": "Vilnius",
            "LVA": "Riga", "EST": "Tallinn", "BLR": "Minsk",
            "MDA": "Chisinau", "GEO": "Tbilisi", "ARM": "Yerevan",
            "AZE": "Baku", "KAZ": "Astana", "UZB": "Tashkent",
            "TKM": "Ashgabat", "KGZ": "Bishkek", "TJK": "Dushanbe",
            "MNG": "Ulaanbaatar", "PRK": "Pyongyang",
        }
        return capitals.get(iso3)

    def _get_regime_score(self, iso3: str) -> Optional[float]:
        # V-Dem polyarchy index approximations (0-1)
        scores = {
            "USA": 0.85, "GBR": 0.88, "FRA": 0.82, "DEU": 0.89,
            "JPN": 0.84, "CAN": 0.92, "AUS": 0.90, "KOR": 0.78,
            "IND": 0.55, "BRA": 0.68, "POL": 0.62, "ZAF": 0.70,
            "CHN": 0.05, "RUS": 0.15, "IRN": 0.10, "SAU": 0.05,
            "PRK": 0.01, "TUR": 0.35, "HUN": 0.45, "VEN": 0.25,
            "EGY": 0.20, "ARE": 0.10, "SGP": 0.50, "VNM": 0.10,
            "PAK": 0.40, "BGD": 0.35, "NGA": 0.45, "ETH": 0.15,
        }
        return scores.get(iso3)

    def _get_military_personnel(self, iso3: str) -> Optional[int]:
        # Active military personnel (approximate)
        personnel = {
            "USA": 1390000, "CHN": 2035000, "RUS": 1014000,
            "IND": 1455000, "PRK": 1280000, "PAK": 654000,
            "KOR": 599000, "IRN": 610000, "EGY": 438500,
            "TUR": 355200, "VNM": 482000, "GBR": 150000,
            "FRA": 205000, "DEU": 184000, "JPN": 247000,
            "ISR": 170000, "SAU": 227000, "POL": 202000,
            "UKR": 200000, "SYR": 170000, "ISR": 170000,
        }
        return personnel.get(iso3)

    def _get_major_trade_partners(self, iso3: str) -> List[Dict]:
        # Simplified major trade partners
        partners = {
            "USA": [{"country": "CHN", "pct": 16.5}, {"country": "CAN", "pct": 15.2}, {"country": "MEX", "pct": 14.8}],
            "CHN": [{"country": "USA", "pct": 17.2}, {"country": "JPN", "pct": 6.8}, {"country": "KOR", "pct": 5.1}],
            "RUS": [{"country": "CHN", "pct": 18.5}, {"country": "NLD", "pct": 8.2}, {"country": "DEU", "pct": 6.1}],
            "IND": [{"country": "USA", "pct": 18.1}, {"country": "CHN", "pct": 15.3}, {"country": "UAE", "pct": 9.2}],
        }
        return partners.get(iso3, [])

    def _get_risk_indices(self, iso3: str) -> Dict[str, int]:
        # Fragile States Index, INFORM Risk, etc. (0-100, higher = worse)
        risks = {
            "USA": {"fragile_states": 35, "conflict_risk": 20, "inform_risk": 2.5},
            "CHN": {"fragile_states": 55, "conflict_risk": 45, "inform_risk": 3.8},
            "RUS": {"fragile_states": 70, "conflict_risk": 75, "inform_risk": 5.2},
            "UKR": {"fragile_states": 65, "conflict_risk": 90, "inform_risk": 6.1},
            "SYR": {"fragile_states": 110, "conflict_risk": 95, "inform_risk": 7.8},
            "AFG": {"fragile_states": 110, "conflict_risk": 98, "inform_risk": 8.1},
            "YEM": {"fragile_states": 112, "conflict_risk": 98, "inform_risk": 8.3},
            "SOM": {"fragile_states": 111, "conflict_risk": 95, "inform_risk": 8.0},
            "SDN": {"fragile_states": 105, "conflict_risk": 90, "inform_risk": 7.5},
            "SSD": {"fragile_states": 108, "conflict_risk": 95, "inform_risk": 7.9},
            "IRN": {"fragile_states": 80, "conflict_risk": 70, "inform_risk": 5.8},
            "VEN": {"fragile_states": 90, "conflict_risk": 60, "inform_risk": 6.2},
            "MMR": {"fragile_states": 100, "conflict_risk": 85, "inform_risk": 7.0},
            "HTI": {"fragile_states": 98, "conflict_risk": 75, "inform_risk": 6.8},
            "LBY": {"fragile_states": 95, "conflict_risk": 80, "inform_risk": 6.5},
            "COD": {"fragile_states": 102, "conflict_risk": 85, "inform_risk": 7.2},
        }
        return risks.get(iso3, {"fragile_states": 50, "conflict_risk": 30, "inform_risk": 3.5})

    def _get_leadership(self, iso3: str) -> Dict[str, str]:
        # Head of state/government as of 2024-2025
        leaders = {
            "USA": {"head_of_state": "Joe Biden", "head_of_government": "Joe Biden", "since": "2021-01-20"},
            "CHN": {"head_of_state": "Xi Jinping", "head_of_government": "Li Qiang", "since": "2013-03-14"},
            "RUS": {"head_of_state": "Vladimir Putin", "head_of_government": "Mikhail Mishustin", "since": "2012-05-07"},
            "UKR": {"head_of_state": "Volodymyr Zelenskyy", "head_of_government": "Denys Shmyhal", "since": "2019-05-20"},
            "ISR": {"head_of_state": "Isaac Herzog", "head_of_government": "Benjamin Netanyahu", "since": "2022-12-29"},
            "IRN": {"head_of_state": "Ali Khamenei", "head_of_government": "Masoud Pezeshkian", "since": "1989-06-04"},
            "SYR": {"head_of_state": "Bashar al-Assad", "head_of_government": "Mohammad Ghazi al-Jalali", "since": "2000-07-17"},
            "SAU": {"head_of_state": "Salman bin Abdulaziz", "head_of_government": "Mohammed bin Salman", "since": "2015-01-23"},
            "TUR": {"head_of_state": "Recep Tayyip Erdogan", "head_of_government": "Recep Tayyip Erdogan", "since": "2014-08-28"},
        }
        return leaders.get(iso3, {"head_of_state": "Unknown", "head_of_government": "Unknown", "since": "unknown"})

    def _get_conflict_history(self, iso3: str) -> Dict[str, Any]:
        # Major conflicts summary
        conflicts = {
            "SYR": {"current": "Syrian Civil War (2011-present)", "deaths_estimate": 500000, "active": True},
            "UKR": {"current": "Russo-Ukrainian War (2014-present)", "deaths_estimate": 400000, "active": True},
            "YEM": {"current": "Yemeni Civil War (2014-present)", "deaths_estimate": 377000, "active": True},
            "AFG": {"current": "Afghan Conflict (1978-present)", "deaths_estimate": 2000000, "active": True},
            "SOM": {"current": "Somali Civil War (1991-present)", "deaths_estimate": 500000, "active": True},
            "SDN": {"current": "Sudan Civil War (2023-present)", "deaths_estimate": 15000, "active": True},
            "SSD": {"current": "South Sudan Civil War (2013-2020)", "deaths_estimate": 400000, "active": False},
            "MMR": {"current": "Myanmar Civil War (2021-present)", "deaths_estimate": 50000, "active": True},
            "ISR": {"current": "Israel-Hamas War (2023-present)", "deaths_estimate": 40000, "active": True},
            "PSE": {"current": "Israel-Hamas War (2023-present)", "deaths_estimate": 40000, "active": True},
            "LBN": {"current": "Israel-Hezbollah Conflict (2023-present)", "deaths_estimate": 3000, "active": True},
            "IRQ": {"current": "Islamic State Insurgency (2014-2017)", "deaths_estimate": 67000, "active": False},
            "COD": {"current": "DRC Conflicts (1996-present)", "deaths_estimate": 6000000, "active": True},
            "COL": {"current": "Colombian Conflict (1964-present)", "deaths_estimate": 220000, "active": True},
        }
        return conflicts.get(iso3, {"current": "No major active conflict", "deaths_estimate": 0, "active": False})

    def _count_recent_coups(self, iso3: str) -> int:
        coup_countries = {"MMR": 2, "MLI": 2, "BFA": 2, "GIN": 1, "TCD": 1, "SDN": 2, "NIG": 1}
        return coup_countries.get(iso3, 0)

    def _count_recent_protests(self, iso3: str) -> int:
        # Protest intensity 2020-2024
        protests = {
            "IRN": 5, "HKG": 4, "BLR": 3, "RUS": 3, "CHN": 2, "USA": 3,
            "FRA": 4, "IND": 3, "BRA": 3, "PER": 3, "CHL": 3, "COL": 3,
            "ISR": 4, "LBN": 3, "IRQ": 3, "TUN": 3, "ALG": 3, "SUDAN": 3,
        }
        return protests.get(iso3, 0)

    def upsert_country(self, profile: Dict[str, Any]):
        with transaction() as conn:
            upsert("countries", profile, ["iso3"])

    def run_all(self, limit: Optional[int] = None):
        """Build profiles for all priority countries."""
        countries_to_process = PRIORITY_COUNTRIES
        if limit:
            countries_to_process = countries_to_process[:limit]

        print(f"[CountryIngester] Building profiles for {len(countries_to_process)} countries...")
        for iso3 in countries_to_process:
            name = next((v for k, v in COUNTRY_ISO3.items() if v == iso3), iso3)
            # Get proper name
            proper_names = {
                "USA": "United States", "CHN": "China", "RUS": "Russia",
                "IND": "India", "JPN": "Japan", "DEU": "Germany",
                "GBR": "United Kingdom", "FRA": "France", "BRA": "Brazil",
                "CAN": "Canada", "AUS": "Australia", "KOR": "South Korea",
                "MEX": "Mexico", "IDN": "Indonesia", "TUR": "Turkey",
                "SAU": "Saudi Arabia", "IRN": "Iran", "ISR": "Israel",
                "UKR": "Ukraine", "POL": "Poland", "EGY": "Egypt",
                "NGA": "Nigeria", "ZAF": "South Africa", "ARG": "Argentina",
                "VEN": "Venezuela", "COL": "Colombia", "PER": "Peru",
                "CHL": "Chile", "PAK": "Pakistan", "BGD": "Bangladesh",
                "VNM": "Vietnam", "THA": "Thailand", "MYS": "Malaysia",
                "SGP": "Singapore", "PHL": "Philippines", "TWN": "Taiwan",
                "HKG": "Hong Kong", "ARE": "United Arab Emirates", "QAT": "Qatar",
                "KWT": "Kuwait", "LBN": "Lebanon", "SYR": "Syria",
                "IRQ": "Iraq", "YEM": "Yemen", "JOR": "Jordan",
                "PSE": "Palestine", "AFG": "Afghanistan", "MMR": "Myanmar",
                "LKA": "Sri Lanka", "NPL": "Nepal", "ETH": "Ethiopia",
                "KEN": "Kenya", "TZA": "Tanzania", "UGA": "Uganda",
                "GHA": "Ghana", "SEN": "Senegal", "CIV": "Cote d'Ivoire",
                "CMR": "Cameroon", "COD": "DR Congo", "SDN": "Sudan",
                "SSD": "South Sudan", "SOM": "Somalia", "ERI": "Eritrea",
                "DJI": "Djibouti", "MDG": "Madagascar", "MWI": "Malawi",
                "ZMB": "Zambia", "ZWE": "Zimbabwe", "BWA": "Botswana",
                "NAM": "Namibia", "MAR": "Morocco", "DZA": "Algeria",
                "TUN": "Tunisia", "LBY": "Libya", "NER": "Niger",
                "MLI": "Mali", "BFA": "Burkina Faso", "TCD": "Chad",
                "MRT": "Mauritania", "GIN": "Guinea", "SLE": "Sierra Leone",
                "LBR": "Liberia", "GAB": "Gabon", "COG": "Congo",
                "RWA": "Rwanda", "BDI": "Burundi", "MOZ": "Mozambique",
                "AGO": "Angola", "SWZ": "Eswatini", "LSO": "Lesotho",
                "ITA": "Italy", "ESP": "Spain", "NLD": "Netherlands",
                "BEL": "Belgium", "CHE": "Switzerland", "AUT": "Austria",
                "NOR": "Norway", "SWE": "Sweden", "FIN": "Finland",
                "DNK": "Denmark", "GRC": "Greece", "PRT": "Portugal",
                "IRL": "Ireland", "CZE": "Czechia", "HUN": "Hungary",
                "ROU": "Romania", "BGR": "Bulgaria", "HRV": "Croatia",
                "SVN": "Slovenia", "SVK": "Slovakia", "LTU": "Lithuania",
                "LVA": "Latvia", "EST": "Estonia", "BLR": "Belarus",
                "MDA": "Moldova", "GEO": "Georgia", "ARM": "Armenia",
                "AZE": "Azerbaijan", "KAZ": "Kazakhstan", "UZB": "Uzbekistan",
                "TKM": "Turkmenistan", "KGZ": "Kyrgyzstan", "TJK": "Tajikistan",
                "MNG": "Mongolia", "PRK": "North Korea",
            }
            name = proper_names.get(iso3, iso3)
            profile = self.build_country_profile(iso3, name)
            self.upsert_country(profile)
            print(f"  {iso3} ({name}): pop={profile['population']}, GDP={profile['gdp_usd']}")
        print("[CountryIngester] Done")


def main():
    ingester = CountryIngester()
    ingester.run_all()


if __name__ == "__main__":
    main()