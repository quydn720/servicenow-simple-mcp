from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from servicenow_mcp.auth.factory import create_auth_provider
from servicenow_mcp.config.local import Settings


class ServiceNowClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        instance = self.settings.instance.rstrip("/")
        if not urlparse(instance).scheme:
            instance = f"https://{instance}"
        self.instance_url = instance
        self.base_url = f"{instance}/api/now"
        self.session = requests.Session()

        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        create_auth_provider(settings).authenticate(self.session)

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        except requests.RequestException:
            raise RuntimeError("ServiceNow request failed; check connectivity") from None

        if response.status_code >= 400:
            message = f"ServiceNow request failed (HTTP {response.status_code})"
            # Return documented API error fields, never raw bodies or headers.
            try:
                body = response.json()
                error = body.get("error") if isinstance(body, dict) else None
                if isinstance(error, dict):
                    details = [error.get(field) for field in ("message", "detail")]
                    details = [value for value in details if isinstance(value, str) and value]
                    if details:
                        message += ": " + "; ".join(details)
            except ValueError:
                pass
            raise RuntimeError(message)

        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("ServiceNow returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise RuntimeError("ServiceNow returned an invalid JSON response")
        if body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else None
            raise RuntimeError(message if isinstance(message, str) else "ServiceNow returned an error")
        if path.startswith("/table/"):
            result = body.get("result")
            if isinstance(result, dict):
                body["result"] = self._display_record(result)
            elif isinstance(result, list):
                body["result"] = [self._display_record(record) for record in result]
        return body

    @staticmethod
    def _display_record(record: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten Table API field wrappers, using display names for references."""
        return {
            field: (
                value.get("display_value", "") if "link" in value else value["value"]
            ) if isinstance(value, dict) and "value" in value else value
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
        return result.get("result", {})

    def create_record(self, table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("POST", f"/table/{table}", json_body=payload)
        return self._write_result(result)

    def update_record(self, table: str, sys_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("PATCH", f"/table/{table}/{sys_id}", json_body=payload)
        return self._write_result(result)

    @staticmethod
    def _write_result(response: Dict[str, Any]) -> Dict[str, Any]:
        record = response.get("result")
        if not isinstance(record, dict) or not record.get("sys_id"):
            raise RuntimeError("ServiceNow write returned no valid record; verify the instance before retrying")
        return record
