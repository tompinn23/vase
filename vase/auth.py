import sys
import webbrowser
from typing import Tuple

import httpx
import asyncio
import time
import jwt
import keyring

if sys.platform == "win32":
    from keyring.backends.Windows import WinVaultKeyring
    keyring.set_keyring(WinVaultKeyring())

from vase.config import config

class AuthException(Exception):
    pass

class AsyncJWTAuth(httpx.Auth):
    def __init__(self, refresh_token: str | None = None):
        """
        token_getter: async callable returning (jwt, expiry_timestamp)
        refresh_token_func: async callable to refresh JWT, returns (jwt, expiry_timestamp)
        """
        if refresh_token is None:
            self.refresh_token = keyring.get_password("org.yonside.vase", "refresh")
        else:
            self.refresh_token = refresh_token
        self.base_url = config.get_str('api_base_url', default="https://fleets.yonside.org/")
        self.token = None
        self.expiry = 0
        self._lock = asyncio.Lock()  # prevent simultaneous refresh

    async def async_auth_flow(self, request):
        # Refresh token if missing or expired
        now = time.time()
        if self.token is None or now >= self.expiry:
            async with self._lock:
                # Double-check inside lock
                if self.token is None or time.time() >= self.expiry:
                    await self.token_refresh()

        # Attach token to request
        request.headers["Authorization"] = f"Bearer {self.token}"

        response = yield request

        # Retry once on 401 Unauthorized
        if response.status_code == 401:
            async with self._lock:
                await self.token_refresh()
            request.headers["Authorization"] = f"Bearer {self.token}"
            yield request

    async def login(self):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}v1/auth/start"
            )
            if resp.status_code != 200:
                raise AuthException("Failed to start login")
            data = resp.json()
            print(data)
            print(f"Login using the following link {data['auth_url']}")
            webbrowser.open(data["auth_url"])
            interval = data["interval"]
            poll_content = f"device_code={data['link']}"
            while True:
                resp = await client.post(
                    f"{self.base_url}v1/auth/poll",
                    content=poll_content,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                if resp.status_code != 200:
                    raise AuthException("Failed to login")
                data = resp.json()
                print(data)
                if data["status"] == "pending":
                    await asyncio.sleep(interval)
                elif data["status"] == "completed":
                    self.token = data["token"]
                    self.refresh_token = data["refresh"]
                    keyring.set_password("org.yonside.vase", "refresh", self.refresh_token)
                    payload = jwt.decode(self.token, options={"verify_signature": False, "verify_sub": False})
                    self.expiry = float(payload.get("exp"))
                    return
                else:
                    raise AuthException("Failed to login")

    async def token_refresh(self):
        if self.refresh_token is None:
            await self.login()
            return

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}v1/auth/refresh",
                headers={"Authorization": f"Bearer {self.refresh_token}"},
            )
            data = resp.json()
            if resp.status_code != 200:
                raise AuthException(f"Failed to refresh token {resp.status_code} {data.get('error')}")

            self.token = data["token"]
            self.refresh_token = data["refresh"]
            keyring.set_password("org.yonside.vase", "refresh", self.refresh_token)
            payload = jwt.decode(self.token, options={"verify_signature": False, "verify_sub": False})
            self.expiry = float(payload.get("exp"))




