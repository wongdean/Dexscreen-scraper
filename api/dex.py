import asyncio
import base64
import os
from curl_cffi.requests import AsyncSession
import json
import nest_asyncio
from datetime import datetime
import time
import struct
from decimal import Decimal, ROUND_DOWN
import re
import requests
import websockets

# Apply nest_asyncio
nest_asyncio.apply()

Api = "TG bot API here"
ID = "Channel ID"

class DexBot():
    def __init__(self, api_key, url, channel_id=ID, max_token=10):
        self.api_key = api_key
        self.channel_id = channel_id
        self.max_token = max_token
        self.url = url
        

    def generate_sec_websocket_key(self):
        random_bytes = os.urandom(16)
        key = base64.b64encode(random_bytes).decode('utf-8')
        return key

    def get_headers(self):
        headers = {
            "Host": "io.dexscreener.com",
            "Connection": "Upgrade",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Upgrade": "websocket",
            "Origin": "https://dexscreener.com",
            "Referer": "https://dexscreener.com/",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "websocket",
            "Sec-Fetch-Mode": "websocket",
            "Sec-Fetch-Site": "same-site",
            'Sec-WebSocket-Version': '13',
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Sec-WebSocket-Key": self.generate_sec_websocket_key()
        }
        return headers

    def candidate_ws_urls(self):
        # Try original endpoint first, then fallback between v5/v4.
        urls = [self.url]
        if "/v5/" in self.url:
            urls.append(self.url.replace("/v5/", "/v4/"))
        elif "/v4/" in self.url:
            urls.append(self.url.replace("/v4/", "/v5/"))
        # Keep order but drop duplicates.
        return list(dict.fromkeys(urls))

    def format_token_data(self):

        """
        Fetch information about specific tokens from the Dexscreener API.

        Args:
            token_addresses (list): List of token addresses.

        Returns:
            dict: A dictionary containing data for each token address or an error message.
        """

        token_addresses = self.start()
        if not token_addresses:
            return json.dumps(
                {
                    "data": [],
                    "error": "No token addresses extracted. WebSocket may be blocked (403) or returned no pairs."
                },
                indent=2
            )

        base_url = "https://api.dexscreener.com/latest/dex/tokens/"
        results = {}

        for address in token_addresses:
            try:
                # Make an API call for each token address
                response = requests.get(f"{base_url}{address}")
                if response.status_code == 200:
                    data = response.json()
                    # Store the relevant data for the token address
                    pairs = data.get('pairs', [])  # 'pairs' contains token market data
                    
                    if pairs and len(pairs) > 0:
                        results[address] = pairs[0]  # Store first pair's data
                    else:
                        results[address] = {"pairAddress": address,
                                            "Error": "No data Retrieved"}
                else:
                    # Handle HTTP errors
                    results[address] = f"Error: Status code {response.status_code}"
            except requests.RequestException as e:
                # Handle request exceptions
                results[address] = f"Error making request: {str(e)}"

        # Extracting values as a list
        results = list(results.values())
        # Output the result as JSON

        return json.dumps({"data": results}, indent=2)
      

    async def connect_with_websockets(self, ws_url, headers):
        # `websockets` handles compressed websocket frames better than
        # curl-cffi's ws parser for this endpoint.
        ws_headers = {
            "Origin": headers["Origin"],
            "Referer": headers["Referer"],
            "User-Agent": headers["User-Agent"],
            "Pragma": headers["Pragma"],
            "Cache-Control": headers["Cache-Control"],
            "Accept-Language": headers["Accept-Language"],
        }

        async with websockets.connect(
            ws_url,
            additional_headers=ws_headers,
            open_timeout=20,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        ) as ws:
            while True:
                data = await ws.recv()
                if not data:
                    return None
                if "pairs" in str(data):
                    return data

    async def connect(self):
        # Rotate impersonation and endpoint version because Dexscreener can 403
        # specific fingerprints or websocket paths.
        impersonations = ("chrome124", "chrome120", "safari17_0")
        urls = self.candidate_ws_urls()
        last_error = "Unknown websocket error"

        for ws_url in urls:
            for impersonate_name in impersonations:
                headers = self.get_headers()
                session = AsyncSession(headers=headers, impersonate=impersonate_name)
                ws = None
                try:
                    # Warm up origin and websocket host to gather cookies.
                    await session.get("https://dexscreener.com/")
                    await session.get("https://io.dexscreener.com/")

                    # Primary path: use websockets client for receiving frames.
                    # curl-cffi may fail on reserved bits for compressed frames.
                    try:
                        data = await self.connect_with_websockets(ws_url, headers)
                        if data is not None:
                            print(f"Connected via websockets ({impersonate_name} warmup): {ws_url}")
                            return data
                    except Exception as ws_e:
                        print(f"websockets client failed [{impersonate_name}] {ws_url}: {ws_e}")

                    # Fallback path: curl-cffi websocket client.
                    ws = await session.ws_connect(ws_url)
                    print(f"Connected via curl-cffi {impersonate_name}: {ws_url}")

                    while True:
                        data = await ws.recv()
                        if not data:
                            print("No data received.")
                            break

                        response = data
                        if isinstance(response, (list, tuple)) and response:
                            response = response[0]

                        if "pairs" in str(response):
                            return response
                except Exception as e:
                    last_error = str(e)
                    print(f"Connection attempt failed [{impersonate_name}] {ws_url}: {last_error}")
                finally:
                    try:
                        if ws is not None:
                            await ws.close()
                    except Exception:
                        pass
                    await session.close()

        return f"Connection error: {last_error}"


    def tg_send(self, message):
        try:
            self.bot.send_message(self.channel_id, message, parse_mode='MarkdownV2', disable_web_page_preview=True)
        except Exception as e:
            print(f"Telegram sending error: {e}")



    def start(self):
        # Run the async connection
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        mes = loop.run_until_complete(self.connect())
        loop.close()

        # Normalize websocket payload to text.
        # `ws.recv()` may yield bytes in some cases and str in others.
        if mes is None:
            return []
        if isinstance(mes, (bytes, bytearray)):
            raw_text = mes.decode("utf-8", errors="ignore")
        else:
            raw_text = str(mes)

        # Replace non-printable chars with spaces to simplify token extraction.
        decoded_text = ''.join(ch if 32 <= ord(ch) <= 126 else ' ' for ch in raw_text)

        # Split into long words
        words = [w for w in decoded_text.split() if len(w) >= 65]


        extracted_tokens = []

        for token in words:
            try:
                token_lower = token.lower()

                # Skip URLs
                if any(substr in token_lower for substr in ["https", "http", "//", ".com"]):
                    continue

                # ETH addresses
                if "0x" in token_lower:
                    eth_match = re.findall(r'0x[0-9a-fA-F]{40,}', token)
                    if eth_match:
                        extracted_tokens.append(eth_match[-1])
                        continue

                # Pump tokens
                if "pump" in token_lower:
                    pump_match = re.search(r'.{0,40}pump', token, re.IGNORECASE)
                    if pump_match:
                        extracted_tokens.append(pump_match.group(0).lstrip('V'))
                        continue

                # Bonk tokens
                if "bonk" in token_lower:
                    bonk_match = re.search(r'.{0,40}bonk', token, re.IGNORECASE)
                    if bonk_match:
                        bonk_token = bonk_match.group(0)
                        if bonk_token.startswith('V'):
                            bonk_token = bonk_token[1:]
                        extracted_tokens.append(bonk_token)
                        continue

                # Solana-like addresses (last 44 chars)
                sol_token = token[-44:]
                if sol_token.startswith('V'):
                    sol_token = sol_token[1:]
                extracted_tokens.append(sol_token)

            except Exception as e:
                print(f"Error processing token '{token}': {e}")


        print("Extraction complete")
        return extracted_tokens[:70]






    def token_getter(self, message):
        pass



