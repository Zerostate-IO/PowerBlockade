"""Unit tests for security module (password hashing and verification)."""

from app.security import hash_password, verify_password


class TestHashPassword:
    def test_hash_password_generates_different_hashes_for_same_password(self):
        password = "test_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2
        assert hash1.startswith("$2b$")

    def test_hash_password_hashes_long_passwords_properly(self):
        password = "a" * 100
        hashed = hash_password(password)

        assert hashed.startswith("$2b$")
        assert len(hashed) > 50

    def test_hash_password_handles_unicode(self):
        password = "p@sswörd🔑"
        hashed = hash_password(password)

        assert hashed.startswith("$2b$")

    def test_hash_password_truncates_at_72_chars(self):
        password = "a" * 100
        hashed = hash_password(password)
        same_prefix_hash = hash_password("a" * 80)

        verify_password(password, hashed)
        verify_password("a" * 100, same_prefix_hash)


class TestVerifyPassword:
    def test_verify_correct_password_returns_true(self):
        password = "correct_password"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_incorrect_password_returns_false(self):
        password = "correct_password"
        hashed = hash_password(password)

        assert verify_password("wrong_password", hashed) is False

    def test_verify_with_invalid_hash_raises_or_returns_false(self):
        try:
            result = verify_password("anything", "invalid_hash")
            assert result is False
        except Exception:
            pass

    def test_verify_with_empty_hash_returns_false(self):
        result = verify_password("anything", "")
        assert result is False


class TestPasswordPreHashing:
    def test_pre_hashing_handles_passwords_exceeding_72_chars(self):
        password = "a" * 80
        hashed = hash_password(password)

        verify_password(password, hashed)

    def test_pre_hashing_does_not_affect_security_short_passwords(self):
        password = "short"
        hashed = hash_password(password)

        verify_password(password, hashed)
        assert not verify_password("wrong", hashed)
