# valuation.py
# NOTE: All Korean text uses unicode escapes (\uXXXX) to survive copy-paste.
import re

TIER_TRIP_DAYS = {
    "domestic": (2, 7), "jp_near": (2, 7), "jp_mid": (3, 7),
    "cn_near": (2, 7), "cn_mid": (3, 7), "tw_hk": (3, 7),
    "sea_near": (4, 9), "sea_mid": (4, 10), "sea_far": (5, 12),
    "mongolia": (4, 8), "guam": (4, 8), "oceania": (7, 14),
    "europe": (7, 14), "namerica": (7, 14), "longhaul": (7, 14),
}
DEFAULT_TRIP_DAYS = (3, 7)

TIER_BASELINE = {
    "domestic": 45000, "jp_near": 150000, "jp_mid": 200000,
    "cn_near": 150000, "cn_mid": 220000, "tw_hk": 200000,
    "sea_near": 250000, "sea_mid": 260000, "sea_far": 420000,
    "mongolia": 350000, "guam": 350000, "oceania": 800000,
    "europe": 900000, "namerica": 1000000, "longhaul": 1000000,
}

AIRPORT_TIER = {
    "CJU": "domestic", "PUS": "domestic", "USN": "domestic", "RSU": "domestic",
    "KWJ": "domestic", "TAE": "domestic", "FUK": "jp_near", "KIX": "jp_near",
    "KKJ": "jp_near", "HSG": "jp_near", "YGJ": "jp_near", "TAK": "jp_near",
    "OIT": "jp_near", "KMJ": "jp_near", "KOJ": "jp_near", "HIJ": "jp_near",
    "UBJ": "jp_near", "IZO": "jp_near", "NRT": "jp_mid", "HND": "jp_mid",
    "NGO": "jp_mid", "CTS": "jp_mid", "KMQ": "jp_mid", "MYJ": "jp_mid",
    "KMI": "jp_mid", "NGS": "jp_mid", "OKA": "jp_mid", "SDJ": "jp_mid",
    "TOY": "jp_mid", "AOJ": "jp_mid", "DLC": "cn_near", "TAO": "cn_near",
    "YNJ": "cn_near", "SHE": "cn_near", "PVG": "cn_mid", "PEK": "cn_mid",
    "PKX": "cn_mid", "CAN": "cn_mid", "XIY": "cn_mid", "CTU": "cn_mid",
    "TPE": "tw_hk", "RMQ": "tw_hk", "KHH": "tw_hk", "HKG": "tw_hk",
    "MFM": "tw_hk", "DAD": "sea_near", "CXR": "sea_near", "HAN": "sea_near",
    "SGN": "sea_near", "PQC": "sea_near", "BKK": "sea_near", "DMK": "sea_near",
    "CRK": "sea_near", "CEB": "sea_near", "MNL": "sea_near", "KLO": "sea_near",
    "CNX": "sea_near", "DPS": "sea_far", "SIN": "sea_far", "BKI": "sea_mid",
    "KUL": "sea_mid", "BWN": "sea_mid", "HKT": "sea_mid", "PEN": "sea_mid",
    "ULN": "mongolia", "GUM": "guam", "SPN": "guam", "BNE": "oceania",
    "SYD": "oceania", "MEL": "oceania", "AKL": "oceania", "WAW": "europe",
    "WRO": "europe", "KRK": "europe", "GDN": "europe", "FCO": "europe",
    "MXP": "europe", "VCE": "europe", "NAP": "europe", "CDG": "europe",
    "ORY": "europe", "LHR": "europe", "LGW": "europe", "FRA": "europe",
    "MUC": "europe", "BER": "europe", "AMS": "europe", "BCN": "europe",
    "MAD": "europe", "LIS": "europe", "OPO": "europe", "VIE": "europe",
    "PRG": "europe", "BUD": "europe", "ZRH": "europe", "IST": "europe",
    "ATH": "europe", "CPH": "europe", "ARN": "europe", "HEL": "europe",
    "OSL": "europe", "DUB": "europe", "BRU": "europe", "LAX": "namerica",
    "SFO": "namerica", "SEA": "namerica", "JFK": "namerica", "EWR": "namerica",
    "ORD": "namerica", "IAD": "namerica", "BOS": "namerica", "YVR": "namerica",
    "YYZ": "namerica", "HNL": "namerica", "LAS": "namerica",
}

