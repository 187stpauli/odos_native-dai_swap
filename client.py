from web3.exceptions import TransactionNotFound
from web3 import AsyncWeb3, AsyncHTTPProvider
from typing import Optional, Union
from web3.contract import AsyncContract
from web3.types import TxParams
from hexbytes import HexBytes
from termcolor import cprint
import asyncio


class Client:
    def __init__(self, from_address: str, to_address: str, chain_id: int, rpc_url: str, private_key: str,
                 amount: float, router_address: str, explorer_url: str, proxy: Optional[str] = None):
        request_kwargs = {"proxy": f"http://{proxy}"} if proxy else {}
        self.router_address = router_address
        self.from_address = from_address
        self.explorer_url = explorer_url
        self.private_key = private_key
        self.to_address = to_address
        self.chain_id = chain_id
        self.amount = amount
        self.proxy = proxy
        self.w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url, request_kwargs=request_kwargs))
        self.eip_1559 = True
        self.address = self.w3.to_checksum_address(
            self.w3.eth.account.from_key(self.private_key).address)

    # Получение баланса нативного токена
    async def get_native_balance(self) -> float:
        """Получает баланс нативного токена в ETH/BNB/MATIC и т.д."""
        balance_wei = await self.w3.eth.get_balance(self.address)
        balance_eth = self.w3.from_wei(balance_wei, "ether")
        return balance_eth

    # Получение баланса ERC20
    async def get_erc20_balance(self) -> float | int:
        # ABI для balanceOf
        erc20_abi = [
            {
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        contract = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.from_address), abi=erc20_abi)

        balance = await contract.functions.balanceOf(self.address).call()

        return balance

    # Создание объекта контракт для дальнейшего обращения к нему
    async def get_contract(self, contract_address: str, abi: list) -> AsyncContract:
        return self.w3.eth.contract(
            address=self.w3.to_checksum_address(contract_address), abi=abi
        )

    # Получение суммы газа за транзакцию
    async def get_tx_fee(self) -> int:
        fee_history = await self.w3.eth.fee_history(10, "latest", [50])
        base_fee = fee_history['baseFeePerGas'][-1]
        max_priority_fee = await self.w3.eth.max_priority_fee
        estimated_gas = 70_000
        max_fee_per_gas = (base_fee + max_priority_fee) * estimated_gas

        return max_fee_per_gas

    # Преобразование в веи
    def to_wei_main(self, number: int | float, decimals: int):
        unit_name = {
            6: "mwei",
            9: "gwei",
            18: "ether"
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f"Невозможно найти имя юнита с децималами: {decimals}")
        return self.w3.to_wei(number, unit_name)

    # Преобразование из веи
    def from_wei_main(self, number: int | float, decimals: int):
        unit_name = {
            6: "mwei",
            9: "gwei",
            18: "ether"
        }.get(decimals)

        if not unit_name:
            raise RuntimeError(f"Невозможно найти имя юнита с децималами: {decimals}")
        return self.w3.from_wei(number, unit_name)

    # Подготовка транзакции
    async def prepare_tx(self, value: Union[int, float] = 0) -> TxParams:
        transaction: TxParams = {
            "chainId": await self.w3.eth.chain_id,
            "nonce": await self.w3.eth.get_transaction_count(self.address),
            "from": self.address,
            "value": self.w3.to_wei(value, "ether"),
        }

        if self.eip_1559:
            base_fee = await self.w3.eth.gas_price
            max_priority_fee_per_gas = await self.w3.eth.max_priority_fee or base_fee
            max_fee_per_gas = int(base_fee * 1.25 + max_priority_fee_per_gas)

            transaction.update({
                "maxPriorityFeePerGas": max_priority_fee_per_gas,
                "maxFeePerGas": max_fee_per_gas,
                "type": "0x2",
            })
        else:
            transaction["gasPrice"] = int((await self.w3.eth.gas_price) * 1.25)

        return transaction

    # Подпись и отправка транзакции
    async def sign_and_send_tx(self, transaction: TxParams, without_gas: bool = False):
        if not without_gas:
            transaction["gas"] = int((await self.w3.eth.estimate_gas(transaction)) * 1.5)

        signed_raw_tx = self.w3.eth.account.sign_transaction(transaction, self.private_key).rawTransaction
        cprint("✅ Транзакция успешно подписана!\n", "light_green")

        tx_hash_bytes = await self.w3.eth.send_raw_transaction(signed_raw_tx)
        tx_hash_hex = self.w3.to_hex(tx_hash_bytes)
        cprint("✅ Транзакция успешно отправлена!\n", "light_green")

        return await self.wait_tx(tx_hash_hex)

    # Ожидание результата транзакции
    async def wait_tx(self, tx_hash: Union[str, HexBytes], explorer_url: Optional[str] = None) -> bool:
        total_time = 0
        timeout = 120
        poll_latency = 10

        tx_hash_bytes = HexBytes(tx_hash)  # Приведение к HexBytes

        while True:
            try:
                receipt = await self.w3.eth.get_transaction_receipt(tx_hash_bytes)
                status = receipt.get("status")
                if status == 1:
                    cprint(
                        f"🎯 Транзакция прошла успешно: "
                        f"{explorer_url + 'tx/' + tx_hash_bytes.hex() if explorer_url else tx_hash_bytes.hex()}",
                        "light_green")
                    return True
                elif status is None:
                    await asyncio.sleep(poll_latency)
                else:
                    cprint(f"❌ Транзакция не выполнена: "
                           f"{explorer_url + 'tx/' + tx_hash_bytes.hex() if explorer_url else tx_hash_bytes.hex()}",
                           "light_red")
                    return False
            except TransactionNotFound:
                if total_time > timeout:
                    cprint(f"⚠️ Транзакция не попала в цепочку после {timeout} секунд", "light_yellow")
                    return False
                total_time += poll_latency
                await asyncio.sleep(poll_latency)
