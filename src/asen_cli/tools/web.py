from __future__ import annotations

import httpx
from pydantic import BaseModel, Field, field_validator

from ..utils.safety import truncate_text
from .base import BaseTool, ToolResult


class WebFetchArgs(BaseModel):
    url: str = Field(..., description="HTTP or HTTPS URL to fetch.")

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a HTTP/HTTPS URL and return truncated text content."
    args_model = WebFetchArgs

    def __init__(self, *, max_output_chars: int, client: httpx.AsyncClient | None = None) -> None:
        self.max_output_chars = max_output_chars
        self.client = client

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = WebFetchArgs.model_validate(args)
        try:
            if self.client is not None:
                response = await self.client.get(typed_args.url, follow_redirects=True)
            else:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    response = await client.get(typed_args.url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            return ToolResult.failure(
                f"Fetch timed out: {exc}",
                error_type="network_timeout",
                retryable=True,
            )
        except httpx.HTTPError as exc:
            return ToolResult.failure(
                f"Fetch failed: {exc}",
                error_type="network_error",
                retryable=True,
            )

        content_type = response.headers.get("content-type", "unknown")
        body = truncate_text(response.text, self.max_output_chars)
        return ToolResult.success(f"url={typed_args.url}\ncontent_type={content_type}\n\n{body}")
