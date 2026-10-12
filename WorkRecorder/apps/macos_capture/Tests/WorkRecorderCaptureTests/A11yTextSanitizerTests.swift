import Testing
@testable import WorkRecorderCapture

struct A11yTextSanitizerTests {
    @Test func redactsBearerAuthorization() {
        let text = A11yTextSanitizer().redact("Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER")

        #expect(text == "Authorization: Bearer REDACTED")
    }

    @Test func redactsBareBearer() {
        let text = A11yTextSanitizer().redact("Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER")

        #expect(text == "Bearer REDACTED")
    }

    @Test func redactsTokenValue() {
        let text = A11yTextSanitizer().redact("API token: SHOULD_NOT_LEAK_VISIBLE_TOKEN")

        #expect(text == "API token: REDACTED")
    }

    @Test func redactsSessionId() {
        let text = A11yTextSanitizer().redact("Session ID: SHOULD_NOT_LEAK_SESSION")

        #expect(text == "Session ID: REDACTED")
    }
}
