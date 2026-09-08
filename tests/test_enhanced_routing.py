#!/usr/bin/env python3
"""
Test script for enhanced provider routing system
"""
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_enhanced_strategies():
    """Test the enhanced routing strategies in isolation"""
    # Import only our enhanced strategies module
    from backend.providers.enhanced.strategies import (
        create_example_candidates,
        EnhancedRouter,
        RoutingContext,
        TaskType,
        ProviderCandidate
    )

    print("=== Testing Enhanced Provider Routing System ===\n")

    # Create manager and register test candidates
    manager = EnhancedRouter()
    candidates = create_example_candidates()
    manager.register_provider("mixed", candidates[0])  # Register with first candidate's config

    # Test different contexts
    test_contexts = [
        RoutingContext(
            model_id="test-model",
            messages=[{"role": "user", "content": "Hello"}],
            task_type=TaskType.CHAT.value,
            max_tokens=500,
            session_id="chat-session-1"
        ),
        RoutingContext(
            model_id="test-model",
            messages=[{"role": "user", "content": "Write a Python function"}],
            task_type=TaskType.CODING.value,
            max_tokens=1500,
            session_id="coding-session-1"
        ),
        RoutingContext(
            model_id="test-model",
            messages=[{"role": "user", "content": "Explain quantum physics"}],
            task_type=TaskType.REASONING.value,
            max_tokens=2000,
            session_id="reasoning-session-1"
        ),
        RoutingContext(
            model_id="test-model",
            messages=[{"role": "user", "content": "Describe this image"}],
            task_type=TaskType.VISION.value,
            max_tokens=1000,
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
        print(f"--- Test Context {i+1}: {context.task_type} ({context.max_tokens} tokens) ---")

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
    test_enhanced_strategies()