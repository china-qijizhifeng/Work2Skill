"""Secret storage adapters for local-only settings."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
from typing import Protocol

logger = logging.getLogger(__name__)


class SecretStore(Protocol):
    """Minimal secret store boundary used by configurable providers."""

    def get(self, *, service: str, account: str) -> str | None:
        """Return a secret value, if configured.

        Args:
            service: Secret namespace, usually a product-scoped service id.
            account: Account or setting key inside the namespace.

        Returns:
            Secret value when present, otherwise ``None``.
        """

    def set(self, *, service: str, account: str, value: str) -> None:
        """Persist a secret value.

        Args:
            service: Secret namespace, usually a product-scoped service id.
            account: Account or setting key inside the namespace.
            value: Secret value to store.
        """

    def delete(self, *, service: str, account: str) -> None:
        """Delete a secret value if present.

        Args:
            service: Secret namespace, usually a product-scoped service id.
            account: Account or setting key inside the namespace.
        """


class SecretStoreError(RuntimeError):
    """Sanitized local secret-store failure that never includes secret values."""


class EnvSecretStore:
    """Read-only fallback that maps a secret account to an environment variable."""

    def get(self, *, service: str, account: str) -> str | None:
        """Return environment-provided secrets for development and tests.

        Args:
            service: Ignored namespace kept for store interoperability.
            account: Environment variable name that may hold the secret.

        Returns:
            Environment secret when configured, otherwise ``None``.
        """

        del service
        return os.getenv(account)

    def set(self, *, service: str, account: str, value: str) -> None:
        """Reject writes because environment variables are process-owned.

        Args:
            service: Ignored namespace kept for store interoperability.
            account: Environment variable name.
            value: Secret value that cannot be persisted here.

        Raises:
            RuntimeError: Always raised because this store is read-only.
        """

        del service, account, value
        raise RuntimeError("environment secret store is read-only")

    def delete(self, *, service: str, account: str) -> None:
        """No-op for read-only fallback stores.

        Args:
            service: Ignored namespace kept for store interoperability.
            account: Environment variable name.
        """

        del service, account


class ChainedSecretStore:
    """Read from multiple stores and write to the first writable store."""

    def __init__(self, *stores: SecretStore) -> None:
        self.stores = stores

    def get(self, *, service: str, account: str) -> str | None:
        """Return the first configured secret.

        Args:
            service: Secret namespace to query in each store.
            account: Account or setting key to query in each store.

        Returns:
            First non-empty secret returned by a store, otherwise ``None``.
        """

        for store in self.stores:
            try:
                value = store.get(service=service, account=account)
                if value:
                    return value
            except Exception as exc:
                logger.debug("Secret store read fallback skipped a store: %s", exc.__class__.__name__)
                continue
        return None

    def set(self, *, service: str, account: str, value: str) -> None:
        """Persist a secret into the first writable store.

        Args:
            service: Secret namespace to write.
            account: Account or setting key to write.
            value: Secret value to persist.

        Raises:
            Exception: Re-raises the first store failure when every store fails.
        """

        first_error: Exception | None = None
        for store in self.stores:
            try:
                store.set(service=service, account=account, value=value)
                return
            except Exception as exc:  # pragma: no cover - defensive fallback boundary.
                logger.debug("Secret store write fallback skipped a store: %s", exc.__class__.__name__)
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def delete(self, *, service: str, account: str) -> None:
        """Delete the secret from every writable store.

        Args:
            service: Secret namespace to delete from.
            account: Account or setting key to delete.
        """

        for store in self.stores:
            try:
                store.delete(service=service, account=account)
            except Exception as exc:
                logger.debug("Secret store delete fallback skipped a store: %s", exc.__class__.__name__)
                continue


class MacOSKeychainSecretStore:
    """Store local model API keys in the user's macOS Keychain."""

    _ERR_SEC_ITEM_NOT_FOUND = -25300
    _ERR_SEC_DUPLICATE_ITEM = -25299

    def __init__(self) -> None:
        self._security: ctypes.CDLL | None = None
        self._core_foundation: ctypes.CDLL | None = None

    def get(self, *, service: str, account: str) -> str | None:
        """Read a generic password from Keychain.

        Args:
            service: Keychain service name.
            account: Keychain account name.

        Returns:
            Stored secret when present, otherwise ``None``.

        Raises:
            SecretStoreError: Raised when Keychain cannot be queried safely.
        """

        security = self._security_framework()
        service_bytes = service.encode("utf-8")
        account_bytes = account.encode("utf-8")
        password_length = ctypes.c_uint32(0)
        password_data = ctypes.c_void_p()
        item_ref = ctypes.c_void_p()
        status = security.SecKeychainFindGenericPassword(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            ctypes.byref(password_length),
            ctypes.byref(password_data),
            ctypes.byref(item_ref),
        )
        if status == self._ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != 0:
            raise SecretStoreError("macOS Keychain read failed")
        try:
            value = ctypes.string_at(password_data, password_length.value).decode("utf-8")
            return value or None
        finally:
            security.SecKeychainItemFreeContent(None, password_data)
            self._release(item_ref)

    def set(self, *, service: str, account: str, value: str) -> None:
        """Write a generic password into Keychain.

        Args:
            service: Keychain service name.
            account: Keychain account name.
            value: Secret value to store.

        Raises:
            SecretStoreError: Raised when Keychain write or update fails.
        """

        security = self._security_framework()
        service_bytes = service.encode("utf-8")
        account_bytes = account.encode("utf-8")
        value_bytes = value.encode("utf-8")
        status = security.SecKeychainAddGenericPassword(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            len(value_bytes),
            value_bytes,
            None,
        )
        if status == self._ERR_SEC_DUPLICATE_ITEM:
            self._update_existing(
                service_bytes=service_bytes,
                account_bytes=account_bytes,
                value_bytes=value_bytes,
            )
            return
        if status != 0:
            raise SecretStoreError("macOS Keychain write failed")

    def delete(self, *, service: str, account: str) -> None:
        """Delete a generic password from Keychain if it exists.

        Args:
            service: Keychain service name.
            account: Keychain account name.

        Raises:
            SecretStoreError: Raised when Keychain delete fails.
        """

        security = self._security_framework()
        item_ref = self._find_item(service_bytes=service.encode("utf-8"), account_bytes=account.encode("utf-8"))
        if item_ref is None:
            return
        try:
            status = security.SecKeychainItemDelete(item_ref)
            if status not in {0, self._ERR_SEC_ITEM_NOT_FOUND}:
                raise SecretStoreError("macOS Keychain delete failed")
        finally:
            self._release(item_ref)

    def _security_framework(self) -> ctypes.CDLL:
        if sys.platform != "darwin":
            raise SecretStoreError("macOS Keychain is unavailable on this platform")
        if self._security is None:
            path = ctypes.util.find_library("Security")
            if not path:
                raise SecretStoreError("macOS Security framework was not found")
            self._security = ctypes.CDLL(path)
            self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
            self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
            self._security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
            self._security.SecKeychainItemDelete.restype = ctypes.c_int32
            self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        return self._security

    def _core_foundation_framework(self) -> ctypes.CDLL:
        if self._core_foundation is None:
            path = ctypes.util.find_library("CoreFoundation")
            if not path:
                raise SecretStoreError("macOS CoreFoundation framework was not found")
            self._core_foundation = ctypes.CDLL(path)
            self._core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
            self._core_foundation.CFRelease.restype = None
        return self._core_foundation

    def _find_item(self, *, service_bytes: bytes, account_bytes: bytes) -> ctypes.c_void_p | None:
        security = self._security_framework()
        item_ref = ctypes.c_void_p()
        status = security.SecKeychainFindGenericPassword(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            None,
            None,
            ctypes.byref(item_ref),
        )
        if status == self._ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != 0:
            raise SecretStoreError("macOS Keychain item lookup failed")
        return item_ref

    def _update_existing(self, *, service_bytes: bytes, account_bytes: bytes, value_bytes: bytes) -> None:
        item_ref = self._find_item(service_bytes=service_bytes, account_bytes=account_bytes)
        if item_ref is None:
            raise SecretStoreError("macOS Keychain item disappeared during update")
        security = self._security_framework()
        try:
            status = security.SecKeychainItemModifyAttributesAndData(
                item_ref,
                None,
                len(value_bytes),
                value_bytes,
            )
            if status != 0:
                raise SecretStoreError("macOS Keychain update failed")
        finally:
            self._release(item_ref)

    def _release(self, item_ref: ctypes.c_void_p) -> None:
        if item_ref:
            self._core_foundation_framework().CFRelease(item_ref)
