"""
Resilience Layer for Provider Management
Implements circuit breakers, connection cooldown, and model lockout mechanisms
"""
import time
import threading
from enum import Enum
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class FailureType(Enum):
    """Types of failures that can trigger resilience mechanisms"""
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    MODEL_NOT_FOUND = "model_not_found"
    AUTHENTICATION_ERROR = "authentication_error"
    UNKNOWN = "unknown"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5          # Number of failures before opening
    recovery_timeout: float = 60.0      # Seconds before trying half-open
    expected_exception: type = Exception  # Exception type to catch
    success_threshold: int = 3          # Successes needed to close from half-open
    timeout: float = 30.0               # Request timeout in seconds


@dataclass
class ProviderMetrics:
    """Metrics tracked for each provider"""
    provider_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeouts: int = 0
    connection_errors: int = 0
    rate_limits: int = 0
    server_errors: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    cooldown_until: float = 0.0        # Timestamp until which to skip this provider
    lockout_until: float = 0.0         # Timestamp until which model is locked out
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.failed_requests / self.total_requests) * 100
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage"""
        return 100.0 - self.failure_rate
    
    @property
    def is_available(self) -> bool:
        """Check if provider is currently available (not in cooldown/lockout)"""
        now = time.time()
        return now >= self.cooldown_until and now >= self.lockout_until
    
    @property
    def is_in_cooldown(self) -> bool:
        """Check if provider is in cooldown period"""
        return time.time() < self.cooldown_until
    
    @property
    def is_locked_out(self) -> bool:
        """Check if provider is locked out"""
        return time.time() < self.lockout_until


class CircuitBreaker:
    """Circuit breaker implementation for provider resilience"""
    
    def __init__(self, provider_name: str, config: CircuitBreakerConfig):
        self.provider_name = provider_name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self._lock = threading.RLock()
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._set_state(CircuitState.HALF_OPEN)
                else:
                    raise Exception(f"Circuit breaker OPEN for {self.provider_name}")
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except self.config.expected_exception as e:
                self._on_failure()
                raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        return (time.time() - self.last_state_change) >= self.config.recovery_timeout
    
    def _on_success(self):
        """Handle successful request"""
        self.failure_count = 0
        self.success_count += 1
        
        if self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.config.success_threshold:
                self._set_state(CircuitState.CLOSED)
    
    def _on_failure(self):
        """Handle failed request"""
        self.failure_count += 1
        self.success_count = 0
        
        if self.state == CircuitState.HALF_OPEN:
            self._set_state(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self._set_state(CircuitState.OPEN)
    
    def _set_state(self, state: CircuitState):
        """Set circuit breaker state"""
        old_state = self.state
        self.state = state
        self.last_state_change = time.time()
        
        logger.info(
            f"Circuit breaker for {self.provider_name}: {old_state.value} -> {state.value}"
        )
        
        # Reset counters on state change
        if state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
        elif state == CircuitState.HALF_OPEN:
            self.success_count = 0
            # failure_count remains as is for half-open transition


class ConnectionCooldownManager:
    """Manages connection cooldown periods for providers"""
    
    def __init__(self, default_cooldown: float = 30.0):
        self.default_cooldown = default_cooldown
        self.provider_cooldowns: Dict[str, float] = {}  # provider_name -> cooldown_until
        self._lock = threading.RLock()
    
    def set_cooldown(self, provider_name: str, duration: Optional[float] = None):
        """Set cooldown period for a provider"""
        with self._lock:
            cooldown_duration = duration if duration is not None else self.default_cooldown
            cooldown_until = time.time() + cooldown_duration
            self.provider_cooldowns[provider_name] = cooldown_until
            logger.info(
                f"Set cooldown for {provider_name} until {time.ctime(cooldown_until)} "
                f"({cooldown_duration}s)"
            )
    
    def is_in_cooldown(self, provider_name: str) -> bool:
        """Check if provider is in cooldown"""
        with self._lock:
            cooldown_until = self.provider_cooldowns.get(provider_name, 0)
            return time.time() < cooldown_until
    
    def get_remaining_cooldown(self, provider_name: str) -> float:
        """Get remaining cooldown time in seconds (0 if not in cooldown)"""
        with self._lock:
            cooldown_until = self.provider_cooldowns.get(provider_name, 0)
            remaining = cooldown_until - time.time()
            return max(0, remaining)
    
    def clear_cooldown(self, provider_name: str):
        """Clear cooldown for a provider"""
        with self._lock:
            if provider_name in self.provider_cooldowns:
                del self.provider_cooldowns[provider_name]
                logger.info(f"Cleared cooldown for {provider_name}")
    
    def cleanup_expired(self):
        """Remove expired cooldown entries"""
        with self._lock:
            now = time.time()
            expired = [
                provider for provider, cooldown_until in self.provider_cooldowns.items()
                if now >= cooldown_until
            ]
            for provider in expired:
                del self.provider_cooldowns[provider]
                if expired:
                    logger.debug(f"Cleaned up expired cooldowns: {expired}")


class ModelLockoutManager:
    """Manages model lockout periods (temporarily disable specific models)"""
    
    def __init__(self, default_lockout: float = 300.0):  # 5 minutes default
        self.default_lockout = default_lockout
        self.model_lockouts: Dict[str, float] = {}  # model_id -> lockout_until
        self._lock = threading.RLock()
    
    def lockout_model(self, model_id: str, duration: Optional[float] = None):
        """Lockout a specific model for a duration"""
        with self._lock:
            lockout_duration = duration if duration is not None else self.default_lockout
            lockout_until = time.time() + lockout_duration
            self.model_lockouts[model_id] = lockout_until
            logger.warning(
                f"Locked out model {model_id} until {time.ctime(lockout_until)} "
                f"({lockout_duration}s)"
            )
    
    def is_locked_out(self, model_id: str) -> bool:
        """Check if model is locked out"""
        with self._lock:
            lockout_until = self.model_lockouts.get(model_id, 0)
            return time.time() < lockout_until
    
    def get_remaining_lockout(self, model_id: str) -> float:
        """Get remaining lockout time in seconds (0 if not locked out)"""
        with self._lock:
            lockout_until = self.model_lockouts.get(model_id, 0)
            remaining = lockout_until - time.time()
            return max(0, remaining)
    
    def clear_lockout(self, model_id: str):
        """Clear lockout for a model"""
        with self._lock:
            if model_id in self.model_lockouts:
                del self.model_lockouts[model_id]
                logger.info(f"Cleared lockout for model {model_id}")
    
    def cleanup_expired(self):
        """Remove expired lockout entries"""
        with self._lock:
            now = time.time()
            expired = [
                model for model, lockout_until in self.model_lockouts.items()
                if now >= lockout_until
            ]
            for model in expired:
                del self.model_lockouts[model]
            if expired:
                logger.debug(f"Cleaned up expired lockouts: {expired}")


class ResilienceManager:
    """Main resilience manager coordinating all resilience mechanisms"""
    
    def __init__(
        self,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        default_cooldown: float = 30.0,
        default_lockout: float = 300.0
    ):
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.cooldown_manager = ConnectionCooldownManager(default_cooldown)
        self.lockout_manager = ModelLockoutManager(default_lockout)
        self.provider_metrics: Dict[str, ProviderMetrics] = {}
        self._lock = threading.RLock()
        
        # Background cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
    
    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for provider"""
        with self._lock:
            if provider_name not in self.circuit_breakers:
                self.circuit_breakers[provider_name] = CircuitBreaker(
                    provider_name, self.circuit_breaker_config
                )
            return self.circuit_breakers[provider_name]
    
    def get_or_create_metrics(self, provider_name: str) -> ProviderMetrics:
        """Get or create metrics for provider"""
        with self._lock:
            if provider_name not in self.provider_metrics:
                self.provider_metrics[provider_name] = ProviderMetrics(provider_name=provider_name)
            return self.provider_metrics[provider_name]
    
    def record_success(
        self,
        provider_name: str,
        model_id: Optional[str] = None,
        response_time: float = 0.0
    ):
        """Record successful request"""
        with self._lock:
            metrics = self.get_or_create_metrics(provider_name)
            metrics.total_requests += 1
            metrics.successful_requests += 1
            metrics.consecutive_failures = 0
            metrics.consecutive_successes += 1
            metrics.last_success_time = time.time()
            
            # Clear any cooldown on success (optional policy)
            if metrics.is_in_cooldown:
                self.cooldown_manager.clear_cooldown(provider_name)
                metrics.cooldown_until = 0
    
    def record_failure(
        self,
        provider_name: str,
        model_id: Optional[str] = None,
        failure_type: FailureType = FailureType.UNKNOWN,
        response_time: float = 0.0
    ):
        """Record failed request and apply resilience mechanisms"""
        with self._lock:
            metrics = self.get_or_create_metrics(provider_name)
            metrics.total_requests += 1
            metrics.failed_requests += 1
            metrics.consecutive_successes = 0
            metrics.consecutive_failures += 1
            metrics.last_failure_time = time.time()
            
            # Update specific failure counters
            if failure_type == FailureType.TIMEOUT:
                metrics.timeouts += 1
            elif failure_type == FailureType.CONNECTION_ERROR:
                metrics.connection_errors += 1
            elif failure_type == FailureType.RATE_LIMIT:
                metrics.rate_limits += 1
            elif failure_type == FailureType.SERVER_ERROR:
                metrics.server_errors += 1
            
            # Apply resilience mechanisms based on failure type and frequency
            self._apply_resilience_mechanisms(provider_name, model_id, failure_type, metrics)
    
    def _apply_resilience_mechanisms(
        self,
        provider_name: str,
        model_id: Optional[str],
        failure_type: FailureType,
        metrics: ProviderMetrics
    ):
        """Apply appropriate resilience mechanisms based on failure patterns"""
        
        # Circuit breaker always gets notified of failures
        circuit_breaker = self.get_circuit_breaker(provider_name)
        # For simplicity, we'll use a generic exception - in practice we'd map failure types
        try:
            # This is a simplified call - actual implementation would wrap the real function
            pass
        except Exception:
            # Circuit breaker will handle this internally
            pass
        
        # Apply cooldown for connection issues and timeouts
        if failure_type in [FailureType.CONNECTION_ERROR, FailureType.TIMEOUT]:
            # Progressive cooldown: longer cooldown for more consecutive failures
            cooldown_duration = min(
                30.0 * (2 ** min(metrics.consecutive_failures - 1, 5)),  # Cap at 30*32=960s
                300.0  # Max 5 minutes
            )
            self.cooldown_manager.set_cooldown(provider_name, cooldown_duration)
            metrics.cooldown_until = time.time() + cooldown_duration
            logger.warning(
                f"Applied {cooldown_duration}s cooldown to {provider_name} due to {failure_type.value}"
            )
        
        # Apply lockout for persistent issues or specific error types
        if (metrics.consecutive_failures >= 5 and 
            failure_type in [FailureType.RATE_LIMIT, FailureType.AUTHENTICATION_ERROR]):
            # Lockout the specific model if provided, otherwise lockout the provider
            lockout_target = model_id or provider_name
            lockout_duration = min(
                60.0 * (2 ** min(metrics.consecutive_failures - 5, 3)),  # Cap at 60*8=480s
                1800.0  # Max 30 minutes
            )
            self.lockout_manager.lockout_model(lockout_target, lockout_duration)
            if model_id:
                metrics.lockout_until = time.time() + lockout_duration
            logger.warning(
                f"Applied {lockout_duration}s lockout to {lockout_target} due to {failure_type.value}"
            )
        
        # Additional lockout for server errors after threshold
        if (failure_type == FailureType.SERVER_ERROR and 
            metrics.consecutive_failures >= 10):
            lockout_target = model_id or provider_name
            self.lockout_manager.lockout_model(lockout_target, 300.0)  # 5 minutes
            if model_id:
                metrics.lockout_until = time.time() + 300.0
            logger.warning(
                f"Applied 300s lockout to {lockout_target} due to persistent server errors"
            )
    
    def is_provider_available(self, provider_name: str) -> bool:
        """Check if provider is available for use"""
        with self._lock:
            metrics = self.get_or_create_metrics(provider_name)
            circuit_breaker = self.get_circuit_breaker(provider_name)
            
            # Check all availability conditions
            return (
                metrics.is_available and
                circuit_breaker.state != CircuitState.OPEN and
                not self.cooldown_manager.is_in_cooldown(provider_name)
            )
    
    def is_model_available(self, model_id: str) -> bool:
        """Check if specific model is available (not locked out)"""
        with self._lock:
            return not self.lockout_manager.is_locked_out(model_id)
    
    def get_provider_health_score(self, provider_name: str) -> float:
        """Get health score for provider (0.0 to 1.0)"""
        with self._lock:
            metrics = self.get_or_create_metrics(provider_name)
            circuit_breaker = self.get_circuit_breaker(provider_name)
            
            # Base score from success rate
            if metrics.total_requests == 0:
                base_score = 0.5  # Neutral for unknown providers
            else:
                base_score = metrics.success_rate / 100.0
            
            # Circuit breaker penalty
            cb_penalty = {
                CircuitState.CLOSED: 1.0,
                CircuitState.HALF_OPEN: 0.7,
                CircuitState.OPEN: 0.0
            }[circuit_breaker.state]
            
            # Availability penalty
            availability_penalty = 1.0 if metrics.is_available else 0.5
            
            # Combined score
            health_score = base_score * cb_penalty * availability_penalty
            return max(0.0, min(1.0, health_score))
    
    def get_resilience_status(self) -> Dict[str, Any]:
        """Get comprehensive resilience status"""
        with self._lock:
            status = {
                "circuit_breakers": {},
                "providers": {},
                "cooldowns": {},
                "lockouts": {},
                "summary": {
                    "total_providers": len(self.provider_metrics),
                    "available_providers": 0,
                    "open_circuit_breakers": 0,
                    "in_cooldown": 0,
                    "locked_out": 0
                }
            }
            
            now = time.time()
            
            for provider_name, metrics in self.provider_metrics.items():
                circuit_breaker = self.circuit_breakers.get(provider_name)
                
                # Circuit breaker status
                cb_state = circuit_breaker.state.value if circuit_breaker else "unknown"
                if cb_state == "open":
                    status["summary"]["open_circuit_breakers"] += 1
                
                # Provider availability
                is_available = self.is_provider_available(provider_name)
                if is_available:
                    status["summary"]["available_providers"] += 1
                
                # Cooldown status
                in_cooldown = self.cooldown_manager.is_in_cooldown(provider_name)
                if in_cooldown:
                    status["summary"]["in_cooldown"] += 1
                
                # Store detailed status
                status["circuit_breakers"][provider_name] = cb_state
                status["providers"][provider_name] = {
                    "available": is_available,
                    "success_rate": metrics.success_rate,
                    "failure_rate": metrics.failure_rate,
                    "total_requests": metrics.total_requests,
                    "consecutive_failures": metrics.consecutive_failures,
                    "consecutive_successes": metrics.consecutive_successes,
                    "health_score": self.get_provider_health_score(provider_name)
                }
                status["cooldowns"][provider_name] = {
                    "in_cooldown": in_cooldown,
                    "remaining_seconds": max(0, metrics.cooldown_until - now) if metrics.cooldown_until > 0 else 0
                }
            
            # Lockout status (model-level)
            for model_id, lockout_until in self.lockout_manager.model_lockouts.items():
                if lockout_until > now:
                    status["lockouts"][model_id] = lockout_until - now
                    status["summary"]["locked_out"] += 1
            
            return status
    
    def _cleanup_loop(self):
        """Background cleanup loop for expired cooldowns and lockouts"""
        while True:
            try:
                time.sleep(30.0)  # Cleanup every 30 seconds
                self.cooldown_manager.cleanup_expired()
                self.lockout_manager.cleanup_expired()
            except Exception as e:
                logger.error(f"Error in resilience cleanup loop: {e}")
    
    def shutdown(self):
        """Shutdown the resilience manager (for cleanup)"""
        # In a real application, we'd signal the cleanup thread to stop
        pass


