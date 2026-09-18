from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from app.auth.factory import create_auth_provider
from app.config import Settings


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
            raise RuntimeError(f"ServiceNow request failed (HTTP {response.status_code})")

        try:
            return response.json()
        except ValueError:
            raise RuntimeError("ServiceNow returned a non-JSON response") from None

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
        return result.get("result", {})

    def update_record(self, table: str, sys_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("PATCH", f"/table/{table}/{sys_id}", json_body=payload)
        return result.get("result", {})
