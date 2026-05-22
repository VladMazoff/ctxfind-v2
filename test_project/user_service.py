"""Test module for ctxfind-v2 integration test."""

from typing import Dict, List, Optional

class User:
    """User model."""

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def validate(self) -> bool:
        return bool(self.name) and "@" in self.email

class UserService:
    """Service for user operations."""

    def __init__(self):
        self.users: List[User] = []

    def create_user(self, data: Dict) -> User:
        user = User(name=data["name"], email=data["email"])
        if user.validate():
            self.users.append(user)
        return user

    def find_user(self, email: str) -> Optional[User]:
        for user in self.users:
            if user.email == email:
                return user
        return None

    def process_user(self, data: Dict) -> User:
        """Process incoming user data and return validated User instance."""
        return self.create_user(data)

def handle_user_request(data: Dict) -> User:
    service = UserService()
    return service.process_user(data)

# Some usage
user = User("test", "test@example.com")
