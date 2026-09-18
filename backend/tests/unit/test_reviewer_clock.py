"""Phase 7 Part 1.4: reviewer actions use the demo reviewer clock, DEMO_CLOCK + elapsed wall time (#33)."""
from datetime import timedelta

from sentinel.api.services.review import DemoReviewerClock, ReviewService
from sentinel.settings import DEMO_CLOCK


def test_starts_at_the_demo_clock_and_is_monotonic():
    clock = DemoReviewerClock()
    readings = [clock() for _ in range(50)]
    assert DEMO_CLOCK <= readings[0] < DEMO_CLOCK + timedelta(seconds=30)
    assert readings == sorted(readings)
    assert all(r.tzinfo is not None for r in readings)


def test_elapsed_time_is_preserved(monkeypatch):
    import sentinel.api.services.review as review
    now = [1000.0]
    monkeypatch.setattr(review.time, "monotonic", lambda: now[0])
    clock = DemoReviewerClock()
    now[0] += 125.5
    assert clock() == DEMO_CLOCK + timedelta(seconds=125.5)


def test_review_service_defaults_to_the_demo_reviewer_clock():
    service = ReviewService(engine=None)
    assert isinstance(service.clock, DemoReviewerClock)

    def fixed():
        return DEMO_CLOCK

    assert ReviewService(engine=None, clock=fixed).clock is fixed
