from configvalidator import ConfigValidator
from typing import Dict, Any, Optional
from client import Client
import requests
import asyncio
import json


class Odos:
    def __init__(self, client: Client) -> None:
        self.client = client

    # Апрув для Odos
    async def check_and_approve(self) -> None:
        try:
            max_uint256 = 2 ** 256 - 1
            with open("erc20_abi.json") as f:
                erc20_abi = json.load(f)

            contract = await self.client.get_contract(
                contract_address=self.client.from_address, abi=erc20_abi
            )

            allowance = await contract.functions.allowance(
                self.client.address,
                self.client.router_address
            ).call()

            if allowance == 0:
                print("⚠️ Нет апрува! Отправляем approve транзакцию...")

                tx = await contract.functions.approve(
                    self.client.router_address,
                    max_uint256
                ).build_transaction({
                    "from": self.client.address,
                    "nonce": await self.client.w3.eth.get_transaction_count(self.client.address),
                    "gas": 60000,
                    "gasPrice": await self.client.w3.eth.gas_price,
                    "chainId": await self.client.w3.eth.chain_id
                })

                signed_tx = self.client.w3.eth.account.sign_transaction(tx, self.client.private_key)
                tx_hash = await self.client.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                print(f"🚀 Отправлена транзакция approve: {tx_hash.hex()}")
                receipt = await self.client.w3.eth.wait_for_transaction_receipt(tx_hash)
                print(f"✅ Approve подтвержден: {receipt.transactionHash.hex()}\n")
            else:
                print("✅ Approve уже есть, всё ок!\n")
        except Exception as e:
            print(f"❌ Ошибка при approve: {e}")
            exit(1)

    # Врап нативного токена
    async def wrap_native(self) -> None:
        try:
            wrap_abi = [
                {
                    "inputs": [],
                    "name": "deposit",
                    "outputs": [],
                    "stateMutability": "payable",
                    "type": "function"
                }
            ]
            address = self.client.address
            amount = self.client.to_wei_main(self.client.amount, 18)

            balance = await self.client.w3.eth.get_balance(address)
            gas_cost = await self.client.get_tx_fee()
            total_needed = amount + gas_cost
            if balance < total_needed:
                print(
                    f"❌ Недостаточно средств для врапа. Баланс: {self.client.from_wei_main(balance, 18)} ETH, "
                    f"требуется: {self.client.from_wei_main(total_needed, 18)} ETH (с учётом газа)."
                )
                exit(1)

            weth = await self.client.get_contract(contract_address=self.client.from_address, abi=wrap_abi)

            tx = await weth.functions.deposit().build_transaction({
                "from": address,
                "value": amount,
                "nonce": await self.client.w3.eth.get_transaction_count(address),
                "gas": 100000,
                "gasPrice": await self.client.w3.eth.gas_price,
                "chainId": await self.client.w3.eth.chain_id
            })

            signed_tx = self.client.w3.eth.account.sign_transaction(tx, private_key=self.client.private_key)
            tx_hash = await self.client.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            print(f"🚀 Отправлена транзакция на врап: {tx_hash.hex()}\n")
            receipt = await self.client.w3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"✅ Транзакция на врап подтверждена: {receipt.transactionHash.hex()}\n")
        except Exception as e:
            print(f"❌ Ошибка при врапе токена: {e}")
            exit(1)

    # Получение quote через Odos API
    async def get_quote(self) -> Dict[str, Any]:
        try:
            url = "https://api.odos.xyz/sor/quote/v2"
            amount = self.client.amount
            params = {
                "chainId": self.client.chain_id,
                "inputTokens": [
                    {
                        "tokenAddress": str(self.client.from_address),
                        "amount": str(self.client.to_wei_main(amount, 18)),
                    }
                ],
                "outputTokens": [
                    {
                        "tokenAddress": f"{self.client.to_address}",
                        "proportion": 1
                    }
                ],
                "slippageLimitPercent": 0.5,
                "userAddr": self.client.address
            }

            proxies = {
                "http": f"http://{self.client.proxy}",
                "https": f"http://{self.client.proxy}"
            }

            try:
                response = requests.post(url, json=params, proxies=proxies, timeout=15)
                response.raise_for_status()
            except requests.exceptions.Timeout:
                print("⏱️ Превышено время ожидания ответа от Odos API.")
                exit(1)
            except requests.exceptions.RequestException as e:
                print(f"❌ Ошибка при обращении к Odos API: {e}")
                exit(1)
            return response.json()

        except requests.RequestException as e:
            print(f"❌ Ошибка получения котировки: {e}")
            exit(1)

    # Построение calldata через assemble
    async def assemble(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        try:
            assemble_url = "https://api.odos.xyz/sor/assemble"
            assemble_request_body = {
                "pathId": quote["pathId"],
                "userAddr": str(self.client.address)
            }

            proxies = {
                "http": f"http://{self.client.proxy}",
                "https": f"http://{self.client.proxy}"
            }
            try:
                response = requests.post(
                    assemble_url,
                    headers={"Content-Type": "application/json"},
                    json=assemble_request_body,
                    proxies=proxies,
                    timeout=15
                )

                response.raise_for_status()
            except requests.exceptions.Timeout:
                print("⏱️ Превышено время ожидания ответа от Odos API.")
                exit(1)
            except requests.exceptions.RequestException as e:
                print(f"❌ Ошибка при обращении к Odos API: {e}")
                exit(1)
            return response.json()

        except requests.RequestException as e:
            print(f"❌ Ошибка сборки транзакции: {e}")
            exit(1)

    # Отправка транзакции на свап
    async def swap(self, build_data: Dict[str, Any]) -> Optional[str]:
        try:
            amount = self.client.to_wei_main(self.client.amount, 18)

            balance = await self.client.get_erc20_balance()
            gas_cost = await self.client.get_tx_fee()
            total_needed = amount + gas_cost
            if balance < total_needed:
                print(
                    f"❌ Недостаточно средств для свапа. Баланс: {self.client.from_wei_main(balance, 18)} ETH, "
                    f"требуется: {self.client.from_wei_main(total_needed, 18)} ETH (с учётом газа)."
                )
                exit(1)

            tx_data = build_data["transaction"]

            tx = {
                "to": tx_data["to"],
                "from": tx_data["from"],
                "value": 0,
                "data": tx_data["data"],
                "chainId": tx_data["chainId"],
                "gas": tx_data["gas"],
                "gasPrice": tx_data["gasPrice"],
                "nonce": tx_data["nonce"],
            }

            signed_tx = self.client.w3.eth.account.sign_transaction(tx, self.client.private_key)
            print("✅ Транзакция успешно подписана!\n")
            tx_hash = await self.client.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            print("✅ Транзакция успешно отправлена!\n")
            return tx_hash.hex()
        except Exception as e:
            print(f"❌ Ошибка при отправке транзакции: {e}")
            exit(1)

    # Функция сборки для выполнения всех модулей
    async def execute(self) -> None:
        await self.check_and_approve()
        await self.wrap_native()
        await asyncio.sleep(0.5)
        quote = await self.get_quote()
        await asyncio.sleep(0.5)
        build_data = await self.assemble(quote)
        await asyncio.sleep(0.5)
        tx_hash = await self.swap(build_data)
        if tx_hash:
            print(f"🔁 Ожидание подтверждения транзакции: {tx_hash}\n")
            await asyncio.sleep(0.5)
            await self.client.wait_tx(tx_hash, self.client.explorer_url)


# Подгрузка всех параметров
async def load_data(network_: str) -> Dict[str, Any]:
    try:
        with open("networks_data.json", "r", encoding="utf-8") as file:
            networks_data = json.load(file)
        return networks_data[network_]
    except FileNotFoundError:
        print(f"⚠️ Файл 'networks_data.json' не найден!")
        exit(1)
    except json.JSONDecodeError:
        print("❌ Ошибка: Некорректный формат JSON в файле 'networks_data.json'.")
        exit(1)
    except KeyError:
        print(f"❌ Сеть '{network_}' не найдена в 'networks_data.json'.")
        exit(1)


# Основная функция
async def main() -> None:
    print(f"⚡️ Запуск скрипта...\n")
    await asyncio.sleep(1)

    print(f"🛠️ Импорт параметров...\n")
    validator = ConfigValidator("settings.json")
    settings = await validator.validate_config()
    network = settings["network"]
    network_data = await load_data(network)

    print(f"🛠️ Инициализация клиента...\n")
    w3_client = Client(
        router_address=network_data["router_address"],
        from_address=network_data["from_address"],
        explorer_url=network_data["explorer_url"],
        to_address=network_data["to_address"],
        private_key=settings["private_key"],
        chain_id=network_data["chain_id"],
        rpc_url=network_data["rpc_url"],
        amount=settings["amount"],
        proxy=settings["proxy"],
    )
    odos_client = Odos(w3_client)

    print(f"🛠️ Подготовка свапа...\n")
    await odos_client.execute()


if __name__ == "__main__":
    asyncio.run(main())
