"""CivitAI API Client — talks to CivitAI and returns clean Python data.

This module is the ONLY place that knows how to communicate with CivitAI.
It handles HTTP calls, pagination, URL construction, and data normalization.

It does NOT know about our database, media store, model store, or gallery.
It takes an API key in the constructor and returns dicts/lists.

CivitAI has two sets of endpoints:
  1. REST API (public, documented): /api/v1/models, /api/v1/images, etc.
  2. tRPC (internal, undocumented): /api/trpc/image.getInfinite, etc.
     Discovered via Playwright network interception. More reliable for
     pagination and has more fields than REST.

Authentication:
  - REST: Authorization: Bearer {api_key}
  - tRPC: same header
  - Downloads: ?token={api_key} query param
  - CDN image URLs: no auth needed (even for NSFW)
"""

import json
import re
from typing import Any

from v2.app.http_client import http


# ── CDN URL helpers ──────────────────────────────────────────────────────────
#
# CivitAI hosts media on a CDN. The URL format is:
#   https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{cdn_id}/original=true/{cdn_id}.{ext}
#
# The cdn_id is a UUID (e.g. d1de8c5d-dea8-41f3-a11d-2f59fcf4029b) that
# identifies the file on the CDN. This is NOT the same as the numeric image
# ID that CivitAI uses in its database.
#
# Card images from the models API have id=null but have the full CDN URL.
# tRPC responses have only the cdn_id in the 'url' field, not the full URL.
# The numeric ID is needed to call getGenerationData.

