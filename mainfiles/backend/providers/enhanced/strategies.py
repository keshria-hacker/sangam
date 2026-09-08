"""
Routing Strategy Interface and Base Implementations
Based on OmniRoute's 19 routing strategies
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import random
import heapq
from enum import Enum


class TaskType(Enum):
    """Task types for routing optimization"""
    CHAT = "chat"
    CODING = "coding"
    REASONING = "reasoning"
    VISION = "vision"
    MULTIMODAL = "multimodal"


@dataclass
class RoutingContext:
    """Context for routing decisions"""
    model_id: str
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 1024
    reasoning_effort: Optional[str] = None
    priority: int = 0  # Higher priority gets better treatment
    task_type: str = "general"
    complexity: float = 0.5
    urgency: float = 0.5
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ProviderCandidate:
    """Represents a provider/model combination for routing"""
    provider_name: str
    model_name: str
    display_name: str  # e.g., "openai/gpt-4"
    
    # Metrics for routing decisions
    cost_per_1m_tokens: float  # USD
    avg_latency_ms: float
    health_score: float  # 0.0 to 1.0 (1.0 = healthy)
    quota_headroom: float  # 0.0 to 1.0 (1.0 = full quota)
    error_rate: float  # 0.0 to 1.0
    context_window: int  # tokens
    
    # Capabilities
    supports_vision: bool = False
    supports_reasoning: bool = False
    supports_tools: bool = False
    
    # State
    is_available: bool = True
    last_used_timestamp: float = 0.0
    usage_count: int = 0
    
    def __post_init__(self):
        # Calculate derived metrics
        self.task_fitness = self._calculate_task_fitness()
    
    def _calculate_task_fitness(self) -> float:
        """Calculate how well this provider fits the task type"""
        # This would be customized based on task_type in context
        # For now, simple heuristic
        score = 0.5  # base score
        
        if self.supports_vision:
            score += 0.2
        if self.supports_reasoning:
            score += 0.2
        if self.supports_tools:
            score += 0.1
            
        return min(score, 1.0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "display_name": self.display_name,
            "cost_per_1m_tokens": self.cost_per_1m_tokens,
            "avg_latency_ms": self.avg_latency_ms,
            "health_score": self.health_score,
            "quota_headroom": self.quota_headroom,
            "error_rate": self.error_rate,
            "context_window": self.context_window,
            "supports_vision": self.supports_vision,
            "supports_reasoning": self.supports_reasoning,
            "supports_tools": self.supports_tools,
            "is_available": self.is_available,
            "task_fitness": self.task_fitness,
            "last_used_timestamp": self.last_used_timestamp,
            "usage_count": self.usage_count
        }


class RoutingStrategy(ABC):
    """Abstract base class for all routing strategies"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
    
    @abstractmethod
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        """Select the best provider candidate based on the strategy"""
        pass
    
    def filter_candidates(self, candidates: List[ProviderCandidate]) -> List[ProviderCandidate]:
        """Filter out unavailable candidates"""
        return [c for c in candidates if c.is_available]


# ============================================================================
# CONCRETE STRATEGY IMPLEMENTATIONS
# ============================================================================

class PriorityStrategy(RoutingStrategy):
    """First-target ordered list with explicit priority"""
    
    def __init__(self):
        super().__init__("priority", "First-target ordered list with explicit priority")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by priority (higher priority first), then by usage count (lower usage first)
        sorted_candidates = sorted(filtered, key=lambda c: (-getattr(c, 'priority', 0), c.usage_count))
        return sorted_candidates[0]