CITY_NAME_TIER = {
    "\uAD11\uC800\uC6B0\uC2DC": "cn_mid", "\uBCA0\uC774\uC9D5\uC2DC": "cn_mid",
    "\uC0C1\uD558\uC774": "cn_mid", "\uC120\uC804\uC2DC": "cn_mid",
    "\uC2DC\uC548\uC2DC": "cn_mid", "\uC7A5\uC790\uC81C\uC2DC": "cn_mid",
    "\uCCAD\uB450\uC2DC": "cn_mid", "\uB2E4\uB80C\uC2DC": "cn_near",
    "\uB2E4\uB844\uC2DC": "cn_near", "\uC120\uC591\uC2DC": "cn_near",
    "\uC60C\uC9C0\uC2DC": "cn_near", "\uCE6D\uB2E4\uC624\uC2DC": "cn_near",
    "\uD558\uC5BC\uBE48\uC2DC": "cn_near", "\uB098\uD3F4\uB9AC": "europe",
    "\uB2C8\uC2A4": "europe", "\uB354\uBE14\uB9B0": "europe",
    "\uB4A4\uC140\uB3C4\uB974\uD504": "europe", "\uB7F0\uB358": "europe",
    "\uB85C\uB9C8": "europe", "\uB958\uBE14\uB7B4\uB098": "europe",
    "\uB9AC\uAC00": "europe", "\uB9AC\uC2A4\uBCF8": "europe",
    "\uB9C8\uB4DC\uB9AC\uB4DC": "europe", "\uB9D0\uB77C\uAC00": "europe",
    "\uB9E8\uCCB4\uC2A4\uD130": "europe", "\uBB8C\uD5E8": "europe",
    "\uBC00\uB77C\uB178": "europe", "\uBC14\uB974\uC0E4\uBC14": "europe",
    "\uBC14\uB974\uC140\uB85C\uB098": "europe", "\uBCA0\uB124\uCE58\uC544": "europe",
    "\uBCA0\uB97C\uB9B0": "europe", "\uBCA0\uC624\uADF8\uB77C\uB4DC": "europe",
    "\uBD80\uB2E4\uD398\uC2A4\uD2B8": "europe", "\uBD80\uCFE0\uB808\uC288\uD2F0": "europe",
    "\uBE0C\uB85C\uCE20\uC640\uD504": "europe", "\uBE0C\uB93C\uC140": "europe",
    "\uBE44\uC5D4\uB098": "europe", "\uBE4C\uB274\uC2A4": "europe",
    "\uC18C\uD53C\uC544": "europe", "\uC2A4\uD1A1\uD640\uB984": "europe",
    "\uC544\uD14C\uB124": "europe", "\uC554\uC2A4\uD14C\uB974\uB2F4": "europe",
    "\uC5D0\uB4E0\uBC84\uB7EC": "europe", "\uC624\uC2AC\uB85C": "europe",
    "\uC774\uC2A4\uD0C4\uBD88": "europe", "\uC790\uADF8\uB808\uBE0C": "europe",
    "\uCDE8\uB9AC\uD788": "europe", "\uCF54\uD39C\uD558\uAC90": "europe",
    "\uD06C\uB77C\uCFE0\uD504": "europe", "\uD0C8\uB9B0": "europe",
    "\uD30C\uB9AC": "europe", "\uD3EC\uB974\uD22C": "europe",
    "\uD504\uB77C\uD558": "europe", "\uD504\uB791\uD06C\uD478\uB974\uD2B8": "europe",
    "\uD53C\uB80C\uCCB4": "europe", "\uD568\uBD80\uB974\uD06C": "europe",
    "\uD5EC\uC2F1\uD0A4": "europe", "\uAD0C": "guam",
    "\uC0AC\uC774\uD310": "guam", "\uACE0\uB9C8\uC4F0\uC2DC": "jp_mid",
    "\uB098\uAC00\uC0AC\uD0A4\uC2DC": "jp_mid", "\uB098\uACE0\uC57C": "jp_mid",
    "\uB098\uACE0\uC57C\uC2DC": "jp_mid", "\uB3C4\uC57C\uB9C8\uC2DC": "jp_mid",
    "\uB3C4\uCFC4": "jp_mid", "\uB3C4\uCFC4\uB3C4": "jp_mid",
    "\uBBF8\uC57C\uC790\uD0A4\uC2DC": "jp_mid", "\uC0BF\uD3EC\uB85C": "jp_mid",
    "\uC0BF\uD3EC\uB85C\uC2DC": "jp_mid", "\uC13C\uB2E4\uC774\uC2DC": "jp_mid",
    "\uC2DC\uC988\uC624\uCE74\uC2DC": "jp_mid", "\uC544\uC624\uBAA8\uB9AC\uC2DC": "jp_mid",
    "\uC624\uD0A4\uB098\uC640": "jp_mid", "\uC624\uD0A4\uB098\uC640\uC2DC": "jp_mid",
    "\uAC00\uACE0\uC2DC\uB9C8\uC2DC": "jp_near", "\uAD6C\uB9C8\uBAA8\uD1A0\uC2DC": "jp_near",
    "\uAE30\uD0C0\uD050\uC288\uC2DC": "jp_near", "\uB2E4\uCE74\uB9C8\uC4F0\uC2DC": "jp_near",
    "\uB9C8\uC4F0\uC57C\uB9C8\uC2DC": "jp_near", "\uC0AC\uAC00\uC2DC": "jp_near",
    "\uC624\uC0AC\uCE74": "jp_near", "\uC624\uC0AC\uCE74\uC2DC": "jp_near",
    "\uC624\uC774\uD0C0\uC2DC": "jp_near", "\uC694\uB098\uACE0\uC2DC": "jp_near",
    "\uC6B0\uBCA0\uC2DC": "jp_near", "\uC774\uC988\uBAA8\uC2DC": "jp_near",
    "\uD6C4\uCFE0\uC624\uCE74": "jp_near", "\uD6C4\uCFE0\uC624\uCE74\uC2DC": "jp_near",
    "\uD788\uB85C\uC2DC\uB9C8\uC2DC": "jp_near", "\uC6B8\uB780\uBC14\uD1A0\uB974": "mongolia",
    "\uB274\uC695": "namerica", "\uB308\uB7EC\uC2A4": "namerica",
    "\uB77C\uC2A4\uBCA0\uC774\uAC70\uC2A4": "namerica", "\uB85C\uC2A4\uC564\uC824\uB808\uC2A4": "namerica",
    "\uBC34\uCFE0\uBC84": "namerica", "\uC0CC\uD504\uB780\uC2DC\uC2A4\uCF54": "namerica",
    "\uC2DC\uC560\uD2C0": "namerica", "\uC2DC\uCE74\uACE0": "namerica",
    "\uC560\uD2C0\uB79C\uD0C0": "namerica", "\uD1A0\uB860\uD1A0": "namerica",
    "\uD638\uB180\uB8F0\uB8E8": "namerica", "\uBA5C\uBC84\uB978": "oceania",
    "\uBE0C\uB9AC\uC988\uBC88": "oceania", "\uC2DC\uB4DC\uB2C8": "oceania",
    "\uC624\uD074\uB79C\uB4DC": "oceania", "\uCF00\uC5B8\uC2A4": "oceania",
    "\uD06C\uB77C\uC774\uC2A4\uD2B8\uCC98\uCE58": "oceania", "\uD37C\uC2A4": "oceania",
    "\uB374\uD30C\uC0AC\uB974": "sea_far", "\uBC1C\uB9AC": "sea_far",
    "\uC2F1\uAC00\uD3EC\uB974": "sea_far", "\uB791\uCE74\uC704": "sea_mid",
    "\uBC18\uB2E4\uB974\uC138\uB9AC\uBCA0\uAC00\uC644": "sea_mid", "\uC870\uD638\uB974\uBC14\uB8E8": "sea_mid",
    "\uCF54\uD0C0\uD0A4\uB098\uBC1C\uB8E8": "sea_mid", "\uCFE0\uC54C\uB77C\uB8F8\uD478\uB974": "sea_mid",
    "\uD398\uB0AD": "sea_mid", "\uD478\uCF13": "sea_mid",
    "\uB098\uD2B8\uB791": "sea_near", "\uB2E4\uB0AD": "sea_near",
    "\uB2EC\uB78F": "sea_near", "\uB9C8\uB2D0\uB77C": "sea_near",
    "\uBC29\uCF55": "sea_near", "\uBCF4\uB77C\uCE74\uC774": "sea_near",
    "\uBE44\uC5D4\uD2F0\uC548": "sea_near", "\uC138\uBD80": "sea_near",
    "\uC138\uBD80\uC2DC": "sea_near", "\uC2DC\uC5E0\uB9BD": "sea_near",
    "\uCE58\uC559\uB9C8\uC774": "sea_near", "\uCE7C\uB9AC\uBCF4": "sea_near",
    "\uD074\uB77D": "sea_near", "\uD478\uAFB8\uC625": "sea_near",
    "\uD504\uB188\uD39C": "sea_near", "\uD558\uB178\uC774": "sea_near",
    "\uD558\uC774\uD401": "sea_near", "\uD638\uCE58\uBBFC\uC2DC": "sea_near",
    "\uAC00\uC624\uC29D": "tw_hk", "\uAC00\uC624\uC29D\uC2DC": "tw_hk",
    "\uB9C8\uCE74\uC624": "tw_hk", "\uD0C0\uC774\uBCA0\uC774": "tw_hk",
    "\uD0C0\uC774\uC911": "tw_hk", "\uD0C0\uC774\uC911\uC2DC": "tw_hk",
    "\uD64D\uCF69": "tw_hk",
}

