"""
Resilience Layer for Provider Management
Implements circuit breakers, connection cooldown, and model lockout mechanisms
"""
import time
import threading
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    CLOSED = "closed"      # Normal operation
    HALF_OPEN = "half_open"  # Testing if service is recovered
    OPEN = "open"          # Short-circuiting requests


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5          # Number of failures before opening
    timeout_duration: float = 60.0      # Seconds to wait before trying half-open
    expected_exception: type = Exception # Exception type that counts as failure
    success_threshold: int = 3          # Number of successes in half-open to close


@dataclass
class ConnectionPoolConfig:
    """Configuration for connection pooling"""
    max_connections: int = 100
    max_connections_per_host: int = 30
    keepalive_timeout: float = 30.0
    force_close: bool = False


@dataclass
class ModelLockoutConfig:
    """Configuration for model lockout (temporary unavailability)"""
    lockout_duration: float = 300.0     # Seconds to lockout a model after repeated failures
    failure_threshold: int = 3          # Failures before lockout
    reset_on_success: bool = True       # Reset failure count on success


@dataclass
class ProviderMetrics:
    """Metrics tracking for a provider"""
    provider_id: str
    total_requests: int = 0
    failed_requests: int = 0
    successful_requests: int = 0
    total_latency: float = 0.0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    lockout_until: float = 0.0          # Timestamp until which provider is locked out
    circuit_breaker_state: CircuitBreakerState = CircuitBreakerState.CLOSED
    circuit_breaker_failures: int = 0
    circuit_breaker_last_state_change: float = field(default_factory=time.time)
    circuit_breaker_success_count: int = 0
    
    def record_success(self, latency: float):
        """Record a successful request"""
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency += latency
        self.last_success_time = time.time()
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        
        # Update circuit breaker
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            self.circuit_breaker_success_count += 1
        elif self.circuit_breaker_state == CircuitBreakerState.CLOSED:
            self.circuit_breaker_failures = 0  # Reset on success
    
    def record_failure(self, latency: float = 0.0):
        """Record a failed request"""
        self.total_requests += 1
        self.failed_requests += 1
        self.total_latency += latency
        self.last_failure_time = time.time()
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        
        # Update circuit breaker
        if self.circuit_breaker_state == CircuitBreakerState.CLOSED:
            self.circuit_breaker_failures += 1
        elif self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            # Any failure in half-open goes back to open
            self.circuit_breaker_state = CircuitBreakerState.OPEN
            self.circuit_breaker_last_state_change = time.time()
            self.circuit_breaker_success_count = 0
    
    def get_failure_rate(self) -> float:
        """Get failure rate as ratio"""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests
    
    def get_average_latency(self) -> float:
        """Get average latency in seconds"""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency / self.successful_requests
    
    def is_available(self, config: CircuitBreakerConfig, lockout_config: ModelLockoutConfig) -> bool:
        """Check if provider is available based on circuit breaker and lockout"""
        now = time.time()
        
        # Check lockout
        if self.lockout_until > now:
            return False
        
        # Check circuit breaker
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            # Check if timeout period has elapsed
            if now - self.circuit_breaker_last_state_change > config.timeout_duration:
                # Try half-open
                self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                self.circuit_breaker_last_state_change = now
                self.circuit_breaker_success_count = 0
                logger.info(f"Circuit breaker for {self.provider_id} moving to HALF_OPEN")
                return True
            else:
                # Still open, short-circuit
                return False
        
        # Half-open and closed states allow requests (half-open will be evaluated per request)
        return True
    
    def on_state_change(self, new_state: CircuitBreakerState):
        """Handle circuit breaker state change"""
        old_state = self.circuit_breaker_state
        self.circuit_breaker_state = new_state
        self.circuit_breaker_last_state_change = time.time()
        
        if new_state == CircuitBreakerState.OPEN:
            logger.warning(f"Circuit breaker for {self.provider_id} opened after {self.circuit_breaker_failures} failures")
        elif new_state == CircuitBreakerState.HALF_OPEN:
            logger.info(f"Circuit breaker for {self.provider_id} half-open, testing recovery")
        elif new_state == CircuitBreakerState.CLOSED:
            logger.info(f"Circuit breaker for {self.provider_id} closed, recovered")


