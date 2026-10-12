"""Image preparation utilities shared by Visual OCR runtime and QA tools."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import VisualOCRSettings


class VisualOCRImagePreparationError(Exception):
    """Raised when screenshot bytes cannot be prepared for a VLM provider."""


@dataclass(frozen=True, slots=True)
class PreparedVisualOCRImage:
    """Provider-ready image payload.

    Attributes:
        image_base64: Base64-encoded PNG bytes safe for data-url transport.
        image_media_type: MIME type for ``image_base64``.
        original_width: Width reported by the source image before resizing.
        original_height: Height reported by the source image before resizing.
        prepared_width: Width sent to the provider.
        prepared_height: Height sent to the provider.
        prepared_byte_size: Size of the encoded image sent to the provider.
    """

    image_base64: str
    image_media_type: str
    original_width: int
    original_height: int
    prepared_width: int
    prepared_height: int
    prepared_byte_size: int


class VisualOCRImagePreparer:
    """Prepare screenshot artifacts for remote visual OCR providers.

    The daemon, QA scripts, and future job replayers should share this class so
    provider behavior does not diverge between production and test tools.
    """

    def __init__(self, *, vault: LocalArtifactVault | None = None) -> None:
        """Create an image preparer.

        Args:
            vault: Optional artifact vault used to read ``local-artifact://``
                URIs. QA tools can call :meth:`prepare_bytes` directly.
        """

        self.vault = vault

    def prepare_artifact(self, *, storage_uri: str, settings: VisualOCRSettings) -> PreparedVisualOCRImage:
        """Read a local artifact and prepare it for the configured provider.

        Args:
            storage_uri: Artifact URI stored on screenshot evidence.
            settings: Visual OCR settings containing max image size.

        Returns:
            Provider-ready PNG data.

        Raises:
            VisualOCRImagePreparationError: If the vault is missing, artifact
                read fails, or the bytes are not a readable image.
        """

        if self.vault is None:
            raise VisualOCRImagePreparationError("visual OCR image preparer has no artifact vault")
        try:
            raw = self.vault.read(storage_uri)
        except ArtifactVaultError as exc:
            raise VisualOCRImagePreparationError("failed to read screenshot for visual OCR") from exc
        return self.prepare_bytes(raw, settings=settings)

    def prepare_bytes(self, raw: bytes, *, settings: VisualOCRSettings) -> PreparedVisualOCRImage:
        """Resize and encode image bytes for a VLM provider.

        Args:
            raw: Source screenshot bytes.
            settings: Visual OCR settings containing ``max_image_long_edge``.

        Returns:
            Provider-ready PNG data and dimensions.

        Raises:
            VisualOCRImagePreparationError: If the bytes cannot be decoded as
                an image by Pillow.
        """

        try:
            return self._prepare_bytes(raw, settings=settings, allow_truncated=False)
        except (UnidentifiedImageError, OSError) as first_exc:
            try:
                return self._prepare_bytes(raw, settings=settings, allow_truncated=True)
            except (UnidentifiedImageError, OSError) as second_exc:
                second_exc.add_note(f"strict decode failed first: {first_exc}")
                raise VisualOCRImagePreparationError("screenshot is not a readable image") from second_exc

    def _prepare_bytes(
        self,
        raw: bytes,
        *,
        settings: VisualOCRSettings,
        allow_truncated: bool,
    ) -> PreparedVisualOCRImage:
        previous_truncated_setting = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = allow_truncated
        try:
            with Image.open(BytesIO(raw)) as image:
                image = ImageOps.exif_transpose(image)
                original_width, original_height = image.size
                image.thumbnail((settings.max_image_long_edge, settings.max_image_long_edge))
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                prepared = output.getvalue()
                return PreparedVisualOCRImage(
                    image_base64=base64.b64encode(prepared).decode("ascii"),
                    image_media_type="image/png",
                    original_width=original_width,
                    original_height=original_height,
                    prepared_width=image.width,
                    prepared_height=image.height,
                    prepared_byte_size=len(prepared),
                )
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated_setting