class WeightedStrategy(RoutingStrategy):
    """Weighted random by per-target weight"""
    
    def __init__(self):
        super().__init__("weighted", "Weighted random by per-target weight")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Calculate weights based on multiple factors
        weights = []
        for candidate in filtered:
            # Combine health, quota headroom, inverse cost, and inverse latency
            weight = (
                candidate.health_score * 0.3 +
                candidate.quota_headroom * 0.3 +
                (1.0 / max(candidate.cost_per_1m_tokens, 0.001)) * 0.2 +
                (1.0 / max(candidate.avg_latency_ms, 1.0)) * 0.2
            )
            weights.append(max(weight, 0.01))  # Ensure minimum weight
        
        # Weighted random selection
        total_weight = sum(weights)
        r = random.uniform(0, total_weight)
        upto = 0
        for i, w in enumerate(weights):
            if upto + w >= r:
                return filtered[i]
            upto += w
        return filtered[-1]  # Fallback


class RoundRobinStrategy(RoutingStrategy):
    """Cycle through targets in order"""
    
    def __init__(self):
        super().__init__("round-robin", "Cycle through targets in order")
        self._last_index = -1
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Simple round-robin
        self._last_index = (self._last_index + 1) % len(filtered)
        return filtered[self._last_index]


class ContextRelayStrategy(RoutingStrategy):
    """Hand off context across targets (long conversations)"""
    
    def __init__(self):
        super().__init__("context-relay", "Hand off context across targets (long conversations)")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Prefer providers with larger context windows for long conversations
        # Also consider health and cost
        scored = []
        for candidate in filtered:
            context_score = min(candidate.context_window / 32768, 1.0)  # Normalize to 32k context
            score = (
                context_score * 0.4 +
                candidate.health_score * 0.3 +
                candidate.quota_headroom * 0.2 +
                (1.0 / max(candidate.cost_per_1m_tokens, 0.001)) * 0.1
            )
            scored.append((score, candidate))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


class FillFirstStrategy(RoutingStrategy):
    """Fill each target's quota before moving to next"""
    
    def __init__(self):
        super().__init__("fill-first", "Fill each target's quota before moving to next")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by quota headroom (ascending) to fill up those with least headroom first
        sorted_candidates = sorted(filtered, key=lambda c: c.quota_headroom)
        return sorted_candidates[0]


class PowerOfTwoChoicesStrategy(RoutingStrategy):
    """Power-of-2-choices random load balancing"""
    
    def __init__(self):
        super().__init__("p2c", "Power-of-2-choices random load balancing")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        if len(filtered) == 1:
            return filtered[0]
        
        # Pick two random candidates and choose the better one based on load
        c1, c2 = random.sample(filtered, 2)
        
        # Better candidate is the one with lower usage count (less loaded)
        if c1.usage_count <= c2.usage_count:
            return c1
        else:
            return c2


class RandomStrategy(RoutingStrategy):
    """Uniform random selection"""
    
    def __init__(self):
        super().__init__("random", "Uniform random selection")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        return random.choice(filtered)


class LeastUsedStrategy(RoutingStrategy):
    """Pick target with lowest current load"""
    
    def __init__(self):
        super().__init__("least-used", "Pick target with lowest current load")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by usage count (ascending)
        sorted_candidates = sorted(filtered, key=lambda c: c.usage_count)
        return sorted_candidates[0]


class CostOptimizedStrategy(RoutingStrategy):
    """Minimize $ per request given catalog pricing"""
    
    def __init__(self):
        super().__init__("cost-optimized", "Minimize $ per request given catalog pricing")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by cost per token (ascending)
        sorted_candidates = sorted(filtered, key=lambda c: c.cost_per_1m_tokens)
        return sorted_candidates[0]


class ResetAwareStrategy(RoutingStrategy):
    """Prioritize by quota reset time — short reset windows ranked higher"""
    
    def __init__(self):
        super().__init__("reset-aware", "Prioritize by quota reset time — short reset windows ranked higher")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # This would need reset time data - for now simulate with inverse quota headroom
        # Lower quota headroom means closer to reset
        sorted_candidates = sorted(filtered, key=lambda c: (1.0 - c.quota_headroom))
        return sorted_candidates[0]


class ResetWindowStrategy(RoutingStrategy):
    """Prefer targets whose quota window resets soonest"""
    
    def __init__(self):
        super().__init__("reset-window", "Prefer targets whose quota window resets soonest")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Similar to reset-aware - prioritize those with less quota headroom
        sorted_candidates = sorted(filtered, key=lambda c: (1.0 - c.quota_headroom))
        return sorted_candidates[0]


