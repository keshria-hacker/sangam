"""
Enhanced Provider Integration with Resilience
Integrates resilience mechanisms into the existing provider system
"""
import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base import BaseProvider, ModelInfo
from .resilience import (
    get_resilience_manager,
    FailureType,
    with_resilience
)

logger = logging.getLogger(__name__)


class ResilienceWrapper:
    """Wraps provider methods with resilience mechanisms"""
    
    def __init__(self, provider: BaseProvider):
        self.provider = provider
        self.provider_name = getattr(provider, 'provider_id', provider.__class__.__name__.lower().replace('provider', ''))
        self.resilience_manager = get_resilience_manager()
    
    def wrap_method(self, method_name: str, model_id: Optional[str] = None):
        """Wrap a provider method with resilience"""
        original_method = getattr(self.provider, method_name)
        
        # Create wrapped method with resilience
        @with_resilience(self.provider_name, model_id)
        def resilient_method(*args, **kwargs):
            return original_method(*args, **kwargs)
        
        # Replace the method on the provider instance
        setattr(self.provider, method_name, resilient_method)
    
    def wrap_all_methods(self):
        """Wrap all relevant provider methods with resilience"""
        # Methods that make API calls and should be protected
        methods_to_wrap = [
            'list_models',
            'get_model_info',
            # Note: actual chat/completion methods are handled by the LLM facade
        ]
        
        for method_name in methods_to_wrap:
            if hasattr(self.provider, method_name):
                self.wrap_method(method_name)


def enhance_provider_with_resilience(provider: BaseProvider) -> BaseProvider:
    """
    Enhance a provider with resilience mechanisms.
    Returns the same provider instance with wrapped methods.
    """
    wrapper = ResilienceWrapper(provider)
    wrapper.wrap_all_methods()
    return provider


# Example usage function for providers that want manual resilience control
def record_provider_success(provider_name: str, model_id: Optional[str] = None):
    """Record a successful provider interaction"""
    manager = get_resilience_manager()
    manager.record_success(provider_name, model_id)


def record_provider_failure(
    provider_name: str,
    model_id: Optional[str] = None,
    failure_type: FailureType = FailureType.UNKNOWN
):
    """Record a failed provider interaction"""
    manager = get_resilience_manager()
    manager.record_failure(provider_name, model_id, failure_type)


def is_provider_available(provider_name: str) -> bool:
    """Check if a provider is available for use"""
    manager = get_resilience_manager()
    return manager.is_provider_available(provider_name)


def get_provider_health_score(provider_name: str) -> float:
    """Get health score for a provider"""
    manager = get_resilience_manager()
    return manager.get_provider_health_score(provider_name)


def get_resilience_status() -> Dict[str, Any]:
    """Get comprehensive resilience status"""
    manager = get_resilience_manager()
    return manager.get_resilience_status()