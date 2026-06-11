"""
City profile ingestion.
Major cities with population, strategic value, infrastructure.
"""
import json
from typing import Dict, Any, List, Optional
from backend.db import get_conn, insert, upsert, transaction

# Major cities with detailed profiles
CITY_PROFILES = [
    # Format: name, country, lat, lng, pop, metro_pop, strategic_value, infrastructure
    # USA
    {"name": "New York", "country": "USA", "lat": 40.71, "lng": -74.01, "pop": 8800000, "metro": 19800000,
     "strategic": "financial", "infra": {"airports": ["JFK", "LGA", "EWR"], "ports": ["NY/NJ"], "bases": [], "fiber": "major hub"}},
    {"name": "Washington DC", "country": "USA", "lat": 38.91, "lng": -77.04, "pop": 670000, "metro": 6300000,
     "strategic": "capital", "infra": {"airports": ["DCA", "IAD", "BWI"], "ports": [], "bases": ["Pentagon", "Fort Belvoir"], "fiber": "major hub"}},
    {"name": "Los Angeles", "country": "USA", "lat": 34.05, "lng": -118.24, "pop": 3900000, "metro": 13200000,
     "strategic": "port", "infra": {"airports": ["LAX"], "ports": ["LA/Long Beach"], "bases": ["Camp Pendleton", "Edwards AFB"], "fiber": "major hub"}},
    {"name": "Chicago", "country": "USA", "lat": 41.88, "lng": -87.63, "pop": 2700000, "metro": 9500000,
     "strategic": "industrial", "infra": {"airports": ["ORD", "MDW"], "ports": ["Great Lakes"], "bases": ["Great Lakes Naval"], "fiber": "major hub"}},
    {"name": "San Francisco", "country": "USA", "lat": 37.77, "lng": -122.42, "pop": 870000, "metro": 4700000,
     "strategic": "tech", "infra": {"airports": ["SFO", "OAK", "SJC"], "ports": ["Oakland"], "bases": [], "fiber": "major hub"}},
    {"name": "Houston", "country": "USA", "lat": 29.76, "lng": -95.37, "pop": 2300000, "metro": 7100000,
     "strategic": "energy", "infra": {"airports": ["IAH", "HOU"], "ports": ["Houston"], "bases": [], "fiber": "major hub"}},
    {"name": "Norfolk", "country": "USA", "lat": 36.85, "lng": -76.29, "pop": 240000, "metro": 1700000,
     "strategic": "military", "infra": {"airports": ["ORF"], "ports": ["Norfolk Naval"], "bases": ["Naval Station Norfolk"], "fiber": "regional"}},

    # China
    {"name": "Beijing", "country": "CHN", "lat": 39.90, "lng": 116.41, "pop": 21500000, "metro": 21500000,
     "strategic": "capital", "infra": {"airports": ["PEK", "PKX"], "ports": [], "bases": ["PLA HQ"], "fiber": "major hub"}},
    {"name": "Shanghai", "country": "CHN", "lat": 31.23, "lng": 121.47, "pop": 24900000, "metro": 24900000,
     "strategic": "financial", "infra": {"airports": ["PVG", "SHA"], "ports": ["Shanghai"], "bases": [], "fiber": "major hub"}},
    {"name": "Shenzhen", "country": "CHN", "lat": 22.54, "lng": 114.06, "pop": 17500000, "metro": 17500000,
     "strategic": "tech", "infra": {"airports": ["SZX"], "ports": ["Yantian", "Shekou"], "bases": [], "fiber": "major hub"}},
    {"name": "Guangzhou", "country": "CHN", "lat": 23.13, "lng": 113.26, "pop": 15300000, "metro": 65600000,
     "strategic": "industrial", "infra": {"airports": ["CAN"], "ports": ["Guangzhou"], "bases": [], "fiber": "major hub"}},

    # Russia
    {"name": "Moscow", "country": "RUS", "lat": 55.76, "lng": 37.62, "pop": 12500000, "metro": 17100000,
     "strategic": "capital", "infra": {"airports": ["SVO", "DME", "VKO"], "ports": [], "bases": ["Kremlin", "General Staff"], "fiber": "major hub"}},
    {"name": "St Petersburg", "country": "RUS", "lat": 59.93, "lng": 30.34, "pop": 5380000, "metro": 5380000,
     "strategic": "port", "infra": {"airports": ["LED"], "ports": ["St Petersburg"], "bases": ["Baltic Fleet"], "fiber": "major hub"}},

    # Europe
    {"name": "London", "country": "GBR", "lat": 51.51, "lng": -0.13, "pop": 9000000, "metro": 14000000,
     "strategic": "financial", "infra": {"airports": ["LHR", "LGW", "STN"], "ports": ["London Gateway"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Paris", "country": "FRA", "lat": 48.86, "lng": 2.35, "pop": 2160000, "metro": 12500000,
     "strategic": "capital", "infra": {"airports": ["CDG", "ORY"], "ports": [], "bases": ["Elysee"], "fiber": "major hub"}},
    {"name": "Berlin", "country": "DEU", "lat": 52.52, "lng": 13.41, "pop": 3670000, "metro": 6100000,
     "strategic": "capital", "infra": {"airports": ["BER"], "ports": [], "bases": ["Bundeswehr HQ"], "fiber": "major hub"}},
    {"name": "Brussels", "country": "BEL", "lat": 50.85, "lng": 4.35, "pop": 1200000, "metro": 2500000,
     "strategic": "capital", "infra": {"airports": ["BRU"], "ports": [], "bases": ["NATO HQ", "EU HQ"], "fiber": "major hub"}},
    {"name": "Kyiv", "country": "UKR", "lat": 50.45, "lng": 30.52, "pop": 2950000, "metro": 3300000,
     "strategic": "capital", "infra": {"airports": ["KBP", "IEV"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Istanbul", "country": "TUR", "lat": 41.01, "lng": 28.98, "pop": 15500000, "metro": 15500000,
     "strategic": "strategic", "infra": {"airports": ["IST", "SAW"], "ports": ["Haydarpasa", "Ambarli"], "bases": ["NATO LANDCOM"], "fiber": "major hub"}},

    # Middle East
    {"name": "Tehran", "country": "IRN", "lat": 35.69, "lng": 51.39, "pop": 9400000, "metro": 16000000,
     "strategic": "capital", "infra": {"airports": ["IKA", "THR"], "ports": [], "bases": ["IRGC HQ"], "fiber": "major hub"}},
    {"name": "Baghdad", "country": "IRQ", "lat": 33.31, "lng": 44.37, "pop": 7180000, "metro": 7180000,
     "strategic": "capital", "infra": {"airports": ["BGW"], "ports": [], "bases": ["Green Zone"], "fiber": "regional"}},
    {"name": "Riyadh", "country": "SAU", "lat": 24.71, "lng": 46.68, "pop": 7680000, "metro": 7680000,
     "strategic": "capital", "infra": {"airports": ["RUH"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Jeddah", "country": "SAU", "lat": 21.49, "lng": 39.24, "pop": 4780000, "metro": 4780000,
     "strategic": "port", "infra": {"airports": ["JED"], "ports": ["Jeddah Islamic Port"], "bases": [], "fiber": "major hub"}},
    {"name": "Dubai", "country": "ARE", "lat": 25.20, "lng": 55.27, "pop": 3500000, "metro": 3500000,
     "strategic": "financial", "infra": {"airports": ["DXB", "DWC"], "ports": ["Jebel Ali"], "bases": [], "fiber": "major hub"}},
    {"name": "Abu Dhabi", "country": "ARE", "lat": 24.45, "lng": 54.38, "pop": 1480000, "metro": 1480000,
     "strategic": "capital", "infra": {"airports": ["AUH"], "ports": ["Khalifa Port"], "bases": [], "fiber": "major hub"}},
    {"name": "Tel Aviv", "country": "ISR", "lat": 32.08, "lng": 34.78, "pop": 460000, "metro": 3850000,
     "strategic": "financial", "infra": {"airports": ["TLV"], "ports": [], "bases": ["IDF HQ"], "fiber": "major hub"}},
    {"name": "Jerusalem", "country": "ISR", "lat": 31.78, "lng": 35.22, "pop": 930000, "metro": 1250000,
     "strategic": "capital", "infra": {"airports": [], "ports": [], "bases": ["Knesset", "MoD"], "fiber": "major hub"}},
    {"name": "Beirut", "country": "LBN", "lat": 33.89, "lng": 35.50, "pop": 2400000, "metro": 2400000,
     "strategic": "capital", "infra": {"airports": ["BEY"], "ports": ["Beirut"], "bases": [], "fiber": "regional"}},
    {"name": "Damascus", "country": "SYR", "lat": 33.51, "lng": 36.31, "pop": 2080000, "metro": 2080000,
     "strategic": "capital", "infra": {"airports": ["DAM"], "ports": [], "bases": ["MoD"], "fiber": "regional"}},
    {"name": "Sanaa", "country": "YEM", "lat": 15.37, "lng": 44.19, "pop": 3100000, "metro": 3100000,
     "strategic": "capital", "infra": {"airports": ["SAH"], "ports": [], "bases": [], "fiber": "limited"}},
    {"name": "Aden", "country": "YEM", "lat": 12.78, "lng": 45.02, "pop": 1080000, "metro": 1080000,
     "strategic": "port", "infra": {"airports": ["ADE"], "ports": ["Aden"], "bases": [], "fiber": "limited"}},

    # South Asia
    {"name": "New Delhi", "country": "IND", "lat": 28.61, "lng": 77.21, "pop": 32900000, "metro": 32900000,
     "strategic": "capital", "infra": {"airports": ["DEL"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Mumbai", "country": "IND", "lat": 19.08, "lng": 72.88, "pop": 21000000, "metro": 21000000,
     "strategic": "financial", "infra": {"airports": ["BOM"], "ports": ["JNPT", "Mumbai"], "bases": ["Western Naval"], "fiber": "major hub"}},
    {"name": "Karachi", "country": "PAK", "lat": 24.86, "lng": 67.01, "pop": 16000000, "metro": 16000000,
     "strategic": "port", "infra": {"airports": ["KHI"], "ports": ["Karachi", "Qasim"], "bases": ["Naval HQ"], "fiber": "major hub"}},
    {"name": "Islamabad", "country": "PAK", "lat": 33.68, "lng": 73.05, "pop": 1200000, "metro": 4100000,
     "strategic": "capital", "infra": {"airports": ["ISB"], "ports": [], "bases": ["GHQ Rawalpindi"], "fiber": "major hub"}},
    {"name": "Dhaka", "country": "BGD", "lat": 23.81, "lng": 90.41, "pop": 21000000, "metro": 21000000,
     "strategic": "capital", "infra": {"airports": ["DAC"], "ports": ["Chittagong"], "bases": ["MoD"], "fiber": "major hub"}},

    # East Asia
    {"name": "Tokyo", "country": "JPN", "lat": 35.68, "lng": 139.69, "pop": 14000000, "metro": 37400000,
     "strategic": "capital", "infra": {"airports": ["HND", "NRT"], "ports": ["Tokyo", "Yokohama"], "bases": ["MoD", "Yokosuka"], "fiber": "major hub"}},
    {"name": "Seoul", "country": "KOR", "lat": 37.57, "lng": 126.98, "pop": 9770000, "metro": 25600000,
     "strategic": "capital", "infra": {"airports": ["ICN", "GMP"], "ports": ["Incheon", "Busan"], "bases": ["MoD", "USFK"], "fiber": "major hub"}},
    {"name": "Pyongyang", "country": "PRK", "lat": 39.03, "lng": 125.75, "pop": 3070000, "metro": 3070000,
     "strategic": "capital", "infra": {"airports": ["FNJ"], "ports": [], "bases": ["KPA HQ"], "fiber": "limited"}},
    {"name": "Taipei", "country": "TWN", "lat": 25.03, "lng": 121.56, "pop": 2700000, "metro": 7000000,
     "strategic": "capital", "infra": {"airports": ["TPE", "TSA"], "ports": ["Keelung", "Taichung"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Hong Kong", "country": "HKG", "lat": 22.32, "lng": 114.17, "pop": 7500000, "metro": 7500000,
     "strategic": "financial", "infra": {"airports": ["HKG"], "ports": ["Hong Kong"], "bases": ["PLA Garrison"], "fiber": "major hub"}},

    # Southeast Asia
    {"name": "Singapore", "country": "SGP", "lat": 1.35, "lng": 103.82, "pop": 5700000, "metro": 5700000,
     "strategic": "strategic", "infra": {"airports": ["SIN"], "ports": ["Singapore"], "bases": ["US Naval", "Changi"], "fiber": "major hub"}},
    {"name": "Jakarta", "country": "IDN", "lat": -6.21, "lng": 106.85, "pop": 10800000, "metro": 33000000,
     "strategic": "capital", "infra": {"airports": ["CGK", "HLP"], "ports": ["Tanjung Priok"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Manila", "country": "PHL", "lat": 14.60, "lng": 120.98, "pop": 1800000, "metro": 14000000,
     "strategic": "capital", "infra": {"airports": ["MNL"], "ports": ["Manila"], "bases": ["MoD", "Subic"], "fiber": "major hub"}},
    {"name": "Bangkok", "country": "THA", "lat": 13.75, "lng": 100.50, "pop": 10500000, "metro": 17000000,
     "strategic": "capital", "infra": {"airports": ["BKK", "DMK"], "ports": ["Laem Chabang"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Ho Chi Minh City", "country": "VNM", "lat": 10.82, "lng": 106.63, "pop": 9000000, "metro": 13000000,
     "strategic": "financial", "infra": {"airports": ["SGN"], "ports": ["Cai Mep"], "bases": [], "fiber": "major hub"}},
    {"name": "Hanoi", "country": "VNM", "lat": 21.03, "lng": 105.85, "pop": 8250000, "metro": 17000000,
     "strategic": "capital", "infra": {"airports": ["HAN"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},

    # Africa
    {"name": "Cairo", "country": "EGY", "lat": 30.04, "lng": 31.24, "pop": 10200000, "metro": 21000000,
     "strategic": "capital", "infra": {"airports": ["CAI"], "ports": ["Sokhna", "Alexandria"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Lagos", "country": "NGA", "lat": 6.52, "lng": 3.38, "pop": 15400000, "metro": 21000000,
     "strategic": "financial", "infra": {"airports": ["LOS"], "ports": ["Lagos"], "bases": [], "fiber": "major hub"}},
    {"name": "Kinshasa", "country": "COD", "lat": -4.32, "lng": 15.32, "pop": 15600000, "metro": 15600000,
     "strategic": "capital", "infra": {"airports": ["FIH"], "ports": [], "bases": [], "fiber": "limited"}},
    {"name": "Johannesburg", "country": "ZAF", "lat": -26.20, "lng": 28.05, "pop": 5600000, "metro": 14000000,
     "strategic": "financial", "infra": {"airports": ["JNB"], "ports": [], "bases": [], "fiber": "major hub"}},
    {"name": "Pretoria", "country": "ZAF", "lat": -25.75, "lng": 28.23, "pop": 740000, "metro": 3000000,
     "strategic": "capital", "infra": {"airports": [], "ports": [], "bases": ["Union Buildings"], "fiber": "major hub"}},
    {"name": "Nairobi", "country": "KEN", "lat": -1.29, "lng": 36.82, "pop": 5100000, "metro": 6500000,
     "strategic": "capital", "infra": {"airports": ["NBO", "WIL"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Addis Ababa", "country": "ETH", "lat": 9.03, "lng": 38.74, "pop": 5200000, "metro": 5200000,
     "strategic": "capital", "infra": {"airports": ["ADD"], "ports": [], "bases": ["AU HQ", "MoD"], "fiber": "major hub"}},
    {"name": "Khartoum", "country": "SDN", "lat": 15.50, "lng": 32.56, "pop": 6200000, "metro": 6200000,
     "strategic": "capital", "infra": {"airports": ["KRT"], "ports": [], "bases": ["MoD"], "fiber": "regional"}},
    {"name": "Mogadishu", "country": "SOM", "lat": 2.04, "lng": 45.34, "pop": 2500000, "metro": 2500000,
     "strategic": "capital", "infra": {"airports": ["MGQ"], "ports": ["Mogadishu"], "bases": [], "fiber": "limited"}},
    {"name": "Casablanca", "country": "MAR", "lat": 33.57, "lng": -7.59, "pop": 3700000, "metro": 4270000,
     "strategic": "financial", "infra": {"airports": ["CMN"], "ports": ["Casablanca"], "bases": [], "fiber": "major hub"}},
    {"name": "Algiers", "country": "DZA", "lat": 36.75, "lng": 3.05, "pop": 2900000, "metro": 4500000,
     "strategic": "capital", "infra": {"airports": ["ALG"], "ports": ["Algiers"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Tripoli", "country": "LBY", "lat": 32.89, "lng": 13.19, "pop": 1300000, "metro": 1300000,
     "strategic": "capital", "infra": {"airports": ["TIP", "MJI"], "ports": ["Tripoli"], "bases": [], "fiber": "limited"}},

    # Latin America
    {"name": "Mexico City", "country": "MEX", "lat": 19.43, "lng": -99.13, "pop": 9200000, "metro": 21000000,
     "strategic": "capital", "infra": {"airports": ["MEX", "NLU"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "São Paulo", "country": "BRA", "lat": -23.55, "lng": -46.63, "pop": 12300000, "metro": 22000000,
     "strategic": "financial", "infra": {"airports": ["GRU", "CGH"], "ports": ["Santos"], "bases": [], "fiber": "major hub"}},
    {"name": "Buenos Aires", "country": "ARG", "lat": -34.60, "lng": -58.38, "pop": 3100000, "metro": 15000000,
     "strategic": "capital", "infra": {"airports": ["EZE", "AEP"], "ports": ["Buenos Aires"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Bogota", "country": "COL", "lat": 4.71, "lng": -74.07, "pop": 8100000, "metro": 11200000,
     "strategic": "capital", "infra": {"airports": ["BOG"], "ports": [], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Lima", "country": "PER", "lat": -12.05, "lng": -77.04, "pop": 11000000, "metro": 11000000,
     "strategic": "capital", "infra": {"airports": ["LIM"], "ports": ["Callao"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Santiago", "country": "CHL", "lat": -33.45, "lng": -70.66, "pop": 6800000, "metro": 6800000,
     "strategic": "capital", "infra": {"airports": ["SCL"], "ports": ["San Antonio", "Valparaiso"], "bases": ["MoD"], "fiber": "major hub"}},
    {"name": "Caracas", "country": "VEN", "lat": 10.48, "lng": -66.87, "pop": 2900000, "metro": 2900000,
     "strategic": "capital", "infra": {"airports": ["CCS"], "ports": ["La Guaira"], "bases": ["MoD"], "fiber": "regional"}},
]


def upsert_cities():
    """Insert or update all city profiles."""
    from backend.db import query_one

    success = 0
    errors = 0
    for city in CITY_PROFILES:
        # Skip if country doesn't exist in DB (would cause FK error)
        if not query_one("SELECT 1 FROM countries WHERE iso3 = ?", (city["country"],)):
            errors += 1
            continue
        try:
            upsert("cities", {
                "name": city["name"],
                "country_code": city["country"],
                "lat": city["lat"],
                "lng": city["lng"],
                "population": city["pop"],
                "metro_population": city["metro"],
                "strategic_value": city["strategic"],
                "infrastructure_json": json.dumps(city["infra"]),
                "recent_events_count": 0,
                "updated_at": "CURRENT_TIMESTAMP"
            }, ["name", "country_code"])
            success += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"[Cities] Error upserting {city['name']}: {e}")
    print(f"[Cities] Upserted {success}/{len(CITY_PROFILES)} city profiles ({errors} skipped)")


if __name__ == "__main__":
    upsert_cities()