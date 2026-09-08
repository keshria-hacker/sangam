"""
Configuration System for Enhanced Provider Routing
Based on OmniRoute's approach but adapted for Sangam
"""
import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import yaml
from pathlib import Path


class RoutingStrategy(Enum):
    """Available routing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LATENCY = "least_latency"
    LEAST_ERROR = "least_error"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LATENCY_BASED_WEIGHTED = "latency_based_weighted"
    ERROR_BASED_WEIGHTED = "error_based_weighted"
    COST_OPTIMIZED = "cost_optimized"
    QUALITY_OPTIMIZED = "quality_optimized"
    BALANCED = "balanced"
    ADAPTIVE = "adaptive"
    PRIORITY_BASED = "priority_based"
    GEOGRAPHIC = "geographic"
    MODEL_SPECIFIC = "model_specific"
    TIME_BASED = "time_based"
    LOAD_SHEDDING = "load_shedding"
    CIRCUIT_BREAKER = "circuit_breaker"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    BATCH_OPTIMIZED = "batch_optimized"
    STREAM_OPTIMIZED = "stream_optimized"


@dataclass
class StrategyConfig:
    """Configuration for a specific routing strategy"""
    name: RoutingStrategy
    enabled: bool = True
    weight: float = 1.0
    parameters: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


@dataclass
class ProviderConfig:
    """Configuration for a specific provider"""
    provider_id: str
    enabled: bool = True
    priority: int = 0  # Lower number = higher priority
    weight: float = 1.0
    max_concurrent_requests: int = 10
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    retry_backoff_factor: float = 2.0
    cost_per_1k_tokens: float = 0.0
    quality_score: float = 1.0  # 0.0 to 1.0
    latency_baseline_ms: float = 1000.0  # Expected latency
    error_rate_threshold: float = 0.05  # 5% error rate before considering unhealthy
    supported_strategies: List[RoutingStrategy] = None
    
    def __post_init__(self):
        if self.supported_strategies is None:
            self.supported_strategies = list(RoutingStrategy)


@dataclass
class RoutingPolicy:
    """Defines how to route requests based on various factors"""
    name: str
    description: str = ""
    default_strategy: RoutingStrategy = RoutingStrategy.ROUND_ROBIN
    strategy_map: Dict[str, RoutingStrategy] = None  # context -> strategy
    fallback_chain: List[RoutingStrategy] = None
    enabled: bool = True
    
    def __post_init__(self):
        if self.strategy_map is None:
            self.strategy_map = {}
        if self.fallback_chain is None:
            self.fallback_chain = [
                RoutingStrategy.LEAST_LATENCY,
                RoutingStrategy.LEAST_ERROR,
                RoutingStrategy.ROUND_ROBIN
            ]


@dataclass
class EnhancedRoutingConfig:
    """Main configuration for enhanced provider routing"""
    # Global settings
    enabled: bool = True
    default_policy: str = "default"
    health_check_interval_seconds: float = 30.0
    metrics_window_size: int = 100  # Number of requests to consider for metrics
    
    # Policies
    policies: Dict[str, RoutingPolicy] = None
    
    # Provider-specific configurations
    provider_configs: Dict[str, ProviderConfig] = None
    
    # Strategy configurations
    strategy_configs: Dict[RoutingStrategy, StrategyConfig] = None
    
    # Advanced features
    enable_model_routing: bool = True
    enable_time_based_routing: bool = False
    enable_geo_routing: bool = False
    enable_cost_optimization: bool = True
    enable_quality_optimization: bool = True
    
    def __post_init__(self):
        if self.policies is None:
            self.policies = {}
        if self.provider_configs is None:
            self.provider_configs = {}
        if self.strategy_configs is None:
            self.strategy_configs = {}


class ConfigManager:
    """Manages loading, saving, and providing access to routing configuration"""
    
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.join(
                os.path.dirname(__file__), 
                "..", 
                "config", 
                "enhanced_routing"
            )
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "routing_config.yaml"
        self._config: Optional[EnhancedRoutingConfig] = None
        self._load_config()
    
    def _load_config(self) -> EnhancedRoutingConfig:
        """Load configuration from file or create default"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                self._config = self._dict_to_config(data)
                return self._config
            except Exception as e:
                print(f"Warning: Failed to load routing config: {e}")
                print("Falling back to default configuration")
        
        # Create default configuration
        self._config = self._create_default_config()
        self._save_config()  # Save default config
        return self._config
    
    def _create_default_config(self) -> EnhancedRoutingConfig:
        """Create default configuration based on current Sangam providers"""
        config = EnhancedRoutingConfig()
        
        # Default policy
        config.policies["default"] = RoutingPolicy(
            name="default",
            description="Default routing policy for Sangam",
            default_strategy=RoutingStrategy.BALANCED,
            strategy_map={
                "chat": RoutingStrategy.LEAST_LATENCY,
                "reasoning": RoutingStrategy.QUALITY_OPTIMIZED,
                "coding": RoutingStrategy.MODEL_SPECIFIC,
                "creative": RoutingStrategy.BALANCED,
                "analysis": RoutingStrategy.LEAST_ERROR
            }
        )
        
        # Provider configurations for existing Sangam providers
        provider_ids = [
            "openai", "anthropic", "nvidia", "together", 
            "groq", "openrouter", "deepseek", "mistral", 
            "gemini", "ollama", "omniroute"
        ]
        
        for provider_id in provider_ids:
            config.provider_configs[provider_id] = ProviderConfig(
                provider_id=provider_id,
                enabled=True,
                priority=self._get_default_priority(provider_id),
                weight=self._get_default_weight(provider_id),
                cost_per_1k_tokens=self._get_default_cost(provider_id),
                quality_score=self._get_default_quality(provider_id),
                latency_baseline_ms=self._get_default_latency(provider_id)
            )
        
        # Strategy configurations
        for strategy in RoutingStrategy:
            config.strategy_configs[strategy] = StrategyConfig(
                name=strategy,
                enabled=True,
                weight=1.0
            )
        
        return config
    
    def _get_default_priority(self, provider_id: str) -> int:
        """Get default priority for provider (lower = higher priority)"""
        # Local providers get higher priority
        local_providers = {"ollama", "omniroute"}
        if provider_id in local_providers:
            return 0
        
        # Fast, cheap providers get higher priority
        fast_cheap = {"groq", "together"}
        if provider_id in fast_cheap:
            return 10
        
        # Quality providers get medium priority
        quality_providers = {"anthropic", "openai"}
        if provider_id in quality_providers:
            return 20
        
        # Others get lower priority
        return 50
    
    def _get_default_weight(self, provider_id: str) -> float:
        """Get default weight for provider"""
        # Higher weight = more preferred
        weights = {
            "ollama": 2.0,      # Free, local, no rate limits
            "groq": 1.8,        # Very fast, good quality
            "together": 1.6,    # Good balance
            "openai": 1.5,      # High quality, reliable
            "anthropic": 1.5,   # High quality, reliable
            "nvidia": 1.4,      # Good for specific models
            "mistral": 1.3,     # Good open models
            "deepseek": 1.3,    # Good coding models
            "gemini": 1.2,      # Good multimodal
            "openrouter": 1.0,  # Aggregator, variable quality
            "omniroute": 1.0,   # Local proxy
        }
        return weights.get(provider_id, 1.0)
    
    def _get_default_cost(self, provider_id: str) -> float:
        """Get default cost per 1K tokens (in USD)"""
        costs = {
            "ollama": 0.0,      # Free (local)
            "groq": 0.0002,     # Very cheap
            "together": 0.0005, # Cheap
            "mistral": 0.0005,  # Cheap
            "deepseek": 0.0005, # Cheap
            "openai": 0.0020,   # Standard
            "anthropic": 0.0025, # Slightly more expensive
            "nvidia": 0.0015,   # Variable
            "gemini": 0.0005,   # Cheap for basic models
            "openrouter": 0.0010, # Aggregator markup
            "omniroute": 0.0,   # Free (local proxy)
        }
        return costs.get(provider_id, 0.0010)
    
    def _get_default_quality(self, provider_id: str) -> float:
        """Get default quality score (0.0 to 1.0)"""
        quality = {
            "ollama": 0.7,      # Depends on local model
            "groq": 0.8,        # Good quality
            "together": 0.75,   # Good quality
            "mistral": 0.8,     # Good open models
            "deepseek": 0.85,   # Excellent for coding
            "openai": 0.9,      # Industry leading
            "anthropic": 0.9,   # Industry leading
            "nvidia": 0.8,      # Good for specific use cases
            "gemini": 0.85,     # Strong multimodal
            "openrouter": 0.7,  # Variable (depends on upstream)
            "omniroute": 0.75,  # Depends on configured upstream
        }
        return quality.get(provider_id, 0.7)
    
    def _get_default_latency(self, provider_id: str) -> float:
        """Get default baseline latency in milliseconds"""
        latency = {
            "ollama": 100.0,    # Local network
            "groq": 200.0,      # Very fast inference
            "together": 800.0,  # Moderate
            "mistral": 700.0,   # Moderate
            "deepseek": 750.0,  # Moderate
            "openai": 600.0,    # Good
            "anthropic": 650.0, # Good
            "nvidia": 500.0,    # Fast for optimized models
            "gemini": 550.0,    # Good
            "openrouter": 1000.0, # Variable (additional hop)
            "omniroute": 50.0,  # Very fast local proxy
        }
        return latency.get(provider_id, 800.0)
    
    def _dict_to_config(self, data: Dict[str, Any]) -> EnhancedRoutingConfig:
        """Convert dictionary to EnhancedRoutingConfig"""
        # This is a simplified conversion - in practice you'd want more robust handling
        config = EnhancedRoutingConfig()
        
        # Handle basic fields
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        # Handle nested objects (simplified)
        if "policies" in data:
            config.policies = {}
            for name, policy_data in data["policies"].items():
                policy = RoutingPolicy(name=name, **policy_data)
                config.policies[name] = policy
        
        if "provider_configs" in data:
            config.provider_configs = {}
            for pid, provider_data in data["provider_configs"].items():
                provider = ProviderConfig(provider_id=pid, **provider_data)
                config.provider_configs[pid] = provider
        
        if "strategy_configs" in data:
            config.strategy_configs = {}
            for strategy_name, strategy_data in data["strategy_configs"].items():
                try:
                    strategy_enum = RoutingStrategy(strategy_name)
                    strategy = StrategyConfig(name=strategy_enum, **strategy_data)
                    config.strategy_configs[strategy_enum] = strategy
                except ValueError:
                    # Skip invalid strategy names
                    continue
        
        return config
    
    def _config_to_dict(self, config: EnhancedRoutingConfig) -> Dict[str, Any]:
        """Convert EnhancedRoutingConfig to dictionary"""
        # Convert to dict with special handling for enums
        result = {
            "enabled": config.enabled,
            "default_policy": config.default_policy,
            "health_check_interval_seconds": config.health_check_interval_seconds,
            "metrics_window_size": config.metrics_window_size,
            "enable_model_routing": config.enable_model_routing,
            "enable_time_based_routing": config.enable_time_based_routing,
            "enable_geo_routing": config.enable_geo_routing,
            "enable_cost_optimization": config.enable_cost_optimization,
            "enable_quality_optimization": config.enable_quality_optimization
        }
        
        # Convert policies
        if config.policies:
            result["policies"] = {}
            for name, policy in config.policies.items():
                policy_dict = {
                    "name": policy.name,
                    "description": policy.description,
                    "default_strategy": policy.default_strategy.value,
                    "strategy_map": {k: v.value for k, v in policy.strategy_map.items()},
                    "fallback_chain": [s.value for s in policy.fallback_chain],
                    "enabled": policy.enabled
                }
                result["policies"][name] = policy_dict
        
        # Convert provider configs
        if config.provider_configs:
            result["provider_configs"] = {}
            for pid, provider in config.provider_configs.items():
                provider_dict = asdict(provider)
                # Convert enums in supported_strategies
                if provider_dict["supported_strategies"]:
                    provider_dict["supported_strategies"] = [
                        s.value for s in provider.supported_strategies
                    ]
                result["provider_configs"][pid] = provider_dict
        
        # Convert strategy configs
        if config.strategy_configs:
            result["strategy_configs"] = {}
            for strategy, strategy_config in config.strategy_configs.items():
                strategy_dict = asdict(strategy_config)
                strategy_dict["name"] = strategy.value  # Convert enum to string
                result["strategy_configs"][strategy.value] = strategy_dict
        
        return result
    
    def get_config(self) -> EnhancedRoutingConfig:
        """Get current configuration"""
        if self._config is None:
            self._load_config()
        return self._config
    
    def save_config(self, config: Optional[EnhancedRoutingConfig] = None):
        """Save configuration to file"""
        if config is None:
            config = self.get_config()
        
        self._config = config
        self._save_config()
    
    def _save_config(self):
        """Internal method to save config to YAML file"""
        if self._config is None:
            return
        
        config_dict = self._config_to_dict(self._config)
        
        # Add header comment
        yaml_content = "# Enhanced Provider Routing Configuration for Sangam\n"
        yaml_content += "# Generated by Hermes Agent - Customize as needed\n\n"
        yaml_content += yaml.dump(config_dict, default_flow_style=False, indent=2)
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
    
    def get_provider_config(self, provider_id: str) -> Optional[ProviderConfig]:
        """Get configuration for specific provider"""
        config = self.get_config()
        return config.provider_configs.get(provider_id)
    
    def update_provider_config(self, provider_id: str, updates: Dict[str, Any]):
        """Update configuration for specific provider"""
        config = self.get_config()
        if provider_id not in config.provider_configs:
            raise ValueError(f"Unknown provider: {provider_id}")
        
        provider = config.provider_configs[provider_id]
        for key, value in updates.items():
            if hasattr(provider, key):
                setattr(provider, key, value)
        
        self.save_config(config)
    
    def get_policy(self, policy_name: str) -> Optional[RoutingPolicy]:
        """Get routing policy by name"""
        config = self.get_config()
        return config.policies.get(policy_name)
    
    def get_strategy_config(self, strategy: RoutingStrategy) -> Optional[StrategyConfig]:
        """Get configuration for specific strategy"""
        config = self.get_config()
        return config.strategy_configs.get(strategy)


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get or create the global config manager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_routing_config() -> EnhancedRoutingConfig:
    """Get the current routing configuration"""
    return get_config_manager().get_config()


