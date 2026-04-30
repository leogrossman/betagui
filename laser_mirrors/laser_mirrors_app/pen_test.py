from __future__ import annotations

from .models import PenTestPoint


def build_pen_test_sequence(
    motor_key: str,
    reference_steps: float,
    start_steps: float,
    stop_steps: float,
    increment_steps: float,
    cycles_per_level: int,
    dwell_s: float,
) -> list[PenTestPoint]:
    """Build a cautious back-and-forth controller stress-test sequence.

    The sequence always returns to the captured reference after each level so a
    controller or IOC failure happens as close as possible to the original
    working point.
    """

    start = max(0.1, float(start_steps))
    stop = max(start, float(stop_steps))
    increment = max(0.1, float(increment_steps))
    cycles = max(1, int(cycles_per_level))
    dwell = max(0.0, float(dwell_s))
    points: list[PenTestPoint] = []
    amplitude = start
    index = 0
    while amplitude <= stop + 1e-9:
        for cycle in range(cycles):
            for direction, note in (
                (+1.0, "forward probe"),
                (-1.0, "reverse probe"),
                (0.0, "return to reference"),
            ):
                target = reference_steps + direction * amplitude
                points.append(
                    PenTestPoint(
                        index=index,
                        motor_key=motor_key,
                        amplitude_steps=amplitude,
                        target_steps=target,
                        dwell_s=dwell,
                        note=f"cycle {cycle + 1}/{cycles}: {note}",
                    )
                )
                index += 1
        amplitude += increment
    return points