COUNTRY_TIER = {
    "\uC911\uAD6D": "cn_mid", "\uB300\uD55C\uBBFC\uAD6D": "domestic",
    "\uADF8\uB9AC\uC2A4": "europe", "\uB124\uB35C\uB780\uB4DC": "europe",
    "\uB178\uB974\uC6E8\uC774": "europe", "\uB374\uB9C8\uD06C": "europe",
    "\uB3C5\uC77C": "europe", "\uBCA8\uAE30\uC5D0": "europe",
    "\uC2A4\uC6E8\uB374": "europe", "\uC2A4\uC704\uC2A4": "europe",
    "\uC2A4\uD398\uC778": "europe", "\uC544\uC77C\uB79C\uB4DC": "europe",
    "\uC601\uAD6D": "europe", "\uC624\uC2A4\uD2B8\uB9AC\uC544": "europe",
    "\uC774\uD0C8\uB9AC\uC544": "europe", "\uCCB4\uCF54": "europe",
    "\uD130\uD0A4": "europe", "\uD280\uB974\uD0A4\uC608": "europe",
    "\uD3EC\uB974\uD22C\uAC08": "europe", "\uD3F4\uB780\uB4DC": "europe",
    "\uD504\uB791\uC2A4": "europe", "\uD540\uB780\uB4DC": "europe",
    "\uD5DD\uAC00\uB9AC": "europe", "\uC77C\uBCF8": "jp_mid",
    "\uBABD\uACE8": "mongolia", "\uBBF8\uAD6D": "namerica",
    "\uCE90\uB098\uB2E4": "namerica", "\uB274\uC9C8\uB79C\uB4DC": "oceania",
    "\uC624\uC2A4\uD2B8\uB808\uC77C\uB9AC\uC544": "oceania", "\uB9D0\uB808\uC774\uC2DC\uC544": "sea_far",
    "\uBE0C\uB8E8\uB098\uC774": "sea_far", "\uC2F1\uAC00\uD3EC\uB974": "sea_far",
    "\uC778\uB3C4\uB124\uC2DC\uC544": "sea_far", "\uB77C\uC624\uC2A4": "sea_near",
    "\uBCA0\uD2B8\uB0A8": "sea_near", "\uCE84\uBCF4\uB514\uC544": "sea_near",
    "\uD0DC\uAD6D": "sea_near", "\uD544\uB9AC\uD540": "sea_near",
    "\uB300\uB9CC": "tw_hk", "\uB9C8\uCE74\uC624": "tw_hk",
    "\uD64D\uCF69": "tw_hk",
}

def normalize_name(s):
    """Strip all whitespace so spacing variants match."""
    return re.sub(r"\s+", "", s or "")


_CITY_LOOKUP = {normalize_name(k): val for k, val in CITY_NAME_TIER.items()}


def resolve_tier(destination_id, country, name=""):
    return (AIRPORT_TIER.get(destination_id)
            or _CITY_LOOKUP.get(normalize_name(name))
            or COUNTRY_TIER.get(normalize_name(country))
            or "longhaul")


def trip_days_range(destination_id, country, name=""):
    tier = resolve_tier(destination_id, country, name)
    return TIER_TRIP_DAYS.get(tier, DEFAULT_TRIP_DAYS)


def value_ratio(price, destination_id, country, name=""):
    if not price:
        return None
    baseline = TIER_BASELINE[resolve_tier(destination_id, country, name)]
    return round(price / baseline, 3)


def grade(ratio):
    if ratio is None:
        return "unknown"
    if ratio <= 0.70:
        return "\U0001F525 \uCD08\uD2B9\uAC00"
    if ratio <= 0.85:
        return "\u2728 \uD2B9\uAC00"
    if ratio <= 1.00:
        return "\U0001F44D \uAD1C\uCC2E\uC74C"
    return "\uBCF4\uD1B5"
