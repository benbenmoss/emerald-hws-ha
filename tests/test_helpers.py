"""Tests for the pure exception-classification helpers."""

from custom_components.emeraldenergy.helpers import (
    is_awscrt_straddle_error,
    is_invalid_credentials_error,
)


def _raise_from(inner: BaseException) -> BaseException:
    """Return `inner` wrapped as `raise ... from inner`, with a real traceback."""
    try:
        try:
            raise inner
        except BaseException as cause:
            raise RuntimeError("wrapper") from cause
    except RuntimeError as outer:
        return outer


def test_straddle_error_matches_certificate_source_attribute_error():
    """AttributeError mentioning _certificate_source is the straddle signature."""
    err = _raise_from(
        AttributeError(
            "'ClientTlsContext' object has no attribute '_certificate_source'"
        )
    )
    assert is_awscrt_straddle_error(err)


def test_straddle_error_ignores_unrelated_exceptions():
    """Unrelated errors, and the right message on the wrong type, don't match."""
    assert not is_awscrt_straddle_error(ValueError("something else"))
    assert not is_awscrt_straddle_error(AttributeError("unrelated attribute error"))
    # Right message, wrong type: only AttributeError should match.
    assert not is_awscrt_straddle_error(
        ValueError("has no attribute '_certificate_source'")
    )


def test_invalid_credentials_error_matches_exact_message():
    """The exact bare-Exception message from getLoginToken is recognised."""
    err = Exception("Failed to log into Emerald API with supplied credentials")
    assert is_invalid_credentials_error(err)


def test_invalid_credentials_error_ignores_other_messages():
    """Other bare exceptions from the library aren't mistaken for bad creds."""
    assert not is_invalid_credentials_error(
        Exception("Unable to fetch properties from Emerald API")
    )
    assert not is_invalid_credentials_error(TimeoutError("timed out"))


def test_invalid_credentials_error_walks_cause_chain():
    """The check follows __cause__, not just the outermost exception."""
    err = _raise_from(
        Exception("Failed to log into Emerald API with supplied credentials")
    )
    assert is_invalid_credentials_error(err)