class HeadroomStrategy(RoutingStrategy):
    """Pick the target with the most remaining quota headroom"""
    
    def __init__(self):
        super().__init__("headroom", "Pick the target with the most remaining quota headroom")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by quota headroom (descending)
        sorted_candidates = sorted(filtered, key=lambda c: c.quota_headroom, reverse=True)
        return sorted_candidates[0]


class StrictRandomStrategy(RoutingStrategy):
    """Random without deduplication of repeats"""
    
    def __init__(self):
        super().__init__("strict-random", "Random without deduplication of repeats")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Pure random - no consideration of history
        return random.choice(filtered)


class AutoStrategy(RoutingStrategy):
    """Use Auto Combo scoring (14-factor)"""
    
    def __init__(self):
        super().__init__("auto", "Use Auto Combo scoring (14-factor)")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # 14-factor scoring inspired by OmniRoute
        scored = []
        for candidate in filtered:
            score = self._calculate_auto_score(candidate, context)
            scored.append((score, candidate))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    
    def _calculate_auto_score(self, candidate: ProviderCandidate, context: RoutingContext) -> float:
        """Calculate the 14-factor auto score"""
        # Health score from circuit breaker (CLOSED=1.0, HALF_OPEN=0.5, OPEN=0.0)
        health = candidate.health_score
        
        # Remaining quota / rate-limit headroom [0..1]
        quota = candidate.quota_headroom
        
        # Inverse blended cost (60% input + 40% output token price, normalized)
        # Assuming equal input/output for simplicity
        cost_inv = 1.0 / max(candidate.cost_per_1m_tokens, 0.001)
        # Normalize cost_inv (this would be done across pool in practice)
        cost_inv = min(cost_inv / 100.0, 1.0)  # Simple normalization
        
        # Inverse p95 latency normalized to pool
        latency_inv = 1.0 / max(candidate.avg_latency_ms, 1.0)
        latency_inv = min(latency_inv / 1000.0, 1.0)  # Simple normalization
        
        # Task-type fitness
        task_fit = candidate.task_fitness
        
        # Variance-based stability (low latency stdDev / error rate)
        # Using error rate as proxy for instability
        stability = 1.0 - min(candidate.error_rate, 1.0)
        
        # Account-tier priority (simplified)
        tier_priority = 0.5  # Would be based on actual account tier
        
        # Affinity between candidate's tier and recommended tier
        tier_affinity = 0.5  # Placeholder
        
        # Match between request specificity and model tier
        specificity_match = 0.5  # Placeholder
        
        # Affinity between request context-window need and model's context window
        if context.max_tokens > 0:
            context_affinity = min(candidate.context_window / max(context.max_tokens * 2, 1), 1.0)
            context_affinity = max(0.0, min(context_affinity, 1.0))  # Clamp to 0-1
        else:
            context_affinity = 0.5
        
        # OAuth session availability (simplified)
        session_availability = 1.0  # Assume available
        
        # Spreads load across connections (anti-concentration)
        # Lower usage count = better
        connection_density = 1.0 / max(candidate.usage_count + 1, 1)
        connection_density = min(connection_density, 1.0)
        
        # Cache affinity (disabled by default)
        cache_affinity = 0.0
        
        # Reset window affinity (disabled by default)
        reset_window_affinity = 0.0
        
        # Weights from OmniRoute documentation (sum to 1.05, but will be normalized)
        weights = {
            'health': 0.20,
            'quota': 0.15,
            'costInv': 0.15,
            'latencyInv': 0.12,
            'taskFit': 0.08,
            'stability': 0.05,
            'tierPriority': 0.05,
            'tierAffinity': 0.05,
            'specificityMatch': 0.05,
            'contextAffinity': 0.05,
            'sessionAvailability': 0.05,
            'connectionDensity': 0.05,
            'cacheAffinity': 0.00,
            'resetWindowAffinity': 0.00
        }
        
        # Calculate weighted sum
        total_score = (
            health * weights['health'] +
            quota * weights['quota'] +
            cost_inv * weights['costInv'] +
            latency_inv * weights['latencyInv'] +
            task_fit * weights['taskFit'] +
            stability * weights['stability'] +
            tier_priority * weights['tierPriority'] +
            tier_affinity * weights['tierAffinity'] +
            specificity_match * weights['specificityMatch'] +
            context_affinity * weights['contextAffinity'] +
            session_availability * weights['sessionAvailability'] +
            connection_density * weights['connectionDensity'] +
            cache_affinity * weights['cacheAffinity'] +
            reset_window_affinity * weights['resetWindowAffinity']
        )
        
        return total_score


