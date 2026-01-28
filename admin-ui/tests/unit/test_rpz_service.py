"""Unit tests for RPZ blocklist parsing service."""

import pytest

from app.services.rpz import parse_blocklist_text


class TestParseBlocklistText:
    def test_hosts_format(self):
        text = """# Comment
0.0.0.0 ad.example.com
0.0.0.0 tracker.example.com
0.0.0.0 malware.example.com
"""
        domains = parse_blocklist_text(text, "hosts")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains
        assert "malware.example.com" in domains

    def test_hosts_format_with_127_0_0_1(self):
        text = """127.0.0.1 ad.example.com
127.0.0.1 tracker.example.com
"""
        domains = parse_blocklist_text(text, "hosts")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains

    def test_plain_domains_format(self):
        text = """ad.example.com
tracker.example.com
malware.example.com
"""
        domains = parse_blocklist_text(text, "domains")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains
        assert "malware.example.com" in domains

    def test_plain_domains_format_with_blank_lines(self):
        text = """ad.example.com

tracker.example.com

malware.example.com
"""
        domains = parse_blocklist_text(text, "domains")
        assert len(domains) == 3

    def test_adblock_format_simple(self):
        text = """||ad.example.com^
||tracker.example.com^
||malware.example.com^
"""
        domains = parse_blocklist_text(text, "adblock")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains

    def test_adblock_format_with_wildcards(self):
        text = """*ad*.example.com
*tracker.example.com*
"""
        domains = parse_blocklist_text(text, "adblock")
        assert len(domains) == 2

    def test_ignores_comments(self):
        text = """# This is a comment
0.0.0.0 ad.example.com
# Another comment
0.0.0.0 tracker.example.com
"""
        domains = parse_blocklist_text(text, "hosts")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains
        assert len(domains) == 2

    def test_invalid_lines_skipped(self):
        text = """invalid line without domain
0.0.0.0 valid.example.com
another invalid line
"""
        domains = parse_blocklist_text(text, "hosts")
        assert "valid.example.com" in domains
        assert len(domains) == 1

    def test_empty_text_returns_empty_set(self):
        domains = parse_blocklist_text("", "hosts")
        assert len(domains) == 0

    def test_deduplicates_domains(self):
        text = """domain.example.com
domain.example.com
another-example.com
"""
        domains = parse_blocklist_text(text, "domains")
        assert len(domains) == 2
        assert "domain.example.com" in domains
        assert "another-example.com" in domains

    def test_trims_whitespace(self):
        text = """  ad.example.com  
  tracker.example.com  """
        domains = parse_blocklist_text(text, "domains")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains

    def test_lowercase_normalization(self):
        text = """AD.EXAMPLE.COM
Tracker.Example.COM
"""
        domains = parse_blocklist_text(text, "domains")
        assert "ad.example.com" in domains
        assert "tracker.example.com" in domains
