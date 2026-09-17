from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests


class ServiceNowClient:
    def __init__(self, settings: Any):
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
        self._set_access_token(self.settings.oauth_access_token)
        if not self.settings.oauth_access_token:
            self._refresh_access_token()

    def _set_access_token(self, access_token: str) -> None:
        if access_token:
            self.session.headers["Authorization"] = f"Bearer {access_token}"

    def _refresh_access_token(self) -> None:
        response = requests.post(
            f"{self.instance_url}/oauth_token.do",
            data={
                "grant_type": "refresh_token",
                "client_id": self.settings.oauth_client_id,
                "client_secret": self.settings.oauth_client_secret,
                "refresh_token": self.settings.oauth_refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )

        if response.status_code >= 400:
            try:
                error_body = response.json()
            except ValueError:
                error_body = {"message": response.text}
            raise RuntimeError(
                f"ServiceNow OAuth token request failed: {response.status_code} - {error_body}"
            )

        try:
            access_token = response.json().get("access_token", "")
        except ValueError as exc:
            raise RuntimeError("ServiceNow OAuth token response was not JSON") from exc

        if not access_token:
            raise RuntimeError("ServiceNow OAuth response did not include an access_token")
        self._set_access_token(access_token)

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            timeout=30,
        )

        if response.status_code >= 400:
            try:
                error_body = response.json()
            except ValueError:
                error_body = {"message": response.text}

            raise RuntimeError(
                f"ServiceNow request failed: {response.status_code} - {error_body}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"ServiceNow returned non-JSON payload: {response.text}") from exc

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