class LastKnownGoodStrategy(RoutingStrategy):
    """Last-Known-Good Path (sticky route to last successful target)"""
    
    def __init__(self):
        super().__init__("lkgp", "Last-Known-Good Path (sticky route to last successful target)")
        self._last_good_provider: Dict[str, str] = {}  # session_id -> provider_model
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # If we have session context and a last good provider for this session, try to use it
        if context.session_id and context.session_id in self._last_good_provider:
            last_good_key = self._last_good_provider[context.session_id]
            for candidate in filtered:
                candidate_key = f"{candidate.provider_name}/{candidate.model_name}"
                if candidate_key == last_good_key:
                    return candidate
        
        # Fallback to health-based selection
        sorted_candidates = sorted(filtered, key=lambda c: c.health_score, reverse=True)
        best_candidate = sorted_candidates[0]
        
        # Update last good provider for this session
        if context.session_id:
            self._last_good_provider[context.session_id] = f"{best_candidate.provider_name}/{best_candidate.model_name}"
        
        return best_candidate


class ContextOptimizedStrategy(RoutingStrategy):
    """Pick target with best fit for current context size"""
    
    def __init__(self):
        super().__init__("context-optimized", "Pick target with best fit for current context size")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Score based on how well context window fits the estimated tokens
        scored = []
        for candidate in filtered:
            if context.max_tokens > 0:
                # Prefer providers with context window just above our needs (not wasteful)
                ratio = context.max_tokens / candidate.context_window
                if ratio <= 1.0:
                    # We fit - score based on how紧凑 the fit is (closer to 1.0 is better, but not over)
                    context_score = ratio  # 1.0 is perfect fit, lower means more headroom
                else:
                    # We don't fit - heavily penalize
                    context_score = 0.1
            else:
                context_score = 0.5  # No context preference
            
            # Combine with other factors
            score = (
                context_score * 0.4 +
                candidate.health_score * 0.3 +
                candidate.quota_headroom * 0.2 +
                (1.0 / max(candidate.cost_per_1m_tokens, 0.001)) * 0.1
            )
            scored.append((score, candidate))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


class CacheOptimizedStrategy(RoutingStrategy):
    """Reorder targets by prompt-cache affinity"""
    
    def __init__(self):
        super().__init__("cache-optimized", "Reorder targets by prompt-cache affinity")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # This would need actual cache affinity data
        # For now, fall back to health-based selection with a small random factor
        scored = []
        for candidate in filtered:
            # Simulate cache affinity (would be based on actual prompt cache hits)
            cache_affinity = random.uniform(0.8, 1.0)  # Placeholder
            
            score = (
                cache_affinity * 0.3 +
                candidate.health_score * 0.4 +
                candidate.quota_headroom * 0.2 +
                (1.0 / max(candidate.cost_per_1m_tokens, 0.001)) * 0.1
            )
            scored.append((score, candidate))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


