from eth_utils import decode_hex
from eth_keys import keys
import requests
import json
import re


class ConfigValidator:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config_data = self.load_config()

    def load_config(self) -> dict:
        """Загружает конфигурационный файл"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Ошибка загрузки файла конфигурации: {e}")
            exit(1)

    async def validate_config(self) -> dict:
        """Валидация всех полей конфигурации"""
        if "private_key" not in self.config_data:
            print("Ошибка: Отсутствует 'private_key' в конфигурации.")
            exit(1)

        if "network" not in self.config_data:
            print("Ошибка: Отсутствует 'network' в конфигурации.")
            exit(1)

        if "proxy" not in self.config_data:
            print("Ошибка: Отсутствует 'proxy' в конфигурации.")
            exit(1)

        if "amount" not in self.config_data:
            print("Ошибка: Отсутствует 'amount' в конфигурации.")
            exit(1)

        await self.validate_private_key(self.config_data["private_key"])
        await self.validate_network(self.config_data["network"])
        await self.validate_amount(self.config_data["amount"])
        await self.validate_proxy(self.config_data["proxy"])

        return self.config_data

    @staticmethod
    async def validate_private_key(private_key: str) -> None:
        """Валидация приватного ключа"""
        try:
            private_key_bytes = decode_hex(private_key)
            _ = keys.PrivateKey(private_key_bytes)
        except (ValueError, Exception):
            print("Ошибка: Некорректный 'private_key' в конфигурации.")
            exit(1)

    @staticmethod
    async def validate_network(network: str) -> None:
        """Валидация названия сети"""
        networks = [
            "Ethereum",
            "Optimism",
            "BNB",
            "Polygon",
            "Fantom",
            "Fraxtal",
            "zkSync Era",
            "Mantle",
            "Base",
            "Arbitrum",
            "Linea",
            "Scroll",
        ]
        if network not in networks:
            print(
                "Ошибка: Неподдерживаемая сеть! Введите одну из поддерживаемых сетей."
            )
            exit(1)

    @staticmethod
    async def validate_proxy(proxy: str) -> None:
        """Валидация прокси-адреса"""
        pattern = (
            r"^(?P<login>[^:@]+):(?P<password>[^:@]+)@(?P<host>[\w.-]+):(?P<port>\d+)$"
        )
        match = re.match(pattern, proxy)
        if not match:
            print("Ошибка: Неверный формат прокси! Должен быть 'login:pass@host:port'.")
            exit(1)

        proxy_url = {"http": f"http://{proxy}"}
        response = requests.get("https://httpbin.org/ip", proxies=proxy_url, timeout=5)
        if response.status_code != 200:
            print("Ошибка: 'proxy' нерабочий или вернул неверный статус-код!")
            exit(1)

    @staticmethod
    async def validate_amount(amount: str) -> None:
        """Валидация количества токенов"""
        try:
            _ = float(amount)
        except ValueError:
            print("Ошибка количества токенов! Введите число.")
            exit(1)
