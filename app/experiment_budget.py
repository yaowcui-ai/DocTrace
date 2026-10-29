"""A rate-limit circuit is reset only by an explicit new experiment invocation."""


class ProviderBudget:
    def __init__(self, *, max_attempts, min_interval=30):
        if max_attempts < 1 or min_interval < 0:
            raise ValueError('Invalid provider budget')
        self.maximum, self.interval = max_attempts, min_interval
        self.attempts, self.last, self.blocked = 0, None, False

    def reserve(self, *, now):
        if self.blocked:
            raise RuntimeError('rate_limited')
        if self.attempts >= self.maximum:
            raise RuntimeError('budget_exhausted')
        delay = max(0, self.last+self.interval-now) if self.last is not None else 0
        self.last = now+delay
        self.attempts += 1
        return delay

    def observe(self, status):
        if status == 429:
            self.blocked = True