class FusionStrategy(RoutingStrategy):
    """Fan out to panel models in parallel, then synthesize via judge"""
    
    def __init__(self, judge_model: str = ""):
        super().__init__("fusion", "Fan out to panel models in parallel, then synthesize via judge")
        self.judge_model = judge_model
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        # For fusion strategy, we return the judge model if specified,
        # otherwise we fall back to auto strategy for selecting the panel
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        if self.judge_model:
            # Look for the judge model in candidates
            for candidate in filtered:
                if candidate.model_name == self.judge_model or candidate.display_name == self.judge_model:
                    return candidate
        
        # Fallback to auto strategy for panel selection
        auto_strategy = AutoStrategy()
        return auto_strategy.select(filtered, context)


class PipelineStrategy(RoutingStrategy):
    """Run targets sequentially, threading output"""
    
    def __init__(self):
        super().__init__("pipeline", "Run targets sequentially, threading output")
    
    def select(self, candidates: List[ProviderCandidate], context: RoutingContext) -> ProviderCandidate:
        # For pipeline, we typically want the first step in the pipeline
        # This would be configured per combo - for now return the "healthiest" 
        # as a placeholder for the first stage
        filtered = self.filter_candidates(candidates)
        if not filtered:
            raise ValueError("No available candidates")
        
        # Sort by health score for pipeline initialization
        sorted_candidates = sorted(filtered, key=lambda c: c.health_score, reverse=True)
        return sorted_candidates[0]


# ============================================================================
# STRATEGY FACTORY AND REGISTRY
# ============================================================================

class StrategyFactory:
    """Factory for creating routing strategy instances"""
    
    _strategies = {
        'priority': PriorityStrategy,
        'weighted': WeightedStrategy,
        'round-robin': RoundRobinStrategy,
        'context-relay': ContextRelayStrategy,
        'fill-first': FillFirstStrategy,
        'p2c': PowerOfTwoChoicesStrategy,
        'random': RandomStrategy,
        'least-used': LeastUsedStrategy,
        'cost-optimized': CostOptimizedStrategy,
        'reset-aware': ResetAwareStrategy,
        'reset-window': ResetWindowStrategy,
        'headroom': HeadroomStrategy,
        'strict-random': StrictRandomStrategy,
        'auto': AutoStrategy,
        'lkgp': LastKnownGoodStrategy,
        'context-optimized': ContextOptimizedStrategy,
        'cache-optimized': CacheOptimizedStrategy,
        'fusion': FusionStrategy,
        'pipeline': PipelineStrategy
    }
    
    @classmethod
    def create_strategy(cls, strategy_name: str, **kwargs) -> RoutingStrategy:
        """Create a strategy instance by name"""
        if strategy_name not in cls._strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        
        strategy_class = cls._strategies[strategy_name]
        return strategy_class(**kwargs)
    
    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """Get list of available strategy names"""
        return list(cls._strategies.keys())
    
    @classmethod
    def get_strategy_description(cls, strategy_name: str) -> str:
        """Get description of a strategy"""
        if strategy_name not in cls._strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        
        # Create temporary instance to get description
        strategy = cls._strategies[strategy_name]()
        return strategy.description


# ============================================================================
# ENHANCED ROUTER (Main class for integration)
# ============================================================================

