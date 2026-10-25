"""
api.py — HTTP API surface (facade).

The actual route handlers live in ``backend/api_routes/``, split by resource:

- ``api_routes/common.py``             SSE framing + upload-content helpers
- ``api_routes/providers_routes.py``   provider keys, model refresh, websearch, health
- ``api_routes/files_routes.py``       document upload
- ``api_routes/chats_routes.py``       chat CRUD, preferences, summary, feedback
- ``api_routes/models_routes.py``      model catalogue
- ``api_routes/chat_stream_routes.py`` chat streaming pipeline

This facade keeps the historical import surface stable: ``backend.main`` mounts
``router``/``public_router`` from here, and tests import or patch
``backend.api.<name>`` as before. Shared module objects (``llm``, ``websearch``,
``settings``, ``uuid``, ``extract_text``, ...) are re-exported so
``patch("backend.api.llm...")`` keeps working — the route modules import the
very same module objects, so a patch on either path affects both.
"""
import uuid  # noqa: F401 — tests patch backend.api.uuid.uuid4

from . import (
    llm,  # noqa: F401 — re-exported for backward-compatible patching
    websearch,  # noqa: F401
)
from .api_routes.chat_stream_routes import (  # noqa: F401
    SSE_HEARTBEAT_INTERVAL,
    chat_stream,
)
from .api_routes.settings_routes import (  # noqa: F401
    get_user_settings,
    put_user_settings,
)
from .api_routes.knowledge_routes import (  # noqa: F401
    get_knowledge_graph,
    search_knowledge,
)
from .api_routes.runs_routes import (  # noqa: F401
    get_run,
    list_runs,
    record_run,
)
from .api_routes.artifacts_routes import (  # noqa: F401
    create_artifact,
    delete_artifact,
    get_artifact,
    list_artifacts,
    list_versions,
    update_artifact,
)
from .api_routes.spec_routes import (  # noqa: F401
    build_spec_doc,
    spec_to_task,
)
from .api_routes.quality_routes import (  # noqa: F401
    get_adhd_style,
    lint_quality,
    preview_quality,
)
# Batch 7: fit routes register BEFORE models_routes so that
# GET /models/hardware is not shadowed by GET /models/{provider}.
from .api_routes import fit_routes  # noqa: F401
from .api_routes import diagrams_routes  # noqa: F401
from .api_routes.automations_routes import (  # noqa: F401
    create_automation,
    delete_automation,
    get_automation,
    list_automations,
    run_automation_now,
    update_automation,
)
from .api_routes.connectors_routes import (  # noqa: F401
    connector_authorize,
    connector_callback,
    disconnect_connector,
    list_connectors,
)
from .api_routes.media_jobs_routes import (  # noqa: F401
    create_media_job,
    get_media_job,
    list_media_jobs,
)
from .api_routes.system_routes import download_backup  # noqa: F401
from .api_routes.security_routes import (  # noqa: F401
    add_allowlist,
    add_finding,
    advance_phase,
    approve_run,
    build_report,
    create_run,
    delete_allowlist,
    get_catalog,
    get_run,
    list_audit,
    list_allowlist,
    list_findings,
    list_runs,
    run_browser,
    set_catalog_enabled,
    validate_finding,
)
from .api_routes.memory_v2_routes import (  # noqa: F401
    create_transcript,
    extract_entities,
    extract_memory_llm,
    get_entity_timeline,
    list_memory_entities,
    list_transcript_rows,
    reflect_memories,
    update_memory_endpoint,
)
from .api_routes.notebooks_routes import (  # noqa: F401
    add_notebook_source,
    create_notebook,
    create_notebook_note,
    delete_notebook,
    get_note_backlinks,
    get_notebook,
    get_notebook_note,
    list_notebook_notes,
    list_notebook_sources,
    list_notebook_transforms,
    list_notebooks,
    note_from_chat,
    retrieve_notebook,
    run_notebook_transform,
    set_source_context,
    update_notebook,
)
from .api_routes.workflows_routes import (  # noqa: F401
    create_workflow,
    delete_workflow,
    get_workflow,
    list_runs,
    list_workflows,
    replay_run,
    run_workflow,
    webhook_run,
)
from .api_routes.compare_routes import (  # noqa: F401
    arena_leaderboard,
    arena_vote,
    compare_models,
)
from .api_routes.chats_routes import (  # noqa: F401
    append_messages,
    create_chat,
    delete_chat,
    get_chat,
    get_chat_summary,
    list_chats,
    submit_feedback,
)