class ResilienceManager:
    """Manages resilience mechanisms for providers"""
    
    def __init__(self,
                 circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
                 connection_pool_config: Optional[ConnectionPoolConfig] = None,
                 model_lockout_config: Optional[ModelLockoutConfig] = None):
        """
        Initialize resilience manager
        
        Args:
            circuit_breaker_config: Configuration for circuit breaker
            connection_pool_config: Configuration for connection pooling
            model_lockout_config: Configuration for model lockout
        """
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        self.connection_pool_config = connection_pool_config or ConnectionPoolConfig()
        self.model_lockout_config = model_lockout_config or ModelLockoutConfig()
        
        # Provider metrics storage
        self._metrics: Dict[str, ProviderMetrics] = {}
        self._lock = threading.RLock()
        
        # Connection pools (simplified - in practice would use actual HTTP connection pools)
        self._connection_pools: Dict[str, Any] = {}
    
    def get_metrics(self, provider_id: str) -> ProviderMetrics:
        """Get or create metrics for a provider"""
        with self._lock:
            if provider_id not in self._metrics:
                self._metrics[provider_id] = ProviderMetrics(provider_id=provider_id)
            return self._metrics[provider_id]
    
    def record_success(self, provider_id: str, latency: float):
        """Record a successful request for a provider"""
        metrics = self.get_metrics(provider_id)
        metrics.record_success(latency)
        
        # Check for circuit breaker state change
        config = self.circuit_breaker_config
        if metrics.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            if metrics.consecutive_successes >= config.success_threshold:
                metrics.on_state_change(CircuitBreakerState.CLOSED)
    
    def record_failure(self, provider_id: str, latency: float = 0.0):
        """Record a failed request for a provider"""
        metrics = self.get_metrics(provider_id)
        metrics.record_failure(latency)
        
        # Check for circuit breaker state change
        config = self.circuit_breaker_config
        if metrics.circuit_breaker_state == CircuitBreakerState.CLOSED:
            if metrics.consecutive_failures >= config.failure_threshold:
                metrics.on_state_change(CircuitBreakerState.OPEN)
        
        # Check for model lockout
        lockout_config = self.model_lockout_config
        if metrics.consecutive_failures >= lockout_config.failure_threshold:
            metrics.lockout_until = time.time() + lockout_config.lockout_duration
            logger.warning(f"Provider {provider_id} locked out for {lockout_config.lockout_duration}s due to {metrics.consecutive_failures} consecutive failures")
    
    def is_provider_available(self, provider_id: str) -> bool:
        """Check if a provider is available for use"""
        metrics = self.get_metrics(provider_id)
        return metrics.is_available(self.circuit_breaker_config, self.model_lockout_config)
    
    def get_provider_health_score(self, provider_id: str) -> float:
        """Get health score for a provider (0.0 to 1.0)"""
        metrics = self.get_metrics(provider_id)
        
        # Base health on success rate and circuit breaker state
        success_rate = 1.0 - metrics.get_failure_rate()
        
        # Circuit breaker penalty
        cb_penalty = 1.0
        if metrics.circuit_breaker_state == CircuitBreakerState.OPEN:
            cb_penalty = 0.0
        elif metrics.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            cb_penalty = 0.5
        
        # Lockout penalty
        lockout_penalty = 0.0 if metrics.lockout_until > time.time() else 1.0
        
        # Combine factors
        health = success_rate * cb_penalty * lockout_penalty
        return max(0.0, min(1.0, health))
    
    def get_provider_latency_score(self, provider_id: str) -> float:
        """Get latency score for a provider (lower latency = higher score)"""
        metrics = self.get_metrics(provider_id)
        avg_latency = metrics.get_average_latency()
        
        # Convert latency to score (inverse relationship, with smoothing)
        # Assuming 1 second is acceptable, 10 seconds is poor
        if avg_latency <= 0:
            return 1.0
        # Normalize: 1/(1 + latency) gives 1.0 at 0 latency, 0.5 at 1s latency, 0.09 at 10s latency
        return 1.0 / (1.0 + avg_latency)
    
    def get_provider_quota_score(self, provider_id: str) -> float:
        """Get quota/availability score for a provider"""
        metrics = self.get_metrics(provider_id)
        
        # Base quota headroom on inverse failure rate and lockout status
        # In a real implementation, this would come from provider-specific quota APIs
        quota_headroom = 1.0 - min(metrics.get_failure_rate(), 0.9)  # Cap at 0.9 to avoid 0
        
        # Apply lockout penalty
        if metrics.lockout_until > time.time():
            quota_headroom = 0.0
        
        return max(0.0, min(1.0, quota_headroom))
    
    def cleanup_old_metrics(self, max_age_hours: float = 24.0):
        """Clean up metrics for providers not seen recently"""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._lock:
            to_remove = [
                pid for pid, metrics in self._metrics.items()
                if metrics.last_failure_time < cutoff and metrics.last_success_time < cutoff
            ]
            for pid in to_remove:
                del self._metrics[pid]
                logger.debug(f"Cleaned up metrics for provider {pid}")
    
    def get_all_metrics(self) -> Dict[str, ProviderMetrics]:
        """Get a copy of all provider metrics"""
        with self._lock:
            return self._metrics.copy()


# Global resilience manager instance
_resilience_manager: Optional[ResilienceManager] = None


def get_resilience_manager() -> ResilienceManager:
    """Get or create the global resilience manager"""
    global _resilience_manager
    if _resilience_manager is None:
        _resilience_manager = ResilienceManager()
    return _resilience_manager


# Decorator for adding resilience to provider calls
def with_resilience(provider_id: str):
    """
    Decorator to add resilience metrics tracking to provider methods
    
    Usage:
        @with_resilience("openai")
        async def stream_completion(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            resilience_manager = get_resilience_manager()
            
            try:
                result = await func(*args, **kwargs)
                latency = time.time() - start_time
                resilience_manager.record_success(provider_id, latency)
                return result
            except Exception as e:
                latency = time.time() - start_time
                resilience_manager.record_failure(provider_id, latency)
                raise
        
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            resilience_manager = get_resilience_manager()
            
            try:
                result = func(*args, **kwargs)
                latency = time.time() - start_time
                resilience_manager.record_success(provider_id, latency)
                return result
            except Exception as e:
                latency = time.time() - start_time
                resilience_manager.record_failure(provider_id, latency)
                raise
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator