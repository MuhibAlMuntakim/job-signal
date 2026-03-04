import time
from loguru import logger

class RateLimiter:
    """
    Token bucket rate limiter.
    Tracks Groq API calls and pauses 
    automatically when approaching 30 RPM.
    Uses 25 as safe limit (5 call buffer).
    """
    def __init__(self, max_calls_per_minute: int = 25):
        self.max_calls = max_calls_per_minute
        self.calls = []

    def wait_if_needed(self):
        """
        Call this BEFORE every Groq API call.
        Checks calls made in last 60 seconds.
        If at limit, sleeps until oldest 
        call expires.
        """
        now = time.time()
        self.calls = [t for t in self.calls 
                      if now - t < 60]
        
        if len(self.calls) >= self.max_calls:
            oldest_call = self.calls[0]
            wait_seconds = 60 - (now - oldest_call) + 1
            logger.warning(
                f"Rate limit approaching "
                f"({len(self.calls)}/{self.max_calls} "
                f"calls in last 60s). "
                f"Pausing {wait_seconds:.1f}s..."
            )
            time.sleep(wait_seconds)
        
        self.calls.append(time.time())

# Single shared instance — import this everywhere
rate_limiter = RateLimiter(max_calls_per_minute=25)
