from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetList:
    category: str
    name: str
    url: str
    format: str  # domains|hosts
    list_type: str  # block|allow
    description: str


# Initial starter presets (will be expanded with researched popular lists).
PRESET_LISTS: list[PresetList] = [
    PresetList(
        category="Ads/Tracking",
        name="StevenBlack Unified (ads+malware)",
        url="https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        format="hosts",
        list_type="block",
        description="Popular consolidated hosts file. Good baseline with low maintenance.",
    ),
    PresetList(
        category="Ads/Tracking",
        name="AdAway (ads)",
        url="https://adaway.org/hosts.txt",
        format="hosts",
        list_type="block",
        description="Conservative, well-maintained ad blocking hosts file.",
    ),
    PresetList(
        category="Ads/Tracking",
        name="AdGuard DNS filter (hosts)",
        url="https://v.firebog.net/hosts/AdguardDNS.txt",
        format="hosts",
        list_type="block",
        description="AdGuard’s DNS-focused blocklist in hosts format.",
    ),
    PresetList(
        category="Ads/Tracking",
        name="Peter Lowe (ad/tracking)",
        url="https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0&mimetype=plaintext",
        format="hosts",
        list_type="block",
        description="Long-running ad server list (low breakage).",
    ),
    PresetList(
        category="Malware",
        name="URLHaus (malware)",
        url="https://urlhaus.abuse.ch/downloads/hostfile/",
        format="hosts",
        list_type="block",
        description="Malware distribution domains (frequently updated).",
    ),
    PresetList(
        category="Malware",
        name="ThreatFox (malware)",
        url="https://threatfox.abuse.ch/downloads/hostfile/",
        format="hosts",
        list_type="block",
        description="Threat intel feed for malware domains.",
    ),
    PresetList(
        category="Phishing/Scams",
        name="Phishing Army (extended)",
        url="https://phishing.army/download/phishing_army_blocklist_extended.txt",
        format="domains",
        list_type="block",
        description="Phishing and scam domains.",
    ),
    PresetList(
        category="Telemetry",
        name="Windows telemetry (WindowsSpyBlocker)",
        url="https://raw.githubusercontent.com/crazy-max/WindowsSpyBlocker/master/data/hosts/spy.txt",
        format="hosts",
        list_type="block",
        description="Blocks known Windows telemetry domains.",
    ),
    PresetList(
        category="Adult",
        name="StevenBlack (porn extension)",
        url="https://raw.githubusercontent.com/StevenBlack/hosts/master/extensions/porn/hosts",
        format="hosts",
        list_type="block",
        description="Adult content extension maintained by StevenBlack.",
    ),
]
