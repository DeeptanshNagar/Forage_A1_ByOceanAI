"""Token / wall-clock budget with a hard cap. The LLM client checks it before every call."""
from __future__ import annotations

import time


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, max_tokens: int = 0, max_seconds: float = 0.0):
        self.max_tokens = max_tokens or 0
        self.max_seconds = max_seconds or 0.0
        self.tokens_used = 0
        self.started = time.time()
        self.exceeded_reason = ""

    def add(self, tokens: int) -> None:
        self.tokens_used += tokens

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def remaining_fraction(self) -> float:
        fr = [1.0]
        if self.max_tokens:
            fr.append(1 - self.tokens_used / self.max_tokens)
        if self.max_seconds:
            fr.append(1 - self.elapsed / self.max_seconds)
        return max(0.0, min(fr))

    def check(self) -> None:
        if self.max_tokens and self.tokens_used >= self.max_tokens:
            self.exceeded_reason = f"token budget exhausted ({self.tokens_used} >= {self.max_tokens})"
            raise BudgetExceeded(self.exceeded_reason)
        if self.max_seconds and self.elapsed >= self.max_seconds:
            self.exceeded_reason = f"time budget exhausted ({self.elapsed:.0f}s >= {self.max_seconds:.0f}s)"
            raise BudgetExceeded(self.exceeded_reason)

    def to_dict(self) -> dict:
        return {
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
            "tokens_used": self.tokens_used,
            "elapsed_s": round(self.elapsed, 2),
            "exceeded": bool(self.exceeded_reason),
            "exceeded_reason": self.exceeded_reason,
        }
