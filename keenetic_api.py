import hashlib
import logging

import httpx

logger = logging.getLogger("keenetic-api")


class KeeneticClient:
    def __init__(self, url: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.client = httpx.AsyncClient(timeout=10, verify=False)

    async def check_connection(self) -> bool:
        try:
            r = await self.client.get(self.url + "/auth")
            if r.status_code == 200:
                return True
            if r.status_code == 401:
                realm = r.headers.get("X-NDM-Realm", "")
                challenge = r.headers.get("X-NDM-Challenge", "")
                if realm and challenge:
                    md5 = hashlib.md5(
                        (self.user + ":" + realm + ":" + self.password).encode()
                    ).hexdigest()
                    sha = hashlib.sha256(
                        (challenge + md5).encode()
                    ).hexdigest()
                    r2 = await self.client.post(
                        self.url + "/auth",
                        json={"login": self.user, "password": sha}
                    )
                    return r2.status_code == 200
            return False
        except Exception as e:
            logger.debug(f"Connection check failed for {self.url}: {e}")
            return False

    async def close(self):
        await self.client.aclose()
