"""Independent monotonic timers; disconnection pauses elapsed connected time."""
import math


def minutes(value, fallback):
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 < value <= 10080 else fallback
    except (TypeError, ValueError):
        return fallback


class Reminders:
    def __init__(self):
        self.elapsed = dict(water=0.0, activity=0.0)
        self.last = None
        self.connected = False

    def advance(self, now, connected, settings):
        delta = max(0, now - self.last) if self.last is not None and self.connected and connected else 0
        self.last, self.connected = now, connected
        due = []
        for key, (enabled, interval) in settings.items():
            if not enabled:
                self.elapsed[key] = 0
            elif connected:
                self.elapsed[key] += delta
                if self.elapsed[key] >= interval * 60:
                    due.append(key)
        return due

    def reset(self, key):
        self.elapsed[key] = 0

    def remaining(self, key, interval):
        return max(0, math.ceil(interval * 60 - self.elapsed[key]))
