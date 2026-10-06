from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from servicenow_mcp.auth.factory import create_auth_provider
from servicenow_mcp.config.local import Settings
from servicenow_mcp.errors import OperationError


class ServiceNowClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        instance = self.settings.instance.rstrip("/")
        if not urlparse(instance).scheme:
            instance = f"https://{instance}"
        self.instance_url = instance
        self.base_url = f"{instance}/api/now"
        self.session = requests.Session()

        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        create_auth_provider(settings).authenticate(self.session)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if path.startswith("/table/"):
            params = dict(params or {})
            # Keep raw values for non-reference fields and use links to identify
            # references without fetching table metadata or individual records.
            params["sysparm_display_value"] = "all"
            params["sysparm_exclude_reference_link"] = "false"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                timeout=30,
            )
        except requests.ConnectTimeout:
            raise OperationError("TIMEOUT", retryable=method == "GET") from None
        except (
            requests.exceptions.InvalidURL,
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
        ):
            raise OperationError("UPSTREAM_ERROR") from None
        except requests.Timeout:
            raise OperationError(
                "TIMEOUT",
                outcome="unknown" if method != "GET" else "failed",
                retryable=method == "GET",
            ) from None
        except requests.RequestException:
            raise OperationError(
                "UPSTREAM_ERROR",
                outcome="unknown" if method != "GET" else "failed",
                retryable=method == "GET",
            ) from None

        write = method != "GET"
        if response.status_code >= 400:
            status = response.status_code
            code = {
                401: "AUTHENTICATION_REQUIRED",
                403: "PERMISSION_DENIED",
                404: "NOT_FOUND",
                408: "TIMEOUT",
                504: "TIMEOUT",
            }.get(status, "UPSTREAM_ERROR")
            # A gateway/server failure may occur after a write has committed.
            outcome = (
                "unknown" if write and (status >= 500 or status == 408) else "failed"
            )
            raise OperationError(
                code,
                outcome=outcome,
                retryable=not write and (status in {408, 429} or status >= 500),
                http_status=status,
            ) from None

        try:
            body = response.json()
        except ValueError:
            raise OperationError(
                "UPSTREAM_ERROR", outcome="unknown" if write else "failed"
            ) from None
        if not isinstance(body, dict) or body.get("error"):
            raise OperationError(
                "UPSTREAM_ERROR", outcome="unknown" if write else "failed"
            ) from None
        if path.startswith("/table/"):
            result = body.get("result")
            if isinstance(result, dict):
                body["result"] = self._display_record(result)
            elif isinstance(result, list):
                if any(not isinstance(record, dict) for record in result):
                    raise OperationError(
                        "UPSTREAM_ERROR", outcome="unknown" if write else "failed"
                    )
                body["result"] = [self._display_record(record) for record in result]
        return body

    @staticmethod
    def _display_record(record: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten Table API field wrappers, using display names for references."""
        return {
            field: (
                value.get("display_value", "") if "link" in value else value["value"]
            )
            if isinstance(value, dict) and "value" in value
            else value
            for field, value in record.items()
        }

    def list_records(
        self,
        table: str,
        query: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "sysparm_limit": min(max(limit, 1), 100),
        }

        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = ",".join(fields)

        result = self._request("GET", f"/table/{table}", params=params)
        return result.get("result", [])

    def get_record(
        self,
        table: str,
        sys_id: str,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if fields:
            params["sysparm_fields"] = ",".join(fields)

        result = self._request("GET", f"/table/{table}/{sys_id}", params=params)
        record = result.get("result")
        if record is None or record == {}:
            raise OperationError("NOT_FOUND", outcome="failed")
        return record

    def create_record(self, table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("POST", f"/table/{table}", json_body=payload)
        return self._write_result(result)

    def update_record(
        self, table: str, sys_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        result = self._request("PATCH", f"/table/{table}/{sys_id}", json_body=payload)
        return self._write_result(result)

    @staticmethod
    def _write_result(response: Dict[str, Any]) -> Dict[str, Any]:
        record = response.get("result")
        if not isinstance(record, dict) or not record.get("sys_id"):
            raise OperationError("UPSTREAM_ERROR", outcome="unknown")
        return record
