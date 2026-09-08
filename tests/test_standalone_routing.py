#!/usr/bin/env python3
"""
Standalone test for enhanced provider routing system
Tests the strategies module in isolation
"""
import sys
import os
import random
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum
from abc import ABC, abstractmethod

# Define the core classes we need (copied from our strategies module)
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
    task_type: TaskType
    estimated_tokens: int
    has_tools: bool = False
    has_vision: bool = False
    session_id: Optional[str] = None
    priority: int = 0  # Higher priority gets better treatment
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

# Import our actual strategies module - but we need to avoid the backend __init__.py
# Let's directly test our strategies by importing just the strategies module
sys.path.insert(0, '/d/projects/chat_app/Universal-Ai-Chat-Platform')

# Try to import just the strategies module directly
try:
    # This should work if we avoid triggering the backend __init__.py
    from backend.providers.enhanced.strategies import (
        ProviderCandidate as EnhancedProviderCandidate,
        RoutingContext as EnhancedRoutingContext,
        TaskType as EnhancedTaskType,
        EnhancedProviderManager,
        StrategyFactory
    )
    print("Successfully imported enhanced strategies module!")
    
    def test_strategies():
        """Test the enhanced routing strategies"""
        print("\n=== Testing Enhanced Provider Routing Strategies ===\n")
        
        # Create test candidates
        candidates = [
            EnhancedProviderCandidate(
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
            EnhancedProviderCandidate(
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
            EnhancedProviderCandidate(
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
        
        manager = EnhancedProviderManager()
        
        # Test different contexts
        test_contexts = [
            EnhancedRoutingContext(
                task_type=EnhancedTaskType.CHAT,
                estimated_tokens=500,
                session_id="chat-session-1"
            ),
            EnhancedRoutingContext(
                task_type=EnhancedTaskType.CODING,
                estimated_tokens=1500,
                session_id="coding-session-1"
            ),
            EnhancedRoutingContext(
                task_type=EnhancedTaskType.REASONING,
                estimated_tokens=2000,
                session_id="reasoning-session-1"
            ),
            EnhancedRoutingContext(
                task_type=EnhancedTaskType.VISION,
                estimated_tokens=1000,
                has_vision=True,
                session_id="vision-session-1"
            )
        ]
        
        strategies_to_test = [
            'priority', 'weighted', 'round-robin', 'context-relay', 'fill-first',
            'p2c', 'random', 'least-used', 'cost-optimized', 'reset-aware',
            'reset-window', 'headroom', 'strict-random', 'auto', 'lkgp',
            'context-optimized', 'cache-optimized', 'fusion', 'pipeline'
        ]
        
        for i, context in enumerate(test_contexts):
            print(f"--- Test Context {i+1}: {context.task_type.value} ({context.estimated_tokens} tokens) ---")
            
            for strategy_name in strategies_to_test:
                try:
                    selected = manager.select_provider(candidates, strategy_name, context)
                    print(f"  {strategy_name:18} -> {selected.display_name}")
                except Exception as e:
                    print(f"  {strategy_name:18} -> ERROR: {str(e)[:50]}...")
            
            print()
        
        # Test strategy descriptions
        print("--- Strategy Descriptions ---")
        for strategy_name in ['auto', 'weighted', 'context-optimized', 'lkgp']:
            desc = manager.strategy_factory.get_strategy_description(strategy_name)
            print(f"  {strategy_name:18} -> {desc}")
        
        print("\n=== Test Complete ===")
    
    if __name__ == "__main__":
        test_strategies()

except Exception as e:
    print(f"Failed to import: {e}")
    print("Let's try a different approach...")
    
    # Fallback: directly test by copying the essential parts
    print("\n=== Running Standalone Strategy Tests ===\n")
    
    # Simple test of the strategy logic
    class MockCandidate:
        def __init__(self, name, cost, latency, health, quota):
            self.display_name = name
            self.cost_per_1m_tokens = cost
            self.avg_latency_ms = latency
            self.health_score = health
            self.quota_headroom = quota
            self.error_rate = 0.01
            self.context_window = 8192
            self.supports_vision = True
            self.supports_reasoning = True
            self.supports_tools = True
            self.is_available = True
            self.usage_count = 0
            self.task_fitness = 0.8
        
        def to_dict(self):
            return {"display_name": self.display_name}
    
    # Test weighted strategy logic
    candidates = [
        MockCandidate("openai/gpt-4", 30.0, 800, 0.95, 0.7),
        MockCandidate("anthropic/claude", 15.0, 1200, 0.9, 0.5),
        MockCandidate("ollama/llama3", 0.0, 2000, 0.8, 1.0)
    ]
    
    def weighted_select(cands):
        weights = []
        for c in cands:
            weight = (
                c.health_score * 0.3 +
                c.quota_headroom * 0.3 +
                (1.0 / max(c.cost_per_1m_tokens, 0.001)) * 0.2 +
                (1.0 / max(c.avg_latency_ms, 1.0)) * 0.2
            )
            weights.append(max(weight, 0.01))
        
        total_weight = sum(weights)
        r = random.uniform(0, total_weight)
        upto = 0
        for i, w in enumerate(weights):
            if upto + w >= r:
                return cands[i]
            upto += w
        return cands[-1]
    
    print("Testing weighted strategy (10 samples):")
    results = {}
    for _ in range(10):
        selected = weighted_select(candidates)
        name = selected.display_name
        results[name] = results.get(name, 0) + 1
    
    for name, count in results.items():
        print(f"  {name}: {count}/10 selections")
    
    print("\n=== Standalone Test Complete ===")