_CDN_BASE = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/"
_CDN_ID_PATTERN = re.compile(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')


def extract_cdn_id_from_url(url: str) -> str:
    """Extract the CDN file UUID from a CivitAI image/video URL.

    CivitAI CDN URLs contain a UUID that identifies the file:
      https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/{uuid}.jpeg

    This UUID is the only identifier available for card images (which have
    id=null in the API response). For community images it's also used as
    a dedup key since it's consistent across REST and tRPC responses.

    Args:
        url: Full CDN URL or partial URL containing a UUID.

    Returns:
        The UUID string, or empty string if not found.
    """
    m = _CDN_ID_PATTERN.search(url)
    return m.group(1) if m else ""


def build_cdn_url(cdn_id: str, media_type: str = "image") -> str:
    """Build a full CDN URL from a cdn_id (UUID).

    tRPC responses return only the cdn_id in the 'url' field. This function
    builds the complete URL that can be used to download the file.

    Args:
        cdn_id: The UUID from the tRPC response 'url' field.
        media_type: 'image' or 'video' — determines the file extension.

    Returns:
        Full CDN URL ready for download.
    """
    ext = ".mp4" if media_type == "video" else ".jpeg"
    return f"{_CDN_BASE}{cdn_id}/original=true/{cdn_id}{ext}"


def build_image_page_url(image_id: int, api_key: str | None = None) -> str:
    """Build the CivitAI web page URL for an image.

    Args:
        image_id: Numeric image ID from the CivitAI database.
        api_key: If provided, appended as ?token= for NSFW access without login.

    Returns:
        URL like https://civitai.com/images/12345 or with ?token=...
    """
    url = f"https://civitai.com/images/{image_id}"
    if api_key:
        url += f"?token={api_key}"
    return url


def build_download_url(version_id: int, api_key: str | None = None) -> str:
    """Build a model file download URL for a CivitAI version.

    Args:
        version_id: CivitAI model version ID.
        api_key: If provided, appended as ?token= for authentication.

    Returns:
        URL like https://civitai.com/api/download/models/12345
    """
    url = f"https://civitai.com/api/download/models/{version_id}"
    if api_key:
        url += f"?token={api_key}"
    return url


# ── Client class ─────────────────────────────────────────────────────────────

class CivitaiClient:
    """Client for the CivitAI API.

    Handles both REST (public, documented) and tRPC (internal, undocumented)
    endpoints. All methods return plain Python dicts/lists — no DB, no store.

    Usage:
        client = CivitaiClient(api_key="your-key")
        model = client.get_model(12345)
        images = client.get_images_trpc(version_id=67890)
    """

    # Base URLs
    _REST_BASE = "https://civitai.com/api/v1"
    _TRPC_BASE = "https://civitai.com/api/trpc"

    def __init__(self, api_key: str = ""):
        """Initialize the client.

        Args:
            api_key: CivitAI API key. Without it, some endpoints return
                     limited data (no meta field, lower rate limits).
        """
        self._api_key = api_key
        self._headers = {}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    # ─────────────────────────────────────────────────────────────────────
    #  INTERNAL: HTTP helpers (delegate to http_client.http)
    # ─────────────────────────────────────────────────────────────────────

    def _get(self, url: str, params: dict | None = None,
             timeout: int | None = None, caller: str = "") -> dict:
        """GET request returning parsed JSON.

        Delegates to the centralised http_client. Auth headers are injected
        from the constructor. Retry, logging, and rate limiting are handled
        by http_client.

        Args:
            url: Full URL to request.
            params: Query parameters dict.
            timeout: Override default timeout (seconds).
            caller: Identifier for logging (auto-set by calling methods).

        Returns:
            Parsed JSON response as dict.
        """
        return http.get_json(
            url, params=params, headers=self._headers,
            timeout=timeout, caller=caller,
        )

    def _trpc_get(self, procedure: str, input_data: dict,
                  timeout: int | None = None, caller: str = "") -> dict:
        """Make a tRPC GET request.

        CivitAI's tRPC endpoints expect the input as a JSON-encoded query
        parameter called 'input'. The response is wrapped in:
            result.data.json

        This method handles the encoding and unwrapping.

        Args:
            procedure: tRPC procedure name (e.g. "image.getInfinite").
            input_data: The 'json' part of the tRPC input. This method
                        wraps it in the required {json: ..., meta: ...} envelope.
            timeout: Override default timeout.
            caller: Identifier for logging.

        Returns:
            The unwrapped response (result.data.json).
        """
        # tRPC envelope: the 'meta' section handles null/undefined cursor
        envelope = {
            "json": input_data,
            "meta": {"values": {"cursor": ["undefined"]}},
        }
        url = f"{self._TRPC_BASE}/{procedure}"
        raw = self._get(
            url, params={"input": json.dumps(envelope)},
            timeout=timeout, caller=caller or f"trpc.{procedure}",
        )
        return raw.get("result", {}).get("data", {}).get("json", {})

    # ─────────────────────────────────────────────────────────────────────
    #  REST API — public, documented by CivitAI
    #  https://github.com/civitai/civitai/wiki/REST-API-Reference
    # ─────────────────────────────────────────────────────────────────────

    def get_model(self, model_id: int) -> dict:
        """Fetch a model with all its versions, files, and card images.

        This is the main entry point for getting everything about a model.
        Returns the parent model data with modelVersions[] array, each
        containing files[] and images[] (card images).

        Note: card images have id=null. Use extract_cdn_id_from_url() on
        the image URL to get a usable identifier.

        REST endpoint: GET /api/v1/models/{id}

        Args:
            model_id: CivitAI model ID (the parent, not a version).

        Returns:
            Full model dict with modelVersions[].
        """
        return self._get(f"{self._REST_BASE}/models/{model_id}",
                         caller="civitai.get_model")

    def get_model_version(self, version_id: int) -> dict:
        """Fetch a single model version with its files and card images.

        REST endpoint: GET /api/v1/model-versions/{id}

        Args:
            version_id: CivitAI version ID.

        Returns:
            Version dict with files[], images[], trainedWords[], etc.
        """
        return self._get(f"{self._REST_BASE}/model-versions/{version_id}",
                         caller="civitai.get_model_version")

    def get_model_version_by_hash(self, file_hash: str) -> dict:
        """Find a model version by file hash.

        Useful for identifying a local file against CivitAI's database.
        Supports AutoV1, AutoV2, SHA256, CRC32, BLAKE3, AutoV3 hashes.

        REST endpoint: GET /api/v1/model-versions/by-hash/{hash}

        Args:
            file_hash: Any supported hash string.

        Returns:
            Version dict, same as get_model_version().
        """
        return self._get(f"{self._REST_BASE}/model-versions/by-hash/{file_hash}",
                         caller="civitai.get_model_version_by_hash")

    def search_models(
        self,
        query: str | None = None,
        types: list[str] | None = None,
        tag: str | None = None,
        username: str | None = None,
        sort: str | None = None,
        period: str | None = None,
        base_models: list[str] | None = None,
        nsfw: bool | None = None,
        limit: int = 100,
        page: int = 1,
    ) -> dict:
        """Search models with filters.

        REST endpoint: GET /api/v1/models

        Args:
            query: Search by model name.
            types: Filter by type(s): Checkpoint, LORA, TextualInversion,
                   Controlnet, VAE, Upscaler, MotionModule, LoCon, DoRA, etc.
            tag: Filter by tag name.
            username: Filter by creator username.
            sort: 'Highest Rated', 'Most Downloaded', 'Newest'.
            period: 'AllTime', 'Year', 'Month', 'Week', 'Day'.
            base_models: Filter by base model(s): 'SD 1.5', 'SDXL 1.0', etc.
            nsfw: Include NSFW models.
            limit: Results per page (1-100, default 100).
            page: Page number.

        Returns:
            Dict with 'items' (model list) and 'metadata' (pagination).
        """
        params = {"limit": limit, "page": page}
        if query:
            params["query"] = query
        if types:
            params["types"] = ",".join(types)
        if tag:
            params["tag"] = tag
        if username:
            params["username"] = username
        if sort:
            params["sort"] = sort
        if period:
            params["period"] = period
        if base_models:
            params["baseModels"] = ",".join(base_models)
        if nsfw is not None:
            params["nsfw"] = str(nsfw).lower()
        return self._get(f"{self._REST_BASE}/models", params=params,
                         caller="civitai.search_models")

    def get_images_rest(
        self,
        model_id: int | None = None,
        version_id: int | None = None,
        username: str | None = None,
        nsfw: str | None = None,
        sort: str | None = None,
        period: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        """Fetch community images via REST API.

        Less reliable than tRPC for pagination (sometimes returns fewer
        items than expected, or no cursor when more exist). Use
        get_images_trpc() when possible.

        REST endpoint: GET /api/v1/images

        Args:
            model_id: Filter by model (parent).
            version_id: Filter by version (modelVersionId param).
            username: Filter by uploader.
            nsfw: NSFW level filter: 'None', 'Soft', 'Mature', 'X', or omit for all.
            sort: 'Newest', 'Most Reactions', 'Most Comments'.
            period: 'AllTime', 'Year', 'Month', 'Week', 'Day'.
            limit: Max results per page (max 200).
            cursor: Pagination cursor from previous response.

        Returns:
            Dict with 'items' (image list) and 'metadata' (with nextCursor).
        """
        params: dict[str, Any] = {"limit": limit}
        if model_id:
            params["modelId"] = model_id
        if version_id:
            params["modelVersionId"] = version_id
        if username:
            params["username"] = username
        if nsfw:
            params["nsfw"] = nsfw
        if sort:
            params["sort"] = sort
        if period:
            params["period"] = period
        if cursor:
            params["cursor"] = cursor
        return self._get(f"{self._REST_BASE}/images", params=params,
                         caller="civitai.get_images_rest")

    def get_creators(
        self,
        query: str | None = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        """Search creators/users.

        REST endpoint: GET /api/v1/creators

        Args:
            query: Search by username.
            limit: Results per page (0-200, default 20).
            page: Page number.

        Returns:
            Dict with 'items' (creator list) and 'metadata' (pagination).
        """
        params: dict[str, Any] = {"limit": limit, "page": page}
        if query:
            params["query"] = query
        return self._get(f"{self._REST_BASE}/creators", params=params,
                         caller="civitai.get_creators")

    def get_tags(self) -> dict:
        """Get available tags for filtering.

        REST endpoint: GET /api/v1/tags

        Returns:
            Dict with 'items' (tag list).
        """
        return self._get(f"{self._REST_BASE}/tags",
                         caller="civitai.get_tags")

    # ─────────────────────────────────────────────────────────────────────
    #  tRPC API — internal, undocumented, discovered via Playwright
    #  More reliable than REST for image pagination.
    #  Requires auth for full results (authed: true).
    # ─────────────────────────────────────────────────────────────────────

    def get_images_trpc(
        self,
        version_id: int | None = None,
        model_id: int | None = None,
        sort: str = "Most Reactions",
        period: str = "AllTime",
        types: list[str] | None = None,
        with_meta: bool = False,
        from_platform: bool = False,
        is_remix: bool | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        """Fetch community images via tRPC (preferred over REST).

        More reliable pagination than REST. Can filter by version.
        Returns richer data including tags, thumbnailUrl, video metadata.

        IMPORTANT: The 'url' field in the response is just the cdn_id (UUID),
        NOT a full URL. Use build_cdn_url() to construct the downloadable URL.

        tRPC endpoint: image.getInfinite

        Args:
            version_id: Filter by model version. If not set, uses model_id.
            model_id: Filter by parent model (used if version_id not set).
            sort: 'Most Reactions' (default), 'Most Comments', 'Most Collected',
                  'Newest', 'Oldest'.
            period: 'AllTime' (default), 'Year', 'Month', 'Week', 'Day'.
            types: Filter media type: ['image'], ['video'], or None for all.
            with_meta: Only return items that have generation metadata.
            from_platform: Only return items generated on CivitAI ("Made on-site").
            is_remix: True=only remixes, False=only originals, None=all.
            limit: Max results per page (max 200).
            cursor: Pagination cursor from previous response's nextCursor.

        Returns:
            Dict with 'items' (image list) and 'nextCursor' (for pagination).
            Items have: id, url (cdn_id only!), type, width, height, nsfwLevel,
            user.username, postId, postTitle, stats, meta (often null for videos),
            metadata (video: hash, size, audio, duration), tags, tagIds,
            modelVersionId, baseModel, thumbnailUrl.
        """
        inp: dict[str, Any] = {
            "modelVersionId": version_id or model_id,
            "period": period,
            "sort": sort,
            "limit": limit,
            "pending": True,
            "include": [],
            "withMeta": with_meta,
            "excludedTagIds": [],
            "disablePoi": True,
            "disableMinor": True,
            "cursor": cursor,
            "authed": True,
        }
        # Optional filters — only add if explicitly set
        if types:
            inp["types"] = types
        if from_platform:
            inp["fromPlatform"] = True
        if is_remix is not None:
            inp["isRemix"] = is_remix

        return self._trpc_get("image.getInfinite", inp)

    def get_image_generation_data(self, image_id: int) -> dict:
        """Fetch full generation data for a single image.

        This is the ONLY way to get resources (LoRAs, checkpoints used),
        tools, and techniques. Requires one call per image — no batch.

        tRPC endpoint: image.getGenerationData

        Args:
            image_id: Numeric image ID (NOT the cdn_id UUID).

        Returns:
            Dict with: meta (prompt, steps, sampler, cfgScale, seed, clipSkip),
            resources[] (modelVersionId, modelId, modelName, modelType, strength),
            tools[] (e.g. "ComfyUI"), techniques[] (e.g. "txt2img"),
            onSite, process, canRemix.
        """
        return self._trpc_get("image.getGenerationData", {
            "id": image_id,
            "authed": True,
        })

    def get_creator_profile(self, username: str) -> dict:
        """Fetch a creator's profile including numeric user ID.

        The numeric ID is needed for prioritizedUserIds in get_images_trpc()
        (though we generally avoid using that parameter as it breaks pagination
        with small limit values).

        tRPC endpoint: user.getCreator

        Args:
            username: CivitAI username.

        Returns:
            User profile dict with numeric 'id', 'username', image, etc.
        """
        return self._trpc_get("user.getCreator", {"username": username})

    def get_hidden_preferences(self) -> dict:
        """Fetch the authenticated user's hidden/blocked content preferences.

        Returns lists of hidden tags, models, users, and blocked users.
        Useful for excludedTagIds in get_images_trpc().

        tRPC endpoint: hiddenPreferences.getHidden

        Returns:
            Dict with: hiddenTags[], hiddenModels[], hiddenUsers[], blockedUsers[].
            Each tag has id, name, nsfwLevel.
        """
        return self._trpc_get("hiddenPreferences.getHidden", None)

    # ─────────────────────────────────────────────────────────────────────
    #  PAGINATION HELPERS — generators that yield all pages
    # ─────────────────────────────────────────────────────────────────────

    def iter_images_rest(
        self,
        model_id: int | None = None,
        version_id: int | None = None,
        max_pages: int = 50,
        **kwargs,
    ):
        """Iterate all community images via REST API, paginating automatically.

        Yields individual image dicts. Stops when no more pages or max_pages reached.

        REST pagination uses metadata.nextCursor — UNRELIABLE. May stop early.
        Prefer iter_images_trpc() when possible.

        Args:
            model_id: Filter by parent model.
            version_id: Filter by version.
            max_pages: Safety limit to prevent infinite loops.
            **kwargs: Passed to get_images_rest() (nsfw, sort, period, limit).

        Yields:
            Individual image dicts from items[].
        """
        cursor = None
        for page in range(max_pages):
            data = self.get_images_rest(
                model_id=model_id,
                version_id=version_id,
                cursor=cursor,
                **kwargs,
            )
            items = data.get("items", [])
            if not items:
                break
            yield from items
            cursor = (data.get("metadata") or {}).get("nextCursor")
            if not cursor:
                break

    def iter_images_trpc(
        self,
        version_id: int | None = None,
        model_id: int | None = None,
        max_pages: int = 50,
        **kwargs,
    ):
        """Iterate all community images via tRPC, paginating automatically.

        Yields individual image dicts. Stops when no more pages or max_pages reached.

        tRPC pagination uses nextCursor — RELIABLE. Always returns cursor
        when more pages exist.

        IMPORTANT: Items have 'url' = cdn_id only. Use build_cdn_url() for full URL.

        Args:
            version_id: Filter by version.
            model_id: Filter by parent model (used if version_id not set).
            max_pages: Safety limit.
            **kwargs: Passed to get_images_trpc() (sort, period, types, etc).

        Yields:
            Individual image dicts from items[].
        """
        cursor = None
        for page in range(max_pages):
            data = self.get_images_trpc(
                version_id=version_id,
                model_id=model_id,
                cursor=cursor,
                **kwargs,
            )
            items = data.get("items", [])
            if not items:
                break
            yield from items
            cursor = data.get("nextCursor")
            if not cursor:
                break

    # ─────────────────────────────────────────────────────────────────────
    #  DATA NORMALIZATION — clean up CivitAI quirks
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def normalize_nsfw_level(value) -> int:
        """Safely convert nsfwLevel to integer.

        CivitAI returns nsfwLevel as: integer, string, "None", or null.
        This normalizes it to an integer.

        Levels: 1=SFW, 2=PG-13, 4=R, 8=X, 16=XXX, 32=blocked.

        Args:
            value: Raw nsfwLevel from API.

        Returns:
            Integer level, or 1 (SFW) if unparseable.
        """
        if value is None or value == "None":
            return 1
        try:
            return int(value)
        except (ValueError, TypeError):
            return 1

    @staticmethod
    def extract_card_images(version_data: dict) -> list[dict]:
        """Extract and normalize card images from a version response.

        Card images (from modelVersions[].images[]) have id=null.
        This extracts the cdn_id from the URL and adds it to each image dict.

        Args:
            version_data: A single version dict from the models API.

        Returns:
            List of image dicts, each with 'cdn_id' added.
        """
        result = []
        for img in version_data.get("images", []):
            url = img.get("url", "")
            if not url:
                continue
            cdn_id = extract_cdn_id_from_url(url)
            if not cdn_id:
                continue
            normalized = dict(img)
            normalized["cdn_id"] = cdn_id
            # id is always null for card images — set to cdn_id as fallback
            if not normalized.get("id"):
                normalized["id"] = cdn_id
            result.append(normalized)
        return result

    @staticmethod
    def normalize_trpc_image(item: dict) -> dict:
        """Normalize a tRPC image item for consistent access.

        tRPC responses have quirks:
        - 'url' is just the cdn_id UUID, not a full URL
        - 'user' is a nested object with 'username'
        - 'metadata' (not 'meta') has video info (duration, audio, size)
        - 'meta' has generation params (prompt, seed, etc.) but is often null

        This adds convenience fields without removing original data.

        Args:
            item: Raw item from image.getInfinite response.

        Returns:
            Same dict with added fields: cdn_id, full_url, username.
        """
        normalized = dict(item)
        cdn_id = item.get("url", "")
        media_type = item.get("type", "image")
        normalized["cdn_id"] = cdn_id
        normalized["full_url"] = build_cdn_url(cdn_id, media_type)
        # Flatten nested user
        user = item.get("user")
        if isinstance(user, dict):
            normalized["username"] = user.get("username", "")
        else:
            normalized["username"] = ""
        return normalized
