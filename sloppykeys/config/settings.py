"""App settings and image profile persistence."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

from sloppykeys.core.image_search import ImageProfile, SearchRegion, clamp_confidence

from .store import ensure_json, read_json, update_json, write_json

SETTINGS_FILE = "settings.json"
IMAGES_DIR_NAME = "images"
IMAGE_SETTINGS_FILE = "images.json"
IMAGES_KEY = "images"

PRIVATE_SERVER_KEY = "private_server_link"
WEBHOOK_KEY = "discord_webhook"

HARD_MODE_KEY = "hard_mode"
# Opt-in: run the ~8s camera sequence once per Roblox session instead of once per match.
# Default **off** because placement coordinates are stored against one camera angle, so if
# Roblox resets the camera on a stage load, skipping misplaces every unit silently. Cheap to
# turn on and observe; expensive to have on by default and be wrong.
CAMERA_ONCE_KEY = "camera_once_per_session"
# Check GitHub for a newer release once per launch. Default **on**: the alternative is a
# user sitting on a version with a known bad Start click and no way to find out. It never
# downloads anything by itself — see `core/updates.py`. Deliberately left out of
# `build_exe.py`'s SHIPPED_SETTINGS_KEYS so a build always ships it on.
AUTO_UPDATE_KEY = "auto_update"
# Expedition difficulty is **not** here. It was one global 1-3 for every Expedition task,
# which contradicted the queue: two tasks on the same map can want different difficulties.
# It lives on the task now (`content/start_stage.difficulty_from_task`), and a leftover
# `expedition_difficulty` key in settings.json is simply ignored.
# There is deliberately no **global** match-tolerance setting. One existed and was removed:
# a single tunable threshold was observed swinging between 0.57 (false matches) and 0.95
# (rejecting nearly everything, since a good match scores 0.95-1.00), and each value broke
# the following run while looking like an image problem. The stale `match_confidence` key in
# an existing settings.json is simply ignored — readers here don't touch unknown keys.
# Per-template thresholds are a different thing and do exist: `config/regions.py`'s
# `ConfidenceStore` (the `confidence` key), floored at 0.60, edited in Settings > Vision.
EMPTY_VALUE = "empty"


class AppSettings:
    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)
        ensure_json(self._path, self.defaults())

    @staticmethod
    def defaults() -> dict[str, object]:
        return {
            PRIVATE_SERVER_KEY: EMPTY_VALUE,
            WEBHOOK_KEY: "",
            HARD_MODE_KEY: False,
            CAMERA_ONCE_KEY: False,
            AUTO_UPDATE_KEY: True,
        }

    def read(self) -> dict[str, object]:
        payload = read_json(self._path)
        return {**self.defaults(), **payload}

    def _set(self, key: str, value: object) -> None:
        """Write one key, atomically.

        Every setter used to `read()` the whole file, change its key and write it all
        back. That is a read-modify-write on a file three other stores also own, and a
        concurrent writer's change lands between the read and the write and is lost.
        `read()` also merges in `defaults()`, so the old path additionally wrote every
        default value back into the file whether it had been set or not.
        """

        def mutate(payload: dict) -> None:
            payload[key] = value

        update_json(self._path, mutate)

    def get_private_server_link(self) -> str:
        value = str(self.read().get(PRIVATE_SERVER_KEY, "")).strip()
        return "" if value.lower() == EMPTY_VALUE else value

    def set_private_server_link(self, link: str) -> None:
        self._set(PRIVATE_SERVER_KEY, link.strip() or EMPTY_VALUE)

    def get_discord_webhook(self) -> str:
        """The Discord webhook URL, or "" for notifications off."""
        return str(self.read().get(WEBHOOK_KEY, "")).strip()

    def set_discord_webhook(self, url: str) -> None:
        self._set(WEBHOOK_KEY, (url or "").strip())

    # There is no `run_challenges` switch. It was the toggle a deleted `TaskDirector` read to
    # decide whether challenges preempted the queue; challenges are now a **task** in the
    # queue, and the presence of that task is the switch. Removing it is safe for a stored
    # setup — an unknown key in settings.json is preserved and simply never read.

    def get_camera_once(self) -> bool:
        return bool(self.read().get(CAMERA_ONCE_KEY, False))

    def set_camera_once(self, enabled: bool) -> None:
        self._set(CAMERA_ONCE_KEY, bool(enabled))

    def get_auto_update(self) -> bool:
        return bool(self.read().get(AUTO_UPDATE_KEY, True))

    def set_auto_update(self, enabled: bool) -> None:
        self._set(AUTO_UPDATE_KEY, bool(enabled))

    def get_hard_mode(self) -> bool:
        return bool(self.read().get(HARD_MODE_KEY, False))

    def set_hard_mode(self, enabled: bool) -> None:
        self._set(HARD_MODE_KEY, bool(enabled))


# Roblox's share page hands the client a deep link rather than a resolved server
# URL, and the client resolves the code itself — so opening this launches Roblox
# straight into the private server, with no browser tab and no manual Join click.
# Format confirmed against roblox.com's own share-page script:
# devforum.roblox.com/t/parsing-deeplink-information-from-a-private-server-link-with-the-newer-format/3464724
SHARE_LINK_TYPE = "Server"

# Codes are interpolated into a URI handed to the shell, so this is a trust
# boundary: anything but plain alphanumerics is rejected, not escaped.
_CODE_PATTERN = re.compile(r"[0-9a-zA-Z]{8,64}")


def _share_uri(code: str) -> str:
    return f"roblox://navigation/share_links?code={code}&type={SHARE_LINK_TYPE}"


def _query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return values[0].strip() if values and values[0].strip() else ""


def parse_private_server_link(link: str) -> tuple[str, str]:
    """Return (launch_uri, error_message).

    Accepts what a user actually has to hand:
      - https://www.roblox.com/share?code=<code>&type=Server  (current format)
      - a bare share code
      - roblox://navigation/share_links?code=<code>&type=Server (already a deep link)
      - https://www.roblox.com/games/<id>?privateServerLinkCode=<code> (legacy)
    """
    cleaned = link.strip()
    if not cleaned:
        return ("", "Enter a private server link.")

    if _CODE_PATTERN.fullmatch(cleaned):
        return (_share_uri(cleaned), "")

    parsed = urlparse(cleaned)
    query = parse_qs(parsed.query)
    code = _query_value(query, "code")

    if parsed.scheme == "roblox":
        if not _CODE_PATTERN.fullmatch(code):
            return ("", "Deep link is missing a valid code.")
        return (_share_uri(code), "")

    if parsed.scheme not in {"http", "https"}:
        return ("", "Link must start with http, https or roblox.")

    if code:
        link_type = _query_value(query, "type") or SHARE_LINK_TYPE
        if link_type.lower() != SHARE_LINK_TYPE.lower():
            return ("", f"Share link type is '{link_type}', expected {SHARE_LINK_TYPE}.")
        if not _CODE_PATTERN.fullmatch(code):
            return ("", "Share code contains unexpected characters.")
        return (_share_uri(code), "")

    # Legacy links carry no share code, so the deprecated placeId/linkCode deep
    # link is the only URI that can be built for one. Still functional as of
    # 2026, but new links won't look like this.
    place = re.search(r"/games/(\d+)", parsed.path)
    legacy_code = _query_value(query, "privateServerLinkCode")
    if place and _CODE_PATTERN.fullmatch(legacy_code):
        return (f"roblox://placeId={place.group(1)}&linkCode={legacy_code}", "")

    return ("", "Paste the share link: roblox.com/share?code=...&type=Server")


class ImageProfileStore:
    """Image templates and their saved search regions."""

    def __init__(self, app_root: str, engine) -> None:
        self._app_root = app_root
        self._engine = engine
        self._images_dir = os.path.join(app_root, IMAGES_DIR_NAME)
        self._path = os.path.join(self._images_dir, IMAGE_SETTINGS_FILE)
        os.makedirs(self._images_dir, exist_ok=True)
        ensure_json(self._path, {IMAGES_KEY: {}})

    @property
    def images_dir(self) -> str:
        return self._images_dir

    def profile_key(self, image_path: str) -> str:
        return self._engine.to_storable_path(image_path).replace("\\", "/")

    def load(self) -> dict[str, ImageProfile]:
        payload = read_json(self._path)
        raw_profiles = payload.get(IMAGES_KEY, {})
        if not isinstance(raw_profiles, dict):
            return {}

        profiles: dict[str, ImageProfile] = {}
        for raw_name, raw_data in raw_profiles.items():
            if not isinstance(raw_name, str) or not isinstance(raw_data, dict):
                continue

            raw_path = str(raw_data.get("image_path", "")).strip()
            if not raw_path:
                continue

            key = self.profile_key(raw_path)
            profiles[key] = ImageProfile(
                name=key,
                image_path=self._engine.to_absolute_path(raw_path),
                region=_parse_region(raw_data.get("region")),
                enabled=bool(raw_data.get("enabled", True)),
                confidence=clamp_confidence(raw_data.get("confidence")),
            )

        return profiles

    def save(self, profiles: dict[str, ImageProfile]) -> bool:
        serialized: dict[str, dict] = {}
        for key, profile in profiles.items():
            entry: dict[str, object] = {
                "image_path": self._engine.to_storable_path(profile.image_path),
                "enabled": bool(profile.enabled),
                "confidence": float(profile.confidence),
            }
            if profile.region is not None:
                entry["region"] = profile.region.as_payload()
            serialized[key] = entry

        return write_json(self._path, {IMAGES_KEY: serialized})


def _parse_region(raw_region: object) -> SearchRegion | None:
    if not isinstance(raw_region, dict):
        return None
    try:
        width = int(raw_region.get("width", 0))
        height = int(raw_region.get("height", 0))
        if width <= 0 or height <= 0:
            return None
        return SearchRegion(
            x=int(raw_region.get("x", 0)),
            y=int(raw_region.get("y", 0)),
            width=width,
            height=height,
        )
    except (TypeError, ValueError):
        return None