class EnhancedRouter:
    """Main enhanced routing engine that combines strategies with resilience"""
    
    def __init__(self, 
                 resilience_manager: Any = None,
                 enable_model_routing: bool = True,
                 enable_time_based_routing: bool = False,
                 enable_geo_routing: bool = False,
                 enable_cost_optimization: bool = True,
                 enable_quality_optimization: bool = True):
        """
        Initialize enhanced router
        
        Args:
            resilience_manager: Resilience manager instance
            enable_model_routing: Enable model-specific routing
            enable_time_based_routing: Enable time-based routing
            enable_geo_routing: Enable geographic routing
            enable_cost_optimization: Enable cost optimization
            enable_quality_optimization: Enable quality optimization
        """
        self.resilience_manager = resilience_manager
        self.enable_model_routing = enable_model_routing
        self.enable_time_based_routing = enable_time_based_routing
        self.enable_geo_routing = enable_geo_routing
        self.enable_cost_optimization = enable_cost_optimization
        self.enable_quality_optimization = enable_quality_optimization
        
        # Provider registry: provider_id -> config
        self.providers: Dict[str, Any] = {}
        self.provider_locals: Dict[str, bool] = {}  # provider_id -> is_local
        
        # Strategy factory
        self.strategy_factory = StrategyFactory()
        
        # Default strategy
        self.default_strategy = 'auto'
    
    def register_provider(self, provider_id: str, config: Any, is_local: bool = False):
        """Register a provider with the router"""
        self.providers[provider_id] = config
        self.provider_locals[provider_id] = is_local
    
    def _create_candidate_from_config(self, provider_id: str, config: Any) -> ProviderCandidate:
        """Create a ProviderCandidate from provider config"""
        # Extract relevant information from config
        # This is a simplified version - in practice we'd get more detailed info
        
        # Get model information (simplified)
        model_name = getattr(config, 'model', 'unknown')
        if not model_name or model_name == 'unknown':
            # Try to get from litellm_prefix or similar
            model_name = getattr(config, 'litellm_prefix', 'unknown').rstrip('/')
            if not model_name or model_name == 'unknown':
                model_name = 'default'
        
        display_name = f"{provider_id}/{model_name}"
        
        # Extract metrics from config or use defaults
        cost_per_1m_tokens = getattr(config, 'cost_per_1m_tokens', 0.001) * 1000  # Convert to per 1M
        avg_latency_ms = getattr(config, 'latency_baseline_ms', 1000.0)
        health_score = getattr(config, 'health_score', 0.8)
        quota_headroom = getattr(config, 'quota_headroom', 0.5)
        error_rate = getattr(config, 'error_rate', 0.05)
        context_window = getattr(config, 'context_window', 4096)
        
        # Capabilities (simplified)
        supports_vision = getattr(config, 'supports_vision', False)
        supports_reasoning = getattr(config, 'supports_reasoning', False)
        supports_tools = getattr(config, 'supports_tools', False)
        
        return ProviderCandidate(
            provider_name=provider_id,
            model_name=model_name,
            display_name=display_name,
            cost_per_1m_tokens=cost_per_1m_tokens,
            avg_latency_ms=avg_latency_ms,
            health_score=health_score,
            quota_headroom=quota_headroom,
            error_rate=error_rate,
            context_window=context_window,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            supports_tools=supports_tools,
            is_available=True  # Assume available unless we have specific health data
        )
    
    async def select_provider(self, context: RoutingContext) -> str:
        """
        Select the best provider for the given context
        
        Args:
            context: Routing context with request details
            
        Returns:
            Selected provider ID
        """
        try:
            # Create provider candidates from registered providers
            candidates = []
            for provider_id, config in self.providers.items():
                is_local = self.provider_locals.get(provider_id, False)
                
                # Skip local providers if no API key (though they might not need one)
                # For now, we'll include all registered providers
                candidate = self._create_candidate_from_config(provider_id, config)
                candidates.append(candidate)
            
            if not candidates:
                raise ValueError("No providers available")
            
            # Determine which strategy to use based on context and configuration
            strategy_name = self._select_strategy(context)
            
            # Create strategy instance
            strategy = self.strategy_factory.create_strategy(strategy_name)
            
            # Select provider using the strategy
            selected_candidate = strategy.select(candidates, context)
            
            return selected_candidate.provider_name
            
        except Exception as e:
            # Fallback to first available provider if selection fails
            if self.providers:
                return list(self.providers.keys())[0]
            raise
    
    def _select_strategy(self, context: RoutingContext) -> str:
        """Select the appropriate routing strategy based on context"""
        # Start with default strategy
        strategy_name = self.default_strategy
        
        # Override based on context and enabled features
        if context.task_type == "coding" and self.enable_cost_optimization:
            strategy_name = "cost-optimized"
        elif context.task_type == "reasoning" and self.enable_quality_optimization:
            strategy_name = "quality-optimized"
        elif context.priority > 50:  # High priority requests
            strategy_name = "priority"
        elif context.session_id and context.session_id in getattr(self, '_last_good_provider', {}):
            # Use sticky routing for known good sessions
            strategy_name = "lkgp"
        elif self.enable_model_routing and hasattr(context, 'model_id'):
            # Model-specific routing (simplified)
            strategy_name = "auto"  # Use auto strategy for model-aware routing
        
        return strategy_name


