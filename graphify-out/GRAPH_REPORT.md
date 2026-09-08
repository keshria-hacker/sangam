# Graph Report - sangam  (2026-09-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 4348 nodes · 7664 edges · 235 communities (208 shown, 21 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 820 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `18e98e84`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test
- llm.py
- SkillExecutor
- ModelInfo
- strategies.py
- detect_injection
- patch
- ConfigManager
- asyncio
- providers/__init__.py
- app
- auth.py
- test_capability_orchestration.py
- integration.py
- AuthUnitTests
- extract_text
- create_app
- ExecutionResult
- state.js
- base.py
- $
- ProviderConfig
- test_response_intelligence.py
- AuthIntegrationTests
- backend/tests/test_api.py
- patch
- document.py
- OllamaProvider
- SearchResult
- database.py
- patch
- MemoryStore
- chat.js
- ProviderStreamChunk
- main.py
- _make_mock_db
- test_document_coverage.py
- api.py
- resilience.py
- RoutingContext
- test_standalone_routing.py
- detect_intent_signals
- TestRequestResponseValidation
- patch
- app.js
- apiFetch
- sidebar.js
- ResilienceManager
- validate_messages
- SanitizeErrorTests
- truncate_preview
- chunk_text
- classification.py
- _parse_duckduckgo
- resilience_integration.py
- TestContextManager
- patch
- sanitize_for_log
- StrategyFactory
- QueryMode
- patch
- patch
- ResponseEventBuilder
- TestChatCompletionEndpoint
- test_context_manager.py
- test_llm.py
- ProviderRegistryTests
- FetchModelsFromProviderTests
- IndexDocumentTests
- sse_event
- api_skills.py
- TestResponsePolicy
- markdown.js
- FakeClient
- ChatRequest
- models.js
- ChunkTextTests
- context_manager.py
- test_document_new.py
- CategorizeErrorTests
- backend/schemas.py
- TestProviderCapabilities
- TestChatMessage
- LoginLockoutTests
- ProviderModelIntegrationTests
- SecurityMiddlewareTests
- test_rag_coverage.py
- retrieve_relevant_chunks
- ChatStreamRequest
- TestPolicyPresets
- SessionManagementTests
- TestTokenCounting
- ChunkingTests
- _make_client
- MemoryStoreResetLimitTests
- tests/test_api.py
- EdgeCaseTests
- TestProviderRegistry
- TestPolicyEdgeCases
- builtin.py
- ChatIntegrationTests
- RateLimitExemptionTests
- ExportsTests
- ContextManager
- security.py
- tests/conftest.py
- ResolveModelTests
- TestProviderRegistry
- ContextBudget
- TestStreamingChatCompletionEndpoint
- TestPolicyManagementEndpoints
- TestStreamingIntegration
- TestErrorHandlingIntegration
- TestChatRequestConstruction
- TestPolicySelector
- TestPolicyAdapter
- TestStreamChunk
- ToolDefinition
- escapeHtml
- VerifyCsrfTests
- AsyncFacadeTests
- RetrieveRelevantChunksCoverageTests
- ConnectionCooldownManager
- ModelLockoutManager
- ResetVectorIndexTests
- SkillRegistry
- asyncio
- TestAnthropicProvider
- ToolRegistry
- _snippet_after
- createResponseController
- test_rag_new.py
- fixture
- CircuitBreaker
- ProviderMetrics
- build_conversation_profile
- LLMProvider
- TestErrorResponses
- TestMetricsIntegration
- TestE2ESecurity
- TestProviderFactory
- TestPolicyManager
- TestChatResponse
- tools/__init__.py
- ToolResult
- _normalize_url
- _strip_tags
- RetrievalTests
- PromptInjectionValidationTests
- ListModelsCoverageTests
- test_websearch_new.py
- RequestIDMiddleware
- resilience/__init__.py
- asyncio
- TestToolUseFlow
- start.py
- TruncationResult
- analyze_request
- TestProviderManagementEndpoints
- TestAPIPerformance
- TestMultiProviderIntegration
- TestCoreChatFlow
- TestStreamingFlow
- TestProviderFailoverFlow
- TestConversationManagementFlow
- TestE2EPerformance
- TestE2EReliability
- ChatHistoryTests
- FileUploadTests
- PasswordSecurityTests
- FrontendResponseControllerTests
- GetAttrTests
- LinkedProvidersTests
- DeleteDocumentChunksTests
- IntegrationTests
- response_intelligence/config.py
- TestAPIModels
- CSRFProtectionTests
- ImageOCRExtractionTests
- FakeResponse
- create_context_manager
- reset_db
- prompt_injector.py
- async_client
- TestMetricsEndpoints
- TestCORSAndSecurity
- TestBaseProvider
- TestPolicyPerformance
- tools/schemas.py
- e2e_tests.spec.ts
- ModelEndpointTests
- OCRUnavailableTests
- PDFOCRBranchTests
- PlainTextEdgeCaseTests
- PDFExtractionTests
- PDLExtractionTests
- PPTXExtractionTests
- test_model_fetch.py
- StreamCompletionCoverageTests
- GetCollectionTests
- RagFailureLoggingTests
- ProviderEventFacadeTests
- ProviderKeyDeletionTests
- DOCXBranchTests
- PPTXEdgeCaseTests
- StreamCompletionErrorHandlingTests
- TestBaseProvider
- WebSearchTests
- LiteLLMProvider
- HealthEndpointTests
- TestProviderInit
- StartupLauncherTests
- .to_dict
- .to_dict
- e2e_client
- .test_show_first_words_flagged
- backend/__init__.py
- enhanced/__init__.py
- generate_master_key.py
- quality.sh script
- start.sh script
- .test_description_field_missing
- .test_http_404_returns_partial_results
- .test_non_dict_entry_is_skipped
- .test_provider_label_is_set_correctly
- .test_timeout_returns_empty_list
- .test_non_string_input_not_flagged
- update_truncate.py
- sangam

## God Nodes (most connected - your core abstractions)
1. `extract_text()` - 73 edges
2. `test()` - 72 edges
3. `ModelInfo` - 63 edges
4. `$` - 62 edges
5. `QueryMode` - 50 edges
6. `create_app()` - 36 edges
7. `ProviderConfig` - 35 edges
8. `RoutingContext` - 35 edges
9. `showToast()` - 35 edges
10. `BaseProvider` - 34 edges

## Surprising Connections (you probably didn't know these)
- `LoginInvalidCredentialsTests` --uses--> `AuthCredentialsIn`  [INFERRED]
  tests/test_auth_coverage.py → backend/schemas.py
- `RegisterPasswordValidationTests` --uses--> `AuthCredentialsIn`  [INFERRED]
  tests/test_auth_coverage.py → backend/schemas.py
- `TestContextManager` --uses--> `ContextManager`  [INFERRED]
  tests/test_context_manager.py → backend/context_manager.py
- `TestContextManagerIntegration` --uses--> `ContextManager`  [INFERRED]
  tests/test_context_manager.py → backend/context_manager.py
- `TestCreateContextManager` --uses--> `ContextManager`  [INFERRED]
  tests/test_context_manager.py → backend/context_manager.py

## Import Cycles
- None detected.

## Communities (235 total, 21 thin omitted)

### Community 0 - "test"
Cohesion: 0.04
Nodes (53): ForgotPasswordIn, ResetPasswordIn, test(), AuthStatusTests, CleanExpiredSessionsTests, CreateSessionTests, ForgotPasswordTests, GetCurrentUserTests (+45 more)

### Community 1 - "llm.py"
Cohesion: 0.05
Nodes (59): default_model_id(), _fetch_provider_models(), get_db_keys(), __getattr__(), _linked_providers(), list_models(), list_ollama_models(), list_provider_status() (+51 more)

