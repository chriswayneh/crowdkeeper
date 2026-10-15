from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class User:
    name: str
    display_name: str = ""
    email: str = ""
    active: bool = True
    last_login: Optional[datetime] = None
    groups: list = field(default_factory=list)
    created: Optional[datetime] = None  # account creation time, if known
