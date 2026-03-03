"""Content sanitization for security.

Removes or masks sensitive information:
- API keys
- Passwords
- Tokens
- Secrets
"""

import re
from dataclasses import dataclass
from re import Pattern


@dataclass
class SanitizationRule:
    """Rule for content sanitization."""

    name: str
    pattern: Pattern[str]
    replacement: str
    description: str


class Sanitizer:
    """Content sanitizer for sensitive data."""

    # Default rules for common secrets
    DEFAULT_RULES = [
        SanitizationRule(
            name="openai_api_key",
            pattern=re.compile(r"sk-[a-zA-Z0-9]{48}"),
            replacement="[OPENAI_API_KEY_REDACTED]",
            description="OpenAI API key",
        ),
        SanitizationRule(
            name="anthropic_api_key",
            pattern=re.compile(r"sk-ant-[a-zA-Z0-9_-]{100,}"),
            replacement="[ANTHROPIC_API_KEY_REDACTED]",
            description="Anthropic API key",
        ),
        SanitizationRule(
            name="generic_api_key",
            pattern=re.compile(r"[a-zA-Z_]+_API_KEY\s*=\s*['\"][^'\"]+['\"]"),
            replacement="[API_KEY_REDACTED]",
            description="Generic API key assignment",
        ),
        SanitizationRule(
            name="password",
            pattern=re.compile(r"password\s*[=:]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
            replacement="[PASSWORD_REDACTED]",
            description="Password",
        ),
        SanitizationRule(
            name="secret",
            pattern=re.compile(r"secret[_\w]*\s*[=:]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
            replacement="[SECRET_REDACTED]",
            description="Secret",
        ),
        SanitizationRule(
            name="token",
            pattern=re.compile(r"token\s*[=:]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
            replacement="[TOKEN_REDACTED]",
            description="Token",
        ),
        SanitizationRule(
            name="bearer_token",
            pattern=re.compile(r"Bearer\s+[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
            replacement="[BEARER_TOKEN_REDACTED]",
            description="JWT Bearer token",
        ),
        SanitizationRule(
            name="private_key",
            pattern=re.compile(
                r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
            ),
            replacement="[PRIVATE_KEY_REDACTED]",
            description="Private key",
        ),
        SanitizationRule(
            name="database_url",
            pattern=re.compile(r"(postgresql|mysql|mongodb)://[^:\s]+:[^@\s]+@"),
            replacement=r"\1://[USER]:[PASS]@",
            description="Database URL with credentials",
        ),
    ]

    def __init__(self, rules: list[SanitizationRule] | None = None):
        """Initialize sanitizer.

        Args:
            rules: Custom sanitization rules (uses defaults if None)
        """
        self.rules = rules or self.DEFAULT_RULES.copy()

    def sanitize(self, content: str) -> str:
        """Sanitize content.

        Args:
            content: Content to sanitize

        Returns:
            Sanitized content
        """
        result = content
        for rule in self.rules:
            result = rule.pattern.sub(rule.replacement, result)
        return result

    def add_rule(self, rule: SanitizationRule) -> "Sanitizer":
        """Add a sanitization rule.

        Args:
            rule: Rule to add

        Returns:
            Self for chaining
        """
        self.rules.append(rule)
        return self

    def remove_rule(self, name: str) -> "Sanitizer":
        """Remove a sanitization rule.

        Args:
            name: Name of rule to remove

        Returns:
            Self for chaining
        """
        self.rules = [r for r in self.rules if r.name != name]
        return self


# Global sanitizer instance
_default_sanitizer = Sanitizer()


def sanitize_content(content: str) -> str:
    """Sanitize content using default rules.

    Args:
        content: Content to sanitize

    Returns:
        Sanitized content
    """
    return _default_sanitizer.sanitize(content)


def sanitize_dict(data: dict, fields: list[str] | None = None) -> dict:
    """Sanitize dictionary values.

    Args:
        data: Dictionary to sanitize
        fields: Specific fields to sanitize (all string values if None)

    Returns:
        Sanitized dictionary
    """
    result = {}
    for key, value in data.items():
        if fields is None or key in fields:
            if isinstance(value, str):
                result[key] = sanitize_content(value)
            else:
                result[key] = value
        else:
            result[key] = value
    return result
