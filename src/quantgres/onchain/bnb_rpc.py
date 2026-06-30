import json
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

OFFICIAL_BNB_RPC_URL = "https://bsc-dataseed.bnbchain.org"
DEFAULT_BNB_RPC_URL = "https://bsc-mainnet.public.blastapi.io"
BNB_CHAIN_ID = 56


class JsonRpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BnbRpcInfo:
    rpc_url: str
    chain_id: int
    latest_block_number: int


@dataclass(frozen=True)
class BnbRawLog:
    chain_id: int
    rpc_url: str
    address: str
    block_number: int
    block_hash: str
    transaction_hash: str
    transaction_index: int
    log_index: int
    data: str
    topics: tuple[str, ...]
    raw_log: dict[str, Any]
    from_block: int
    to_block: int


def hex_to_int(value: str) -> int:
    if not value.startswith("0x"):
        raise ValueError(f"Expected hex quantity, got {value!r}.")
    return int(value, 16)


def int_to_hex(value: int) -> str:
    if value < 0:
        raise ValueError("Block numbers must be non-negative.")
    return hex(value)


def parse_block_arg(value: str) -> int:
    if value.startswith("0x"):
        return hex_to_int(value)
    parsed = int(value)
    if parsed < 0:
        raise ValueError("Block numbers must be non-negative.")
    return parsed


def call_rpc(
    *,
    rpc_url: str,
    method: str,
    params: list[Any],
    timeout_seconds: float = 15,
) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    request = Request(
        rpc_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Quantgres/0.1",
        },
        method="POST",
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    if not isinstance(body, dict):
        raise TypeError("Expected JSON-RPC response object.")

    error = body.get("error")
    if isinstance(error, dict):
        code = int(error.get("code", 0))
        message = str(error.get("message", "unknown JSON-RPC error"))
        raise JsonRpcError(code, message)

    if "result" not in body:
        raise RuntimeError("JSON-RPC response did not include result.")

    return body["result"]


def load_bnb_rpc_info(
    *,
    rpc_url: str = DEFAULT_BNB_RPC_URL,
) -> BnbRpcInfo:
    chain_id = hex_to_int(str(call_rpc(rpc_url=rpc_url, method="eth_chainId", params=[])))
    latest_block_number = hex_to_int(
        str(call_rpc(rpc_url=rpc_url, method="eth_blockNumber", params=[]))
    )
    return BnbRpcInfo(
        rpc_url=rpc_url,
        chain_id=chain_id,
        latest_block_number=latest_block_number,
    )


def normalize_log(
    *,
    raw_log: dict[str, Any],
    chain_id: int,
    rpc_url: str,
    from_block: int,
    to_block: int,
) -> BnbRawLog:
    topics = raw_log.get("topics")
    if not isinstance(topics, list) or not all(isinstance(topic, str) for topic in topics):
        raise TypeError("Expected log topics to be a list of strings.")

    return BnbRawLog(
        chain_id=chain_id,
        rpc_url=rpc_url,
        address=str(raw_log["address"]).lower(),
        block_number=hex_to_int(str(raw_log["blockNumber"])),
        block_hash=str(raw_log["blockHash"]),
        transaction_hash=str(raw_log["transactionHash"]),
        transaction_index=hex_to_int(str(raw_log["transactionIndex"])),
        log_index=hex_to_int(str(raw_log["logIndex"])),
        data=str(raw_log["data"]),
        topics=tuple(topics),
        raw_log=raw_log,
        from_block=from_block,
        to_block=to_block,
    )


def get_logs(
    *,
    rpc_url: str,
    chain_id: int,
    from_block: int,
    to_block: int,
    address: str | None = None,
    topic0: str | None = None,
) -> tuple[BnbRawLog, ...]:
    if to_block < from_block:
        raise ValueError("to_block must be greater than or equal to from_block.")

    log_filter: dict[str, Any] = {
        "fromBlock": int_to_hex(from_block),
        "toBlock": int_to_hex(to_block),
    }
    if address is not None:
        log_filter["address"] = address
    if topic0 is not None:
        log_filter["topics"] = [topic0]

    result = call_rpc(rpc_url=rpc_url, method="eth_getLogs", params=[log_filter])
    if not isinstance(result, list):
        raise TypeError("Expected eth_getLogs result to be a list.")

    logs: list[BnbRawLog] = []
    for row in result:
        if not isinstance(row, dict):
            raise TypeError("Expected every log row to be an object.")
        logs.append(
            normalize_log(
                raw_log=row,
                chain_id=chain_id,
                rpc_url=rpc_url,
                from_block=from_block,
                to_block=to_block,
            )
        )

    return tuple(logs)
