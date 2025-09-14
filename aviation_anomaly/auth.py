"""Authentication for OpenSky Trino access."""

import json
import os
import sys
import time
from pathlib import Path
from typing import NamedTuple

import requests


class Credentials(NamedTuple):
    """Username and password credentials."""
    username: str
    password: str


class TokenManager:
    """Manages JWT token caching and refresh for OpenSky."""
    
    TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    CLIENT_ID = "trino-client"
    
    def __init__(self, cache_file: Path | None = None):
        """Initialize token manager.
        
        Args:
            cache_file: Path to token cache file (defaults to .opensky_tokens.json in cwd)
        """
        if cache_file is None:
            cache_file = Path.cwd() / ".opensky_tokens.json"
        
        self.cache_file = cache_file
    
    def get_valid_token(self) -> str | None:
        """Get cached token if valid, refreshing if needed.
        
        Returns:
            Access token or None if not available/expired
        """
        tokens = self._load_cached_tokens()
        if not tokens:
            return None
        
        # Check if token is still valid (with 5 minute buffer)
        expires_at = tokens.get("expires_at", 0)
        if time.time() < (expires_at - 300):
            return tokens["access_token"]
        
        # Try to refresh if we have a refresh token
        refresh_token = tokens.get("refresh_token")
        if refresh_token and time.time() < expires_at:
            new_tokens = self._refresh_token(refresh_token)
            if new_tokens:
                self._cache_tokens(new_tokens)
                return new_tokens["access_token"]
        
        return None
    
    def authenticate(self, credentials: Credentials) -> str:
        """Authenticate with username/password.
        
        Args:
            credentials: Username and password
            
        Returns:
            Access token
            
        Raises:
            RuntimeError: If authentication fails
        """
        data = {
            "grant_type": "password",
            "username": credentials.username,
            "password": credentials.password,
            "client_id": self.CLIENT_ID,
        }
        
        response = requests.post(self.TOKEN_URL, data=data)
        
        if response.status_code != 200:
            raise RuntimeError(f"Authentication failed: {response.status_code}")
        
        tokens = response.json()
        self._cache_tokens(tokens)
        return tokens["access_token"]
    
    def _refresh_token(self, refresh_token: str) -> dict | None:
        """Refresh an expired access token.
        
        Args:
            refresh_token: OAuth refresh token
            
        Returns:
            New token response or None if refresh fails
        """
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.CLIENT_ID,
        }
        
        try:
            response = requests.post(self.TOKEN_URL, data=data)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        
        return None
    
    def _load_cached_tokens(self) -> dict | None:
        """Load tokens from cache file.
        
        Returns:
            Token dictionary or None if not cached
        """
        if not self.cache_file.exists():
            return None
        
        try:
            with open(self.cache_file) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    
    def _cache_tokens(self, tokens: dict) -> None:
        """Cache tokens to file with proper permissions.
        
        Args:
            tokens: Token response from OAuth endpoint
        """
        cache_data = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": time.time() + tokens.get("expires_in", 3600)
        }
        
        # Write with restricted permissions
        temp_file = self.cache_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(cache_data, f, indent=2)
        
        # Set restrictive permissions (owner read/write only)
        os.chmod(temp_file, 0o600)
        
        # Atomic rename
        temp_file.rename(self.cache_file)


class CredentialProvider:
    """Provides credentials from environment or prompts."""
    
    def get_credentials(self) -> Credentials:
        """Get credentials from environment or prompt.
        
        Returns:
            Username and password
            
        Raises:
            RuntimeError: In CI mode if credentials not in environment
        """
        # Check if we're in CI/non-interactive mode
        is_ci = (
            os.environ.get("CI") == "true" or
            os.environ.get("GITHUB_ACTIONS") == "true" or
            not sys.stdin.isatty()
        )
        
        # Try environment variables first
        username = os.environ.get("OPENSKY_USERNAME")
        password = os.environ.get("OPENSKY_PASSWORD")
        
        if username and password:
            return Credentials(username, password)
        
        # In CI mode, fail if no environment variables
        if is_ci:
            raise RuntimeError(
                "OpenSky credentials required in CI/non-interactive mode.\n"
                "Set OPENSKY_USERNAME and OPENSKY_PASSWORD environment variables."
            )
        
        # Interactive mode: prompt for missing credentials
        if not username:
            username = input("OpenSky username: ")
        
        if not password:
            import getpass
            password = getpass.getpass("OpenSky password: ")
        
        return Credentials(username, password)


def get_opensky_token() -> str:
    """Get authenticated OpenSky access token.
    
    This is the main entry point for authentication. It handles:
    - Token caching and refresh
    - Credential discovery (env vars or prompts)
    - CI/CD vs interactive mode detection
    
    Returns:
        Valid JWT access token
        
    Raises:
        RuntimeError: If authentication fails
    """
    token_manager = TokenManager()
    
    # Try cached token first
    token = token_manager.get_valid_token()
    if token:
        return token
    
    # Need fresh authentication
    credential_provider = CredentialProvider()
    credentials = credential_provider.get_credentials()
    
    return token_manager.authenticate(credentials)