# ============================================================================
# EXAMPLE USAGE AND TESTING
# ============================================================================

def create_example_candidates() -> List[ProviderCandidate]:
    """Create example provider candidates for testing"""
    return [
        ProviderCandidate(
            provider_name="openai",
            model_name="gpt-4",
            display_name="openai/gpt-4",
            cost_per_1m_tokens=30.0,
            avg_latency_ms=800,
            health_score=0.95,
            quota_headroom=0.7,
            error_rate=0.02,
            context_window=8192,
            supports_vision=True,
            supports_reasoning=True,
            supports_tools=True
        ),
        ProviderCandidate(
            provider_name="anthropic",
            model_name="claude-3-opus-20240229",
            display_name="anthropic/claude-3-opus",
            cost_per_1m_tokens=15.0,
            avg_latency_ms=1200,
            health_score=0.9,
            quota_headroom=0.5,
            error_rate=0.01,
            context_window=200000,
            supports_vision=True,
            supports_reasoning=True,
            supports_tools=True
        ),
        ProviderCandidate(
            provider_name="ollama",
            model_name="llama3-70b",
            display_name="ollama/llama3-70b",
            cost_per_1m_tokens=0.0,
            avg_latency_ms=2000,
            health_score=0.8,
            quota_headroom=1.0,
            error_rate=0.05,
            context_window=8192,
            supports_vision=False,
            supports_reasoning=True,
            supports_tools=False
        )
    ]


if __name__ == "__main__":
    # Example usage
    from dataclasses import dataclass
    
    @dataclass
    class MockResilienceManager:
        pass
    
    manager = MockResilienceManager()
    router = EnhancedRouter(resilience_manager=manager)
    
    # Register example providers (mock configs)
    class MockConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    router.register_provider("openai", MockConfig(
        model="gpt-4",
        cost_per_1m_tokens=0.03,
        latency_baseline_ms=800,
        health_score=0.95,
        quota_headroom=0.7,
        error_rate=0.02,
        context_window=8192,
        supports_vision=True,
        supports_reasoning=True,
        supports_tools=True
    ))
    
    router.register_provider("anthropic", MockConfig(
        model="claude-3-opus-20240229",
        cost_per_1m_tokens=0.015,
        latency_baseline_ms=1200,
        health_score=0.9,
        quota_headroom=0.5,
        error_rate=0.01,
        context_window=200000,
        supports_vision=True,
        supports_reasoning=True,
        supports_tools=True
    ))
    
    router.register_provider("ollama", MockConfig(
        model="llama3-70b",
        cost_per_1m_tokens=0.0,
        latency_baseline_ms=2000,
        health_score=0.8,
        quota_headroom=1.0,
        error_rate=0.05,
        context_window=8192,
        supports_vision=False,
        supports_reasoning=True,
        supports_tools=False
    ))
    
    # Test different strategies via context
    import asyncio
    
    async def test_router():
        contexts = [
            RoutingContext(
                model_id="test",
                messages=[{"role": "user", "content": "Hello"}],
                task_type="chat",
                priority=10
            ),
            RoutingContext(
                model_id="test",
                messages=[{"role": "user", "content": "Write a Python function"}],
                task_type="coding",
                priority=50
            ),
            RoutingContext(
                model_id="test",
                messages=[{"role": "user", "content": "Explain quantum physics"}],
                task_type="reasoning",
                priority=80
            )
        ]
        
        print("Testing enhanced router with different contexts...")
        for i, context in enumerate(contexts):
            try:
                selected = await router.select_provider(context)
                print(f"Context {i+1} ({context.task_type}, priority {context.priority}) -> {selected}")
            except Exception as e:
                print(f"Context {i+1} -> ERROR: {e}")
    
    asyncio.run(test_router())