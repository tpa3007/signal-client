"""Region-aware source registry for targeted multilingual research.

Maps a detected language/region to a curated list of direct-crawl URLs:
independent journalism, opposition outlets, regional neighbours, and Telegram
public channels — ordered by information value, not alphabetically.

Tier labels:
  independent   — verified independent journalism (high credibility)
  opposition    — exiled / diaspora media; biased against incumbent but factual
  regional      — neighbouring-country press; Western-aligned but close access
  blogger       — Telegram war/event bloggers; ground-level, use for leads only
  grey          — military forums, pro-regime news blogs, specialist trackers;
                  often first with operational details but editorially biased —
                  credibility 0.40-0.55; always cross-check against independent tier
  state         — official state media; use ONLY to track official positions
                  (credibility floor 0.2 so Forager doesn't over-weight them)

Usage:
    from lib.integrations.region_sources import get_seed_urls_for_language
    urls = get_seed_urls_for_language("russian")  # → [(url, cred_score, tier), ...]
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegionSource:
    url: str
    name: str
    region: str
    tier: str          # independent | opposition | regional | blogger | grey | state
    credibility: float  # 0.0–1.0 passed to Forager SourceRegisterRequest
    language: str      # ISO 639-1 or descriptive
    tg_channel: str | None = None   # public Telegram channel name (without @)
    rss: str | None = None          # RSS feed URL if available


# ─────────────────────────────────────────────────────────────────────────────
# RUSSIA / UKRAINE / BELARUS / Baltics
# ─────────────────────────────────────────────────────────────────────────────

_RU_UA: list[RegionSource] = [
    # ── Independent Russian-language journalism ────────────────────────────
    RegionSource("https://meduza.io/en", "Meduza (EN)", "russia_ukraine", "independent", 0.90, "russian", tg_channel="meduzaio"),
    RegionSource("https://meduza.io", "Meduza (RU)", "russia_ukraine", "independent", 0.90, "russian", tg_channel="meduzaio"),
    RegionSource("https://theins.ru/en", "The Insider Russia", "russia_ukraine", "independent", 0.90, "russian", tg_channel="theinsider_russia"),
    RegionSource("https://istories.media", "iStories (Important Stories)", "russia_ukraine", "independent", 0.90, "russian", tg_channel="istories_media"),
    RegionSource("https://novayagazeta.eu", "Novaya Gazeta Europe", "russia_ukraine", "opposition", 0.85, "russian", tg_channel="novayagazeta_eu"),
    RegionSource("https://zona.media", "Mediazona", "russia_ukraine", "independent", 0.85, "russian", tg_channel="mediazona_ru"),
    RegionSource("https://republic.ru", "Republic.ru", "russia_ukraine", "independent", 0.80, "russian"),
    RegionSource("https://verstka.media", "Verstka Media", "russia_ukraine", "independent", 0.85, "russian", tg_channel="verstka_media"),
    RegionSource("https://www.dw.com/ru", "DW Russian", "russia_ukraine", "regional", 0.85, "russian"),
    # ── Ukrainian independent journalism ──────────────────────────────────
    RegionSource("https://www.pravda.com.ua", "Ukranian Pravda", "russia_ukraine", "independent", 0.85, "ukrainian", tg_channel="ukrpravda_news"),
    RegionSource("https://www.ukrinform.ua", "Ukrinform (UA)", "russia_ukraine", "regional", 0.75, "ukrainian", tg_channel="ukrinform_ua"),
    RegionSource("https://www.unian.ua", "UNIAN", "russia_ukraine", "regional", 0.72, "ukrainian", tg_channel="uniannet"),
    RegionSource("https://suspilne.media", "Suspilne (UA public)", "russia_ukraine", "regional", 0.80, "ukrainian", tg_channel="suspilne_ua"),
    RegionSource("https://nv.ua/ukr", "NV Ukraine", "russia_ukraine", "independent", 0.80, "ukrainian"),
    RegionSource("https://babel.ua", "Babel.ua", "russia_ukraine", "independent", 0.82, "ukrainian", tg_channel="babel_ua"),
    # ── Investigative / conflict tracking ────────────────────────────────
    RegionSource("https://www.bellingcat.com", "Bellingcat", "russia_ukraine", "independent", 0.92, "english"),
    RegionSource("https://understandingwar.org", "ISW (Institute for Study of War)", "russia_ukraine", "independent", 0.88, "english", tg_channel="thestudyofwar"),
    RegionSource("https://www.oryxspioenkop.com", "Oryx (equipment losses DB)", "russia_ukraine", "independent", 0.87, "english"),
    RegionSource("https://militaryland.net", "Militaryland", "russia_ukraine", "independent", 0.75, "english"),
    RegionSource("https://www.rferl.org", "Radio Free Europe", "russia_ukraine", "opposition", 0.80, "russian", tg_channel="rferl"),
    RegionSource("https://en.delfi.lt", "Delfi Lithuania", "russia_ukraine", "regional", 0.82, "english"),
    RegionSource("https://news.err.ee", "ERR (Estonia)", "russia_ukraine", "regional", 0.85, "english"),
    RegionSource("https://www.lrt.lt/en", "LRT (Lithuania)", "russia_ukraine", "regional", 0.83, "english"),
    RegionSource("https://tvn24.pl/en", "TVN24 (Poland)", "russia_ukraine", "regional", 0.80, "english"),
    RegionSource("https://www.theguardian.com/world/russia", "Guardian/Russia", "russia_ukraine", "independent", 0.85, "english"),
    # ── High-value Telegram-only analytical channels ─────────────────────
    # TG-only sources: no web URL (None), crawled via t.me/s/ or RSShub only
    RegionSource("https://t.me/s/CITeam", "CIT (Conflict Intelligence Team)", "russia_ukraine", "independent", 0.88, "russian", tg_channel="CITeam"),
    RegionSource("https://t.me/s/wartranslated", "War Translated (EN)", "russia_ukraine", "independent", 0.82, "english", tg_channel="wartranslated"),
    RegionSource("https://t.me/s/InformNapalm", "InformNapalm (UA intel)", "russia_ukraine", "independent", 0.80, "ukrainian", tg_channel="InformNapalm"),
    RegionSource("https://t.me/s/Tendar", "Tendar (NATO analyst NL)", "russia_ukraine", "independent", 0.82, "english", tg_channel="Tendar"),
    RegionSource("https://t.me/s/UkraineWarReport", "Ukraine War Report", "russia_ukraine", "regional", 0.72, "english", tg_channel="UkraineWarReport"),
    RegionSource("https://t.me/s/dosye_ua", "Досье UA (UA investigations)", "russia_ukraine", "independent", 0.78, "ukrainian", tg_channel="dosye_ua"),
    RegionSource("https://t.me/s/mediahunters", "MediaHunters (fact-check)", "russia_ukraine", "independent", 0.85, "russian", tg_channel="mediahunters"),
    RegionSource("https://t.me/s/mdforeignaffairs", "Moldova Foreign Affairs", "russia_ukraine", "regional", 0.70, "english", tg_channel="mdforeignaffairs"),
    RegionSource("https://t.me/s/zaborona", "Заборона (UA independent)", "russia_ukraine", "independent", 0.82, "ukrainian", tg_channel="zaborona"),
    RegionSource("https://t.me/s/dw_russian", "DW Russian TG", "russia_ukraine", "regional", 0.85, "russian", tg_channel="dw_russian"),
    # ── Telegram war bloggers (credibility LOW — leads only, always cross-check) ──
    RegionSource("https://t.me/s/rybar", "Rybar (RU mil blogger)", "russia_ukraine", "blogger", 0.35, "russian", tg_channel="rybar"),
    RegionSource("https://t.me/s/grey_zone", "Grey Zone (RU)", "russia_ukraine", "blogger", 0.30, "russian", tg_channel="grey_zone"),
    RegionSource("https://t.me/s/wargonzo", "Wargonzo (RU war correspondent)", "russia_ukraine", "blogger", 0.30, "russian", tg_channel="wargonzo"),
    RegionSource("https://t.me/s/rlz_the_kraken", "RLZ Kraken (UA mil)", "russia_ukraine", "blogger", 0.45, "ukrainian", tg_channel="rlz_the_kraken"),
    RegionSource("https://t.me/s/nexta_tv", "NEXTA TV", "russia_ukraine", "opposition", 0.65, "russian", tg_channel="nexta_tv"),
    RegionSource("https://t.me/s/flash_ua", "Flash UA", "russia_ukraine", "regional", 0.60, "ukrainian", tg_channel="flash_ua"),
    RegionSource("https://t.me/s/ukraina_ru", "Украина.ру (pro-RU)", "russia_ukraine", "blogger", 0.25, "russian", tg_channel="ukraina_ru"),
    RegionSource("https://t.me/s/readovkaru", "Readovka (RU nationalist)", "russia_ukraine", "blogger", 0.28, "russian", tg_channel="readovkaru"),
    # ── Grey — Russian military news blogs (pro-regime but operationally detailed) ──
    # These sources are editorially biased toward Russia but often carry genuine
    # operational details (unit positions, equipment losses, SIGINT clips) 12-48h
    # before Western press.  Cross-check every claim against independent tier.
    RegionSource("https://topwar.ru", "Topwar.ru (RU mil news blog)", "russia_ukraine", "grey", 0.45, "russian", tg_channel="topwar_ru"),
    RegionSource("https://topcor.ru", "Topcor.ru (RU mil analysis)", "russia_ukraine", "grey", 0.42, "russian"),
    RegionSource("https://militarist.ru", "Militarist.ru (RU mil)", "russia_ukraine", "grey", 0.43, "russian"),
    RegionSource("https://t.me/s/dva_majors", "Two Majors (RU mil intel analyst)", "russia_ukraine", "grey", 0.40, "russian", tg_channel="dva_majors"),
    RegionSource("https://t.me/s/fighterbomber", "Fighterbomber (RU pilot blogger)", "russia_ukraine", "grey", 0.35, "russian", tg_channel="fighterbomber"),
    RegionSource("https://t.me/s/intelslava", "Intel Slava Z (global events agg.)", "russia_ukraine", "grey", 0.38, "english", tg_channel="intelslava"),
    # ── Grey — Ukrainian military / defence forums ─────────────────────────
    # forum.defence.ua: UA mil community; raw unit reports, equipment spotting
    # mil.in.ua: Ukrainian military news portal; faster than mainstream UA press
    RegionSource("https://mil.in.ua", "Mil.in.ua (UA mil news)", "russia_ukraine", "grey", 0.52, "ukrainian"),
    RegionSource("https://forum.defence.ua/viewforum.php?f=2", "Defence.ua forum (UA)", "russia_ukraine", "grey", 0.48, "ukrainian"),
    RegionSource("https://t.me/s/DeepStateUA", "Deep State UA (frontline map)", "russia_ukraine", "grey", 0.62, "ukrainian", tg_channel="DeepStateUA"),
    RegionSource("https://t.me/s/militarymaps", "Military Maps (frontline EN)", "russia_ukraine", "grey", 0.60, "english", tg_channel="militarymaps"),
    RegionSource("https://t.me/s/osinttechnical", "OSINT Technical (mil tech tracker)", "russia_ukraine", "grey", 0.55, "english", tg_channel="osinttechnical"),
    # ── State (track official positions only) ────────────────────────────
    RegionSource("https://tass.com", "TASS (state)", "russia_ukraine", "state", 0.20, "english", tg_channel="tass_agency"),
    RegionSource("https://ria.ru", "RIA Novosti (state)", "russia_ukraine", "state", 0.15, "russian"),
    RegionSource("https://t.me/s/mod_russia", "RU MoD (state)", "russia_ukraine", "state", 0.15, "russian", tg_channel="mod_russia"),
    RegionSource("https://t.me/s/MFA_Russia", "RU MFA (state)", "russia_ukraine", "state", 0.18, "russian", tg_channel="MFA_Russia"),
]

# ─────────────────────────────────────────────────────────────────────────────
# MIDDLE EAST — Iran, Israel/Palestine, Saudi, Gulf
# ─────────────────────────────────────────────────────────────────────────────

_MIDDLE_EAST: list[RegionSource] = [
    RegionSource("https://www.iranintl.com/en", "Iran International", "middle_east", "opposition", 0.80, "persian", tg_channel="iranintl"),
    RegionSource("https://www.radiofarda.com", "Radio Farda (RFE/RL Farsi)", "middle_east", "opposition", 0.78, "persian"),
    RegionSource("https://en.radiofarda.com", "Radio Farda (EN)", "middle_east", "opposition", 0.78, "persian"),
    RegionSource("https://t.me/s/iranintl", "IranIntl Telegram", "middle_east", "opposition", 0.78, "persian", tg_channel="iranintl"),
    RegionSource("https://www.mei.edu", "Middle East Institute", "middle_east", "independent", 0.85, "english"),
    RegionSource("https://www.al-monitor.com", "Al-Monitor", "middle_east", "independent", 0.82, "english"),
    RegionSource("https://www.haaretz.com", "Haaretz (IL)", "middle_east", "independent", 0.85, "hebrew"),
    RegionSource("https://www.timesofisrael.com", "Times of Israel", "middle_east", "regional", 0.78, "english"),
    RegionSource("https://www.middleeasteye.net", "Middle East Eye", "middle_east", "independent", 0.75, "english"),
    RegionSource("https://english.alarabiya.net", "Al Arabiya (EN)", "middle_east", "regional", 0.60, "english"),
    RegionSource("https://www.jpost.com", "Jerusalem Post", "middle_east", "regional", 0.72, "english"),
    RegionSource("https://www.theguardian.com/world/middleeast", "Guardian/ME", "middle_east", "independent", 0.85, "english"),
    RegionSource("https://t.me/s/IranIntl_Farsi", "IranIntl Farsi TG", "middle_east", "opposition", 0.80, "persian", tg_channel="IranIntl_Farsi"),
    RegionSource("https://t.me/s/MiddleEastEye", "Middle East Eye TG", "middle_east", "independent", 0.75, "english", tg_channel="MiddleEastEye"),
    RegionSource("https://t.me/s/MEE_Arabic", "MEE Arabic TG", "middle_east", "independent", 0.75, "arabic", tg_channel="MEE_Arabic"),
    RegionSource("https://t.me/s/AJArabic", "Al Jazeera Arabic TG", "middle_east", "regional", 0.65, "arabic", tg_channel="AJArabic"),
    RegionSource("https://t.me/s/bbc_persian", "BBC Persian TG", "middle_east", "independent", 0.88, "persian", tg_channel="bbc_persian"),
    RegionSource("https://t.me/s/VOAPersian", "VOA Persian TG", "middle_east", "opposition", 0.78, "persian", tg_channel="VOAPersian"),
    # ── Grey — Iran semi-official / resistance axis ───────────────────────
    # Tasnim & FarsNews are IRGC-linked; faster than IRNA on military/nuclear stories
    # but heavily filtered through regime narrative. Use for official timing, not facts.
    RegionSource("https://www.tasnimnews.com/en", "Tasnim News (IR IRGC-linked)", "middle_east", "grey", 0.35, "persian"),
    RegionSource("https://www.farsnews.ir/en", "FarsNews (IR semi-official)", "middle_east", "grey", 0.32, "persian"),
    # Al-Mayadeen: Lebanon-based, Hezbollah editorial line but strong regional access
    RegionSource("https://www.mayadeen.net/en", "Al-Mayadeen (Hezbollah-aligned LB)", "middle_east", "grey", 0.36, "arabic", tg_channel="AlMayadeen"),
    # Official positions
    RegionSource("https://www.irna.ir/en", "IRNA (Iran state)", "middle_east", "state", 0.20, "english"),
    RegionSource("https://t.me/s/khamenei_ir", "Khamenei official TG", "middle_east", "state", 0.15, "persian", tg_channel="khamenei_ir"),
]

# ─────────────────────────────────────────────────────────────────────────────
# CHINA / TAIWAN / HK
# ─────────────────────────────────────────────────────────────────────────────

_CHINA_TAIWAN: list[RegionSource] = [
    RegionSource("https://www.scmp.com", "South China Morning Post", "china_taiwan", "regional", 0.72, "english"),
    RegionSource("https://www.rfa.org/english", "Radio Free Asia", "china_taiwan", "opposition", 0.78, "english"),
    RegionSource("https://www.taipeitimes.com", "Taipei Times", "china_taiwan", "regional", 0.78, "english"),
    RegionSource("https://focustaiwan.tw", "Focus Taiwan (CNA)", "china_taiwan", "regional", 0.80, "english"),
    RegionSource("https://thediplomat.com", "The Diplomat", "china_taiwan", "independent", 0.85, "english"),
    RegionSource("https://sinocism.com", "Sinocism (Bill Bishop)", "china_taiwan", "independent", 0.87, "english"),
    RegionSource("https://www.chinafile.com", "ChinaFile (Asia Society)", "china_taiwan", "independent", 0.85, "english"),
    RegionSource("https://www.hongkongfp.com", "Hong Kong Free Press", "china_taiwan", "independent", 0.85, "english"),
    RegionSource("https://www.bbc.com/zhongwen/simp", "BBC Chinese", "china_taiwan", "independent", 0.88, "chinese"),
    # State (track official positions)
    RegionSource("https://www.xinhuanet.com/english", "Xinhua (state)", "china_taiwan", "state", 0.20, "english"),
    RegionSource("https://global.chinadaily.com.cn", "China Daily (state)", "china_taiwan", "state", 0.20, "english"),
]

# ─────────────────────────────────────────────────────────────────────────────
# KOREA (North & South)
# ─────────────────────────────────────────────────────────────────────────────

_KOREA: list[RegionSource] = [
    RegionSource("https://www.38north.org", "38 North (DPRK specialist)", "korea", "independent", 0.90, "english"),
    RegionSource("https://www.nknews.org", "NK News", "korea", "independent", 0.88, "english"),
    RegionSource("https://en.yna.co.kr", "Yonhap (SK state agency)", "korea", "regional", 0.78, "english"),
    RegionSource("https://www.koreatimes.co.kr", "Korea Times", "korea", "regional", 0.75, "english"),
    RegionSource("https://thediplomat.com/category/korean-peninsula", "Diplomat/Korea", "korea", "independent", 0.85, "english"),
    RegionSource("https://english.hani.co.kr", "Hankyoreh (progressive)", "korea", "independent", 0.80, "english"),
    RegionSource("https://www.rfa.org/korean", "RFA Korean", "korea", "opposition", 0.78, "korean"),
    # ── DPRK specialist trackers (high quality, English) ─────────────────
    RegionSource("https://www.dailynk.com", "DailyNK (NK defector-run media)", "korea", "independent", 0.82, "english"),
    RegionSource("https://www.nkleadershipwatch.org", "NK Leadership Watch", "korea", "independent", 0.80, "english"),
    RegionSource("https://sinonk.com", "Sino-NK (China-DPRK analysis)", "korea", "independent", 0.78, "english"),
    RegionSource("https://thediplomat.com/category/china/north-korea", "Diplomat/NKorea", "korea", "independent", 0.85, "english"),
    # ── Grey — DPRK state media aggregator ───────────────────────────────
    # Use ONLY to monitor official DPRK positions; never cite as independent fact
    RegionSource("https://kcnawatch.org", "KCNA Watch (DPRK state aggregator)", "korea", "grey", 0.28, "english"),
]

# ─────────────────────────────────────────────────────────────────────────────
# EAST EUROPE (Romania, Hungary, Serbia, Poland, Balkans)
# ─────────────────────────────────────────────────────────────────────────────

_EAST_EUROPE: list[RegionSource] = [
    RegionSource("https://g4media.ro", "G4Media (Romania independent)", "east_europe", "independent", 0.85, "romanian", tg_channel="g4media"),
    RegionSource("https://www.recorder.ro", "Recorder.ro (RO investigative)", "east_europe", "independent", 0.88, "romanian", tg_channel="recorderro"),
    RegionSource("https://www.digi24.ro", "Digi24 Romania", "east_europe", "regional", 0.75, "romanian"),
    RegionSource("https://romania.europalibera.org", "Europa Libera Romania", "east_europe", "opposition", 0.82, "romanian"),
    RegionSource("https://telex.hu", "Telex (Hungary independent)", "east_europe", "independent", 0.88, "hungarian"),
    RegionSource("https://444.hu", "444.hu (Hungary)", "east_europe", "independent", 0.85, "hungarian"),
    RegionSource("https://n1info.com", "N1 (Serbia/Balkans)", "east_europe", "independent", 0.80, "serbian"),
    RegionSource("https://www.rferl.org/z/693", "RFE/RL Balkans", "east_europe", "opposition", 0.80, "english"),
    RegionSource("https://balkaninsight.com", "Balkan Insight (BIRN)", "east_europe", "independent", 0.90, "english"),
    RegionSource("https://notesfrompoland.com", "Notes from Poland", "east_europe", "independent", 0.83, "english"),
    RegionSource("https://t.me/s/recorderro", "Recorder.ro Telegram", "east_europe", "independent", 0.85, "romanian", tg_channel="recorderro"),
]

# ─────────────────────────────────────────────────────────────────────────────
# LATIN AMERICA (Brazil, Argentina, Venezuela, etc.)
# ─────────────────────────────────────────────────────────────────────────────

_LATAM: list[RegionSource] = [
    RegionSource("https://www.folha.uol.com.br", "Folha de S.Paulo", "latam", "independent", 0.82, "portuguese"),
    RegionSource("https://agenciabrasil.ebc.com.br/en", "Agencia Brasil (EN)", "latam", "regional", 0.75, "english"),
    RegionSource("https://www.infobae.com", "Infobae (AR)", "latam", "regional", 0.72, "spanish"),
    RegionSource("https://www.lanacion.com.ar", "La Nacion (AR)", "latam", "independent", 0.78, "spanish"),
    RegionSource("https://larepublica.pe", "La Republica (PE)", "latam", "independent", 0.72, "spanish"),
    RegionSource("https://www.el-nacional.com", "El Nacional (VE opposition)", "latam", "opposition", 0.70, "spanish"),
    RegionSource("https://www.rferl.org/z/1405", "RFE/RL Latin America", "latam", "opposition", 0.78, "spanish"),
    RegionSource("https://english.elpais.com/international", "El Pais Internacional", "latam", "independent", 0.83, "english"),
    # ── Cartel / organised crime / Venezuela ─────────────────────────────
    # InSight Crime: premier tracker for LatAm organised crime, cartels, state capture.
    # Essential for Mexico, Colombia, Venezuela, Honduras, El Salvador markets.
    RegionSource("https://insightcrime.org", "InSight Crime (LatAm crime & conflict)", "latam", "independent", 0.83, "english"),
    # Armando.info: Venezuela's top investigative outlet; breaks Maduro/military stories
    RegionSource("https://armando.info", "Armando.info (Venezuela investigations)", "latam", "independent", 0.80, "spanish"),
    # Conectas / Agencia Publica: Brazil human rights & political investigations
    RegionSource("https://apublica.org", "Agencia Publica (BR investigative)", "latam", "independent", 0.80, "portuguese"),
    # ── Grey — LatAm security / conflict tracking ─────────────────────────
    RegionSource("https://t.me/s/VenezuelaCrisis", "Venezuela Crisis (tracker)", "latam", "grey", 0.45, "spanish", tg_channel="VenezuelaCrisis"),
    RegionSource("https://t.me/s/colombiaconflicto", "Colombia Conflicto (FARC/ELN)", "latam", "grey", 0.45, "spanish", tg_channel="colombiaconflicto"),
]

# ─────────────────────────────────────────────────────────────────────────────
# TURKEY / CENTRAL ASIA
# ─────────────────────────────────────────────────────────────────────────────

_TURKEY: list[RegionSource] = [
    RegionSource("https://www.gazeteduvar.com.tr/en", "Gazete Duvar (TR independent)", "turkey", "independent", 0.80, "turkish"),
    RegionSource("https://bianet.org/english", "Bianet (TR civil society)", "turkey", "independent", 0.82, "english"),
    RegionSource("https://www.al-monitor.com/turkey", "Al-Monitor/Turkey", "turkey", "independent", 0.82, "english"),
    RegionSource("https://ahvalnews.com", "Ahval (TR opposition)", "turkey", "opposition", 0.75, "english", tg_channel="ahvalnews"),
    RegionSource("https://tr.euronews.com", "Euronews TR", "turkey", "regional", 0.75, "turkish"),
    RegionSource("https://www.rferl.org/z/690", "RFE/RL Turkic", "turkey", "opposition", 0.78, "turkish"),
]

# ─────────────────────────────────────────────────────────────────────────────
# ARABIC MENA — Yemen/Houthi, Gaza, Sudan, Libya, Syria, Iraq
# (non-Iran Arabic world; Telegram is top-1 source here — no English equivalent)
# ─────────────────────────────────────────────────────────────────────────────

_ARABIC_MENA: list[RegionSource] = [
    # ── Pan-Arab independent media ────────────────────────────────────────
    RegionSource("https://www.aljazeera.net", "Al Jazeera Arabic", "arabic_mena", "regional", 0.68, "arabic", tg_channel="AJArabic"),
    RegionSource("https://arabic.alarabiya.net", "Al Arabiya Arabic", "arabic_mena", "regional", 0.60, "arabic", tg_channel="alarabiya"),
    RegionSource("https://www.middleeasteye.net/ar", "Middle East Eye Arabic", "arabic_mena", "independent", 0.75, "arabic", tg_channel="MEE_Arabic"),
    RegionSource("https://www.bbc.com/arabic", "BBC Arabic", "arabic_mena", "independent", 0.88, "arabic", tg_channel="bbcarabic"),
    RegionSource("https://www.france24.com/ar", "France 24 Arabic", "arabic_mena", "independent", 0.85, "arabic", tg_channel="France24Arabic"),
    RegionSource("https://www.dw.com/ar", "DW Arabic", "arabic_mena", "independent", 0.85, "arabic", tg_channel="dw_arabic"),
    # ── Yemen / Houthi / Red Sea ───────────────────────────────────────────
    RegionSource("https://t.me/s/AnsarAllahPS", "Ansarallah (Houthi official)", "arabic_mena", "state", 0.20, "arabic", tg_channel="AnsarAllahPS"),
    RegionSource("https://t.me/s/QudsN", "Quds News (resistance axis)", "arabic_mena", "blogger", 0.38, "arabic", tg_channel="QudsN"),
    RegionSource("https://t.me/s/yemenmonitor", "Yemen Monitor", "arabic_mena", "independent", 0.70, "arabic", tg_channel="yemenmonitor"),
    RegionSource("https://t.me/s/almasirahnews", "Al Masirah (Houthi media)", "arabic_mena", "state", 0.18, "arabic", tg_channel="almasirahnews"),
    RegionSource("https://mwatana.org/en", "Mwatana (Yemen human rights)", "arabic_mena", "independent", 0.72, "english"),
    # ── Gaza / Palestine / Lebanon ────────────────────────────────────────
    RegionSource("https://t.me/s/HamasInfoPS", "Hamas Info (official)", "arabic_mena", "state", 0.20, "arabic", tg_channel="HamasInfoPS"),
    RegionSource("https://t.me/s/QudsNewsNetwork", "Quds News Network", "arabic_mena", "blogger", 0.40, "arabic", tg_channel="QudsNewsNetwork"),
    RegionSource("https://t.me/s/alahed_news", "Al-Ahed (Hezbollah media)", "arabic_mena", "state", 0.18, "arabic", tg_channel="alahed_news"),
    RegionSource("https://www.972mag.com", "+972 Magazine (IL/PA independent)", "arabic_mena", "independent", 0.83, "english"),
    RegionSource("https://www.palestinechronicle.com", "Palestine Chronicle", "arabic_mena", "independent", 0.65, "english"),
    # ── Sudan ─────────────────────────────────────────────────────────────
    # Sudan civil war: RSF vs SAF — almost NO English coverage, all in Arabic TG
    RegionSource("https://t.me/s/sudan_24_news", "Sudan 24 (news)", "arabic_mena", "regional", 0.60, "arabic", tg_channel="sudan_24_news"),
    RegionSource("https://t.me/s/SudanSudanSudan", "Sudan War Monitor", "arabic_mena", "independent", 0.65, "arabic", tg_channel="SudanSudanSudan"),
    RegionSource("https://t.me/s/RadioDabanga", "Radio Dabanga (Sudan)", "arabic_mena", "independent", 0.78, "english", tg_channel="RadioDabanga"),
    RegionSource("https://www.sudantribune.com", "Sudan Tribune", "arabic_mena", "independent", 0.75, "english"),
    # ── Syria ─────────────────────────────────────────────────────────────
    RegionSource("https://t.me/s/orient_news", "Orient News (Syria)", "arabic_mena", "opposition", 0.62, "arabic", tg_channel="orient_news"),
    RegionSource("https://t.me/s/zaman_alwasl", "Zaman al-Wasl (Syria opp.)", "arabic_mena", "opposition", 0.58, "arabic", tg_channel="zaman_alwasl"),
    RegionSource("https://www.syriahr.com/en", "SOHR (Syria Human Rights)", "arabic_mena", "independent", 0.72, "english"),
    # ── Libya ─────────────────────────────────────────────────────────────
    RegionSource("https://t.me/s/LibyaObserver1", "Libya Observer", "arabic_mena", "regional", 0.62, "english", tg_channel="LibyaObserver1"),
    RegionSource("https://www.libyaherald.com", "Libya Herald", "arabic_mena", "independent", 0.70, "english"),
    # ── Iraq ──────────────────────────────────────────────────────────────
    RegionSource("https://t.me/s/BasraNews1", "Basra News", "arabic_mena", "regional", 0.55, "arabic", tg_channel="BasraNews1"),
    RegionSource("https://www.rudaw.net/english", "Rudaw (Iraqi Kurdistan)", "arabic_mena", "regional", 0.75, "english"),
    # ── Pan-Arab independent + English analysis ───────────────────────────
    RegionSource("https://english.alaraby.co.uk", "Al-Araby Al-Jadeed (The New Arab)", "arabic_mena", "independent", 0.72, "english"),
    RegionSource("https://www.aljazeera.com/where/middle-east", "Al Jazeera English/ME", "arabic_mena", "regional", 0.68, "english"),
    # ── Grey — MENA conflict tracking ─────────────────────────────────────
    # These Telegram channels aggregate MENA military/conflict reports in real time.
    # Resistance-axis and counter-narrative sources included for timing signals only.
    RegionSource("https://t.me/s/MENAConflictMonitor", "MENA Conflict Monitor", "arabic_mena", "grey", 0.48, "english", tg_channel="MENAConflictMonitor"),
    RegionSource("https://t.me/s/MiddleEastWatcher", "Middle East Watcher", "arabic_mena", "grey", 0.45, "english", tg_channel="MiddleEastWatcher"),
]

# ─────────────────────────────────────────────────────────────────────────────
# SOUTH & SOUTHEAST ASIA — Pakistan, Afghanistan, Myanmar
# ─────────────────────────────────────────────────────────────────────────────

_SOUTH_ASIA: list[RegionSource] = [
    # ── Pakistan ──────────────────────────────────────────────────────────
    RegionSource("https://www.geo.tv", "Geo TV Pakistan", "south_asia", "regional", 0.72, "urdu", tg_channel="GeoTVNews"),
    RegionSource("https://www.dawn.com", "Dawn (Pakistan)", "south_asia", "independent", 0.83, "english", tg_channel="dawndotcom"),
    RegionSource("https://www.thenews.com.pk", "The News (Pakistan)", "south_asia", "regional", 0.72, "english"),
    RegionSource("https://t.me/s/PTIofficial", "PTI Imran Khan (official)", "south_asia", "blogger", 0.38, "urdu", tg_channel="PTIofficial"),
    RegionSource("https://t.me/s/ARYNEWSOFFICIAL", "ARY News Pakistan", "south_asia", "regional", 0.65, "urdu", tg_channel="ARYNEWSOFFICIAL"),
    # ── Afghanistan ───────────────────────────────────────────────────────
    RegionSource("https://tolonews.com", "TOLOnews Afghanistan", "south_asia", "independent", 0.75, "dari", tg_channel="TOLOnewsEN"),
    RegionSource("https://www.khaama.com", "Khaama Press (AF)", "south_asia", "independent", 0.72, "english"),
    RegionSource("https://t.me/s/Taliban", "Taliban IEA (official)", "south_asia", "state", 0.18, "dari", tg_channel="Taliban"),
    RegionSource("https://www.rferl.org/z/627", "RFE/RL Afghanistan (Dari/Pashto)", "south_asia", "opposition", 0.80, "dari"),
    # ── Myanmar ───────────────────────────────────────────────────────────
    # Myanmar: military junta (Tatmadaw) vs NUG resistance — Telegram is THE source
    RegionSource("https://www.irrawaddy.com", "The Irrawaddy (Myanmar)", "south_asia", "independent", 0.87, "english", tg_channel="theirrawaddy"),
    RegionSource("https://myanmar-now.org/en", "Myanmar Now", "south_asia", "independent", 0.83, "english", tg_channel="myanmar_now_en"),
    RegionSource("https://t.me/s/NUGMyanmar", "NUG Myanmar (resistance gov.)", "south_asia", "opposition", 0.70, "burmese", tg_channel="NUGMyanmar"),
    RegionSource("https://t.me/s/pdfinformation", "PDF Information (resistance)", "south_asia", "blogger", 0.50, "burmese", tg_channel="pdfinformation"),
    RegionSource("https://t.me/s/TatmadawTrue", "Tatmadaw True (junta)", "south_asia", "state", 0.18, "burmese", tg_channel="TatmadawTrue"),
    RegionSource("https://www.frontiermyanmar.net", "Frontier Myanmar", "south_asia", "independent", 0.82, "english"),
    # ── India (elections / geopolitical) ─────────────────────────────────
    RegionSource("https://www.thehindu.com", "The Hindu (India)", "south_asia", "independent", 0.83, "english"),
    RegionSource("https://t.me/s/thewirenews", "The Wire India", "south_asia", "independent", 0.80, "english", tg_channel="thewirenews"),
    RegionSource("https://aninews.in", "ANI (India primary wire service)", "south_asia", "regional", 0.68, "english"),
    # ── Grey — South Asia defence / military community ────────────────────
    # Pakistan Defence Forum: leaked mil info, order-of-battle claims, equipment
    # spotting — treat as leads only; high noise ratio but sometimes first-to-publish
    RegionSource("https://defence.pk", "Pakistan Defence Forum", "south_asia", "grey", 0.45, "english"),
    # South Asia Monitor: policy/security tracker covers India-Pakistan-China triangle
    RegionSource("https://southasiamonitor.org", "South Asia Monitor", "south_asia", "grey", 0.55, "english"),
    # ── Myanmar additional grey ───────────────────────────────────────────
    RegionSource("https://t.me/s/HninSi_News", "Hnin Si News (Myanmar resistance)", "south_asia", "grey", 0.50, "burmese", tg_channel="HninSi_News"),
    RegionSource("https://t.me/s/MyanmarUncensored", "Myanmar Uncensored", "south_asia", "grey", 0.48, "english", tg_channel="MyanmarUncensored"),
]

# ─────────────────────────────────────────────────────────────────────────────
# FRANCOPHONE AFRICA — Sahel coups, Congo, CAR, West Africa
# ─────────────────────────────────────────────────────────────────────────────

_FRANCOPHONE_AFRICA: list[RegionSource] = [
    # ── Pan-African reference sources ────────────────────────────────────
    RegionSource("https://www.rfi.fr/en/africa", "RFI Africa (EN)", "francophone_africa", "independent", 0.87, "french", tg_channel="RFI_Afrique"),
    RegionSource("https://www.bbc.com/afrique", "BBC Afrique (French)", "francophone_africa", "independent", 0.88, "french", tg_channel="bbcafrique"),
    RegionSource("https://www.jeuneafrique.com", "Jeune Afrique", "francophone_africa", "independent", 0.80, "french", tg_channel="JeuneAfrique"),
    RegionSource("https://www.lemonde.fr/afrique", "Le Monde Afrique", "francophone_africa", "independent", 0.85, "french"),
    RegionSource("https://www.france24.com/fr/afrique", "France 24 Afrique", "francophone_africa", "independent", 0.82, "french", tg_channel="France24"),
    RegionSource("https://apanews.net", "APA News (African Press)", "francophone_africa", "regional", 0.72, "english"),
    # ── Sahel (Mali, Burkina Faso, Niger — junta-controlled, all on TG) ──
    RegionSource("https://t.me/s/maliactualites", "Mali Actualités", "francophone_africa", "regional", 0.55, "french", tg_channel="maliactualites"),
    RegionSource("https://t.me/s/Burkina_Actu", "Burkina Actu", "francophone_africa", "regional", 0.55, "french", tg_channel="Burkina_Actu"),
    RegionSource("https://t.me/s/NigerActualite", "Niger Actualité", "francophone_africa", "regional", 0.52, "french", tg_channel="NigerActualite"),
    RegionSource("https://t.me/s/VagueInfos", "Vague Infos (Sahel)", "francophone_africa", "blogger", 0.45, "french", tg_channel="VagueInfos"),
    # ── Congo (DRC) ───────────────────────────────────────────────────────
    RegionSource("https://www.radiookapi.net", "Radio Okapi (DRC, UN-backed)", "francophone_africa", "independent", 0.80, "french"),
    RegionSource("https://t.me/s/CongoActualite", "Congo Actualité", "francophone_africa", "regional", 0.55, "french", tg_channel="CongoActualite"),
    RegionSource("https://www.actualite.cd", "Actualite.cd (DRC)", "francophone_africa", "independent", 0.70, "french"),
    # ── Ethiopia (Amharic + English) ──────────────────────────────────────
    # Tigray war / Amhara conflict: Telegram is the ONLY real-time source
    RegionSource("https://addisstandard.com", "Addis Standard (Ethiopia)", "francophone_africa", "independent", 0.80, "english", tg_channel="AddisStandard"),
    RegionSource("https://t.me/s/EthiopianNews24", "Ethiopian News 24", "francophone_africa", "regional", 0.55, "amharic", tg_channel="EthiopianNews24"),
    RegionSource("https://t.me/s/EthiopiaInsider", "Ethiopia Insider", "francophone_africa", "independent", 0.65, "english", tg_channel="EthiopiaInsider"),
    RegionSource("https://www.rferl.org/z/608", "RFE/RL Amharic/Tigrinya", "francophone_africa", "independent", 0.80, "amharic"),
    # ── West Africa ───────────────────────────────────────────────────────
    RegionSource("https://www.theafricareport.com", "The Africa Report", "francophone_africa", "independent", 0.78, "english"),
    RegionSource("https://t.me/s/africa_news_eng", "Africa News English", "francophone_africa", "regional", 0.60, "english", tg_channel="africa_news_eng"),
    # ── High-quality Africa security analysis ─────────────────────────────
    # ISS Africa: top African security think tank, field offices across the continent
    # InSight Crime: best tracker for organised crime / armed groups (DRC, West Africa)
    # The Sentry: conflict-finance investigations (follow the money on warlords/juntas)
    # ACLED: conflict-event database updated weekly; use dashboard for recent data
    RegionSource("https://issafrica.org", "ISS Africa (security think tank)", "francophone_africa", "independent", 0.85, "english"),
    RegionSource("https://insightcrime.org", "InSight Crime (organized crime/conflict)", "francophone_africa", "independent", 0.83, "english"),
    RegionSource("https://thesentry.org", "The Sentry (conflict finance investigations)", "francophone_africa", "independent", 0.82, "english"),
    RegionSource("https://acleddata.com/dashboard", "ACLED (conflict event data)", "francophone_africa", "independent", 0.88, "english"),
    # ── Grey — Sahel Wagner/AES junta channels ────────────────────────────
    # These channels carry junta announcements and Wagner PR 6-24h before Western press.
    # High disinformation risk — use for timing signals only.
    RegionSource("https://t.me/s/AfriqueMidi", "Afrique Midi (Sahel pro-junta)", "francophone_africa", "grey", 0.40, "french", tg_channel="AfriqueMidi"),
    RegionSource("https://t.me/s/sahelwatch", "Sahel Watch (conflict tracker)", "francophone_africa", "grey", 0.50, "english", tg_channel="sahelwatch"),
    RegionSource("https://t.me/s/CongoKinshasa", "Congo Kinshasa (M23/DRC tracker)", "francophone_africa", "grey", 0.48, "french", tg_channel="CongoKinshasa"),
]

# ─────────────────────────────────────────────────────────────────────────────
# CAUCASUS — Armenia, Azerbaijan, Georgia, Nagorno-Karabakh
# ─────────────────────────────────────────────────────────────────────────────

_CAUCASUS: list[RegionSource] = [
    # ── Pan-Caucasus ─────────────────────────────────────────────────────
    RegionSource("https://jam-news.net", "JAMnews (Caucasus regional)", "caucasus", "independent", 0.80, "english", tg_channel="JAMnewsEN"),
    RegionSource("https://caucasuswatch.de", "Caucasus Watch (DE/EN)", "caucasus", "independent", 0.82, "english"),
    RegionSource("https://www.rferl.org/z/376", "RFE/RL Caucasus", "caucasus", "independent", 0.82, "english"),
    # ── Georgia ───────────────────────────────────────────────────────────
    RegionSource("https://civil.ge", "Civil.ge (Georgia independent)", "caucasus", "independent", 0.88, "english", tg_channel="civilgeorgia"),
    RegionSource("https://www.interpressnews.ge/en", "Interpressnews Georgia", "caucasus", "regional", 0.70, "english"),
    RegionSource("https://t.me/s/formula_geo", "Formula TV Georgia", "caucasus", "independent", 0.72, "georgian", tg_channel="formula_geo"),
    RegionSource("https://t.me/s/tvpirveli_ge", "TV Pirveli Georgia", "caucasus", "independent", 0.72, "georgian", tg_channel="tvpirveli_ge"),
    # ── Armenia ───────────────────────────────────────────────────────────
    RegionSource("https://www.azatutyun.am/", "Azatutyun (RFE/RL Armenia)", "caucasus", "independent", 0.82, "armenian", tg_channel="azatutyun"),
    RegionSource("https://armenpress.am/eng", "Armenpress (state agency)", "caucasus", "state", 0.35, "armenian"),
    RegionSource("https://t.me/s/armenianreport", "Armenian Report", "caucasus", "independent", 0.72, "english", tg_channel="armenianreport"),
    # ── Azerbaijan ────────────────────────────────────────────────────────
    RegionSource("https://www.turan.az/ext/news/en", "Turan Agency (AZ independent)", "caucasus", "independent", 0.72, "azerbaijani"),
    RegionSource("https://t.me/s/meydan_tv", "Meydan TV (AZ opposition)", "caucasus", "opposition", 0.78, "azerbaijani", tg_channel="meydan_tv"),
    RegionSource("https://t.me/s/JAMnewsAZ", "JAMnews Azerbaijan", "caucasus", "independent", 0.78, "azerbaijani", tg_channel="JAMnewsAZ"),
    # Nagorno-Karabakh / Artsakh
    RegionSource("https://t.me/s/ArtsakhInfo", "Artsakh Info", "caucasus", "regional", 0.55, "armenian", tg_channel="ArtsakhInfo"),
    # ── South Caucasus independent analysis ──────────────────────────────
    # OC Media: investigative journalism across Georgia, Armenia, Azerbaijan
    # Caucasian Knot: conflict events database for the wider Caucasus
    RegionSource("https://oc-media.org", "OC Media (South Caucasus independent)", "caucasus", "independent", 0.83, "english"),
    RegionSource("https://www.kavkaz-uzel.eu/articles", "Caucasian Knot (conflict events)", "caucasus", "independent", 0.78, "english"),
    RegionSource("https://www.eurasianet.org", "EurasiaNet (Caucasus + Central Asia)", "caucasus", "independent", 0.82, "english"),
    # ── Grey — Caucasus regional trackers ────────────────────────────────
    RegionSource("https://t.me/s/caucasus_watch", "Caucasus Watch TG", "caucasus", "grey", 0.50, "english", tg_channel="caucasus_watch"),
    RegionSource("https://t.me/s/abkhazinform", "Abkhazia Inform (breakaway state)", "caucasus", "grey", 0.30, "russian", tg_channel="abkhazinform"),
]

# ─────────────────────────────────────────────────────────────────────────────
# WESTERN EUROPE (Germany, France, Netherlands)
# ─────────────────────────────────────────────────────────────────────────────

_EUROPE_WEST: list[RegionSource] = [
    RegionSource("https://www.spiegel.de/international", "Der Spiegel (EN)", "europe_west", "independent", 0.87, "english"),
    RegionSource("https://taz.de", "taz (DE progressive)", "europe_west", "independent", 0.80, "german"),
    RegionSource("https://www.sueddeutsche.de", "Sueddeutsche Zeitung", "europe_west", "independent", 0.85, "german"),
    RegionSource("https://www.lemonde.fr", "Le Monde", "europe_west", "independent", 0.87, "french"),
    RegionSource("https://www.liberation.fr", "Liberation (FR)", "europe_west", "independent", 0.82, "french"),
    RegionSource("https://www.nrc.nl", "NRC (NL)", "europe_west", "independent", 0.85, "dutch"),
    RegionSource("https://www.volkskrant.nl", "Volkskrant (NL)", "europe_west", "independent", 0.83, "dutch"),
    RegionSource("https://euobserver.com", "EUobserver", "europe_west", "independent", 0.85, "english"),
    RegionSource("https://www.politico.eu", "Politico Europe", "europe_west", "independent", 0.85, "english"),
]


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL OSINT — cross-regional military, conflict, and OSINT aggregators
#
# These sources are NOT region-specific.  They complement any regional list for
# markets with military, conflict, or geopolitical exposure.  Accessible via
# get_global_osint_urls() — useful to inject for ANY conflict market regardless
# of the detected local_language.
#
# Tier breakdown:
#   independent   — rigorous, primary-source methods (Bellingcat, ISW, Oryx, ACLED)
#   grey          — faster but noisier (Telegram aggregators, pro-military blogs)
# ─────────────────────────────────────────────────────────────────────────────

_OSINT_GLOBAL: list[RegionSource] = [
    # ── Verified OSINT / investigative (high credibility) ─────────────────
    RegionSource("https://www.bellingcat.com", "Bellingcat (global OSINT)", "global_osint", "independent", 0.92, "english"),
    RegionSource("https://understandingwar.org", "ISW (theater analysis)", "global_osint", "independent", 0.88, "english", tg_channel="thestudyofwar"),
    RegionSource("https://www.oryxspioenkop.com", "Oryx (equipment losses tracker)", "global_osint", "independent", 0.87, "english"),
    RegionSource("https://acleddata.com/dashboard", "ACLED (conflict event database)", "global_osint", "independent", 0.88, "english"),
    RegionSource("https://warontherocks.com", "War on the Rocks (strategy analysis)", "global_osint", "independent", 0.85, "english"),
    RegionSource("https://www.thedrive.com/the-war-zone", "The War Zone (aviation/military)", "global_osint", "independent", 0.83, "english"),
    RegionSource("https://www.defenseone.com", "Defense One (US defense community)", "global_osint", "regional", 0.78, "english"),
    RegionSource("https://www.janes.com/defence-news", "Jane's Defence (mil intel)", "global_osint", "independent", 0.85, "english"),
    # ── Real-time conflict tracking ───────────────────────────────────────
    RegionSource("https://liveuamap.com", "Live UA Map (realtime conflict)", "global_osint", "grey", 0.65, "english"),
    RegionSource("https://t.me/s/militarymaps", "Military Maps (frontline global)", "global_osint", "grey", 0.60, "english", tg_channel="militarymaps"),
    RegionSource("https://t.me/s/osinttechnical", "OSINT Technical (mil tech tracker)", "global_osint", "grey", 0.55, "english", tg_channel="osinttechnical"),
    RegionSource("https://t.me/s/OSINTdefender", "OSINT Defender (global mil news)", "global_osint", "grey", 0.58, "english", tg_channel="OSINTdefender"),
    RegionSource("https://t.me/s/war_monitor", "War Monitor (global conflicts)", "global_osint", "grey", 0.52, "english", tg_channel="war_monitor"),
    # ── Broad aggregators (fast but noise; use for timing, not content) ───
    RegionSource("https://t.me/s/intelslava", "Intel Slava Z (global events agg.)", "global_osint", "grey", 0.38, "english", tg_channel="intelslava"),
    RegionSource("https://t.me/s/conflictnews", "Conflict News (aggregator)", "global_osint", "grey", 0.45, "english", tg_channel="conflictnews"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Master routing table: local_language → region sources
# ─────────────────────────────────────────────────────────────────────────────

_LANGUAGE_TO_SOURCES: dict[str, list[RegionSource]] = {
    # Russian / ex-Soviet space
    "russian":    _RU_UA,
    "ukrainian":  _RU_UA,
    "russian (tass, interfax)": _RU_UA,
    "ukrainian (ukrinform)":    _RU_UA,
    # Middle East — Iran/Israel focus (Persian/Hebrew)
    "persian":    _MIDDLE_EAST,
    "farsi":      _MIDDLE_EAST,
    "hebrew":     _MIDDLE_EAST,
    "persian (irna, presstv, tehran times)": _MIDDLE_EAST,
    # Arabic MENA — Yemen/Houthi, Gaza, Sudan, Libya, Syria, Iraq
    # (supersedes old _MIDDLE_EAST Arabic entry — more comprehensive for conflict zones)
    "arabic":                               _ARABIC_MENA,
    "arabic (al jazeera, arab news)":       _ARABIC_MENA,
    "arabic (irna)":                        _ARABIC_MENA,
    "arabic (mena)":                        _ARABIC_MENA,
    # East Asia
    "chinese":    _CHINA_TAIWAN,
    "korean":     _KOREA,
    # East Europe
    "romanian":   _EAST_EUROPE,
    "hungarian":  _EAST_EUROPE,
    "serbian":    _EAST_EUROPE,
    "polish":     _EAST_EUROPE,
    # Turkey
    "turkish":    _TURKEY,
    # South & Southeast Asia
    "urdu":       _SOUTH_ASIA,
    "dari":       _SOUTH_ASIA,
    "pashto":     _SOUTH_ASIA,
    "burmese":    _SOUTH_ASIA,
    "hindi":      _SOUTH_ASIA,
    # Francophone Africa (Sahel, Congo, Ethiopia)
    "french (africa)":         _FRANCOPHONE_AFRICA,
    "french (sahel)":          _FRANCOPHONE_AFRICA,
    "amharic":                 _FRANCOPHONE_AFRICA,
    "tigrinya":                _FRANCOPHONE_AFRICA,
    # Caucasus
    "armenian":    _CAUCASUS,
    "azerbaijani": _CAUCASUS,
    "georgian":    _CAUCASUS,
    # Western Europe (default French falls here unless Africa context detected)
    "german":     _EUROPE_WEST,
    "french":     _EUROPE_WEST,
    "dutch":      _EUROPE_WEST,
    "netherlands":_EUROPE_WEST,
    # Latin America
    "portuguese": _LATAM,
    "spanish":    _LATAM,
    "portuguese (brazil)": _LATAM,
    # Global OSINT — cross-regional military/conflict sources
    # Access via get_global_osint_urls() or get_seed_urls_for_language("osint")
    "osint":      _OSINT_GLOBAL,
    "military":   _OSINT_GLOBAL,
    "conflict":   _OSINT_GLOBAL,
}


def get_sources_for_language(
    language: str,
    *,
    exclude_tiers: list[str] | None = None,
    max_sources: int = 12,
) -> list[RegionSource]:
    """Return curated RegionSource list for a detected language.

    Args:
        language: value of local_language field from Command G (e.g. "russian")
        exclude_tiers: tiers to skip (default: excludes "state" to avoid boosting propaganda)
        max_sources: cap on number of sources returned (independent/opposition first)

    Returns:
        List of RegionSource ordered by credibility descending.
    """
    if exclude_tiers is None:
        exclude_tiers = ["state"]  # never auto-seed state media into Forager

    key = language.lower().strip()
    sources = _LANGUAGE_TO_SOURCES.get(key) or []

    if not sources:
        # Try first word of composite language descriptor
        first_word = key.split()[0]
        sources = _LANGUAGE_TO_SOURCES.get(first_word) or []

    filtered = [s for s in sources if s.tier not in exclude_tiers]
    filtered.sort(key=lambda s: s.credibility, reverse=True)
    return filtered[:max_sources]


def get_seed_urls_for_language(
    language: str,
    *,
    max_sources: int = 10,
    include_telegram: bool = True,
    exclude_tiers: list[str] | None = None,
) -> list[tuple[str, float, str]]:
    """Return (url, credibility_score, tier) tuples for direct Forager injection.

    Telegram channels are included as t.me/s/{channel} URLs — trafilatura can
    extract text from these static HTML pages without any auth.

    Args:
        language: local_language value from Command G
        max_sources: cap on news sites (Telegram channels are in addition)
        include_telegram: whether to add t.me/s/ URLs for channels
        exclude_tiers: tiers to skip (default excludes "state")

    Returns:
        List of (url, credibility_score, tier) ordered by credibility desc.
    """
    sources = get_sources_for_language(
        language,
        exclude_tiers=exclude_tiers,
        max_sources=max_sources,
    )

    result: list[tuple[str, float, str]] = []
    seen_urls: set[str] = set()

    for src in sources:
        # Add web URL
        if src.url not in seen_urls:
            result.append((src.url, src.credibility, src.tier))
            seen_urls.add(src.url)

        # Add Telegram channel as t.me/s/ URL (separate from the main URL)
        if include_telegram and src.tg_channel:
            tg_url = f"https://t.me/s/{src.tg_channel}"
            if tg_url not in seen_urls:
                result.append((tg_url, src.credibility, f"telegram:{src.tier}"))
                seen_urls.add(tg_url)

    return result


def get_global_osint_urls(
    *,
    max_sources: int = 10,
    include_telegram: bool = True,
    min_credibility: float = 0.0,
    tiers: list[str] | None = None,
) -> list[tuple[str, float, str]]:
    """Return cross-regional OSINT sources for any military/conflict market.

    These sources complement region-specific sources — inject alongside
    get_seed_urls_for_language() for markets with geopolitical/conflict exposure.

    Args:
        max_sources:       cap on sources returned (highest credibility first)
        include_telegram:  whether to add t.me/s/ URLs for TG channels
        min_credibility:   only return sources at or above this threshold
        tiers:             whitelist of tiers to include (None = all except state)

    Returns:
        List of (url, credibility_score, tier) ordered by credibility desc.
    """
    allowed_tiers = set(tiers) if tiers else {"independent", "regional", "grey", "blogger"}
    sources = [s for s in _OSINT_GLOBAL
               if s.tier in allowed_tiers and s.credibility >= min_credibility]
    sources.sort(key=lambda s: s.credibility, reverse=True)

    result: list[tuple[str, float, str]] = []
    seen_urls: set[str] = set()
    for src in sources[:max_sources]:
        if src.url not in seen_urls:
            result.append((src.url, src.credibility, src.tier))
            seen_urls.add(src.url)
        if include_telegram and src.tg_channel:
            tg_url = f"https://t.me/s/{src.tg_channel}"
            if tg_url not in seen_urls:
                result.append((tg_url, src.credibility, f"telegram:{src.tier}"))
                seen_urls.add(tg_url)
    return result


def get_propaganda_note(language: str) -> str:
    """Return a short reminder for the Forager to include in research context."""
    # Use max_sources=999 so state/blogger sources (lowest credibility) aren't cut
    sources = get_sources_for_language(language, exclude_tiers=[], max_sources=999)
    state_names = [s.name for s in sources if s.tier == "state"]
    blogger_names = [s.name for s in sources if s.tier == "blogger"]
    grey_names = [s.name for s in sources if s.tier == "grey"]
    parts: list[str] = []
    if state_names:
        parts.append(f"STATE MEDIA (official position only, do not cite as fact): {', '.join(state_names)}")
    if blogger_names:
        parts.append(f"WAR BLOGGERS (leads only, cross-check required): {', '.join(blogger_names)}")
    if grey_names:
        parts.append(f"GREY SOURCES (editorially biased, cross-check with independent tier): {', '.join(grey_names)}")
    return ". ".join(parts) if parts else ""
