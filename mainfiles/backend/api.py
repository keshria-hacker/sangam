"""
api.py — HTTP API surface (facade).

The actual route handlers live in ``backend/api_routes/``, split by resource:

- ``api_routes/common.py``             SSE framing + upload-content helpers
- ``api_routes/providers_routes.py``   provider keys, model refresh, websearch, health
- ``api_routes/files_routes.py``       document upload
- ``api_routes/chats_routes.py``       chat CRUD, preferences, summary, feedback
- ``api_routes/models_routes.py``      model catalogue
- ``api_routes/chat_stream_routes.py`` chat streaming pipeline + agentic reasoning

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
    agentic_reasoning_endpoint,
    chat_stream,
)
from .api_routes.chats_routes import (  # noqa: F401
    create_chat,
    delete_chat,
    get_chat,
    get_chat_summary,
    get_preferences,
    list_chats,
    submit_feedback,
    update_preferences,
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
