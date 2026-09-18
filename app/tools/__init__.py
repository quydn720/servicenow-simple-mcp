from typing import Callable

from app.service_now_client import ServiceNowClient

ClientFactory = Callable[[], ServiceNowClient]