# Importing the route modules registers all endpoints on the shared routers.
from .api_routes.common import (  # noqa: F401
    ALLOWED_MIME_TYPES,
    MAGIC_AVAILABLE,
    _background_tasks,
    _get_magic,
    _magic,
    public_router,
    router,
    sse_event,
    sse_response_event,
)
from .api_routes.files_routes import upload_file  # noqa: F401
from .api_routes.features_routes import get_features  # noqa: F401
from .api_routes.extensions_routes import (  # noqa: F401
    disable_extension,
    enable_extension,
    list_extensions,
)
from .api_routes.media_routes import (  # noqa: F401
    get_media,
    load_media_attachment,
    upload_media,
)
from .api_routes.memory_routes import (  # noqa: F401
    create_memory,
    get_memory_stats,
    remove_memory,
    run_consolidation,
    search_memories,
)
from .api_routes.voice_routes import (  # noqa: F401
    get_voice_status,
    get_voices,
    speech_to_text,
    text_to_speech,
)
from .api_routes.image_routes import (  # noqa: F401
    describe_image_endpoint,
    generate_image_endpoint,
    get_image_status,
    image_prompt_endpoint,
    inpaint_image_endpoint,
    outpaint_image_endpoint,
    upscale_image_endpoint,
    vary_image_endpoint,
)
from .api_routes.teams_routes import (  # noqa: F401
    get_teams,
    run_team_endpoint,
)
from .api_routes.learn_routes import (  # noqa: F401
    answer_feedback,
    create_lesson,
)
from .api_routes.analytics_routes import (  # noqa: F401
    analytics_stats,
)
from .api_routes.models_routes import (  # noqa: F401
    _to_model_info,
    get_models,
    get_provider_models,
)
from .api_routes.providers_routes import (  # noqa: F401
    clear_inaccessible_models,
    delete_provider_key,
    get_providers,
    get_websearch,
    health,
    list_provider_keys,
    refresh_provider_models,
    set_provider_key,
)
from .api_routes.omniroute_routes import (  # noqa: F401
    omniroute_config,
    omniroute_status,
    omniroute_sync,
)
from .api_routes.agents_routes import (  # noqa: F401
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    run_custom_agent,
    update_agent,
)
from .api_routes.code_agent_routes import (  # noqa: F401
    chat_agent_run,
    code_agent_run,
)
# Batch 5: importing these modules registers their routes (engineering on
# the shared router; skills v2 on the skills router) and pipeline tables.
from .api_routes import engineering_routes  # noqa: F401
from .api_routes import skills_v2_routes  # noqa: F401
# Batch 6: importing this module registers the LAN device routes on the
# shared router (host) and the claim route on the public router, plus the
# paired_devices table on Base.metadata.
from .api_routes import devices_routes  # noqa: F401
# Deep-read Wave-2: importing these modules registers their routes on
# the shared router (code-graph, goals, and the deep-routes wrappers
# for council/debate/hive/hooks/worktrees/skills-creator/personas/lessons).
from .api_routes import code_graph_routes  # noqa: F401
from .api_routes import deep_routes  # noqa: F401
from .api_routes import goals_routes  # noqa: F401
# Batch 9 (memory/research): importing this module registers the
# observation / research-job tables and all batch routes on the
# shared router.
from .api_routes import memory_research_routes  # noqa: F401
# Batch 10 (agent runtime + skills): importing this module registers
# the runtime endpoints (plan/contract/compact/steering/tray/sandbox/
# flow/hive/drivers/eval) on the shared router.
from .api_routes import agent_runtime_routes  # noqa: F401
# Doctor lives in its own module with its own router; include it on the
# shared router so it is served (and authenticated) like /system/*.
from .doctor import router as _doctor_router

router.include_router(_doctor_router)
from .api_routes.routing_routes import evaluate_routing  # noqa: F401
from .config import settings  # noqa: F401
from .database import AsyncSessionLocal, get_db  # noqa: F401
from .document import extract_text, truncate_preview  # noqa: F401
from .models import Chat, Message, ProviderKey, UploadedFile, UserPreference  # noqa: F401
from .rag import index_document, retrieve_relevant_chunks  # noqa: F401
from .schemas import (  # noqa: F401
    ChatDetailOut,
    ChatOut,
    ChatStreamRequest,
    FeedbackIn,
    FileUploadOut,
    ModelInfo,
    ProviderKeyIn,
    ProviderKeyOut,
    ProviderModelEntry,
    ProviderStatus,
    RefreshModelsOut,
    UserPreferenceIn,
    UserPreferenceOut,
)