### Community 2 - "SkillExecutor"
Cohesion: 0.08
Nodes (43): _build_validation_model(), BaseModel, skills/executor.py — hardened skill execution with timeouts, retries, and…, Hardened skill executor with: - Per-skill timeout (configurable, with global…, Get or create validation model for a skill (cached)., Execute the LLM call with retry logic for transient failures. Returns: tuple of…, Build a Pydantic model for validating skill parameters at runtime. The model is…, SkillExecutor (+35 more)

### Community 3 - "ModelInfo"
Cohesion: 0.04
Nodes (47): Attempt to start Ollama server (backward-compatible wrapper)., _try_start_ollama(), ModelInfo, ModelInfo, Fetch available models from the provider's API., Standardized model information., Compatibility module - exposes legacy constants from original llm.py for…, clear_inaccessible() (+39 more)

### Community 4 - "strategies.py"
Cohesion: 0.05
Nodes (42): CacheOptimizedStrategy, ContextOptimizedStrategy, ContextRelayStrategy, CostOptimizedStrategy, FillFirstStrategy, FusionStrategy, HeadroomStrategy, LastKnownGoodStrategy (+34 more)

### Community 5 - "detect_injection"
Cohesion: 0.05
Nodes (32): detect_injection(), Scan *text* for prompt injection patterns. Returns ------- (flagged, score,…, DetectInjectionTests, DAN (Do Anything Now) pattern is flagged., Output format override attempts are flagged., Repeat the above text' is flagged., Base64 encoding/decoding references add to score but may not reach threshold., ROT13 decode references add to score but may not reach threshold. (+24 more)

### Community 6 - "patch"
Cohesion: 0.05
Nodes (37): BaseHTTPMiddleware, Request, Response, Log every request/response with timing and request ID for traceability., RequestLoggingMiddleware, CSRFMiddlewareTests, HealthCheckTests, LifespanTests (+29 more)

### Community 7 - "ConfigManager"
Cohesion: 0.06
Nodes (33): ConfigManager, EnhancedRoutingConfig, get_config_manager(), ProviderConfig, Any, Enum, Configuration System for Enhanced Provider Routing Based on OmniRoute's…, Manages loading, saving, and providing access to routing configuration (+25 more)

### Community 8 - "asyncio"
Cohesion: 0.05
Nodes (31): asyncio, Test completion maps policy to OpenAI API parameters., Test streaming maps policy to OpenAI API parameters., Test handling of OpenAI API errors., Test handling of OpenAI streaming errors., Test completion with reasoning models (o1, o3-mini)., Test OpenAI provider reports supported models., Test health check endpoint. (+23 more)

### Community 9 - "providers/__init__.py"
Cohesion: 0.06
Nodes (38): AnthropicProvider, Anthropic provider implementation., Anthropic provider using LiteLLM for unified streaming., BaseProvider, Abstract base class for LLM providers., Get the resolved API key., Build authentication headers for the provider., Build the model listing URL (handles query-key auth). (+30 more)

### Community 10 - "app"
Cohesion: 0.06
Nodes (26): AsyncClient, app(), Build the FastAPI application with a clean test database., AuthEndpointTests, Integration tests for auth endpoints via the router., Valid registration should create user and return token., Short password should be rejected., Password without uppercase should be rejected. (+18 more)

### Community 11 - "auth.py"
Cohesion: 0.09
Nodes (37): auth_status(), _clean_expired_sessions(), _create_session(), current_user(), forgot_password(), get_current_user(), _hash_password(), _hash_token() (+29 more)

### Community 12 - "test_capability_orchestration.py"
Cohesion: 0.09
Nodes (46): capability_decide(), CapabilityDecision, detect_capability_signals(), _mode_str(), Any, Capability Orchestration — Phase 7 Determines which tools/capabilities should…, Detect which capability signals are present in the request. Returns a dict with…, Main entry point: decide which capabilities/tools to offer the model. This is… (+38 more)

### Community 13 - "integration.py"
Cohesion: 0.07
Nodes (36): AsyncGenType, get_routing_config(), Get the current routing configuration, _create_routing_context_from_guidance(), enhanced_stream_completion(), enhanced_stream_response_events(), _get_available_providers_for_model(), Any (+28 more)

### Community 14 - "AuthUnitTests"
Cohesion: 0.05
Nodes (22): AuthStatusTests, AuthUnitTests, create_test_tables(), drop_test_tables(), Same password and salt should produce same hash., Different salts should produce different hashes., Different passwords should produce different hashes., Hash should be 128 hex chars (64 bytes). (+14 more)

### Community 15 - "extract_text"
Cohesion: 0.07
Nodes (17): extract_text(), Dispatches to the right extractor for `extension`. Returns an empty string…, DocumentExtractionTests, CSVExtractionTests, DocxExtractionTests, PlainTextExtractionTests, Verify all PLAIN_TEXT_EXTENSIONS are supported., UTF-8 encoded content is handled correctly. (+9 more)

### Community 16 - "create_app"
Cohesion: 0.07
Nodes (30): Validate CSRF token for state-changing requests. Raise 403 on failure., verify_csrf(), create_app(), Create and configure the FastAPI application. This factory function allows…, CSRFMiddlewareTests, HealthCheckTests, LifespanTests, patch (+22 more)

### Community 17 - "ExecutionResult"
Cohesion: 0.06
Nodes (25): ExecutionResult, get_executor(), Any, Exception, Validate and coerce parameters against skill definition. Returns the…, Execute a single skill with timeout and retry protection. Args: skill_id: The…, Execute dependencies first, then build prompt with their results., Convert exception to user-friendly error message with category. (+17 more)

### Community 18 - "state.js"
Cohesion: 0.05
Nodes (37): filterChats(), filterModels(), [getAbortController, setAbortController], [getActiveChatId, setActiveChatId], [getActiveProviderFilter, setActiveProviderFilter], [getAttachedFiles, setAttachedFiles], [getBackendReachable, setBackendReachable], getChatBuckets() (+29 more)

### Community 19 - "base.py"
Cohesion: 0.10
Nodes (29): Any, parse_litellm_stream_chunk(), ABC, Base provider types and abstract interface., Extract canonical provider-boundary data from a LiteLLM chunk., Mark a model as inaccessible (returned 404/NotFound)., track_inaccessible(), LiteLLM fallback provider - catches any provider not explicitly implemented. (+21 more)

### Community 20 - "$"
Cohesion: 0.07
Nodes (20): clearToasts(), resetToastTimer(), showError(), showInfo(), showSuccess(), showToast(), VISIBLE_TOASTS, $ (+12 more)

### Community 21 - "ProviderConfig"
Cohesion: 0.06
Nodes (24): fetch_models_from_provider(), Backward-compatible wrapper for the old fetch_models_from_provider API. This…, ProviderConfig, Static configuration for a provider., init_provider_registry(), ProviderRegistry, Provider registry - central configuration and discovery., Initialize the registry with all static configurations. (+16 more)

### Community 22 - "test_response_intelligence.py"
Cohesion: 0.11
Nodes (39): build_system_prompt_additions(), Convert structured guidance into system prompt lines. Each addition is a single…, IntentSignal, BaseModel, Detected signals from user message + context. Each field maps to one of the 16…, Complete structured guidance for the model. This is the single output of…, ResponseGuidance, Tests for Response Intelligence Layer (Phase 6). Covers all 16 adaptive… (+31 more)

### Community 23 - "AuthIntegrationTests"
Cohesion: 0.07
Nodes (20): AuthIntegrationTests, Creating the first user succeeds (single-user mode permits one)., A second registration attempt is blocked by single-user mode., Too-short password returns 422., Empty request body returns 422., Valid credentials return a token., Wrong password returns 401., User that was never registered returns 401. (+12 more)

### Community 24 - "backend/tests/test_api.py"
Cohesion: 0.13
Nodes (31): ChatMessage, ChatResponse, default_policy(), failing_provider(), mock_provider(), fixture, Pytest configuration and fixtures for Phase 4 Adaptive Response Intelligence…, Default response policy for testing. (+23 more)

### Community 25 - "patch"
Cohesion: 0.07
Nodes (23): CSVEdgeCaseTests, ExtractTextDispatchTests, ImageOCRBranchTests, patch, Tests for image OCR branches (lines 200-215)., Image mode conversion (lines 207-208)., No text detected returns specific message (lines 211-212)., General exception during OCR returns error message (lines 214-215). (+15 more)

### Community 26 - "document.py"
Cohesion: 0.09
Nodes (26): _extract_csv(), _extract_docx(), _extract_image_ocr(), _extract_pdf(), _extract_pdf_ocr(), _extract_pptx(), _extract_xlsx(), Path (+18 more)

### Community 27 - "OllamaProvider"
Cohesion: 0.07
Nodes (24): OllamaProvider, Ollama local model provider with native streaming API., _make_ollama_config(), _make_openai_config(), patch, ProviderConfig, Tests for OllamaProvider., Test OllamaProvider can be instantiated with config. (+16 more)

### Community 28 - "SearchResult"
Cohesion: 0.09
Nodes (24): format_context(), Real web search for the chat platform. Out of the box this uses DuckDuckGo's…, Render search results as a system/context block the model can use., Run a web search and return parsed results. Raises ``RuntimeError`` on…, _search_duckduckgo(), _search_tavily(), SearchResult, web_search() (+16 more)

### Community 29 - "database.py"
Cohesion: 0.07
Nodes (28): Base, _create_engine(), _EngineProxy, get_db(), get_engine(), AsyncSession, database.py — async SQLAlchemy engine, session factory, and the Base…, FastAPI dependency — yields a request-scoped async session. (+20 more)

### Community 30 - "patch"
Cohesion: 0.07
Nodes (24): _provider_reachable(), Check if provider endpoint is reachable with given key., ClearInaccessibleModelsTests, DefaultModelIdTests, ListProviderStatusCoverageTests, ProviderReachableTests, patch, Tests for _provider_reachable function covering HTTP error paths (lines… (+16 more)

### Community 31 - "MemoryStore"
Cohesion: 0.07
Nodes (20): get_rate_limit_middleware(), BaseHTTPMiddleware, Request, RateLimitConfig, RateLimitMiddleware, Rate limiting middleware for the API. Provides per-IP and per-user rate…, Factory for the rate limit middleware (allows dependency injection in tests).…, Configuration for a rate limit tier. (+12 more)

### Community 32 - "chat.js"
Cohesion: 0.13
Nodes (32): autoResizeTextarea(), buildMessageNode(), doCancel(), doSave(), elements, getProviderInfo(), handleFileSelection(), handleSend() (+24 more)

### Community 33 - "ProviderStreamChunk"
Cohesion: 0.10
Nodes (22): ProviderStreamChunk, Any, Stream a completion from the provider., Provider-boundary stream data before canonical event serialization. Existing…, Stream canonical Sangam response events with tool execution support., stream_response_events(), Canonical tool call from the model., ToolCall (+14 more)

### Community 34 - "main.py"
Cohesion: 0.09
Nodes (23): get_settings(), config.py — centralized, typed application settings. Everything environment-…, Cached so the .env file is only parsed once per process., Clear the settings cache for testing., reset_settings(), Settings, init_db(), Create tables on startup. For anything beyond SQLite-for-a-resume-project,… (+15 more)

### Community 35 - "_make_mock_db"
Cohesion: 0.07
Nodes (23): ChatManagementTests, FileUploadTests, MagicAvailabilityTests, _make_mock_db(), ProviderKeyManagementTests, Tests for api.py branch coverage - targeting uncovered lines., Tests for chat management endpoints (lines 272, 280-283, 291-295)., Get chat returns 404 when not found (line 282). (+15 more)

### Community 36 - "test_document_coverage.py"
Cohesion: 0.06
Nodes (23): dict, ConstantsEdgeCaseTests, ImportErrorTests, PasswordProtectedPDFTests, PDFOCRSizeLimitTests, PDFPdf2imageNotInstalledTests, Additional tests for document.py to achieve higher branch coverage. Tests…, Tests for import error handling (lines 20-21). (+15 more)

### Community 37 - "api.py"
Cohesion: 0.12
Nodes (31): chat_stream(), clear_inaccessible_models(), delete_chat(), delete_provider_key(), get_chat(), _get_magic(), get_models(), get_providers() (+23 more)

### Community 38 - "resilience.py"
Cohesion: 0.07
Nodes (23): CircuitBreakerConfig, CircuitBreakerState, ConnectionPoolConfig, get_resilience_manager(), ModelLockoutConfig, ProviderMetrics, Enum, Get average latency in seconds (+15 more)

### Community 39 - "RoutingContext"
Cohesion: 0.15
Nodes (6): AutoStrategy, ProviderCandidate, Use Auto Combo scoring (14-factor), Calculate the 14-factor auto score, RoutingContext, Calculate how well this provider fits the task type

### Community 40 - "test_standalone_routing.py"
Cohesion: 0.08
Nodes (22): create_example_candidates(), Enum, Create example provider candidates for testing, TaskType, Test the enhanced routing strategies in isolation, Test script for enhanced provider routing system, test_enhanced_strategies(), MockCandidate (+14 more)

### Community 41 - "detect_intent_signals"
Cohesion: 0.06
Nodes (32): detect_intent_signals(), _detect_tool_need(), Detect all 16 behavioral signals from message + context. Returns an…, Detect tool need level from message and signals., Test 1: Short query → wants_concise=True, max_paragraphs constraint., Test 2: 'explain in detail' → wants_detailed=True., Test 3: Factual query → wants_direct_answer=True, mode=FACTUAL., Test 4: Follow-up reference → has_followup=True, profile populated. (+24 more)

### Community 42 - "TestRequestResponseValidation"
Cohesion: 0.06
Nodes (19): Test validation of requests and responses., Test request validation catches missing fields., Test request validates message role values., Test response validates finish_reason values., Test response validates usage token counts., Test stream chunk validates delta content., TestRequestResponseValidation, Test provider configuration handling. (+11 more)

### Community 43 - "patch"
Cohesion: 0.11
Nodes (16): _search_brave(), patch, Long snippets are truncated to 400 chars., Tests for _search_tavily function (mocked HTTP)., Successful Tavily response parsed correctly., Empty results raises RuntimeError., Results without URL are skipped., HTTP errors raise RuntimeError. (+8 more)

### Community 44 - "app.js"
Cohesion: 0.16
Nodes (27): elements, init(), initDOM(), initGlobalListeners(), startApplication(), syncDropdownsFromState(), initAppState(), initElements() (+19 more)

### Community 45 - "apiFetch"
Cohesion: 0.16
Nodes (26): elements, hideProfilePopup(), initAuth(), initializeAuth(), initProfilePopup(), logout(), positionProfilePopup(), setProfile() (+18 more)

### Community 46 - "sidebar.js"
Cohesion: 0.17
Nodes (27): selectModel(), closeProfilePopup(), buildChatItem(), callChatModule(), closeContextMenu(), closeMobileSidebar(), deleteChat(), elements (+19 more)

### Community 47 - "ResilienceManager"
Cohesion: 0.10
Nodes (14): CircuitBreakerConfig, Any, Main resilience manager coordinating all resilience mechanisms, Get or create circuit breaker for provider, Get or create metrics for provider, Record successful request, Record failed request and apply resilience mechanisms, Apply appropriate resilience mechanisms based on failure patterns (+6 more)

### Community 48 - "validate_messages"
Cohesion: 0.11
Nodes (15): Any, Validate a list of chat messages for prompt injection. Returns the messages…, validate_messages(), Clean messages pass through unchanged., Tests for validate_messages function., Injection in user message adds _injection_warning metadata., Injection in assistant message also adds warning., Only messages with injections get warnings. (+7 more)

### Community 49 - "SanitizeErrorTests"
Cohesion: 0.08
Nodes (14): Tests for sanitize_error function., OpenAI API key pattern is redacted., Anthropic API key pattern is redacted., Gemini API key pattern is redacted., NVIDIA API key pattern is redacted., Together AI API key pattern is redacted., Groq API key pattern is redacted., OpenRouter API key pattern is redacted. (+6 more)

### Community 50 - "truncate_preview"
Cohesion: 0.12
Nodes (9): truncate_preview(), Tests for truncate_preview edge cases., Unicode characters at boundary handled correctly., Newlines in middle of text handled., Exact length with unicode doesn't over-truncate., TruncatePreviewEdgeCases, Tests for truncate_preview function., TruncatePreviewTests (+1 more)

### Community 51 - "chunk_text"
Cohesion: 0.11
Nodes (14): chunk_text(), Split *text* into overlapping chunks of approximately *chunk_size* tokens.…, ChunkTextCoverageTests, Tests for chunk_text function covering edge cases (lines 133, 161-162)., Empty text returns empty list (line 123-124)., Whitespace-only text returns empty list., Text splits on double newlines., Single oversized paragraph is hard-split (line 144-148). (+6 more)

### Community 52 - "classification.py"
Cohesion: 0.09
Nodes (23): _detect_capability_hint(), _detect_tone(), _has_followup_reference(), _is_ambiguous(), _is_analysis_request(), _is_coding_request(), _is_creative_request(), _is_factual_request() (+15 more)

### Community 53 - "_parse_duckduckgo"
Cohesion: 0.12
Nodes (14): _parse_duckduckgo(), ParseDuckDuckGoTests, Parse basic DuckDuckGo results., Parsing respects max_results limit., Empty HTML raises RuntimeError., HTML without result-link class raises RuntimeError., Handles double quotes in class attribute., Handles mixed single/double quotes. (+6 more)

### Community 54 - "resilience_integration.py"
Cohesion: 0.12
Nodes (20): get_resilience_manager(), Get comprehensive resilience status, Decorator to automatically apply resilience mechanisms to provider calls, with_resilience(), enhance_provider_with_resilience(), get_provider_health_score(), get_resilience_status(), is_provider_available() (+12 more)

### Community 55 - "TestContextManager"
Cohesion: 0.08
Nodes (13): Tests for ContextManager truncation logic., Empty message list should return empty result., Messages that fit should not be truncated., System messages should always be preserved., Tool messages (results) should always be preserved., Assistant messages with tool_calls should be preserved., The last user message should always be preserved., Old user/assistant pairs should be truncated first. (+5 more)

### Community 56 - "patch"
Cohesion: 0.11
Nodes (14): get_websearch(), Live web search. Works out of the box via DuckDuckGo (no key); upgrade by…, patch, Tests for provider model refresh endpoint., Unknown provider returns 404., Local provider returns 400., Missing API key returns 400., Tests for web search endpoint. (+6 more)

### Community 57 - "sanitize_for_log"
Cohesion: 0.12
Nodes (12): Truncate and strip control chars for safe logging., sanitize_for_log(), Tests for sanitize_for_log function., Normal text passes through unchanged (within limit)., Control characters (except \\n, \\r, \\t) are stripped., Newlines are preserved (not in control char range)., \\r is preserved in the regex (not in 0x00-0x08 range)., Text longer than max_len is truncated with ellipsis. (+4 more)

### Community 58 - "StrategyFactory"
Cohesion: 0.09
Nodes (13): Any, Factory for creating routing strategy instances, Create a strategy instance by name, Get list of available strategy names, Get description of a strategy, Initialize enhanced router Args: resilience_manager: Resilience manager…, Register a provider with the router, Create a ProviderCandidate from provider config (+5 more)

### Community 59 - "QueryMode"
Cohesion: 0.12
Nodes (23): classify_query_mode(), Classify the query into a high-level mode. Priority order (first match wins):…, StrEnum, QueryMode, High-level query classification modes., Test: Phase 6 response guidance remains functional., test_phase6_signals_preserved(), Test: QueryMode.CREATIVE for creative writing. (+15 more)

### Community 60 - "patch"
Cohesion: 0.09
Nodes (12): patch, Timeout returns structured error result (lines 221-229)., Generic exception is categorized (lines 230-239)., Dependency result is stored in context (lines 255-256)., Validation error from dependency execution is propagated (lines 199-200)., Empty response from model raises ValueError (line 302)., Successful execution returns content., Missing 'skill' in chain step returns error result (lines 344-348). (+4 more)

### Community 61 - "patch"
Cohesion: 0.11
Nodes (13): patch, Tests for retrieve_relevant_chunks function., Empty query returns empty list., None query returns empty list., None file_ids returns empty list., Successful retrieval returns formatted chunks., Empty results from ChromaDB returns empty list., None results from ChromaDB returns empty list. (+5 more)

### Community 62 - "ResponseEventBuilder"
Cohesion: 0.19
Nodes (6): Any, Small lifecycle/sequencing guard for one assistant response., Single canonical response event sent through the response pipeline., ResponseEvent, ResponseEventBuilder, ResponseEventLifecycleTests

### Community 63 - "TestChatCompletionEndpoint"
Cohesion: 0.09
Nodes (12): Test completion validates messages array., Test completion validates individual message structure., Test completion applies policy parameters from request., Test completion returns token usage., Test completion returns finish reason., Test completion handles provider errors gracefully., Test completion uses fallback provider on failure., Test POST /api/v1/chat/completions endpoint. (+4 more)

### Community 64 - "test_context_manager.py"
Cohesion: 0.12
Nodes (16): MockModelInfo, Unit tests for ContextManager - Phase 9 P0 token budget and safe truncation.…, Test that Phase 6 guidance is preserved when possible, but can be truncated if…, Mock ModelInfo for testing., Test with small context window (e.g., 2048)., Integration-style tests simulating real usage., Simulate a chat with system prompt, RAG, web search, and history., A complete tool invocation cycle should be preserved. (+8 more)

### Community 65 - "test_llm.py"
Cohesion: 0.09
Nodes (14): FetchModelsFromProviderTests, ModelInfoTests, OllamaWrapperTests, Comprehensive tests for llm.py — Unified LLM Provider Facade. Tests cover: -…, Tests for fetch_models_from_provider legacy wrapper., Returns list of dicts with expected fields., Deduplicates models by raw ID., Tests for Ollama backward-compatible wrapper functions. (+6 more)

### Community 66 - "ProviderRegistryTests"
Cohesion: 0.09
Nodes (12): ProviderRegistryTests, Tests for provider registry and constants., PROVIDERS dict is available., CURATED_MODELS dict is available., MODELS dict is available., ProviderRegistry instance is available., _inaccessible_models set is available., inaccessible_models alias points to same set. (+4 more)

### Community 67 - "FetchModelsFromProviderTests"
Cohesion: 0.09
Nodes (12): FetchModelsFromProviderTests, Custom header auth (Anthropic-style X-API-Key)., When a custom ``name_field`` is provided, it should be used., When ``name_field`` is set but missing in the entry, derive from id., Description is extracted when ``description_field`` is specified., Model IDs have a prefix stripped (Gemini ``models/`` -> ``gemini-...``)., Models whose id contains an ``_NON_CHAT_MARKERS`` substring (embed, rerank,…, Models like ``llama-3.2-90b-vision-instruct`` and ``cosmos3-nano-reasoner``… (+4 more)

### Community 68 - "IndexDocumentTests"
Cohesion: 0.10
Nodes (11): IndexDocumentCoverageTests, Empty chunks returns 0 (line 202-203)., Exception during indexing returns -1 (lines 222-224)., IndexDocumentTests, Tests for index_document function., Reset vector index before each test., Clean up after each test., Indexing empty text returns 0. (+3 more)

### Community 69 - "sse_event"
Cohesion: 0.12
Nodes (13): Serialize multiline provider output as a valid SSE frame., Serialize a canonical response event as an SSE frame., sse_event(), sse_response_event(), Tests for SSE event formatting., Simple single-line data becomes valid SSE., Event type is included when provided., Multi-line data is split into multiple data: lines. (+5 more)

### Community 70 - "api_skills.py"
Cohesion: 0.14
Nodes (20): chain_skills(), execute_skill(), get_skill(), list_categories(), list_skills(), BaseModel, get, post (+12 more)

### Community 71 - "TestResponsePolicy"
Cohesion: 0.10
Nodes (12): Test stop_sequences defaults to empty list, not None., Test various temperature values., Test various top_p values., Test reasoning_budget is only relevant when enable_reasoning=True., Test ResponsePolicy configuration and validation., Test creating a policy with defaults., Test creating a policy with custom values., Test that ResponsePolicy is immutable (frozen dataclass). (+4 more)

### Community 72 - "markdown.js"
Cohesion: 0.17
Nodes (16): showReasoningInNode(), areMarkdownLibsLoaded(), checkLibraries(), configureMarked(), enhanceCodeBlocks(), finalizeMarkdownRender(), getMarkdownCSP(), injectMarkdownCSP() (+8 more)

### Community 73 - "FakeClient"
Cohesion: 0.12
Nodes (8): FakeClient, Simulates ``httpx.AsyncClient``. Each test provides a ``responses`` callable…, ModelSelectionTests, The picker must mirror the provider's API, not a static catalogue., Ollama must surface only real, pulled models — never a hard-coded default list…, When the local Ollama server isn't up, list_ollama_models should attempt to…, NVIDIA NIM exposes vision/guard/embedding/rerank models too. The picker must…, When the live API answers, curated defaults must not be injected.

### Community 74 - "ChatRequest"
Cohesion: 0.14
Nodes (12): ChatRequest, Immutable chat completion request., Test reasoning policy parameters are passed to provider., Integration tests for provider completion/streaming with policies., TestProviderIntegration, Test ChatRequest immutable data structure., Test creating a chat request., Test request with custom metadata. (+4 more)

### Community 75 - "models.js"
Cohesion: 0.29
Nodes (19): setupGlobalNamespace(), ../features/settings/settings.js, closeModelDropdown(), elements, formatContextSize(), getModelSpeedClass(), getProviderInfo(), handleLoadError() (+11 more)

### Community 76 - "ChunkTextTests"
Cohesion: 0.10
Nodes (11): ChunkTextTests, Overlap from previous chunk carried into next chunk., Multiple small paragraphs combine into chunks., Custom chunk_size and overlap parameters are respected., Tests for the chunk_text function., Empty string returns empty list., Whitespace-only string returns empty list., Text exactly at chunk boundary returns single chunk. (+3 more)

### Community 77 - "context_manager.py"
Cohesion: 0.13
Nodes (13): count_tokens(), _get_encoding_for_model(), Context Manager - Token Budget & Safe Truncation (Phase 9 P0) This module…, Get tiktoken encoding for a model ID. Falls back to cl100k_base if model-…, Count tokens in a text string using the given encoding., Encoding, GPT-4-Turbo should use cl100k_base encoding., Claude models should fall back to cl100k_base. (+5 more)

### Community 78 - "test_document_new.py"
Cohesion: 0.11
Nodes (11): _extract_plain_text(), ErrorHandlingTests, ExtensionNormalizationTests, PlainTextExtractionInternalTests, Comprehensive tests for document.py — file text extraction. Tests cover: -…, Tests for extension case normalization., Extension with leading dot is normalized., Tests for internal plain text extraction function. (+3 more)

### Community 79 - "CategorizeErrorTests"
Cohesion: 0.11
Nodes (10): CategorizeErrorTests, Tests for _categorize_error method., asyncio.TimeoutError categorized as timeout., ConnectionError categorized as network error., ValueError categorized as validation error., 429/rate limit categorized as rate limited., 401/unauthorized categorized as auth failed., 404/not found categorized as model not found. (+2 more)

### Community 80 - "backend/schemas.py"
Cohesion: 0.19
Nodes (17): AuthStatusOut, AuthTokenOut, ChatDetailOut, ChatMessageIn, ChatOut, FileUploadOut, ForgotPasswordOut, MessageOut (+9 more)

### Community 81 - "TestProviderCapabilities"
Cohesion: 0.11
Nodes (10): Test provider capability reporting., Test OpenAI provider reports streaming support., Test OpenAI provider reports tool call support., Test OpenAI provider reports reasoning support., Test Anthropic provider reports streaming support., Test Anthropic provider reports tool call support., Test Anthropic provider reports thinking support., Test provider reports maximum context window. (+2 more)

### Community 82 - "TestChatMessage"
Cohesion: 0.11
Nodes (10): Test ChatMessage immutable data structure., Test creating a user message., Test assistant message with tool calls., Test creating a tool result message., Test creating a system message., Test conversion to provider-compatible dict., Test to_dict excludes None optional fields., Test that ChatMessage is immutable. (+2 more)

### Community 83 - "LoginLockoutTests"
Cohesion: 0.19
Nodes (12): FastAPI, LoginLockoutTests, _make_mock_db(), _make_mock_response(), Tests for the brute-force login lockout (audit C-007). A username is locked out…, A blocked attempt logs a warning with the username., One user's failures do not affect another user's budget., Create a mock db session whose ``scalar`` returns are consumed in order. (+4 more)

### Community 84 - "ProviderModelIntegrationTests"
Cohesion: 0.14
Nodes (9): Register and login, return auth headers. In single-user mode register may…, ProviderModelIntegrationTests, GET /api/settings/providers returns provider configs., PUT and DELETE a provider API key., GET /api/settings/providers/{id}/models/refresh triggers model fetch., Test /api/providers and /api/models endpoints., GET /api/providers lists all available providers., GET /api/providers should require auth. (+1 more)

### Community 85 - "SecurityMiddlewareTests"
Cohesion: 0.12
Nodes (7): Every response should have X-Request-ID., Custom X-Request-ID should be echoed back., Different requests should get different IDs (when not custom)., Test security headers, CSRF, and request ID middleware., Content-Security-Policy header should be present., POST with cookie but missing CSRF header should fail., SecurityMiddlewareTests

### Community 86 - "test_rag_coverage.py"
Cohesion: 0.11
Nodes (12): CloseClientTests, GetClientTests, Tests for rag.py branch coverage - targeting uncovered lines: - 79:…, Tests for _get_client function (line 79)., _get_client creates PersistentClient when not exists., Tests for reset_vector_index function., ValueError during delete_collection is caught (line 312-313)., NotFoundError during delete_collection is caught (line 314-315). (+4 more)

### Community 87 - "retrieve_relevant_chunks"
Cohesion: 0.19
Nodes (14): delete_document_chunks(), _get_client(), _get_collection(), index_document(), Any, rag.py — chunk + retrieve for document RAG. Replaces the old approach of…, Chunk, embed, and store *text* in the vector index. Parameters ----------…, Retrieve the top-*top_k* most relevant chunks for *query*. Parameters… (+6 more)

### Community 88 - "ChatStreamRequest"
Cohesion: 0.15
Nodes (8): ChatStreamRequest, model_validator, ChatStreamTests, Tests for chat streaming endpoint validation logic., Chat stream should validate model exists before streaming., Unknown model should raise 400., Web search, when enabled, injects context into stream., ChatStreamRequestTests

### Community 89 - "TestPolicyPresets"
Cohesion: 0.12
Nodes (10): fixture, Test built-in policy presets., Built-in policy presets - to be implemented in response_policy module., Test balanced preset exists., Test fast preset exists., Test thorough preset exists., Test creative preset exists., Test precise preset exists. (+2 more)

### Community 90 - "SessionManagementTests"
Cohesion: 0.12
Nodes (8): Expired sessions should be deleted., _create_session should create AuthSession in database., _create_session should delete previous sessions for the same user., Tests for session management., Expired sessions should not allow access., Logout should delete server-side session record., SessionManagementTests, Select the best provider candidate based on the strategy

### Community 91 - "TestTokenCounting"
Cohesion: 0.12
Nodes (9): Tests for token counting utilities., Empty string should return 0 tokens., Simple text should return approximate token count., User message should include role overhead., System message should be counted., Assistant message with tool_calls should include them., Tool message should include tool_call_id., Vision message with structured content should count text parts. (+1 more)

### Community 92 - "ChunkingTests"
Cohesion: 0.12
Nodes (9): ChunkingTests, Text shorter than one chunk returns a single chunk., Empty string returns an empty list., Whitespace-only input returns an empty list., Text that exceeds one chunk's char target produces two chunks., Adjacent chunks share some text when overlap > 0., A single oversized paragraph is hard-split at the chunk boundary., Text just under the char target stays as one chunk. (+1 more)

### Community 93 - "_make_client"
Cohesion: 0.14
Nodes (8): FetchProviderModelsWrapperTests, _make_client(), Query-parameter auth (Gemini-style ``?key=...``)., Duplicate model IDs in the same page or across pages are collapsed to a single…, The private wrapper that maps ``PROVIDER_MODEL_API`` config to…, If two raw IDs produce the same prefixed LiteLLM ID, dedup., Patch ``httpx.AsyncClient`` so every instance uses *handler* (a callable…, Bearer token auth (OpenAI, Together, Groq, OpenRouter, …).

### Community 94 - "MemoryStoreResetLimitTests"
Cohesion: 0.12
Nodes (10): MemoryStoreResetLimitTests, Tests for the rate-limit store ``reset_limit`` method (audit C-007). The brute-…, ``MemoryStore.reset_limit`` clears recorded hits for a key., After a reset the same key gets a fresh budget again., Resetting a key that was never used must not raise., ``RedisStore.reset_limit`` deletes the Redis key and the fallback., The Redis key is deleted via the connected client., Hits recorded in the in-memory fallback are cleared too. (+2 more)

### Community 95 - "tests/test_api.py"
Cohesion: 0.12
Nodes (10): Reset the engine for testing (creates new engine with current settings)., reset_engine_for_testing(), ProviderKeyManagementTests, Unit tests for the API module (api.py). Tests cover: - Health endpoints -…, Tests for provider API key management endpoints., list_provider_keys skips local providers., Returns linked status for DB keys and env keys., Tests for clearing inaccessible models cache. (+2 more)

### Community 96 - "EdgeCaseTests"
Cohesion: 0.12
Nodes (9): prompt_injection.py — heuristic-based prompt injection detection for chat…, EdgeCaseTests, Comprehensive tests for prompt_injection.py — prompt injection detection. Tests…, Edge cases and boundary conditions., Very long text with injection is handled., Unicode variations of injection patterns., Patterns match case-insensitively., Partial word matches (e.g., 'instructions' in 'instruction') don't falsely… (+1 more)

### Community 97 - "TestProviderRegistry"
Cohesion: 0.12
Nodes (9): Test provider registration and lookup., Test registering a provider., Test getting a registered provider., Test getting unknown provider raises error., Test listing all registered providers., Test checking if provider supports a model., Test automatic provider selection for model., Test health checking all providers. (+1 more)

### Community 98 - "TestPolicyEdgeCases"
Cohesion: 0.12
Nodes (9): Test edge cases and error handling in policy system., Test handling of empty messages list., Test handling of very long conversation context., Test validation rejects invalid temperature., Test validation rejects invalid max_tokens., Test validation catches missing required fields., Test policy can be serialized/deserialized., Test creating policy from dictionary. (+1 more)

### Community 99 - "builtin.py"
Cohesion: 0.23
Nodes (15): execute_code_handler(), _get_workspace_root(), _is_path_allowed(), list_files_handler(), Any, Path, Built-in tools for the chat application., List files in a directory. (+7 more)

### Community 100 - "ChatIntegrationTests"
Cohesion: 0.17
Nodes (8): ChatIntegrationTests, Get a non-existent chat should return 404., POST /api/chat/stream without model should fail validation., POST /api/chat/stream without auth should be rejected., POST /api/chat/stream with unknown model should not crash., Test /api/chats and /api/chat/stream endpoints., A new user should have an empty chat list., Deleting a non-existent chat should return 404.

### Community 101 - "RateLimitExemptionTests"
Cohesion: 0.12
Nodes (9): RateLimitExemptionTests, Tests for rate limit exempt paths., Health endpoints are exempt., OpenAPI docs are exempt., Model inaccessible clear endpoint is exempt., Auth endpoints have strict limits., Chat streaming has appropriate limits., File upload has limits. (+1 more)

### Community 102 - "ExportsTests"
Cohesion: 0.12
Nodes (9): ExportsTests, Tests for __all__ exports., All exports in __all__ are available in module., Main async API functions are exported., Provider registry exports are present., Type exports are present., Legacy compatibility exports are present., Model discovery exports are present. (+1 more)

### Community 103 - "ContextManager"
Cohesion: 0.23
Nodes (10): ContextManager, count_message_tokens(), Any, Manages token budget and safe truncation for conversation messages., Count total tokens for a list of messages., Classify a system message by type for priority-based truncation. Returns:…, Group tool interactions into atomic units. Returns: (preserved_tools,…, Truncate messages to fit within token budget using priority-based strategy.… (+2 more)

### Community 104 - "security.py"
Cohesion: 0.18
Nodes (13): decrypt_field(), encrypt_field(), EncryptionError, _get_fernet(), Exception, security.py — Field-level encryption for sensitive data at rest. Uses Fernet…, Raised when encryption/decryption fails., Encrypt a string for database storage. Returns bytes. (+5 more)

### Community 105 - "tests/conftest.py"
Cohesion: 0.17
Nodes (14): auth_headers(), client(), event_loop(), mock_httpx_client(), _mock_ocr_dependencies(), fixture, Reusable test fixtures for Sangam backend tests. Provides async app client,…, Register a test user and return user info + auth. (+6 more)

### Community 106 - "ResolveModelTests"
Cohesion: 0.13
Nodes (8): ollama:model format returns ModelInfo with ollama provider., ollama:model:tag format works correctly., provider::litellm_id format resolves from CURATED_MODELS., provider::litellm_id with unknown model creates basic ModelInfo., Invalid model ID format returns None., Empty string returns None., Provider not in CURATED_MODELS falls back correctly., ResolveModelTests

### Community 107 - "TestProviderRegistry"
Cohesion: 0.13
Nodes (8): Tests for ProviderRegistry., Test registry can be created., Should return dict of all provider configs., Should return config for known provider., Should return config for OpenAI., Should return list of all provider IDs., Should return list of non-local provider IDs., TestProviderRegistry

### Community 108 - "ContextBudget"
Cohesion: 0.18
Nodes (9): ContextBudget, Token budget configuration for a request., Tokens available for input context (history + system + RAG + tools)., Initialize context manager for a specific model. Args: model_info: ModelInfo…, Tests for ContextBudget dataclass., Available context = window - output - margin., Small context window should handle correctly., Available should not go negative. (+1 more)

### Community 109 - "TestStreamingChatCompletionEndpoint"
Cohesion: 0.14
Nodes (8): Test POST /api/v1/chat/completions with stream=True., Test streaming endpoint requires authentication., Test streaming returns Server-Sent Events., Test SSE format matches OpenAI specification., Test final SSE chunk includes usage., Test stream handles client disconnect gracefully., Test stream enforces timeout., TestStreamingChatCompletionEndpoint

### Community 110 - "TestPolicyManagementEndpoints"
Cohesion: 0.14
Nodes (8): Test policy management API endpoints., Test GET /api/v1/policies endpoint., Test GET /api/v1/policies/{name} endpoint., Test POST /api/v1/policies endpoint., Test PUT /api/v1/policies/{name} endpoint., Test DELETE /api/v1/policies/{name} endpoint., Test policies are validated on create/update., TestPolicyManagementEndpoints

### Community 111 - "TestStreamingIntegration"
Cohesion: 0.14
Nodes (8): Test streaming-specific integration behaviors., Test streaming yields chunks in correct order., Test handling of partial/incomplete chunks., Test final chunk includes aggregated usage., Test streaming reasoning content deltas., Test stream can be cancelled mid-generation., Test handling of consumer backpressure., TestStreamingIntegration

### Community 112 - "TestErrorHandlingIntegration"
Cohesion: 0.14
Nodes (8): Test error handling across the request pipeline., Test handling of invalid API key., Test rate limit handling with retry logic., Test handling of context length exceeded., Test handling of content policy violations., Test retry on transient network errors., Test behavior when all providers fail., TestErrorHandlingIntegration

### Community 113 - "TestChatRequestConstruction"
Cohesion: 0.14
Nodes (8): Integration tests for building chat requests with policies., Test building request from conversation history with policy., Test that policy parameters are mapped to provider-specific format., Test building request with system prompt injection., Test request building truncates history to fit context window., Test request building includes tool definitions when provided., Test request building validates policy works with model., TestChatRequestConstruction

### Community 114 - "TestPolicySelector"
Cohesion: 0.14
Nodes (8): Test policy selection logic based on context., Test policy selection for simple, short queries., Test policy selection for complex reasoning tasks., Test policy selection for creative tasks., Test policy selection for code generation., Test policy selection respects user tier limits., Test policy adapts max_tokens based on context length., TestPolicySelector

### Community 115 - "TestPolicyAdapter"
Cohesion: 0.14
Nodes (8): Test dynamic policy adaptation during conversation., Test policy adapts when requests timeout., Test policy adapts when error rate increases., Test policy adapts when latency is high., Test policy reduces max_tokens when finish_reason is 'length'., Test policy increases temperature when responses are repetitive., Test policy enables reasoning for detected complex queries., TestPolicyAdapter

### Community 116 - "TestStreamChunk"
Cohesion: 0.14
Nodes (8): Test StreamChunk immutable data structure., Test basic stream chunk., Test final chunk with finish reason., Test chunk with usage info., Test chunk with tool call delta., Test chunk with reasoning delta., Test that StreamChunk is immutable., TestStreamChunk

### Community 117 - "ToolDefinition"
Cohesion: 0.15
Nodes (9): Any, Register a tool definition., Get a tool definition by name., Get all enabled tool definitions., Convert enabled tools to OpenAI function format., Complete definition of a tool available to the model., tool_definition_to_openai_function(), ToolDefinition (+1 more)

### Community 118 - "escapeHtml"
Cohesion: 0.31
Nodes (13): applyFilters(), copyCommand(), elements, executeSkill(), init(), initElements(), loadSkills(), openSkillsModal() (+5 more)

### Community 119 - "VerifyCsrfTests"
Cohesion: 0.14
Nodes (8): Tests for verify_csrf function (lines 68-88)., GET requests skip CSRF check (line 70-71)., CSRF skip paths bypass check (lines 72-73)., No CSRF cookie means no check needed (line 77-78)., Missing header raises 403 (lines 80-85)., Invalid token raises 403 (lines 87-88)., Valid token passes (line 88)., VerifyCsrfTests

### Community 120 - "AsyncFacadeTests"
Cohesion: 0.14
Nodes (8): AsyncFacadeTests, Tests for async facade functions., list_models delegates to providers.list_models., list_provider_status delegates to providers.list_provider_status., default_model_id delegates to providers.default_model_id., stream_completion delegates to providers.stream_completion., get_db_keys delegates to providers.get_db_keys., resolve_api_key delegates to providers.resolve_api_key.

### Community 121 - "RetrieveRelevantChunksCoverageTests"
Cohesion: 0.14
Nodes (7): Tests for retrieve_relevant_chunks (line 273)., Empty query returns empty list (line 255-256)., Empty document in results is skipped (line 272-273)., Exception during retrieval returns empty list (lines 286-288)., RetrieveRelevantChunksCoverageTests, Empty file_ids returns empty list., Missing metadata handled gracefully.

### Community 122 - "ConnectionCooldownManager"
Cohesion: 0.15
Nodes (7): ConnectionCooldownManager, Manages connection cooldown periods for providers, Set cooldown period for a provider, Check if provider is in cooldown, Get remaining cooldown time in seconds (0 if not in cooldown), Clear cooldown for a provider, Remove expired cooldown entries

### Community 123 - "ModelLockoutManager"
Cohesion: 0.15
Nodes (7): ModelLockoutManager, Manages model lockout periods (temporarily disable specific models), Lockout a specific model for a duration, Check if model is locked out, Get remaining lockout time in seconds (0 if not locked out), Clear lockout for a model, Remove expired lockout entries

### Community 124 - "ResetVectorIndexTests"
Cohesion: 0.15
Nodes (8): close_client(), Close the chromadb client and clear singletons. Primarily used in test teardown…, Tests for reset_vector_index and close_client., reset_vector_index deletes and recreates collection., ValueError (older chromadb) is caught., NotFoundError (chromadb 1.5+) is caught., close_client resets both _client and _collection., ResetVectorIndexTests

### Community 125 - "SkillRegistry"
Cohesion: 0.21
Nodes (4): Any, Path, SkillRegistry, SkillRegistryTests

### Community 126 - "asyncio"
Cohesion: 0.21
Nodes (8): asyncio, Test adaptive policy selection and application., Test automatic policy selection for simple queries., Test automatic policy selection for complex reasoning., Test policy adapts after timeout., Test policy adapts after repeated errors., Test policy respects user tier limits., TestAdaptivePolicyFlow

### Community 127 - "TestAnthropicProvider"
Cohesion: 0.15
Nodes (8): fixture, Create OpenAI provider with mocked client., Test Anthropic provider implementation., Create Anthropic provider with mocked client., Test streaming maps policy to Anthropic API parameters., Test completion with thinking enabled., Test Anthropic provider reports supported models., TestAnthropicProvider

### Community 128 - "ToolRegistry"
Cohesion: 0.15
Nodes (4): Central registry for tool definitions., Check if a tool is enabled., List all registered tool names., ToolRegistry

### Community 129 - "_snippet_after"
Cohesion: 0.21
Nodes (8): _snippet_after(), Tests for _snippet_after function., Extracts snippet after href., Returns empty string when href not found., Tries multiple regex patterns for snippet., HTML entities in snippet are unescaped., HTML tags in snippet are stripped., SnippetAfterTests

### Community 130 - "createResponseController"
Cohesion: 0.33
Nodes (11): createResponseController(), emit(), flush(), handleCanonical(), handleLegacy(), scheduleReasoningFlush(), scheduleTextFlush(), scheduleToolInputFlush() (+3 more)

### Community 131 - "test_rag_new.py"
Cohesion: 0.15
Nodes (6): ConstantsTests, ConstantsTests, Comprehensive tests for rag.py — RAG chunking, indexing, and retrieval. Tests…, Tests for module constants., Constants are positive values., CHROMA_DB_DIR is a Path.

### Community 132 - "fixture"
Cohesion: 0.15
Nodes (13): coding_history(), concise_history(), detailed_history(), empty_history(), followup_history(), fixture, Empty conversation history., Short conversation history (3 messages). (+5 more)

### Community 133 - "CircuitBreaker"
Cohesion: 0.26
Nodes (7): CircuitBreaker, Execute function with circuit breaker protection, Check if enough time has passed to attempt reset, Handle successful request, Handle failed request, Set circuit breaker state, Circuit breaker implementation for provider resilience

### Community 134 - "ProviderMetrics"
Cohesion: 0.17
Nodes (7): ProviderMetrics, Metrics tracked for each provider, Calculate failure rate as percentage, Calculate success rate as percentage, Check if provider is currently available (not in cooldown/lockout), Check if provider is in cooldown period, Check if provider is locked out

### Community 135 - "build_conversation_profile"
Cohesion: 0.17
Nodes (12): build_conversation_profile(), Build ConversationProfile from recent message history. Analyzes the last N…, Test 14: Coding intent + code history → mode=CODING, has_code_context=True., Profile detects code fences in history., Profile detects user prefers concise responses., Profile detects user prefers detailed responses., Profile extracts recurring topics., test_coding_mode_with_history() (+4 more)

### Community 136 - "LLMProvider"
Cohesion: 0.17
Nodes (7): LLMProvider, Protocol for LLM providers., Non-streaming completion., Streaming completion., Check provider availability., Models this provider supports., Protocol

### Community 137 - "TestErrorResponses"
Cohesion: 0.17
Nodes (7): Test error response formats., Test validation error response format., Test authentication error response format., Test rate limit error response format., Test provider error response format., Test internal server error response format., TestErrorResponses

### Community 138 - "TestMetricsIntegration"
Cohesion: 0.17
Nodes (7): Test metrics collection during request processing., Test latency is recorded for each request., Test token usage is recorded., Test error rate is tracked., Test which policy was selected is recorded., Test fallback provider usage is tracked., TestMetricsIntegration

### Community 139 - "TestE2ESecurity"
Cohesion: 0.17
Nodes (7): End-to-end security tests., Test malicious input is sanitized., Test all endpoints require authentication., Test users can only access their own conversations., Test rate limits are enforced per user., Test user data is isolated., TestE2ESecurity

### Community 140 - "TestProviderFactory"
Cohesion: 0.17
Nodes (7): Test provider factory for creating providers., Test creating OpenAI provider from config., Test creating Anthropic provider from config., Test creating provider from environment variables., Test creating provider with custom configuration., Test creating unknown provider raises error., TestProviderFactory

### Community 141 - "TestPolicyManager"
Cohesion: 0.17
Nodes (7): Test centralized policy management., Test getting default policy., Test getting named policy preset., Test registering custom policy., Test listing all available policies., Test policy parameter validation., TestPolicyManager

### Community 142 - "TestChatResponse"
Cohesion: 0.17
Nodes (7): Test ChatResponse immutable data structure., Test creating a chat response., Test response with tool calls., Test response with reasoning content., Test all valid finish reasons., Test that ChatResponse is immutable., TestChatResponse

### Community 143 - "tools/__init__.py"
Cohesion: 0.26
Nodes (9): Register all built-in tools with the global registry., register_builtin_tools(), Exception, Tool executor for running tool calls., ToolExecutionError, ToolTimeoutError, ToolValidationError, Tools package - Tool execution infrastructure. (+1 more)

### Community 144 - "ToolResult"
Cohesion: 0.24
Nodes (5): ToolExecutor, BaseModel, Canonical tool result returned to the model., Return True if the tool execution was successful., ToolResult

### Community 145 - "_normalize_url"
Cohesion: 0.21
Nodes (7): _normalize_url(), Empty string returns empty string., NormalizeUrlTests, Tests for _normalize_url function., Absolute URLs passed through., Protocol-relative URLs get https: prefix., Relative URLs get duckduckgo base.

### Community 146 - "_strip_tags"
Cohesion: 0.23
Nodes (7): _strip_tags(), Tests for _strip_tags function., Nested tags stripped., Self-closing tags removed., Text without tags unchanged., Malformed tags handled gracefully., StripTagsTests

### Community 147 - "RetrievalTests"
Cohesion: 0.17
Nodes (6): skipIf, Integration tests for index_document + retrieve_relevant_chunks., Index simple text and retrieve a relevant chunk., An empty query returns an empty list., Empty file_ids list returns an empty list., RetrievalTests

### Community 148 - "PromptInjectionValidationTests"
Cohesion: 0.17
Nodes (7): PromptInjectionValidationTests, Tests for validate_messages function in api.py (uses prompt_injection)., Injection in user message adds warning metadata., Empty or non-string content is skipped., Injection in one message doesn't affect others., Assistant messages are also validated., Non-string content (like lists) handled gracefully.

### Community 149 - "ListModelsCoverageTests"
Cohesion: 0.17
Nodes (7): ListModelsCoverageTests, fetch_models_from_provider exception is caught and returns empty list (lines…, asyncio.gather with return_exceptions=True handles exceptions (line 264)., Tests for list_models function covering error paths., When resolve_api_key returns None, provider is skipped (line 247)., Exception in fetch_ollama_models is caught and ignored (lines 239-241)., When registry.get_config returns None, provider is skipped (line 250).

### Community 150 - "test_websearch_new.py"
Cohesion: 0.17
Nodes (8): DuckDuckGoSearchTests, Comprehensive tests for websearch.py — web search functionality. Tests cover: -…, Tests for SearchResult dataclass., SearchResult creates with all fields., to_context returns formatted string., Tests for _search_duckduckgo function (mocked HTTP)., to_context handles special characters., SearchResultTests

### Community 151 - "RequestIDMiddleware"
Cohesion: 0.22
Nodes (8): Middleware package for FastAPI application., get_request_id(), BaseHTTPMiddleware, Request, Request ID Middleware - Generates/extracts and propagates request IDs for…, Extract or generate a unique request ID and propagate it through the…, Get the request ID from request state (set by RequestIDMiddleware)., RequestIDMiddleware

### Community 152 - "resilience/__init__.py"
Cohesion: 0.24
Nodes (10): CircuitState, _classify_failure(), FailureType, Enum, Exception, Circuit breaker states, Types of failures that can trigger resilience mechanisms, Reset the global resilience manager (mainly for testing) (+2 more)

### Community 153 - "asyncio"
Cohesion: 0.18
Nodes (6): asyncio, Test streaming completion respects policy., Test that stream=False policy uses complete instead., Test fallback provider is used when primary fails., Test adaptive_timeout is enforced., Test non-streaming completion respects policy.

### Community 154 - "TestToolUseFlow"
Cohesion: 0.18
Nodes (6): Test tool/function calling flow., Test tool call execution and result return., Test multiple parallel tool calls., Test tool call error handling., Test streaming tool call argument deltas., TestToolUseFlow

### Community 155 - "start.py"
Cohesion: 0.31
Nodes (10): build_commands(), ensure_env_file(), ensure_virtualenv(), free_port(), get_python_executable(), install_requirements(), main(), _print_error() (+2 more)

### Community 156 - "TruncationResult"
Cohesion: 0.24
Nodes (7): Result of context truncation operation., Context utilization as percentage of available budget., TruncationResult, Tests for TruncationResult dataclass., Utilization percentage calculation., Zero budget should return 100%., TestTruncationResult

### Community 157 - "analyze_request"
Cohesion: 0.22
Nodes (10): analyze_request(), _apply_constraints(), any, Main entry point: analyze request and return complete guidance. This is the…, Apply structured constraints based on guidance signals., asyncio, analyze_request returns fully populated ResponseGuidance., analyze_request uses conversation history for profile. (+2 more)

### Community 158 - "TestProviderManagementEndpoints"
Cohesion: 0.20
Nodes (6): Test provider management API endpoints., Test GET /api/v1/providers endpoint., Test GET /api/v1/providers/{name} endpoint., Test GET /api/v1/providers/{name}/health endpoint., Test GET /api/v1/providers/{name}/models endpoint., TestProviderManagementEndpoints

### Community 159 - "TestAPIPerformance"
Cohesion: 0.20
Nodes (6): Test API performance characteristics., Test completion endpoint latency., Test time to first chunk in streaming., Test handling concurrent requests., Test handling large conversation contexts., TestAPIPerformance

### Community 160 - "TestMultiProviderIntegration"
Cohesion: 0.20
Nodes (6): Test integration with multiple providers., Test automatic provider selection based on model., Test health check is performed before routing request., Test load balancing across multiple providers., Test policy adapted for provider-specific capabilities., TestMultiProviderIntegration

### Community 161 - "TestCoreChatFlow"
Cohesion: 0.20
Nodes (6): Test chat with system prompt., Test chat with custom policy parameters., Test end-to-end chat completion flow., Test simple chat completion from request to response., Test multi-turn conversation maintains context., TestCoreChatFlow

### Community 162 - "TestStreamingFlow"
Cohesion: 0.20
Nodes (6): Test end-to-end streaming flow., Test streaming chat completion., Test streaming with tool call deltas., Test streaming with reasoning content., Test cancelling a stream mid-generation., TestStreamingFlow

### Community 163 - "TestProviderFailoverFlow"
Cohesion: 0.20
Nodes (6): Test provider failover and fallback behavior., Test fallback provider used when primary fails., Test error returned when all providers fail., Test unhealthy providers are skipped., Test correct provider selected for model., TestProviderFailoverFlow

### Community 164 - "TestConversationManagementFlow"
Cohesion: 0.20
Nodes (6): Test conversation/session management., Test conversation history persists across requests., Test conversation truncation at context window limit., Test conversation branching (forking)., Test automatic conversation summarization., TestConversationManagementFlow

### Community 165 - "TestE2EPerformance"
Cohesion: 0.20
Nodes (6): End-to-end performance tests., Test P95 latency under concurrent load., Test requests per second throughput., Test memory usage remains stable under load., Test streaming doesn't buffer entire response., TestE2EPerformance

### Community 166 - "TestE2EReliability"
Cohesion: 0.20
Nodes (6): End-to-end reliability tests., Test system degrades gracefully under partial failures., Test circuit breaker opens after repeated failures., Test retry with exponential backoff., Test idempotent request handling., TestE2EReliability

### Community 167 - "ChatHistoryTests"
Cohesion: 0.20
Nodes (5): ChatHistoryTests, Tests for chat history endpoints., GET /chats endpoint function exists., GET /chats/{chat_id} endpoint function exists., DELETE /chats/{chat_id} endpoint function exists.

### Community 168 - "FileUploadTests"
Cohesion: 0.20
Nodes (5): FileUploadTests, Tests for file upload endpoint logic., ALLOWED_MIME_TYPES contains expected mappings., MAGIC_AVAILABLE reflects import status., Upload rejects unsupported extensions.

### Community 169 - "PasswordSecurityTests"
Cohesion: 0.20
Nodes (6): PasswordSecurityTests, Tests for password hashing security., Password hash should use scrypt (not md5, sha1, etc)., Password comparison should use constant-time comparison., Token hash should use SHA-256., CSRF token should be URL-safe.

### Community 170 - "FrontendResponseControllerTests"
Cohesion: 0.31
Nodes (3): FrontendResponseControllerTests, Verify text_end triggers automatic flush of buffered content., Verify that multiple rapid text_delta events are coalesced into a single flush.

### Community 171 - "GetAttrTests"
Cohesion: 0.20
Nodes (6): GetAttrTests, Tests for __getattr__ lazy loading., _providers_static triggers lazy load., _ollama_start_attempted triggers lazy load., _ollama_process triggers lazy load., Unknown attribute raises AttributeError.

### Community 172 - "LinkedProvidersTests"
Cohesion: 0.20
Nodes (6): LinkedProvidersTests, Tests for _linked_providers function., Empty keys returns providers with env keys., Keys with matching provider IDs are linked., Providers with env_key set are linked even without DB key., Local providers (ollama) are always excluded.

### Community 173 - "DeleteDocumentChunksTests"
Cohesion: 0.22
Nodes (5): DeleteDocumentChunksTests, Exception returns False (lines 301-303)., DeleteDocumentChunksTests, Tests for delete_document_chunks function., Successful deletion returns True.

### Community 174 - "IntegrationTests"
Cohesion: 0.20
Nodes (5): IntegrationTests, Integration tests using real ChromaDB with temp directory., Create temp directory for ChromaDB., Cleanup temp directory., Test chunk_text directly with various inputs.

### Community 175 - "response_intelligence/config.py"
Cohesion: 0.22
Nodes (8): get_trigger_patterns(), BaseModel, Configuration for Response Intelligence Layer. Feature flags, trigger keywords,…, Configuration for the response intelligence analyzer., Return all trigger keyword lists as a flat dict for easy iteration., ResponseIntelligenceConfig, get_trigger_patterns returns all categories., test_config_trigger_patterns()

### Community 176 - "TestAPIModels"
Cohesion: 0.22
Nodes (5): Test API request/response models., Test ChatCompletionRequest model validation., Test ChatCompletionResponse model., Test StreamChunk response model., TestAPIModels

### Community 177 - "CSRFProtectionTests"
Cohesion: 0.22
Nodes (4): CSRFProtectionTests, Tests for CSRF protection., GET requests should not require CSRF token., POST/PUT/DELETE should require CSRF when cookie present.

### Community 178 - "ImageOCRExtractionTests"
Cohesion: 0.22
Nodes (5): ImageOCRExtractionTests, Tests for image OCR extraction., When tesseract binary is missing, extract_text handles it gracefully., When tesseract binary is missing, returns error message., Test image size limit check.

### Community 179 - "FakeResponse"
Cohesion: 0.22
Nodes (4): FakeResponse, When the API returns a ``next`` field, the function follows it and consumes…, A ``next`` URL that points back to a visited page must not loop., Simulates ``httpx.Response`` for our mocked ``AsyncClient.get()``.

### Community 180 - "create_context_manager"
Cohesion: 0.29
Nodes (6): create_context_manager(), Factory function to create ContextManager. Allows for potential future…, Tests for factory function., Factory should return ContextManager instance., Factory should pass custom parameters., TestCreateContextManager

### Community 182 - "prompt_injector.py"
Cohesion: 0.25
Nodes (7): _add_mode_instructions(), _add_tone_instruction(), format_guidance_for_debug(), Prompt injection for Response Intelligence. Translates structured…, Add tone-specific instruction., Format guidance for logging/debugging., Add mode-specific base instructions.

### Community 183 - "async_client"
Cohesion: 0.25
Nodes (8): app(), async_client(), client(), mock_llm_client(), fixture, Mock LLM client for API tests., Create FastAPI app with mocked dependencies., Create async test client.

### Community 184 - "TestMetricsEndpoints"
Cohesion: 0.25
Nodes (5): Test metrics and monitoring endpoints., Test GET /metrics endpoint., Test GET /health endpoint., Test GET /ready endpoint., TestMetricsEndpoints

### Community 185 - "TestCORSAndSecurity"
Cohesion: 0.25
Nodes (5): Test CORS and security headers., Test CORS headers are present., Test security headers are present., Test rate limiting headers are present., TestCORSAndSecurity

### Community 186 - "TestBaseProvider"
Cohesion: 0.25
Nodes (5): Test the abstract base provider class., Test that base provider cannot be instantiated directly., Test base provider defines required abstract methods., Test base provider implements shared functionality., TestBaseProvider

### Community 187 - "TestPolicyPerformance"
Cohesion: 0.25
Nodes (5): Test policy system performance characteristics., Test policy creation is fast., Test policy selection is fast under load., Test thread-safe concurrent policy access., TestPolicyPerformance

### Community 188 - "tools/schemas.py"
Cohesion: 0.36
Nodes (6): Any, Tool schema definitions and validation., Return a dict suitable for sending to the LLM as a tool result message., tool_definition_to_anthropic_tool(), _validate_json_schema(), validate_tool_arguments()

### Community 190 - "ModelEndpointTests"
Cohesion: 0.25
Nodes (4): ModelEndpointTests, Tests for model/provider listing endpoints., GET /models delegates to llm.list_models., GET /providers delegates to llm.list_provider_status.

### Community 191 - "OCRUnavailableTests"
Cohesion: 0.25
Nodes (5): OCRUnavailableTests, Tests for when OCR is not available (lines 20-21, 106, 197)., _extract_pdf_ocr returns empty string when OCR not available (line 106)., _extract_image_ocr returns message when OCR not available (line 197)., File size check runs even when OCR unavailable (lines 200-203).

### Community 192 - "PDFOCRBranchTests"
Cohesion: 0.25
Nodes (5): PDFOCRBranchTests, Tests for PDF OCR fallback branches (lines 93-94, 133-134)., PDF extraction attempts OCR on corrupt PDF (lines 90-96)., PDF extraction returns error when OCR also fails (lines 90-96)., _extract_pdf_ocr continues on per-page exception (lines 133-134).

### Community 193 - "PlainTextEdgeCaseTests"
Cohesion: 0.25
Nodes (5): PlainTextEdgeCaseTests, Tests for plain text extraction edge cases., Unknown extension returns empty string (line 64)., Extension matching is case insensitive., Non-existent file returns error message via extract_text wrapper.

### Community 194 - "PDFExtractionTests"
Cohesion: 0.25
Nodes (4): PDFExtractionTests, Tests for PDF extraction (including OCR fallback)., Test OCR fallback when extracted text is too short., Test PDF extraction doesn't try OCR when unavailable.

### Community 195 - "PDLExtractionTests"
Cohesion: 0.25
Nodes (5): PDLExtractionTests, Tests for PDF text extraction., Missing PDF returns error message., Using .pdf extension on non-PDF returns error., Unknown extension returns empty string.

### Community 196 - "PPTXExtractionTests"
Cohesion: 0.25
Nodes (4): PPTXExtractionTests, Tests for PPTX extraction., Test PPTX with multiple slides and shapes., Test PPTX with shapes that don't have text frames.

### Community 197 - "test_model_fetch.py"
Cohesion: 0.25
Nodes (5): ModelDiscoveryLoggingTests, Tests for ``fetch_models_from_provider()`` — the public, standalone function…, Silent failures in model discovery must now be logged. The graceful-degradation…, A connection error is logged with provider context and returns []., Ollama unreachable after retries logs a warning and returns [].

### Community 198 - "StreamCompletionCoverageTests"
Cohesion: 0.25
Nodes (5): Tests for stream_completion covering fallback paths (lines 363-364, 372)., Mock async generator for LLM stream., Falls back to LiteLLM when provider class not found (lines 363-364)., Uses custom provider class when available (lines 370-374)., StreamCompletionCoverageTests

### Community 199 - "GetCollectionTests"
Cohesion: 0.25
Nodes (5): GetCollectionTests, Tests for _get_collection function (lines 86-92)., _get_collection returns existing collection., ValueError when getting collection triggers create_collection (lines 87-88)., NotFoundError when getting collection triggers create_collection (lines 89-91).

### Community 200 - "RagFailureLoggingTests"
Cohesion: 0.25
Nodes (5): RagFailureLoggingTests, Failure paths must log a traceback via ``logger.exception``. The graceful-…, index_document failure logs exception with file context, returns -1., retrieve failure logs exception with query context, returns []., delete failure logs exception with file context, returns False.

### Community 202 - "ProviderKeyDeletionTests"
Cohesion: 0.29
Nodes (4): ProviderKeyDeletionTests, Tests for provider key deletion., Deleting unknown provider returns 404., Deleting linked key removes from DB.

### Community 203 - "DOCXBranchTests"
Cohesion: 0.33
Nodes (4): DOCXBranchTests, Tests for DOCX extraction branches., Empty paragraphs are skipped (line 142)., Table extraction (lines 144-148).

### Community 204 - "PPTXEdgeCaseTests"
Cohesion: 0.33
Nodes (4): PPTXEdgeCaseTests, Tests for PPTX edge cases., General exception returns error message (lines 190-191)., Shapes without text_frame are skipped.

### Community 205 - "StreamCompletionErrorHandlingTests"
Cohesion: 0.33
Nodes (4): Tests for stream_completion error handling., Exceptions from provider are propagated., All parameters are passed to underlying function., StreamCompletionErrorHandlingTests

### Community 206 - "TestBaseProvider"
Cohesion: 0.33
Nodes (4): Tests for BaseProvider abstract class., BaseProvider should not be instantiable directly., Subclasses must implement abstract methods., TestBaseProvider

### Community 208 - "LiteLLMProvider"
Cohesion: 0.40
Nodes (3): LiteLLMProvider, Any, Generic provider using LiteLLM for any supported model.

### Community 209 - "HealthEndpointTests"
Cohesion: 0.50
Nodes (3): HealthEndpointTests, Tests for health endpoints., Health endpoint returns expected structure.

### Community 210 - "TestProviderInit"
Cohesion: 0.50
Nodes (3): Tests for providers __init__ module., All provider modules should import without error., TestProviderInit

### Community 215 - "e2e_client"
Cohesion: 0.67
Nodes (3): e2e_client(), fixture, Create a full test client with real components (mocked external APIs).

## Knowledge Gaps
- **39 isolated node(s):** `ChatResponse`, `MockResilienceManager`, `elements`, `state`, `RESPONSE_EVENT_TYPES` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1913 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `parse_litellm_stream_chunk()` connect `base.py` to `ProviderStreamChunk`, `LLMProvider`, `providers/__init__.py`, `LiteLLMProvider`, `ResponseEventBuilder`?**
  _High betweenness centrality (0.191) - this node is a cross-community bridge._
- **Why does `LLMProvider` connect `LLMProvider` to `backend/tests/test_api.py`?**
  _High betweenness centrality (0.183) - this node is a cross-community bridge._
- **Why does `ModelInfo` connect `ModelInfo` to `test_context_manager.py`, `llm.py`, `ProviderStreamChunk`, `test_llm.py`, `ContextManager`, `providers/__init__.py`, `ContextBudget`, `context_manager.py`, `integration.py`, `LiteLLMProvider`, `base.py`, `create_context_manager`, `resilience_integration.py`, `AsyncFacadeTests`, `OllamaProvider`, `patch`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Are the 61 inferred relationships involving `extract_text()` (e.g. with `.test_dispatch_csv_extension()` and `.test_dispatch_docx_extension()`) actually correct?**
  _`extract_text()` has 61 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `test()` (e.g. with `.test_delete_chat_exists()` and `.test_delete_chat_not_found()`) actually correct?**
  _`test()` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `ModelInfo` (e.g. with `ContextManager` and `create_context_manager()`) actually correct?**
  _`ModelInfo` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 42 inferred relationships involving `QueryMode` (e.g. with `classify_query_mode()` and `_add_mode_instructions()`) actually correct?**
  _`QueryMode` has 42 INFERRED edges - model-reasoned connections that need verification._