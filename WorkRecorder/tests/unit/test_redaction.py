from packages.evidence.redaction import SensitiveTextRedactor


def test_sensitive_text_redactor_handles_common_secret_shapes():
    redactor = SensitiveTextRedactor()

    text = redactor.redact(
        "\n".join(
            [
                "Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER",
                "Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER",
                "API token: SHOULD_NOT_LEAK_VISIBLE_TOKEN",
                "Session ID: SHOULD_NOT_LEAK_SESSION",
                "csrf=SHOULD_NOT_LEAK_CSRF",
                "jwt=abc.def.ghi",
                "email ops@example.test",
            ]
        )
    )

    assert "SHOULD_NOT_LEAK" not in text
    assert "abc.def.ghi" not in text
    assert "ops@example.test" not in text
    assert "Authorization: Bearer [REDACTED]" in text
    assert "API token: [REDACTED]" in text