# Example usage and validation
if __name__ == "__main__":
    # Test the configuration system
    config_manager = ConfigManager()
    config = config_manager.get_config()
    
    print("=== Enhanced Routing Configuration ===")
    print(f"Enabled: {config.enabled}")
    print(f"Default policy: {config.default_policy}")
    print(f"Number of policies: {len(config.policies)}")
    print(f"Number of providers: {len(config.provider_configs)}")
    print(f"Number of strategies: {len(config.strategy_configs)}")
    
    # Show some provider configs
    print("\n=== Sample Provider Configurations ===")
    for provider_id in ["ollama", "groq", "openai", "anthropic"]:
        provider = config.provider_configs.get(provider_id)
        if provider:
            print(f"{provider_id}:")
            print(f"  Priority: {provider.priority}")
            print(f"  Weight: {provider.weight}")
            print(f"  Cost/1K tokens: ${provider.cost_per_1k_tokens:.4f}")
            print(f"  Quality score: {provider.quality_score:.2f}")
            print(f"  Latency baseline: {provider.latency_baseline_ms:.0f}ms")
    
    # Show default policy
    print("\n=== Default Policy ===")
    default_policy = config.policies.get("default")
    if default_policy:
        print(f"Name: {default_policy.name}")
        print(f"Description: {default_policy.description}")
        print(f"Default strategy: {default_policy.default_strategy.value}")
        print("Strategy map:")
        for context, strategy in default_policy.strategy_map.items():
            print(f"  {context} -> {strategy.value}")
        print(f"Fallback chain: {[s.value for s in default_policy.fallback_chain]}")
    
    print("\n=== Configuration Saved To ===")
    print(config_manager.config_file)