# Global resilience manager instance
_resilience_manager: Optional[ResilienceManager] = None


def get_resilience_manager() -> ResilienceManager:
    """Get or create the global resilience manager"""
    global _resilience_manager
    if _resilience_manager is None:
        _resilience_manager = ResilienceManager()
    return _resilience_manager


def reset_resilience_manager():
    """Reset the global resilience manager (mainly for testing)"""
    global _resilience_manager
    if _resilience_manager:
        _resilience_manager.shutdown()
    _resilience_manager = None


# Decorator for automatic resilience wrapping
def with_resilience(provider_name: str, model_id: Optional[str] = None):
    """Decorator to automatically apply resilience mechanisms to provider calls"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            manager = get_resilience_manager()
            try:
                result = func(*args, **kwargs)
                manager.record_success(provider_name, model_id)
                return result
            except Exception as e:
                # Determine failure type from exception
                failure_type = _classify_failure(e)
                manager.record_failure(provider_name, model_id, failure_type)
                raise e
        return wrapper
    return decorator


def _classify_failure(exception: Exception) -> FailureType:
    """Classify exception into failure type"""
    exception_str = str(exception).lower()
    exception_type = type(exception).__name__.lower()
    
    if "timeout" in exception_str or "timeout" in exception_type:
        return FailureType.TIMEOUT
    elif "connection" in exception_str or "connection" in exception_type:
        return FailureType.CONNECTION_ERROR
    elif "rate limit" in exception_str or "429" in exception_str:
        return FailureType.RATE_LIMIT
    elif "authentication" in exception_str or "401" in exception_str or "403" in exception_str:
        return FailureType.AUTHENTICATION_ERROR
    elif "not found" in exception_str or "404" in exception_str:
        return FailureType.MODEL_NOT_FOUND
    elif "500" in exception_str or "502" in exception_str or "503" in exception_str or "504" in exception_str:
        return FailureType.SERVER_ERROR
    else:
        return FailureType.UNKNOWN