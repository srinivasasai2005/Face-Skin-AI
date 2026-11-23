import pytest

from security import IntegrityError, RateLimiter, sha256_hex, verify_sha256


def test_verify_sha256_accepts_the_matching_bytes():
    verify_sha256(b"model bytes", sha256_hex(b"model bytes"), "model")


def test_verify_sha256_rejects_any_change():
    good = sha256_hex(b"model bytes")
    with pytest.raises(IntegrityError, match="model failed its integrity check"):
        verify_sha256(b"model bytez", good, "model")
    with pytest.raises(IntegrityError):
        verify_sha256(b"", good)


def test_verify_sha256_is_case_and_whitespace_tolerant_about_the_pinned_value():
    verify_sha256(b"x", " " + sha256_hex(b"x").upper() + "\n")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_rate_limiter_blocks_after_the_limit_and_recovers():
    clock = FakeClock()
    rl = RateLimiter(limit=3, window=60, clock=clock)
    assert [rl.allow() for _ in range(3)] == [True, True, True]
    assert rl.allow() is False and rl.retry_after() == pytest.approx(60)
    clock.now = 59
    assert rl.allow() is False and rl.retry_after() == pytest.approx(1)
    clock.now = 60.1
    assert rl.allow() is True  # the oldest event has aged out


def test_rate_limiter_does_not_count_rejected_attempts():
    clock = FakeClock()
    rl = RateLimiter(limit=1, window=10, clock=clock)
    assert rl.allow()
    for _ in range(50):
        assert not rl.allow()
    clock.now = 10.5
    assert rl.allow()  # hammering while blocked must not extend the block


# --- model integrity & overload protection (model.py) ---------------------------

import model


@pytest.fixture
def fresh_loader():
    model.get_learner.cache_clear()
    yield
    model.get_learner.cache_clear()


def test_the_pinned_fingerprint_matches_the_shipped_model():
    # If this fails after you replaced export.pkl on purpose, run `python model.py`
    # and paste the printed value into MODEL_SHA256.
    assert sha256_hex(model.MODEL_PATH.read_bytes()) == model.MODEL_SHA256


def test_a_tampered_model_file_is_refused_before_anything_is_unpickled(tmp_path, monkeypatch, fresh_loader):
    evil = tmp_path / "export.pkl"
    # A pickle whose __reduce__ would run code if it were ever loaded.
    import pickle, os

    class Boom:
        def __reduce__(self):
            return (os.system, ("echo pwned > /dev/null",))

    evil.write_bytes(pickle.dumps(Boom()))
    monkeypatch.setattr(model, "MODEL_PATH", evil)
    with pytest.raises(IntegrityError, match="integrity check"):
        model.get_learner()


def test_overload_is_refused_instead_of_queued_forever(monkeypatch):
    import threading
    monkeypatch.setattr(model, "_queue_slots", threading.BoundedSemaphore(0))
    with pytest.raises(model.BusyError):
        model.analyze_bytes(b"irrelevant")


def test_queue_slot_is_released_even_when_the_image_is_bad():
    from image_utils import ImageError
    before = model._queue_slots._value
    for _ in range(model.MAX_QUEUED_ANALYSES + 3):  # would deadlock/refuse if slots leaked
        with pytest.raises(ImageError):
            model.analyze_bytes(b"not an image")
    assert model._queue_slots._value == before
