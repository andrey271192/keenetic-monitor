import asyncio
import httpx
import urllib.parse
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KeeneticClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/')

        if self.base_url.endswith('/dashboard'):
            self.base_url = self.base_url[:-10]
        elif self.base_url.endswith('/login'):
            self.base_url = self.base_url[:-6]

        self.username = username
        self.password = password

        self.client = httpx.AsyncClient(timeout=30)

        parsed = urllib.parse.urlparse(self.base_url)
        self.host = parsed.hostname

        # SNMP настройки
        self.snmp_community = "public"
        self.use_snmp = True  # 🔥 авто-режим

        logger.info(f"Init {self.host} (SNMP auto)")

    # ========= CHECK =========
    async def check_connection(self):
        try:
            resp = await self.client.get(self.base_url, timeout=10)
            return resp.status_code in [200, 401, 403]
        except Exception as e:
            logger.error(f"HTTP ошибка {self.host}: {e}")
            return False

    # ========= SNMP =========
    async def get_wireguard_status(self):
        if not self.use_snmp:
            return []

        try:
            # быстрый тест SNMP (1 интерфейс)
            test_cmd = [
                'snmpget',
                '-v2c',
                '-c', self.snmp_community,
                '-t', '1',
                '-r', '0',
                self.host,
                '1.3.6.1.2.1.1.1.0'
            ]

            test_proc = await asyncio.create_subprocess_exec(
                *test_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await test_proc.communicate()

            if test_proc.returncode != 0:
                logger.warning(f"SNMP недоступен на {self.host}")
                return []

        except Exception as e:
            logger.warning(f"SNMP check fail {self.host}: {e}")
            return []

        # ---------- основной SNMP ----------
        wireguard_ifaces = []

        try:
            cmd = [
                'snmpwalk',
                '-v2c',
                '-c', self.snmp_community,
                '-t', '2',
                '-r', '1',
                self.host,
                '1.3.6.1.2.1.2.2.1.2'
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"snmpwalk error {self.host}")
                return []

            lines = stdout.decode().split('\n')

            iface_pattern = r'\.(\d+)\s*=\s*STRING:\s*"(.+)"'

            for line in lines:
                match = re.search(iface_pattern, line)
                if match:
                    if_idx = match.group(1)
                    if_name = match.group(2)

                    if "Wireguard" in if_name:
                        status_cmd = [
                            'snmpget',
                            '-v2c',
                            '-c', self.snmp_community,
                            self.host,
                            f'1.3.6.1.2.1.2.2.1.8.{if_idx}'
                        ]

                        status_proc = await asyncio.create_subprocess_exec(
                            *status_cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )

                        s_out, _ = await status_proc.communicate()

                        status = 1
                        match_status = re.search(r'INTEGER:\s*(\d+)', s_out.decode())
                        if match_status:
                            status = int(match_status.group(1))

                        wireguard_ifaces.append({
                            "name": if_name,
                            "up": status == 1
                        })

            if wireguard_ifaces:
                logger.info(f"{self.host} WG: {len(wireguard_ifaces)}")

        except Exception as e:
            logger.error(f"SNMP error {self.host}: {e}")

        return wireguard_ifaces

    # ========= CLOSE =========
    async def close(self):
        await self.client.aclose()
